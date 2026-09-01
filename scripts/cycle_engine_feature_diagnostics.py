"""Descriptive diagnostics joining frozen Evidence to ex-post outcomes.

This module is analysis-only: it never creates a score, ranking, signal, or
allocation recommendation.
"""
from __future__ import annotations
import argparse, hashlib, json, math, re, sys
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'
EVIDENCE=DATA/'cycle_engine_features_v1.json'; EVIDENCE_AUDIT=DATA/'cycle_engine_features_audit_v1.json'
TARGETS=DATA/'cycle_engine_evaluation_targets_v1.json'; TARGET_AUDIT=DATA/'cycle_engine_evaluation_targets_audit_v1.json'
OUT=DATA/'cycle_engine_feature_diagnostics_v1.json'; AUDIT=DATA/'cycle_engine_feature_diagnostics_audit_v1.json'
ERAS={'A':('2010-01','2014-12'),'B':('2015-01','2019-12'),'C':('2020-01','2026-08')}
HORIZONS=(6,12,24); FAMILIES=('valuation_level','relative_valuation','earnings_growth','earnings_quality','macro_confirmation','trend_level','trend_direction','trend_momentum','trend_damage','sentiment_overlay')
FORBIDDEN=('forward_','months_to_','broad_proxy_index','evaluation_target')

