import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from activequal.adapter.service.simulator import SimulatedBenchAdapter
from activequal.controller.service.controller import Controller
from activequal.controller.service.http_client import HttpBackendClient
from activequal.controller.service.spool import Spool
from activequal.decision.service.decision import propose
from activequal.model.examples import oled_example_contract
from activequal.service.auth import ACTOR_HEADER, OPERATOR_TOKEN_HEADER, PASSPHRASE_HEADER, AuthConfig, hash_passphrase
from activequal.service.backend import Backend
from activequal.service.http_api import Api, ApiServer, Headers, Request, require_loopback
from activequal.service.runner import AgentRunner
from activequal.storage.database import Database

OPERATOR = "o" * 32
PASSPHRASE = "correct horse battery"
AUTH = AuthConfig(OPERATOR, hash_passphrase(PASSPHRASE))
GOOD_HEALTH = {"estopReleased": True, "interlockHealthy": True, "watchdogHealthy": True, "outputsInShutdown": True,
               "adaptersCompatible": True, "tripActive": False, "dutFirmwareSha256": "0" * 64,
               "mcuFirmwareSha256": "m" * 64}


class Client:
    """Calls Api.handle directly, the way the server does after parsing."""

    def __init__(self, api):
        self.api = api

    def call(self, method, path, body=None, *, human=True, reviewer=False, bearer=None, name="sam", raw=None, headers=None):
        h = dict(headers or {})
        if human:
            h.update({OPERATOR_TOKEN_HEADER: OPERATOR, ACTOR_HEADER: name})
        if reviewer:
            h[PASSPHRASE_HEADER] = PASSPHRASE
        if bearer:
            h["Authorization"] = f"Bearer {bearer}"
        payload = raw if raw is not None else json.dumps(body or {}).encode()
        path, _, query = path.partition("?")
        params = dict(p.split("=") for p in query.split("&")) if query else {}
        return self.api.handle(Request(method, path, params, Headers(h), lambda: payload))


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.backend = Backend(Database(), self.folder.name, software_version="git:test")
        self.api = Api(self.backend, AUTH, propose)
        self.c = Client(self.api)

    def tearDown(self):
        self.backend.db.close()
        self.folder.cleanup()

    def bootstrap(self, discovery=4, verification=3, planner="tpe"):
        """Everything up to a READY campaign, through the HTTP API only."""
        c = self.c
        created = c.call("POST", "/v1/contracts", {"contract": oled_example_contract()})
        self.assertEqual(created.status, 201, created.body)
        key = created.body["contractId"]
        for reviewer in ("dana", "alex"):
            r = c.call("POST", f"/v1/contracts/{key}/versions/1:approve", name=reviewer, reviewer=True)
            self.assertEqual(r.status, 200, r.body)
        fixture = c.call("POST", "/v1/fixtures", {"fixtureId": "bench-A", "revision": "A", "approvedMcuFirmwareSha256": "m" * 64,
                                                  "capabilities": ["supply.ch2", "supply.ch3", "dut", "mcu"]},
                         name="dana", reviewer=True)
        self.assertEqual(fixture.status, 201, fixture.body)
        self.token = fixture.body["token"]
        until = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        cal = c.call("POST", "/v1/fixtures/bench-A/calibrations", {
            "channels": {ch: {"gain": 1, "offset": 0, "uncertainty": 0.005} for ch in ("supply.ch2", "supply.ch3")}, "meterIdentity": "Fluke 87V",
            "operator": "sam", "validUntil": until})
        self.assertEqual(cal.status, 201, cal.body)
        self.assertEqual(c.call("POST", "/v1/bench/health", GOOD_HEALTH, human=False, bearer=self.token).status, 200)
        campaign = c.call("POST", "/v1/campaigns", {"contractId": key, "version": 1, "fixtureId": "bench-A", "planner": planner,
                                                    "seed": 42, "discoveryBudget": discovery, "verificationBudget": verification})
        self.assertEqual(campaign.status, 201, campaign.body)
        self.cid, version = campaign.body["id"], campaign.body["version"]
        v = c.call("POST", f"/v1/campaigns/{self.cid}:validate", {"campaignVersion": version})
        self.assertEqual(v.body["state"], "READY", v.body)
        a = c.call("POST", f"/v1/campaigns/{self.cid}:arm", {"campaignVersion": v.body["version"]})
        self.assertEqual(a.status, 200, a.body)
        s = c.call("POST", f"/v1/campaigns/{self.cid}:start", {"campaignVersion": a.body["version"]})
        self.assertEqual(s.body["state"], "RUNNING", s.body)
        return key


