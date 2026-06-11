import asyncio
import unittest

import cache
from cache import CachedJSON


class _FakeClock:
    """Monkeypatchable stand-in for time.time() with manual advance."""

    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class CacheJsonTests(unittest.TestCase):
    def test_cached_json_serializes_compact_payloads(self):
        cache_obj = CachedJSON(ttl=60)

        async def build():
            return {"papers": [{"title": "A", "count": 1}]}

        body, _etag = asyncio.run(cache_obj.get_or_build("k", build))

        self.assertEqual(body, b'{"papers":[{"title":"A","count":1}]}')


class CacheJsonStaleWhileRevalidateTests(unittest.TestCase):
    def setUp(self):
        self._clock = _FakeClock()
        self._orig_time = cache.time.time
        cache.time.time = self._clock

    def tearDown(self):
        cache.time.time = self._orig_time

    def test_stale_entry_served_immediately_and_triggers_bg_refresh(self):
        c = CachedJSON(ttl=10, stale_ttl=100)
        calls = {"n": 0}
        bg_started = asyncio.Event()

        async def build():
            calls["n"] += 1
            return {"v": calls["n"]}

        async def scenario():
            first, _ = await c.get_or_build("k", build)
            self.assertEqual(first, b'{"v":1}')

            # move into the stale window (ttl < age < ttl + stale_ttl)
            self._clock.advance(20)

            # background refresh schedules a task but builds with a slight gate
            async def gated_build():
                bg_started.set()
                calls["n"] += 1
                return {"v": calls["n"]}

            stale_body, _ = await c.get_or_build("k", gated_build)
            # old value returned immediately, not the refreshed one
            self.assertEqual(stale_body, b'{"v":1}')

            # let the scheduled background task run
            await bg_started.wait()
            for _ in range(5):
                await asyncio.sleep(0)

            # next read in the now-fresh window sees refreshed value
            fresh_body, _ = await c.get_or_build("k", build)
            self.assertEqual(fresh_body, b'{"v":2}')

        asyncio.run(scenario())
        self.assertEqual(c.metrics["hit_stale"], 1)
        self.assertGreaterEqual(c.metrics["build_ok"], 2)

    def test_expired_beyond_stale_window_rebuilds_synchronously(self):
        c = CachedJSON(ttl=10, stale_ttl=5)
        calls = {"n": 0}

        async def build():
            calls["n"] += 1
            return {"v": calls["n"]}

        async def scenario():
            await c.get_or_build("k", build)
            # past ttl + stale_ttl: entry expired, must rebuild and wait
            self._clock.advance(100)
            body, _ = await c.get_or_build("k", build)
            self.assertEqual(body, b'{"v":2}')

        asyncio.run(scenario())
        self.assertEqual(calls["n"], 2)
        self.assertEqual(c.metrics["miss"], 2)


class CacheJsonSingleFlightTests(unittest.TestCase):
    def test_concurrent_get_or_build_invokes_builder_once(self):
        c = CachedJSON(ttl=60)
        calls = {"n": 0}
        gate = asyncio.Event()

        async def build():
            calls["n"] += 1
            await gate.wait()
            return {"v": calls["n"]}

        async def scenario():
            t1 = asyncio.create_task(c.get_or_build("k", build))
            t2 = asyncio.create_task(c.get_or_build("k", build))
            # let both tasks register on the same inflight future
            for _ in range(5):
                await asyncio.sleep(0)
            gate.set()
            r1, r2 = await asyncio.gather(t1, t2)
            return r1, r2

        (b1, e1), (b2, e2) = asyncio.run(scenario())
        self.assertEqual(calls["n"], 1)
        self.assertEqual(b1, b'{"v":1}')
        self.assertEqual(b1, b2)
        self.assertEqual(e1, e2)
        self.assertEqual(c.metrics["build_ok"], 1)


class CacheJsonEvictionTests(unittest.TestCase):
    def test_max_keys_evicts_least_recently_used(self):
        c = CachedJSON(ttl=60, max_keys=2)

        def make_builder(val):
            async def build():
                return {"v": val}
            return build

        async def scenario():
            await c.get_or_build("a", make_builder(1))
            await c.get_or_build("b", make_builder(2))
            # touch "a" so "b" becomes least recently used
            await c.get_or_build("a", make_builder(99))
            # inserting "c" evicts "b"
            await c.get_or_build("c", make_builder(3))

        asyncio.run(scenario())
        self.assertEqual(len(c._entries), 2)
        self.assertIn("a", c._entries)
        self.assertIn("c", c._entries)
        self.assertNotIn("b", c._entries)


class CacheJsonWarmTests(unittest.TestCase):
    def setUp(self):
        self._clock = _FakeClock()
        self._orig_time = cache.time.time
        cache.time.time = self._clock

    def tearDown(self):
        cache.time.time = self._orig_time

    def test_warm_prefills_empty_key(self):
        c = CachedJSON(ttl=60)
        calls = {"n": 0}

        async def build():
            calls["n"] += 1
            return {"v": calls["n"]}

        async def scenario():
            await c.warm("k", build)
            # subsequent read is a fresh hit, no rebuild
            body, _ = await c.get_or_build("k", build)
            return body

        body = asyncio.run(scenario())
        self.assertEqual(body, b'{"v":1}')
        self.assertEqual(calls["n"], 1)
        self.assertEqual(c.metrics["warm_ok"], 1)
        self.assertEqual(c.metrics["hit_fresh"], 1)

    def test_warm_skips_when_fresh_entry_exists(self):
        c = CachedJSON(ttl=60)
        calls = {"n": 0}

        async def build():
            calls["n"] += 1
            return {"v": calls["n"]}

        async def scenario():
            await c.get_or_build("k", build)
            await c.warm("k", build)

        asyncio.run(scenario())
        self.assertEqual(calls["n"], 1)
        self.assertEqual(c.metrics["warm_skip"], 1)
        self.assertEqual(c.metrics["warm_ok"], 0)


class CacheJsonStaleOnErrorTests(unittest.TestCase):
    def setUp(self):
        self._clock = _FakeClock()
        self._orig_time = cache.time.time
        cache.time.time = self._clock

    def tearDown(self):
        cache.time.time = self._orig_time

    def test_background_builder_failure_keeps_serving_stale(self):
        c = CachedJSON(ttl=10, stale_ttl=100)
        failed = asyncio.Event()

        async def good_build():
            return {"v": 1}

        async def failing_build():
            failed.set()
            raise RuntimeError("upstream down")

        async def scenario():
            await c.get_or_build("k", good_build)
            self._clock.advance(20)  # into stale window

            stale_body, _ = await c.get_or_build("k", failing_build)
            self.assertEqual(stale_body, b'{"v":1}')

            # let the background refresh run and fail
            await failed.wait()
            for _ in range(5):
                await asyncio.sleep(0)

            # entry must still be present and still stale-servable
            again_body, _ = await c.get_or_build("k", failing_build)
            self.assertEqual(again_body, b'{"v":1}')

        asyncio.run(scenario())
        self.assertIn("k", c._entries)
        self.assertGreaterEqual(c.metrics["build_err"], 1)


if __name__ == "__main__":
    unittest.main()
