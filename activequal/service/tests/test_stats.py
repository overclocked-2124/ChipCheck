"""Statistics tests: hand-computed cases, textbook cases and seeded property tests.

Sources of expected values are stated beside each test. Where a value is derived here, the arithmetic is shown.
"""

import math
import random
import unittest

from activequal.service import stats

# Freireich et al. (1963) 6-MP versus placebo leukemia remission times in weeks, as tabulated in Kleinbaum & Klein,
# "Survival Analysis: A Self-Learning Text", ch. 1-2 (a "+" there marks a censored time). 6-MP arm, n = 21:
SIX_MP = [(6, 1), (6, 1), (6, 1), (6, 0), (7, 1), (9, 0), (10, 1), (10, 0), (11, 0), (13, 1), (16, 1), (17, 0),
          (19, 0), (20, 0), (22, 1), (23, 1), (25, 0), (32, 0), (32, 0), (34, 0), (35, 0)]
# Placebo arm, n = 21, no censoring.
PLACEBO = [1, 1, 2, 2, 3, 4, 4, 5, 5, 8, 8, 8, 8, 11, 11, 12, 12, 15, 17, 22, 23]


class WilsonTests(unittest.TestCase):
    def test_zero_of_ten_closed_form(self):
        # With p = 0 the upper bound is z^2 / (n + z^2): 3.841459 / 13.841459 = 0.277533.
        low, high = stats.wilson_interval(0, 10)
        self.assertEqual(low, 0.0)
        self.assertAlmostEqual(high, 3.841458820694124 / 13.841458820694124, places=9)
        self.assertAlmostEqual(high, 0.27753, places=5)

    def test_zero_of_twenty_closed_form(self):
        # 3.841459 / 23.841459 = 0.161125.
        self.assertAlmostEqual(stats.wilson_interval(0, 20)[1], 0.161125, places=6)

    def test_nine_of_ten(self):
        # Wilson interval at z = 1.96: centre = (0.9 + 3.8415/20) / (1 + 3.8415/10) = 0.7921; the half-width then gives
        # 0.5958 to 0.9821 (the same bounds are quoted in standard Wilson tables for 9/10).
        low, high = stats.wilson_interval(9, 10)
        self.assertAlmostEqual(low, 0.5958, places=4)
        self.assertAlmostEqual(high, 0.9821, places=4)

    def test_newcombe_1998_table_i(self):
        # Newcombe, Statistics in Medicine 17 (1998) 857-872, Table I, method 3 (Wilson), z = 1.96: 81/263 and 15/148.
        low, high = stats.wilson_interval(81, 263, z=1.96)
        self.assertAlmostEqual(low, 0.2553, places=4)
        self.assertAlmostEqual(high, 0.3662, places=4)
        low, high = stats.wilson_interval(15, 148, z=1.96)
        self.assertAlmostEqual(low, 0.0624, places=4)
        self.assertAlmostEqual(high, 0.1605, places=4)

    def test_edges(self):
        self.assertIsNone(stats.wilson_interval(0, 0))
        low, high = stats.wilson_interval(10, 10)
        self.assertEqual(high, 1.0)
        self.assertLess(low, 1.0)
        with self.assertRaises(ValueError):
            stats.wilson_interval(3, 2)

    def test_summary_shape(self):
        summary = stats.proportion_summary(9, 10)
        self.assertEqual((summary["numerator"], summary["denominator"], summary["rate"]), (9, 10, 0.9))
        self.assertEqual(stats.proportion_summary(0, 0)["wilson95"], None)


class BinomialTests(unittest.TestCase):
    def test_two_sided_nine_of_ten(self):
        # P(X <= 1) + P(X >= 9) under p = 0.5: 2 * (1 + 10) / 1024 = 22 / 1024.
        self.assertAlmostEqual(stats.binomial_p_value(9, 10), 22 / 1024)

    def test_one_sided(self):
        self.assertAlmostEqual(stats.binomial_p_value(9, 10, alternative="greater"), 11 / 1024)
        self.assertAlmostEqual(stats.binomial_p_value(1, 10, alternative="less"), 11 / 1024)

    def test_centre_is_one(self):
        self.assertAlmostEqual(stats.binomial_p_value(5, 10), 1.0)