class AuthTests(ApiTestCase):
    def test_health_and_metrics_are_open_everything_else_is_not(self):
        self.assertEqual(self.c.call("GET", "/healthz", human=False).status, 200)
        self.assertIn(b"activequal_campaigns", self.c.call("GET", "/metrics", human=False).body)
        for method, path in (("GET", "/v1/campaigns"), ("POST", "/v1/contracts"), ("POST", "/v1/proposals"),
                             ("GET", "/v1/episodes/x")):
            self.assertEqual(self.c.call(method, path, human=False).status, 401, path)

    def test_operator_token_and_actor_name_are_required(self):
        bad_token = self.c.call("GET", "/v1/campaigns", human=False, headers={OPERATOR_TOKEN_HEADER: "x" * 32, ACTOR_HEADER: "sam"})
        self.assertEqual(bad_token.status, 401)
        no_name = self.c.call("GET", "/v1/campaigns", human=False, headers={OPERATOR_TOKEN_HEADER: OPERATOR})
        self.assertEqual(no_name.status, 401)
        bad_name = self.c.call("GET", "/v1/campaigns", name="sam; DROP TABLE")
        self.assertEqual(bad_name.status, 401)
        self.assertEqual(self.c.call("GET", "/v1/campaigns").status, 200)

    def test_reviewer_actions_need_the_passphrase(self):
        key = self.c.call("POST", "/v1/contracts", {"contract": oled_example_contract()}).body["contractId"]
        no_pass = self.c.call("POST", f"/v1/contracts/{key}/versions/1:approve", name="dana")
        self.assertEqual(no_pass.status, 403)
        wrong = self.c.call("POST", f"/v1/contracts/{key}/versions/1:approve", name="dana",
                            headers={PASSPHRASE_HEADER: "wrong passphrase"})
        self.assertEqual(wrong.status, 403)
        self.assertEqual(self.c.call("POST", "/v1/fixtures", {"fixtureId": "f", "revision": "A", "capabilities": ["dut"]}).status, 403)
        ok = self.c.call("POST", f"/v1/contracts/{key}/versions/1:approve", name="dana", reviewer=True)
        self.assertEqual(ok.status, 200)

    def test_bench_token_reaches_only_bench_endpoints(self):
        self.bootstrap()
        self.assertEqual(self.c.call("GET", "/v1/campaigns", human=False, bearer=self.token).status, 401)
        self.assertEqual(self.c.call("POST", "/v1/bench/claim", {"controllerInstanceId": "c"}, human=False).status, 401)
        self.assertEqual(self.c.call("POST", "/v1/bench/claim", {"controllerInstanceId": "c"}, human=False, bearer="nope").status, 401)
        self.assertEqual(self.c.call("POST", "/v1/bench/claim", {"controllerInstanceId": "c"}, human=False, bearer=self.token).status, 204)
        # an operator header does not authenticate the bench API
        self.assertEqual(self.c.call("POST", "/v1/bench/claim", {"controllerInstanceId": "c"}).status, 401)

    def test_passphrase_hashing(self):
        stored = hash_passphrase("a long enough passphrase")
        from activequal.service.auth import verify_passphrase
        self.assertTrue(verify_passphrase("a long enough passphrase", stored))
        self.assertFalse(verify_passphrase("another passphrase", stored))
        self.assertFalse(verify_passphrase("x", "garbage"))
        self.assertNotEqual(hash_passphrase("a long enough passphrase"), stored)       # salted
        with self.assertRaises(ValueError):
            AuthConfig("short", stored)
        with self.assertRaises(ValueError):
            AuthConfig("t" * 32, "plaintext")

    def test_loopback_only(self):
        for host in ("127.0.0.1", "::1", "localhost"):
            require_loopback(host)
        for host in ("0.0.0.0", "192.168.1.5", "example.com", ""):
            with self.assertRaises(ValueError):
                require_loopback(host)


