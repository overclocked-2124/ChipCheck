import unittest

from activequal.model.contract import parse_contract
from activequal.model.errors import InvalidRequest
from activequal.model.examples import oled_example_contract


class OracleSectionTests(unittest.TestCase):
    def test_example_contract_parses_in_full(self):
        model = parse_contract(oled_example_contract(), require_oracle=True)
        self.assertEqual(set(model.observations),
                         {"oledLatencyMs", "maxHeartbeatGapMs", "resetCount", "measuredOledRailV",
                          "measuredDut3v3MinV"})
        self.assertEqual([r.id for r in model.requirements], ["latency", "heartbeat", "reset", "dut_3v3_band"])
        self.assertEqual(model.validity[0].tracks, "oledRailV")
        self.assertEqual(model.safety.max_episode_s, 10)
        self.assertEqual(model.safety.channels["supply.ch2"], {"maxA": 0.2, "maxV": 3.6})
        rail = model.controls["oledRailV"]
        self.assertEqual((rail.unit, rail.shutdown, rail.slew_per_s_max, rail.bind),
                         ("V", 0.0, 0.5, ("supply.ch2", "setVoltage")))
        self.assertEqual(model.plan, "default_v1")

    def test_decision_style_contract_without_oracle_sections_still_parses(self):
        contract = oled_example_contract()
        for key in ("observations", "requirements", "validity", "safety"):
            del contract[key]
        model = parse_contract(contract)
        self.assertIsNone(model.observations)
        with self.assertRaises(InvalidRequest):
            parse_contract(contract, require_oracle=True)

    def test_partial_oracle_sections_are_rejected(self):
        contract = oled_example_contract()
        del contract["safety"]
        with self.assertRaises(InvalidRequest):
            parse_contract(contract)

    def mutate(self, mutation):
        contract = oled_example_contract()
        mutation(contract)
        with self.assertRaises(InvalidRequest):
            parse_contract(contract, require_oracle=True)

    def test_rejects_bad_observations(self):
        self.mutate(lambda c: c["observations"]["resetCount"].update(source="telepathy"))
        self.mutate(lambda c: c["observations"]["resetCount"].update(reduction="median"))
        self.mutate(lambda c: c["observations"]["resetCount"].update(required=False))
        self.mutate(lambda c: c["observations"]["resetCount"].update(uncertainty=-1))
        self.mutate(lambda c: c["observations"]["oledLatencyMs"].update(requiredWhen={"control": "ghost", "eq": 1}))
        self.mutate(lambda c: c["observations"]["resetCount"].pop("unit"))

    def test_rejects_bad_requirements(self):
        self.mutate(lambda c: c["requirements"][0].update(metric="ghost"))
        self.mutate(lambda c: c["requirements"][0].update(op="<"))
        self.mutate(lambda c: c["requirements"][0].update(nominal=130))     # nominal on the wrong side of <=
        self.mutate(lambda c: c["requirements"][0].pop("nominal"))
        self.mutate(lambda c: c["requirements"][1].update(id="latency"))    # duplicate id
        self.mutate(lambda c: c["requirements"][3].update(nominal=3.5))     # outside the band
        self.mutate(lambda c: c["requirements"][3].update(lo=3.5))
        self.mutate(lambda c: c.update(requirements=[]))

    def test_requirement_on_a_swept_rail_is_rejected(self):
        self.mutate(lambda c: c["requirements"].append(
            {"id": "rail", "metric": "measuredOledRailV", "op": "band", "lo": 3.0, "hi": 3.6, "nominal": 3.3}))

    def test_rejects_bad_validity_and_safety(self):
        self.mutate(lambda c: c["validity"][0].update(tracks="workload"))
        self.mutate(lambda c: c["validity"][0].update(tracks="ghost"))
        self.mutate(lambda c: c["validity"][0].update(tolerance=0))
        self.mutate(lambda c: c["safety"].update(maxEpisodeS=0))
        self.mutate(lambda c: c["safety"].pop("maxTempC"))
        self.mutate(lambda c: c["safety"]["channels"]["supply.ch2"].update(maxA=-1))
        self.mutate(lambda c: c["safety"].update(channels={}))

    def test_rejects_bad_control_extras(self):
        self.mutate(lambda c: c["controls"]["oledRailV"].update(slewPerSMax=0))
        self.mutate(lambda c: c["controls"]["oledRailV"].update(bind={"target": "x"}))
        self.mutate(lambda c: c["controls"]["oledRailV"].update(shutdown="off"))
        self.mutate(lambda c: c["controls"]["oledRailV"].update(unit=""))


if __name__ == "__main__":
    unittest.main()
