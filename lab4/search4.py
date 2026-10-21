import asyncio
import os
import time
from contextlib import asynccontextmanager
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timedelta
from collections import defaultdict

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from sqlalchemy import MetaData, Table, and_, select
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

DB_URL = URL.create(
    drivername="postgresql+asyncpg",
    username=os.getenv("DB_USER", "postgres"),
    password=os.getenv("DB_PASSWORD") or None,
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", "5432")),
    database=os.getenv("DB_NAME", "flights"),
)

PROVIDERS = {
    1: os.getenv("PROVIDER_1_URL", "http://127.0.0.1:8001"),
    2: os.getenv("PROVIDER_2_URL", "http://127.0.0.1:8002"),
    3: os.getenv("PROVIDER_3_URL", "http://127.0.0.1:8003"),
}

metadata = MetaData()


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = create_async_engine(DB_URL, pool_pre_ping=True)
    client = httpx.AsyncClient(trust_env=False)
    process_pool = ProcessPoolExecutor(max_workers=int(os.getenv("CPU_WORKERS", "2")))
    try:
        async with engine.connect() as conn:
            await conn.run_sync(metadata.reflect, only=["flights"])
        app.state.engine = engine
        app.state.client = client
        app.state.process_pool = process_pool
        app.state.flights_table = metadata.tables["flights"]
        yield
    finally:
        await client.aclose()
        await engine.dispose()
        process_pool.shutdown(wait=True, cancel_futures=True)


app = FastAPI(title="Flight Search Service", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


async def get_db_flights(search_date, engine, flights_table):
    start = datetime.combine(search_date, datetime.min.time())
    end = start + timedelta(days=1)
    query = select(flights_table).where(
        and_(
            flights_table.c.departure_time >= start,
            flights_table.c.departure_time < end,
        )
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(query)).mappings().all()

    result = []
    for row in rows:
        result.append({
            "carrier": row["carrier"],
            "flight_number": row["flight_number"],
            "origin": row["origin"],
            "destination": row["destination"],
            "departure_time": row["departure_time"].isoformat(),
            "arrival_time": row["arrival_time"].isoformat(),
            "price": float(row["price"]),
        })
    return result


async def get_provider_flights(provider_id, search_date, client):
    url = PROVIDERS[provider_id] + "/flights"
    deadline = time.monotonic() + 2.0

    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            response = await client.get(
                url,
                params={"date": search_date.isoformat()},
                timeout=remaining,
            )
            response.raise_for_status()
            return response.json()["flights"]
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError, KeyError):
            if attempt == 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0.2:
                    break
                await asyncio.sleep(0.2)
    return None


def build_routes(flights, origin, destination, search_date):
    by_origin = defaultdict(list)
    for flight in flights:
        departure = datetime.fromisoformat(flight["departure_time"])
        arrival = datetime.fromisoformat(flight["arrival_time"])
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
                {k: v for k, v in flight.items() if not k.startswith("_")}
                for flight in path
            ],
            "transfers": len(path) - 1,
            "total_price": round(sum(float(f["price"]) for f in path), 2),
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
            explore(next_airport, path + [flight], visited | {next_airport})

    explore(origin, [], {origin})
    routes.sort(key=lambda route: route["total_price"])
    return routes[:20]


@app.get("/search")
async def search(
    request: Request,
    origin: str = Query(..., min_length=3, max_length=3),
    destination: str = Query(..., min_length=3, max_length=3),
    flight_date: date = Query(..., alias="date"),
):
    started = time.perf_counter()
    origin = origin.upper()
    destination = destination.upper()
    if origin == destination:
        raise HTTPException(
            status_code=400, detail="Origin and destination must differ"
        )

    # База данных и все три поставщика опрашиваются одновременно.
    results = await asyncio.gather(
        get_db_flights(
            flight_date, request.app.state.engine, request.app.state.flights_table
        ),
        *(
            get_provider_flights(provider_id, flight_date, request.app.state.client)
            for provider_id in PROVIDERS
        ),
        return_exceptions=True,
    )

    # Ошибка БД возвращает 503; ошибки поставщиков не прерывают остальные запросы.
    db_result, *provider_results = results
    if isinstance(db_result, BaseException):
        raise HTTPException(
            status_code=503,
            detail=f"Database unavailable: {db_result.__class__.__name__}",
        ) from db_result

    all_flights = db_result
    db_has_flights = bool(all_flights)
    provider_results = [
        None if isinstance(result, BaseException) else result
        for result in provider_results
    ]

    failed_providers = []
    for provider_id, provider_flights in zip(PROVIDERS, provider_results):
        if provider_flights is None:
            failed_providers.append(provider_id)
        else:
            all_flights.extend(provider_flights)

    if not db_has_flights and len(failed_providers) == 3:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Search temporarily unavailable",
                "failed_providers": failed_providers,
            },
        )

    loop = asyncio.get_running_loop()
    routes = await loop.run_in_executor(
        request.app.state.process_pool,
        build_routes, all_flights, origin, destination, flight_date
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "origin": origin,
        "destination": destination,
        "date": flight_date.isoformat(),
        "routes": routes,
        "failed_providers": failed_providers,
        "processing_time_ms": elapsed_ms,
    }
