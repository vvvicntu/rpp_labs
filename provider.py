
import os
import time
import random
import hashlib
from datetime import date, datetime, timedelta

from fastapi import FastAPI, HTTPException, Query

app = FastAPI()

# Параметры поставщика из переменных окружения
PROVIDER_ID = int(os.getenv("PROVIDER_ID", "1"))
AVG_DELAY_MS = int(os.getenv("AVG_DELAY_MS", "300"))
ERROR_PROB = float(os.getenv("ERROR_PROB", "0.05"))
SLOW_PROB = float(os.getenv("SLOW_PROB", "0"))
FLIGHTS_PER_DAY = int(os.getenv("FLIGHTS_PER_DAY", "500"))


# Проверка работоспособности поставщика
@app.get("/health")
def health():
    return {
        "status": "ok",
        "provider": PROVIDER_ID
    }


# Получение рейсов за указанную дату
@app.get("/flights")
def get_flights(flight_date: date = Query(..., alias="date")):

    # Фиксированный seed для одинаковых рейсов
    # у одного поставщика на одну дату
    seed_text = f"{PROVIDER_ID}-{flight_date.isoformat()}"
    seed = int(hashlib.sha256(seed_text.encode()).hexdigest(), 16)
    rng = random.Random(seed)

    # Случайная задержка при каждом запросе (±30%)
    delay = AVG_DELAY_MS * random.uniform(0.7, 1.3)

    # Вероятность медленного ответа (3 секунды)
    if random.random() < SLOW_PROB:
        delay = 3000

    time.sleep(delay / 1000)

    # Вероятность ошибки HTTP 500
    if random.random() < ERROR_PROB:
        raise HTTPException(
            status_code=500,
            detail="Provider error"
        )

    # Список 30 аэропортов
    airports = [
        "SVO", "DME", "VKO", "LED", "KZN",
        "AER", "SVX", "OVB", "KRR", "UFA",
        "ROV", "KGD", "MRV", "GOJ", "CEK",
        "KJA", "IKT", "VVO", "KHV", "TJM",
        "OMS", "PEE", "SIP", "MMK", "ARH",
        "MUR", "NAL", "ASF", "REN", "NOZ"
    ]

    # Список авиаперевозчиков
    carriers = [
        "Aeroflot",
        "S7",
        "Ural Airlines",
        "Pobeda",
        "Russia"
    ]

    flights = []

    # Генерация 500 рейсов за дату
    for i in range(FLIGHTS_PER_DAY):

        origin = rng.choice(airports)

        destination = rng.choice(
            [a for a in airports if a != origin]
        )

        # Случайное время вылета
        departure = datetime.combine(
            flight_date,
            datetime.min.time()
        ) + timedelta(
            seconds=rng.randint(0, 86399)
        )

        # Продолжительность полёта от 1 до 6 часов
        duration = rng.randint(1, 6)
        arrival = departure + timedelta(hours=duration)

        # Добавление рейса
        flights.append({
            "carrier": rng.choice(carriers),
            "flight_number": f"P{PROVIDER_ID}-{i + 1:04d}",
            "origin": origin,
            "destination": destination,
            "departure_time": departure.isoformat(),
            "arrival_time": arrival.isoformat(),
            "price": round(rng.uniform(3000, 50000), 2)
        })

    # Возвращаем список рейсов
    return {
        "provider": PROVIDER_ID,
        "date": flight_date.isoformat(),
        "flights": flights
    }
