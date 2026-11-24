"""Локальные проверки бизнес-логики; SQLite не заменяет проверку PostgreSQL."""
import unittest
from unittest.mock import patch
from collections import Counter
from decimal import Decimal
from sqlalchemy import create_engine, insert, event
from sqlalchemy.pool import StaticPool
from app.seed_data import generate

class Connection:
    def __init__(self, conn): self.conn=conn
    async def execute(self,*args,**kw): return self.conn.execute(*args,**kw)
    async def run_sync(self, fn): return fn(self.conn)
class Context:
    def __init__(self, cm): self.cm=cm
    async def __aenter__(self): return Connection(self.cm.__enter__())
    async def __aexit__(self,*args): return self.cm.__exit__(*args)
class Engine:
    def __init__(self): self.sync_engine=create_engine('sqlite://',poolclass=StaticPool)
    def begin(self): return Context(self.sync_engine.begin())
    def connect(self): return Context(self.sync_engine.connect())
# Подменяется только драйвер/соединение. Код SQL и бизнес-операций — настоящий.
with patch('sqlalchemy.ext.asyncio.create_async_engine',return_value=Engine()):
    from app import db, services, events

class Offline(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        db.metadata.drop_all(db.engine.sync_engine)
        await db.create_tables()
        with db.engine.sync_engine.begin() as c:
            for table,rows in zip((db.restaurants,db.dishes,db.orders,db.order_items),generate()): c.execute(insert(table),rows)
    async def test_seed(self):
        rs,ds,os,its=generate(); self.assertEqual((len(rs),len(ds),len(os),len(its)),(5,50,100,200))
        self.assertEqual(set(Counter(o['status'] for o in os).values()),{20})
        self.assertEqual((await db.get_order(1)).total,Decimal('850.00'))
        self.assertEqual(len(await db.list_orders(db.OrderStatus.READY)),20)
    async def test_create_and_delivery(self):
        row=await services.create_order(1,'Анна','Адрес',[(1,2),(2,1)])
        self.assertEqual(row.total,Decimal('800.00')); self.assertEqual(row.status,'CREATED')
        q=events.subscribe(row.id)
        try:
            for fn,status in [(services.accept,'ACCEPTED'),(services.mark_ready,'READY'),(services.mark_delivered,'DELIVERED')]:
                self.assertEqual((await fn(row.id)).status,status); self.assertEqual(q.get_nowait().status.value,status)
        finally: events.unsubscribe(row.id,q)
        self.assertNotIn(row.id,events._queues)
    async def test_validation(self):
        for items in ([],[(1,0)],[(1,21)],[(11,1)],[(1,1)]*11):
            with self.assertRaises(services.OrderValidationError): await services.create_order(1,'Анна','Адрес',items)
        self.assertEqual(len(await db.list_orders()),100)
        with self.assertRaises(services.NotFound): await services.accept(999999)
        with self.assertRaises(services.TransitionNotAllowed): await services.accept(5)
        self.assertEqual((await db.get_order(5)).status,'CANCELLED')
    async def test_cancel(self):
        with self.assertRaises(services.OrderValidationError): await services.cancel(1,'а')
        row=await services.cancel(1,'Изменились планы'); self.assertEqual(row.status,'CANCELLED')
        self.assertEqual(row.cancel_reason,'Изменились планы')
        with self.assertRaises(services.TransitionNotAllowed): await services.cancel(3,'Изменились планы')
    async def test_batch_counts(self):
        for status,n in [('CANCELLED',20),('READY',20),(None,100)]:
            trace=[]; token=db.sql_trace.set(trace)
            try:
                rows=await db.list_orders(status)
                for row in rows:
                    await db.get_restaurant(row.restaurant_id)
                    for item in await db.get_items(row.id): await db.get_dish(item.dish_id)
                self.assertEqual(len(trace),1+4*n)
                trace.clear(); rows=await db.list_orders(status)
                await db.get_restaurants(list({r.restaurant_id for r in rows}))
                grouped=await db.get_items_by_orders([r.id for r in rows])
                await db.get_dishes(list({i.dish_id for group in grouped.values() for i in group}))
                self.assertEqual(len(trace),4)
                print(f'{status or "ALL"}: orders={n}, single={1+4*n}, batch={len(trace)}')
            finally: db.sql_trace.reset(token)

if __name__=='__main__': unittest.main(verbosity=2)
