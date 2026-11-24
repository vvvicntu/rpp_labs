"""Детерминированные исходные данные, независимо от СУБД."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

NAMES = ['Сибирская кухня','Итальянский дворик','Восток','Зелёный сад','Городское кафе']
MENUS = [
 ['Пельмени','Борщ','Вареники','Котлета','Гречка','Солянка','Салат','Блины','Сырники','Морс'],
 ['Маргарита','Карбонара','Лазанья','Ризотто','Брускетта','Песто','Равиоли','Тирамису','Панна-котта','Лимонад'],
 ['Плов','Манты','Лагман','Шурпа','Самса','Кебаб','Хумус','Фалафель','Пахлава','Чай'],
 ['Боул','Тофу','Салат с киноа','Суп-пюре','Овощи гриль','Рататуй','Кускус','Смузи','Фруктовый салат','Сок'],
 ['Бургер','Сэндвич','Куриный суп','Паста','Картофель','Цезарь','Стейк','Чизкейк','Круассан','Кофе']]
STATUSES = ['CREATED','ACCEPTED','READY','DELIVERED','CANCELLED']

def generate():
    restaurants = [dict(id=r,name=NAMES[r-1],address=f'Новосибирск, ул. Ленина, {r*10}') for r in range(1,6)]
    dishes = [dict(id=(r-1)*10+j,restaurant_id=r,name=MENUS[r-1][j-1],price=Decimal(200+50*j+20*(r-1)).quantize(Decimal('.01'))) for r in range(1,6) for j in range(1,11)]
    orders, items = [], []
    for i in range(1,101):
        r = ((i-1)//5)%5+1
        status = STATUSES[(i-1)%5]
        positions = []
        for j in range(2):
            dish = dishes[(r-1)*10+((i-1+j)%10)]
            positions.append(dict(order_id=i,dish_id=dish['id'],quantity=j+1,price=dish['price']))
        orders.append(dict(id=i,restaurant_id=r,customer_name=f'Клиент {i}',delivery_address=f'Новосибирск, ул. Кирова, {i}',status=status,
            cancel_reason='Изменились планы' if status=='CANCELLED' else None,total=sum(p['price']*p['quantity'] for p in positions),
            created_at=datetime(2026,11,1,tzinfo=timezone.utc)+timedelta(minutes=i)))
        items.extend(positions)
    return restaurants,dishes,orders,items
