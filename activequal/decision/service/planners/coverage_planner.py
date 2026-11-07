from __future__ import annotations

import itertools
from typing import Any

from domain import SearchDomain

from .base import step_seed
from .plan_support import PlanCollector, discrete_values, grid_value, is_numeric, step_count

PRIMES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)  # one per numeric control (at most 12 controls)
TRIES_PER_ROW = 8   # Halton points tried for one array row before moving on (forbidden/executed ones are skipped)


def halton(index: int, base: int) -> float:
    """Van der Corput radical inverse of ``index`` in ``base``; lies in [0, 1)."""
    result, fraction = 0.0, 1.0 / base
    while index > 0:
        index, digit = divmod(index, base)
        result += digit * fraction
        fraction /= base
    return result


def pairwise_array(sizes: list[int]) -> list[list[int]]:
    """Deterministic greedy pairwise covering array over factors with ``sizes`` values each.

    Rows hold value indexes (0 = the nominal value). Row 0 is all-nominal. Each further row starts
    from the first uncovered pair and fills the other factors with the value covering most new pairs
    (ties go to the lowest index), so every pair of values of every two factors appears at least once.
    """
    factors = len(sizes)
    if factors == 0:
        return [[]]
    uncovered = {((i, a), (j, b)) for i, j in itertools.combinations(range(factors), 2)
                 for a in range(sizes[i]) for b in range(sizes[j])}

    def cover(row: list[int]) -> None:
        for i, j in itertools.combinations(range(factors), 2):
            uncovered.discard(((i, row[i]), (j, row[j])))

    rows = [[0] * factors]
    cover(rows[0])
    while uncovered:
        (i, a), (j, b) = min(uncovered)
        row: list[int | None] = [None] * factors
        row[i], row[j] = a, b
        for k in range(factors):
            if row[k] is not None:
                continue
            def gain(value: int, k: int = k) -> int:
                total = 0
                for m, chosen in enumerate(row):
                    if chosen is not None:
                        pair = ((m, chosen), (k, value)) if m < k else ((k, value), (m, chosen))
                        total += pair in uncovered
                return total
            row[k] = max(range(sizes[k]), key=lambda value: (gain(value), -value))
        done = [int(value) for value in row if value is not None]
        rows.append(done)
        cover(done)
    return rows


class CoveragePlanner:
    """Pairwise covering array over categorical/boolean controls plus a Halton sequence for numeric ones.

    Rows of the array (row 0 = every nominal value) are visited in order. Numeric controls take the
    nominal values on row 0, every minimum on row 1 and every maximum on row 2 (so nominal and corners
    are folded in), then Halton points on the step grid. Halton index offset comes from the campaign
    seed (``step_seed``), not from the history length, so the stream is stable and executed points are
    simply skipped. A row whose point is forbidden or executed retries with later Halton points
    (up to 8). After the array is used the rows repeat with fresh Halton points. The planner stops
    (and says so) when a full pass produces nothing new, e.g. an all-discrete domain whose array is spent.
    Forbidden rules may remove array rows, so pair coverage is guaranteed only when none apply.
    """

    name = "coverage"

    def propose(self, domain: SearchDomain, history, count, seed, config):
        controls = list(domain.controls.values())
        discrete = [c for c in controls if not is_numeric(c)]
        numeric = [c for c in controls if is_numeric(c)]
        values = [discrete_values(c) for c in discrete]
        rows = pairwise_array([len(v) for v in values])
        offset = 1 + step_seed(seed, 0, "coverage-halton") % 4096
        collector = PlanCollector(domain, history, count, "BASELINE")
        reasons: list[str] = []
        fixed_numeric = [
            {c.name: c.nominal for c in numeric},
            {c.name: grid_value(c, 0) for c in numeric},
            {c.name: grid_value(c, step_count(c)) for c in numeric},
        ]
        counter = 0
        for cycle in itertools.count():
            progressed = False
            for row_index, row in enumerate(rows):
                point = {c.name: values[k][row[k]] for k, c in enumerate(discrete)}
                for attempt in range(TRIES_PER_ROW):
                    if collector.full:
                        break
                    if numeric and cycle == 0 and row_index < 3 and attempt == 0:
                        point.update(fixed_numeric[row_index])
                        label = ("nominal", "minimum", "maximum")[row_index] + " numeric values"
                    else:
                        counter += 1
                        for k, c in enumerate(numeric):
                            unit = halton(offset + counter, PRIMES[k])
                            point[c.name] = grid_value(c, min(step_count(c), int(unit * (step_count(c) + 1))))
                        label = "Halton numeric values"
                    if collector.offer(point):
                        reasons.append(f"Coverage baseline: pairwise row {row_index + 1} of {len(rows)}, {label}")
                        progressed = True
                        break
                if collector.full:
                    break
            if collector.full or not progressed:
                break
        return collector.proposals(reasons, "coverage plan produced no further new points")
