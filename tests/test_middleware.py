"""Pure-ASGI middleware contract: security headers + per-IP rate limiting.

These guard the P1-B conversion from BaseHTTPMiddleware to raw ASGI — the
conversion that unblocks streaming/SSE. If the send-wrapper plumbing regresses,
headers silently vanish or the limiter stops counting; both are caught here.
"""
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

import main
from main import RateLimitMiddleware


class SecurityHeaderTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_security_headers_present_on_api(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("x-content-type-options"), "nosniff")
        self.assertIn("max-age=", r.headers.get("strict-transport-security", ""))
        self.assertEqual(r.headers.get("x-frame-options"), "SAMEORIGIN")

    def test_csp_present_and_has_no_stale_google_origins(self):
        csp = self.client.get("/api/health").headers.get("content-security-policy", "")
        self.assertIn("default-src 'self'", csp)
        self.assertIn("frame-ancestors 'self'", csp)
        self.assertNotIn("accounts.google.com", csp)
        self.assertNotIn("apis.google.com", csp)


class RateLimitTests(unittest.TestCase):
    @staticmethod
    def _client(burst: int, path: str = "/api/x") -> TestClient:
        app = FastAPI()

        @app.get(path)
        def _h():
            return {"ok": True}

        app.add_middleware(RateLimitMiddleware, burst=burst)
        return TestClient(app)

    def test_burst_then_429(self):
        c = self._client(burst=2)
        self.assertEqual(c.get("/api/x").status_code, 200)
        self.assertEqual(c.get("/api/x").status_code, 200)
        r = c.get("/api/x")
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["detail"], "rate limited")
        self.assertTrue(r.headers.get("retry-after"))

    def test_health_is_exempt(self):
        c = self._client(burst=1, path="/api/health")
        for _ in range(4):
            self.assertEqual(c.get("/api/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()
