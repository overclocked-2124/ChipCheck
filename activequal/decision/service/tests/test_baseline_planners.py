import itertools
import unittest
from decimal import Decimal

from activequal.decision.service.decision import InvalidRequest, propose
from activequal.decision.service.domain import canonical, condition_key, domain_from_contract, is_forbidden, parse_history
from activequal.decision.service.planners import PLANNER_REGISTRY
from activequal.decision.service.planners.coverage_planner import halton, pairwise_array

CODES = {"STARTUP", "MODEL", "FALLBACK", "BASELINE", "MANUAL"}


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


def discrete_contract(forbidden=None):
    return contract(controls={
        "a": {"type": "categorical", "values": ["x", "y", "z"], "nominal": "y"},
        "b": {"type": "boolean", "nominal": True},
        "c": {"type": "categorical", "values": ["p", "q", "r", "s"]},
        "d": {"type": "boolean"},
    }, forbidden=forbidden or [])


def run(method, c=None, count=10, history=None, seed=5, **extra):
    request = {"contract": c or contract(), "method": method, "count": count, "seed": seed,
               "history": history or [], **extra}
    return propose(request)


def keys(result):
    return [condition_key(t["conditions"]) for t in result["tests"]]


def history_of(result, outcome="PASS"):
    return [{"conditions": t["conditions"], "outcome": outcome, "robustness": 0.5} for t in result["tests"]]


def pairs(rows, names):
    return {((a, row[a]), (b, row[b])) for row in rows for a, b in itertools.combinations(names, 2)}


class CommonBehaviour(unittest.TestCase):
    methods = ("fixed_corner", "coverage")

    def test_deterministic_unique_and_allowed(self):
        domain = domain_from_contract(contract())
        for method in self.methods:
            first = run(method)
            self.assertEqual(first, run(method))
            self.assertEqual(len(set(keys(first))), len(first["tests"]))
            for test in first["tests"]:
                self.assertFalse(is_forbidden(domain, test["conditions"]))
                self.assertEqual(test["conditions"], canonical(domain, test["conditions"]))

    def test_no_repeat_of_executed_points_whatever_the_outcome(self):
        for method in self.methods:
            for outcome in ("PASS", "INVALID_EXPERIMENT", "SAFETY_ABORT", "DUT_FAILURE"):
                first = run(method, count=4)
                history = [{"conditions": t["conditions"], "outcome": outcome,
                            **({"robustness": -1.0} if outcome in {"PASS", "DUT_FAILURE"} else {})}
                           for t in first["tests"]]
                second = run(method, count=4, history=history)
                self.assertFalse(set(keys(first)) & set(keys(second)), (method, outcome))

    def test_nominal_first_for_fixed_corner(self):
        domain = domain_from_contract(contract())
        first = run("fixed_corner", count=1)["tests"][0]["conditions"]
        self.assertEqual(first, canonical(domain, {n: c.nominal for n, c in domain.controls.items()}))

    def test_reason_codes_present_on_every_planner(self):
        manual = [{"oledRailV": 3.3, "redLed": False, "workload": "idle", "flashOffsetMs": 0, "dwellMs": 200}]
        expected = {"random": "BASELINE", "grid": "BASELINE", "fixed_corner": "BASELINE", "coverage": "BASELINE",
                    "manual": "MANUAL", "tpe": "STARTUP"}
        for method, code in expected.items():
            result = run(method, count=1, candidates=manual)
            self.assertEqual(result["tests"][0]["reasonCode"], code, method)
            self.assertTrue(result["tests"][0]["reason"])
        self.assertTrue(set(PLANNER_REGISTRY) >= {"fixed_corner", "coverage", "manual"})

    def test_adaptive_codes_switch_to_model_after_warmup(self):
        seedset = run("random", count=6)
        result = run("tpe", count=1, history=history_of(seedset), warmupTrials=4)
        self.assertEqual(result["tests"][0]["reasonCode"], "MODEL")
        self.assertIn("reason", result["tests"][0])

    def test_fallback_code(self):
        from activequal.decision.service.planners.base import OptunaPlanner
        import optuna

        class Stuck(optuna.samplers.BaseSampler):
            def infer_relative_search_space(self, study, trial):
                return {}

            def sample_relative(self, study, trial, search_space):
                return {}

            def sample_independent(self, study, trial, name, dist):
                return dist.choices[0] if hasattr(dist, "choices") else dist.low

        class StuckPlanner(OptunaPlanner):
            name = "stuck"
            fallback_to_random = True

            def make_sampler(self, domain, seed, config):
                return Stuck()

            def reason(self, trained, config):
                return "stuck"

            def code(self, trained, config):
                return "MODEL"

            def ask_limit(self, seen_count, count):
                return 3 * count + 1

        domain = domain_from_contract(contract())
        first = StuckPlanner().propose(domain, [], 1, 0, {})
        history = parse_history(domain, [{"conditions": first[0].conditions, "outcome": "PASS", "robustness": 0.1}])
        later = StuckPlanner().propose(domain, history, 2, 0, {})
        self.assertEqual({p.code for p in later}, {"FALLBACK"})


