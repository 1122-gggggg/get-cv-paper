"""Offline contract for the in-process SSE EventHub."""
import unittest

from event_hub import _MAX_SUBSCRIBERS, _QUEUE_MAXSIZE, EventHub


class EventHubTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_fans_out_to_all_subscribers(self):
        hub = EventHub()
        q1 = hub.subscribe()
        q2 = hub.subscribe()
        self.assertEqual(hub.subscriber_count, 2)
        hub.publish({"type": "papers", "disciplines": ["cv"]})
        self.assertEqual((await q1.get())["disciplines"], ["cv"])
        self.assertEqual((await q2.get())["disciplines"], ["cv"])

    async def test_unsubscribe_stops_delivery(self):
        hub = EventHub()
        q = hub.subscribe()
        hub.unsubscribe(q)
        self.assertEqual(hub.subscriber_count, 0)
        hub.publish({"type": "papers"})
        self.assertTrue(q.empty())

    async def test_full_queue_drops_oldest(self):
        hub = EventHub()
        q = hub.subscribe()
        for i in range(_QUEUE_MAXSIZE + 3):
            hub.publish({"type": "papers", "n": i})
        # queue is capped; oldest events were dropped so newest survives
        self.assertEqual(q.qsize(), _QUEUE_MAXSIZE)
        drained = [q.get_nowait()["n"] for _ in range(_QUEUE_MAXSIZE)]
        self.assertEqual(drained[-1], _QUEUE_MAXSIZE + 2)  # last published kept
        self.assertNotIn(0, drained)  # oldest dropped

    async def test_capacity_cap_returns_none(self):
        hub = EventHub()
        subs = [hub.subscribe() for _ in range(_MAX_SUBSCRIBERS)]
        self.assertTrue(all(s is not None for s in subs))
        self.assertIsNone(hub.subscribe())  # over capacity


if __name__ == "__main__":
    unittest.main()
