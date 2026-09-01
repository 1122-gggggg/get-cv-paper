import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cache
from cache import CachedJSON, LRUStore


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


    def test_etag_response_headers_and_304(self):
        from starlette.requests import Request
        from cache import etag_response, make_etag, _DEFAULT_CACHE_HEADERS

        self.assertIn("stale-while-revalidate=60", _DEFAULT_CACHE_HEADERS["Cache-Control"])
        self.assertIn("stale-if-error=120", _DEFAULT_CACHE_HEADERS["Cache-Control"])

        body = b'{"hello":"world"}'
        etag = make_etag(body)

        # Regular request
        req = Request({"type": "http", "method": "GET", "headers": []})
        resp = etag_response(req, body, etag)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("etag"), etag)
        self.assertEqual(resp.headers.get("cdn-cache-control"), "public, max-age=30, stale-while-revalidate=120")
        self.assertIn("stale-while-revalidate=60", resp.headers.get("cache-control", ""))
        self.assertIn("stale-if-error=120", resp.headers.get("cache-control", ""))

        # 304 match
        req_304 = Request({"type": "http", "method": "GET", "headers": [(b"if-none-match", etag.encode("utf-8"))]})
        resp_304 = etag_response(req_304, body, etag)
        self.assertEqual(resp_304.status_code, 304)
        self.assertEqual(resp_304.headers.get("etag"), etag)
        self.assertEqual(resp_304.headers.get("cdn-cache-control"), "public, max-age=30, stale-while-revalidate=120")

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



class LRUStorePersistenceTests(unittest.TestCase):
    def test_malformed_persisted_json_is_ignored_and_length_is_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            (cache_dir / "s2.json").write_text("{not json", encoding="utf-8")

            store = LRUStore("s2", maxsize=2, ttl=60, cache_dir=cache_dir)

            self.assertEqual(len(store), 0)
            self.assertIsNone(store.get("missing"))

    def test_load_filters_invalid_entries_and_caps_lru_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            (cache_dir / "s2.json").write_text(
                (
                    '{"invalid":{"at":"now","v":"bad"},'
                    '"old":{"at":1,"v":"old"},'
                    '"new":{"at":2,"v":"new"}}'
                ),
                encoding="utf-8",
            )

            store = LRUStore("s2", maxsize=1, ttl=0, cache_dir=cache_dir)

            self.assertEqual(len(store), 1)
            self.assertIsNone(store.get("old"))
            self.assertEqual(store.get("new"), "new")

    def test_flush_keeps_dirty_state_when_new_write_arrives_mid_flush(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            store = LRUStore("s2", maxsize=2, ttl=60, cache_dir=cache_dir)
            store.set("existing", "old")
            original_write_text = Path.write_text
            wrote_new_value = False

            def write_snapshot(path, text, *args, **kwargs):
                nonlocal wrote_new_value
                if not wrote_new_value and path == store.path.with_suffix(".tmp"):
                    wrote_new_value = True
                    store.set("new", "value")
                return original_write_text(path, text, *args, **kwargs)

            with patch.object(Path, "write_text", write_snapshot):
                store.flush()

            self.assertTrue(store._dirty)
            store.flush()
            restored = LRUStore("s2", maxsize=2, ttl=60, cache_dir=cache_dir)
            self.assertEqual(restored.get("new"), "value")


if __name__ == "__main__":
    unittest.main()
