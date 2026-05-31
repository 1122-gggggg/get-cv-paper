"""Hybrid recall: BM25 lexical scoring, RRF fusion, multi-centroid rerank.

Guards the two recall guarantees: (1) lexical match surfaces without embeddings,
(2) hybrid_rank degrades to BM25-only on embed outage instead of raising (no 502).
"""
import asyncio
import unittest

import semantic


def _p(pid, title, summary=""):
    return {"id": pid, "title": title, "summary": summary}


_POOL = [
    _p("1", "Diffusion models for image generation", "denoising score matching"),
    _p("2", "Reinforcement learning for robotics control", "policy gradient"),
    _p("3", "Graph neural networks for molecules", "message passing"),
    _p("4", "Fast diffusion sampling via distillation", "consistency models"),
]


class Bm25Tests(unittest.TestCase):
    def test_lexical_match_scores(self):
        scores = semantic._bm25_scores("diffusion sampling", _POOL)
        # papers 1 & 4 mention diffusion; 2 & 3 do not
        self.assertIn(0, scores)
        self.assertIn(3, scores)
        self.assertNotIn(1, scores)
        self.assertNotIn(2, scores)

    def test_empty_query(self):
        self.assertEqual(semantic._bm25_scores("", _POOL), {})

    def test_ranks_are_dense_and_unique(self):
        ranks = semantic._ranks_from_scores({0: 0.9, 3: 0.5, 2: 0.5})
        self.assertEqual(sorted(ranks.values()), [1, 2, 3])
        self.assertEqual(ranks[0], 1)  # highest score → rank 1


class HybridFallbackTests(unittest.TestCase):
    def setUp(self):
        self._saved = semantic.HF_TOKEN
        semantic.HF_TOKEN = ""  # force dense stage to raise → BM25-only path

    def tearDown(self):
        semantic.HF_TOKEN = self._saved

    def test_bm25_only_no_raise(self):
        # client=None is safe: _hf_embed short-circuits on empty HF_TOKEN before use
        res = asyncio.run(semantic.hybrid_rank(None, "diffusion", _POOL, top_k=3))
        self.assertFalse(res["dense"])
        self.assertTrue(res["lexical"])
        self.assertTrue(res["papers"])
        self.assertEqual(res["papers"][0]["id"] in {"1", "4"}, True)
        # fallback path still annotates lexical score, never a 502
        self.assertIn("lexical_score", res["papers"][0])

    def test_empty_pool(self):
        res = asyncio.run(semantic.hybrid_rank(None, "x", [], top_k=3))
        self.assertEqual(res["papers"], [])


class MultiCentroidTests(unittest.TestCase):
    def test_single_centroid_when_few(self):
        vecs = [[1.0, 0.0], [0.0, 1.0]]
        self.assertEqual(len(semantic._multi_centroids(vecs)), 1)

    def test_multiple_centroids_when_many(self):
        vecs = [[1.0, 0.0]] * 3 + [[0.0, 1.0]] * 3
        cents = semantic._multi_centroids(vecs, max_k=3)
        self.assertGreaterEqual(len(cents), 1)
        self.assertLessEqual(len(cents), 3)

    def test_centroid_is_normalized(self):
        c = semantic._mean_centroid([[3.0, 4.0]])
        norm = sum(x * x for x in c) ** 0.5
        self.assertAlmostEqual(norm, 1.0, places=5)


if __name__ == "__main__":
    unittest.main()
