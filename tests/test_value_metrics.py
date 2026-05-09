import json
import subprocess
import textwrap
import unittest


def run_node_expr(expr: str) -> dict:
    script = textwrap.dedent(
        f"""
        const metrics = require('./static/value-metrics.js');
        const result = {expr};
        console.log(JSON.stringify(result));
        """
    )
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


class ValueMetricsTests(unittest.TestCase):
    def test_high_signal_paper_is_ranked_hot(self):
        result = run_node_expr(
            """
            metrics.computeValueMetrics({
              citations: 420,
              influential: 35,
              hfUpvotes: 120,
              hasCode: true,
              stars: 1800,
              citationSpeed: 18,
              venueH5: 240,
              localViews: 2
            })
            """
        )

        self.assertGreaterEqual(result["score"], 70)
        self.assertIn(result["tier"], ["hot", "high"])
        self.assertTrue(any("引用" in r for r in result["reasons"]))
        self.assertTrue(any("開源" in r for r in result["reasons"]))

    def test_new_paper_without_external_signal_stays_watch(self):
        result = run_node_expr(
            """
            metrics.computeValueMetrics({
              citations: 0,
              influential: 0,
              hfUpvotes: 0,
              hasCode: false,
              stars: 0,
              citationSpeed: 0,
              venueH5: 0,
              localViews: 0
            })
            """
        )

        self.assertLess(result["score"], 20)
        self.assertEqual(result["tier"], "watch")


if __name__ == "__main__":
    unittest.main()
