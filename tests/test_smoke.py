"""Deploy smoke + pipeline-contract checks.

These guard the cheapest, highest-value invariants that, if broken, take the
whole site down on the next push: the app importing, critical routes existing,
the cross-source merge contract the frontend depends on, and embedding-prefix
consistency with the configured model.
"""
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from fastapi.testclient import TestClient

import main
import semantic
from dedup import merge_sources


CURRENT_ROUTES = {
    ("GET", "/"),
    ("GET", "/sw.js"),
    ("GET", "/robots.txt"),
    ("GET", "/sitemap.xml"),
    ("GET", "/api/health"),
    ("GET", "/api/ready"),
    ("GET", "/api/papers"),
    ("GET", "/api/feed"),
    ("GET", "/api/stream"),
    ("GET", "/api/trending"),
    ("GET", "/api/emerging"),
    ("GET", "/api/hot"),
    ("GET", "/api/search"),
    ("GET", "/api/semantic-search"),
    ("GET", "/api/disciplines"),
    ("GET", "/api/subtopics"),
    ("GET", "/api/citations"),
    ("GET", "/api/pwc"),
    ("GET", "/api/metrics"),
    ("GET", "/metrics"),
    ("GET", "/api/openreview"),
    ("GET", "/api/reviews"),
    ("POST", "/api/view"),
    ("GET", "/api/popular"),
    ("GET", "/api/author/search"),
    ("GET", "/api/author/{author_id}/papers"),
    ("GET", "/api/bibtex"),
}

REMOVED_ROUTES = {
    "/api/rss",
    "/api/custom",
    "/api/personalized",
    "/api/recommendations",
    "/api/push/key",
    "/api/push/subscribe",
    "/api/push/unsubscribe",
    "/api/push/test",
}


class SmokeTests(unittest.TestCase):
    def test_current_routes_registered_with_expected_methods(self):
        routes = {
            (method, route.path)
            for route in main.app.routes
            for method in (getattr(route, "methods", None) or set())
        }
        missing = CURRENT_ROUTES - routes
        self.assertEqual(missing, set(), f"missing routes: {missing}")


    def test_seo_routes_use_absolute_escaped_request_urls(self):
        client = TestClient(main.app, base_url="https://papers.example.test:8443")
        with patch.object(main, "DISCIPLINES", {"ai&ml": object()}):
            sitemap = client.get("/sitemap.xml")

        self.assertEqual(sitemap.status_code, 200)
        ElementTree.fromstring(sitemap.text)
        self.assertIn("<loc>https://papers.example.test:8443/</loc>", sitemap.text)
        self.assertIn(
            "<loc>https://papers.example.test:8443/?discipline=ai%26ml</loc>",
            sitemap.text,
        )

        robots = client.get("/robots.txt")
        self.assertEqual(robots.status_code, 200)
        self.assertIn(
            "Sitemap: https://papers.example.test:8443/sitemap.xml",
            robots.text,
        )
    def test_removed_subscription_and_recommendation_routes_absent(self):
        paths = {getattr(r, "path", None) for r in main.app.routes}
        present = REMOVED_ROUTES & paths
        self.assertEqual(present, set(), f"removed routes still registered: {present}")

    def test_merge_keeps_higher_priority_primary_and_unions_signals(self):
        openalex = {
            "title": "Scaling Laws for X",
            "url": "https://openalex.org/W1",
            "source": "openalex",
            "external_ids": {"arxiv": "2401.00001"},
            "citation_count": 100,
        }
        arxiv = {
            "title": "Scaling Laws for X",
            "url": "https://arxiv.org/abs/2401.00001",
            "source": "arxiv",
            "citation_count": 5,
            "hf_upvotes": 20,
        }

        merged = merge_sources([openalex], [arxiv])

        self.assertEqual(len(merged), 1)
        item = merged[0]
        # arxiv (priority 0) wins over openalex (priority 1) as primary.
        self.assertEqual(item["url"], "https://arxiv.org/abs/2401.00001")
        # citation_count is the max across sources; hf_upvotes carried over.
        self.assertEqual(item["citation_count"], 100)
        self.assertEqual(item["hf_upvotes"], 20)
        # source becomes a union list.
        self.assertIn("arxiv", item["source"])
        self.assertIn("openalex", item["source"])

    def test_merge_preserves_distinct_papers(self):
        a = {"title": "Paper A", "url": "https://arxiv.org/abs/2401.00001", "source": "arxiv"}
        b = {"title": "Paper B", "url": "https://arxiv.org/abs/2402.00002", "source": "arxiv"}

        merged = merge_sources([a], [b])

        self.assertEqual(len(merged), 2)

    def test_embedding_prefix_matches_model_family(self):
        paper = {"title": "T", "summary": "S"}
        passage = semantic._passage_text(paper)
        query = semantic._query_text("q")
        if semantic._IS_E5:
            self.assertTrue(passage.startswith("passage: "))
            self.assertTrue(query.startswith("query: "))
        else:
            self.assertFalse(passage.startswith("passage: "))
            self.assertFalse(query.startswith("query: "))

    def test_embedding_cache_model_is_versioned(self):
        self.assertIn("#", semantic._EMBED_CACHE_MODEL)
        self.assertTrue(semantic._EMBED_CACHE_MODEL.endswith(semantic._EMBED_VERSION))


if __name__ == "__main__":
    unittest.main()
