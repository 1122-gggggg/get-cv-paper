"""SSE streaming contract: EventHub pub/sub fan-out + /api/stream framing (#15).

Never opens a real long-lived connection. The route handler's async generator is
driven directly: events are published through the EventHub and frames are pulled
with anext() under asyncio.run. The ping timeout is shrunk and request.is_disconnected
is stubbed so nothing blocks forever.
"""
import asyncio
import unittest

import main
from event_hub import EventHub, _MAX_SUBSCRIBERS


class _FakeRequest:
    """Minimal stand-in for starlette Request: controls disconnect polling."""

    def __init__(self, disconnect_after: int = 10_000) -> None:
        self._calls = 0
        self._disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self._calls += 1
        return self._calls > self._disconnect_after


class EventHubTests(unittest.TestCase):
    def test_subscribe_then_publish_reaches_subscriber(self):
        async def scenario():
            hub = EventHub()
            q = hub.subscribe()
            self.assertIsNotNone(q)
            self.assertEqual(hub.subscriber_count, 1)
            hub.publish({"type": "papers", "disciplines": ["cs.LG"], "at": 1})
            return await q.get()

        event = asyncio.run(scenario())
        self.assertEqual(event["type"], "papers")
        self.assertEqual(event["disciplines"], ["cs.LG"])

    def test_publish_fans_out_to_all_subscribers(self):
        async def scenario():
            hub = EventHub()
            q1 = hub.subscribe()
            q2 = hub.subscribe()
            hub.publish({"type": "papers", "at": 2})
            return await q1.get(), await q2.get()

        e1, e2 = asyncio.run(scenario())
        self.assertEqual(e1, e2)
        self.assertEqual(e1["at"], 2)

    def test_unsubscribe_stops_delivery(self):
        async def scenario():
            hub = EventHub()
            q = hub.subscribe()
            hub.unsubscribe(q)
            self.assertEqual(hub.subscriber_count, 0)
            hub.publish({"type": "papers", "at": 3})
            return q.empty()

        self.assertTrue(asyncio.run(scenario()))

    def test_subscribe_returns_none_at_capacity(self):
        async def scenario():
            hub = EventHub()
            held = [hub.subscribe() for _ in range(_MAX_SUBSCRIBERS)]
            self.assertTrue(all(q is not None for q in held))
            self.assertEqual(hub.subscriber_count, _MAX_SUBSCRIBERS)
            return hub.subscribe()

        self.assertIsNone(asyncio.run(scenario()))

    def test_full_queue_drops_oldest_event(self):
        async def scenario():
            hub = EventHub()
            q = hub.subscribe()
            maxsize = q.maxsize
            for i in range(maxsize):
                hub.publish({"type": "papers", "at": i})
            # Queue is now full; one more publish should evict the oldest (at=0).
            hub.publish({"type": "papers", "at": maxsize})
            drained = [(await q.get())["at"] for _ in range(maxsize)]
            return drained, maxsize

        drained, maxsize = asyncio.run(scenario())
        self.assertEqual(len(drained), maxsize)
        self.assertNotIn(0, drained)
        self.assertIn(maxsize, drained)


class StreamEndpointTests(unittest.TestCase):
    def setUp(self):
        # Replace the module-global hub with a fresh one so tests don't leak
        # subscribers into each other or into the running app.
        self._orig_hub = main._event_hub
        self._orig_ping = main._SSE_PING_S
        main._event_hub = EventHub()
        main._SSE_PING_S = 0.01  # tiny so the heartbeat branch fires fast

    def tearDown(self):
        main._event_hub = self._orig_hub
        main._SSE_PING_S = self._orig_ping

    @staticmethod
    async def _frames(gen, n: int) -> list[bytes]:
        out: list[bytes] = []
        for _ in range(n):
            out.append(await gen.__anext__())
        return out

    def test_first_frame_is_connected_comment(self):
        async def scenario():
            resp = await main.stream(_FakeRequest())
            gen = resp.body_iterator
            first = await gen.__anext__()
            await gen.aclose()
            return first

        first = asyncio.run(scenario())
        self.assertEqual(first, b": connected\n\n")

    def test_published_event_becomes_sse_data_frame(self):
        async def scenario():
            resp = await main.stream(_FakeRequest())
            gen = resp.body_iterator
            connected = await gen.__anext__()
            main._event_hub.publish({"type": "papers", "disciplines": ["cs.LG"], "at": 7})
            frame = await gen.__anext__()
            await gen.aclose()
            return connected, frame

        connected, frame = asyncio.run(scenario())
        self.assertEqual(connected, b": connected\n\n")
        text = frame.decode("utf-8")
        self.assertTrue(text.startswith("data: "))
        self.assertTrue(text.endswith("\n\n"))
        payload = text[len("data: "):-2]
        self.assertIn('"type":"papers"', payload)
        self.assertIn('"at":7', payload)

    def test_heartbeat_ping_emitted_on_idle(self):
        async def scenario():
            resp = await main.stream(_FakeRequest())
            gen = resp.body_iterator
            await gen.__anext__()  # connected
            # No event published → wait_for times out → ping frame.
            ping = await gen.__anext__()
            await gen.aclose()
            return ping

        ping = asyncio.run(scenario())
        self.assertEqual(ping, b": ping\n\n")

    def test_response_is_event_stream_media_type(self):
        async def scenario():
            resp = await main.stream(_FakeRequest())
            await resp.body_iterator.aclose()
            return resp

        resp = asyncio.run(scenario())
        self.assertEqual(resp.media_type, "text/event-stream")
        self.assertEqual(resp.headers.get("cache-control"), "no-cache")

    def test_disconnect_breaks_loop_and_unsubscribes(self):
        async def scenario():
            # Disconnect reported immediately on the first poll inside the loop.
            resp = await main.stream(_FakeRequest(disconnect_after=0))
            gen = resp.body_iterator
            frames = []
            async for chunk in gen:
                frames.append(chunk)
            return frames, main._event_hub.subscriber_count

        frames, remaining = asyncio.run(scenario())
        # Only the initial ": connected" comment before the disconnect break.
        self.assertEqual(frames, [b": connected\n\n"])
        self.assertEqual(remaining, 0)

    def test_capacity_full_returns_503(self):
        async def scenario():
            for _ in range(_MAX_SUBSCRIBERS):
                main._event_hub.subscribe()
            try:
                await main.stream(_FakeRequest())
            except main.HTTPException as exc:
                return exc.status_code
            return None

        self.assertEqual(asyncio.run(scenario()), 503)


if __name__ == "__main__":
    unittest.main()
