import unittest

from decision import InvalidRequest, propose


def setup():
    return {
        "name": "OLED demo",
        "rail": {"name": "OLED rail", "minimumVolts": 3.0, "maximumVolts": 3.6, "stepVolts": 0.1},
        "safety": {"maximumVolts": 3.6},
        "redLedOptions": ["on", "off"],
        "greenLedOptions": ["on", "off"],
        "workloadOptions": ["oled_refresh", "idle"],
        "experimentBudget": 30,
    }


class DecisionTests(unittest.TestCase):
    def test_proposals_stay_in_declared_domain_and_repeat_with_seed(self):
        request = {"setup": setup(), "method": "tpe", "seed": 17, "count": 3}
        first = propose(request)
        self.assertEqual(first, propose(request))
        self.assertEqual(len(first["tests"]), 3)
        self.assertEqual(first["historyUsed"], 0)
        for test in first["tests"]:
            conditions = test["conditions"]
            self.assertGreaterEqual(conditions["railVolts"], 3.0)
            self.assertLessEqual(conditions["railVolts"], 3.6)
            self.assertIn(conditions["redLed"], {"on", "off"})
            self.assertIn(conditions["greenLed"], {"on", "off"})
            self.assertIn(conditions["workload"], {"oled_refresh", "idle"})

    def test_measured_history_drives_tpe_after_warmup(self):
        base = propose({"setup": setup(), "method": "random", "seed": 23, "count": 8})["tests"]
        history = [
            {"conditions": item["conditions"], "outcome": "DUT_FAILURE" if index == 2 else "PASS",
             "robustness": -0.5 if index == 2 else 0.8}
            for index, item in enumerate(base)
        ]
        result = propose({"setup": setup(), "method": "tpe", "seed": 23, "warmupTrials": 4,
                          "history": history, "count": 2})
        self.assertEqual(result["historyUsed"], 8)
        self.assertEqual(len(result["tests"]), 2)
        self.assertIn("TPE selected", result["tests"][0]["reason"])
        self.assertNotIn(result["tests"][0]["conditions"], [x["conditions"] for x in history])

    def test_invalid_measurements_do_not_train_planner(self):
        result = propose({"setup": setup(), "history": [
            {"outcome": "INVALID_EXPERIMENT"}, {"outcome": "SAFETY_ABORT"}
        ]})
        self.assertEqual(result["historyUsed"], 0)

    def test_grid_baseline_and_budget(self):
        config = setup()
        config["experimentBudget"] = 2
        result = propose({"setup": config, "method": "grid", "count": 5})
        self.assertEqual(len(result["tests"]), 2)
        self.assertNotEqual(result["tests"][0]["conditions"], result["tests"][1]["conditions"])

    def test_optional_second_rail_is_selected_within_its_own_range(self):
        config = setup()
        config["additionalRails"] = [{"name": "Sensor rail", "minimumVolts": 3.1,
                                       "maximumVolts": 3.4, "stepVolts": 0.1}]
        result = propose({"setup": config, "method": "tpe", "count": 3})
        self.assertEqual(len(result["tests"]), 3)
        for test in result["tests"]:
            self.assertGreaterEqual(test["conditions"]["sensorRailVolts"], 3.1)
            self.assertLessEqual(test["conditions"]["sensorRailVolts"], 3.4)

    def test_refuses_unenforceable_constraints_and_ceiling_mismatch(self):
        config = setup()
        config["forbiddenCombinations"] = "red on and green off"
        with self.assertRaisesRegex(InvalidRequest, "free-text forbidden"):
            propose({"setup": config})
        config = setup()
        config["safety"]["maximumVolts"] = 3.3
        with self.assertRaisesRegex(InvalidRequest, "voltage ceiling"):
            propose({"setup": config})


class RegressionTests(unittest.TestCase):
    def test_random_planner_does_not_exhaust_on_long_history(self):
        # A stateless sampler seeded identically replays the same stream; with 50+
        # prior points that used to leave zero candidates.
        import optuna
        from domain import domain_from_setup
        config = setup()
        config["rail"]["stepVolts"] = 0.01
        domain = domain_from_setup(config)
        study = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=7))
        history = []
        for _ in range(60):
            params = study.ask(fixed_distributions=domain.distributions).params
            history.append({"conditions": params, "outcome": "PASS", "robustness": 0.5})
        result = propose({"setup": config, "method": "random", "seed": 7, "count": 1, "history": history})
        self.assertEqual(len(result["tests"]), 1)
        self.assertNotIn(result["tests"][0]["conditions"], [item["conditions"] for item in history])

    def test_invalid_and_aborted_points_are_never_reproposed(self):
        config = setup()
        config["rail"].update(minimumVolts=3.0, maximumVolts=3.1, stepVolts=0.1)
        config["redLedOptions"], config["greenLedOptions"], config["workloadOptions"] = ["on"], ["off"], ["idle"]
        points = propose({"setup": config, "method": "random", "count": 2})["tests"]
        self.assertEqual(len(points), 2)
        for outcome in ("INVALID_EXPERIMENT", "SAFETY_ABORT"):
            result = propose({"setup": config, "method": "random", "count": 2,
                              "history": [{"conditions": points[0]["conditions"], "outcome": outcome}]})
            self.assertEqual([item["conditions"] for item in result["tests"]], [points[1]["conditions"]])
            self.assertEqual(result["historyUsed"], 0)