class RoutingTests(ApiTestCase):
    def test_errors_follow_the_hld_05_model(self):
        self.assertEqual(self.c.call("GET", "/v1/nowhere").status, 404)
        self.assertEqual(self.c.call("DELETE", "/v1/campaigns").status, 405)
        missing = self.c.call("GET", "/v1/campaigns/none")
        self.assertEqual((missing.status, missing.body["error"]["code"]), (404, "NOT_FOUND"))
        bad = self.c.call("POST", "/v1/contracts", raw=b"{not json")
        self.assertEqual((bad.status, bad.body["error"]["code"]), (400, "INVALID_ARGUMENT"))
        self.assertEqual(self.c.call("POST", "/v1/contracts", {"contract": 5}).status, 400)
        self.assertEqual(self.c.call("POST", "/v1/contracts", {"contract": {"contractVersion": 2}}).status, 400)
        self.assertEqual(self.c.call("POST", "/v1/contracts", raw=b"[1]").status, 400)

    def test_stale_version_and_illegal_actions(self):
        key = self.bootstrap()
        stale = self.c.call("POST", f"/v1/campaigns/{self.cid}:pause", {"campaignVersion": 1})
        self.assertEqual((stale.status, stale.body["error"]["code"]), (409, "STALE_VERSION"))
        self.assertEqual(stale.body["error"]["details"]["currentVersion"], 5)
        illegal = self.c.call("POST", f"/v1/campaigns/{self.cid}:arm", {"campaignVersion": 5})
        self.assertEqual((illegal.status, illegal.body["error"]["code"]), (412, "FAILED_PRECONDITION"))
        self.assertEqual(self.c.call("POST", f"/v1/campaigns/{self.cid}:pause", {"campaignVersion": "5"}).status, 400)
        self.assertEqual(self.c.call("POST", f"/v1/campaigns/{self.cid}:pause", {"campaignVersion": True}).status, 400)

    def test_internal_errors_do_not_leak(self):
        self.api.backend = None            # break the dependency
        response = self.c.call("GET", "/v1/campaigns/x")
        self.assertEqual((response.status, response.body["error"]["code"]), (500, "INTERNAL"))
        self.assertNotIn("Traceback", json.dumps(response.body))

    def test_manual_candidate_goes_through_the_same_safety_path(self):
        self.bootstrap()
        ok = {"sensorRailV": 3.30, "redLed": True, "greenLed": False, "workload": "oled_refresh", "flashOffsetMs": 0,
              "dwellMs": 500, "oledRailV": 3.25}
        accepted = self.c.call("POST", f"/v1/campaigns/{self.cid}/manual-candidates", {"conditions": ok, "note": "demo point"})
        self.assertEqual((accepted.status, accepted.body["state"]), (201, "MATERIALIZED"))
        unsafe = self.c.call("POST", f"/v1/campaigns/{self.cid}/manual-candidates", {"conditions": {**ok, "oledRailV": 3.9}})
        self.assertEqual(unsafe.body["state"], "REJECTED")
        episodes = self.c.call("GET", f"/v1/campaigns/{self.cid}/episodes").body
        self.assertEqual(episodes["rejected"][0]["conditions"]["oledRailV"], 3.9)
        row = self.backend.db.one("SELECT reason_code FROM candidates WHERE state = 'MATERIALIZED'")
        self.assertEqual(row["reason_code"], "MANUAL")

    def test_proposals_preview_never_creates_episodes(self):
        self.bootstrap()
        contract = oled_example_contract()
        response = self.c.call("POST", "/v1/proposals", {"contract": contract, "method": "random", "seed": 1, "count": 2})
        self.assertEqual(response.status, 200)
        self.assertEqual(len(response.body["tests"]), 2)
        self.assertEqual(self.backend.in_flight_count(self.cid), 0)

    def test_events_json_and_after_cursor(self):
        self.bootstrap()
        events = self.c.call("GET", f"/v1/campaigns/{self.cid}/events").body["events"]
        self.assertEqual([e["newState"] for e in events if e["entity"] == "campaign"],
                         ["DRAFT", "VALIDATING", "READY", "ARMED", "RUNNING"])
        later = self.c.call("GET", f"/v1/campaigns/{self.cid}/events?after={events[-2]['id']}").body["events"]
        self.assertEqual([e["id"] for e in later], [events[-1]["id"]])
        self.assertEqual(self.c.call("GET", f"/v1/campaigns/{self.cid}/events?after=x").status, 400)
        sse = self.c.call("GET", f"/v1/campaigns/{self.cid}/events", headers={"Accept": "text/event-stream"})
        self.assertEqual(sse.content_type, "text/event-stream")
        stream = sse.stream
        self.assertEqual(next(stream), b": connected\n\n")
        first = next(stream).decode()
        self.assertIn("data: ", first)
        self.assertEqual(json.loads(first.split("data: ")[1].split("\n")[0])["id"], events[0]["id"])

    def test_metrics_reflect_state(self):
        self.bootstrap()
        text = self.c.call("GET", "/metrics", human=False).body.decode()
        self.assertIn('activequal_campaigns{state="RUNNING"} 1', text)


