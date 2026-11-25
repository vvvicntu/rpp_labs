import os
from enum import Enum
from collections import defaultdict
from sqlalchemy import (MetaData, Table, Column, Integer, String, Text, Numeric,
                        DateTime, ForeignKey, CheckConstraint, select, func, event)
from sqlalchemy.ext.asyncio import create_async_engine
from contextvars import ContextVar

# enum позволяет создать перечисление как строковое значение
class OrderStatus(str, Enum):
    CREATED = 'CREATED'
    ACCEPTED = 'ACCEPTED'
    READY = 'READY'
    DELIVERED = 'DELIVERED'
    CANCELLED = 'CANCELLED'

# описание бд и создание таблиц
metadata = MetaData()
restaurants = Table('restaurants', metadata,
    Column('id', Integer, primary_key=True), Column('name', String(200), nullable=False),
    Column('address', Text, nullable=False))
dishes = Table('dishes', metadata,
    Column('id', Integer, primary_key=True),
    Column('restaurant_id', ForeignKey('restaurants.id'), nullable=False, index=True),
    Column('name', String(200), nullable=False), Column('price', Numeric(12,2), nullable=False),
    CheckConstraint('price >= 0'))
orders = Table('orders', metadata,
    Column('id', Integer, primary_key=True), Column('restaurant_id', ForeignKey('restaurants.id'), nullable=False),
    Column('customer_name', Text, nullable=False), Column('delivery_address', Text, nullable=False),
    Column('status', String(20), nullable=False, index=True), Column('cancel_reason', String(200)),
    Column('total', Numeric(14,2), nullable=False),
    Column('created_at', DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("status IN ('CREATED','ACCEPTED','READY','DELIVERED','CANCELLED')"))
order_items = Table('order_items', metadata,
    Column('id', Integer, primary_key=True), Column('order_id', ForeignKey('orders.id', ondelete='CASCADE'), nullable=False, index=True),
    Column('dish_id', ForeignKey('dishes.id'), nullable=False), Column('quantity', Integer, nullable=False),
    Column('price', Numeric(12,2), nullable=False), CheckConstraint('quantity BETWEEN 1 AND 20'))
# подключение к бд
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql+asyncpg://lab6:lab6@localhost:5432/lab6')
engine = create_async_engine(DATABASE_URL, echo=True)

# подсчет кол-ва sql запросов (для n+1)
# переменная контекста выполнения, чтобы хранит данные отдельно для разных контекстов асинхронного выполнения
sql_trace = ContextVar('sql_trace', default=None) 
@event.listens_for(engine.sync_engine, 'before_cursor_execute')
def count_sql(conn, cursor, statement, parameters, context, executemany):
    trace = sql_trace.get() # получаем список SQL-команд текущего HTTP-запроса
    if trace is not None and statement.lstrip().upper().startswith(('SELECT','INSERT','UPDATE','DELETE')):
        trace.append(statement) # добавляем SQL-команду в список (в main.py после обработки HTTP-запроса определяется длина списка)

async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

async def read(stmt):
    async with engine.connect() as conn:
        return (await conn.execute(stmt)).mappings().all()

async def one(table, id):
    rows = await read(select(table).where(table.c.id == id))
    return rows[0] if rows else None

async def get_restaurant(id): return await one(restaurants, id)
async def get_dish(id): return await one(dishes, id)
async def get_order(id): return await one(orders, id)
async def get_items(order_id):
    return await read(select(order_items).where(order_items.c.order_id == order_id).order_by(order_items.c.id))
async def get_dishes_by_restaurant(restaurant_id):
    return await read(select(dishes).where(dishes.c.restaurant_id == restaurant_id).order_by(dishes.c.id))
async def list_restaurants(): return await read(select(restaurants).order_by(restaurants.c.id))
async def by_ids(table, ids):
    rows = await read(select(table).where(table.c.id.in_(ids)))
    return {r.id: r for r in rows}
async def get_restaurants(ids): return await by_ids(restaurants, ids)
async def get_dishes(ids): return await by_ids(dishes, ids)
async def get_items_by_orders(order_ids):
    rows = await read(select(order_items).where(order_items.c.order_id.in_(order_ids)).order_by(order_items.c.id))
    found = defaultdict(list)
    for r in rows: found[r.order_id].append(r)
    return dict(found)
async def list_orders(status=None):
    stmt = select(orders)
    if status is not None: stmt = stmt.where(orders.c.status == OrderStatus(status).value)
    return await read(stmt.order_by(orders.c.created_at.desc(), orders.c.id.desc()))
