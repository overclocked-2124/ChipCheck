import itertools
import unittest

from activequal.service.states import (CAMPAIGN_TRANSITIONS, CANDIDATE_TRANSITIONS, EPISODE_TRANSITIONS,
                                       CampaignState as C, CandidateState as K, EpisodeState as E,
                                       IllegalTransition, campaign_transition, candidate_transition,
                                       episode_transition)

ARGS = dict(actor_type="test", actor_id="t1", reason_code="TEST", reason="because")

# Transcribed from the HLD 03 diagrams, independently of the tables under test.
CAMPAIGN_EDGES = {
    (C.DRAFT, C.VALIDATING), (C.VALIDATING, C.DRAFT), (C.VALIDATING, C.READY), (C.READY, C.ARMED),
    (C.ARMED, C.RUNNING), (C.RUNNING, C.PAUSING), (C.PAUSING, C.PAUSED), (C.PAUSED, C.RUNNING),
    (C.RUNNING, C.COMPLETED), (C.RUNNING, C.ABORTING), (C.ARMED, C.ABORTING), (C.ABORTING, C.ABORTED),
    (C.RUNNING, C.LOCKED_OUT), (C.ARMED, C.LOCKED_OUT), (C.LOCKED_OUT, C.DRAFT), (C.READY, C.DRAFT),
    # documented additions
    (C.PAUSING, C.LOCKED_OUT), (C.ABORTING, C.LOCKED_OUT), (C.PAUSING, C.ABORTING), (C.PAUSED, C.ABORTING),
}
CANDIDATE_EDGES = {(K.PROPOSED, K.VALIDATING), (K.VALIDATING, K.REJECTED), (K.VALIDATING, K.APPROVED),
                   (K.APPROVED, K.MATERIALIZED)}
EPISODE_EDGES = {
    (E.AVAILABLE, E.LEASED), (E.LEASED, E.PREFLIGHT), (E.PREFLIGHT, E.CONFIGURING),
    (E.PREFLIGHT, E.SHUTTING_DOWN), (E.CONFIGURING, E.SETTLING), (E.CONFIGURING, E.SHUTTING_DOWN),
    (E.SETTLING, E.EXECUTING), (E.SETTLING, E.SHUTTING_DOWN), (E.EXECUTING, E.OBSERVING),
    (E.EXECUTING, E.EMERGENCY_CUTOFF), (E.EXECUTING, E.SHUTTING_DOWN), (E.OBSERVING, E.SHUTTING_DOWN),
    (E.OBSERVING, E.EMERGENCY_CUTOFF), (E.EMERGENCY_CUTOFF, E.LOCKOUT), (E.SHUTTING_DOWN, E.SUBMITTING),
    (E.SHUTTING_DOWN, E.EMERGENCY_CUTOFF), (E.SUBMITTING, E.FINALIZED), (E.SUBMITTING, E.EVIDENCE_PENDING),
    (E.EVIDENCE_PENDING, E.FINALIZED), (E.LOCKOUT, E.FINALIZED),
    # documented additions
    (E.PREFLIGHT, E.EMERGENCY_CUTOFF), (E.CONFIGURING, E.EMERGENCY_CUTOFF), (E.SETTLING, E.EMERGENCY_CUTOFF),
}


class TransitionTableTests(unittest.TestCase):
    def check(self, enum, table, edges, move):
        self.assertEqual(set(table), set(enum), "every state needs a row, even terminal ones")
        for current, new in itertools.product(enum, enum):
            if (current, new) in edges:
                event = move(current, new, **ARGS)
                self.assertEqual((event.previous_state, event.new_state), (current, new))
                self.assertEqual(event.reason_code, "TEST")
                self.assertIsNotNone(event.at.tzinfo)
            else:
                with self.assertRaises(IllegalTransition, msg=f"{current} -> {new}"):
                    move(current, new, **ARGS)

    def test_campaign(self):
        self.check(C, CAMPAIGN_TRANSITIONS, CAMPAIGN_EDGES, campaign_transition)

    def test_candidate(self):
        self.check(K, CANDIDATE_TRANSITIONS, CANDIDATE_EDGES, candidate_transition)

    def test_episode(self):
        self.check(E, EPISODE_TRANSITIONS, EPISODE_EDGES, episode_transition)

    def test_terminal_states_have_no_exits(self):
        for state in (C.COMPLETED, C.ABORTED):
            self.assertEqual(CAMPAIGN_TRANSITIONS[state], frozenset())
        self.assertEqual(EPISODE_TRANSITIONS[E.FINALIZED], frozenset())

    def test_lockout_requires_manual_reset_to_draft_only(self):
        self.assertEqual(CAMPAIGN_TRANSITIONS[C.LOCKED_OUT], frozenset({C.DRAFT}))   # never straight to ARMED/RUNNING

    def test_cutoff_always_leads_to_lockout(self):
        self.assertEqual(EPISODE_TRANSITIONS[E.EMERGENCY_CUTOFF], frozenset({E.LOCKOUT}))

    def test_every_transition_needs_actor_and_reason(self):
        for missing in ("actor_type", "actor_id", "reason_code", "reason"):
            args = {**ARGS, missing: ""}
            with self.assertRaises(IllegalTransition):
                campaign_transition(C.DRAFT, C.VALIDATING, **args)

    def test_error_names_the_allowed_moves(self):
        with self.assertRaises(IllegalTransition) as caught:
            campaign_transition(C.DRAFT, C.RUNNING, **ARGS)
        self.assertIn("VALIDATING", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
