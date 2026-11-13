from interaction_demo import simulator
import tempfile
import copy
import unittest
from unittest.mock import patch
from activequal.decision.service.decision import propose as real_decision
from pathlib import Path
from interaction_demo.core import Campaign

class CampaignTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = Campaign(Path(self.tmp.name) / 'campaign.sqlite')

    def test_batch_budget_persistence_and_invalid_exclusion(self):
        cid = self.c.create('tpe', 3, 12)
        self.c.propose(cid, 2)
        with self.assertRaises(ValueError): self.c.propose(cid, 1)
        def invalid(cmd):
            return {'campaign_id': cmd['campaign_id'], 'batch_id': cmd['batch_id'], 'experiment_id': cmd['experiment_id'], 'applied_parameters': cmd['parameters'], 'outcome': 'INVALID', 'measurement_quality': 'INVALID', 'measurements': {}}
        self.c.run_pending(cid, invalid)
        self.c.propose(cid, 10)
        self.c.run_pending(cid)
        with self.assertRaises(ValueError): self.c.propose(cid, 1)
        self.assertEqual(len(self.c.state(cid)['experiments']), 3)

    def test_decision_receives_only_completed_outcomes_and_chunks_batches(self):
        cid = self.c.create('tpe', 50, 42)
        calls = []
        def observe(request):
            calls.append(copy.deepcopy(request))
            return real_decision(request)
        with patch('interaction_demo.core.decision_propose', side_effect=observe):
            first = self.c.propose(cid, 25)
            self.assertEqual([call['count'] for call in calls], [10, 10, 5])
            self.assertTrue(all(row['outcome'] == 'INVALID_EXPERIMENT' for row in calls[1]['history']))
            self.assertEqual(len({tuple(row['parameters'].values()) for row in first['experiments']}), 25)
            def mixed(cmd):  # the real fault is rare; force a mix of outcomes so Decision sees both
                r = simulator.execute(cmd)
                if cmd['parameters']['led1_value'] < 100: r = {**r, 'outcome': 'FAIL', 'measurements': {'buzzer_detected': False}}
                return r
            self.c.run_pending(cid, mixed)
            calls.clear()
            self.c.propose(cid, 5)
            self.assertEqual(len(calls[0]['history']), 25)
            self.assertEqual({row['outcome'] for row in calls[0]['history']}, {'PASS', 'DUT_FAILURE'})
            self.assertTrue(all(row['robustness'] in (0.0, 1.0) for row in calls[0]['history']))

    def test_result_identity_checked_before_recording(self):
        cid = self.c.create('random', 1, 2)
        self.c.propose(cid, 1)
        with self.assertRaises(ValueError):
            self.c.run_pending(cid, lambda cmd: {'campaign_id':'wrong'})
        self.assertIsNone(self.c.state(cid)['experiments'][0]['result'])

    def test_confirm_repeats_and_counts_budget(self):
        cid = self.c.create('random', 2, 2)
        self.c.propose(cid, 1)
        def fail(cmd):
            return {'campaign_id':cmd['campaign_id'], 'batch_id':cmd['batch_id'], 'experiment_id':cmd['experiment_id'], 'applied_parameters':cmd['parameters'], 'outcome':'FAIL', 'measurement_quality':'VALID', 'measurements':{}}
        first = self.c.run_pending(cid, fail)['experiments'][0]['parameters']
        second = self.c.propose(cid, 1, 'confirm')['experiments'][1]['parameters']
        self.assertEqual(first, second)
        self.c.run_pending(cid, fail)
        with self.assertRaises(ValueError): self.c.propose(cid, 1)

if __name__ == '__main__': unittest.main()


class FaultTest(unittest.TestCase):
    def test_injected_fault_range(self):
        from interaction_demo.fault_injection import buzzer_should_sound as ok
        self.assertFalse(ok(255, 255, 255))   # blue and green fully on (3.3 V), yellow at 3.3 V
        self.assertFalse(ok(255, 255, 209))   # yellow at 2.7 V, the low edge
        self.assertTrue(ok(255, 255, 208))    # yellow just below 2.7 V
        self.assertTrue(ok(249, 255, 230))    # blue not fully on
        self.assertTrue(ok(255, 200, 230))    # green not fully on
        self.assertTrue(ok(0, 0, 0))
