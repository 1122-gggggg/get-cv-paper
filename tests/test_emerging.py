"""Burst-detection scoring + /api/emerging contract.

Guards the Poisson normalization (a newcomer must outrank an incumbent) and the
endpoint's warming_up contract that the Pulse dashboard depends on.
"""
import unittest

from fastapi.testclient import TestClient

import main
import semantic
from main import _emergence_score


def _delta(cit_new, cit_old, hf_new=0, hf_old=0, pid="p"):
    return {"paper_id": pid, "cit_new": cit_new, "cit_old": cit_old,
            "hf_new": hf_new, "hf_old": hf_old, "date_new": "d2", "date_old": "d1"}


class EmergenceScoreTests(unittest.TestCase):
    def test_newcomer_beats_incumbent(self):
        # 0->5 should score higher than 100->105 (same raw delta, lower baseline).
        newcomer = _emergence_score(_delta(5, 0))
        incumbent = _emergence_score(_delta(105, 100))
        self.assertGreater(newcomer["emergence"], incumbent["emergence"])
        self.assertEqual(newcomer["cit_delta"], 5)

    def test_noise_below_gate(self):
        # 50->51 is one extra citation on a large base: must fall under the z gate.
        s = _emergence_score(_delta(51, 50))
        self.assertLess(s["emergence"], main._EMERGE_MIN)

    def test_negative_delta_clamped(self):
        s = _emergence_score(_delta(3, 9))
        self.assertEqual(s["cit_delta"], 0)
        self.assertEqual(s["emergence"], 0.0)

    def test_hf_contributes(self):
        s = _emergence_score(_delta(0, 0, hf_new=10, hf_old=0))
        self.assertEqual(s["hf_delta"], 10)
        self.assertGreater(s["emergence"], 0)


class RecentShareTests(unittest.TestCase):
    def test_all_recent_is_one(self):
        members = [{"published": "2999-01-01"}, {"published": "2999-01-02"}]
        self.assertEqual(semantic._recent_share(members), 1.0)

    def test_all_old_is_zero(self):
        members = [{"published": "2000-01-01"}, {"published": "2000-01-02"}]
        self.assertEqual(semantic._recent_share(members), 0.0)

    def test_empty(self):
        self.assertEqual(semantic._recent_share([]), 0.0)


class EmergingEndpointTests(unittest.TestCase):
    def test_endpoint_contract(self):
        c = TestClient(main.app)
        r = c.get("/api/emerging")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("papers", body)
        self.assertIsInstance(body["papers"], list)
        self.assertIn("warming_up", body)


if __name__ == "__main__":
    unittest.main()