def contract(**overrides):
    value = {
        "contractVersion": 2,
        "setup": {"dut": "demo"},
        "controls": {
            "oledRailV": {"type": "continuous", "min": 3.0, "max": 3.6, "step": 0.1, "nominal": 3.3},
            "redLed": {"type": "boolean", "nominal": False},
            "workload": {"type": "categorical", "values": ["idle", "oled_refresh", "flash_write"], "nominal": "idle"},
            "flashOffsetMs": {"type": "integer", "min": 0, "max": 20, "step": 5, "nominal": 0,
                              "activeWhen": {"control": "workload", "eq": "flash_write"}},
            "dwellMs": {"type": "duration", "min": 200, "max": 400, "step": 100, "nominal": 200},
        },
        "forbidden": [{"all": [{"control": "workload", "eq": "flash_write"}, {"control": "oledRailV", "gte": 3.5}]}],
        "campaign": {"budget": 30},
    }
    value.update(overrides)
    return value


class ContractTests(unittest.TestCase):
    def test_contract_controls_drive_the_search_space(self):
        result = propose({"contract": contract(), "method": "random", "seed": 3, "count": 10})
        self.assertEqual(result["setupName"], "demo")
        for test in result["tests"]:
            c = test["conditions"]
            self.assertEqual(set(c), {"oledRailV", "redLed", "workload", "flashOffsetMs", "dwellMs"})
            self.assertIsInstance(c["redLed"], bool)
            self.assertIn(c["dwellMs"], {200, 300, 400})
            self.assertEqual(c["flashOffsetMs"] % 5, 0)

    def test_forbidden_rules_and_inactive_controls(self):
        seen = []
        for seed in range(12):
            seen += propose({"contract": contract(), "method": "random", "seed": seed, "count": 10})["tests"]
        for test in seen:
            c = test["conditions"]
            self.assertFalse(c["workload"] == "flash_write" and c["oledRailV"] >= 3.5)
            if c["workload"] != "flash_write":
                self.assertEqual(c["flashOffsetMs"], 0)  # inactive control pinned to nominal

    def test_adaptive_planner_runs_on_mixed_contract_history(self):
        base = propose({"contract": contract(), "method": "random", "seed": 9, "count": 10})["tests"]
        history = [{"conditions": item["conditions"], "outcome": "PASS", "robustness": 0.4 + index / 100}
                   for index, item in enumerate(base)]
        result = propose({"contract": contract(), "method": "tpe", "seed": 9, "warmupTrials": 5,
                          "history": history, "count": 3})
        self.assertEqual(result["historyUsed"], 10)
        self.assertEqual(len(result["tests"]), 3)
        self.assertIn("TPE selected", result["tests"][0]["reason"])
        self.assertEqual(result, propose({"contract": contract(), "method": "tpe", "seed": 9,
                                          "warmupTrials": 5, "history": history, "count": 3}))

    def test_contract_is_validated(self):
        cases = {
            "contractVersion 2": contract(contractVersion=1),
            "nominal must sit on the step grid": contract(controls={
                "v": {"type": "continuous", "min": 3.0, "max": 3.6, "step": 0.1, "nominal": 3.33}}),
            "unknown control": contract(forbidden=[{"all": [{"control": "ghost", "eq": 1}]}]),
            "cycle": contract(controls={
                "a": {"type": "boolean", "activeWhen": {"control": "b", "eq": True}},
                "b": {"type": "boolean", "activeWhen": {"control": "a", "eq": True}}}, forbidden=[]),
            "unsupported type": contract(controls={"x": {"type": "bitfield"}}),
            "budget": contract(campaign={"budget": 0}),
        }
        for message, bad in cases.items():
            with self.subTest(message), self.assertRaisesRegex(InvalidRequest, message):
                propose({"contract": bad})
        with self.assertRaisesRegex(InvalidRequest, "either contract or setup"):
            propose({"contract": contract(), "setup": setup()})

    def test_unknown_method_lists_registered_planners(self):
        with self.assertRaisesRegex(InvalidRequest, "grid, random, tpe"):
            propose({"setup": setup(), "method": "annealing"})


def _gp_available():
    try:
        import optuna
        optuna.samplers.GPSampler(seed=0)
        return True
    except ImportError:
        return False


class GPPlannerTests(unittest.TestCase):
    @unittest.skipUnless(_gp_available(), "optional GP dependencies are not installed")
    def test_gp_proposes_in_domain_from_measured_history(self):
        base = propose({"contract": contract(), "method": "random", "seed": 4, "count": 8})["tests"]
        history = [{"conditions": item["conditions"], "outcome": "PASS", "robustness": 0.2 + index / 20}
                   for index, item in enumerate(base)]
        result = propose({"contract": contract(), "method": "gp", "seed": 4, "warmupTrials": 4,
                          "history": history, "count": 2})
        self.assertEqual(result["historyUsed"], 8)
        self.assertEqual(len(result["tests"]), 2)
        self.assertIn("GP model selected", result["tests"][0]["reason"])
        known = [item["conditions"] for item in history]
        for test in result["tests"]:
            self.assertNotIn(test["conditions"], known)
            self.assertIn(test["conditions"]["workload"], {"idle", "oled_refresh", "flash_write"})

    def test_missing_gp_dependencies_give_a_clear_error(self):
        import optuna
        from unittest import mock
        with mock.patch.object(optuna.samplers, "GPSampler", side_effect=ImportError("torch")):
            with self.assertRaisesRegex(InvalidRequest, "requirements-gp.txt"):
                propose({"setup": setup(), "method": "gp"})


if __name__ == "__main__":
    unittest.main()
