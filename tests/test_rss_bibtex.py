"""Offline contract for BibTeX export."""
import unittest

from fastapi.testclient import TestClient

import main


# ── pure helper: _bibtex_key ──────────────────────────────────────
class BibtexKeyTests(unittest.TestCase):
    def test_lastname_year_firstword(self):
        key = main._bibtex_key(["Jane Doe", "John Smith"], "2024", "Deep Learning Models")
        self.assertEqual(key, "doe2024deep")

    def test_skips_stopwords_in_title(self):
        key = main._bibtex_key(["Ada Lovelace"], "2030", "The On Of Engine")
        # the/on/of are stopwords → first meaningful word is "engine"
        self.assertEqual(key, "lovelace2030engine")

    def test_stable_for_same_inputs(self):
        args = (["Marie Curie"], "1903", "Radioactivity Studies")
        self.assertEqual(main._bibtex_key(*args), main._bibtex_key(*args))

    def test_year_truncated_to_four_chars(self):
        key = main._bibtex_key(["Alan Turing"], "2026-05", "Computing Machinery")
        self.assertEqual(key, "turing2026computing")

    def test_no_authors_uses_anon(self):
        key = main._bibtex_key([], "2026", "Anonymous Work")
        self.assertTrue(key.startswith("anon2026"))

    def test_punctuation_stripped_from_lastname(self):
        key = main._bibtex_key(["O'Brien-Ng"], "2026", "Networks")
        # non-alphanumerics removed from the surname token
        self.assertTrue(key.startswith("obrienng2026"))

    def test_result_is_ascii_keylike(self):
        key = main._bibtex_key(["Jane Doe"], "2024", "Deep Nets")
        self.assertTrue(key.isalnum())
        self.assertTrue(len(key) <= 50)


# ── pure helper: _bibtex_escape ───────────────────────────────────
class BibtexEscapeTests(unittest.TestCase):
    def test_braces_and_specials_escaped(self):
        out = main._bibtex_escape("a & b % c $ d # e _ f { g } h")
        for token in (r"\&", r"\%", r"\$", r"\#", r"\_", r"\{", r"\}"):
            self.assertIn(token, out)

    def test_backslash_and_tilde_and_caret(self):
        self.assertIn(r"\textbackslash{}", main._bibtex_escape("a\\b"))
        self.assertIn(r"\textasciitilde{}", main._bibtex_escape("a~b"))
        self.assertIn(r"\textasciicircum{}", main._bibtex_escape("a^b"))

    def test_plain_text_unchanged_and_stripped(self):
        self.assertEqual(main._bibtex_escape("  Hello World  "), "Hello World")

    def test_empty_input(self):
        self.assertEqual(main._bibtex_escape(""), "")


# ── route: /api/bibtex (S2 source patched / pre-seeded) ───────────
class BibtexRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self._aid = "2401.12345"

        async def _no_network(_client, _missing):
            self.fail("fetch_s2_batch should not be called when store is warm")

        self._orig = main.fetch_s2_batch
        main.fetch_s2_batch = _no_network
        main._s2_store.set(
            self._aid,
            {
                "title": "Sample Paper on Models",
                "authors": ["Jane Doe", "John Smith"],
                "venue": "NeurIPS",
            },
        )

    def tearDown(self):
        main.fetch_s2_batch = self._orig
        main._s2_store._data.pop(self._aid, None)

    def test_bibtex_export_returns_bib_body(self):
        r = self.client.get(f"/api/bibtex?arxiv_ids={self._aid}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("application/x-bibtex", r.headers["content-type"])
        self.assertTrue(r.content)
        text = r.text
        self.assertIn("@article{", text)
        self.assertIn("title = {Sample Paper on Models}", text)
        self.assertIn("Jane Doe and John Smith", text)
        self.assertIn("journal = {NeurIPS}", text)
        self.assertIn(f"eprint = {{{self._aid}}}", text)
        self.assertIn("doe2024", text)  # key derived from author+year

    def test_missing_ids_400(self):
        r = self.client.get("/api/bibtex?arxiv_ids=")
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
