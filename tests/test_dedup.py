"""Offline unit tests for cross-source paper dedup/merge logic in dedup.py."""
import unittest

from dedup import (
    SOURCE_PRIORITY,
    _extract_arxiv_id,
    _extract_doi,
    _fuzzy_title_key,
    _normalize_doi,
    _paper_keys,
    _src_priority,
    merge_sources,
)


class NormalizeDoiTests(unittest.TestCase):
    def test_strips_https_prefix_and_lowercases(self):
        self.assertEqual(_normalize_doi("https://doi.org/10.1234/ABC"), "10.1234/abc")

    def test_strips_doi_colon_prefix_and_trailing_slash(self):
        self.assertEqual(_normalize_doi("doi:10.1234/abc/"), "10.1234/abc")

    def test_none_and_empty_return_none(self):
        self.assertIsNone(_normalize_doi(None))
        self.assertIsNone(_normalize_doi(""))

    def test_non_doi_string_returns_none(self):
        self.assertIsNone(_normalize_doi("not-a-doi"))


class ExtractIdTests(unittest.TestCase):
    def test_doi_from_external_ids(self):
        p = {"external_ids": {"doi": "10.1000/xyz"}}
        self.assertEqual(_extract_doi(p), "10.1000/xyz")

    def test_doi_scanned_from_url(self):
        p = {"url": "https://doi.org/10.1000/fromurl"}
        self.assertEqual(_extract_doi(p), "10.1000/fromurl")

    def test_doi_absent_returns_none(self):
        self.assertIsNone(_extract_doi({"url": "https://example.com/paper"}))

    def test_arxiv_from_external_ids_with_version_stripped(self):
        p = {"external_ids": {"arxiv": "2601.00001v3"}}
        self.assertEqual(_extract_arxiv_id(p), "2601.00001")

    def test_arxiv_from_url(self):
        p = {"url": "https://arxiv.org/abs/2601.12345"}
        self.assertEqual(_extract_arxiv_id(p), "2601.12345")

    def test_arxiv_absent_returns_none(self):
        self.assertIsNone(_extract_arxiv_id({"url": "https://example.com/x"}))


class FuzzyTitleKeyTests(unittest.TestCase):
    def test_lowercase_punct_stripped_and_first_last(self):
        key = _fuzzy_title_key("Deep Learning, Revisited!", ["John A. Smith"])
        self.assertEqual(key, "deep learning revisited|smith")

    def test_comma_author_takes_lastname_before_comma(self):
        key = _fuzzy_title_key("A Title", ["Smith, John"])
        self.assertEqual(key, "a title|smith")

    def test_truncates_title_to_60_chars(self):
        long_title = "word " * 30  # 150 chars worth
        key = _fuzzy_title_key(long_title, None)
        # no author -> just the truncated normalized title
        self.assertLessEqual(len(key), 60)

    def test_same_title_different_author_yields_different_keys(self):
        k1 = _fuzzy_title_key("Same Title", ["Alice Brown"])
        k2 = _fuzzy_title_key("Same Title", ["Bob Green"])
        self.assertNotEqual(k1, k2)

    def test_none_title_returns_none(self):
        self.assertIsNone(_fuzzy_title_key(None, ["Smith"]))

    def test_no_authors_returns_title_only(self):
        self.assertEqual(_fuzzy_title_key("Plain Title", None), "plain title")


class PaperKeysAndPriorityTests(unittest.TestCase):
    def test_keys_in_doi_arxiv_fuzzy_order(self):
        p = {
            "external_ids": {"doi": "10.1234/x", "arxiv": "2601.00001"},
            "title": "T",
            "authors": ["A B"],
        }
        keys = _paper_keys(p)
        self.assertEqual([k[0] for k in keys], ["doi", "arxiv", "fuzzy"])

    def test_empty_paper_has_no_keys(self):
        self.assertEqual(_paper_keys({}), [])

    def test_src_priority_string_source(self):
        self.assertEqual(_src_priority({"source": "crossref"}), SOURCE_PRIORITY["crossref"])

    def test_src_priority_list_takes_min(self):
        self.assertEqual(
            _src_priority({"source": ["crossref", "arxiv"]}),
            SOURCE_PRIORITY["arxiv"],
        )

    def test_src_priority_unknown_defaults_high(self):
        self.assertEqual(_src_priority({"source": "weird"}), 99)

    def test_src_priority_missing_defaults_to_arxiv(self):
        self.assertEqual(_src_priority({}), SOURCE_PRIORITY["arxiv"])


