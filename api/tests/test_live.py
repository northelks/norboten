"""Redis's four jobs, in memory — and against a real Redis when NORBOTEN_TEST_REDIS_URL is set."""

import asyncio
import json
import os

import pytest

from norboten_api import live
from norboten_api.play_store import FrameBatch, MemoryPlayStore, PlaySession
from norboten_api.routers import play as play_router

REDIS = os.environ.get("NORBOTEN_TEST_REDIS_URL", "")
KINDS = ["memory", pytest.param("redis", marks=pytest.mark.skipif(not REDIS, reason="no redis"))]


@pytest.fixture(params=KINDS)
async def bus(request):
    b = live.build(REDIS if request.param == "redis" else "")
    yield b
    await b.close()


async def test_a_subscriber_gets_what_is_published_and_nothing_before(bus):
    await bus.publish("play:x", {"n": 0})  # nobody listening: gone
    async with bus.subscribe("play:x") as sub:
        await asyncio.sleep(0.05)  # redis confirms the subscription asynchronously
        await bus.publish("play:x", {"n": 1})
        assert await sub.next(2) == {"n": 1}
        assert await sub.next(0.1) is None


async def test_values_expire_and_counters_count(bus):
    await bus.set("device:abc", "pending", ttl=1)
    assert await bus.get("device:abc") == "pending"
    await bus.delete("device:abc")
    assert await bus.get("device:abc") is None
    assert [await bus.incr("rate:t", ttl=60) for _ in range(3)] == [1, 2, 3]


async def test_a_rate_limit_trips_after_the_allowance(bus):
    results = [await live.limited(bus, "chat-test", "10.0.0.1", per_minute=2) for _ in range(3)]
    assert results == [False, False, True]
    assert not await live.limited(bus, "chat-test", "10.0.0.2", per_minute=2)


async def _events(response, into: list, stop_after: str):
    async for chunk in response.body_iterator:
        text = chunk if isinstance(chunk, str) else chunk.decode()
        for block in text.strip().split("\n\n"):
            if block.startswith("event: "):
                name, data = block.split("\n", 1)
                into.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
                if into[-1][0] == stop_after:
                    return


async def test_a_viewer_who_arrives_first_is_sent_frames_as_they_are_published():
    store, bus = MemoryPlayStore(), live.MemoryBus()
    session = PlaySession(
        session_id="s-live-0001", user_id="u", nick="tux", lab_id="hello", width=80, height=24
    )
    await store.start(session)
    response = await play_router.stream("s-live-0001", after=-1, play=store, bus=bus)
    seen: list = []
    viewer = asyncio.create_task(_events(response, seen, stop_after="end"))
    await asyncio.sleep(0.05)
    assert seen == [("header", session.header())]

    batch = FrameBatch(seq=0, at=0.0, events=[[0.0, "o", "$ ls\r\n"]])
    await store.append("s-live-0001", batch)
    await bus.publish("play:s-live-0001", {"type": "batch", "batch": batch.model_dump()})
    await bus.publish("play:s-live-0001", {"type": "batch", "batch": batch.model_dump()})  # twice
    await bus.publish("play:s-live-0001", {"type": "end", "duration": 1.0})
    await asyncio.wait_for(viewer, 2)

    assert [name for name, _ in seen] == ["header", "batch", "end"]  # the repeat is dropped
    assert seen[1][1]["events"] == [[0.0, "o", "$ ls\r\n"]]
