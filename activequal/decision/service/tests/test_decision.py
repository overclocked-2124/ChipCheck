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


if __name__ == "__main__":
    unittest.main()
