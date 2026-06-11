import json
import subprocess
import textwrap
import unittest


def run_node_expr(expr: str):
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


def tier_for(input_literal: str) -> str:
    return run_node_expr(f"metrics.computeValueMetrics({input_literal}).tier")


def score_for(input_literal: str) -> int:
    return run_node_expr(f"metrics.computeValueMetrics({input_literal}).score")


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


class TierBoundaryTests(unittest.TestCase):
    """Each cutoff in tierFor (20/42/65/82) is probed just-below vs just-above.

    Inputs were derived from the real scoring so the rounded score lands exactly
    on the adjacent integers straddling the cutoff. If a weight or cap changes,
    these will flag it.
    """

    def test_watch_to_emerging_at_20(self):
        below = "{ citations: 70 }"
        above = "{ citations: 89 }"
        self.assertEqual(score_for(below), 19)
        self.assertEqual(score_for(above), 20)
        self.assertEqual(tier_for(below), "watch")
        self.assertEqual(tier_for(above), "emerging")

    def test_emerging_to_solid_at_42(self):
        below = "{ hasCode: true, stars: 50, influential: 5, citations: 302 }"
        above = "{ hasCode: true, stars: 50, influential: 5, citations: 303 }"
        self.assertEqual(score_for(below), 41)
        self.assertEqual(score_for(above), 42)
        self.assertEqual(tier_for(below), "emerging")
        self.assertEqual(tier_for(above), "solid")

    def test_solid_to_hot_at_65(self):
        base = (
            "influential: 20, citationSpeed: 15, venueH5: 150, hasCode: true, "
            "stars: 300, localViews: 3, hfUpvotes: 25"
        )
        below = f"{{ {base}, citations: 19 }}"
        above = f"{{ {base}, citations: 20 }}"
        self.assertEqual(score_for(below), 64)
        self.assertEqual(score_for(above), 65)
        self.assertEqual(tier_for(below), "solid")
        self.assertEqual(tier_for(above), "hot")

    def test_hot_to_high_at_82(self):
        base = (
            "citations: 400, influential: 70, citationSpeed: 40, venueH5: 400, "
            "localViews: 10, hasCode: true, stars: 3000"
        )
        below = f"{{ {base}, hfUpvotes: 0 }}"
        above = f"{{ {base}, hfUpvotes: 1 }}"
        self.assertEqual(score_for(below), 81)
        self.assertEqual(score_for(above), 83)
        self.assertEqual(tier_for(below), "hot")
        self.assertEqual(tier_for(above), "high")

    def test_score_is_clamped_to_100(self):
        maxed = (
            "{ citations: 100000, influential: 10000, hfUpvotes: 100000, "
            "hasCode: true, stars: 1000000, citationSpeed: 10000, "
            "venueH5: 100000, localViews: 100000 }"
        )
        self.assertLessEqual(score_for(maxed), 100)
        self.assertEqual(tier_for(maxed), "high")


class LogScaleTests(unittest.TestCase):
    def test_zero_and_negative_map_to_zero(self):
        self.assertEqual(run_node_expr("metrics.logScale(0, 500)"), 0)
        self.assertEqual(run_node_expr("metrics.logScale(-10, 500)"), 0)

    def test_value_at_cap_is_one(self):
        self.assertEqual(run_node_expr("metrics.logScale(500, 500)"), 1)

    def test_value_above_cap_is_clamped_to_one(self):
        self.assertEqual(run_node_expr("metrics.logScale(5000, 500)"), 1)

    def test_monotonic_strictly_increasing_below_cap(self):
        samples = run_node_expr(
            "[1, 5, 25, 100, 250, 499].map(v => metrics.logScale(v, 500))"
        )
        self.assertEqual(samples, sorted(samples))
        for a, b in zip(samples, samples[1:]):
            self.assertLess(a, b)

    def test_between_zero_and_one_inside_range(self):
        mid = run_node_expr("metrics.logScale(50, 500)")
        self.assertGreater(mid, 0)
        self.assertLess(mid, 1)


class FormatCompactTests(unittest.TestCase):
    def test_below_thousand_is_plain_integer(self):
        self.assertEqual(run_node_expr("metrics.formatCompact(999)"), "999")
        self.assertEqual(run_node_expr("metrics.formatCompact(0)"), "0")

    def test_rounds_sub_thousand_to_nearest_integer(self):
        self.assertEqual(run_node_expr("metrics.formatCompact(12.4)"), "12")
        self.assertEqual(run_node_expr("metrics.formatCompact(12.6)"), "13")

    def test_thousand_boundary_switches_to_k(self):
        self.assertEqual(run_node_expr("metrics.formatCompact(1000)"), "1.0k")
        self.assertEqual(run_node_expr("metrics.formatCompact(12000)"), "12.0k")

    def test_million_boundary_switches_to_m(self):
        self.assertEqual(run_node_expr("metrics.formatCompact(1000000)"), "1.0m")
        self.assertEqual(run_node_expr("metrics.formatCompact(1500000)"), "1.5m")

    def test_just_below_thousand_stays_integer(self):
        self.assertEqual(run_node_expr("metrics.formatCompact(999.4)"), "999")


if __name__ == "__main__":
    unittest.main()
