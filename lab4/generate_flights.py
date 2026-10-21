
import random
from datetime import datetime, timedelta
import psycopg

# Подключение к БД
conn = psycopg.connect(
    host="localhost",
    port=5432,
    dbname="flights",
    user="postgres"
)

random.seed(42)

airports = [
    "SVO", "DME", "VKO", "LED", "KZN",
    "AER", "SVX", "OVB", "KRR", "UFA",
    "ROV", "KGD", "MRV", "GOJ", "CEK",
    "KJA", "IKT", "VVO", "KHV", "TJM",
    "OMS", "PEE", "SIP", "MMK", "ARH",
    "MUR", "NAL", "ASF", "REN", "NOZ"
]

carriers = ["Aeroflot", "S7", "Ural Airlines", "Pobeda", "Russia"]

start_date = datetime(2026, 10, 15)
total_flights = 0

try:
    with conn.cursor() as cur:
        # Для повторного запуска сначала очищаем таблицу
        cur.execute("TRUNCATE TABLE flights RESTART IDENTITY")

        # Генерация данных для 120 дней
        for day in range(120):
            current_date = start_date + timedelta(days=day)
            rows = []

            # Генерация 1500 рейсов в день
            for number in range(1500):
                origin = random.choice(airports)
                destination = random.choice(
                    [a for a in airports if a != origin]
                )

                # Генерация случайного времени вылета в пределах дня
                departure = current_date + timedelta(
                    seconds=random.randint(0, 86399)
                )
                duration = random.randint(1, 6)

                arrival = departure + timedelta(hours=duration) # Добавляем случайную продолжительность полета 1-6 часов
                carrier = random.choice(carriers) # Выбираем случайного перевозчика
                flight_number = f"{carrier[:2].upper()}{number + 1:04d}" # Формируем номер рейса, используя первые две буквы перевозчика и порядковый номер рейса
                price = round(random.uniform(3000, 50000), 2) # Генерация случайной цены билета 

                rows.append((
                    carrier,
                    flight_number,
                    origin,
                    destination,
                    departure,
                    arrival,
                    price
                ))

            cur.executemany(
                """
                INSERT INTO flights
                (carrier, flight_number, origin, destination,
                 departure_time, arrival_time, price)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                rows
            )

            total_flights += len(rows)
            print(f"День {day + 1}/120: добавлено {total_flights} рейсов")

    conn.commit()
    print(f"\nГотово! Всего добавлено рейсов: {total_flights}")

except Exception:
    conn.rollback()
    raise

finally:
    conn.close()
