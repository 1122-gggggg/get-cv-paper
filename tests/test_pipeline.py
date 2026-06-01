"""Core pipeline contracts: arXiv XML parsing, input validation, probes.

Guards the parse → validate → serve path that every feed depends on, plus the
XML-hardening (defusedxml) and arXiv-id boundary validation added in P3.
"""
import unittest

import clients
import main


_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v1</id>
    <title>A Great Paper (arXiv:2401.12345)</title>
    <summary>We study things in
    great detail.</summary>
    <published>2024-01-15T00:00:00Z</published>
    <author><name>Jane Doe</name></author>
    <author><name>John Roe</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2001.00001v2</id>
    <title>An Older Paper</title>
    <summary>old</summary>
    <published>2020-01-01T00:00:00Z</published>
    <author><name>Old Author</name></author>
  </entry>
</feed>"""

# DTD-defined custom entity: stdlib ET would expand it; defusedxml must reject.
_ENTITY_BOMB = b"""<?xml version="1.0"?>
<!DOCTYPE feed [<!ENTITY x "boom">]>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>1</id><title>&x;</title></entry>
</feed>"""


class ArxivParserTests(unittest.TestCase):
    def test_parses_entry_fields(self):
        papers = clients._parse_arxiv_entries(_ATOM, cutoff=None)
        self.assertEqual(len(papers), 2)
        p = papers[0]
        # "(arXiv:...)" suffix stripped, newline collapsed.
        self.assertEqual(p["title"], "A Great Paper")
        self.assertNotIn("\n", p["summary"])
        self.assertEqual(p["external_ids"], {"arxiv": "2401.12345"})
        self.assertEqual(p["source"], "arxiv")
        self.assertEqual(p["authors"], ["Jane Doe", "John Roe"])

    def test_cutoff_early_stop_drops_old(self):
        from datetime import datetime

        cutoff = datetime(2023, 1, 1)
        papers = clients._parse_arxiv_entries(_ATOM, cutoff=cutoff)
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["external_ids"]["arxiv"], "2401.12345")

    def test_defused_parser_rejects_entity_definition(self):
        # If stdlib ET were used, this would parse and expand &x; to "boom".
        with self.assertRaises(Exception):
            clients._parse_arxiv_entries(_ENTITY_BOMB, cutoff=None)


class ArxivIdValidationTests(unittest.TestCase):
    def test_accepts_new_and_legacy_ids(self):
        good = ["2401.12345", "2401.1234", "2401.12345v3", "cs.AI/0601001", "hep-th/9901001v2"]
        self.assertEqual(main._valid_arxiv_ids(good), good)

    def test_rejects_junk(self):
        bad = ["", "../../etc/passwd", "DROP TABLE", "2401", "abcd.efgh", "<script>"]
        self.assertEqual(main._valid_arxiv_ids(bad), [])

    def test_unique_csv_dedups_and_strips(self):
        out = main._unique_csv(" a, b ,a, , c ", max_items=10)
        self.assertEqual(out, ["a", "b", "c"])


class ArxivListingQueryTests(unittest.TestCase):
    def _capture_query(self, **kwargs) -> str:
        import asyncio

        captured = {}

        class _FakeResp:
            status_code = 200
            content = _ATOM

            def raise_for_status(self):
                return None

        class _FakeClient:
            async def get(self, _url, params=None, timeout=None):
                captured["search_query"] = params["search_query"]
                return _FakeResp()

        asyncio.run(clients.fetch_arxiv_listing(
            _FakeClient(), "cs.CV", 7, 50, **kwargs
        ))
        return captured["search_query"]

    def test_single_cat_plain_query(self):
        self.assertEqual(self._capture_query(), "cat:cs.CV")

    def test_multi_cat_builds_grouped_or(self):
        q = self._capture_query(cats=["cs.LG", "stat.ML"])
        self.assertEqual(q, "(cat:cs.LG OR cat:stat.ML)")

    def test_terms_appended_as_and_clause(self):
        q = self._capture_query(cats=["cs.AI", "cs.MA"], terms="all:agent")
        self.assertEqual(q, "(cat:cs.AI OR cat:cs.MA) AND (all:agent)")


class GithubRepoHelperTests(unittest.TestCase):
    def test_extract_first_repo_from_abstract(self):
        text = "Code at https://github.com/Owner/My-Repo.git and a demo."
        self.assertEqual(
            clients.extract_github_url(text), "https://github.com/Owner/My-Repo"
        )

    def test_extract_skips_non_repo_owners(self):
        text = "See https://github.com/sponsors/foo then https://github.com/o/r ."
        self.assertEqual(clients.extract_github_url(text), "https://github.com/o/r")

    def test_extract_returns_none_when_absent(self):
        self.assertIsNone(clients.extract_github_url("no links here"))
        self.assertIsNone(clients.extract_github_url(None))

    def test_repo_slug_extraction(self):
        self.assertEqual(
            clients.github_repo_slug("https://github.com/Owner/Repo"), "Owner/Repo"
        )
        self.assertIsNone(clients.github_repo_slug(None))


class OpenReviewRatingTests(unittest.TestCase):
    def test_parse_rating_handles_int_and_string(self):
        self.assertEqual(clients._parse_or_rating(6), 6.0)
        self.assertEqual(clients._parse_or_rating("8: accept, good paper"), 8.0)
        self.assertEqual(clients._parse_or_rating("5.5"), 5.5)
        self.assertIsNone(clients._parse_or_rating("no score"))
        self.assertIsNone(clients._parse_or_rating(True))
        self.assertIsNone(clients._parse_or_rating(None))

    def test_ratings_extracted_from_direct_replies(self):
        note = {"details": {"directReplies": [
            {"content": {"rating": {"value": "6: marginally above"}}},
            {"content": {"rating": {"value": 8}}},
            {"content": {"comment": {"value": "nice"}}},  # 非評審,無 rating
        ]}}
        self.assertEqual(clients._openreview_ratings(note), [6.0, 8.0])

    def test_ratings_empty_when_no_reviews(self):
        self.assertEqual(clients._openreview_ratings({}), [])
        self.assertEqual(clients._openreview_ratings({"details": {}}), [])


class PapersSortFilterTests(unittest.TestCase):
    _PAPERS = [
        {"title": "Diffusion models", "summary": "image gen", "authors": ["Ho"],
         "published": "2024-03-01 10:00", "citation_count": 5, "hf_upvotes": 2,
         "github_stars": 100, "review_avg": 7.0},
        {"title": "Mamba state space", "summary": "long context", "authors": ["Gu"],
         "published": "2024-05-02 09:00", "citation_count": 50, "hf_upvotes": 0,
         "github_stars": 9, "review_avg": None},
        {"title": "RLHF tuning", "summary": "alignment work", "authors": ["Lee"],
         "published": "2024-01-10 00:00", "citation_count": 0, "hf_upvotes": 30,
         "review_avg": 8.5},
    ]

    def test_latest_sorts_by_published_desc(self):
        out = main._sort_papers(self._PAPERS, "latest")
        self.assertEqual([p["published"] for p in out],
                         ["2024-05-02 09:00", "2024-03-01 10:00", "2024-01-10 00:00"])

    def test_citations_sort_and_missing_keys_sink(self):
        out = main._sort_papers(self._PAPERS, "citations")
        self.assertEqual(out[0]["title"], "Mamba state space")  # 50 cits first

    def test_unknown_sort_returns_input_unchanged(self):
        out = main._sort_papers(self._PAPERS, "bogus")
        self.assertIs(out, self._PAPERS)

    def test_sort_does_not_mutate_input(self):
        before = [p["title"] for p in self._PAPERS]
        main._sort_papers(self._PAPERS, "citations")
        self.assertEqual([p["title"] for p in self._PAPERS], before)

    def test_filter_matches_title_summary_author(self):
        self.assertEqual(len(main._filter_papers_by_query(self._PAPERS, "mamba")), 1)
        self.assertEqual(len(main._filter_papers_by_query(self._PAPERS, "alignment")), 1)
        self.assertEqual(len(main._filter_papers_by_query(self._PAPERS, "gu")), 1)
        self.assertEqual(len(main._filter_papers_by_query(self._PAPERS, "zzz")), 0)


class ViewBeaconTests(unittest.TestCase):
    def test_beacon_paper_id_prefers_arxiv(self):
        self.assertEqual(main._beacon_paper_id("2401.123", "https://x/1", "T"),
                         "arxiv:2401.123")

    def test_beacon_paper_id_url_fallback(self):
        pid = main._beacon_paper_id("", "https://arxiv.org/abs/2401.5", "T")
        self.assertEqual(pid, "url:https://arxiv.org/abs/2401.5")

    def test_beacon_paper_id_title_fallback(self):
        self.assertTrue(main._beacon_paper_id("", "", "Some Title").startswith("title:"))

    def _client_with_fake_store(self):
        from fastapi.testclient import TestClient

        class _FakeStore:
            def __init__(self):
                self.recorded = []

            def record_view(self, pid, url="", title=""):
                self.recorded.append((pid, url, title))

            def top_viewed(self, days=7, limit=40):
                return [{"title": "Hot", "url": "https://a/1", "view_count": 9}]

        fake = _FakeStore()
        self._orig_store = main._paper_store
        main._paper_store = fake
        main._popular_cache._entries.clear()
        return TestClient(main.app), fake

    def tearDown(self):
        if hasattr(self, "_orig_store"):
            main._paper_store = self._orig_store

    def test_view_beacon_records_and_returns_204(self):
        c, fake = self._client_with_fake_store()
        r = c.post("/api/view", json={"arxiv_id": "2401.7", "url": "https://a/7", "title": "P"})
        self.assertEqual(r.status_code, 204)
        self.assertEqual(fake.recorded[0][0], "arxiv:2401.7")

    def test_view_beacon_rejects_empty(self):
        c, _ = self._client_with_fake_store()
        r = c.post("/api/view", json={})
        self.assertEqual(r.status_code, 400)

    def test_view_beacon_rejects_non_http_url(self):
        c, fake = self._client_with_fake_store()
        r = c.post("/api/view", json={"url": "javascript:alert(1)"})
        self.assertEqual(r.status_code, 400)  # url stripped → empty beacon
        self.assertEqual(fake.recorded, [])

    def test_popular_returns_papers(self):
        c, _ = self._client_with_fake_store()
        r = c.get("/api/popular?days=7&limit=10")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["papers"][0]["view_count"], 9)


class ProbeTests(unittest.TestCase):
    # Plain TestClient (no `with`) skips lifespan → no warmup / no network.
    def test_health_always_ok(self):
        from fastapi.testclient import TestClient

        c = TestClient(main.app)
        r = c.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_ready_503_when_cache_cold(self):
        from fastapi.testclient import TestClient

        main._papers_cache._entries.clear()
        c = TestClient(main.app)
        r = c.get("/api/ready")
        self.assertEqual(r.status_code, 503)


if __name__ == "__main__":
    unittest.main()
