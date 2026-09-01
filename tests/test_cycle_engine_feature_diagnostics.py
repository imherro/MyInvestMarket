from __future__ import annotations
import copy,json,sys,unittest
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'scripts'))
import cycle_engine_feature_diagnostics as d
class DiagnosticsTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.data=json.loads((ROOT/'data/cycle_engine_feature_diagnostics_v1.json').read_text(encoding='utf-8')); cls.e,cls.t=d.load()
 def test_audit_passes(self): self.assertTrue(json.loads((ROOT/'data/cycle_engine_feature_diagnostics_audit_v1.json').read_text())['passed'])
 def test_spearman(self): self.assertEqual(d.spearman([1,2,3,4],[10,20,30,40]),1); self.assertEqual(d.spearman([1,2,3,4],[40,30,20,10]),-1)
 def test_rank_bucket_boundaries(self):
  for value,bucket in ((0,'0-20'),(19.999,'0-20'),(20,'20-40'),(39.999,'20-40'),(40,'40-60'),(59.999,'40-60'),(60,'60-80'),(79.999,'60-80'),(80,'80-100'),(100,'80-100')): self.assertEqual(d.rank_bucket(value),bucket)
  for value in (-.001,100.001):
   with self.assertRaises(ValueError): d.rank_bucket(value)
 def test_audit_detects_source_mutation(self):
  x=copy.deepcopy(self.data); x['source_evidence_sha']='bad'; self.assertFalse(d.audit(x)['passed'])
 def test_audit_detects_diagnostic_tamper(self):
  x=copy.deepcopy(self.data); p=next(iter(x['feature_diagnostics'])); x['feature_diagnostics'][p]['target_diagnostics']['forward_12m_return_pct']['spearman_rho']=999; self.assertFalse(d.audit(x)['passed'])
 def test_audit_counter_mutations(self):
  x=copy.deepcopy(self.data); x['feature_diagnostics']['future_target']= {}; self.assertGreater(d.audit(x)['unauthorized_feature_count'],0)
  x=copy.deepcopy(self.data); p=next(iter(x['feature_diagnostics'])); x['feature_diagnostics'][p]['ready_sample_count']+=1; self.assertGreater(d.audit(x)['readiness_rule_violation_count'],0)
  x=copy.deepcopy(self.data); p=next(iter(x['feature_diagnostics'])); x['feature_diagnostics'][p]['bucket_diagnostics']['0-20']['sample_count']+=1; self.assertGreater(d.audit(x)['bucket_assignment_violation_count'],0)
  x=copy.deepcopy(self.data); x['era_diagnostics']['A']='bad'; self.assertGreater(d.audit(x)['era_boundary_violation_count'],0)
 def test_future_and_noncandidate_counters(self):
  x=copy.deepcopy(self.data); x['feature_diagnostics']['forward_12m_return_pct']={}; self.assertGreater(d.audit(x)['unauthorized_feature_count'],0); self.assertGreater(d.audit(x)['future_target_used_as_feature_count'],0)
  x=copy.deepcopy(self.data); x['feature_diagnostics']['valuation.indices.csi300.pe_ttm.value']={}; self.assertGreater(d.audit(x)['non_candidate_feature_analyzed_count'],0)
 def test_boolean_redundancy_family_and_monotonicity_counters(self):
  p=next(p for p,v in self.data['feature_diagnostics'].items() if 'above_ma250' in p or 'above_50' in p)
  x=copy.deepcopy(self.data); x['feature_diagnostics'][p]['era_diagnostics']['B']['boolean_diagnostics']['forward_12m_return_pct']['true_minus_false_median']=999; self.assertGreater(d.audit(x)['boolean_group_violation_count'],0)
  x=copy.deepcopy(self.data); x['redundancy_matrix'][0]['spearman_rho']=999; self.assertGreater(d.audit(x)['redundancy_formula_violation_count'],0)
  x=copy.deepcopy(self.data); x['family_diagnostics']['valuation_level']['candidate_count']+=1; self.assertGreater(d.audit(x)['family_diagnostics_violation_count'],0)
  x=copy.deepcopy(self.data); p=next(iter(x['feature_diagnostics'])); x['feature_diagnostics'][p]['monotonic_step_count']=999; self.assertGreater(d.audit(x)['monotonicity_formula_violation_count'],0)
 def test_sample_alignment_counter(self):
  t=copy.deepcopy(self.t); t['records'][0]['month']='2018-02'
  with patch.object(d,'load',return_value=(self.e,t)): self.assertGreater(d.audit(self.data)['sample_alignment_violation_count'],0)
 def test_no_score_or_recommendation_fields(self):
  self.assertNotIn('score',self.data); self.assertNotIn('recommendation',self.data)
  self.assertFalse(any(k in self.data['feature_diagnostics'] for k in ('feature_rank','best_features','recommended_features')))
 def test_boolean_era_diagnostics_are_present(self):
  paths=[p for p in self.data['feature_diagnostics'] if 'above_ma250' in p or 'above_50' in p]
  self.assertTrue(paths)
  for p in paths:
   for era in ('A','B','C'): self.assertIn('boolean_diagnostics',self.data['feature_diagnostics'][p]['era_diagnostics'][era])
if __name__=='__main__': unittest.main()
