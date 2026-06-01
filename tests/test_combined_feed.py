import asyncio
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException

import main


class _FakeRequest:
    def __init__(self, inm: str | None = None):
        self.headers = {"if-none-match": inm} if inm else {}


class CombinedFeedTests(unittest.TestCase):
    def test_valid_field_ids_dedups_filters_unknown_and_caps(self):
        ids = list(main.DISCIPLINES.keys())
        a, b, c = ids[0], ids[1], ids[2]
        raw = f" {a}, {b} , {a}, __nope__, {c} "
        self.assertEqual(main._valid_field_ids(raw), [a, b, c])

        many = ",".join(ids[: main._FEED_MAX_FIELDS + 3])
        self.assertEqual(len(main._valid_field_ids(many)), main._FEED_MAX_FIELDS)

        self.assertEqual(main._valid_field_ids("nope,??,"), [])

    def test_combined_feed_rejects_empty_or_unknown(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(main.get_combined_feed(request=_FakeRequest(), fields="__x__"))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_combined_feed_merges_dedups_tags_and_sorts(self):
        ids = list(main.DISCIPLINES.keys())[:2]
        a, b = ids[0], ids[1]
        pa = {"papers": [
            {"title": "Shared", "url": "u1", "external_ids": {"arxiv": "2401.00001"}, "published": "2024-01-02"},
            {"title": "OnlyA", "url": "u2", "external_ids": {"arxiv": "2401.00002"}, "published": "2024-01-05"},
        ]}
        pb = {"papers": [
            {"title": "Shared", "url": "u1", "external_ids": {"arxiv": "2401.00001"}, "published": "2024-01-02"},
            {"title": "OnlyB", "url": "u3", "external_ids": {"arxiv": "2401.00003"}, "published": "2024-01-01"},
        ]}
        bodies = {
            a: json.dumps(pa).encode("utf-8"),
            b: json.dumps(pb).encode("utf-8"),
        }

        def fake_build_spec(fid, days, mx, topic=""):
            return fid, None

        async def fake_get_or_build(key, builder):
            return bodies[key], "etag-" + key

        with patch.object(main, "_papers_build_spec", fake_build_spec), \
             patch.object(main._papers_cache, "get_or_build", fake_get_or_build):
            resp = asyncio.run(
                main.get_combined_feed(request=_FakeRequest(), fields=f"{a},{b}", sort="latest")
            )

        payload = json.loads(resp.body)
        self.assertTrue(payload["combined"])
        self.assertEqual(payload["fields"], [a, b])
        # Shared paper deduped → 3 unique
        self.assertEqual(payload["count"], 3)
        titles = [p["title"] for p in payload["papers"]]
        # latest sort → OnlyA (01-05) > Shared (01-02) > OnlyB (01-01)
        self.assertEqual(titles, ["OnlyA", "Shared", "OnlyB"])
        shared = next(p for p in payload["papers"] if p["title"] == "Shared")
        self.assertEqual(shared["fields"], [a, b])

    def test_combined_feed_survives_one_field_failure(self):
        ids = list(main.DISCIPLINES.keys())[:2]
        a, b = ids[0], ids[1]
        good = {"papers": [
            {"title": "Good", "url": "g1", "external_ids": {"arxiv": "2402.00001"}, "published": "2024-02-01"},
        ]}

        def fake_build_spec(fid, days, mx, topic=""):
            return fid, None

        async def fake_get_or_build(key, builder):
            if key == b:
                raise RuntimeError("pool down")
            return json.dumps(good).encode("utf-8"), "etag"

        with patch.object(main, "_papers_build_spec", fake_build_spec), \
             patch.object(main._papers_cache, "get_or_build", fake_get_or_build):
            resp = asyncio.run(
                main.get_combined_feed(request=_FakeRequest(), fields=f"{a},{b}")
            )

        payload = json.loads(resp.body)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["papers"][0]["title"], "Good")


if __name__ == "__main__":
    unittest.main()
