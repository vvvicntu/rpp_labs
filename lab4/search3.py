import os
import time
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from collections import defaultdict

import httpx
from fastapi import FastAPI, HTTPException, Query
from starlette.concurrency import run_in_threadpool
from sqlalchemy import (
    MetaData, Table, select, and_
)
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine


# Подключение к PostgreSQL
db_url = URL.create(
    drivername="postgresql+asyncpg",
    username=os.getenv("DB_USER", "postgres"),
    password=os.getenv("DB_PASSWORD") or None,
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", "5432")),
    database=os.getenv("DB_NAME", "flights")
)

engine = create_async_engine(
    db_url,
    pool_pre_ping=True
)

metadata = MetaData()

flights_table = None
http_client = None


# Адреса трёх поставщиков
PROVIDERS = {
    1: os.getenv("PROVIDER_1_URL", "http://127.0.0.1:8001"),
    2: os.getenv("PROVIDER_2_URL", "http://127.0.0.1:8002"),
    3: os.getenv("PROVIDER_3_URL", "http://127.0.0.1:8003")
}


# Создание и закрытие ресурсов приложения
@asynccontextmanager
async def lifespan(app: FastAPI):
    global flights_table, http_client

    # Асинхронная загрузка структуры таблицы
    async with engine.begin() as conn:
        flights_table = await conn.run_sync(
            lambda sync_conn: Table(
                "flights",
                metadata,
                autoload_with=sync_conn
            )
        )

    # Один HTTP-клиент для всех запросов
    http_client = httpx.AsyncClient(
        timeout=2.0,
        trust_env=False
    )

    try:
        yield
    finally:
        await http_client.aclose()
        await engine.dispose()


app = FastAPI(
    title="Flight Search Service",
    lifespan=lifespan
)


@app.get("/health")
async def health():
    return {"status": "ok"}


# Асинхронное получение рейсов из PostgreSQL
async def get_db_flights(search_date):
    start = datetime.combine(
        search_date, datetime.min.time()
    )
    end = start + timedelta(days=1)

    query = select(flights_table).where(
        and_(
            flights_table.c.departure_time >= start,
            flights_table.c.departure_time < end
        )
    )

    async with engine.connect() as conn:
        result = await conn.execute(query)
        rows = result.mappings().all()

    flights = []

    for row in rows:
        flights.append({
            "carrier": row["carrier"],
            "flight_number": row["flight_number"],
            "origin": row["origin"],
            "destination": row["destination"],
            "departure_time": row["departure_time"].isoformat(),
            "arrival_time": row["arrival_time"].isoformat(),
            "price": float(row["price"])
        })

    return flights


# Асинхронный запрос поставщика с общим лимитом 2 секунды
async def get_provider_flights(provider_id, search_date):
    url = PROVIDERS[provider_id] + "/flights"
    deadline = time.monotonic() + 2.0

    for attempt in range(2):
        remaining = deadline - time.monotonic()

        if remaining <= 0:
            break

        try:
            response = await http_client.get(
                url,
                params={"date": search_date.isoformat()},
                timeout=remaining
            )

            response.raise_for_status()

            return response.json()["flights"]

        except (
            httpx.RequestError,
            httpx.HTTPStatusError,
            ValueError,
            KeyError
        ):
            if attempt == 0:
                remaining = deadline - time.monotonic()

                if remaining <= 0.2:
                    break

                await asyncio.sleep(0.2)

    return None


# Формирование маршрутов без сети и базы данных
def build_routes(flights, origin, destination, search_date):

    by_origin = defaultdict(list)

    for flight in flights:
        departure = datetime.fromisoformat(
            flight["departure_time"]
        )
        arrival = datetime.fromisoformat(
            flight["arrival_time"]
        )

        if departure.date() != search_date:
            continue

        if flight["origin"] == flight["destination"]:
            continue

        item = dict(flight)
        item["_departure"] = departure
        item["_arrival"] = arrival

        by_origin[item["origin"]].append(item)

    routes = []

    def add_route(path):
        routes.append({
            "flights": [
                {
                    k: v for k, v in flight.items()
                    if not k.startswith("_")
                }
                for flight in path
            ],
            "transfers": len(path) - 1,
            "total_price": round(
                sum(float(f["price"]) for f in path), 2
            )
        })

    def explore(airport, path, visited):
        if airport == destination:
            if path:
                add_route(path)
            return

        if len(path) >= 3:
            return

        for flight in by_origin.get(airport, []):
            next_airport = flight["destination"]

            if next_airport in visited:
                continue

            if path:
                connection = (
                    flight["_departure"] - path[-1]["_arrival"]
                ).total_seconds()

                if not 3600 <= connection <= 21600:
                    continue

            explore(
                next_airport,
                path + [flight],
                visited | {next_airport}
            )

    explore(origin, [], {origin})

    routes.sort(key=lambda route: route["total_price"])

    return routes[:20]


@app.get("/search")
async def search(
    origin: str = Query(..., min_length=3, max_length=3),
    destination: str = Query(..., min_length=3, max_length=3),
    flight_date: date = Query(..., alias="date")
):
    started = time.perf_counter()

    origin = origin.upper()
    destination = destination.upper()

    if origin == destination:
        raise HTTPException(
            status_code=400,
            detail="Origin and destination must differ"
        )

    # Асинхронно читаем собственную базу
    try:
        all_flights = await get_db_flights(flight_date)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database unavailable: {exc.__class__.__name__}"
        )

    db_has_flights = bool(all_flights)
    failed_providers = []

    # Параллельный опрос трёх поставщиков
    provider_ids = list(PROVIDERS.keys())

    provider_results = await asyncio.gather(
        *[
            get_provider_flights(provider_id, flight_date)
            for provider_id in provider_ids
        ]
    )

    for provider_id, provider_flights in zip(
        provider_ids, provider_results
    ):
        if provider_flights is None:
            failed_providers.append(provider_id)
        else:
            all_flights.extend(provider_flights)

    # Если источники недоступны
    if not db_has_flights and len(failed_providers) == 3:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Search temporarily unavailable",
                "failed_providers": failed_providers
            }
        )

    # Вычисления выполняются в рабочем потоке,
    # чтобы не блокировать event loop
    routes = await run_in_threadpool(
        build_routes,
        all_flights,
        origin,
        destination,
        flight_date
    )

    elapsed_ms = round(
        (time.perf_counter() - started) * 1000, 2
    )

    return {
        "origin": origin,
        "destination": destination,
        "date": flight_date.isoformat(),
        "routes": routes,
        "failed_providers": failed_providers,
        "processing_time_ms": elapsed_ms
    }
