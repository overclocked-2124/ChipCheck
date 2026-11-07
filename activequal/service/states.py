"""Campaign, candidate and episode state machines (HLD 03 §6, §7, §8).

Each machine is a table of allowed transitions. Anything not listed is rejected, so a new
transition needs an edit here and a test, never an `if` somewhere else. A transition produces
an append-only audit event (HLD 03 §19, principle 10).

Two additions go beyond the HLD 03 diagrams; both follow from "every safety trip leads to
cutoff and lockout" (HLD 03 §13, §26) and from the simulator test "E-stop during each
physical phase" (§23.2):

* a campaign that is PAUSING or ABORTING still has an episode running, so a safety trip there
  also reaches LOCKED_OUT;
* an episode can reach EMERGENCY_CUTOFF from PREFLIGHT, CONFIGURING and SETTLING, because
  outputs may already be enabled in those phases.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Generic, Mapping, TypeVar


class IllegalTransition(ValueError):
    """The requested state change is not in the machine's transition table."""


class CampaignState(str, Enum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    READY = "READY"
    ARMED = "ARMED"
    RUNNING = "RUNNING"
    PAUSING = "PAUSING"
    PAUSED = "PAUSED"
    ABORTING = "ABORTING"
    ABORTED = "ABORTED"
    COMPLETED = "COMPLETED"
    LOCKED_OUT = "LOCKED_OUT"


class CandidateState(str, Enum):
    PROPOSED = "PROPOSED"
    VALIDATING = "VALIDATING"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    MATERIALIZED = "MATERIALIZED"


class EpisodeState(str, Enum):
    AVAILABLE = "AVAILABLE"
    LEASED = "LEASED"
    PREFLIGHT = "PREFLIGHT"
    CONFIGURING = "CONFIGURING"
    SETTLING = "SETTLING"
    EXECUTING = "EXECUTING"
    OBSERVING = "OBSERVING"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    EMERGENCY_CUTOFF = "EMERGENCY_CUTOFF"
    LOCKOUT = "LOCKOUT"
    SUBMITTING = "SUBMITTING"
    EVIDENCE_PENDING = "EVIDENCE_PENDING"
    FINALIZED = "FINALIZED"


C, K, E = CampaignState, CandidateState, EpisodeState

CAMPAIGN_TRANSITIONS: Mapping[CampaignState, frozenset[CampaignState]] = {
    C.DRAFT: frozenset({C.VALIDATING}),
    C.VALIDATING: frozenset({C.DRAFT, C.READY}),
    C.READY: frozenset({C.ARMED, C.DRAFT}),
    C.ARMED: frozenset({C.RUNNING, C.ABORTING, C.LOCKED_OUT}),
    C.RUNNING: frozenset({C.PAUSING, C.COMPLETED, C.ABORTING, C.LOCKED_OUT}),
    C.PAUSING: frozenset({C.PAUSED, C.LOCKED_OUT}),
    C.PAUSED: frozenset({C.RUNNING}),
    C.ABORTING: frozenset({C.ABORTED, C.LOCKED_OUT}),
    C.LOCKED_OUT: frozenset({C.DRAFT}),
    C.COMPLETED: frozenset(),
    C.ABORTED: frozenset(),
}

CANDIDATE_TRANSITIONS: Mapping[CandidateState, frozenset[CandidateState]] = {
    K.PROPOSED: frozenset({K.VALIDATING}),
    K.VALIDATING: frozenset({K.REJECTED, K.APPROVED}),
    K.APPROVED: frozenset({K.MATERIALIZED}),
    K.REJECTED: frozenset(),
    K.MATERIALIZED: frozenset(),
}

EPISODE_TRANSITIONS: Mapping[EpisodeState, frozenset[EpisodeState]] = {
    E.AVAILABLE: frozenset({E.LEASED}),
    E.LEASED: frozenset({E.PREFLIGHT}),
    E.PREFLIGHT: frozenset({E.CONFIGURING, E.SHUTTING_DOWN, E.EMERGENCY_CUTOFF}),
    E.CONFIGURING: frozenset({E.SETTLING, E.SHUTTING_DOWN, E.EMERGENCY_CUTOFF}),
    E.SETTLING: frozenset({E.EXECUTING, E.SHUTTING_DOWN, E.EMERGENCY_CUTOFF}),
    E.EXECUTING: frozenset({E.OBSERVING, E.EMERGENCY_CUTOFF, E.SHUTTING_DOWN}),
    E.OBSERVING: frozenset({E.SHUTTING_DOWN, E.EMERGENCY_CUTOFF}),
    E.SHUTTING_DOWN: frozenset({E.SUBMITTING, E.EMERGENCY_CUTOFF}),
    E.EMERGENCY_CUTOFF: frozenset({E.LOCKOUT}),
    E.LOCKOUT: frozenset({E.FINALIZED}),
    E.SUBMITTING: frozenset({E.FINALIZED, E.EVIDENCE_PENDING}),
    E.EVIDENCE_PENDING: frozenset({E.FINALIZED}),
    E.FINALIZED: frozenset(),
}

# States in which no physical action can still be under way for the episode.
EPISODE_TERMINAL = frozenset({E.FINALIZED})
# States in which the fixture may have energized outputs, so an unplanned loss of the owner needs cutoff.
EPISODE_MAY_BE_ENERGIZED = frozenset({E.CONFIGURING, E.SETTLING, E.EXECUTING, E.OBSERVING})

S = TypeVar("S", bound=Enum)


@dataclass(frozen=True)
class TransitionEvent(Generic[S]):
    """One audit record (HLD 03 §19). The caller adds campaign/episode identity when persisting."""

    previous_state: S
    new_state: S
    actor_type: str
    actor_id: str
    reason_code: str
    reason: str
    at: datetime


def can_transition(table: Mapping[S, frozenset[S]], current: S, new: S) -> bool:
    return new in table[current]


def transition(table: Mapping[S, frozenset[S]], current: S, new: S, *, actor_type: str, actor_id: str,
               reason_code: str, reason: str, now: datetime | None = None) -> TransitionEvent[S]:
    """Validate ``current -> new`` and return the audit event; raise ``IllegalTransition`` otherwise."""
    if current not in table or new not in table:
        raise IllegalTransition(f"unknown state in {current!r} -> {new!r}")
    if not can_transition(table, current, new):
        allowed = ", ".join(sorted(state.value for state in table[current])) or "none"
        raise IllegalTransition(f"{current.value} -> {new.value} is not allowed (allowed from {current.value}: {allowed})")
    if not (actor_type and actor_id and reason_code and reason):
        raise IllegalTransition("every transition needs an actor, a reason code and a reason")
    return TransitionEvent(current, new, actor_type, actor_id, reason_code, reason,
                           now or datetime.now(timezone.utc))


def campaign_transition(current: CampaignState, new: CampaignState, **kw) -> TransitionEvent[CampaignState]:
    return transition(CAMPAIGN_TRANSITIONS, current, new, **kw)


def candidate_transition(current: CandidateState, new: CandidateState, **kw) -> TransitionEvent[CandidateState]:
    return transition(CANDIDATE_TRANSITIONS, current, new, **kw)


def episode_transition(current: EpisodeState, new: EpisodeState, **kw) -> TransitionEvent[EpisodeState]:
    return transition(EPISODE_TRANSITIONS, current, new, **kw)
