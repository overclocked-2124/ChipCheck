import copy
import unittest

from activequal.model.errors import InvalidRequest
from activequal.model.evidence import manifest_hash, parse_result


def payload():
    body = {
        "episodeId": "e1", "attempt": 1, "leaseId": "l1", "contractHash": "c" * 64, "fixtureId": "bench-A",
        "requested": {"oledRailV": 3.24, "redLed": True},
        "measured": {"measuredOledRailV": {"value": 3.238, "uncertainty": 0.01}, "oledLatencyMs": {"value": None}},
        "quality": {"railSettled": True, "instrumentFault": False, "shutdownConfirmed": True, "timeouts": []},
        "events": [{"type": "OUTPUT_ENABLE", "controllerTimeMs": 1203}], "traces": [], "safetyTrip": None,
    }
    body["manifestHash"] = manifest_hash(body)
    return body


class EvidenceTests(unittest.TestCase):
    def test_hash_ignores_its_own_field_and_key_order(self):
        body = payload()
        reordered = dict(reversed(list(body.items())))
        self.assertEqual(manifest_hash(body), manifest_hash(reordered))
        self.assertEqual(manifest_hash({**body, "manifestHash": "other"}), body["manifestHash"])

    def test_any_change_changes_the_hash(self):
        body = payload()
        for path, value in ((("requested", "oledRailV"), 3.25), (("attempt",), 2), (("safetyTrip",), "x")):
            changed = copy.deepcopy(body)
            target = changed
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            self.assertNotEqual(manifest_hash(changed), body["manifestHash"], path)

    def test_parse_valid(self):
        result = parse_result(payload())
        self.assertEqual(result.episode_id, "e1")
        self.assertEqual(result.measured["measuredOledRailV"].value, 3.238)
        self.assertIsNone(result.measured["oledLatencyMs"].value)
        self.assertTrue(result.shutdown_confirmed)

    def test_parse_rejects_malformed(self):
        def broken(mutate):
            body = payload()
            mutate(body)
            with self.assertRaises(InvalidRequest):
                parse_result(body)
        broken(lambda b: b.pop("episodeId"))
        broken(lambda b: b.update(attempt=0))
        broken(lambda b: b.update(attempt=True))
        broken(lambda b: b.update(requested={}))
        broken(lambda b: b["measured"].update(x={"value": float("nan")}))
        broken(lambda b: b["measured"].update(x={"value": True}))
        broken(lambda b: b["measured"].update(x={"nothing": 1}))
        broken(lambda b: b["quality"].pop("shutdownConfirmed"))
        broken(lambda b: b["quality"].update(timeouts="late"))
        broken(lambda b: b.update(safetyTrip=""))
        broken(lambda b: b.update(traces=[{"sha256": "XYZ"}]))
        broken(lambda b: b.update(events=[1]))
        with self.assertRaises(InvalidRequest):
            parse_result([])


if __name__ == "__main__":
    unittest.main()
