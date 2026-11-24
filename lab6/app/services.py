"""Бизнес-операции; запись заказа и позиций в одной транзакции."""
from decimal import Decimal
from sqlalchemy import select, insert, update
from app import db, events
from app.db import OrderStatus as S

class NotFound(Exception): pass
class TransitionNotAllowed(Exception): pass
class OrderValidationError(Exception): pass

TRANSITIONS = {
    'accept': ({S.CREATED}, S.ACCEPTED),
    'mark_ready': ({S.ACCEPTED}, S.READY),
    'mark_delivered': ({S.READY}, S.DELIVERED),
    'cancel': ({S.CREATED, S.ACCEPTED}, S.CANCELLED),
}

def validate_order(customer_name, delivery_address, items):
    if not customer_name.strip() or not delivery_address.strip():
        raise OrderValidationError('Имя клиента и адрес доставки обязательны')
    if not 1 <= len(items) <= 10:
        raise OrderValidationError('Заказ должен содержать от 1 до 10 позиций')
    if any(not 1 <= quantity <= 20 for _, quantity in items):
        raise OrderValidationError('Количество порций должно быть от 1 до 20')

def next_status(status, action, reason=None):
    allowed, target = TRANSITIONS[action]
    if S(status) not in allowed:
        raise TransitionNotAllowed(f'Событие {action} недопустимо в состоянии {S(status).value}')
    if action == 'cancel' and (reason is None or not 3 <= len(reason.strip()) <= 200):
        raise OrderValidationError('Причина отмены должна содержать от 3 до 200 символов')
    return target

async def create_order(restaurant_id, customer_name, delivery_address, items):
    validate_order(customer_name, delivery_address, items)
    async with db.engine.begin() as conn:
        restaurant = (await conn.execute(select(db.restaurants).where(db.restaurants.c.id == restaurant_id))).first()
        if restaurant is None: raise NotFound(f'Ресторан {restaurant_id} не найден')
        ids = [dish_id for dish_id, _ in items]
        rows = (await conn.execute(select(db.dishes).where(db.dishes.c.id.in_(ids)))).mappings().all()
        found = {r.id:r for r in rows}
        positions = []
        total = Decimal('0.00')
        for dish_id, quantity in items:
            dish = found.get(dish_id)
            if dish is None: raise NotFound(f'Блюдо {dish_id} не найдено')
            if dish.restaurant_id != restaurant_id:
                raise OrderValidationError('Все блюда должны принадлежать выбранному ресторану')
            positions.append(dict(dish_id=dish_id, quantity=quantity, price=dish.price))
            total += dish.price * quantity
        row = (await conn.execute(insert(db.orders).values(restaurant_id=restaurant_id,
            customer_name=customer_name.strip(), delivery_address=delivery_address.strip(),
            status=S.CREATED.value, total=total).returning(db.orders))).mappings().one()
        await conn.execute(insert(db.order_items), [dict(p, order_id=row.id) for p in positions])
    return row

async def transition(order_id, action, reason=None):
    async with db.engine.begin() as conn:
        # Блокировка строки исключает конфликт одновременных переходов.
        row = (await conn.execute(select(db.orders).where(db.orders.c.id == order_id).with_for_update())).mappings().first()
        if row is None: raise NotFound(f'Заказ {order_id} не найден')
        target = next_status(row.status, action, reason)
        values = {'status':target.value}
        if action == 'cancel': values['cancel_reason'] = reason.strip()
        result = (await conn.execute(update(db.orders).where(db.orders.c.id == order_id).values(**values).returning(db.orders))).mappings().one()
    events.publish(events.OrderStatusChanged(order_id, target))
    return result

async def accept(order_id): return await transition(order_id, 'accept')
async def mark_ready(order_id): return await transition(order_id, 'mark_ready')
async def mark_delivered(order_id): return await transition(order_id, 'mark_delivered')
async def cancel(order_id, reason): return await transition(order_id, 'cancel', reason)
