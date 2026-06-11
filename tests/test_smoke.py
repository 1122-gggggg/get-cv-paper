"""Deploy smoke + pipeline-contract checks.

These guard the cheapest, highest-value invariants that, if broken, take the
whole site down on the next push: the app importing, critical routes existing,
the cross-source merge contract the frontend depends on, and embedding-prefix
consistency with the configured model.
"""
import unittest

import main
import semantic
from dedup import merge_sources


CRITICAL_ROUTES = {
    "/api/health",
    "/api/papers",
    "/api/trending",
    "/api/emerging",
    "/api/search",
    "/api/subtopics",
    "/api/metrics",
    "/metrics",
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
    def test_critical_routes_registered(self):
        paths = {getattr(r, "path", None) for r in main.app.routes}
        missing = CRITICAL_ROUTES - paths
        self.assertEqual(missing, set(), f"missing routes: {missing}")

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
