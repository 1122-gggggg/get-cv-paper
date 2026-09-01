import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


import main
from paper_store import PaperStore

class _FakeRequest:
    def __init__(self, inm: str | None = None):
        self.headers = {"if-none-match": inm} if inm else {}


class RangeFilterTests(unittest.TestCase):
    def setUp(self):
        self.sample_papers = [
            {
                "title": "Paper 1",
                "summary": "Summary 1",
                "published": "2026-01-01",
                "url": "https://arxiv.org/abs/2601.00001",
                "citation_count": 15,
                "github_stars": 100,
                "hf_upvotes": 5,
                "github_url": "https://github.com/test/repo1",
                "view_count": 10,
                "external_ids": {"arxiv": "2601.00001"},
            },
            {
                "title": "Paper 2",
                "summary": "Summary 2",
                "published": "2026-01-02",
                "url": "https://arxiv.org/abs/2601.00002",
                "citation_count": 5,
                "github_stars": 0,
                "hf_upvotes": 20,
                "github_url": "",
                "view_count": 2,
                "external_ids": {"arxiv": "2601.00002"},
            },
            {
                "title": "Paper 3",
                "summary": "Summary 3",
                "published": "2026-01-03",
                "url": "https://arxiv.org/abs/2601.00003",
                "citation_count": 50,
                "github_stars": 60,
                "hf_upvotes": 0,
                "github_url": "https://github.com/test/repo3",
                "view_count": 8,
                "external_ids": {"arxiv": "2601.00003"},
            },
        ]

    def test_filter_papers_by_metrics_citations(self):
        res = main._filter_papers_by_metrics(self.sample_papers, min_cit=10)
        self.assertEqual(len(res), 2)
        self.assertEqual([p["title"] for p in res], ["Paper 1", "Paper 3"])

        res_bounded = main._filter_papers_by_metrics(self.sample_papers, min_cit=10, max_cit=20)
        self.assertEqual(len(res_bounded), 1)
        self.assertEqual(res_bounded[0]["title"], "Paper 1")

    def test_filter_papers_by_metrics_stars_and_code(self):
        res = main._filter_papers_by_metrics(self.sample_papers, min_stars=50, has_code=True)
        self.assertEqual(len(res), 2)
        self.assertEqual([p["title"] for p in res], ["Paper 1", "Paper 3"])

        res_code_only = main._filter_papers_by_metrics(self.sample_papers, has_code=True)
        self.assertEqual(len(res_code_only), 2)

    def test_filter_papers_by_metrics_views(self):
        res = main._filter_papers_by_metrics(self.sample_papers, min_views=5)
        self.assertEqual(len(res), 2)
        self.assertEqual([p["title"] for p in res], ["Paper 1", "Paper 3"])

        res_views_max = main._filter_papers_by_metrics(self.sample_papers, max_views=5)
        self.assertEqual(len(res_views_max), 1)
        self.assertEqual(res_views_max[0]["title"], "Paper 2")

    def test_filter_papers_by_metrics_hf(self):
        res = main._filter_papers_by_metrics(self.sample_papers, min_hf=10)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["title"], "Paper 2")

    def test_get_papers_endpoint_with_filters(self):
        payload = {"papers": self.sample_papers}
        body_bytes = json.dumps(payload).encode("utf-8")
        etag = "etag-test"

        async def fake_get_or_build(key, builder):
            return body_bytes, etag

        def fake_build_spec(disc, days, mx, topic=""):
            return "test_key", None

        with patch.object(main._papers_cache, "get_or_build", fake_get_or_build), \
             patch.object(main, "_papers_build_spec", fake_build_spec):
            # Test default: no transform, returns original cached body & etag
            resp_default = asyncio.run(
                main.get_papers(request=_FakeRequest(), discipline_id="cv")
            )
            self.assertEqual(resp_default.headers.get("etag"), etag)
            data_default = json.loads(resp_default.body)
            self.assertEqual(len(data_default["papers"]), 3)

            # Test min_citations=10
            resp_cit = asyncio.run(
                main.get_papers(request=_FakeRequest(), discipline_id="cv", min_citations=10)
            )
            data_cit = json.loads(resp_cit.body)
            self.assertEqual(len(data_cit["papers"]), 2)
            self.assertTrue(all(p["citation_count"] >= 10 for p in data_cit["papers"]))

            # Test combined min_views=5 and has_code=True
            resp_combo = asyncio.run(
                main.get_papers(request=_FakeRequest(), min_views=5, has_code=True)
            )
            data_combo = json.loads(resp_combo.body)
            self.assertEqual(len(data_combo["papers"]), 2)
            self.assertTrue(all(p["view_count"] >= 5 and p["github_url"] for p in data_combo["papers"]))

            # Test 304 if-none-match
            fresh_etag = resp_combo.headers.get("etag")
            resp_304 = asyncio.run(
                main.get_papers(request=_FakeRequest(inm=fresh_etag), min_views=5, has_code=True)
            )
            self.assertEqual(resp_304.status_code, 304)

    def test_combined_feed_with_filters(self):
        ids = list(main.DISCIPLINES.keys())[:2]
        a, b = ids[0], ids[1]
        pa = {"papers": [self.sample_papers[0], self.sample_papers[1]]}
        pb = {"papers": [self.sample_papers[1], self.sample_papers[2]]}
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
                main.get_combined_feed(
                    request=_FakeRequest(),
                    fields=f"{a},{b}",
                    min_stars=50,
                )
            )
        data = json.loads(resp.body)
        self.assertTrue(data["combined"])
        self.assertEqual(len(data["papers"]), 2)
        self.assertEqual([p["title"] for p in data["papers"]], ["Paper 3", "Paper 1"])

    def test_paper_store_views_for_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = PaperStore(db_path=Path(tmpdir) / "test.sqlite")
            try:
                store.record_view("arxiv:2601.00001")
                store.record_view("arxiv:2601.00001")
                store.record_view("arxiv:2601.00002")

                res = store.views_for_ids(["arxiv:2601.00001", "arxiv:2601.00002", "arxiv:nonexistent"])
                self.assertEqual(res.get("arxiv:2601.00001"), 2)
                self.assertEqual(res.get("arxiv:2601.00002"), 1)
                self.assertNotIn("arxiv:nonexistent", res)

                single = store.paper_views_count("arxiv:2601.00001")
                self.assertEqual(single, 2)
                single_none = store.paper_views_count("arxiv:nonexistent")
                self.assertEqual(single_none, 0)
            finally:
                store.close()

if __name__ == "__main__":
    unittest.main()
