"""Predicates shared by ``forbidden``, ``activeWhen`` and ``requiredWhen`` (HLD 04 §12.1).

An atom is ``{"control": name, <op>: value}`` with exactly one comparator. A rule is
``{"all": [atom, ...]}`` and matches when every atom does.
"""

from __future__ import annotations

from typing import Any

from activequal.model.errors import InvalidRequest

COMPARATORS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "in": lambda a, b: a in b,
}


def validate_atom(atom: Any, known: set[str], where: str) -> None:
    if not isinstance(atom, dict) or not isinstance(atom.get("control"), str):
        raise InvalidRequest(f"{where} predicate needs a control name")
    if atom["control"] not in known:
        raise InvalidRequest(f"{where} refers to unknown control {atom['control']!r}")
    ops = [key for key in atom if key in COMPARATORS]
    if len(ops) != 1 or set(atom) != {"control", ops[0]}:
        raise InvalidRequest(f"{where} predicate needs exactly one comparator")
    if ops[0] == "in" and not isinstance(atom["in"], list):
        raise InvalidRequest(f"{where} 'in' needs a list")


def validate_rule(rule: Any, known: set[str], where: str) -> None:
    if not isinstance(rule, dict) or set(rule) != {"all"} or not isinstance(rule["all"], list) or not rule["all"]:
        raise InvalidRequest(f"{where} must be an object with a non-empty 'all' list")
    for atom in rule["all"]:
        validate_atom(atom, known, where)


def atom_matches(atom: dict[str, Any], conditions: dict[str, Any], on_error: bool = False) -> bool:
    """Evaluate one atom. ``on_error`` is the result when the values cannot be compared.

    Decision's courtesy filter keeps the default (an unorderable pair does not match).
    Authoritative safety checks pass ``on_error=True`` so that a value they cannot
    evaluate counts as a match, which rejects a forbidden rule's candidate.
    """
    op = next(key for key in atom if key in COMPARATORS)
    value = conditions[atom["control"]]
    try:
        return bool(COMPARATORS[op](value, atom[op]))
    except TypeError:
        return on_error


def rule_matches(rule: dict[str, Any], conditions: dict[str, Any], on_error: bool = False) -> bool:
    return all(atom_matches(atom, conditions, on_error) for atom in rule["all"])
