import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

import main


class ApiLimitTests(unittest.TestCase):
    def test_unique_csv_preserves_order_and_enforces_limit(self):
        self.assertEqual(main._unique_csv(" 1,2,1,,3 ", max_items=3), ["1", "2", "3"])

        with self.assertRaises(HTTPException) as ctx:
            main._unique_csv("1,2,3,4", max_items=3)

        self.assertEqual(ctx.exception.status_code, 400)

    def test_bounded_int_clamps_invalid_and_extreme_values(self):
        self.assertEqual(main._bounded_int("bad", default=7, min_value=1, max_value=10), 7)
        self.assertEqual(main._bounded_int(-50, default=7, min_value=1, max_value=10), 1)
        self.assertEqual(main._bounded_int(5000, default=7, min_value=1, max_value=10), 10)

    def test_search_clamps_upstream_max_results(self):
        seen = {}

        async def fake_search(_client, q, max_results):
            seen["q"] = q
            seen["max_results"] = max_results
            return []

        with patch.object(main, "fetch_arxiv_search", fake_search):
            result = asyncio.run(main.search_papers(" diffusion ", max_results=9999))

        self.assertEqual(result, {"papers": []})
        self.assertEqual(seen, {"q": "diffusion", "max_results": main._SEARCH_MAX_RESULTS})

    def test_canonical_max_collapses_user_and_warmup_to_same_bucket(self):
        # 使用者 50 與語意召回/warmup 80 必須落入同一桶,cache key 才會一致
        self.assertEqual(main._canonical_max(50), main._canonical_max(main._WARMUP_MAX))
        self.assertEqual(main._canonical_max(50), 80)
        self.assertEqual(main._canonical_max(1), 80)
        self.assertEqual(main._canonical_max(80), 80)
        self.assertEqual(main._canonical_max(81), 200)
        self.assertEqual(main._canonical_max(1000), 1000)
        self.assertEqual(main._canonical_max(99999), 5000)

    def test_build_spec_cache_key_aligns_user_request_with_warmup(self):
        user_key, _ = main._papers_build_spec(main.DEFAULT_DISCIPLINE, main._WARMUP_DAYS, 50)
        warm_key, _ = main._papers_build_spec(
            main.DEFAULT_DISCIPLINE, main._WARMUP_DAYS, main._WARMUP_MAX
        )
        self.assertEqual(user_key, warm_key)

    def test_pwc_rejects_too_many_ids_before_fetching(self):
        too_many = ",".join(str(i) for i in range(main._PWC_IDS_MAX + 1))

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(main.get_pwc(request=None, arxiv_ids=too_many))

        self.assertEqual(ctx.exception.status_code, 400)



class ApiQueryBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_oversized_public_query_values_return_422(self):
        cases = (
            ("/api/papers", {"q": "x" * 257}),
            ("/api/papers", {"topic": "x" * 65}),
            ("/api/feed", {"q": "x" * 257, "fields": "ml"}),
            ("/api/feed", {"fields": "x" * 257}),
            ("/api/search", {"q": "x" * 257}),
            ("/api/semantic-search", {"q": "x" * 257}),
            ("/api/author/search", {"q": "x" * 201}),
        )

        for path, params in cases:
            with self.subTest(path=path, params=params):
                self.assertEqual(self.client.get(path, params=params).status_code, 422)

    def test_author_query_keeps_two_character_minimum(self):
        self.assertEqual(self.client.get("/api/author/search", params={"q": "x"}).status_code, 422)


class PaperUrlBoundaryTests(unittest.TestCase):
    def test_serializers_remove_unsafe_navigation_urls(self):
        paper = {
            "title": "Unsafe paper",
            "summary": "Summary",
            "url": "javascript:alert(1)",
            "github_url": "https://user:pass@github.com/org/repo",
        }

        self.assertEqual(main._slim_paper(paper)["url"], "")
        self.assertNotIn("github_url", main._slim_paper(paper))
        compact = main._ssr_compact(paper)
        self.assertEqual(compact["url"], "")
        self.assertEqual(compact["github_url"], "")

    def test_view_beacon_drops_credential_url(self):
        class Store:
            def __init__(self):
                self.calls = []

            def record_view(self, paper_id, url="", title=""):
                self.calls.append((paper_id, url, title))

        store = Store()
        with patch.object(main, "_paper_store", store):
            response = TestClient(main.app).post(
                "/api/view",
                json={
                    "url": "https://user:pass@arxiv.org/abs/2401.00001",
                    "title": "Credentialed URL",
                },
            )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(store.calls[0][1], "")


if __name__ == "__main__":
    unittest.main()
