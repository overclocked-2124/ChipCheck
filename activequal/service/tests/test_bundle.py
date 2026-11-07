"""Evidence bundle tests: layout, round trip, tamper detection, determinism, refusal and no ground-truth leakage."""

import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from activequal.service import bundle
from activequal.service import report as rep
from activequal.service.tests.support import SAM, World
from activequal.service.tests.test_report import FAIL_CONDITIONS, clean_rig, fault_rig, trace_world

# Anything that would reveal the simulator: profile names, its module, constants and injection vocabulary.
LEAK_PATTERNS = (r"\bB1[abw]\b", r"\bB2\b", r"\bB3\b", r"(?i)simulat", r"(?i)noise_seed", r"(?i)FaultInjection",
                 r"(?i)\bprofile", r"(?i)ground.?truth label", r"_PEAK_EXCESS", r"FAIL_LINE", r"_CLIFF", r"(?i)hidden fault")


def tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class Exported(unittest.TestCase):
    """Shared exports of three finished campaigns: Rig fault, Rig clean and a hand-built one with a trace."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.fault = fault_rig()
        cls.clean = clean_rig()
        cls.hand, cls.ids = trace_world()
        cls.dirs = {}
        for name, backend, cid in (("fault", cls.fault.backend, cls.fault.world.campaign_id),
                                   ("clean", cls.clean.backend, cls.clean.world.campaign_id),
                                   ("hand", cls.hand.backend, cls.hand.campaign_id)):
            cls.dirs[name] = base / name
            bundle.export_bundle(backend, cid, cls.dirs[name])

    @classmethod
    def tearDownClass(cls):
        cls.fault.close()
        cls.clean.close()
        cls.hand.close()
        cls.tmp.cleanup()


class RoundTrip(Exported):
    def test_verify_is_clean(self):
        for name, directory in self.dirs.items():
            self.assertEqual(bundle.verify_bundle(directory), [], name)

    def test_layout(self):
        files = set(tree(self.dirs["hand"]))
        for required in ("manifest.json", "contract.json", "calibration.json", "planner.json", "episodes.jsonl",
                         "events.jsonl", "report.md", "report.json", "checksums.sha256"):
            self.assertIn(required, files)
        cx = self.hand.backend.counterexamples(self.hand.campaign_id)
        self.assertEqual({f for f in files if f.startswith("counterexamples/")},
                         {f"counterexamples/{c['id']}.json" for c in cx})
        self.assertEqual({f for f in files if f.startswith("traces/")}, {f"traces/{self.ids['trace']}"})
        self.assertEqual(set(tree(self.dirs["clean"])) & {f for f in files if f.startswith("counterexamples/")}, set())

    def test_checksums_verified_independently_with_hashlib(self):
        for directory in self.dirs.values():
            lines = (directory / "checksums.sha256").read_text().splitlines()
            self.assertEqual(lines, sorted(lines, key=lambda l: l.split("  ", 1)[1]))
            listed = {}
            for line in lines:
                digest, name = line.split("  ", 1)
                self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", digest))
                self.assertEqual(hashlib.sha256((directory / name).read_bytes()).hexdigest(), digest, name)
                listed[name] = digest
            self.assertEqual(set(listed), set(tree(directory)) - {"checksums.sha256"})

    def test_manifest(self):
        directory = self.dirs["hand"]
        manifest = json.loads((directory / "manifest.json").read_text())
        view = self.hand.backend.get_campaign(self.hand.campaign_id)
        self.assertEqual(manifest["campaignId"], self.hand.campaign_id)
        self.assertFalse(manifest["partial"])
        self.assertEqual(manifest["contract"]["hash"], view["contractHash"])
        self.assertEqual(manifest["software"]["campaign"], "git:test")
        self.assertEqual(manifest["exportedAt"], "2026-11-16T09:00:00.000Z")        # the Backend clock, not wall time
        self.assertEqual(manifest["planner"]["sha256"], hashlib.sha256((directory / "planner.json").read_bytes()).hexdigest())
        self.assertEqual(manifest["traces"][0]["sha256"], self.ids["trace"])
        self.assertEqual(manifest["counts"], {"episodes": 4, "events": manifest["counts"]["events"],
                                              "counterexamples": 1, "traces": 1})
        self.assertEqual(manifest["dutFirmwareSha256"], "0" * 64)
        self.assertTrue(manifest["calibrationId"])

    def test_contract_bytes_exactly_as_stored(self):
        directory = self.dirs["fault"]
        doc = json.loads((directory / "contract.json").read_text())
        stored = self.fault.backend.db.query("SELECT canonical_json, contract_hash FROM contract_versions")[0]
        self.assertEqual(doc["canonicalJson"], stored["canonical_json"])
        self.assertEqual(hashlib.sha256(doc["canonicalJson"].encode()).hexdigest(), stored["contract_hash"])
        self.assertEqual({a["reviewer"] for a in doc["approvals"]}, {"dana", "alex"})

    def test_episodes_cover_every_episode_with_requested_and_measured_apart(self):
        rows = [json.loads(l) for l in (self.dirs["fault"] / "episodes.jsonl").read_text().splitlines()]
        view = self.fault.backend.get_campaign(self.fault.world.campaign_id)
        self.assertEqual(len(rows), sum(view["episodesByOutcome"].values()))
        self.assertEqual({r["outcome"] for r in rows}, set(view["episodesByOutcome"]))
        sample = rows[0]
        for key in ("episodeId", "campaignId", "attempt", "role", "requested", "measured", "verdict", "planner",
                    "traces", "contractHash", "fixtureId", "software"):
            self.assertIn(key, sample)
        self.assertIn("margins", sample["verdict"])
        self.assertIn("reason", sample["planner"])
        self.assertNotIn("oledLatencyMs", sample["requested"])         # latency is measured, never requested
        invalid = [r for r in rows if r["outcome"] == "INVALID_EXPERIMENT"]
        self.assertTrue(invalid)                                       # invalid episodes are exported too

    def test_traces_events_and_counterexample_file(self):
        directory = self.dirs["hand"]
        data = (directory / "traces" / self.ids["trace"]).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), self.ids["trace"])
        episodes = {json.loads(l)["episodeId"]: json.loads(l) for l in (directory / "episodes.jsonl").read_text().splitlines()}
        self.assertEqual(episodes[self.ids["pass"]]["traces"], [self.ids["trace"]])
        events = [json.loads(l) for l in (directory / "events.jsonl").read_text().splitlines()]
        self.assertEqual([e["id"] for e in events], sorted(e["id"] for e in events))
        self.assertTrue({"CONTRACT_CREATED", "CAMPAIGN_CREATED", "COMPLETED"} <= {e["reasonCode"] for e in events})
        self.assertTrue(any(e["detail"] for e in events))
        cx = json.loads(next((directory / "counterexamples").glob("*.json")).read_text())
        self.assertEqual(cx["counterexample"]["originalEpisodeId"], self.ids["fail"])
        self.assertEqual(cx["counterexample"]["origin"], "seeded")
        self.assertEqual({e["episodeId"] for e in cx["episodes"]}, {self.ids["fail"], self.ids["replay"]})
        self.assertEqual(cx["hashes"]["contractHash"], rep.build_report(self.hand.backend, self.hand.campaign_id)["identity"]["contractHash"])

    def test_report_files_match_the_report(self):
        directory = self.dirs["fault"]
        report = rep.build_report(self.fault.backend, self.fault.world.campaign_id)
        self.assertEqual(json.loads((directory / "report.json").read_text()), report)
        self.assertEqual((directory / "report.md").read_text(), rep.render_markdown(report) + "\n")

    def test_clean_report_in_bundle_has_honest_sentence(self):
        self.assertIn(rep.NO_FAILURE_SENTENCE, (self.dirs["clean"] / "report.md").read_text())


class Tamper(Exported):
    def check_flips(self, name, positions):
        for position in positions:
            with tempfile.TemporaryDirectory() as tmp:
                copy = Path(tmp) / "b"
                for rel, data in tree(self.dirs["hand"]).items():
                    (copy / rel).parent.mkdir(parents=True, exist_ok=True)
                    (copy / rel).write_bytes(data)
                path = copy / name
                data = bytearray(path.read_bytes())
                index = position if position >= 0 else len(data) + position
                data[index] ^= 0x01
                path.write_bytes(bytes(data))
                self.assertTrue(bundle.verify_bundle(copy), f"flip at {position} of {name} not detected")

    def test_one_flipped_byte_in_every_file_is_detected(self):
        for name in tree(self.dirs["hand"]):
            size = len((self.dirs["hand"] / name).read_bytes())
            self.check_flips(name, sorted({0, size // 2, -1}))

    def test_every_byte_of_the_checksum_file_is_protected(self):
        size = len((self.dirs["hand"] / "checksums.sha256").read_bytes())
        self.check_flips("checksums.sha256", range(0, size, 7))

    def test_missing_extra_and_truncated(self):
        def fresh(tmp):
            copy = Path(tmp) / "b"
            for rel, data in tree(self.dirs["hand"]).items():
                (copy / rel).parent.mkdir(parents=True, exist_ok=True)
                (copy / rel).write_bytes(data)
            return copy
        with tempfile.TemporaryDirectory() as tmp:
            copy = fresh(tmp)
            (copy / "report.md").unlink()
            self.assertTrue(any("report.md" in p and "missing" in p for p in bundle.verify_bundle(copy)))
        with tempfile.TemporaryDirectory() as tmp:
            copy = fresh(tmp)
            (copy / "notes.txt").write_text("hello")
            self.assertTrue(any("notes.txt" in p and "not listed" in p for p in bundle.verify_bundle(copy)))
        with tempfile.TemporaryDirectory() as tmp:
            copy = fresh(tmp)
            (copy / "checksums.sha256").unlink()
            self.assertTrue(any("checksums.sha256 is missing" in p for p in bundle.verify_bundle(copy)))
        with tempfile.TemporaryDirectory() as tmp:
            copy = fresh(tmp)
            (copy / "traces" / self.ids["trace"]).unlink()
            self.assertTrue(bundle.verify_bundle(copy))
        self.assertTrue(bundle.verify_bundle(Path(self.tmp.name) / "nope"))

    def test_consistent_rewrite_is_still_caught_by_trace_hash_and_bad_json(self):
        """An attacker who also recomputes checksums.sha256 is still caught by the content checks."""
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "b"
            for rel, data in tree(self.dirs["hand"]).items():
                (copy / rel).parent.mkdir(parents=True, exist_ok=True)
                (copy / rel).write_bytes(data)
            (copy / "traces" / self.ids["trace"]).write_bytes(b"swapped trace")
            (copy / "events.jsonl").write_bytes(b'{"id": 1}\nnot json\n')
            digests = {n: hashlib.sha256(d).hexdigest() for n, d in tree(copy).items() if n != "checksums.sha256"}
            (copy / "checksums.sha256").write_text("".join(f"{digests[n]}  {n}\n" for n in sorted(digests)))
            problems = bundle.verify_bundle(copy)
            self.assertTrue(any("trace content does not match its hash" in p for p in problems), problems)
            self.assertTrue(any("events.jsonl line 2" in p for p in problems), problems)


class Determinism(Exported):
    def test_second_export_is_byte_identical(self):
        for backend, cid, name in ((self.fault.backend, self.fault.world.campaign_id, "fault"),
                                   (self.hand.backend, self.hand.campaign_id, "hand")):
            with tempfile.TemporaryDirectory() as tmp:
                again = Path(tmp) / "elsewhere" / "second"
                bundle.export_bundle(backend, cid, again)
                self.assertEqual(tree(again), tree(self.dirs[name]))

    def test_refuses_a_non_empty_directory(self):
        with self.assertRaises(bundle.BundleError):
            bundle.export_bundle(self.hand.backend, self.hand.campaign_id, self.dirs["hand"])


class Refusal(unittest.TestCase):
    def test_non_terminal_campaign_is_refused_unless_partial(self):
        world = World(discovery=2, verification=0)
        try:
            world.run_episode(0, FAIL_CONDITIONS, measured={"oledLatencyMs": 100.0})
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(bundle.BundleError) as caught:
                    bundle.export_bundle(world.backend, world.campaign_id, Path(tmp) / "b")
                self.assertIn("RUNNING", str(caught.exception))
                self.assertFalse((Path(tmp) / "b").exists())
                manifest = bundle.export_bundle(world.backend, world.campaign_id, Path(tmp) / "partial", allow_partial=True)
                self.assertTrue(manifest["partial"])
                self.assertTrue(json.loads((Path(tmp) / "partial" / "report.json").read_text())["partial"])
                self.assertIn("PARTIAL REPORT", (Path(tmp) / "partial" / "report.md").read_text())
                self.assertEqual(bundle.verify_bundle(Path(tmp) / "partial"), [])
        finally:
            world.close()

    def test_aborted_campaign_is_terminal(self):
        world = World(discovery=2, verification=0)
        try:
            world.backend.abort_campaign(world.campaign_id, world.view()["version"], SAM)
            self.assertEqual(world.view()["state"], "ABORTED")
            with tempfile.TemporaryDirectory() as tmp:
                manifest = bundle.export_bundle(world.backend, world.campaign_id, Path(tmp) / "b")
                self.assertFalse(manifest["partial"])
                self.assertEqual(manifest["stop"]["state"], "ABORTED")
        finally:
            world.close()


class NoGroundTruth(Exported):
    def test_no_simulator_vocabulary_in_any_exported_file(self):
        for name, directory in self.dirs.items():
            for rel, data in tree(directory).items():
                text = data.decode("utf-8", errors="replace")
                for pattern in LEAK_PATTERNS:
                    self.assertIsNone(re.search(pattern, text), f"{name}/{rel} matches {pattern}")

    def test_no_ground_truth_files_or_keys(self):
        for directory in self.dirs.values():
            names = " ".join(tree(directory))
            self.assertNotRegex(names, r"(?i)label|truth|fault")
            manifest = (directory / "manifest.json").read_text()
            self.assertIn("not included", manifest)
            self.assertNotIn("seededFault", manifest)

    def test_absolute_paths_do_not_leak(self):
        for directory in self.dirs.values():
            for rel, data in tree(directory).items():
                self.assertNotIn(self.tmp.name.encode(), data, rel)
                self.assertNotIn(b"/tmp/", data, rel)


if __name__ == "__main__":
    unittest.main()
