
import argparse
import asyncio
import math
import random
import time

import httpx


SEARCH_PARAMS = {
    "origin": "SVO",
    "destination": "LED",
    "date": "2026-10-15",
}


def percentile(values, percent):
    if not values:
        return 0.0

    values = sorted(values)
    position = (len(values) - 1) * percent / 100
    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        return values[lower]

    return (
        values[lower] * (upper - position)
        + values[upper] * (position - lower)
    )


def print_statistics(name, results, duration):
    count = len(results)
    times = [item[0] for item in results]
    errors = sum(1 for item in results if not item[1])

    print(f"\n{name}")
    print(f"Количество запросов: {count}")
    print(f"Запросов в секунду: {count / duration:.2f}")
    print(f"p50: {percentile(times, 50):.2f} мс")
    print(f"p95: {percentile(times, 95):.2f} мс")
    print(f"p99: {percentile(times, 99):.2f} мс")
    print(f"Максимальное время: {max(times, default=0):.2f} мс")
    print(f"Ошибки: {errors / count * 100 if count else 0:.2f} %")


async def send_request(client, url, params, results, measure_from):
    started = time.perf_counter()
    success = False

    try:
        response = await client.get(url, params=params)
        success = response.status_code == 200
    except httpx.RequestError:
        pass

    finished = time.perf_counter()

    if started >= measure_from:
        results.append(((finished - started) * 1000, success))


async def closed_client(
    client, url, results, measure_from, stop_at
):
    while time.perf_counter() < stop_at:
        await send_request(
            client, url, SEARCH_PARAMS, results, measure_from
        )


async def closed_load(
    client, url, clients_count, results, measure_from, stop_at
):
    tasks = [
        asyncio.create_task(
            closed_client(
                client, url, results, measure_from, stop_at
            )
        )
        for _ in range(clients_count)
    ]
    await asyncio.gather(*tasks)


async def open_load(
    client, url, rate, results, measure_from, stop_at
):
    tasks = []
    next_request = time.perf_counter()

    while next_request < stop_at:
        delay = next_request - time.perf_counter()

        if delay > 0:
            await asyncio.sleep(delay)

        tasks.append(
            asyncio.create_task(
                send_request(
                    client, url, SEARCH_PARAMS, results, measure_from
                )
            )
        )

        next_request += random.expovariate(rate)

    await asyncio.gather(*tasks)


async def health_monitor(
    client, url, results, measure_from, stop_at
):
    next_check = time.perf_counter()

    while next_check < stop_at:
        delay = next_check - time.perf_counter()

        if delay > 0:
            await asyncio.sleep(delay)

        if next_check >= stop_at:
            break

        await send_request(
            client, url, None, results, measure_from
        )

        next_check += 0.1


async def main(args):
    base_url = args.url.rstrip("/")
    search_url = base_url + "/search"
    health_url = base_url + "/health"

    search_results = []
    health_results = []

    started = time.perf_counter()
    measure_from = started + args.warmup
    stop_at = measure_from + args.duration

    print("Нагрузочное тестирование")
    print(f"Режим: {args.mode}")
    print(f"Прогрев: {args.warmup} с")
    print(f"Длительность замера: {args.duration} с")
    print(f"Адрес: {base_url}")

    if args.mode == "closed":
        print(f"Количество клиентов: {args.clients}")
    else:
        print(f"Интенсивность: {args.rate} запросов/с")

    limits = httpx.Limits(
        max_connections=1000,
        max_keepalive_connections=100
    )

    timeout = httpx.Timeout(30.0)

    async with httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        trust_env=False
    ) as client:

        health_task = asyncio.create_task(
            health_monitor(
                client,
                health_url,
                health_results,
                measure_from,
                stop_at
            )
        )

        if args.mode == "closed":
            await closed_load(
                client,
                search_url,
                args.clients,
                search_results,
                measure_from,
                stop_at
            )
        else:
            await open_load(
                client,
                search_url,
                args.rate,
                search_results,
                measure_from,
                stop_at
            )

        await health_task

    print_statistics(
        "Результаты GET /search",
        search_results,
        args.duration
    )

    print_statistics(
        "Результаты GET /health",
        health_results,
        args.duration
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--mode",
        choices=["closed", "open"],
        required=True
    )
    parser.add_argument("--clients", type=int, default=1)
    parser.add_argument("--rate", type=float, default=5.0)
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--warmup", type=float, default=10)
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000"
    )

    args = parser.parse_args()

    if args.clients <= 0 or args.rate <= 0:
        parser.error("clients и rate должны быть больше нуля")

    if args.duration <= 0 or args.warmup < 0:
        parser.error("Неверная длительность теста")

    asyncio.run(main(args))