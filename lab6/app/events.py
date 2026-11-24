import asyncio
from collections import defaultdict
from dataclasses import dataclass
from app.db import OrderStatus

@dataclass(frozen=True)
class OrderStatusChanged:
    order_id: int
    status: OrderStatus

_queues: dict[int, set[asyncio.Queue]] = defaultdict(set)

def subscribe(order_id):
    queue = asyncio.Queue()
    _queues[order_id].add(queue)
    return queue

def unsubscribe(order_id, queue):
    queues = _queues.get(order_id)
    if queues is not None:
        queues.discard(queue)
        if not queues: _queues.pop(order_id, None)

def publish(event):
    for queue in tuple(_queues.get(event.order_id, ())):
        queue.put_nowait(event)
