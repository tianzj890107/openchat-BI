"""The 15 delivered AI slots have a fixed, read-only publication contract."""
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bi_agent.cockpit.cards import CONTRACT
from bi_agent.cockpit.dashboard_source import RELEASE
from bi_agent.cockpit.publications import view_scope
from bi_agent.cockpit.refresh import delivered_component_requests
from bi_agent.cockpit.router import build_cockpit_router
from bi_agent.cockpit.store import Store
from bi_agent.cockpit.targets import (REGISTRY_VERSION, maintenance_targets,
                                      slot_registry, slots)


class Config:
    base_url = 'http://ap.example/api/gateway2'
    batch_mode = 'individual'
    receipt_ttl = 3600

    def headers(self):
        return {'X-App-Id': 'slot-publication-test'}

    def identity(self):
        return 'source-slots'


QUERIES = {
    'bid': {'analysisConfig': {'indicators': [{'identifierCode': 'YWLN_M0034'}]},
            'commonConfig': {'pagination': {'pageNum': 1, 'pageSize': 20}}},
    'quotation': {'analysisConfig': {'indicators': [{'identifierCode': 'YWLN_M0031'}]},
                  'commonConfig': {'pagination': {'pageNum': 1, 'pageSize': 20}}},
    'order': {'analysisConfig': {'indicators': [{'identifierCode': 'YWLN_M0032'}]},
              'commonConfig': {'pagination': {'pageNum': 1, 'pageSize': 20}}},
    'opportunity': {'analysisConfig': {'indicators': [{'identifierCode': 'YWLN_M0023'}]},
                    'commonConfig': {'pagination': {'pageNum': 1, 'pageSize': 20}}},
    'shipment': {'analysisConfig': {'indicators': [{'identifierCode': 'YWLN_M0036'}]},
                 'commonConfig': {'pagination': {'pageNum': 1, 'pageSize': 20}}},
}


def _save_stage(store, cfg, stage, page):
    context = dict(id=1, page=page, stage=stage, engine='main', source='service',
                   dataSource='ap', dataIdentity=cfg.identity(), dataFingerprint='fp-' + stage,
                   chartSnapshotId=RELEASE, chartQueries=[json.dumps(QUERIES[stage], sort_keys=True)],
                   period='2025-10', department='全部产品部', filters={}, repositoryId='',
                   clarifications={}, baselineAnalysisId='')
    item = store.create_analysis('slot-' + stage, context)
    store.update_analysis(item['id'], status='limited', result=dict(
        summary=stage + ' 已发布卡片', causes=[], recommendations=[], limitations=[],
        cardContract=CONTRACT), evidence={'facts': [], 'records': [], 'evidence': []})
    assert store.publish(item['id'])
    assert store.bind_view(view_scope(item['context']), stage, item['scope'])
    return store.get_analysis(item['id'])


def _client(tmp_path, monkeypatch, cfg):
    import bi_agent.cockpit.router as router_module
    monkeypatch.setenv('COCKPIT_DATA_MODE', 'ap')
    monkeypatch.delenv('COCKPIT_REFRESH_ENABLED', raising=False)
    monkeypatch.setattr(router_module, 'get_gateway', lambda: SimpleNamespace(config=cfg))
    app = FastAPI()
    app.include_router(build_cockpit_router(
        lambda: str(tmp_path),
        main_runner=lambda *a: (_ for _ in ()).throw(AssertionError('read path must not call the model')),
        main_context=lambda context: {}))
    return TestClient(app)


def test_registry_is_the_fixed_fifteen_slot_contract():
    registry = slot_registry()
    assert len(registry) == 15
    assert [item['slotId'] for item in registry] == [item['id'] for item in slots()]
    assert all(set(item) == {'slotId', 'page', 'stage', 'outputType', 'contractVersion'}
               for item in registry)
    assert all(item['contractVersion'] == CONTRACT for item in registry)
    assert {item['outputType'] for item in registry} == {'card', 'table'}
    assert REGISTRY_VERSION
    assert len(maintenance_targets()) == 10


def test_preheat_plans_can_be_derived_without_a_previous_browser_visit():
    for stage in ('bid', 'quotation', 'order', 'opportunity', 'shipment'):
        requests = delivered_component_requests(stage)
        assert requests, stage
        assert all('analysisConfig' in request and 'commonConfig' in request
                   for request in requests)


def test_ai_publications_returns_all_slots_without_starting_analysis(tmp_path, monkeypatch):
    cfg = Config()
    store = Store(tmp_path / 'dataset' / 'cockpit' / 'history.sqlite3')
    for stage, page in (('bid', 'operations'), ('quotation', 'operations'),
                        ('order', 'operations'), ('opportunity', 'analysis'),
                        ('shipment', 'analysis')):
        _save_stage(store, cfg, stage, page)

    value = _client(tmp_path, monkeypatch, cfg).get(
        '/api/cockpit/ai-publications?id=1&uiScope=default').json()
    assert value['expectedCount'] == value['targetCount'] == 15
    assert value['readyCount'] == value['publishedCount'] == 15
    assert value['missingCount'] == value['updatingCount'] == 0
    assert set(value['slots']) == {item['id'] for item in slots()}
    assert value['scopeKey'] == 'default'
    assert value['registryVersion'] == REGISTRY_VERSION
    assert all(item['status'] == 'ready' and item['payload']['result']['cardContract'] == CONTRACT
               for item in value['slots'].values())
    assert value['slots']['bid-status-note']['payload']['id'] == store.latest_views(
        1, 'main', 'operations').get('bid')['id']


def test_missing_slots_are_explicit_and_never_empty_completed(tmp_path, monkeypatch):
    value = _client(tmp_path, monkeypatch, Config()).get(
        '/api/cockpit/ai-publications?id=1&uiScope=default').json()
    assert value['expectedCount'] == 15
    assert value['readyCount'] == 0
    assert value['missingCount'] == 15
    assert all(item['status'] == 'missing' and item['payload'] is None
               for item in value['slots'].values())


def test_custom_scope_never_reuses_default_scope_cards(tmp_path, monkeypatch):
    cfg = Config()
    store = Store(tmp_path / 'dataset' / 'cockpit' / 'history.sqlite3')
    for stage, page in (('bid', 'operations'), ('quotation', 'operations'),
                        ('order', 'operations'), ('opportunity', 'analysis'),
                        ('shipment', 'analysis')):
        _save_stage(store, cfg, stage, page)
    value = _client(tmp_path, monkeypatch, cfg).get(
        '/api/cockpit/ai-publications?id=1&uiScope=month%3D2026-01').json()
    assert value['readyCount'] == 0
    assert value['missingCount'] == 15
    assert value['requestedScope'] == 'month=2026-01'
