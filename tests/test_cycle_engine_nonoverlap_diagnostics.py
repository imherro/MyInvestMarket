from __future__ import annotations
import copy, json, sys, unittest
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'scripts'))
import cycle_engine_nonoverlap_diagnostics as n

class NonOverlapTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.data=json.loads((ROOT/'data/cycle_engine_nonoverlap_diagnostics_v1.json').read_text(encoding='utf-8'))
 def test_audit_passes(self): self.assertTrue(json.loads((ROOT/'data/cycle_engine_nonoverlap_diagnostics_audit_v1.json').read_text())['passed'])
 def test_feature_and_candidate_counts(self): self.assertEqual(self.data['feature_count'],42); self.assertEqual(self.data['candidate_feature_count'],34); self.assertEqual(len(self.data['features']),34)
 def test_natural_month_rule_is_explicit(self): self.assertIn('calendar_month_index % horizon',self.data['cohort_rule']); self.assertEqual(n.month_index('2020-01')%6,1)
 def test_all_fixed_cohorts_are_present(self):
  for f in self.data['features'].values():
   for h in (6,12,24): self.assertEqual(set(f['horizons'][f'forward_{h}m']['cohorts']),{f'cohort_{i}' for i in range(h)})
 def test_cohorts_use_natural_calendar(self):
  for f in self.data['features'].values():
   for h in (6,12,24):
    for cid,c in f['horizons'][f'forward_{h}m']['cohorts'].items():
     self.assertTrue(all(n.month_index(m)%h==int(cid.split('_')[1]) for m in c['origin_months']))
 def test_cohort_spacing_is_non_overlapping(self):
  for f in self.data['features'].values():
   for h in (6,12,24):
    for c in f['horizons'][f'forward_{h}m']['cohorts'].values():
     self.assertTrue(all(n.month_index(b)-n.month_index(a)>=h for a,b in zip(c['origin_months'],c['origin_months'][1:])))
 def test_continuous_has_return_and_drawdown_rho(self):
  f=next(v for v in self.data['features'].values() if v['feature_type']=='continuous'); c=f['horizons']['forward_6m']['cohorts']['cohort_0']['continuous']; self.assertIn('spearman_rho',c['forward_return']); self.assertIn('spearman_rho',c['max_drawdown'])
 def test_boolean_has_no_spearman(self):
  f=next(v for v in self.data['features'].values() if v['feature_type']=='boolean'); c=f['horizons']['forward_6m']['cohorts']['cohort_0']['boolean']; self.assertNotIn('spearman_rho',c['forward_return']); self.assertIn('true_minus_false_median',c['max_drawdown'])
 def test_continuous_stability_fields(self):
  f=next(v for v in self.data['features'].values() if v['feature_type']=='continuous'); s=f['horizons']['forward_6m']['stability']['forward_return'];
  for k in ('valid_cohort_count','median_rho','minimum_rho','maximum_rho','positive_cohort_count','negative_cohort_count','zero_or_null_cohort_count','sign_consistency_ratio','max_abs_rho','min_abs_rho'): self.assertIn(k,s)
 def test_boolean_stability_fields(self):
  f=next(v for v in self.data['features'].values() if v['feature_type']=='boolean'); s=f['horizons']['forward_6m']['stability']['forward_return'];
  for k in ('valid_cohort_count','median_difference','minimum_difference','maximum_difference','positive_cohort_count','negative_cohort_count','sign_consistency_ratio'): self.assertIn(k,s)
 def test_overlap_comparison_fields(self):
  for f in self.data['features'].values():
   for h in (6,12,24):
    for c in f['horizons'][f'forward_{h}m']['overlap_comparison'].values(): self.assertTrue({'overlapping_value','nonoverlap_median_value','absolute_difference','same_sign'}<=set(c))
 def test_source_mutation_counter(self):
  x=copy.deepcopy(self.data); x['source_evidence_sha']='bad'; self.assertGreater(n.audit(x)['source_mutation_count'],0)
 def test_cohort_rule_mutation_counter(self):
  x=copy.deepcopy(self.data); x['cohort_rule']='record_position % horizon'; self.assertGreater(n.audit(x)['natural_month_cohort_violation_count'],0)
 def test_feature_scope_mutation_counter(self):
  x=copy.deepcopy(self.data); x['features']['fake.feature']={}; self.assertGreater(n.audit(x)['candidate_scope_violation_count'],0)
 def test_spacing_mutation_counter(self):
  x=copy.deepcopy(self.data); f=next(iter(x['features'].values())); f['horizons']['forward_6m']['cohorts']['cohort_0']['origin_months']=['2020-01','2020-02']; self.assertGreater(n.audit(x)['overlapping_origin_violation_count'],0)
 def test_origin_membership_delete_and_duplicate_counters(self):
  path=next(iter(self.data['features'])); c=self.data['features'][path]['horizons']['forward_6m']['cohorts']['cohort_0']
  x=copy.deepcopy(self.data); x['features'][path]['horizons']['forward_6m']['cohorts']['cohort_0']['origin_months']=c['origin_months'][1:]; self.assertGreater(n.audit(x)['origin_membership_violation_count'],0)
  x=copy.deepcopy(self.data); c2=x['features'][path]['horizons']['forward_6m']['cohorts']['cohort_0']; c2['origin_months'] += [c2['origin_months'][0]]; self.assertGreater(n.audit(x)['origin_membership_violation_count'],0)
 def test_continuous_mutation_counter(self):
  x=copy.deepcopy(self.data); f=next(v for v in x['features'].values() if v['feature_type']=='continuous'); f['horizons']['forward_6m']['cohorts']['cohort_0']['continuous']['forward_return']['spearman_rho']=999; self.assertGreater(n.audit(x)['correlation_formula_violation_count'],0)
 def test_boolean_mutation_counter(self):
  x=copy.deepcopy(self.data); f=next(v for v in x['features'].values() if v['feature_type']=='boolean'); f['horizons']['forward_6m']['cohorts']['cohort_0']['boolean']['forward_return']['true_minus_false_median']=999; self.assertGreater(n.audit(x)['boolean_formula_violation_count'],0)
 def test_stability_mutation_counter(self):
  x=copy.deepcopy(self.data); f=next(iter(x['features'].values())); f['horizons']['forward_6m']['stability']['forward_return']['median_rho']=999; self.assertGreater(n.audit(x)['stability_summary_violation_count'],0)
 def test_overlap_mutation_counter(self):
  x=copy.deepcopy(self.data); f=next(iter(x['features'].values())); f['horizons']['forward_6m']['overlap_comparison']['forward_return']['same_sign']=not f['horizons']['forward_6m']['overlap_comparison']['forward_return']['same_sign']; self.assertGreater(n.audit(x)['overlap_comparison_violation_count'],0)
 def test_era_boundary_mutation_counter(self):
  x=copy.deepcopy(self.data); x['eras']['A'][1]='2015-01'; self.assertGreater(n.audit(x)['era_boundary_violation_count'],0)
 def test_upstream_gate_is_required(self):
  self.assertTrue(json.loads((ROOT/'data/cycle_engine_walk_forward_diagnostics_audit_v1.json').read_text())['passed'])
 def test_target_availability_mutation_counter(self):
  x=copy.deepcopy(self.data); f=next(iter(x['features'].values())); f['horizons']['forward_6m']['cohorts']['cohort_0']['origin_months'].append('2026-08'); self.assertGreater(n.audit(x)['target_availability_violation_count'],0)
 def test_sample_alignment_mutation_counter(self):
  evidence,targets,phase3=n.load(); changed=copy.deepcopy(targets); changed['records'][0]['month']='2018-02'
  with patch.object(n,'load',return_value=(evidence,changed,phase3)): self.assertGreater(n.audit(self.data)['sample_alignment_violation_count'],0)
 def test_upstream_audit_failure_counter(self):
  class FakePath:
   def read_text(self,**kwargs): return '{"passed":false}'
  for name in ('EA','TA','DA','WA'):
   with patch.object(n,name,FakePath()): self.assertGreater(n.audit(self.data)['upstream_audit_gate_violation_count'],0)
 def test_actual_upstream_content_mutation_counter(self):
  with patch.object(n,'upstream_file_hashes',side_effect=[n.upstream_file_hashes(),{}]):
   self.assertGreater(n.audit(self.data)['upstream_mutation_count'],0)
 def test_forbidden_output_counter(self):
  for key in ('score','ranking','selection','state','regime','weight','threshold','allocation','position','signal','backtest'):
   x=copy.deepcopy(self.data); x[key]=1; self.assertGreater(n.audit(x)['forbidden_output_violation_count'],0)
 def test_research_boundary_counter(self):
  x=copy.deepcopy(self.data); x['research_only']=False; self.assertGreater(n.audit(x)['research_boundary_violation_count'],0)
  x=copy.deepcopy(self.data); x['uses_future_information']=False; self.assertGreater(n.audit(x)['research_boundary_violation_count'],0)
 def test_research_only_boundary(self):
  self.assertTrue(self.data['research_only']); self.assertNotIn('score',self.data); self.assertNotIn('position',self.data); self.assertNotIn('signal',self.data)
if __name__=='__main__': unittest.main()
