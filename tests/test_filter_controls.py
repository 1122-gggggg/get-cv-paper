import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FilterControlsTests(unittest.TestCase):
    def test_time_range_and_metric_controls_are_present(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "script.js").read_text(encoding="utf-8")

        for range_id in ["day", "week", "month"]:
            self.assertIn(f'data-range="{range_id}"', html)

        for sort_id in ["latest", "popularity", "citations", "value", "velocity", "hf"]:
            self.assertIn(f'data-value="{sort_id}"', html)

        self.assertIn("currentTimeRange", script)
        self.assertIn("getPopularityScore", script)
        self.assertIn("sortPapersByMetric", script)

    def test_research_coverage_and_storage_tools_are_present(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "script.js").read_text(encoding="utf-8")

        for expected_id in [
            'id="coverageBar"',
            'id="storageExportBtn"',
            'id="storageImportBtn"',
            'id="storageImportFile"',
        ]:
            self.assertIn(expected_id, html)

        for expected_fn in [
            "renderCoverageBar",
            "prewarmExtendedPaperRanges",
            "exportUserState",
            "importUserStateFile",
        ]:
            self.assertIn(expected_fn, script)

    def test_first_paint_has_no_csp_blocked_preload_handlers(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

        self.assertNotIn("onload=", html)
        self.assertNotIn("fonts.googleapis.com", html)
        self.assertNotIn("/api/papers?max_results=", html)

    def test_subscription_and_recommendation_controls_are_absent(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "script.js").read_text(encoding="utf-8")

        for forbidden in [
            "rssSubscribeBtn",
            "pushSubscribeBtn",
            "addCustomFeedBtn",
            "customFeedModal",
            'data-value="personalized"',
            "similarModal",
            "similar-btn",
        ]:
            self.assertNotIn(forbidden, html)

        for forbidden in [
            "/api/rss",
            "/api/push",
            "/api/custom",
            "/api/personalized",
            "/api/recommendations",
            "applyPersonalizedRerank",
            "initWebPush",
        ]:
            self.assertNotIn(forbidden, script)


if __name__ == "__main__":
    unittest.main()
