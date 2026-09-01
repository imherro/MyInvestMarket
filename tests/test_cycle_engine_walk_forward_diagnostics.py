from __future__ import annotations
import copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import cycle_engine_walk_forward_diagnostics as w
class WalkForwardTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.d=json.loads((ROOT/'data/cycle_engine_walk_forward_diagnostics_v1.json').read_text()); cls.e,cls.t=w.load()
 def test_snapshots_start_at_2013_12(self): self.assertEqual(self.d['snapshots'][0]['as_of_month'],'2013-12')
 def test_target_cutoff_is_explicit(self):
  self.assertTrue(all(x['target_cutoff_rule']=='target_month <= as_of_month' for s in self.d['snapshots'] for f in s['features'].values() for x in f['sample_diagnostics'].values()))
 def test_audit_passes(self): self.assertTrue(json.loads((ROOT/'data/cycle_engine_walk_forward_diagnostics_audit_v1.json').read_text())['passed'])
 def test_future_target_cutoff_tamper(self):
  x=copy.deepcopy(self.d); p=next(iter(x['snapshots'][0]['features'])); x['snapshots'][0]['features'][p]['sample_diagnostics']['forward_6m']['target_cutoff_rule']='broken'; self.assertGreater(w.audit(x)['target_cutoff_violation_count'],0)
 def test_source_hash_tamper(self):
  x=copy.deepcopy(self.d);x['source_evidence_sha']='bad';self.assertGreater(w.audit(x)['source_mutation_count'],0)
if __name__=='__main__':unittest.main()
