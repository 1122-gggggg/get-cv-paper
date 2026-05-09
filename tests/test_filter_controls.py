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


if __name__ == "__main__":
    unittest.main()