class LiveSystemTests(unittest.TestCase):
    """The whole system over real sockets: control plane + Agent runner + bench process (Gate A shape)."""

    def test_a_campaign_runs_end_to_end_over_http(self):
        with tempfile.TemporaryDirectory() as folder:
            backend = Backend(Database(), Path(folder) / "traces", software_version="git:test")
            runner = AgentRunner(backend, propose, interval_s=0.05)
            api = Api(backend, AUTH, propose, runner)
            server = ApiServer(api, "127.0.0.1", 0)
            server.start()
            base = f"http://127.0.0.1:{server.port}"

            def call(method, path, body=None, *, reviewer=False, name="sam"):
                headers = {OPERATOR_TOKEN_HEADER: OPERATOR, ACTOR_HEADER: name, "Content-Type": "application/json"}
                if reviewer:
                    headers[PASSPHRASE_HEADER] = PASSPHRASE
                request = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                                 method=method, headers=headers)
                with urllib.request.urlopen(request, timeout=10) as response:
                    return json.loads(response.read() or b"null")
            try:
                key = call("POST", "/v1/contracts", {"contract": oled_example_contract()})["contractId"]
                for reviewer in ("dana", "alex"):
                    call("POST", f"/v1/contracts/{key}/versions/1:approve", reviewer=True, name=reviewer)
                token = call("POST", "/v1/fixtures", {"fixtureId": "bench-A", "revision": "A", "approvedMcuFirmwareSha256": "m" * 64,
                                                      "capabilities": ["supply.ch2", "supply.ch3", "dut", "mcu"]},
                             reviewer=True, name="dana")["token"]
                call("POST", "/v1/fixtures/bench-A/calibrations", {
                    "channels": {ch: {"gain": 1, "offset": 0, "uncertainty": 0.005} for ch in ("supply.ch2", "supply.ch3")}, "meterIdentity": "Fluke",
                    "operator": "sam", "validUntil": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()})

                adapter = SimulatedBenchAdapter("B1w", noise_seed=3)
                controller = Controller(HttpBackendClient(base, token), adapter, Spool(Path(folder) / "spool"), "bench-A",
                                        heartbeat_interval_s=0.2)
                controller.report_health()
                campaign = call("POST", "/v1/campaigns", {"contractId": key, "version": 1, "fixtureId": "bench-A", "planner": "tpe",
                                                          "seed": 42, "discoveryBudget": 50, "verificationBudget": 24})
                cid = campaign["id"]
                state = call("POST", f"/v1/campaigns/{cid}:validate", {"campaignVersion": campaign["version"]})
                self.assertEqual(state["state"], "READY", state)
                state = call("POST", f"/v1/campaigns/{cid}:arm", {"campaignVersion": state["version"]})
                state = call("POST", f"/v1/campaigns/{cid}:start", {"campaignVersion": state["version"]})
                runner.start()

                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    if controller.run_once() is None:
                        time.sleep(0.02)
                    if call("GET", f"/v1/campaigns/{cid}")["state"] == "COMPLETED":
                        break
                view = call("GET", f"/v1/campaigns/{cid}")
                self.assertEqual(view["state"], "COMPLETED", view)
                self.assertNotIn("agentError", view)
                counterexamples = call("GET", f"/v1/campaigns/{cid}/counterexamples")["counterexamples"]
                self.assertEqual(len(counterexamples), 1)
                self.assertEqual(counterexamples[0]["reproductions"], counterexamples[0]["attempts"])
                events = call("GET", f"/v1/campaigns/{cid}/events")["events"]
                self.assertEqual(events[-1]["newState"], "COMPLETED")
                self.assertTrue(all(e["actorId"] and e["reasonCode"] for e in events))
            finally:
                runner.stop()
                server.stop()
                backend.db.close()

    def test_bench_client_maps_http_errors_and_outages(self):
        client = HttpBackendClient("http://127.0.0.1:9", "t" * 20, timeout_s=0.5)       # nothing listens there
        from activequal.service.errors import BackendError
        with self.assertRaises(BackendError) as caught:
            client.claim("c")
        self.assertEqual(caught.exception.code, "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
