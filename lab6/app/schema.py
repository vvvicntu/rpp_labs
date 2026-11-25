import logging
import os
from datetime import datetime
from decimal import Decimal
from typing import AsyncGenerator
import strawberry
from strawberry.types import Info
from strawberry.dataloader import DataLoader
from graphql import GraphQLError
from app import db, services, events

log = logging.getLogger(__name__) # настрйока логирования
OrderStatus = strawberry.enum(db.OrderStatus) # перечисление статусов
ERROR_CODES = {services.NotFound:'NOT_FOUND', services.TransitionNotAllowed:'TRANSITION_NOT_ALLOWED', services.OrderValidationError:'VALIDATION_ERROR'}

def parse_id(value): # перобразование "айди" в айди
    try: return int(value)
    except (ValueError, TypeError):
        raise GraphQLError('Некорректный идентификатор', extensions={'code':'VALIDATION_ERROR'})

async def call(operation):
    try: return await operation
    except tuple(ERROR_CODES) as exc:
        raise GraphQLError(str(exc), extensions={'code':ERROR_CODES[type(exc)]}) from exc
    except Exception as exc:
        log.exception('Ошибка операции')
        raise GraphQLError('Internal error', extensions={'code':'INTERNAL_ERROR'}) from exc

# даталодер, где мы загружаем
async def load_restaurants(ids): # кол-во рестиков
    found = await db.get_restaurants(ids)
    return [found.get(i) for i in ids]
async def load_dishes(ids): # кол-во блюд
    found = await db.get_dishes(ids)
    return [found.get(i) for i in ids]
async def load_items(ids): # кол-во опозиций 
    found = await db.get_items_by_orders(ids)
    return [found.get(i, []) for i in ids]

async def get_context():
    return {'restaurants':DataLoader(load_fn=load_restaurants), 'dishes':DataLoader(load_fn=load_dishes),
            'items':DataLoader(load_fn=load_items), 'use_loaders':os.getenv('USE_DATALOADER','1') == '1'}

async def related(info, key, id, single):
    if info.context['use_loaders']:
        return await call(info.context[key].load(id))
    return await call(single(id))

# 4 сущности нашей предметной области
@strawberry.type #декоратор, чтобы объект питона стал объектом  графкл
class Restaurant:
    id: strawberry.ID
    name: str
    address: str
    @strawberry.field
    async def dishes(self) -> list['Dish']:
        return [to_dish(r) for r in await call(db.get_dishes_by_restaurant(int(self.id)))]

@strawberry.type
class Dish:
    id: strawberry.ID
    name: str
    price: Decimal
    restaurant_id: strawberry.Private[int]
    @strawberry.field
    async def restaurant(self, info: Info) -> Restaurant:
        return to_restaurant(await related(info,'restaurants',self.restaurant_id,db.get_restaurant))

@strawberry.type
class OrderItem:
    quantity: int
    price: Decimal
    dish_id: strawberry.Private[int]
    @strawberry.field
    def amount(self) -> Decimal: return self.price * self.quantity
    @strawberry.field
    async def dish(self, info: Info) -> Dish:
        return to_dish(await related(info,'dishes',self.dish_id,db.get_dish))

@strawberry.type
class Order:
    id: strawberry.ID
    status: OrderStatus
    total: Decimal
    created_at: datetime
    customer_name: str
    delivery_address: str
    cancel_reason: str | None
    restaurant_id: strawberry.Private[int]
    @strawberry.field
    async def restaurant(self, info: Info) -> Restaurant:
        return to_restaurant(await related(info,'restaurants',self.restaurant_id,db.get_restaurant))
    @strawberry.field
    async def items(self, info: Info) -> list[OrderItem]:
        rows = await related(info,'items',int(self.id),db.get_items)
        return [OrderItem(quantity=r.quantity, price=r.price, dish_id=r.dish_id) for r in rows]

def sid(id): return strawberry.ID(str(id))
def to_restaurant(r): return Restaurant(id=sid(r.id), name=r.name, address=r.address)
def to_dish(r): return Dish(id=sid(r.id), name=r.name, price=r.price, restaurant_id=r.restaurant_id)
def to_order(r):
    return Order(id=sid(r.id),status=db.OrderStatus(r.status),total=r.total,created_at=r.created_at,
        customer_name=r.customer_name,delivery_address=r.delivery_address,cancel_reason=r.cancel_reason,restaurant_id=r.restaurant_id)

@strawberry.input
class OrderItemInput:
    dish_id: strawberry.ID
    quantity: int
@strawberry.input
class CreateOrderInput:
    restaurant_id: strawberry.ID
    customer_name: str
    delivery_address: str
    items: list[OrderItemInput]

@strawberry.type
class Query:
    @strawberry.field
    async def order(self, id: strawberry.ID) -> Order | None:
        row = await call(db.get_order(parse_id(id)))
        return to_order(row) if row else None
    @strawberry.field
    async def orders(self, status: OrderStatus | None = None) -> list[Order]:
        return [to_order(r) for r in await call(db.list_orders(status))]
    @strawberry.field
    async def restaurants(self) -> list[Restaurant]:
        return [to_restaurant(r) for r in await call(db.list_restaurants())]

@strawberry.type
class Mutation:
    @strawberry.mutation
    async def create_order(self, input: CreateOrderInput) -> Order | None:
        return to_order(await call(services.create_order(parse_id(input.restaurant_id),input.customer_name,input.delivery_address,
            [(parse_id(i.dish_id),i.quantity) for i in input.items])))
    @strawberry.mutation
    async def accept_order(self,id: strawberry.ID) -> Order | None:
        return to_order(await call(services.accept(parse_id(id))))
    @strawberry.mutation
    async def mark_order_ready(self,id: strawberry.ID) -> Order | None:
        return to_order(await call(services.mark_ready(parse_id(id))))
    @strawberry.mutation
    async def mark_order_delivered(self,id: strawberry.ID) -> Order | None:
        return to_order(await call(services.mark_delivered(parse_id(id))))
    @strawberry.mutation
    async def cancel_order(self,id: strawberry.ID,reason: str) -> Order | None:
        return to_order(await call(services.cancel(parse_id(id),reason)))

FINAL = {db.OrderStatus.DELIVERED, db.OrderStatus.CANCELLED}
@strawberry.type
class Subscription:
    @strawberry.subscription
    async def order_status_changed(self, order_id: strawberry.ID) -> AsyncGenerator[Order,None]:
        pid = parse_id(order_id)
        queue = events.subscribe(pid)
        try:
            row = await call(db.get_order(pid))
            if row is None: raise GraphQLError(f'Заказ {pid} не найден',extensions={'code':'NOT_FOUND'})
            status = db.OrderStatus(row.status)
            yield to_order(row)
            while status not in FINAL:
                event = await queue.get()
                # Если событие уже отражено в начальном снимке, не дублируем его.
                rank = {db.OrderStatus.CREATED:0,db.OrderStatus.ACCEPTED:1,db.OrderStatus.READY:2,
                        db.OrderStatus.DELIVERED:3,db.OrderStatus.CANCELLED:3}
                if rank[event.status] <= rank[status]: continue
                status = event.status
                order = to_order(await call(db.get_order(pid)))
                order.status = status
                if status != db.OrderStatus.CANCELLED: order.cancel_reason = None
                yield order
        finally:
            events.unsubscribe(pid,queue)

schema = strawberry.Schema(query=Query,mutation=Mutation,subscription=Subscription)
