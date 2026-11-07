import unittest

from activequal.tools.parity import check, two_proportion_z
from activequal.tools.stack import SimulatedStack


class ParityTests(unittest.TestCase):
    def test_z_statistic(self):
        self.assertEqual(two_proportion_z(10, 20, 10, 20), 0.0)
        # pooled p = 50/80 = 0.625; spread = sqrt(0.625 * 0.375 * (1/40 + 1/40)) = sqrt(0.01171875) = 0.108253; z = 0.25 / 0.108253
        self.assertAlmostEqual(two_proportion_z(30, 40, 20, 40), 2.30940, places=4)
        self.assertEqual(two_proportion_z(0, 20, 0, 20), 0.0)
        self.assertEqual(two_proportion_z(20, 20, 0, 20), float("inf"))

    def test_full_stack_matches_the_benchmark_cli_for_tpe_on_the_wide_island(self):
        result = check("B1w", "tpe", 30, 24, base_seed=11)
        self.assertTrue(result.agrees(), result)
        self.assertGreater(min(result.cli_rate, result.stack_rate), 0.45)      # both clearly find the island

    def test_full_stack_matches_the_benchmark_cli_for_random_on_the_cliff(self):
        result = check("B2", "random", 50, 30, base_seed=5)
        self.assertTrue(result.agrees(), result)

    def test_clean_device_is_never_flagged_by_either_path(self):
        result = check("B3", "random", 20, 8, base_seed=3)
        self.assertEqual((result.cli_rate, result.stack_rate), (0.0, 0.0))


class StackTests(unittest.TestCase):
    def test_simulated_stack_runs_a_campaign_through_every_service(self):
        with SimulatedStack("B1w", discovery=50, verification=24, noise_seed=3) as stack:
            steps = stack.run()
            self.assertEqual(steps[-1].kind, "completed")
            self.assertIsNotNone(stack.episodes_to_first_failure())
            self.assertEqual(len(stack.backend.counterexamples(stack.campaign_id)), 1)


if __name__ == "__main__":
    unittest.main()
