"""Semantic surface contracts: /api/semantic-search and /api/subtopics.

Every upstream is stubbed: _papers_for_discipline (would hit arXiv) and the
HF-backed rank/cluster coroutines are monkeypatched, and main.HF_TOKEN is
flipped to exercise the feature-enabled vs feature-disabled branches. No network
is ever touched. Plain TestClient(main.app) (no `with`) skips the lifespan so no
warmup fires.
"""
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import main
import semantic


def _client() -> TestClient:
    return TestClient(main.app)


# A tiny synthetic pool — IDs are valid arXiv form so _valid_arxiv_ids passes.
_POOL = [
    {"id": "2401.00001", "title": "Diffusion models for vision", "summary": "a", "published": "2026-06-01"},
    {"id": "2401.00002", "title": "Transformer language pretraining", "summary": "b", "published": "2026-06-01"},
    {"id": "2401.00003", "title": "Graph neural retrieval", "summary": "c", "published": "2026-05-01"},
]


async def _fake_pool(discipline_id: str) -> list[dict]:
    return [dict(p) for p in _POOL]


async def _empty_pool(discipline_id: str) -> list[dict]:
    return []


async def _fake_hybrid(client, query, papers, top_k=30, rrf_k=60):
    return {"papers": [dict(p) for p in papers[:top_k]], "dense": True, "lexical": True}


async def _fake_cluster(client, papers, k=6, min_cluster=3):
    return [
        {"label": "vision", "count": 5, "momentum": 0.2, "sample_titles": ["t1", "t2"]},
        {"label": "language", "count": 4, "momentum": 0.1, "sample_titles": ["t3"]},
    ]


class SemanticSearchTests(unittest.TestCase):
    def test_happy_path_returns_ranked_shape(self):
        with mock.patch.object(main, "HF_TOKEN", "tok"), \
             mock.patch.object(main, "_papers_for_discipline", _fake_pool), \
             mock.patch.object(main, "hybrid_rank", _fake_hybrid):
            r = _client().get("/api/semantic-search?q=diffusion&discipline=cv")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["query"], "diffusion")
        self.assertEqual(body["discipline"], "cv")
        self.assertEqual(body["model"], main.HF_EMBED_MODEL)
        self.assertTrue(body["dense"])
        self.assertTrue(body["lexical"])
        self.assertEqual(body["pool_size"], len(_POOL))
        self.assertEqual(len(body["papers"]), len(_POOL))

    def test_cross_discipline_pools_and_dedups(self):
        with mock.patch.object(main, "HF_TOKEN", "tok"), \
             mock.patch.object(main, "_papers_for_discipline", _fake_pool), \
             mock.patch.object(main, "hybrid_rank", _fake_hybrid):
            r = _client().get("/api/semantic-search?q=neural&cross=true")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["discipline"], "all")
        # dedup across the 4 warmup disciplines collapses identical IDs to one set
        self.assertEqual(body["pool_size"], len(_POOL))

    def test_empty_query_short_circuits_without_token_check(self):
        # blank q returns 200 even with no HF token (no upstream touched)
        with mock.patch.object(main, "HF_TOKEN", ""):
            r = _client().get("/api/semantic-search?q=%20%20")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["papers"], [])
        self.assertEqual(body["query"], "")

    def test_feature_disabled_without_token_is_503(self):
        with mock.patch.object(main, "HF_TOKEN", ""):
            r = _client().get("/api/semantic-search?q=diffusion")
        self.assertEqual(r.status_code, 503)

    def test_garbage_query_still_ranks_gracefully(self):
        # non-empty junk query is a valid request; ranking stub returns a shape
        with mock.patch.object(main, "HF_TOKEN", "tok"), \
             mock.patch.object(main, "_papers_for_discipline", _fake_pool), \
             mock.patch.object(main, "hybrid_rank", _fake_hybrid):
            r = _client().get("/api/semantic-search?q=%24%25%5E%26*%28%29")
        self.assertEqual(r.status_code, 200)
        self.assertIn("papers", r.json())

    def test_ranking_failure_maps_to_502(self):
        async def _boom(client, query, papers, top_k=30, rrf_k=60):
            raise RuntimeError("hf down")

        with mock.patch.object(main, "HF_TOKEN", "tok"), \
             mock.patch.object(main, "_papers_for_discipline", _fake_pool), \
             mock.patch.object(main, "hybrid_rank", _boom):
            r = _client().get("/api/semantic-search?q=diffusion")
        self.assertEqual(r.status_code, 502)


class SubtopicsTests(unittest.TestCase):
    def setUp(self):
        # subtopics is cached; clear so each test sees its own stubbed build
        main._subtopics_cache._entries.clear()

    def test_happy_path_returns_clusters(self):
        with mock.patch.object(main, "HF_TOKEN", "tok"), \
             mock.patch.object(main, "_papers_for_discipline", _fake_pool), \
             mock.patch.object(main, "cluster_papers", _fake_cluster):
            r = _client().get("/api/subtopics?discipline=cv&k=4")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["discipline"], "cv")
        self.assertEqual(len(body["clusters"]), 2)
        self.assertEqual(body["clusters"][0]["label"], "vision")

    def test_feature_disabled_without_token_returns_empty(self):
        with mock.patch.object(main, "HF_TOKEN", ""):
            r = _client().get("/api/subtopics?discipline=cv")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["clusters"], [])
        self.assertEqual(body["reason"], "no_hf_token")

    def test_empty_pool_reports_reason(self):
        with mock.patch.object(main, "HF_TOKEN", "tok"), \
             mock.patch.object(main, "_papers_for_discipline", _empty_pool):
            r = _client().get("/api/subtopics?discipline=cv")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["reason"], "empty_pool")

    def test_cluster_failure_is_graceful(self):
        async def _boom(client, papers, k=6, min_cluster=3):
            raise RuntimeError("embed down")

        with mock.patch.object(main, "HF_TOKEN", "tok"), \
             mock.patch.object(main, "_papers_for_discipline", _fake_pool), \
             mock.patch.object(main, "cluster_papers", _boom):
            r = _client().get("/api/subtopics?discipline=cv")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["reason"], "cluster_failed")


class KMeansTests(unittest.TestCase):
    def test_groups_two_well_separated_clusters(self):
        # two tight clusters in opposite corners of a 2-D space
        vecs = [
            [1.0, 0.0], [0.98, 0.02], [0.95, 0.05],
            [0.0, 1.0], [0.02, 0.98], [0.05, 0.95],
        ]
        assign, centroids = semantic._kmeans(vecs, k=2)
        self.assertEqual(len(assign), len(vecs))
        self.assertEqual(len(centroids), 2)
        # the three near-(1,0) points share a label distinct from the (0,1) trio
        self.assertEqual(len({assign[0], assign[1], assign[2]}), 1)
        self.assertEqual(len({assign[3], assign[4], assign[5]}), 1)
        self.assertNotEqual(assign[0], assign[3])

    def test_k_capped_at_sample_count(self):
        vecs = [[1.0, 0.0], [0.0, 1.0]]
        assign, centroids = semantic._kmeans(vecs, k=5)
        # k is clamped to n; never more centroids than samples
        self.assertEqual(len(centroids), len(vecs))
        self.assertEqual(len(assign), len(vecs))

    def test_empty_input_returns_empty(self):
        assign, centroids = semantic._kmeans([], k=3)
        self.assertEqual(assign, [])
        self.assertEqual(centroids, [])


if __name__ == "__main__":
    unittest.main()
