"""Delivered metadata, prototype fidelity, and analysis evidence must agree."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from bi_agent.cockpit.metadata import build_bundle, ROOT, PAGE_IDS, OPS_NODES, RISK_NODES
from bi_agent.cockpit.prototype import PrototypeSource
from bi_agent.cockpit.router import build_cockpit_router


def test_compilation_preserves_upstream_and_all_renderable_data_is_explicit():
    original=(ROOT/'template-registry.json').read_bytes()
    b=build_bundle()
    assert (ROOT/'template-registry.json').read_bytes()==original
    assert set(b['pages'])=={'overview','operations','analysis'}
    assert len(b['bindings'])==100
    unavailable=[]
    for tid,t in b['templates'].items():
        ids={c['id'] for c in t['components']}
        for c in t['components']:
            assert set(c.get('children',[]))<=ids
            if c.get('dataConfig',{}).get('sourceType')=='request':
                key=c['cockpitBindingKey']
                assert key in b['datasets']
                if isinstance(b['datasets'][key],dict) and b['datasets'][key].get('error'):unavailable.append(c['id'])
    assert unavailable==[]
    missing=[c for c in b['templates']['2112062888320483329']['components'] if c['type']=='cockpit-gap']
    assert [c['id'] for c in missing]==['share-bar-79fsomq9']


def test_node_templates_and_insight_paths_are_consistent():
    b=build_bundle()
    for page,nodes,container in [('operations',OPS_NODES,'template-rjjcf4v1'),('analysis',RISK_NODES,'template-ryfsat5y')]:
        components=b['templates'][PAGE_IDS[page]]['components']
        c=next(x for x in components if x['type']=='mini-cpgraph')
        assert {n['id'] for n in c['cockpitGraphData']['nodes']}==set(nodes.values())
        assert c['graphConfig']['defaultActiveKey'] in nodes.values()
        rules=c['graphConfig']['graphTemplateSwitchRules']
        assert {r['nodeId'] for r in rules}==set(nodes.values())
        assert all(r['templateId'] in b['templates'] for r in rules)
    assert all(not any(s['kind']=='tab' for s in i['embedPath']['segments']) for i in b['insights'])
    assert len(b['insights'])==3
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
