"""Offline contract for the in-process SSE EventHub."""
import asyncio
import threading
import unittest
from unittest.mock import patch

import event_hub
from event_hub import _MAX_SUBSCRIBERS, _QUEUE_MAXSIZE, EventHub


class EventHubTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_fans_out_to_all_subscribers(self):
        hub = EventHub()
        q1 = hub.subscribe()
        q2 = hub.subscribe()
        self.assertIsNotNone(q1)
        self.assertIsNotNone(q2)
        self.assertEqual(hub.subscriber_count, 2)
        hub.publish({"type": "papers", "disciplines": ["cv"]})
        self.assertEqual((await q1.get())["disciplines"], ["cv"])
        self.assertEqual((await q2.get())["disciplines"], ["cv"])

    async def test_each_subscriber_receives_an_independent_mapping(self):
        hub = EventHub()
        q1 = hub.subscribe()
        q2 = hub.subscribe()
        self.assertIsNotNone(q1)
        self.assertIsNotNone(q2)

        hub.publish({"type": "papers", "disciplines": ["cv"]})
        first = await q1.get()
        second = await q2.get()
        first["type"] = "mutated"
        first["disciplines"].append("ml")

        self.assertEqual(second["type"], "papers")
        self.assertEqual(second["disciplines"], ["cv"])

    async def test_publish_from_worker_thread_wakes_subscriber(self):
        owner_thread = threading.get_ident()

        class OwnerThreadQueue(asyncio.Queue):
            def put_nowait(self, item):
                if threading.get_ident() != owner_thread:
                    raise RuntimeError("queue delivery ran outside its owner thread")
                return super().put_nowait(item)

        hub = EventHub()
        with patch.object(event_hub.asyncio, "Queue", OwnerThreadQueue):
            q = hub.subscribe()
        self.assertIsNotNone(q)
        errors: list[BaseException] = []

        def publish_from_worker() -> None:
            try:
                hub.publish({"type": "papers", "at": 7})
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=publish_from_worker)
        worker.start()
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])

        event = await asyncio.wait_for(q.get(), timeout=1)
        self.assertEqual(event["at"], 7)

    async def test_unsubscribe_stops_delivery(self):
        hub = EventHub()
        q = hub.subscribe()
        self.assertIsNotNone(q)
        hub.unsubscribe(q)
        self.assertEqual(hub.subscriber_count, 0)
        hub.publish({"type": "papers"})
        self.assertTrue(q.empty())

    async def test_full_queue_drops_oldest(self):
        hub = EventHub()
        q = hub.subscribe()
        self.assertIsNotNone(q)
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
