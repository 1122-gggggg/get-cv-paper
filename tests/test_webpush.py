"""Web-Push subscription store + endpoint contract (#19)."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from paper_store import PaperStore


class _FakeRequest:
    def __init__(self, body: bytes):
        self._body = body

    async def body(self) -> bytes:
        return self._body


class PushStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = PaperStore(Path(self._tmp.name) / "t.sqlite")

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_upsert_list_and_delete(self):
        self.store.upsert_push_sub("https://a/1", "p1", "a1", "cv,ml")
        self.store.upsert_push_sub("https://a/2", "p2", "a2", "")
        subs = {s["endpoint"]: s for s in self.store.all_push_subs()}
        self.assertEqual(self.store.count_push_subs(), 2)
        self.assertEqual(subs["https://a/1"]["fields"], "cv,ml")
        self.assertIsNone(subs["https://a/1"]["last_sent"])

        # upsert same endpoint replaces fields
        self.store.upsert_push_sub("https://a/1", "p1b", "a1b", "nlp")
        self.assertEqual(self.store.count_push_subs(), 2)
        self.assertEqual(
            {s["endpoint"]: s["fields"] for s in self.store.all_push_subs()}["https://a/1"],
            "nlp",
        )

        self.store.mark_push_sent(["https://a/1"])
        self.assertIsNotNone(
            {s["endpoint"]: s["last_sent"] for s in self.store.all_push_subs()}["https://a/1"]
        )

        self.store.delete_push_sub("https://a/2")
        self.assertEqual(self.store.count_push_subs(), 1)

    def test_upsert_ignores_incomplete(self):
        self.store.upsert_push_sub("", "p", "a", "")
        self.store.upsert_push_sub("https://a/x", "", "a", "")
        self.assertEqual(self.store.count_push_subs(), 0)


class PushEndpointTests(unittest.TestCase):
    def test_clean_fields_filters_and_caps(self):
        ids = list(main.DISCIPLINES.keys())
        raw = [ids[0], ids[1], ids[0], "__nope__", ids[2]]
        self.assertEqual(main._clean_fields(raw), f"{ids[0]},{ids[1]},{ids[2]}")
        self.assertEqual(main._clean_fields("not-a-list"), "")
        self.assertEqual(len(main._clean_fields(ids[:50]).split(",")), main._PUSH_FIELDS_MAX)

    def test_key_endpoint_reports_disabled_state(self):
        with patch.object(main.push_service, "enabled", False), \
             patch.object(main.push_service, "_public", ""):
            out = asyncio.run(main.push_key())
            self.assertFalse(out["enabled"])

    def test_subscribe_noop_when_disabled(self):
        with patch.object(main.push_service, "enabled", False):
            body = json.dumps({"subscription": {"endpoint": "https://x/1",
                              "keys": {"p256dh": "p", "auth": "a"}}}).encode()
            out = asyncio.run(main.push_subscribe(_FakeRequest(body)))
            self.assertEqual(out, {"ok": False, "enabled": False})

    def test_digest_payload_prefers_matched_fields(self):
        hot = {"papers": [
            {"title": "A", "url": "u1", "fields": ["ml"]},
            {"title": "B", "url": "u2", "fields": ["cv"]},
        ]}
        out = main._digest_payload_for(["cv"], hot)
        self.assertIn("B", out["body"])
        self.assertEqual(out["url"], "u2")
        # no papers → None
        self.assertIsNone(main._digest_payload_for(["cv"], {"papers": []}))


if __name__ == "__main__":
    unittest.main()