class FixedCornerTests(unittest.TestCase):
    def test_plan_contains_min_max_and_discrete_values(self):
        result = run("fixed_corner", count=10)
        rails = {t["conditions"]["oledRailV"] for t in result["tests"]}
        self.assertTrue({3.0, 3.6} <= rails or {3.0, 3.3} <= rails)
        self.assertEqual({t["conditions"]["dwellMs"] for t in result["tests"]} >= {200, 400}, True)

    def test_exhaustion_returns_fewer_and_says_so(self):
        c = contract(controls={"v": {"type": "continuous", "min": 1.0, "max": 2.0, "step": 0.5, "nominal": 1.5},
                               "led": {"type": "boolean"}}, forbidden=[])
        everything = []
        history = []
        while True:
            result = run("fixed_corner", c=c, count=3, history=history)
            if not result["tests"]:
                break
            everything += result["tests"]
            history += history_of(result)
        self.assertEqual(len(everything), len(set(keys({"tests": everything}))))
        short = run("fixed_corner", c=c, count=3, history=history[:-1])
        self.assertEqual(len(short["tests"]), 1)
        self.assertIn("exhausted", short["tests"][0]["reason"])
        self.assertIn("1 of 3", short["tests"][0]["reason"])
        self.assertEqual(run("fixed_corner", c=c, count=3, history=history)["tests"], [])

    def test_forbidden_nominal_is_skipped(self):
        c = contract(forbidden=[{"all": [{"control": "workload", "eq": "idle"}]}])
        for test in run("fixed_corner", c=c)["tests"]:
            self.assertNotEqual(test["conditions"]["workload"], "idle")

    def test_inactive_control_pinned_and_deduped(self):
        for test in run("fixed_corner", count=10)["tests"]:
            if test["conditions"]["workload"] != "flash_write":
                self.assertEqual(test["conditions"]["flashOffsetMs"], 0)


class CoverageTests(unittest.TestCase):
    def test_pairwise_array_covers_every_pair(self):
        sizes = [3, 2, 4, 2, 3]
        rows = pairwise_array(sizes)
        needed = {((i, a), (j, b)) for i, j in itertools.combinations(range(5), 2)
                  for a in range(sizes[i]) for b in range(sizes[j])}
        self.assertEqual(pairs(rows, range(5)), needed)
        self.assertEqual(rows[0], [0] * 5)
        self.assertEqual(rows, pairwise_array(sizes))
        self.assertLess(len(rows), 3 * 4 * 3)  # far smaller than the full factorial (144)

    def test_planner_output_covers_all_discrete_pairs_when_budget_allows(self):
        c = discrete_contract()
        domain = domain_from_contract(c)
        names = list(domain.controls)
        rows = pairwise_array([len(domain.controls[n].distribution.choices) for n in names])
        result = run("coverage", c=c, count=10)  # 10 is the per-request cap; array is smaller
        self.assertGreaterEqual(len(rows), 1)
        history = []
        got = []
        while len(got) < len(rows):
            step = run("coverage", c=c, count=min(10, len(rows) - len(got)), history=history)
            got += step["tests"]
            history += history_of(step)
        need = {((a, x), (b, y)) for a, b in itertools.combinations(names, 2)
                for x in domain.controls[a].distribution.choices for y in domain.controls[b].distribution.choices}
        seen = pairs([t["conditions"] for t in got], names)
        self.assertEqual(seen, need)
        self.assertEqual(result["tests"][0]["conditions"], {n: domain.controls[n].nominal for n in names})

    def test_covers_discrete_pairs_with_numeric_controls_present(self):
        c = contract(forbidden=[])
        domain = domain_from_contract(c)
        history, got = [], []
        for _ in range(3):
            step = run("coverage", c=c, count=10, history=history)
            got += step["tests"]
            history += history_of(step)
        names = ["redLed", "workload"]
        need = {(("redLed", r), ("workload", w)) for r in (False, True)
                for w in domain.controls["workload"].distribution.choices}
        self.assertTrue(need <= pairs([t["conditions"] for t in got], names))

    def test_halton_values_lie_on_step_grid_and_in_range(self):
        domain = domain_from_contract(contract(forbidden=[]))
        history, got = [], []
        for _ in range(3):
            step = run("coverage", count=10, history=history)
            got += step["tests"]
            history += history_of(step)
        for test in got:
            for name, control in domain.controls.items():
                dist = control.distribution
                if not hasattr(dist, "step"):
                    continue
                value = test["conditions"][name]
                self.assertTrue(dist.low <= value <= dist.high)
                offset = (Decimal(str(value)) - Decimal(str(dist.low))) / Decimal(str(dist.step))
                self.assertEqual(offset, offset.to_integral_value(), (name, value))
        rails = {t["conditions"]["oledRailV"] for t in got}
        self.assertGreater(len(rails), 3)

    def test_halton_is_in_unit_interval(self):
        values = [halton(i, 3) for i in range(1, 200)]
        self.assertTrue(all(0 <= v < 1 for v in values))
        self.assertEqual(halton(1, 2), 0.5)
        self.assertEqual(len(set(values)), len(values))

    def test_seed_changes_numeric_stream_but_not_array(self):
        first, second = run("coverage", seed=1, count=10), run("coverage", seed=2, count=10)
        self.assertNotEqual(keys(first), keys(second))
        self.assertEqual([t["conditions"]["workload"] for t in first["tests"][:2]],
                         [t["conditions"]["workload"] for t in second["tests"][:2]])

    def test_forbidden_never_proposed(self):
        domain = domain_from_contract(contract())
        history, got = [], []
        for _ in range(6):
            step = run("coverage", count=10, history=history)
            got += step["tests"]
            history += history_of(step)
        self.assertGreater(len(got), 10)
        self.assertFalse(any(is_forbidden(domain, t["conditions"]) for t in got))

    def test_all_discrete_domain_exhausts_with_note(self):
        c = discrete_contract()
        history, total = [], 0
        for _ in range(20):
            step = run("coverage", c=c, count=10, history=history)
            total += len(step["tests"])
            history += history_of(step)
            if len(step["tests"]) < 10:
                self.assertTrue(all("no further new points" in t["reason"] for t in step["tests"]))
                break
        else:
            self.fail("coverage never ran out on an all-discrete domain")
        self.assertGreater(total, 0)