class ChiSquareTests(unittest.TestCase):
    def test_critical_values(self):
        # Standard chi-square (1 d.f.) upper-tail critical values: 3.841 -> 0.05, 6.635 -> 0.01, 10.828 -> 0.001.
        self.assertAlmostEqual(stats.chi_square_sf_1df(3.841458820694124), 0.05, places=9)
        self.assertAlmostEqual(stats.chi_square_sf_1df(6.634896601021213), 0.01, places=9)
        self.assertAlmostEqual(stats.chi_square_sf_1df(10.827566170662733), 0.001, places=9)
        self.assertEqual(stats.chi_square_sf_1df(0), 1.0)


class KaplanMeierTests(unittest.TestCase):
    def test_hand_example_with_tie_and_censoring(self):
        # times 1, 2, 2, 3 (censored), 4 -> t=1: 4/5 = 0.8; t=2: two events, 4 at risk: 0.8 * 2/4 = 0.4;
        # t=3 censored; t=4: 1 at risk, 1 event: 0.4 * 0 = 0.
        km = stats.kaplan_meier([1, 2, 2, 3, 4], [1, 1, 1, 0, 1])
        self.assertEqual([s["time"] for s in km["steps"]], [1, 2, 4])
        self.assertEqual([s["atRisk"] for s in km["steps"]], [5, 4, 1])
        for got, want in zip((s["survival"] for s in km["steps"]), (0.8, 0.4, 0.0)):
            self.assertAlmostEqual(got, want)
        # Greenwood at t=1: S * sqrt(d / (n (n - d))) = 0.8 * sqrt(1 / 20) = 0.178885.
        self.assertAlmostEqual(km["steps"][0]["standardError"], 0.8 * math.sqrt(1 / 20))
        self.assertEqual((km["events"], km["censored"], km["median"]), (4, 1, 2))

    def test_events_precede_censoring_at_tied_times(self):
        # One event and one censoring both at t=2 among 2 subjects: the event sees 2 at risk, so S = 1/2.
        km = stats.kaplan_meier([2, 2], [1, 0])
        self.assertAlmostEqual(km["steps"][0]["survival"], 0.5)
        self.assertEqual(km["steps"][0]["atRisk"], 2)

    def test_freireich_6mp_curve(self):
        # Kleinbaum & Klein, Table 1.1 / ch. 2: 6-MP survival 0.857, 0.807, 0.753, 0.690, 0.627, 0.538, 0.448 at
        # weeks 6, 7, 10, 13, 16, 22, 23. Derivation: 18/21 = 0.857; x 16/17 = 0.807; x 14/15 = 0.753;
        # x 11/12 = 0.690; x 10/11 = 0.627; x 6/7 = 0.538; x 5/6 = 0.448.
        km = stats.kaplan_meier([t for t, _ in SIX_MP], [e for _, e in SIX_MP])
        expected = {6: 0.857, 7: 0.807, 10: 0.753, 13: 0.690, 16: 0.627, 22: 0.538, 23: 0.448}
        self.assertEqual([s["time"] for s in km["steps"]], list(expected))
        for step in km["steps"]:
            self.assertAlmostEqual(step["survival"], expected[step["time"]], places=3)
        self.assertEqual(km["median"], 23)          # first time S <= 0.5
        self.assertAlmostEqual(stats.survival_at(km, 12), 0.753, places=3)
        self.assertEqual(stats.survival_at(km, 3), 1.0)

    def test_all_censored(self):
        km = stats.kaplan_meier([5, 5, 5], [0, 0, 0])
        self.assertEqual((km["steps"], km["median"], km["events"], km["censored"]), ([], None, 0, 3))


