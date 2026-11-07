"""Property-based tests for the Decision Service (requires the `hypothesis` package)."""

import contextlib
import copy
import os
import unittest

try:
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st
except ImportError:  # optional test dependency
    raise unittest.SkipTest("hypothesis is not installed") from None

import optuna

from activequal.decision.service.decision import InvalidRequest, propose
from activequal.decision.service.domain import condition_key, domain_from_contract, is_forbidden

SETTINGS = settings(max_examples=int(os.environ.get("PROP_EXAMPLES", "60")), deadline=None, suppress_health_check=list(HealthCheck))


@st.composite
def control_spec(draw):
    kind = draw(st.sampled_from(["continuous", "integer", "duration", "boolean", "categorical"]))
    if kind == "continuous":
        step = draw(st.sampled_from([0.1, 0.25, 0.5]))
        low = draw(st.integers(0, 20)) * step
        n = draw(st.integers(2, 25))
        return {"type": kind, "min": round(low, 6), "max": round(low + n * step, 6), "step": step,
                "nominal": round(low + draw(st.integers(0, n)) * step, 6)}
    if kind in {"integer", "duration"}:
        step = draw(st.integers(1, 5))
        low = draw(st.integers(0, 20))
        n = draw(st.one_of(st.integers(2, 20), st.integers(10**6, 10**12)))   # include ranges too big to list
        return {"type": kind, "min": low, "max": low + n * step, "step": step,
                "nominal": low + draw(st.integers(0, n)) * step}
    if kind == "boolean":
        return {"type": kind, "nominal": draw(st.booleans())}
    values = draw(st.lists(st.sampled_from(list("abcdefgh")), min_size=1, max_size=5, unique=True))
    return {"type": kind, "values": values, "nominal": draw(st.sampled_from(values))}


def a_value(spec, draw):
    if spec["type"] == "boolean":
        return draw(st.booleans())
    if spec["type"] == "categorical":
        return draw(st.sampled_from(spec["values"]))
    return spec["min"]


@st.composite
def contracts(draw):
    count = draw(st.integers(1, 5))
    names = [f"c{i}" for i in range(count)]
    controls = {name: draw(control_spec()) for name in names}
    for index, name in enumerate(names[1:], start=1):
        if draw(st.booleans()):
            target = names[draw(st.integers(0, index - 1))]
            controls[name]["activeWhen"] = {"control": target, "eq": a_value(controls[target], draw)}
    forbidden = []
    for _ in range(draw(st.integers(0, 2))):
        chosen = draw(st.lists(st.sampled_from(names), min_size=1, max_size=2, unique=True))
        forbidden.append({"all": [{"control": n, "eq": a_value(controls[n], draw)} for n in chosen]})
    return {"contractVersion": 2, "setup": {"dut": "prop"}, "controls": controls,
            "forbidden": forbidden, "campaign": {"budget": draw(st.integers(1, 40))}}


def run_campaign(contract, method, seed, steps, outcomes):
    """Feed proposals back as history the way an Agent would."""
    history, domain = [], domain_from_contract(contract)
    for step in range(steps):
        request = {"contract": contract, "method": method, "seed": seed, "count": 3,
                   "warmupTrials": 3, "history": history}
        result = propose(request)
        assert result == propose(request), "same request must give the same answer"
        keys = [condition_key(item["conditions"]) for item in result["tests"]]
        assert len(keys) == len(set(keys)), "duplicate proposals in one response"
        known = {condition_key(item["conditions"]) for item in history}
        assert len(result["tests"]) <= min(3, domain.budget)
        for test in result["tests"]:
            c = test["conditions"]
            assert set(c) == set(domain.controls)
            optuna.trial.create_trial(params=c, distributions=domain.distributions, value=0.0)  # in-domain
            assert condition_key(c) not in known, "re-proposed an executed point"
            assert not is_forbidden(domain, c), "proposed a forbidden combination"
            for name, control in domain.controls.items():
                atom = control.active_when
                if atom is not None and not _holds(atom, c):
                    assert c[name] == control.nominal, "inactive control not pinned to nominal"
        if not result["tests"]:
            return
        outcome = outcomes[step % len(outcomes)]
        item = {"conditions": result["tests"][0]["conditions"], "outcome": outcome}
        if outcome in {"PASS", "DUT_FAILURE"}:
            item["robustness"] = (step % 7) / 3 - 1
        history.append(item)


def _holds(atom, c):
    return c[atom["control"]] == atom["eq"]


class PropertyTests(unittest.TestCase):
    @SETTINGS
    @given(contracts(), st.sampled_from(["random", "tpe"]), st.integers(0, 1000),
           st.lists(st.sampled_from(["PASS", "DUT_FAILURE", "INVALID_EXPERIMENT", "SAFETY_ABORT"]),
                    min_size=1, max_size=6))
    def test_proposals_are_valid_unique_and_deterministic(self, contract, method, seed, outcomes):
        run_campaign(contract, method, seed, 8, outcomes)

    @SETTINGS
    @given(contracts(), st.data())
    def test_mutated_contracts_never_crash(self, contract, data):
        junk = st.one_of(st.none(), st.booleans(), st.integers(-10**6, 10**6), st.floats(allow_nan=True),
                         st.text(max_size=8), st.lists(st.integers(), max_size=3),
                         st.dictionaries(st.text(max_size=4), st.integers(), max_size=2))
        bad = copy.deepcopy(contract)
        slots = [bad]
        stack = [bad]
        while stack:  # collect every dict/list container so one entry can be overwritten
            node = stack.pop()
            for child in (node.values() if isinstance(node, dict) else node):
                if isinstance(child, (dict, list)):
                    slots.append(child)
                    stack.append(child)
        target = data.draw(st.sampled_from(slots))
        if isinstance(target, dict) and target:
            target[data.draw(st.sampled_from(sorted(target)))] = data.draw(junk)
        elif isinstance(target, list) and target:
            target[data.draw(st.integers(0, len(target) - 1))] = data.draw(junk)
        with contextlib.suppress(InvalidRequest):  # a clean rejection is the expected outcome
            propose({"contract": bad, "method": "random", "count": 2})


if __name__ == "__main__":
    unittest.main()
