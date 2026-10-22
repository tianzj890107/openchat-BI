"""Delivered metadata, native ProUI runtime, and analysis evidence must agree."""
import hashlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from bi_agent.cockpit.metadata import build_bundle, ROOT, PAGE_IDS, OPS_NODES, RISK_NODES
from bi_agent.cockpit.prototype import PrototypeSource
from bi_agent.cockpit.router import build_cockpit_router
from bi_agent.cockpit.runtime import PAGE_TEMPLATES, RELEASE, release_payload, runtime_payload


def test_compilation_preserves_upstream_and_all_renderable_data_is_explicit():
    original=(ROOT/'template-registry.json').read_bytes()
    b=build_bundle()
    assert (ROOT/'template-registry.json').read_bytes()==original
    assert set(b['pages'])=={'home','overview','operations','analysis'}
    assert len(b['bindings'])==106
    reported={(g.get('templateId'),g.get('componentId')) for g in b['gaps'] if g['code']=='CHILD_DEFINITION_MISSING'}
    unavailable=[]
    for tid,t in b['templates'].items():
        ids={c['id'] for c in t['components']}
        for c in t['components']:
            for child in c.get('children',[]):
                if child not in ids:assert (tid,child) in reported
            if c.get('dataConfig',{}).get('sourceType')=='request':
                key=c['cockpitBindingKey']
                assert key in b['datasets']
                if isinstance(b['datasets'][key],dict) and b['datasets'][key].get('error'):unavailable.append(c['id'])
    assert unavailable==[]
    components=b['templates']['2112062888320483329']['components']
    assert all(c['type'] not in {'cockpit-gap','cockpit-risk-list'} for c in components)
    missing=next(g for g in b['gaps'] if g['code']=='CHILD_DEFINITION_MISSING')
    assert missing['componentId']=='share-bar-79fsomq9'


def test_node_templates_and_insight_paths_are_consistent():
    b=build_bundle()
    for page,nodes,container in [('operations',OPS_NODES,'template-rjjcf4v1'),('analysis',RISK_NODES,'template-ryfsat5y')]:
        components=b['templates'][PAGE_IDS[page]]['components']
        c=next(x for x in components if x['type']=='mini-cpgraph')
        assert {n['id'] for n in c['cockpitGraphData']['nodes']}==set(nodes.values())
        rules=c['graphConfig']['graphTemplateSwitchRules']
        assert {r['nodeId'] for r in rules}==set(nodes.values())
        assert all(r['templateId'] in b['templates'] for r in rules)
    assert all(any(s['kind']=='tab' for s in i['embedPath']['segments']) for i in b['insights'])
    assert len(b['insights'])==17
    assert {i['id'] for i in b['insights']} >= {'focus-risks','scheme-guide-summary','shipment-risk-summary','shipment-task-order'}
    detail=b['datasets']['2112010750949113858/table-nu6hm1ge']
    assert len(detail)==15
    assert detail[0]['f0']=='构网型产品部 · 目标'
    assert detail[0]['f13']=='18.54'


def test_prototype_rows_reconcile_with_the_rendered_shipping_table():
    b=build_bundle();source=PrototypeSource();snapshot=source.snapshot();e=source.evidence(snapshot,'shipment')
    table=next(b['datasets'][c['cockpitBindingKey']] for c in b['templates']['2112064144187375617']['components'] if c['type']=='table')
    assert {r['id'] for r in e['records']}=={r['f0'] for r in table}
    assert sum(r['amount'] for r in e['records'])==pytest.approx(24.3)
    assert sum(c['amount'] for c in e['causes'])==pytest.approx(24.3)
    assert e['records'][0]['id']=='SO-2026-0318'
    assert e['records'][0]['amount']==4.8
    assert e['sourceMode']=='prototype'
    assert len(source.evidence(snapshot,'opportunity')['records'])==10
    assert source.evidence(snapshot,'quotation')['records'][0]['id']=='XM-2026-4206'
    assert source.evidence(snapshot,'bid')['records'][0]['id']=='P01'
    with pytest.raises(ValueError):source.snapshot('2025-09')
    with pytest.raises(ValueError):source.snapshot(department='AIDC产品部')


