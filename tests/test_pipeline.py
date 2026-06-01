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