class ManualTests(unittest.TestCase):
    def point(self, **overrides):
        value = {"oledRailV": 3.3, "redLed": False, "workload": "idle", "flashOffsetMs": 0, "dwellMs": 200}
        value.update(overrides)
        return value

    def manual(self, candidates, **kwargs):
        return run("manual", count=kwargs.pop("count", 5), candidates=candidates, **kwargs)

    def test_returns_in_order_skipping_executed(self):
        candidates = [self.point(), self.point(oledRailV=3.1), self.point(dwellMs=300), self.point(redLed=True)]
        first = self.manual(candidates, count=2)
        self.assertEqual([t["conditions"]["oledRailV"] for t in first["tests"]], [3.3, 3.1])
        self.assertEqual({t["reasonCode"] for t in first["tests"]}, {"MANUAL"})
        skipped = self.manual(candidates, history=[{"conditions": candidates[0], "outcome": "SAFETY_ABORT"}])
        self.assertEqual([t["conditions"]["oledRailV"] for t in skipped["tests"]], [3.1, 3.3, 3.3])
        self.assertIn("exhausted", skipped["tests"][0]["reason"])

    def test_values_are_normalised_and_inactive_pinned(self):
        result = self.manual([self.point(workload=" IDLE ", flashOffsetMs=10, dwellMs=300.0, oledRailV=3.2)])
        conditions = result["tests"][0]["conditions"]
        self.assertEqual(conditions["workload"], "idle")
        self.assertEqual(conditions["flashOffsetMs"], 0)
        self.assertEqual(conditions["dwellMs"], 300)
        self.assertIsInstance(conditions["dwellMs"], int)

    def test_duplicates_collapse(self):
        result = self.manual([self.point(), self.point(flashOffsetMs=15)])  # same point once pinned
        self.assertEqual(len(result["tests"]), 1)

    def test_forbidden_point_is_passed_on_for_backend_to_reject(self):
        forbidden = self.point(workload="flash_write", oledRailV=3.6)
        result = self.manual([forbidden])
        self.assertEqual(len(result["tests"]), 1)
        self.assertEqual(result["tests"][0]["conditions"]["workload"], "flash_write")

    def test_validation_errors(self):
        bad = {
            "unknown": self.point(extra=1),
            "missing": {k: v for k, v in self.point().items() if k != "dwellMs"},
            "out-of-range": self.point(oledRailV=4.0),
            "off-grid": self.point(oledRailV=3.25),
            "off-grid int": self.point(dwellMs=250),
            "bad option": self.point(workload="sleep"),
            "bad bool": self.point(redLed="yes"),
            "bool as number": self.point(dwellMs=True),
        }
        for label, candidate in bad.items():
            with self.assertRaises(InvalidRequest, msg=label) as ctx:
                self.manual([self.point(), candidate])
            self.assertIn("candidates[", str(ctx.exception), label)
        for value in (None, [], "x", [5], {}):
            with self.assertRaises(InvalidRequest):
                self.manual(value)
        with self.assertRaises(InvalidRequest):
            run("manual")

    def test_message_names_the_problem(self):
        with self.assertRaisesRegex(InvalidRequest, "unknown controls: extra"):
            self.manual([self.point(extra=1)])
        with self.assertRaisesRegex(InvalidRequest, "missing controls: dwellMs"):
            self.manual([{k: v for k, v in self.point().items() if k != "dwellMs"}])
        with self.assertRaisesRegex(InvalidRequest, "step grid"):
            self.manual([self.point(oledRailV=3.25)])


if __name__ == "__main__":
    unittest.main()
