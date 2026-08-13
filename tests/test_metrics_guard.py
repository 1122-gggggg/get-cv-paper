"""Auth contract for the /metrics Prometheus endpoint (_metrics_guard).

Fail-closed: with METRICS_KEY set, the exact key is required; without a key
configured, only loopback clients are allowed so a misconfigured prod deploy
never exposes internals at the public edge. Guard reads the module-level
main._METRICS_KEY at request time, so tests monkeypatch that directly.

Plain TestClient (no `with`) skips the network-touching lifespan.
"""
import unittest

from fastapi.testclient import TestClient

import main


class MetricsGuardKeySetTests(unittest.TestCase):
    """METRICS_KEY configured → exact Authorization bearer token required."""

    def setUp(self):
        self._orig = main._METRICS_KEY
        main._METRICS_KEY = "s3cret-metrics-key"

    def tearDown(self):
        main._METRICS_KEY = self._orig

    def test_missing_bearer_token_is_rejected(self):
        c = TestClient(main.app)
        r = c.get("/metrics")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.headers.get("www-authenticate"), "Bearer")

    def test_query_key_is_rejected(self):
        c = TestClient(main.app)
        r = c.get("/metrics", params={"key": "s3cret-metrics-key"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.headers.get("www-authenticate"), "Bearer")

    def test_correct_bearer_returns_200_text(self):
        c = TestClient(main.app)
        r = c.get("/metrics", headers={"Authorization": "Bearer s3cret-metrics-key"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("text/plain"))
        # Exposition format always emits at least one HELP header line.
        self.assertIn("# HELP", r.text)

    def test_api_metrics_uses_the_same_bearer_guard(self):
        c = TestClient(main.app)
        rejected = c.get("/api/metrics", params={"key": "s3cret-metrics-key"})
        accepted = c.get("/api/metrics", headers={"Authorization": "Bearer s3cret-metrics-key"})

        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(rejected.headers.get("www-authenticate"), "Bearer")
        self.assertEqual(accepted.status_code, 200)


class MetricsGuardNoKeyTests(unittest.TestCase):
    """No METRICS_KEY configured → loopback-only (fail-closed default)."""

    def setUp(self):
        self._orig = main._METRICS_KEY
        main._METRICS_KEY = ""

    def tearDown(self):
        main._METRICS_KEY = self._orig

    def test_non_loopback_client_is_rejected(self):
        # Default TestClient client host is "testclient" (not loopback).
        c = TestClient(main.app)
        r = c.get("/metrics")
        self.assertEqual(r.status_code, 403)

    def test_loopback_client_is_allowed(self):
        c = TestClient(main.app, client=("127.0.0.1", 50000))
        r = c.get("/metrics")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("text/plain"))

    def test_query_key_is_ignored_for_non_loopback(self):
        # A supplied key must not bypass the loopback gate when none is set.
        c = TestClient(main.app)
        r = c.get("/metrics", params={"key": "anything"})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
