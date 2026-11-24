"""Повторный запуск сбрасывает учебные данные. Не применять к рабочей базе."""
import asyncio
from sqlalchemy import insert, text
from app import db
from app.seed_data import generate

async def seed():
    await db.create_tables()
    rs, ds, os, its = generate()
    async with db.engine.begin() as conn:
        await conn.execute(text('TRUNCATE order_items, orders, dishes, restaurants RESTART IDENTITY'))
        for table, rows in [(db.restaurants,rs),(db.dishes,ds),(db.orders,os),(db.order_items,its)]:
            await conn.execute(insert(table),rows)
        for name in ('restaurants','dishes','orders'):
            await conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), (SELECT max(id) FROM {name}))"))
    print(f'Ресторанов: {len(rs)}; блюд: {len(ds)}; заказов: {len(os)}; позиций: {len(its)}')

async def main():
    try: await seed()
    finally: await db.engine.dispose()
if __name__ == '__main__': asyncio.run(main())
