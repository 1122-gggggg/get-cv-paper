"""Offline contract for the OAI-PMH harvester parser + set mapping + store state."""
import asyncio
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from oai_harvest import cat_to_oai_set, harvest_arxiv_oai, parse_oai_records
from paper_store import PaperStore

_PAGE_WITH_TOKEN = b"""<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <responseDate>2026-06-01T00:00:00Z</responseDate>
  <request verb="ListRecords" metadataPrefix="arXiv" set="cs">http://export.arxiv.org/oai2</request>
  <ListRecords>
    <record>
      <header>
        <identifier>oai:arXiv.org:2601.00001</identifier>
        <datestamp>2026-05-31</datestamp>
        <setSpec>cs</setSpec>
      </header>
      <metadata>
        <arXiv xmlns="http://arxiv.org/OAI/arXiv/">
          <id>2601.00001</id>
          <created>2026-05-30</created>
          <updated>2026-05-31</updated>
          <authors>
            <author><keyname>Smith</keyname><forenames>John A.</forenames></author>
            <author><keyname>Doe</keyname><forenames>Jane</forenames></author>
          </authors>
          <title>A
          Multi-line   Title</title>
          <categories>cs.CV cs.LG</categories>
          <abstract>  We present a
          new method.  </abstract>
          <doi>10.1234/xyz</doi>
        </arXiv>
      </metadata>
    </record>
    <record>
      <header status="deleted">
        <identifier>oai:arXiv.org:2601.00002</identifier>
        <datestamp>2026-05-31</datestamp>
      </header>
    </record>
    <resumptionToken cursor="0" completeListSize="2">TOKEN-PAGE-2</resumptionToken>
  </ListRecords>
</OAI-PMH>"""

_PAGE_FINAL = b"""<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <ListRecords>
    <record>
      <header><identifier>oai:arXiv.org:2601.00003</identifier><datestamp>2026-05-31</datestamp></header>
      <metadata>
        <arXiv xmlns="http://arxiv.org/OAI/arXiv/">
          <id>2601.00003</id>
          <created>2026-05-29</created>
          <title>Robotics Paper</title>
          <categories>cs.RO eess.SY</categories>
          <abstract>Robots.</abstract>
        </arXiv>
      </metadata>
    </record>
    <resumptionToken cursor="1" completeListSize="2"></resumptionToken>
  </ListRecords>
</OAI-PMH>"""

_NO_RECORDS = b"""<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <error code="noRecordsMatch">No matching records</error>
</OAI-PMH>"""

_BAD_ARG = b"""<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <error code="badArgument">bad from</error>
</OAI-PMH>"""


class OaiParserTests(unittest.TestCase):
    def test_parses_record_fields_and_token(self):
        papers, token = parse_oai_records(_PAGE_WITH_TOKEN)
        self.assertEqual(token, "TOKEN-PAGE-2")
        self.assertEqual(len(papers), 1)  # deleted record skipped
        p = papers[0]
        self.assertEqual(p["external_ids"]["arxiv"], "2601.00001")
        self.assertEqual(p["url"], "https://arxiv.org/abs/2601.00001")
        self.assertEqual(p["title"], "A Multi-line Title")  # whitespace collapsed
        self.assertEqual(p["summary"], "We present a new method.")
        self.assertEqual(p["published"], "2026-05-30 00:00")  # created, day-stamped
        self.assertEqual(p["authors"], ["John A. Smith", "Jane Doe"])
        self.assertEqual(p["categories"], ["cs.CV", "cs.LG"])
        self.assertEqual(p["source"], "arxiv")

    def test_empty_resumption_token_means_done(self):
        papers, token = parse_oai_records(_PAGE_FINAL)
        self.assertIsNone(token)
        self.assertEqual(papers[0]["categories"], ["cs.RO", "eess.SY"])

    def test_no_records_match_is_soft(self):
        papers, token = parse_oai_records(_NO_RECORDS)
        self.assertEqual(papers, [])
        self.assertIsNone(token)

    def test_other_oai_error_raises_502(self):
        with self.assertRaises(HTTPException) as ctx:
            parse_oai_records(_BAD_ARG)
        self.assertEqual(ctx.exception.status_code, 502)


class _StubResponse:
    def __init__(self, content: bytes):
        self.content = content
        self.status_code = 200
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        pass


class _StubClient:
    """Returns queued pages in order; records each request's params."""

    def __init__(self, pages: list[bytes]):
        self._pages = list(pages)
        self.calls: list[dict] = []

    async def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append(dict(params or {}))
        return _StubResponse(self._pages.pop(0))


class OaiHarvestPaginationTests(unittest.TestCase):
    def test_follows_resumption_token_and_dedups(self):
        client = _StubClient([_PAGE_WITH_TOKEN, _PAGE_FINAL])
        papers = asyncio.run(
            harvest_arxiv_oai(client, "cs", from_date="2026-05-30", max_pages=4)
        )
        ids = [p["external_ids"]["arxiv"] for p in papers]
        self.assertEqual(ids, ["2601.00001", "2601.00003"])  # deleted skipped, 2 pages
        # page 1 carries set+from; page 2 carries only the resumption token
        self.assertEqual(client.calls[0]["set"], "cs")
        self.assertEqual(client.calls[0]["from"], "2026-05-30")
        self.assertEqual(client.calls[1], {"verb": "ListRecords", "resumptionToken": "TOKEN-PAGE-2"})

    def test_max_pages_caps_pagination(self):
        client = _StubClient([_PAGE_WITH_TOKEN, _PAGE_FINAL])
        papers = asyncio.run(
            harvest_arxiv_oai(client, "cs", from_date="2026-05-30", max_pages=1)
        )
        self.assertEqual([p["external_ids"]["arxiv"] for p in papers], ["2601.00001"])
        self.assertEqual(len(client.calls), 1)


class OaiSetMappingTests(unittest.TestCase):
    def test_cs_and_stat_and_math(self):
        self.assertEqual(cat_to_oai_set("cs.CV"), "cs")
        self.assertEqual(cat_to_oai_set("stat.ML"), "stat")
        self.assertEqual(cat_to_oai_set("math.OC"), "math")
        self.assertEqual(cat_to_oai_set("eess.SY"), "eess")

    def test_physics_groups(self):
        self.assertEqual(cat_to_oai_set("cond-mat.stat-mech"), "physics:cond-mat")
        self.assertEqual(cat_to_oai_set("hep-th"), "physics:hep-th")
        self.assertEqual(cat_to_oai_set("quant-ph"), "physics:quant-ph")
        self.assertEqual(cat_to_oai_set("physics.optics"), "physics:physics")

    def test_unknown_returns_none(self):
        self.assertIsNone(cat_to_oai_set(""))
        self.assertIsNone(cat_to_oai_set("zzz.QQ"))


class OaiStateStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = PaperStore(Path(self._tmp.name) / "t.sqlite")

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def test_roundtrip_and_default(self):
        self.assertIsNone(self.store.oai_get_state("cs"))
        self.store.oai_set_state("cs", "2026-05-31")
        self.assertEqual(self.store.oai_get_state("cs"), "2026-05-31")
        self.store.oai_set_state("cs", "2026-06-01")  # advances
        self.assertEqual(self.store.oai_get_state("cs"), "2026-06-01")
        self.assertIsNone(self.store.oai_get_state(""))


if __name__ == "__main__":
    unittest.main()
