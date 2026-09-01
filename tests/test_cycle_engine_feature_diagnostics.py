from __future__ import annotations
import copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'scripts'))
import cycle_engine_feature_diagnostics as d
class DiagnosticsTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.data=json.loads((ROOT/'data/cycle_engine_feature_diagnostics_v1.json').read_text(encoding='utf-8')); cls.e,cls.t=d.load()
 def test_audit_passes(self): self.assertTrue(json.loads((ROOT/'data/cycle_engine_feature_diagnostics_audit_v1.json').read_text())['passed'])
 def test_spearman(self): self.assertEqual(d.spearman([1,2,3,4],[10,20,30,40]),1); self.assertEqual(d.spearman([1,2,3,4],[40,30,20,10]),-1)
 def test_audit_detects_source_mutation(self):
  x=copy.deepcopy(self.data); x['source_evidence_sha']='bad'; self.assertFalse(d.audit(x)['passed'])
 def test_audit_detects_diagnostic_tamper(self):
  x=copy.deepcopy(self.data); p=next(iter(x['feature_diagnostics'])); x['feature_diagnostics'][p]['target_diagnostics']['forward_12m_return_pct']['spearman_rho']=999; self.assertFalse(d.audit(x)['passed'])
 def test_no_score_or_recommendation_fields(self):
  self.assertNotIn('score',self.data); self.assertNotIn('recommendation',self.data)
  self.assertFalse(any(k in self.data['feature_diagnostics'] for k in ('feature_rank','best_features','recommended_features')))
if __name__=='__main__': unittest.main()