class LogRankTests(unittest.TestCase):
    def test_hand_example(self):
        # A: events at 1, 2, 3; B: events at 4, 5, 6.
        # t=1: n1=3 n2=3 d=1: E=1/2,      V=(3/6)(3/6)            = 0.25
        # t=2: n1=2 n2=3 d=1: E=2/5,      V=(2/5)(3/5)            = 0.24
        # t=3: n1=1 n2=3 d=1: E=1/4,      V=(1/4)(3/4)            = 0.1875
        # t>=4: n1=0, so E=0 and V=0.
        # O1=3, E1=0.5+0.4+0.25=1.15, V=0.6775, chi2=(3-1.15)^2/0.6775=3.4225/0.6775.
        result = stats.logrank_test([1, 2, 3], [1, 1, 1], [4, 5, 6], [1, 1, 1])
        self.assertAlmostEqual(result["expectedA"], 1.15)
        self.assertAlmostEqual(result["variance"], 0.6775)
        self.assertAlmostEqual(result["chiSquare"], 3.4225 / 0.6775)
        self.assertAlmostEqual(result["p"], math.erfc(math.sqrt(3.4225 / 0.6775 / 2)))
        self.assertAlmostEqual(result["expectedA"] + result["expectedB"], 6)

    def test_tie_correction(self):
        # One time, both arms tied: n1=2 n2=2, d=2. E1 = 2*2/4 = 1, V = 2 (2/4)(2/4)(4-2)/(4-1) = 1/3.
        result = stats.logrank_test([1, 1], [1, 1], [1, 5], [1, 0])
        # Event times: t=1 only (B's second subject is censored at 5). n1=2, n2=2, d=3: E1 = 3*2/4 = 1.5,
        # V = 3 (1/2)(1/2)(4-3)/(3) = 0.25.
        self.assertAlmostEqual(result["expectedA"], 1.5)
        self.assertAlmostEqual(result["variance"], 0.25)

    def test_freireich_textbook(self):
        # Kleinbaum & Klein (ch. 2, Table 2.1): 6-MP observed 9, expected 19.25; placebo observed 21, expected
        # 10.75; log-rank chi-square 16.79 (p < 0.0001). Check: (9 - 19.25)^2 / 6.257 = 105.06 / 6.257 = 16.79.
        result = stats.logrank_test([t for t, _ in SIX_MP], [e for _, e in SIX_MP], PLACEBO, [1] * len(PLACEBO))
        self.assertEqual((result["observedA"], result["observedB"]), (9, 21))
        self.assertAlmostEqual(result["expectedA"], 19.25, places=2)
        self.assertAlmostEqual(result["expectedB"], 10.75, places=2)
        self.assertAlmostEqual(result["chiSquare"], 16.79, places=2)
        self.assertLess(result["p"], 1e-4)

    def test_symmetric_in_arms(self):
        ab = stats.logrank_test([1, 4, 7], [1, 1, 0], [2, 3, 9], [1, 0, 1])
        ba = stats.logrank_test([2, 3, 9], [1, 0, 1], [1, 4, 7], [1, 1, 0])
        self.assertAlmostEqual(ab["chiSquare"], ba["chiSquare"])

    def test_no_events_is_not_significant(self):
        result = stats.logrank_test([5, 5], [0, 0], [5, 5], [0, 0])
        self.assertEqual((result["chiSquare"], result["p"]), (0.0, 1.0))

    def test_needs_both_samples(self):
        with self.assertRaises(ValueError):
            stats.logrank_test([], [], [1], [1])

    def test_property_identical_distributions_rarely_significant(self):
        rng = random.Random(20261107)
        rejections = trials = 0
        for _ in range(300):
            samples = []
            for _arm in range(2):
                times = [min(50, math.ceil(rng.expovariate(1 / 40))) for _ in range(25)]
                samples.append((times, [t < 50 for t in times]))
            trials += 1
            rejections += stats.logrank_test(*samples[0], *samples[1])["p"] < 0.05
        # Nominal level 0.05; with 300 trials the standard error is 0.0126, so 0.095 is a 3.5-sigma ceiling.
        self.assertLess(rejections / trials, 0.095)

    def test_property_separated_exponentials_are_significant(self):
        rng = random.Random(7)
        significant = 0
        for _ in range(100):
            fast = [min(50, math.ceil(rng.expovariate(1 / 8))) for _ in range(20)]
            slow = [min(50, math.ceil(rng.expovariate(1 / 120))) for _ in range(20)]
            significant += stats.logrank_test(fast, [t < 50 for t in fast], slow, [t < 50 for t in slow])["p"] < 0.05
        self.assertGreaterEqual(significant, 95)


