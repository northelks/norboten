"""Redis: what has to be fast and shared between API processes, and is fine to lose.

Three jobs, all of them small:

* **live frames** — a recorder's batch is published on `play:<session_id>` the moment it arrives,
  and every viewer's server-sent-events loop is subscribed to that channel. A viewer who opens a
  session before it starts simply waits on the channel; nobody polls the database;
* **rate limits** — a counter per client and window (`limited`, `limited_in`). A sign-in in flight
  is not here: it lives in PostgreSQL (`pending.py`), to survive a restart;
* **a short cache** — the leaderboard, which every profile page and TUI screen asks for.

Nothing here is the record of anything: the recording is in PostgreSQL, the account is in
PostgreSQL. If Redis restarts, live viewers reconnect, the limits start counting again, and the
cache refills — which is exactly why these three things live here and nothing else does.

Without `NORBOTEN_REDIS_URL` the API uses `MemoryBus`, which does all three inside one process. That
is right for tests and a laptop and wrong for a server running more than one worker.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol


class Subscription(Protocol):
    async def next(self, timeout: float) -> dict | None:
        """The next message, or None when `timeout` seconds pass without one."""
        ...


class Bus(Protocol):
    async def publish(self, channel: str, message: dict) -> None: ...
    def subscribe(self, channel: str): ...  # an async context manager yielding a Subscription
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl: int) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def incr(self, key: str, ttl: int) -> int: ...
    async def close(self) -> None: ...


class _QueueSubscription:
    def __init__(self, queue: asyncio.Queue) -> None:
        self.queue = queue

    async def next(self, timeout: float) -> dict | None:
        try:
            return await asyncio.wait_for(self.queue.get(), timeout)
        except TimeoutError:
            return None


class _RedisSubscription:
    def __init__(self, pubsub) -> None:
        self.pubsub = pubsub

    async def next(self, timeout: float) -> dict | None:
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            raw = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=left)
            if raw and raw.get("type") == "message":
                return json.loads(raw["data"])


class MemoryBus:
    """One process's worth of Redis."""

    def __init__(self) -> None:
        self._channels: dict[str, set[asyncio.Queue]] = {}
        self._values: dict[str, tuple[str, float]] = {}

    async def publish(self, channel: str, message: dict) -> None:
        for queue in list(self._channels.get(channel, ())):
            queue.put_nowait(message)

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncIterator[Subscription]:
        queue: asyncio.Queue = asyncio.Queue()
        self._channels.setdefault(channel, set()).add(queue)
        try:
            yield _QueueSubscription(queue)
        finally:
            self._channels[channel].discard(queue)
            if not self._channels[channel]:
                self._channels.pop(channel, None)

    def _live(self, key: str) -> str | None:
        item = self._values.get(key)
        if item is None:
            return None
        value, expires = item
        if expires < time.monotonic():
            self._values.pop(key, None)
            return None
        return value

    async def get(self, key: str) -> str | None:
        return self._live(key)

    async def set(self, key: str, value: str, ttl: int) -> None:
        self._values[key] = (value, time.monotonic() + ttl)

    async def delete(self, key: str) -> None:
        self._values.pop(key, None)

    async def incr(self, key: str, ttl: int) -> int:
        current = self._live(key)
        value = int(current or 0) + 1
        expires = self._values[key][1] if current is not None else time.monotonic() + ttl
        self._values[key] = (str(value), expires)
        return value

    async def close(self) -> None:
        self._channels.clear()


class RedisBus:
    """The real thing: redis.asyncio, one connection pool for commands and one per subscriber."""

    def __init__(self, url: str) -> None:
        import redis.asyncio as redis

        self._redis = redis.from_url(url, decode_responses=True)

    async def publish(self, channel: str, message: dict) -> None:
        await self._redis.publish(channel, json.dumps(message))

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncIterator[Subscription]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            yield _RedisSubscription(pubsub)
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    async def get(self, key: str) -> str | None:
        return await self._redis.get(key)

    async def set(self, key: str, value: str, ttl: int) -> None:
        await self._redis.set(key, value, ex=ttl)

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def incr(self, key: str, ttl: int) -> int:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, ttl, nx=True)  # the window starts with the first hit
            value, _ = await pipe.execute()
        return int(value)

    async def close(self) -> None:
        await self._redis.aclose()


def build(url: str) -> Bus:
    return RedisBus(url) if url.startswith(("redis://", "rediss://", "unix://")) else MemoryBus()


async def limited(bus: Bus, bucket: str, who: str, per_minute: int) -> bool:
    """True when `who` has used up this minute's allowance for `bucket`."""
    return await limited_in(bus, bucket, who, per_minute, 60)


async def limited_in(bus: Bus, bucket: str, who: str, allowance: int, seconds: int) -> bool:
    """The same, over a window of any length: a fixed window, so the worst case is twice the
    allowance across a boundary — close enough for a limit whose job is to stop a flood."""
    window = int(time.time() // seconds)
    return await bus.incr(f"rate:{bucket}:{who}:{window}", ttl=seconds + 5) > allowance
