"""Console read views (HLD 09 §5): lists, live lease, episode detail, records, report, contract and comparison."""

import unittest

from activequal.decision.service.decision import propose
from activequal.service.http_api import Api
from activequal.service.tests.support import CANDIDATE, World
from activequal.service.tests.test_http_api import AUTH, Client


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.w = World(discovery=3, verification=2)
        self.c = Client(Api(self.w.backend, AUTH, propose))

    def tearDown(self):
        self.w.close()

    def get(self, path):
        response = self.c.call("GET", path)
        self.assertEqual(response.status, 200, response.body)
        return response.body

    def test_lists_contracts_and_fixtures(self):
        contracts = self.get("/v1/contracts")["contracts"]
        self.assertEqual([(c["contractId"], c["version"], c["approved"]) for c in contracts],
                         [(self.w.contract_key, 1, True)])
        self.assertNotIn("contract", contracts[0])          # summaries only
        fixtures = self.get("/v1/fixtures")["fixtures"]
        self.assertEqual([f["id"] for f in fixtures], ["bench-A"])
        self.assertIsNotNone(fixtures[0]["calibration"])

    def test_lease_shows_owner_and_real_heartbeat_then_clears(self):
        self.assertIsNone(self.get(f"/v1/campaigns/{self.w.campaign_id}/lease")["lease"])
        self.w.submit(0)
        claim = self.w.claim()
        self.w.walk(claim, "PREFLIGHT")
        lease = self.get(f"/v1/campaigns/{self.w.campaign_id}/lease")["lease"]
        self.assertEqual((lease["id"], lease["owner"], lease["state"]), (claim["leaseId"], "controller-1", "ACTIVE"))
        self.assertTrue(lease["lastHeartbeatAt"])
        self.w.walk(claim, "CONFIGURING", "SETTLING", "EXECUTING", "OBSERVING", "SHUTTING_DOWN")
        self.w.backend.submit_result(self.w.payload(claim), "bench-A")
        self.assertIsNone(self.get(f"/v1/campaigns/{self.w.campaign_id}/lease")["lease"])

    def test_episode_detail_adds_planner_quality_and_lease(self):
        self.w.run_episode(0, measured={"oledLatencyMs": 250.0})
        episode_id = self.w.db.one("SELECT id FROM episodes")["id"]
        detail = self.get(f"/v1/episodes/{episode_id}")
        self.assertEqual(detail["outcome"], "DUT_FAILURE")
        self.assertEqual(detail["planner"]["reasonCode"], "BASELINE")
        self.assertTrue(detail["quality"]["shutdownConfirmed"])
        self.assertEqual(detail["benchEvents"][0]["type"], "OUTPUT_ENABLE")
        self.assertEqual([l["state"] for l in detail["leases"]], ["RELEASED"])
        self.assertEqual(detail["measured"]["measuredOledRailV"]["requested"], 3.25)
        self.assertEqual(detail["discoveryIndex"], 1)

    def test_records_report_and_contract(self):
        self.w.run_episode(0)
        records = self.get(f"/v1/campaigns/{self.w.campaign_id}/records")
        self.assertEqual(len(records["episodes"]), 1)
        self.assertIn("measuredOledRailV", records["episodes"][0]["measured"])
        rep = self.get(f"/v1/campaigns/{self.w.campaign_id}/report")
        self.assertEqual(rep["campaignId"], self.w.campaign_id)
        contract = self.get(f"/v1/campaigns/{self.w.campaign_id}/contract")
        self.assertEqual((contract["contractId"], contract["contractHash"]), (self.w.contract_key, self.w.contract_hash))
        self.assertEqual(contract["maxEpisodeS"], 10)
        self.assertEqual(contract["expectedMaxRuntimeS"], 10 * (3 - 1 + 2))   # remaining episodes x maxEpisodeS

    def test_compare_uses_first_confirmed_failure_and_validates_input(self):
        body = self.get(f"/v1/compare?campaigns={self.w.campaign_id}")
        row = body["campaigns"][0]
        self.assertIsNone(row["firstConfirmedFailureAt"])
        self.assertIn("profiles", body["comparison"])
        self.assertEqual(self.c.call("GET", "/v1/compare").status, 400)
        self.assertEqual(self.c.call("GET", "/v1/compare?campaigns=nope").status, 404)

    def test_manual_candidates_take_the_next_sequence_atomically(self):
        first = self.w.backend.submit_candidate(self.w.campaign_id, None, dict(CANDIDATE),
                                                planner_reason="a", reason_code="MANUAL")
        second = self.w.backend.submit_candidate(self.w.campaign_id, None, {**CANDIDATE, "oledRailV": 3.9},
                                                 planner_reason="b", reason_code="MANUAL")
        self.assertEqual((first["plannerSequence"], second["plannerSequence"]), (0, 1))


if __name__ == "__main__":
    unittest.main()