class DiscoveryRateTests(unittest.TestCase):
    def test_counts_and_interval(self):
        records = [{"budget": 50, "episodes_to_failure": t} for t in (3, 29, 30, 31, 50, None, None, None)]
        at30 = stats.discovery_rate(records, 30)
        self.assertEqual((at30["numerator"], at30["denominator"]), (3, 8))
        self.assertEqual(at30["wilson95"], list(stats.wilson_interval(3, 8)))
        self.assertEqual(stats.discovery_rate(records, 50)["numerator"], 5)

    def test_short_budget_campaigns_are_excluded_not_counted_as_misses(self):
        records = [{"budget": 20, "episodes_to_failure": None}, {"budget": 50, "episodes_to_failure": 10}]
        out = stats.discovery_rate(records, 30)
        self.assertEqual((out["numerator"], out["denominator"], out["excludedBudgetTooSmall"]), (1, 1, 1))


class ComparePlannersTests(unittest.TestCase):
    def synthetic(self):
        rng = random.Random(11)
        records = []
        for planner, mean in (("tpe", 10), ("random", 70), ("gp", 12)):
            for _ in range(20):
                t = math.ceil(rng.expovariate(1 / mean))
                records.append({"planner": planner, "profile": "P1", "episodes_to_failure": t if t <= 50 else None,
                                "budget": 50})
        records.append({"planner": "tpe", "profile": "P2", "episodes_to_failure": 4, "budget": 50})
        records.append({"planner": "random", "profile": "P2", "episodes_to_failure": None, "budget": 50})
        return records

    def test_structure_and_numbers(self):
        records = self.synthetic()
        out = stats.compare_planners(records)
        self.assertEqual(sorted(out["profiles"]), ["P1", "P2"])
        p1 = out["profiles"]["P1"]
        self.assertEqual(sorted(p1["planners"]), ["gp", "random", "tpe"])
        tpe_rows = [r for r in records if r["planner"] == "tpe" and r["profile"] == "P1"]
        found30 = sum(1 for r in tpe_rows if r["episodes_to_failure"] is not None and r["episodes_to_failure"] <= 30)
        rate = p1["planners"]["tpe"]["discoveryRates"]["30"]
        self.assertEqual((rate["numerator"], rate["denominator"]), (found30, 20))
        self.assertEqual(len(p1["logRank"]), 3)                   # three pairs
        direct = stats.logrank_test(
            *zip(*[(float(r["episodes_to_failure"] or 50), r["episodes_to_failure"] is not None)
                   for r in tpe_rows]),
            *zip(*[(float(r["episodes_to_failure"] or 50), r["episodes_to_failure"] is not None)
                   for r in records if r["planner"] == "random" and r["profile"] == "P1"]))
        pair = next(e for e in p1["logRank"] if (e["a"], e["b"]) == ("random", "tpe"))
        self.assertAlmostEqual(pair["chiSquare"], direct["chiSquare"])    # arms swapped: same statistic
        self.assertLess(pair["p"], 0.01)                                  # 10 vs 70 mean is well separated
        self.assertAlmostEqual(pair["pBonferroni"], min(1.0, 3 * pair["p"]))
        self.assertEqual(out["profiles"]["P2"]["planners"]["tpe"]["kaplanMeier"]["steps"][0]["time"], 4)

    def test_censoring_at_budget_not_dropped(self):
        out = stats.compare_planners([{"planner": "a", "profile": "p", "episodes_to_failure": None, "budget": 15},
                                      {"planner": "a", "profile": "p", "episodes_to_failure": 3, "budget": 15},
                                      {"planner": "b", "profile": "p", "episodes_to_failure": None, "budget": 15}],
                                     checkpoints=(15,))
        km = out["profiles"]["p"]["planners"]["a"]["kaplanMeier"]
        self.assertEqual((km["n"], km["events"], km["censored"]), (2, 1, 1))
        self.assertEqual(out["profiles"]["p"]["planners"]["a"]["discoveryRates"]["15"]["denominator"], 2)

    def test_bad_records_are_refused(self):
        with self.assertRaises(ValueError):
            stats.compare_planners([{"planner": "a", "profile": "p", "episodes_to_failure": 99, "budget": 15}])
        with self.assertRaises(ValueError):
            stats.compare_planners([{"planner": "a", "profile": "p", "budget": 15}])


if __name__ == "__main__":
    unittest.main()