def test_static_proui_runtime_is_reproducible_and_uses_release_data():
    path=ROOT.parent/'runtime.json'
    stored=json.loads(path.read_text())
    assert stored==runtime_payload()
    assert stored==release_payload()
    assert stored['renderer']=='ProBiDashboard'
    assert stored['mode']=='release'
    assert stored['source']['dashboardId']=='2109836674373566465'
    assert stored['source']['version']=='1.0.0'
    assert stored['source']['templateCount']==15
    assert stored['source']['totalComponents']==139
    assert set(stored['pages'])=={'home','overview','operations','analysis'}
    assert stored['counts']['home']=={
        'total':9,'types':{'group':1,'title':1,'button-group':1,'progress':5,'mini-cpgraph':1},'withData':6,
    }
    assert stored['counts']['overview']=={
        'total':9,'types':{'progress':5,'template':1,'button-group':1,'title':1,'group':1},'withData':6,
    }
    assert stored['counts']['operations']['total']==43
    assert stored['counts']['operations']['withData']==33
    assert stored['counts']['analysis']=={
        'total':10,'types':{'progress':5,'mini-cpgraph':1,'template':1,'group':1,'title':1,'button-group':1},'withData':6,
    }
    assert len(stored['templates'])==15
    assert stored['gaps']==[]
    prohibited={'cockpit-gap','cockpit-risk-list'}
    for spec in list(stored['pages'].values()) + list(stored['templates'].values()):
        for component in spec['components']:
            assert component['type'] not in prohibited
    assert all(page['insights']==[] for page in stored['pages'].values())

    source=json.loads((RELEASE/'source.json').read_text())
    snapshot=RELEASE/source['snapshot']['file']
    raw=snapshot.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==source['snapshot']['sha256']
    assert len(raw)==source['snapshot']['bytes']
    captured=json.loads(raw)
    assert len(captured['analysis'])==source['snapshot']['analysisRequests']==21
    assert len(captured['batch'])==source['snapshot']['batchRequests']==2
    assert len(captured['requests'])==source['snapshot']['helmetRequests']==2

    cockpit=RELEASE.parents[1]
    js=(cockpit/'cockpit.js').read_text()
    html=(cockpit/'index.html').read_text()
    assert '__cockpitQueryDebug' not in js
    assert 'debug' not in html
    assert 'pdt-release-2109836674373566465' in html


def test_metadata_api_and_analysis_source_isolation(tmp_path):
    app=FastAPI();app.include_router(build_cockpit_router(lambda:tmp_path))
    client=TestClient(app)
    assert client.get('/api/cockpit/metadata').json()['sourceMode']=='prototype'
    original=client.get('/api/cockpit/snapshot').json()
    exact=client.get('/api/cockpit/snapshot?source=prototype').json()
    assert original['snapshotId']!=exact['snapshotId']
    assert client.get('/api/cockpit/snapshot?source=prototype&period=2025-09').status_code==422
    e=client.get('/api/cockpit/evidence?source=prototype&stage=shipment').json()
    assert e['snapshotId']==exact['snapshotId']
    assert e['records'][0]['id']=='SO-2026-0318'


def test_runtime_components_are_release_templates_verbatim():
    payload=runtime_payload()
    root=json.loads(json.loads((RELEASE/'dashboard.json').read_text())['data']['configs'])
    assert payload['dashboard']['components']==root['components']
    assert [(c['id'],c['type']) for c in payload['dashboard']['components']]==[
        ('composite-filter-hzjk9t5q','composite-filter'),
        ('tab-container-zm9eyxne','tab-container'),
    ]

    tabs=next(c for c in root['components'] if c['type']=='tab-container')['baseConfig']['tabs']
    assert [t['id'] for t in tabs]==list(payload['pages'][page]['tabId'] for page in ('home','overview','operations','analysis'))
    assert [t['templateId'] for t in tabs]==list(PAGE_TEMPLATES.values())

    for page,tid in PAGE_TEMPLATES.items():
        record=json.loads((RELEASE/'templates'/f'{tid}.json').read_text())
        files=json.loads(record['data']['configs'])
        assert payload['pages'][page]['components']==files['components']
        assert payload['templates'][tid]['components']==files['components']
        assert payload['pages'][page]['insights']==[]
