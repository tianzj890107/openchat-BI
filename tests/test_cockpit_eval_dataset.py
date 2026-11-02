"""Dataset and harness integrity, separate from product correctness/red cases."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from scripts.run_cockpit_eval import DATA, evaluate, run
from bi_agent.cockpit.targets import slot_registry


def test_case_integrity_and_all_delivered_slots():
    raw=(DATA/'cases.json').read_bytes();cases=json.loads(raw)
    import re
    schema=json.loads((DATA/'case.schema.json').read_text())
    for case in cases:
        assert set(case)==set(schema['required'])
        assert re.fullmatch(schema['properties']['id']['pattern'],case['id'])
        assert isinstance(case['input'],dict) and isinstance(case['expected'],dict) and case['expected']
    manifest=json.loads((DATA/'manifest.json').read_text())
    assert hashlib.sha256(raw).hexdigest()==manifest['casesSha256']
    assert len(cases)==manifest['cases']==54
    assert len({c['id'] for c in cases})==len(cases)
    assert {c['input']['slot'] for c in cases if c['operation']=='projection'}=={s['slotId'] for s in slot_registry()}
    assert all(c['rationale'] and c['priority'] in {'P0','P1','P2'} for c in cases)
    assert all(c['operation'] in {'reasoning','classify','summary','scope','projection','draft'} for c in cases)


def test_harness_does_not_mutate_golden_inputs():
    cases=json.loads((DATA/'cases.json').read_text());before=deepcopy(cases)
    report=run(cases)
    assert cases==before
    assert report['total']==report['passed']+report['failed']
    assert not any(r.get('harnessError') for r in report['results'])


def test_wrong_expectations_cannot_silently_pass():
    cases=json.loads((DATA/'cases.json').read_text())
    for op in ('classify','summary','scope','projection','draft'):
        case=deepcopy(next(c for c in cases if c['operation']==op))
        if op=='classify':case['expected']['kind']='IMPOSSIBLE'
        elif op=='summary':case['expected']['contains']=['IMPOSSIBLE']
        elif op=='scope':case['expected']['keep']=not case['expected']['keep']
        elif op=='projection':case['expected']['contract']='IMPOSSIBLE'
        else:case['expected']['ids']=['IMPOSSIBLE']
        assert evaluate(case)[1] is False


def test_invalid_operations_are_harness_errors_not_product_gaps():
    report=run([{'id':'bad','area':'harness','priority':'P0','operation':'invalid','input':{},'expected':{}}])
    assert report['failed']==1
    assert report['results'][0]['harnessError'] is True
