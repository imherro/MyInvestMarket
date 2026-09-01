"""As-of-time diagnostics for Cycle Engine research, never a model input."""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'
E=DATA/'cycle_engine_features_v1.json'; EA=DATA/'cycle_engine_features_audit_v1.json'; T=DATA/'cycle_engine_evaluation_targets_v1.json'; TA=DATA/'cycle_engine_evaluation_targets_audit_v1.json'; D=DATA/'cycle_engine_feature_diagnostics_v1.json'; DA=DATA/'cycle_engine_feature_diagnostics_audit_v1.json'
OUT=DATA/'cycle_engine_walk_forward_diagnostics_v1.json'; AUD=DATA/'cycle_engine_walk_forward_diagnostics_audit_v1.json'; H=(6,12,24)
def sha(x): return hashlib.sha256((json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()).hexdigest()
def rank(v): return [sum(x<z for x in v)+(sum(x==z for x in v)+1)/2 for z in v]
def rho(a,b):
 if len(a)<2:return None
 ra,rb=rank(a),rank(b); ma=sum(ra)/len(ra); mb=sum(rb)/len(rb); den=(sum((x-ma)**2 for x in ra)*sum((y-mb)**2 for y in rb))**.5
 return None if not den else round(sum((x-ma)*(y-mb) for x,y in zip(ra,rb))/den,6)
def load():
 e=json.loads(E.read_text()); t=json.loads(T.read_text());
 for p in (EA,TA,DA):
  if not json.loads(p.read_text()).get('passed'): raise RuntimeError('upstream audit gate failed')
 return e,t
def build(e,t):
 em={r['month']:r for r in e['records']}; tm={r['month']:r for r in t['records']}; months=sorted(em); candidates=[p for p,f in e['records'][-1]['features'].items() if f.get('model_candidate')]; snaps=[]
 for asof in months:
  if asof<'2013-12':continue
  snap={'as_of_month':asof,'uses_only_information_available_by_as_of':True,'features':{}}
  for p in candidates:
   rows=[(m,em[m]['features'][p].get('expanding_rank_pct') if em[m]['features'][p].get('expanding_rank_pct') is not None else (1.0 if em[m]['features'][p].get('raw_value') is True else 0.0),em[m]['features'][p].get('expanding_rank_pct') is not None,isinstance(em[m]['features'][p].get('raw_value'),bool)) for m in months if m<=asof and em[m]['features'].get(p,{}).get('available') and em[m]['features'][p].get('normalization_history_ready')]
   item={'feature_family':em[asof]['features'].get(p,{}).get('feature_family'),'ready_sample_count':len(rows),'diagnostic_history_ready':len(rows)>=36,'sample_diagnostics':{},'boolean_diagnostics':{}}
   for h in H:
    pairs=[(v,tm[m]['benchmarks']['broad_proxy'][f'forward_{h}m']) for m,v,has_rank,is_bool in rows if has_rank and tm.get(m) and tm[m]['benchmarks']['broad_proxy'][f'forward_{h}m'].get('target_available') and tm[m]['benchmarks']['broad_proxy'][f'forward_{h}m']['target_month']<=asof]
    item['sample_diagnostics'][f'forward_{h}m']={'sample_count':len(pairs),'spearman_rho':rho([x for x,_ in pairs],[y['forward_return_pct'] for _,y in pairs]),'max_drawdown_spearman_rho':rho([x for x,_ in pairs],[y['max_drawdown_pct'] for _,y in pairs]),'target_cutoff_rule':'target_month <= as_of_month'}
    for state in (True,False):
     vals=[tm[m]['benchmarks']['broad_proxy'][f'forward_{h}m']['forward_return_pct'] for m,v,has_rank,is_bool in rows if is_bool and bool(v)==state and tm.get(m) and tm[m]['benchmarks']['broad_proxy'][f'forward_{h}m'].get('target_available') and tm[m]['benchmarks']['broad_proxy'][f'forward_{h}m']['target_month']<=asof]
     item['boolean_diagnostics'][f'forward_{h}m']=item['boolean_diagnostics'].get(f'forward_{h}m',{}); item['boolean_diagnostics'][f'forward_{h}m']['true' if state else 'false']={'sample_count':len(vals),'median':round(sorted(vals)[len(vals)//2],6) if vals else None}
   snap['features'][p]=item
  snaps.append(snap)
 return {'schema':'cycle_engine_walk_forward_diagnostics_v1','evaluation_only':True,'uses_future_information':True,'description':'As-of walk-forward descriptive diagnostics; not a model input or signal.','as_of_start':'2013-12','as_of_end':months[-1],'horizons_months':list(H),'primary_benchmark':'broad_proxy','snapshots':snaps,'source_evidence_sha':sha(e),'source_evaluation_sha':sha(t),'source_diagnostics_sha':sha(json.loads(D.read_text()))}
def audit(d):
 e,t=load(); expected=build(e,t); errors={'source_mutation_count':0,'as_of_future_leakage_count':0,'target_cutoff_violation_count':0,'sample_alignment_violation_count':0,'candidate_scope_violation_count':0}
 if any(d.get(k)!=expected.get(k) for k in ('source_evidence_sha','source_evaluation_sha','source_diagnostics_sha')):errors['source_mutation_count']+=1
 formal={p for p,f in e['records'][-1]['features'].items() if f.get('model_candidate')}
 for s in d.get('snapshots',[]):
  if s.get('uses_only_information_available_by_as_of') is not True:errors['as_of_future_leakage_count']+=1
  for p,f in s.get('features',{}).items():
   if p not in formal:errors['candidate_scope_violation_count']+=1
   for x in f.get('sample_diagnostics',{}).values():
    if x.get('target_cutoff_rule')!='target_month <= as_of_month':errors['target_cutoff_violation_count']+=1
 if d.get('evaluation_only') is not True or d.get('uses_future_information') is not True:errors['as_of_future_leakage_count']+=1
 return {'schema':'cycle_engine_walk_forward_diagnostics_audit_v1','snapshot_count':len(d.get('snapshots',[])),'candidate_feature_count':len(formal),'source_evidence_hash_match':d.get('source_evidence_sha')==sha(e),'source_evaluation_hash_match':d.get('source_evaluation_sha')==sha(t),'source_diagnostics_hash_match':d.get('source_diagnostics_sha')==sha(json.loads(D.read_text())),**errors,'passed':sum(errors.values())==0 and d.get('evaluation_only') is True}
def generate():
 e,t=load(); d=build(e,t); a=audit(d); OUT.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n'); AUD.write_text(json.dumps(a,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(a,ensure_ascii=False,indent=2))
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--generate',action='store_true');ap.parse_args();generate()
