"""Every planner value lands exactly on the contract's decimal step grid, so the safety rules never refuse it
as OFF_STEP_GRID because of binary floating point (3.5300000000000002 is 3.53)."""

import unittest

import optuna

from activequal.decision.service.decision import propose
from activequal.decision.service.domain import snap
from activequal.model.contract import parse_contract
from activequal.model.examples import oled_example_contract
from activequal.model.safety.rules import check_candidate


class GridTests(unittest.TestCase):
    def test_snap_cleans_float_noise_and_keeps_bounds(self):
        dist = optuna.distributions.FloatDistribution(3.0, 3.6, step=0.01)
        self.assertEqual([snap(dist, v) for v in (3.5300000000000002, 3.5700000000000003, 3.6000000000000005, 2.99)],
                         [3.53, 3.57, 3.6, 3.0])
        self.assertEqual(snap(optuna.distributions.IntDistribution(0, 10), 4), 4)
        self.assertEqual(snap(dist, "x"), "x")

    def test_no_planner_proposal_is_off_grid(self):
        contract = oled_example_contract()
        model = parse_contract(contract)
        for method in ("random", "tpe", "coverage", "fixed_corner", "gp"):
            tests = propose({"contract": contract, "method": method, "seed": 3, "count": 10})["tests"]
            for test in tests:
                codes = [v.code for v in check_candidate(model, test["conditions"]).violations]
                self.assertNotIn("OFF_STEP_GRID", codes, (method, test["conditions"]))


if __name__ == "__main__":
    unittest.main()
