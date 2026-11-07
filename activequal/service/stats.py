"""Statistics for campaign reports and planner comparisons (PRD §21.5-21.7, HLD 06 §8, HLD 08 §9).

Pure Python, standard library only. Everything here is a small, well-known estimator:

* Wilson score interval for a proportion (reproduction rate, discovery rate);
* Kaplan-Meier survival estimate with right censoring (episodes to first confirmed failure,
  censored at the discovery budget);
* two-sample log-rank test (chi-square, 1 degree of freedom, p-value from ``math.erfc``);
* exact binomial p-value;
* ``compare_planners``: the pre-registered comparison of HLD 06 §8 over per-campaign records.

Conventions: a time is the 1-based index of the discovery episode at which the event happened, or the
budget when the campaign was censored. At tied times events are counted before censorings (the standard
convention), so a subject censored at ``t`` is still at risk for an event at ``t``.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

Z95 = 1.959963984540054          # two-sided 95% normal quantile


# --------------------------------------------------------------------------- proportions

def wilson_interval(successes: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """Wilson score interval for ``successes`` out of ``n``. ``None`` when ``n`` is 0 (nothing was measured)."""
    if not (isinstance(successes, int) and isinstance(n, int)) or n < 0 or not 0 <= successes <= max(n, 0):
        raise ValueError("need integers with 0 <= successes <= n")
    if n == 0:
        return None
    p = successes / n
    z2 = z * z
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    low = 0.0 if successes == 0 else max(0.0, centre - half)       # the bound is exactly 0 or 1 at the extremes;
    high = 1.0 if successes == n else min(1.0, centre + half)      # floating point would leave 1 - 1e-16
    return low, high


def proportion_summary(successes: int, n: int, z: float = Z95) -> dict[str, Any]:
    """Numerator, denominator, rate and Wilson interval, as the reports show a reproduction or discovery rate."""
    interval = wilson_interval(successes, n, z)
    return {"numerator": successes, "denominator": n, "rate": None if n == 0 else successes / n,
            "wilson95": None if interval is None else [interval[0], interval[1]]}


def binomial_p_value(k: int, n: int, p0: float = 0.5, alternative: str = "two-sided") -> float:
    """Exact binomial test of ``k`` successes in ``n`` trials against success probability ``p0``.

    ``two-sided`` sums every outcome at most as likely as the observed one (the usual exact definition).
    """
    if not (0 <= k <= n) or not 0.0 <= p0 <= 1.0:
        raise ValueError("need 0 <= k <= n and 0 <= p0 <= 1")
    pmf = [math.comb(n, i) * (p0 ** i) * ((1 - p0) ** (n - i)) for i in range(n + 1)]
    if alternative == "greater":
        return min(1.0, sum(pmf[k:]))
    if alternative == "less":
        return min(1.0, sum(pmf[:k + 1]))
    if alternative != "two-sided":
        raise ValueError("alternative must be two-sided, greater or less")
    observed = pmf[k]
    return min(1.0, sum(p for p in pmf if p <= observed * (1 + 1e-9)))


# --------------------------------------------------------------------------- survival

def kaplan_meier(times: Sequence[float], events: Sequence[bool]) -> dict[str, Any]:
    """Kaplan-Meier estimate. ``events[i]`` is True for an observed event, False for a right-censored time.

    Returns ``steps`` (one per distinct event time: ``time``, ``atRisk``, ``events``, ``censored`` at that
    time, ``survival`` just after it and the Greenwood ``standardError``), the counts, and the median
    (smallest event time with survival <= 0.5, or None when the curve never reaches 0.5).
    """
    if len(times) != len(events):
        raise ValueError("times and events must have the same length")
    pairs = sorted(zip(times, (bool(e) for e in events)))
    at_risk = len(pairs)
    survival, greenwood = 1.0, 0.0
    steps: list[dict[str, Any]] = []
    index = 0
    while index < len(pairs):
        t = pairs[index][0]
        deaths = censored = 0
        while index < len(pairs) and pairs[index][0] == t:
            if pairs[index][1]:
                deaths += 1
            else:
                censored += 1
            index += 1
        if deaths:
            survival *= 1 - deaths / at_risk
            if at_risk > deaths:
                greenwood += deaths / (at_risk * (at_risk - deaths))
            se = survival * math.sqrt(greenwood) if at_risk > deaths else 0.0
            steps.append({"time": t, "atRisk": at_risk, "events": deaths, "censored": censored,
                          "survival": survival, "standardError": se})
        at_risk -= deaths + censored
    median = next((s["time"] for s in steps if s["survival"] <= 0.5), None)
    return {"n": len(pairs), "events": sum(s["events"] for s in steps), "censored": len(pairs) - sum(s["events"] for s in steps),
            "steps": steps, "median": median}


def survival_at(curve: dict[str, Any], t: float) -> float:
    """The Kaplan-Meier survival probability at time ``t`` (1.0 before the first event)."""
    value = 1.0
    for step in curve["steps"]:
        if step["time"] > t:
            break
        value = step["survival"]
    return value


def chi_square_sf_1df(x: float) -> float:
    """Survival function of the chi-square distribution with 1 degree of freedom: P(X >= x) = erfc(sqrt(x / 2))."""
    if x <= 0:
        return 1.0
    return math.erfc(math.sqrt(x / 2))


def logrank_test(times_a: Sequence[float], events_a: Sequence[bool],
                 times_b: Sequence[float], events_b: Sequence[bool]) -> dict[str, Any]:
    """Two-sample log-rank test (Mantel-Haenszel form, hypergeometric variance with the tie correction).

    At each distinct event time ``t`` with ``n1``, ``n2`` at risk and ``d`` events in total out of ``n = n1 + n2``:
    ``E1 += d n1 / n`` and ``V += d (n1/n) (n2/n) (n - d) / (n - 1)``. The statistic is ``(O1 - E1)^2 / V``,
    chi-square with 1 degree of freedom under the null of equal survival curves.
    """
    if len(times_a) != len(events_a) or len(times_b) != len(events_b):
        raise ValueError("times and events must have the same length")
    a = [(t, bool(e)) for t, e in zip(times_a, events_a)]
    b = [(t, bool(e)) for t, e in zip(times_b, events_b)]
    if not a or not b:
        raise ValueError("both samples need at least one subject")
    event_times = sorted({t for t, e in a + b if e})
    observed_a = sum(1 for _, e in a if e)
    observed_b = sum(1 for _, e in b if e)
    expected_a = variance = 0.0
    for t in event_times:
        n1 = sum(1 for s, _ in a if s >= t)
        n2 = sum(1 for s, _ in b if s >= t)
        d1 = sum(1 for s, e in a if e and s == t)
        d2 = sum(1 for s, e in b if e and s == t)
        n, d = n1 + n2, d1 + d2
        expected_a += d * n1 / n
        if n > 1:
            variance += d * (n1 / n) * (n2 / n) * (n - d) / (n - 1)
    expected_b = (observed_a + observed_b) - expected_a
    statistic = 0.0 if variance <= 0 else (observed_a - expected_a) ** 2 / variance
    return {"chiSquare": statistic, "df": 1, "p": chi_square_sf_1df(statistic),
            "observedA": observed_a, "expectedA": expected_a, "observedB": observed_b, "expectedB": expected_b,
            "variance": variance, "nA": len(a), "nB": len(b)}


# --------------------------------------------------------------------------- campaign records

def discovery_rate(records: Iterable[dict[str, Any]], budget: int, z: float = Z95) -> dict[str, Any]:
    """Share of campaigns with a confirmed failure within ``budget`` discovery episodes, with a Wilson interval.

    A campaign whose own budget is below ``budget`` cannot say anything about ``budget`` and is excluded
    (listed in ``excludedBudgetTooSmall``), never counted as a miss.
    """
    records = list(records)
    usable = [r for r in records if r["budget"] >= budget]
    excluded = len(records) - len(usable)
    found = sum(1 for r in usable if r["episodes_to_failure"] is not None and r["episodes_to_failure"] <= budget)
    return {"budget": budget, **proportion_summary(found, len(usable), z), "excludedBudgetTooSmall": excluded}


def _validate_record(record: dict[str, Any]) -> tuple[float, bool]:
    for key in ("planner", "profile", "episodes_to_failure", "budget"):
        if key not in record:
            raise ValueError(f"record is missing {key!r}")
    etf, budget = record["episodes_to_failure"], record["budget"]
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1:
        raise ValueError("budget must be a positive integer")
    if etf is None:
        return float(budget), False                    # right-censored at the budget
    if not isinstance(etf, int) or isinstance(etf, bool) or not 1 <= etf <= budget:
        raise ValueError("episodes_to_failure must be None or an integer between 1 and the budget")
    return float(etf), True


def compare_planners(records: Sequence[dict[str, Any]], checkpoints: Sequence[int] = (30, 50),
                     z: float = Z95) -> dict[str, Any]:
    """The pre-registered comparison of HLD 06 §8 over per-campaign records.

    ``records``: ``{"planner", "profile", "episodes_to_failure": int | None, "budget": int}``. Campaigns are
    compared only within a profile (benchmark). Per profile and planner: the Kaplan-Meier curve censored at the
    budget, the discovery rate with Wilson interval at each checkpoint, and for every pair of planners the
    log-rank test (primary metric) with a Bonferroni-adjusted p-value over the pairs of that profile.
    Records of campaigns that were not valid (invalid campaign, aborted before the budget) belong in ``excluded``
    by the caller, never silently dropped here.
    """
    by_profile: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for record in records:
        _validate_record(record)
        by_profile.setdefault(record["profile"], {}).setdefault(record["planner"], []).append(record)
    profiles: dict[str, Any] = {}
    for profile in sorted(by_profile):
        planners = by_profile[profile]
        groups: dict[str, Any] = {}
        data: dict[str, tuple[list[float], list[bool]]] = {}
        for planner in sorted(planners):
            rows = planners[planner]
            pairs = [_validate_record(r) for r in rows]
            times, flags = [p[0] for p in pairs], [p[1] for p in pairs]
            data[planner] = (times, flags)
            groups[planner] = {"campaigns": len(rows), "kaplanMeier": kaplan_meier(times, flags),
                               "discoveryRates": {str(b): discovery_rate(rows, b, z) for b in checkpoints}}
        names = sorted(planners)
        pairs_out = []
        for i, first in enumerate(names):
            for second in names[i + 1:]:
                test = logrank_test(*data[first], *data[second])
                pairs_out.append({"a": first, "b": second, **test})
        for entry in pairs_out:
            entry["pBonferroni"] = min(1.0, entry["p"] * len(pairs_out))
        profiles[profile] = {"planners": groups, "logRank": pairs_out}
    return {"primaryMetric": "episodes to first confirmed failure (discovery pool), log-rank on Kaplan-Meier curves "
                             "censored at the discovery budget",
            "checkpoints": list(checkpoints), "profiles": profiles}
