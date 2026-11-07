import unittest

from activequal.model.contract import parse_contract
from activequal.model.errors import InvalidRequest
from activequal.model.predicates import atom_matches, rule_matches, validate_rule


def contract(**overrides):
    base = {
        "contractVersion": 2,
        "setup": {"dut": "esp32s3-oled-demo"},
        "controls": {
            "oledRailV": {"type": "continuous", "min": 3.0, "max": 3.6, "step": 0.01, "nominal": 3.3},
            "workload": {"type": "categorical", "values": ["idle", "flash_write"], "nominal": "idle"},
            "flashOffsetMs": {"type": "integer", "min": 0, "max": 20, "step": 1, "nominal": 0,
                              "activeWhen": {"control": "workload", "eq": "flash_write"}},
            "redLed": {"type": "boolean", "nominal": False},
        },
        "forbidden": [{"all": [{"control": "workload", "eq": "flash_write"}, {"control": "oledRailV", "gte": 3.55}]}],
        "campaign": {"budget": 30},
    }
    base.update(overrides)
    return base


class ParseContractTests(unittest.TestCase):
    def test_parses_controls_and_budget(self):
        model = parse_contract(contract())
        self.assertEqual(model.dut, "esp32s3-oled-demo")
        self.assertEqual(model.budget, 30)
        self.assertEqual(set(model.controls), {"oledRailV", "workload", "flashOffsetMs", "redLed"})
        rail = model.controls["oledRailV"]
        self.assertTrue(rail.continuous)
        self.assertEqual((rail.minimum, rail.maximum, rail.step, rail.nominal), (3.0, 3.6, 0.01, 3.3))
        self.assertEqual(model.controls["redLed"].values, (False, True))
        self.assertEqual(model.controls["flashOffsetMs"].nominal, 0)

    def test_rejects_wrong_version_and_missing_parts(self):
        for bad in (None, {}, contract(contractVersion=1), contract(controls={}), contract(campaign={}),
                    contract(setup={}), contract(forbidden="x")):
            with self.assertRaises(InvalidRequest, msg=repr(bad)):
                parse_contract(bad)

    def test_rejects_off_grid_nominal_and_ranges(self):
        for patch in ({"nominal": 3.305}, {"max": 3.605}, {"step": 0}, {"min": 3.6}):
            controls = contract()["controls"]
            controls["oledRailV"] = {**controls["oledRailV"], **patch}
            with self.assertRaises(InvalidRequest, msg=repr(patch)):
                parse_contract(contract(controls=controls))

    def test_rejects_activation_cycles_and_unknown_references(self):
        controls = contract()["controls"]
        controls["workload"] = {**controls["workload"], "activeWhen": {"control": "flashOffsetMs", "gte": 1}}
        with self.assertRaises(InvalidRequest):
            parse_contract(contract(controls=controls))
        with self.assertRaises(InvalidRequest):
            parse_contract(contract(forbidden=[{"all": [{"control": "ghost", "eq": 1}]}]))

    def test_rejects_non_finite_and_boolean_numbers(self):
        for value in (float("nan"), float("inf"), True, "3.3x"):
            controls = contract()["controls"]
            controls["oledRailV"] = {**controls["oledRailV"], "nominal": value}
            with self.assertRaises(InvalidRequest, msg=repr(value)):
                parse_contract(contract(controls=controls))


class PredicateTests(unittest.TestCase):
    def test_all_comparators(self):
        conditions = {"v": 3.3, "w": "idle"}
        cases = [({"control": "v", "gte": 3.3}, True), ({"control": "v", "gt": 3.3}, False),
                 ({"control": "v", "lt": 3.4}, True), ({"control": "w", "ne": "idle"}, False),
                 ({"control": "w", "in": ["idle", "x"]}, True), ({"control": "w", "eq": "x"}, False)]
        for atom, expected in cases:
            self.assertEqual(atom_matches(atom, conditions), expected, atom)

    def test_unorderable_values_fail_open_by_default_and_closed_on_request(self):
        atom = {"control": "w", "gte": 3.5}
        conditions = {"w": "idle"}
        self.assertFalse(atom_matches(atom, conditions))
        self.assertTrue(atom_matches(atom, conditions, on_error=True))
        rule = {"all": [atom]}
        self.assertFalse(rule_matches(rule, conditions))
        self.assertTrue(rule_matches(rule, conditions, on_error=True))

    def test_rule_validation(self):
        validate_rule({"all": [{"control": "a", "eq": 1}]}, {"a"}, "r")
        for bad in ({}, {"all": []}, {"all": [{"control": "a"}]}, {"all": [{"control": "a", "eq": 1, "lt": 2}]},
                    {"all": [{"control": "a", "in": 3}]}, {"any": []}):
            with self.assertRaises(InvalidRequest, msg=repr(bad)):
                validate_rule(bad, {"a"}, "r")


if __name__ == "__main__":
    unittest.main()
