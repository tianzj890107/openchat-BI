"""Offline cockpit delivery eval; no service, credentials, SQL or model calls."""
import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from bi_agent.cockpit.delivery import (
    classify_cause, draftable_actions, normalize_delivery_contract, project_card,
    recommendation_empty_state, sanitize_summary, validate_reasoning,
)
from bi_agent.cockpit.dashboard_source import filter_stage_selected

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'dataset/evals/cockpit'


def evaluate(case):
    value = deepcopy(case['input']); expected = case['expected']; op = case['operation']
    if op == 'reasoning':
        rejected = False
        try:
            validate_reasoning({'summary':value['summary'],'causes':value.get('causes',[]),
                                'recommendations':value.get('recommendations',[])},
                               value.get('evidence',{}),stage=value.get('stage',''))
        except ValueError:
            rejected = True
        return {'reject': rejected}, rejected == expected['reject']
    if op == 'classify':
        result = classify_cause(value)
        return {'kind':result}, result == expected['kind']
    if op == 'summary':
        result = sanitize_summary(value['text'], {})
        return {'text':result}, all(x in result for x in expected['contains']) and not any(x in result for x in expected['absent'])
    if op == 'scope':
        query = {'analysisConfig': {'indicators':[{'identifierCode':code} for code in value['codes']]}}
        kept,_ = filter_stage_selected({'q':{'request':query}}, value['stage'])
        return {'keep':bool(kept)}, bool(kept) == expected['keep']
    if op == 'projection':
        cause = {'id':'c1','title':'缺口集中于团队','description':'汇总切片，不证明因果',
                 'status':'hypothesis','evidenceIds':['e1']}
        action = {'id':'a1','causeIds':['c1'],'action':'核对订单清单','ownerRole':'业务负责人',
                  'deadlineDays':5,'acceptance':'形成核查清单'}
        item = {'id':'fixture','status':'limited','context':{'stage':'shipment'},
                'result':{'summary':'当前存在缺口，需要核实。','causes':[cause],'recommendations':[action],
                          'limitations':[],'cardContract':'cockpit-cards-v1'},
                'evidence':{'facts':[],'records':[],'evidence':[{'id':'e1'}],'limitations':[]}}
        if 'result' in value:
            item['result'] = deepcopy(value['result'])
        if 'evidence' in value:
            item['evidence'] = deepcopy(value['evidence'])
        projected = project_card(item,value['slot'])
        r = projected['result']; ids = {c['id'] for c in r.get('causes',[])}
        checks = {'no_dangling': all(set(a.get('causeIds',[])) <= ids for a in r.get('recommendations',[])),
                  'contract':r.get('deliveryContract'),'summary_nonempty':bool(r.get('summary')),
                  'no_verified':not any(c.get('status')=='supported' for c in r.get('causes',[]))}
        if 'actionTypes' in expected:
            checks['actionTypes'] = {str(a.get('id')):a.get('actionType') for a in r.get('recommendations',[])}
        return checks, checks == expected
    if op == 'draft':
        result = value.get('result') or {}
        evidence = value.get('evidence') or {}
        normalized = normalize_delivery_contract(result, evidence)
        actual = {'emptyState':recommendation_empty_state(normalized.get('causes'),normalized.get('recommendations'))}
        try:
            selected, _ = draftable_actions(normalized, evidence, value.get('recommendationIds'))
            actual.update(draftable=bool(selected), ids=[str(item.get('id')) for item in selected],
                          actionTypes=[item.get('actionType') for item in selected])
        except ValueError as exc:
            actual.update(draftable=False, ids=[], error=str(exc))
        checks = {}
        for key in ('draftable','ids','actionTypes','emptyState'):
            if key in expected:
                checks[key] = actual.get(key)
        if 'errorContains' in expected:
            needle = expected['errorContains']
            checks['errorContains'] = needle if needle in str(actual.get('error') or '') else ''
        return actual, checks == expected
    raise ValueError('Unknown operation: '+op)


def run(cases):
    results=[]
    for case in cases:
        try:
            actual, passed = evaluate(case)
            results.append({'id':case['id'],'area':case['area'],'priority':case['priority'],
                            'passed':passed,'expected':case['expected'],'actual':actual})
        except Exception as exc:
            results.append({'id':case['id'],'area':case['area'],'priority':case['priority'],
                            'passed':False,'error':str(exc),'harnessError':True})
    return {'total':len(results),'passed':sum(r['passed'] for r in results),
            'failed':sum(not r['passed'] for r in results),'results':results}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--baseline',type=Path,help='Explicit reviewed failure budget; plain runs are strict')
    args=parser.parse_args()
    raw=(DATA/'cases.json').read_bytes();cases=json.loads(raw)
    manifest=json.loads((DATA/'manifest.json').read_text())
    if hashlib.sha256(raw).hexdigest()!=manifest['casesSha256']:
        raise SystemExit('Case integrity mismatch')
    if len({c['id'] for c in cases})!=len(cases):raise SystemExit('Duplicate case IDs')
    report=run(cases);failures={r['id'] for r in report['results'] if not r['passed']}
    report['casesSha256']=manifest['casesSha256']
    print(json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=False))
    for result in report['results']:
        if not result['passed']:print(json.dumps(result,ensure_ascii=False))
    if args.output:args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    if args.baseline:
        baseline=json.loads(args.baseline.read_text())
        if baseline['casesSha256']!=manifest['casesSha256']:raise SystemExit('Baseline case hash mismatch')
        budget=set(baseline['knownFailures'])
        if any(r.get('harnessError') for r in report['results']):return 1
        return int(bool(failures-budget))
    return int(bool(failures))

if __name__=='__main__':raise SystemExit(main())
