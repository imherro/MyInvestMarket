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
 def test_latest_eligible_origins_respect_as_of(self):
  latest=self.d['snapshots'][-1]
  for horizon,expected in ((6,'2026-02'),(12,'2025-08'),(24,'2024-08')):
   origins=[f['sample_diagnostics'][f'forward_{horizon}m']['latest_eligible_origin_month'] for f in latest['features'].values()]
   origins=[x for x in origins if x is not None]
   self.assertIn(expected,origins)
   self.assertTrue(all(x <= expected for x in origins))
 def test_max_drawdown_and_boolean_outputs_exist(self):
  self.assertTrue(all('max_drawdown_spearman_rho' in x for s in self.d['snapshots'] for f in s['features'].values() for x in f['sample_diagnostics'].values()))
  boolean_feature=next(f for f in self.d['snapshots'][-1]['features'].values() if f['boolean_diagnostics'])
  group=boolean_feature['boolean_diagnostics']['forward_6m']
  self.assertIn('true_minus_false_median',group)
  self.assertIn('max_drawdown_true_minus_false_median',group)
 def test_boolean_difference_requires_36_realized_samples(self):
  x=copy.deepcopy(self.d)
  boolean_feature=next(f for f in x['snapshots'][-1]['features'].values() if f['boolean_diagnostics'])
  group=boolean_feature['boolean_diagnostics']['forward_6m']
  group['true']['sample_count']=1; group['false']['sample_count']=1; group['true_minus_false_median']=123
  self.assertGreater(w.audit(x)['sample_count_violation_count'],0)
 def test_sign_flip_definition_ignores_zero_and_null(self):
  self.assertEqual(w.sign_flips([None,0,0.2,0.1,-0.1,-0.2,0.3]),2)
if __name__=='__main__':unittest.main()
