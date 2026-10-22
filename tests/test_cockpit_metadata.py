"""Delivered metadata, native ProUI runtime, and analysis evidence must agree."""
import hashlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from bi_agent.cockpit.metadata import build_bundle, ROOT, PAGE_IDS, OPS_NODES, RISK_NODES
from bi_agent.cockpit.prototype import PrototypeSource
from bi_agent.cockpit.router import build_cockpit_router
from bi_agent.cockpit.runtime import METADATA, PAGE_TEMPLATES, RELEASE, release_payload, runtime_payload


def test_compilation_preserves_upstream_and_all_renderable_data_is_explicit():
    original=(ROOT/'template-registry.json').read_bytes()
    b=build_bundle()
    assert (ROOT/'template-registry.json').read_bytes()==original
    assert set(b['pages'])=={'overview','operations','analysis'}
    assert len(b['bindings'])==86
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
    assert len(b['insights'])==12
    assert {i['id'] for i in b['insights']} >= {'bid-status-note','quote-summary','shipment-risk-summary','shipment-task-order'}
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
    assert stored['source']['dashboardId']=='iba-demo-1021'
    assert stored['source']['version']=='37975c7'
    assert stored['source']['templateCount']==13
    assert stored['source']['totalComponents']==122
    assert set(stored['pages'])=={'overview','operations','analysis'}
    assert stored['counts']['overview']=={
        'total':10,'types':{'progress':5,'template':1,'button-group':1,'title':1,'group':1,'process-arc':1},'withData':7,
    }
    assert stored['counts']['operations']['total']==38
    assert stored['counts']['operations']['withData']==28
    assert stored['counts']['analysis']=={
        'total':10,'types':{'progress':5,'mini-cpgraph':1,'template':1,'group':1,'title':1,'button-group':1},'withData':5,
    }
    assert len(stored['templates'])==13
    assert {gap['code'] for gap in stored['gaps']} >= {'CHILD_DEFINITION_MISSING','AP_SNAPSHOT_BASIS'}
    prohibited={'cockpit-gap','cockpit-risk-list'}
    for spec in list(stored['pages'].values()) + list(stored['templates'].values()):
        for component in spec['components']:
            assert component['type'] not in prohibited
    assert {page: len(value['insights']) for page, value in stored['pages'].items()}=={
        'overview': 0, 'operations': 4, 'analysis': 8,
    }
    assert {slot['id'] for slot in stored['pages']['analysis']['insights']}=={
        'sales-shipment-issues', 'opportunity-risk', 'opportunity-coverage-note',
        'order-risk-summary', 'shipment-risk-summary',
        'shipment-overdue-note', 'shipment-cause-breakdown', 'shipment-task-order',
    }
    assert all('segments' in slot['embedPath'] for value in stored['pages'].values() for slot in value['insights'])

    source=json.loads((RELEASE/'source.json').read_text())
    snapshot=RELEASE/source['snapshot']['file']
    raw=snapshot.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==source['snapshot']['sha256']
    assert len(raw)==source['snapshot']['bytes']
    captured=json.loads(raw)
    assert len(captured['analysis'])==source['snapshot']['analysisRequests']==39
    assert len(captured['batch'])==source['snapshot']['batchRequests']==3
    assert len(captured['requests'])==source['snapshot']['helmetRequests']==4
    assert source['snapshot']['filterVariants']==4
    filter_rows={tuple(key['commonConfig']['filters']['value']) for key in map(json.loads,captured['analysis']) if (key.get('commonConfig') or {}).get('filters')}
    assert filter_rows=={('2025-01-01','2025-12-31'),('2026-01-01','2026-12-31')}
    for key,value in captured['analysis'].items():
        assert json.loads(key)
        if value.get('success'):
            assert 'result' in value['data']
        else:
            assert 'data' not in value

    cockpit=RELEASE.parents[1]
    js=(cockpit/'cockpit.js').read_text()
    html=(cockpit/'index.html').read_text()
    assert '__cockpitQueryDebug' not in js
    assert 'debug' not in html
    assert '@@COCKPIT_VERSION@@' in html
    assert 'pdt-release-2109836674373566465' in js


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


def test_runtime_components_preserve_templates_with_analysis_graph_override():
    payload=runtime_payload()
    root=json.loads((METADATA/'components.json').read_text())
    assert payload['dashboard']['components']==root
    assert [(c['id'],c['type']) for c in payload['dashboard']['components']]==[
        ('composite-filter-hzjk9t5q','composite-filter'),
        ('tab-container-zm9eyxne','tab-container'),
    ]

    tabs=next(c for c in root if c['type']=='tab-container')['baseConfig']['tabs']
    assert [t['id'] for t in tabs]==list(payload['pages'][page]['tabId'] for page in ('overview','operations','analysis'))
    assert [t['templateId'] for t in tabs]==list(PAGE_TEMPLATES.values())

    for page,tid in PAGE_TEMPLATES.items():
        files=json.loads((METADATA/'template-registry.json').read_text())[tid]
        expected=json.loads(json.dumps(files['components']))
        if page=='analysis':
            graph=next(c for c in expected if c['id']=='mini-cpgraph-93j6k86p')
            graph['title']='销售额口径 · 三节点头盔图（商机获取 → 订单接收 → 发货）'
            graph['graphConfig']['graphTemplateSwitchRules']=[
                rule for rule in graph['graphConfig']['graphTemplateSwitchRules']
                if rule['nodeId']!='2109840573985767425'
            ]
        assert payload['pages'][page]['components']==expected
        assert payload['templates'][tid]['components']==expected
        assert payload['pages'][page]['insights']==release_payload()['pages'][page]['insights']
    source_registry=json.loads((METADATA/'template-registry.json').read_text())
    source_graph=next(c for c in source_registry[PAGE_TEMPLATES['analysis']]['components']
                      if c['id']=='mini-cpgraph-93j6k86p')
    assert source_graph['title']=='销售额口径 · 四节点头盔图（商机获取 → 投标 → 订单接收 → 发货）'
