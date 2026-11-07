from __future__ import annotations

import itertools
from typing import Any

from activequal.decision.service.domain import SearchDomain

from .plan_support import PlanCollector, discrete_values, grid_value, is_numeric, step_count

MAX_PLAN = 64              # the plan never grows beyond this many points
MAX_CORNER_VERTICES = 16   # all-numeric min/max corners, in binary-counting order


class FixedCornerPlanner:
    """Nominal point, then reviewed corners, in a fixed order that depends only on the domain.

    Plan order (controls in declared order):
      1. nominal point;
      2. one-at-a-time: each numeric control at min then max, each discrete control at its other values;
      3. each numeric extreme (min/max) combined with each non-nominal value of each discrete control;
      4. all-numeric corners (every numeric control at min or max, discrete at nominal), up to 16.
    The list is truncated to 64 points. Forbidden and already-executed points (any outcome) are
    skipped; when the plan runs out fewer than ``count`` candidates are returned and the reason says so.
    """

    name = "fixed_corner"

    def plan(self, domain: SearchDomain) -> list[tuple[dict[str, Any], str]]:
        controls = list(domain.controls.values())
        nominal = {control.name: control.nominal for control in controls}
        numeric = [c for c in controls if is_numeric(c)]
        discrete = [c for c in controls if not is_numeric(c)]
        extremes = {c.name: [("min", grid_value(c, 0)), ("max", grid_value(c, step_count(c)))] for c in numeric}
        plan: list[tuple[dict[str, Any], str]] = [(nominal, "nominal point")]
        for c in numeric:
            for label, value in extremes[c.name]:
                plan.append(({**nominal, c.name: value}, f"{c.name} at {label}"))
        for c in discrete:
            for value in discrete_values(c)[1:]:
                plan.append(({**nominal, c.name: value}, f"{c.name}={value}"))
        for n in numeric:
            for label, value in extremes[n.name]:
                for d in discrete:
                    for other in discrete_values(d)[1:]:
                        plan.append(({**nominal, n.name: value, d.name: other},
                                     f"{n.name} at {label} with {d.name}={other}"))
        if len(numeric) > 1:
            for bits in itertools.islice(itertools.product((0, 1), repeat=len(numeric)), MAX_CORNER_VERTICES):
                corner = {c.name: extremes[c.name][bit][1] for c, bit in zip(numeric, bits)}
                plan.append(({**nominal, **corner}, "all-numeric corner " + "".join(map(str, bits))))
        return plan[:MAX_PLAN]

    def propose(self, domain, history, count, seed, config):
        collector = PlanCollector(domain, history, count, "BASELINE")
        reasons: list[str] = []
        for conditions, label in self.plan(domain):
            if collector.offer(conditions):
                reasons.append(f"Fixed corner plan: {label}")
            if collector.full:
                break
        return collector.proposals(reasons, "fixed corner plan exhausted")
