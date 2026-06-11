"""Offline contracts for the upstream adapters in clients.py.

Every upstream is stubbed (no real network). Canned XML/JSON fixtures are inline.
Covers query-building (quoting/escaping), field extraction, the defusedxml
PubMed parse path, the inverted-index abstract reconstruction, and the
soft-fail (empty/error → []) contract.
"""
import asyncio
import unittest
from datetime import datetime

import clients


# ── Stub transport ────────────────────────────────────────────────
class _Resp:
    def __init__(self, *, content: bytes = b"", json_body=None, status_code: int = 200, text: str = ""):
        self.content = content
        self._json = json_body
        self.status_code = status_code
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    """Records every request; serves queued responses (one per call) in order.

    Accepts the union of kwargs the adapters use (params/json/headers/timeout)
    for both GET and POST.
    """

    def __init__(self, responses: list[_Resp]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append({"method": "GET", "url": url, "params": dict(params or {}), "headers": headers})
        return self._responses.pop(0)

    async def post(self, url, json=None, timeout=None, headers=None):
        self.calls.append({"method": "POST", "url": url, "json": json})
        return self._responses.pop(0)


class _BoomClient:
    """Every request raises — exercises the transport-error soft-fail branch."""

    async def get(self, *a, **k):
        raise RuntimeError("network down")

    async def post(self, *a, **k):
        raise RuntimeError("network down")


def _run(coro):
    return asyncio.run(coro)


_TODAY = datetime.now()
_RECENT = _TODAY.strftime("%Y-%m-%d")


# ── arXiv search XML fixture ──────────────────────────────────────
_ARXIV_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2502.01234v1</id>
    <title>Diffusion Models for Everything (arXiv:2502.01234)</title>
    <summary>We propose a
    unified method.</summary>
    <published>2025-02-10T00:00:00Z</published>
    <author><name>Ada Lovelace</name></author>
  </entry>
</feed>"""


class ArxivSearchTests(unittest.TestCase):
    def test_phrase_helper_strips_quotes(self):
        self.assertEqual(clients._arxiv_phrase('  "graph nets"  '), "graph nets")
        self.assertEqual(clients._arxiv_phrase('he said "hi"'), "he said hi")

    def test_search_quotes_user_query_as_phrase(self):
        # post-fix: the raw user query is escaped + wrapped as all:"<phrase>".
        client = _Client([_Resp(content=_ARXIV_ATOM)])
        papers = _run(clients.fetch_arxiv_search(client, 'graph "neural" nets', 25))
        sq = client.calls[0]["params"]["search_query"]
        self.assertEqual(sq, 'all:"graph neural nets"')  # inner quotes stripped
        self.assertEqual(papers[0]["external_ids"]["arxiv"], "2502.01234")
        self.assertEqual(papers[0]["title"], "Diffusion Models for Everything")

    def test_search_upstream_error_raises_502(self):
        from fastapi import HTTPException

        client = _Client([_Resp(status_code=500)])
        with self.assertRaises(HTTPException) as ctx:
            _run(clients.fetch_arxiv_search(client, "anything", 10))
        self.assertEqual(ctx.exception.status_code, 502)


class ArxivListingTermsTests(unittest.TestCase):
    def test_terms_escaped_into_and_clause(self):
        # cats grouped with OR, free-text terms AND-appended verbatim.
        client = _Client([_Resp(content=_ARXIV_ATOM)])
        _run(clients.fetch_arxiv_listing(
            client, "cs.CV", 7, 50, cats=["cs.LG", "stat.ML"], terms='all:"agents"',
        ))
        sq = client.calls[0]["params"]["search_query"]
        self.assertEqual(sq, '(cat:cs.LG OR cat:stat.ML) AND (all:"agents")')

    def test_rate_limited_exhausts_retries_raises_502(self):
        from unittest import mock

        from fastapi import HTTPException

        # Three 429s exhaust all retry slots → final (no-sleep) slot raises 502.
        # Patch asyncio.sleep so the backoff doesn't actually block the suite.
        client = _Client([_Resp(status_code=429), _Resp(status_code=429), _Resp(status_code=429)])

        async def _no_sleep(_s):
            return None

        with mock.patch.object(clients.asyncio, "sleep", _no_sleep):
            with self.assertRaises(HTTPException) as ctx:
                _run(clients.fetch_arxiv_listing(client, "cs.CV", 7, 50))
        self.assertEqual(ctx.exception.status_code, 502)


# ── Semantic Scholar ──────────────────────────────────────────────
class S2BatchTests(unittest.TestCase):
    def test_batch_maps_ids_to_metrics(self):
        body = [
            {"citationCount": 42, "influentialCitationCount": 5, "referenceCount": 30,
             "publicationVenue": {"name": "NeurIPS"}},
            None,  # unresolved id → skipped
        ]
        client = _Client([_Resp(json_body=body)])
        out = _run(clients.fetch_s2_batch(client, ["2502.01234", "9999.99999"]))
        self.assertIn("2502.01234", out)
        self.assertNotIn("9999.99999", out)
        self.assertEqual(out["2502.01234"]["count"], 42)
        self.assertEqual(out["2502.01234"]["venue"], "NeurIPS")
        # request posts ArXiv:-prefixed ids
        self.assertEqual(client.calls[0]["json"]["ids"][0], "ArXiv:2502.01234")

    def test_batch_falls_back_to_venue_field(self):
        body = [{"citationCount": 1, "venue": "ICML"}]
        client = _Client([_Resp(json_body=body)])
        out = _run(clients.fetch_s2_batch(client, ["2502.01234"]))
        self.assertEqual(out["2502.01234"]["venue"], "ICML")

    def test_batch_transport_error_returns_partial_empty(self):
        out = _run(clients.fetch_s2_batch(_BoomClient(), ["2502.01234"]))
        self.assertEqual(out, {})


class S2SearchTests(unittest.TestCase):
    def test_search_extracts_fields_and_passes_query(self):
        body = {"data": [{
            "title": "Scaling Laws",
            "abstract": "We study scaling.",
            "publicationDate": _RECENT,
            "authors": [{"name": "Grace Hopper"}],
            "externalIds": {"ArXiv": "2502.05555", "DOI": "10.1/ABC"},
            "venue": "ICLR",
            "citationCount": 7,
        }]}
        client = _Client([_Resp(json_body=body)])
        out = _run(clients.fetch_s2_search(client, "scaling laws", "Computer Science", 365, 20))
        self.assertEqual(client.calls[0]["params"]["query"], "scaling laws")
        self.assertEqual(client.calls[0]["params"]["fieldsOfStudy"], "Computer Science")
        self.assertEqual(len(out), 1)
        p = out[0]
        self.assertEqual(p["source"], "s2_search")
        self.assertEqual(p["url"], "https://arxiv.org/abs/2502.05555")
        self.assertEqual(p["external_ids"], {"arxiv": "2502.05555", "doi": "10.1/abc"})
        self.assertEqual(p["authors"], ["Grace Hopper"])

    def test_search_empty_query_short_circuits(self):
        out = _run(clients.fetch_s2_search(_BoomClient(), "", None, 30, 10))
        self.assertEqual(out, [])

    def test_search_non_200_returns_empty(self):
        client = _Client([_Resp(status_code=429, text="rate limited")])
        out = _run(clients.fetch_s2_search(client, "q", None, 30, 10))
        self.assertEqual(out, [])


class S2AuthorTests(unittest.TestCase):
    def test_author_papers_extracts(self):
        body = {"data": [{
            "title": "My Paper",
            "abstract": "a",
            "publicationDate": "2025-03-01",
            "externalIds": {"DOI": "10.9/XYZ"},
            "venue": "TMLR",
            "citationCount": 11,
        }]}
        client = _Client([_Resp(json_body=body)])
        out = _run(clients.fetch_s2_author_papers(client, "1234", limit=10))
        self.assertEqual(out[0]["source"], "s2_author")
        self.assertEqual(out[0]["url"], "https://doi.org/10.9/xyz")
        self.assertEqual(out[0]["authors"], [])  # author endpoint omits co-authors

    def test_author_papers_error_empty(self):
        self.assertEqual(_run(clients.fetch_s2_author_papers(_BoomClient(), "1", 10)), [])

    def test_author_search_passes_through_data(self):
        body = {"data": [{"name": "Yann L", "hIndex": 99}]}
        client = _Client([_Resp(json_body=body)])
        out = _run(clients.fetch_s2_author_search(client, "Yann L", limit=5))
        self.assertEqual(out, body["data"])
        self.assertEqual(client.calls[0]["params"]["query"], "Yann L")

    def test_author_search_non_200_empty(self):
        client = _Client([_Resp(status_code=500)])
        self.assertEqual(_run(clients.fetch_s2_author_search(client, "x", 5)), [])


# ── OpenAlex ──────────────────────────────────────────────────────
class InvertedIndexTests(unittest.TestCase):
    def test_reconstructs_text_in_position_order(self):
        inv = {"the": [0, 4], "quick": [1], "brown": [2], "fox": [3], "jumps": [5]}
        self.assertEqual(
            clients._abstract_from_inv_index(inv),
            "the quick brown fox the jumps",
        )

    def test_none_or_empty_returns_empty_string(self):
        self.assertEqual(clients._abstract_from_inv_index(None), "")
        self.assertEqual(clients._abstract_from_inv_index({}), "")


class OpenAlexTests(unittest.TestCase):
    def test_listing_extracts_fields_and_abstract(self):
        body = {"results": [{
            "title": "Cross-Disc Paper",
            "abstract_inverted_index": {"Hello": [0], "world": [1]},
            "authorships": [{"author": {"display_name": "A. Author"}}],
            "ids": {"doi": "https://doi.org/10.5/DEF"},
            "locations": [{"source": {"display_name": "arXiv"},
                           "landing_page_url": "https://arxiv.org/abs/2503.04567"}],
            "primary_location": {"source": {"display_name": "Some Journal"}},
            "publication_date": _RECENT,
            "cited_by_count": 4,
        }]}
        client = _Client([_Resp(json_body=body)])
        out = _run(clients.fetch_openalex_listing(client, "C123", 30, 50, search_query="cross"))
        self.assertEqual(client.calls[0]["params"]["search"], "cross")
        self.assertIn("concepts.id:C123", client.calls[0]["params"]["filter"])
        p = out[0]
        self.assertEqual(p["source"], "openalex")
        self.assertEqual(p["summary"], "Hello world")
        self.assertEqual(p["external_ids"]["doi"], "10.5/DEF")
        self.assertEqual(p["external_ids"]["arxiv"], "2503.04567")
        self.assertEqual(p["url"], "https://arxiv.org/abs/2503.04567")  # arXiv preferred
        self.assertEqual(p["venue"], "Some Journal")

    def test_listing_non_200_returns_empty(self):
        client = _Client([_Resp(status_code=503, text="oops")])
        self.assertEqual(_run(clients.fetch_openalex_listing(client, None, 30, 50)), [])

    def test_listing_transport_error_returns_empty(self):
        self.assertEqual(_run(clients.fetch_openalex_listing(_BoomClient(), None, 30, 50)), [])


# ── Crossref ──────────────────────────────────────────────────────
class CrossrefTests(unittest.TestCase):
    def test_listing_extracts_and_strips_jats(self):
        body = {"message": {"items": [{
            "title": ["A Journal Paper"],
            "DOI": "10.1234/ABCD",
            "published-online": {"date-parts": [[2025, 4, 9]]},
            "author": [{"given": "Jane", "family": "Smith"}],
            "container-title": ["Nature"],
            "abstract": "<jats:p>Real abstract.</jats:p>",
            "is-referenced-by-count": 8,
        }]}}
        client = _Client([_Resp(json_body=body)])
        out = _run(clients.fetch_crossref_listing(client, "Computer Science", 30, 50, search_query="nn"))
        self.assertEqual(client.calls[0]["params"]["query"], "nn")
        self.assertEqual(client.calls[0]["params"]["query.bibliographic"], "Computer Science")
        p = out[0]
        self.assertEqual(p["source"], "crossref")
        self.assertEqual(p["summary"], "Real abstract.")  # jats tags stripped
        self.assertEqual(p["published"], "2025-04-09 00:00")
        self.assertEqual(p["url"], "https://doi.org/10.1234/abcd")
        self.assertEqual(p["venue"], "Nature")
        self.assertEqual(p["authors"], ["Jane Smith"])

    def test_listing_skips_items_without_title(self):
        body = {"message": {"items": [{"DOI": "10.1/x"}]}}
        client = _Client([_Resp(json_body=body)])
        self.assertEqual(_run(clients.fetch_crossref_listing(client, None, 30, 50)), [])

    def test_listing_error_returns_empty(self):
        self.assertEqual(_run(clients.fetch_crossref_listing(_BoomClient(), None, 30, 50)), [])


# ── ChemRxiv (CrossRef prefix) ────────────────────────────────────
class ChemRxivTests(unittest.TestCase):
    def test_listing_extracts_posted_content(self):
        body = {"message": {"items": [{
            "title": ["A Chem Preprint"],
            "DOI": "10.26434/CHEMRXIV-XYZ",
            "posted": {"date-parts": [[2025, 5, 1]]},
            "author": [{"given": "B", "family": "Curie"}],
            "abstract": "<p>chem</p>",
            "is-referenced-by-count": 0,
        }]}}
        client = _Client([_Resp(json_body=body)])
        out = _run(clients.fetch_chemrxiv_listing(client, 30, 50))
        self.assertIn("from-posted-date", client.calls[0]["params"]["filter"])
        p = out[0]
        self.assertEqual(p["source"], "chemrxiv")
        self.assertEqual(p["venue"], "ChemRxiv")
        self.assertEqual(p["summary"], "chem")
        self.assertEqual(p["published"], "2025-05-01 00:00")

    def test_listing_non_200_empty(self):
        client = _Client([_Resp(status_code=403, text="cf")])
        self.assertEqual(_run(clients.fetch_chemrxiv_listing(client, 30, 50)), [])


# ── bioRxiv / medRxiv ─────────────────────────────────────────────
class BioRxivTests(unittest.TestCase):
    def test_listing_parses_collection_and_splits_authors(self):
        body = {"collection": [{
            "title": "A Bio Preprint",
            "doi": "10.1101/2025.05.01.ABC",
            "authors": "Smith, J.; Doe, A.",
            "abstract": "bio abstract",
            "date": "2025-05-15",
        }]}
        # second page empty so the while-loop terminates deterministically
        client = _Client([_Resp(json_body=body)])
        out = _run(clients.fetch_biorxiv_listing(client, "biorxiv", 30, 1))
        self.assertEqual(len(out), 1)
        p = out[0]
        self.assertEqual(p["source"], "biorxiv")
        self.assertEqual(p["authors"], ["Smith, J.", "Doe, A."])
        self.assertEqual(p["url"], "https://doi.org/10.1101/2025.05.01.abc")
        self.assertEqual(p["published"], "2025-05-15 00:00")
        self.assertEqual(p["venue"], "biorxiv")
        self.assertIn("biorxiv", client.calls[0]["url"])

    def test_listing_empty_collection_returns_empty(self):
        client = _Client([_Resp(json_body={"collection": []})])
        self.assertEqual(_run(clients.fetch_biorxiv_listing(client, "medrxiv", 30, 50)), [])

    def test_listing_non_200_breaks_to_empty(self):
        client = _Client([_Resp(status_code=500)])
        self.assertEqual(_run(clients.fetch_biorxiv_listing(client, "biorxiv", 30, 50)), [])


# ── PubMed (defusedxml efetch path) ───────────────────────────────
_PUBMED_ESEARCH_JSON = {"esearchresult": {"idlist": ["40000001"]}}

_PUBMED_EFETCH_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>40000001</PMID>
      <Article>
        <ArticleTitle>Neuroscience of Sleep</ArticleTitle>
        <Abstract>
          <AbstractText>Background segment.</AbstractText>
          <AbstractText>Methods segment.</AbstractText>
        </Abstract>
        <Journal><Title>Journal of Sleep</Title></Journal>
        <AuthorList>
          <Author><ForeName>Jane</ForeName><LastName>Roe</LastName></Author>
        </AuthorList>
      </Article>
      <PubDate><Year>2025</Year><Month>May</Month><Day>20</Day></PubDate>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="doi">10.1000/SLEEP.42</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""

# DTD-defined custom entity: defusedxml must reject this rather than expand it.
_PUBMED_ENTITY_BOMB = b"""<?xml version="1.0"?>
<!DOCTYPE PubmedArticleSet [<!ENTITY boom "PWNED">]>
<PubmedArticleSet>
  <PubmedArticle><MedlineCitation><Article>
  <ArticleTitle>&boom;</ArticleTitle></Article></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""


class _PubmedClient:
    """Serves esearch JSON then efetch XML based on requested URL."""

    def __init__(self, esearch: _Resp, efetch: _Resp):
        self._esearch = esearch
        self._efetch = efetch
        self.calls: list[str] = []

    async def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append(url)
        if "esearch" in url:
            return self._esearch
        return self._efetch


class PubmedTests(unittest.TestCase):
    def setUp(self):
        # Neutralize the 3-req/sec token bucket so tests never block on sleep.
        from unittest import mock

        async def _noop():
            return None

        self._throttle_patch = mock.patch.object(clients, "_pubmed_throttle", _noop)
        self._throttle_patch.start()

    def tearDown(self):
        self._throttle_patch.stop()

    def test_no_mesh_term_short_circuits(self):
        out = _run(clients.fetch_pubmed_listing(_BoomClient(), None, 30, 10))
        self.assertEqual(out, [])

    def test_two_stage_parse_extracts_fields(self):
        client = _PubmedClient(
            _Resp(json_body=_PUBMED_ESEARCH_JSON),
            _Resp(content=_PUBMED_EFETCH_XML),
        )
        out = _run(clients.fetch_pubmed_listing(client, "Sleep", 365, 10))
        self.assertEqual(len(out), 1)
        p = out[0]
        self.assertEqual(p["source"], "pubmed")
        self.assertEqual(p["title"], "Neuroscience of Sleep")
        self.assertEqual(p["summary"], "Background segment. Methods segment.")
        self.assertEqual(p["venue"], "Journal of Sleep")
        self.assertEqual(p["authors"], ["Jane Roe"])
        self.assertEqual(p["published"], "2025-05-20 00:00")
        self.assertEqual(p["external_ids"]["doi"], "10.1000/sleep.42")
        self.assertEqual(p["external_ids"]["pmid"], "40000001")
        self.assertEqual(p["url"], "https://doi.org/10.1000/sleep.42")

    def test_empty_idlist_returns_empty(self):
        client = _PubmedClient(
            _Resp(json_body={"esearchresult": {"idlist": []}}),
            _Resp(content=_PUBMED_EFETCH_XML),
        )
        self.assertEqual(_run(clients.fetch_pubmed_listing(client, "Sleep", 30, 10)), [])

    def test_esearch_non_200_returns_empty(self):
        client = _PubmedClient(
            _Resp(status_code=429),
            _Resp(content=_PUBMED_EFETCH_XML),
        )
        self.assertEqual(_run(clients.fetch_pubmed_listing(client, "Sleep", 30, 10)), [])

    def test_efetch_entity_bomb_is_soft_failed_to_empty(self):
        # defusedxml raises on the DTD entity; the adapter catches → [].
        client = _PubmedClient(
            _Resp(json_body=_PUBMED_ESEARCH_JSON),
            _Resp(content=_PUBMED_ENTITY_BOMB),
        )
        self.assertEqual(_run(clients.fetch_pubmed_listing(client, "Sleep", 365, 10)), [])


if __name__ == "__main__":
    unittest.main()
