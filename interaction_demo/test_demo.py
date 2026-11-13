import tempfile
import unittest
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
