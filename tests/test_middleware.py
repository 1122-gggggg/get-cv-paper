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


    def test_vary_and_cache_control_on_api_endpoints(self):
        r_health = self.client.get("/api/health")
        self.assertEqual(r_health.status_code, 200)
        self.assertIn("stale-while-revalidate=60", r_health.headers.get("cache-control", ""))

        r_papers = self.client.get("/api/papers?discipline=cv")
        self.assertEqual(r_papers.status_code, 200)
        self.assertIn("Accept-Encoding", r_papers.headers.get("vary", ""))
        self.assertIn("stale-while-revalidate=60", r_papers.headers.get("cache-control", ""))
        self.assertIn("stale-if-error=120", r_papers.headers.get("cache-control", ""))
        self.assertIn("public, max-age=30, stale-while-revalidate=120", r_papers.headers.get("cdn-cache-control", ""))
        self.assertTrue(r_papers.headers.get("etag"))

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


class ClientIpPrecedenceTests(unittest.TestCase):
    """Proxy headers are only eligible after an explicit trusted-proxy opt-in."""

    @staticmethod
    def _scope(headers, client=("198.51.100.7", 55555)):
        return {
            "type": "http",
            "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in headers],
            "client": client,
        }

    def test_default_ignores_spoofable_proxy_headers(self):
        scope = self._scope([
            ("x-forwarded-for", "1.2.3.4, 9.9.9.9"),
            ("fly-client-ip", "203.0.113.42"),
        ])
        self.assertEqual(RateLimitMiddleware._client_ip(scope, trust_proxy_headers=False), "198.51.100.7")

    def test_trusted_fly_header_wins_over_xff(self):
        scope = self._scope([
            ("x-forwarded-for", "1.2.3.4, 9.9.9.9"),
            ("fly-client-ip", "203.0.113.42"),
        ])
        self.assertEqual(RateLimitMiddleware._client_ip(scope, trust_proxy_headers=True), "203.0.113.42")

    def test_trusted_xff_uses_first_valid_hop(self):
        scope = self._scope([("x-forwarded-for", "203.0.113.9, 9.9.9.9")])
        self.assertEqual(RateLimitMiddleware._client_ip(scope, trust_proxy_headers=True), "203.0.113.9")

    def test_invalid_proxy_values_fall_back_to_client_host(self):
        scope = self._scope([
            ("fly-client-ip", "not-an-ip"),
            ("x-forwarded-for", "also-not-an-ip, 203.0.113.9"),
        ])
        self.assertEqual(RateLimitMiddleware._client_ip(scope, trust_proxy_headers=True), "198.51.100.7")

    def test_unknown_when_no_client_and_no_headers(self):
        scope = self._scope([], client=None)
        self.assertEqual(RateLimitMiddleware._client_ip(scope, trust_proxy_headers=False), "unknown")

    def test_trust_proxy_headers_defaults_to_false(self):
        middleware = RateLimitMiddleware(FastAPI())
        self.assertFalse(middleware.trust_proxy_headers)


class SlotRefundTests(unittest.TestCase):
    """A 5xx response refunds its reserved slot so failures stay free and do not
    permanently consume the burst budget (see the >=500 branch in __call__)."""

    @staticmethod
    def _client(burst: int):
        app = FastAPI()

        @app.get("/api/boom")
        def _boom():
            from fastapi import HTTPException
            raise HTTPException(status_code=500, detail="kaboom")

        @app.get("/api/ok")
        def _ok():
            return {"ok": True}

        app.add_middleware(RateLimitMiddleware, burst=burst)
        # raise_server_exceptions=False so the 500 flows through the ASGI stack
        # (and the send-wrapper sees status 500) instead of bubbling into the test.
        return TestClient(app, raise_server_exceptions=False)

    def test_5xx_refunds_slot_and_does_not_exhaust_burst(self):
        c = self._client(burst=2)
        # Far more 5xx hits than the burst budget; if refund regressed this 429s.
        for _ in range(6):
            self.assertEqual(c.get("/api/boom").status_code, 500)
        # Budget never consumed by the failures, so a good request still passes.
        self.assertEqual(c.get("/api/ok").status_code, 200)

    def test_2xx_does_consume_budget(self):
        # Control: successful requests are NOT refunded — burst of 1 yields one 200
        # then a 429, proving the refund path is specific to 5xx.
        c = self._client(burst=1)
        self.assertEqual(c.get("/api/ok").status_code, 200)
        self.assertEqual(c.get("/api/ok").status_code, 429)


    def test_weighted_5xx_refunds_all_reserved_slots(self):
        app = FastAPI()

        @app.post("/api/view")
        def _boom():
            from fastapi import HTTPException
            raise HTTPException(status_code=500, detail="kaboom")

        @app.get("/api/ok")
        def _ok():
            return {"ok": True}

        app.add_middleware(RateLimitMiddleware, burst=10)
        c = TestClient(app, raise_server_exceptions=False)
        for _ in range(3):
            self.assertEqual(c.post("/api/view").status_code, 500)
        self.assertEqual(c.get("/api/ok").status_code, 200)


class CostWeightingTests(unittest.TestCase):
    @staticmethod
    def _client(burst: int, path: str, method: str = "GET") -> TestClient:
        app = FastAPI()

        @app.api_route(path, methods=[method])
        def _h():
            return {"ok": True}

        app.add_middleware(RateLimitMiddleware, burst=burst)
        return TestClient(app)

    def test_search_reserves_three_slots(self):
        c = self._client(burst=5, path="/api/search")
        self.assertEqual(c.get("/api/search").status_code, 200)
        rejected = c.get("/api/search")
        self.assertEqual(rejected.status_code, 429)
        self.assertGreaterEqual(int(rejected.headers["retry-after"]), 59)

    def test_semantic_search_reserves_five_slots(self):
        c = self._client(burst=5, path="/api/semantic-search")
        self.assertEqual(c.get("/api/semantic-search").status_code, 200)
        self.assertEqual(c.get("/api/semantic-search").status_code, 429)

    def test_view_post_reserves_ten_slots(self):
        c = self._client(burst=10, path="/api/view", method="POST")
        self.assertEqual(c.post("/api/view").status_code, 200)
        self.assertEqual(c.post("/api/view").status_code, 429)

    def test_default_path_reserves_one_slot(self):
        c = self._client(burst=2, path="/api/papers")
        self.assertEqual(c.get("/api/papers").status_code, 200)
        self.assertEqual(c.get("/api/papers").status_code, 200)
        self.assertEqual(c.get("/api/papers").status_code, 429)

if __name__ == "__main__":
    unittest.main()