def canonical_sha(value:Any)->str:
    return hashlib.sha256((json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()).hexdigest()
def rank(values:list[float])->list[float]:
    out=[]
    for x in values:
        less=sum(v<x for v in values); equal=sum(v==x for v in values)
        out.append(less+(equal+1)/2)
    return out
def spearman(a:list[float],b:list[float])->float|None:
    if len(a)<2: return None
    ra,rb=rank(a),rank(b); ma=sum(ra)/len(ra); mb=sum(rb)/len(rb)
    den=math.sqrt(sum((x-ma)**2 for x in ra)*sum((y-mb)**2 for y in rb))
    return None if den==0 else round(sum((x-ma)*(y-mb) for x,y in zip(ra,rb))/den,6)
def quantile(values:list[float],q:float)->float|None:
    if not values:return None
    s=sorted(values); p=(len(s)-1)*q; lo=int(p); hi=min(lo+1,len(s)-1)
    return round(s[lo]+(s[hi]-s[lo])*(p-lo),6)
def stats(values:list[float])->dict[str,Any]:
    return {'sample_count':len(values),'mean':round(sum(values)/len(values),6) if values else None,'median':quantile(values,.5),'p25':quantile(values,.25),'p75':quantile(values,.75)}
def load():
    e=json.loads(EVIDENCE.read_text(encoding='utf-8')); t=json.loads(TARGETS.read_text(encoding='utf-8'))
    ea=json.loads(EVIDENCE_AUDIT.read_text(encoding='utf-8')); ta=json.loads(TARGET_AUDIT.read_text(encoding='utf-8'))
    if not ea.get('passed') or not ta.get('passed'): raise RuntimeError('source audit gate failed')
    return e,t
def target_value(trow:dict[str,Any],h:int,key:str)->float|None:
    x=trow['benchmarks']['broad_proxy'][f'forward_{h}m'].get(key)
    return float(x) if isinstance(x,(int,float)) else None
def build(evidence:dict[str,Any],targets:dict[str,Any])->dict[str,Any]:
    em={r['month']:r for r in evidence['records']}; tm={r['month']:r for r in targets['records']}; months=sorted(set(em)&set(tm))
    features={}
    for path, sample in evidence['records'][-1]['features'].items():
        if not sample.get('model_candidate'): continue
        family=sample.get('feature_family'); rows=[]
        for m in months:
            f=em[m]['features'].get(path,{}); ready=f.get('normalization_history_ready') is True
            value=f.get('expanding_rank_pct'); is_bool=isinstance(f.get('raw_value'),bool)
            if not (f.get('available') and (value is not None or is_bool) and ready): continue
            rows.append((m,float(value) if value is not None else float(f.get('raw_value')),value is not None,is_bool))
        diag={'path':path,'feature_family':family,'short_history':path=='sentiment.a_fear.fear_score','all_available_sample_count':sum(1 for m in months if em[m]['features'].get(path,{}).get('available')),'ready_sample_count':len(rows),'target_diagnostics':{},'bucket_diagnostics':{},'era_diagnostics':{}}
        for h in (3,6,12,24):
            pairs=[(v,target_value(tm[m],h,'forward_return_pct')) for m,v,has_rank,_ in rows if has_rank and target_value(tm[m],h,'forward_return_pct') is not None]
            diag['target_diagnostics'][f'forward_{h}m_return_pct']={'sample_count':len(pairs),'spearman_rho':spearman([x for x,_ in pairs],[y for _,y in pairs])}
            bool_rows=[(v,target_value(tm[m],h,'forward_return_pct')) for m,v,_,is_bool in rows if is_bool and target_value(tm[m],h,'forward_return_pct') is not None]
            diag['target_diagnostics'][f'forward_{h}m_boolean_groups']={'true':stats([y for x,y in bool_rows if x==1]),'false':stats([y for x,y in bool_rows if x==0]),'true_minus_false_median':(quantile([y for x,y in bool_rows if x==1],.5)-quantile([y for x,y in bool_rows if x==0],.5)) if [y for x,y in bool_rows if x==1] and [y for x,y in bool_rows if x==0] else None}
        for h in HORIZONS:
            pairs=[(v,target_value(tm[m],h,'forward_return_pct')) for m,v,has_rank,_ in rows if has_rank and target_value(tm[m],h,'forward_return_pct') is not None]
            for key in ('forward_return_pct','max_drawdown_pct'):
                vals=[target_value(tm[m],h,key) for m,v,has_rank,_ in rows if has_rank and target_value(tm[m],h,key) is not None]
                diag['target_diagnostics'][f'forward_{h}m_{key}']= {'sample_count':len(vals),'spearman_rho':spearman([v for m,v,has_rank,_ in rows if has_rank and target_value(tm[m],h,key) is not None],vals)}
        for lo,hi in ((0,20),(20,40),(40,60),(60,80),(80,100)):
            members=[(m,v) for m,v,has_rank,_ in rows if has_rank and (v>=lo and v<(hi if hi<100 else 101))]; item={'range':f'{lo}-{hi}','sample_count':len(members)}
            for h in HORIZONS:
                vals=[target_value(tm[m],h,'forward_return_pct') for m,v in members if target_value(tm[m],h,'forward_return_pct') is not None]; item[f'median_forward_{h}m_return']=quantile(vals,.5)
                vals=[target_value(tm[m],h,'max_drawdown_pct') for m,v in members if target_value(tm[m],h,'max_drawdown_pct') is not None]; item[f'median_forward_{h}m_max_drawdown']=quantile(vals,.5)
            diag['bucket_diagnostics'][f'{lo}-{hi}']=item
        med=[diag['bucket_diagnostics'][f'{lo}-{hi}']['median_forward_12m_return'] for lo,hi in ((0,20),(20,40),(40,60),(60,80),(80,100))]; med=[x for x in med if x is not None]
        steps=[med[i+1]-med[i] for i in range(len(med)-1)]
        diag['increasing_step_count']=sum(x>0 for x in steps); diag['decreasing_step_count']=sum(x<0 for x in steps)
        diag['monotonic_step_count']=max(diag['increasing_step_count'],diag['decreasing_step_count'])
        for era,(start,end) in ERAS.items():
            er=[(m,v) for m,v,has_rank,_ in rows if has_rank and start<=m<=end]
            era_diag={'target_diagnostics':{},'bucket_diagnostics':{},'boolean_diagnostics':{}}
            for h in HORIZONS:
                for key in ('forward_return_pct','max_drawdown_pct'):
                    pairs=[(v,target_value(tm[m],h,key)) for m,v in er if target_value(tm[m],h,key) is not None]
                    era_diag['target_diagnostics'][f'forward_{h}m_{key}']={'sample_count':len(pairs),'spearman_rho':spearman([x for x,_ in pairs],[y for _,y in pairs])}
            for lo,hi in ((0,20),(20,40),(40,60),(60,80),(80,100)):
                members=[(m,v) for m,v in er if lo<=v<(hi if hi<100 else 101)]; era_diag['bucket_diagnostics'][f'{lo}-{hi}']={'sample_count':len(members),**{f'median_{h}m_{key}':quantile([target_value(tm[m],h,key) for m,_ in members if target_value(tm[m],h,key) is not None],.5) for h in HORIZONS for key in ('forward_return_pct','max_drawdown_pct')}}
            bool_er=[(m,int(v)) for m,v,_,is_bool in rows if is_bool and start<=m<=end]
            for h in HORIZONS:
                for key in ('forward_return_pct','max_drawdown_pct'):
                    groups={}
                    for state in (1,0):
                        vals=[target_value(tm[m],h,key) for m,v in bool_er if v==state and target_value(tm[m],h,key) is not None]
                        groups['true' if state else 'false']=stats(vals)
                    tmed=groups['true']['median']; fmed=groups['false']['median']
                    groups['true_minus_false_median']=None if tmed is None or fmed is None else round(tmed-fmed,6)
                    era_diag['boolean_diagnostics'][f'forward_{h}m_{key}']=groups
            diag['era_diagnostics'][era]=era_diag
        features[path]=diag
    candidates=sorted(features); redundancy=[]
    for a,b in combinations(candidates,2):
        def value(path,m):
            f=em[m]['features'][path]; return f.get('expanding_rank_pct') if f.get('expanding_rank_pct') is not None else (1.0 if f.get('raw_value') is True else 0.0 if f.get('raw_value') is False else None)
        pairs=[(value(a,m),value(b,m)) for m in months if em[m]['features'].get(a,{}).get('available') and em[m]['features'].get(b,{}).get('available') and em[m]['features'][a].get('normalization_history_ready') and em[m]['features'][b].get('normalization_history_ready') and value(a,m) is not None and value(b,m) is not None]
        rho=spearman([x for x,_ in pairs],[y for _,y in pairs]); redundancy.append({'feature_a':a,'feature_b':b,'family_a':features[a]['feature_family'],'family_b':features[b]['feature_family'],'overlap_count':len(pairs),'spearman_rho':rho,'high_redundancy':rho is not None and abs(rho)>=.8})
    family={}
    for f in FAMILIES:
        fs=[x for x in features.values() if x['feature_family']==f]; rs=[x['spearman_rho'] for x in redundancy if x['family_a']==f and x['family_b']==f and x['spearman_rho'] is not None]
        family[f]={'candidate_count':len(fs),'available_history_range':{x['path']:[x['all_available_sample_count'],x['ready_sample_count']] for x in fs},'median_pairwise_absolute_correlation':quantile([abs(x) for x in rs],.5),'maximum_pairwise_absolute_correlation':max([abs(x) for x in rs],default=None),'high_redundancy_pair_count':sum(abs(x)>=.8 for x in rs)}
    return {'schema':'cycle_engine_feature_diagnostics_v1','source_evidence_sha':canonical_sha(evidence),'source_evaluation_sha':canonical_sha(targets),'feature_diagnostics':features,'family_diagnostics':family,'redundancy_matrix':redundancy,'era_diagnostics':ERAS}
def audit(d:dict[str,Any])->dict[str,Any]:
    e,t=load(); expected=build(e,t); ea=json.loads(EVIDENCE_AUDIT.read_text()); ta=json.loads(TARGET_AUDIT.read_text()); errors={'unauthorized_feature_count':0,'future_target_used_as_feature_count':0,'non_candidate_feature_analyzed_count':0,'sample_alignment_violation_count':0,'readiness_rule_violation_count':0,'bucket_assignment_violation_count':0,'correlation_formula_violation_count':0,'boolean_group_violation_count':0,'redundancy_formula_violation_count':0,'family_diagnostics_violation_count':0,'era_boundary_violation_count':0,'monotonicity_formula_violation_count':0,'source_mutation_count':0}
    if d.get('source_evidence_sha')!=canonical_sha(e) or d.get('source_evaluation_sha')!=canonical_sha(t): errors['source_mutation_count']+=1
    formal={p for p,f in e['records'][-1]['features'].items() if f.get('model_candidate')}; actual_paths=set(d.get('feature_diagnostics',{})); all_paths=set(e['records'][-1]['features'])
    errors['unauthorized_feature_count'] += len(actual_paths-all_paths); errors['non_candidate_feature_analyzed_count'] += len((actual_paths&all_paths)-formal)
    if d.get('redundancy_matrix')!=expected.get('redundancy_matrix'): errors['redundancy_formula_violation_count']+=1
    if d.get('family_diagnostics')!=expected.get('family_diagnostics'): errors['family_diagnostics_violation_count']+=1
    evidence_months={r['month'] for r in e['records']}; target_months={r['month'] for r in t['records']}
    if evidence_months != target_months: errors['sample_alignment_violation_count'] += 1
    if d.get('era_diagnostics') != ERAS: errors['era_boundary_violation_count'] += 1
    for p in actual_paths & formal:
        got=d['feature_diagnostics'][p]; exp=expected['feature_diagnostics'][p]
        if got.get('target_diagnostics')!=exp.get('target_diagnostics') or got.get('era_diagnostics')!=exp.get('era_diagnostics'): errors['correlation_formula_violation_count']+=1
        if got.get('bucket_diagnostics')!=exp.get('bucket_diagnostics'): errors['bucket_assignment_violation_count']+=1
        if got.get('increasing_step_count')!=exp.get('increasing_step_count') or got.get('decreasing_step_count')!=exp.get('decreasing_step_count'): errors['monotonicity_formula_violation_count']+=1
        expected_ready=sum(1 for r in e['records'] if r['features'].get(p,{}).get('available') and r['features'].get(p,{}).get('normalization_history_ready') is True)
        if got.get('ready_sample_count') != expected_ready: errors['readiness_rule_violation_count'] += 1
        if got.get('era_diagnostics',{}).get('A',{}).get('boolean_diagnostics') != exp.get('era_diagnostics',{}).get('A',{}).get('boolean_diagnostics'): errors['boolean_group_violation_count'] += 1
    feature_paths=list(d.get('feature_diagnostics',{}))
    if any(token in path for path in feature_paths for token in FORBIDDEN): errors['future_target_used_as_feature_count']+=1
    source_ok=d.get('source_evidence_sha')==canonical_sha(e) and d.get('source_evaluation_sha')==canonical_sha(t)
    return {'schema':'cycle_engine_feature_diagnostics_audit_v1','feature_count':len(e['records'][-1]['features']),'candidate_feature_count':len(expected['feature_diagnostics']),'source_evidence_hash_match':d.get('source_evidence_sha')==canonical_sha(e),'source_evaluation_hash_match':d.get('source_evaluation_sha')==canonical_sha(t),'evidence_audit_passed':ea.get('passed') is True,'evaluation_audit_passed':ta.get('passed') is True,**errors,'passed':source_ok and ea.get('passed') is True and ta.get('passed') is True and sum(errors.values())==0}
def generate():
    e,t=load(); d=build(e,t); a=audit(d); OUT.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); AUDIT.write_text(json.dumps(a,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); return a
if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--generate',action='store_true'); args=ap.parse_args(); print(json.dumps(generate(),ensure_ascii=False,indent=2)); sys.exit(0)