class MergeSourcesTests(unittest.TestCase):
    def test_doi_dedup_same_title_different_source(self):
        arxiv = {
            "title": "A Great Paper",
            "authors": ["Jane Doe"],
            "source": "arxiv",
            "external_ids": {"doi": "10.1234/great", "arxiv": "2601.00009"},
        }
        crossref = {
            "title": "A Great Paper (published version)",
            "authors": ["Jane Doe"],
            "source": "crossref",
            "external_ids": {"doi": "10.1234/great"},
            "citation_count": 42,
        }
        out = merge_sources([arxiv], [crossref])
        self.assertEqual(len(out), 1)
        merged = out[0]
        # arxiv stays primary (higher precedence) -> keeps arxiv title
        self.assertEqual(merged["title"], "A Great Paper")
        self.assertCountEqual(merged["source"], ["arxiv", "crossref"])
        self.assertEqual(merged["citation_count"], 42)

    def test_arxiv_id_matches_doi_record_via_shared_key(self):
        a = {
            "title": "Paper X",
            "authors": ["Al Pha"],
            "source": "arxiv",
            "external_ids": {"arxiv": "2601.55555"},
        }
        b = {
            "title": "Completely Different Wording Here",
            "authors": ["No Match"],
            "source": "openalex",
            "external_ids": {"arxiv": "2601.55555v2"},
        }
        out = merge_sources([a], [b])
        self.assertEqual(len(out), 1)
        self.assertCountEqual(out[0]["source"], ["arxiv", "openalex"])

    def test_distinct_papers_not_merged(self):
        a = {"title": "Alpha", "authors": ["X Y"], "source": "arxiv",
             "external_ids": {"doi": "10.1/a"}}
        b = {"title": "Beta", "authors": ["P Q"], "source": "arxiv",
             "external_ids": {"doi": "10.1/b"}}
        out = merge_sources([a], [b])
        self.assertEqual(len(out), 2)

    def test_more_preferred_source_arriving_later_becomes_primary(self):
        crossref = {
            "title": "Crossref Title",
            "authors": ["Jane Doe"],
            "source": "crossref",
            "external_ids": {"doi": "10.1234/shared"},
            "citation_count": 10,
        }
        arxiv = {
            "title": "Arxiv Title",
            "authors": ["Jane Doe"],
            "source": "arxiv",
            "external_ids": {"doi": "10.1234/shared"},
            "hf_upvotes": 7,
        }
        out = merge_sources([crossref], [arxiv])
        self.assertEqual(len(out), 1)
        primary = out[0]
        # arxiv (priority 0) wins as primary over crossref (priority 2)
        self.assertEqual(primary["title"], "Arxiv Title")
        self.assertCountEqual(primary["source"], ["crossref", "arxiv"])
        # metadata accumulated from both
        self.assertEqual(primary["citation_count"], 10)
        self.assertEqual(primary["hf_upvotes"], 7)

    def test_external_ids_unioned_and_citation_max(self):
        a = {
            "title": "T", "authors": ["A B"], "source": "openalex",
            "external_ids": {"doi": "10.1/t"},
            "citation_count": 3,
        }
        b = {
            "title": "T", "authors": ["A B"], "source": "crossref",
            "external_ids": {"doi": "10.1/t", "pmid": "999"},
            "citation_count": 99,
        }
        out = merge_sources([a], [b])
        self.assertEqual(len(out), 1)
        merged = out[0]
        self.assertEqual(merged["external_ids"]["doi"], "10.1/t")
        self.assertEqual(merged["external_ids"]["pmid"], "999")
        self.assertEqual(merged["citation_count"], 99)

    def test_review_and_missing_fields_filled_from_dup(self):
        arxiv = {
            "title": "T", "authors": ["A B"], "source": "arxiv",
            "external_ids": {"arxiv": "2601.77777"},
            "summary": "",  # falsy -> should be filled
        }
        openreview = {
            "title": "T", "authors": ["A B"], "source": "openalex",
            "external_ids": {"arxiv": "2601.77777"},
            "or_rating": 8.0,
            "review_avg": 7.5,
            "review_count": 4,
            "summary": "filled in",
            "venue": "ICLR 2026",
        }
        out = merge_sources([arxiv], [openreview])
        self.assertEqual(len(out), 1)
        merged = out[0]
        self.assertEqual(merged["or_rating"], 8.0)
        self.assertEqual(merged["review_avg"], 7.5)
        self.assertEqual(merged["review_count"], 4)
        self.assertEqual(merged["summary"], "filled in")
        self.assertEqual(merged["venue"], "ICLR 2026")

    def test_keyless_papers_pass_through_without_merge(self):
        a = {"source": "arxiv"}  # no doi/arxiv/title -> no keys
        b = {"source": "crossref"}
        out = merge_sources([a, b])
        self.assertEqual(len(out), 2)

    def test_insertion_order_preserved(self):
        a = {"title": "First", "authors": ["A A"], "source": "arxiv",
             "external_ids": {"doi": "10.1/1"}}
        b = {"title": "Second", "authors": ["B B"], "source": "arxiv",
             "external_ids": {"doi": "10.1/2"}}
        c = {"title": "Third", "authors": ["C C"], "source": "arxiv",
             "external_ids": {"doi": "10.1/3"}}
        out = merge_sources([a], [b], [c])
        self.assertEqual([p["title"] for p in out], ["First", "Second", "Third"])

    def test_hf_daily_beats_openalex_but_loses_to_arxiv(self):
        # hf_daily (0.5) vs openalex (1): hf_daily is primary
        hf = {"title": "T", "authors": ["A B"], "source": "hf_daily",
              "external_ids": {"arxiv": "2601.00010"}, "hf_upvotes": 12}
        oa = {"title": "T", "authors": ["A B"], "source": "openalex",
              "external_ids": {"arxiv": "2601.00010"}, "citation_count": 5}
        out = merge_sources([oa], [hf])
        self.assertEqual(len(out), 1)
        self.assertCountEqual(out[0]["source"], ["openalex", "hf_daily"])
        # hf_daily arrived second but is more preferred -> primary
        self.assertEqual(out[0]["hf_upvotes"], 12)
        self.assertEqual(out[0]["citation_count"], 5)


if __name__ == "__main__":
    unittest.main()
