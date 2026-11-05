"""The 15 delivered AI slots have a fixed, read-only publication contract."""
import json
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bi_agent.cockpit.cards import CONTRACT
from bi_agent.cockpit.dashboard_source import RELEASE
from bi_agent.cockpit.publications import view_scope
from bi_agent.cockpit.refresh import (delivered_component_requests, period_target_scope,
                                      preheat_target_scope)
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
    'combined': {'analysisConfig': {'indicators': [{'identifierCode': 'YWLN_M0035'}]}},
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


def _save_stage(store, cfg, stage, page, findings=None, period='2025-10'):
    context = dict(id=1, page=page, stage=stage, engine='main', source='service',
                   dataSource='ap', dataIdentity=cfg.identity(), dataFingerprint='fp-' + stage,
                   chartSnapshotId=RELEASE, chartQueries=[json.dumps(QUERIES[stage], sort_keys=True)],
                   period=period, department='全部产品部', filters={}, repositoryId='',
                   clarifications={}, baselineAnalysisId='')
    findings = findings or []
    evidence_ids = [str(value) for finding in findings for value in finding.get('evidenceIds', [])]
    evidence = dict(facts=[dict(id=value, label='测试风险', value=1, unit='', definition='测试证据')
                           for value in dict.fromkeys(evidence_ids)],
                    records=[], evidence=[], limitations=[])
    item = store.create_analysis('slot-' + stage, context)
    store.update_analysis(item['id'], status='limited', result=dict(
        summary=stage + ' 已发布卡片', causes=[], recommendations=[], limitations=[],
        findings=findings, cardContract=CONTRACT), evidence=evidence)
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


def _period_scope(period, grain='MONTH'):
    return json.dumps([
        ['setButtonGrainSelection:grain:{}', json.dumps(grain)],
        ['setFilterConditions:filter:{}', json.dumps([{'label': '时间', 'value': period}],
                                                      ensure_ascii=False)],
    ], ensure_ascii=False)


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
                        ('shipment', 'analysis'), ('combined', 'analysis')):
        _save_stage(store, cfg, stage, page)

    value = _client(tmp_path, monkeypatch, cfg).get(
        '/api/cockpit/ai-publications?id=1&uiScope=default').json()
    assert value['expectedCount'] == value['targetCount'] == 15
    assert value['readyCount'] == value['publishedCount'] == 15
    assert value['renderableCount'] == 15
    assert value['completeCount'] == 0
    assert value['limitedCount'] == 15
    assert value['incompleteCount'] == 15
    assert value['missingCount'] == value['updatingCount'] == 0
    assert set(value['slots']) == {item['id'] for item in slots()}
    assert value['scopeKey'] == 'default'
    assert value['registryVersion'] == REGISTRY_VERSION
    assert all(item['status'] == 'ready' and item['payload']['result']['cardContract'] == CONTRACT
               for item in value['slots'].values())
    from bi_agent.cockpit.delivery import SLOT_SPECS
    for slot_id, item in value['slots'].items():
        spec = SLOT_SPECS[slot_id]
        assert item['contentStatus'] == 'limited' and item['contentComplete'] is False
        assert 'ANALYSIS_LIMITED' in item['contentGaps']
        assert ('CAUSES_EMPTY' in item['contentGaps']) is spec.get('causes_required', True)
        assert ('ACTION_EMPTY' in item['contentGaps']) is spec.get('actions_required', False)
    assert all(item['lastSuccessfulPublication'] == item['payload'] and item['lastSuccessfulAt'] > 0
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


def test_custom_scope_exposes_default_cards_only_as_marked_fallback(tmp_path, monkeypatch):
    cfg = Config()
    store = Store(tmp_path / 'dataset' / 'cockpit' / 'history.sqlite3')
    for stage, page in (('bid', 'operations'), ('quotation', 'operations'),
                        ('order', 'operations'), ('opportunity', 'analysis'),
                        ('shipment', 'analysis'), ('combined', 'analysis')):
        _save_stage(store, cfg, stage, page)
    value = _client(tmp_path, monkeypatch, cfg).get(
        '/api/cockpit/ai-publications?id=1&uiScope=month%3D2026-01').json()
    assert value['readyCount'] == 15
    assert value['missingCount'] == 0
    assert value['requestedScope'] == 'month=2026-01'
    assert value['scopeMatch'] is False
    assert value['displayScope'] == 'default'
    assert all(item['scopeMatch'] is False and item['displayScope'] == 'default'
               and item['status'] == 'ready' for item in value['slots'].values())
    assert all('已发布卡片' in item['payload']['result']['summary']
               for item in value['slots'].values())
    assert all(item['payload']['result']['deliveryContract'] == 'cockpit-delivery-v2'
               for item in value['slots'].values())


def test_month_and_empty_date_scopes_reuse_preheated_default_cards(tmp_path, monkeypatch):
    cfg = Config()
    store = Store(tmp_path / 'dataset' / 'cockpit' / 'history.sqlite3')
    for stage, page in (('bid', 'operations'), ('quotation', 'operations'),
                        ('order', 'operations'), ('opportunity', 'analysis'),
                        ('shipment', 'analysis'), ('combined', 'analysis')):
        _save_stage(store, cfg, stage, page)
    client = _client(tmp_path, monkeypatch, cfg)
    for scope in (
        '[]',
        json.dumps([["setButtonGrainSelection:grain:{}", '"MONTH"']]),
    ):
        value = client.get('/api/cockpit/ai-publications', params={'id': 1, 'uiScope': scope}).json()
        assert value['readyCount'] == 15
        assert value['scopeMatch'] is True
        assert value['displayScope'] == 'default'
        assert all(item['scopeMatch'] is True for item in value['slots'].values())


def test_date_scope_reads_its_exact_period_card_before_the_latest_default(tmp_path, monkeypatch):
    cfg = Config()
    store = Store(tmp_path / 'dataset' / 'cockpit' / 'history.sqlite3')
    sept = _save_stage(store, cfg, 'shipment', 'analysis', period='2025-09')
    october = _save_stage(store, cfg, 'shipment', 'analysis', period='2025-10')
    store.publish_period(1, '2025-09', 'shipment', {}, sept['id'],
                         view_scope(sept['context']))
    store.publish_period(1, '2025-10', 'shipment', {}, october['id'],
                         view_scope(october['context']))

    client = _client(tmp_path, monkeypatch, cfg)
    for period, expected in (('2025-09', sept), ('2025-10', october)):
        value = client.get('/api/cockpit/ai-publications',
                           params={'id': 1, 'uiScope': _period_scope(period)}).json()
        shipment = next(item for item in value['slots'].values() if item['stage'] == 'shipment')
        assert value['requestedPeriod'] == period
        assert value['scopeMatch'] is True and value['displayScope'] == 'period'
        assert shipment['periodMatch'] is True and shipment['scopeMatch'] is True
        assert shipment['payload']['id'] == expected['id']
        status = client.get('/api/cockpit/publications/status',
                            params={'id': 1, 'page': 'analysis',
                                    'uiScope': _period_scope(period)}).json()
        assert status['period'] == period and status['periodMatch'] is True


def test_preheated_years_and_months_survive_restart_and_serve_each_range(tmp_path, monkeypatch):
    cfg = Config()
    store = Store(tmp_path / 'dataset' / 'cockpit' / 'history.sqlite3')
    stage_pages = {'bid': 'operations', 'quotation': 'operations', 'order': 'operations',
                   'opportunity': 'analysis', 'shipment': 'analysis'}
    periods = ('2024', '2025', '2025-09', '2025-10', '2025-11')
    expected = {}
    for period in periods:
        expected[period] = {}
        for stage, page in stage_pages.items():
            item = _save_stage(store, cfg, stage, page, period=period)
            store.publish_period(1, period, stage, {}, item['id'],
                                 view_scope(item['context']))
            expected[period][stage] = item['id']

    # A new router/store instance models a service restart with only SQLite.
    client = _client(tmp_path, monkeypatch, cfg)
    for period in periods:
        scope = _period_scope(period, 'YEAR' if len(period) == 4 else 'MONTH')
        value = client.get('/api/cockpit/ai-publications',
                           params={'id': 1, 'uiScope': scope}).json()
        assert value['requestedPeriod'] == period
        assert value['scopeMatch'] is True and value['displayScope'] == 'period'
        for stage, analysis_id in expected[period].items():
            slot = next(item for item in value['slots'].values() if item['stage'] == stage)
            assert slot['periodMatch'] is True
            assert slot['payload']['id'] == analysis_id


def test_non_default_grain_view_and_business_filters_do_not_reuse_default_scope(tmp_path, monkeypatch):
    cfg = Config()
    store = Store(tmp_path / 'dataset' / 'cockpit' / 'history.sqlite3')
    for stage, page in (('bid', 'operations'), ('quotation', 'operations'),
                        ('order', 'operations'), ('opportunity', 'analysis'),
                        ('shipment', 'analysis'), ('combined', 'analysis')):
        _save_stage(store, cfg, stage, page)
    client = _client(tmp_path, monkeypatch, cfg)
    for scope in (
        json.dumps([["setButtonGrainSelection:grain:{}", '"YEAR"']]),
        json.dumps([["setButtonGrainSelection:other:{}", '"MONTH"']]),
        json.dumps([["setContainerActiveNode:node:{}", '{"nodeId":"quote-node"}']]),
        json.dumps([["setFilterConditions:filter:{}", '{"label":"时间","value":"2026"}']]),
    ):
        value = client.get('/api/cockpit/ai-publications', params={'id': 1, 'uiScope': scope}).json()
        assert value['readyCount'] == 15
        assert value['scopeMatch'] is False
        assert all(item['scopeMatch'] is False for item in value['slots'].values())


def test_ai_publications_exposes_deduplicated_metric_risk_counts(tmp_path, monkeypatch):
    cfg = Config()
    store = Store(tmp_path / 'dataset' / 'cockpit' / 'history.sqlite3')
    findings = {
        'opportunity': [dict(id='sales-risk', kind='risk_fact', title='销售额低于目标',
                             description='测试风险事实', metricCodes=['SALES_GAP'],
                             evidenceIds=['sales-evidence'], riskDomain='sales')],
        'shipment': [dict(id='shipment-risk', kind='risk_fact', title='出货量低于目标',
                          description='测试风险事实', metricCodes=['SHIPMENT_GAP'],
                          evidenceIds=['shipment-evidence'], riskDomain='shipment')],
    }
    for stage, page in (('bid', 'operations'), ('quotation', 'operations'),
                        ('order', 'operations'), ('opportunity', 'analysis'),
                        ('shipment', 'analysis'), ('combined', 'analysis')):
        _save_stage(store, cfg, stage, page, findings.get(stage))

    value = _client(tmp_path, monkeypatch, cfg).get(
        '/api/cockpit/ai-publications?id=1&uiScope=default').json()
    assert value['riskCounts']['sales'] == dict(
        value['riskCounts']['sales'], count=1, known=True, scopeMatch=True)
    assert value['riskCounts']['shipment'] == dict(
        value['riskCounts']['shipment'], count=1, known=True, scopeMatch=True)
    assert value['slots']['opportunity-risk']['riskFindingCount'] == 1
    assert value['slots']['shipment-risk-summary']['riskFindingCount'] == 1


def test_default_scope_reads_default_period_before_newest_history(tmp_path, monkeypatch):
    monkeypatch.setattr('bi_agent.cockpit.periods.default_period', lambda: '2025-10')
    cfg = Config()
    store = Store(tmp_path / 'dataset' / 'cockpit' / 'history.sqlite3')
    october = _save_stage(store, cfg, 'shipment', 'analysis', period='2025-10')
    store.publish_period(1, '2025-10', 'shipment', {}, october['id'],
                         view_scope(october['context']))
    # Publish history afterwards so the newest default view is September.
    september = _save_stage(store, cfg, 'shipment', 'analysis', period='2025-09')
    store.publish_period(1, '2025-09', 'shipment', {}, september['id'],
                         view_scope(september['context']))
    client = _client(tmp_path, monkeypatch, cfg)

    def default_shipment():
        value = client.get('/api/cockpit/ai-publications',
                           params={'id': 1, 'uiScope': 'default'}).json()
        slot = next(item for item in value['slots'].values() if item['stage'] == 'shipment')
        return value, slot

    value, slot = default_shipment()
    assert value['requestedPeriod'] == '2025-10'
    assert slot['payload']['id'] == october['id']
    assert slot['periodMatch'] is True
    assert slot['scopeMatch'] is True

    august = _save_stage(store, cfg, 'shipment', 'analysis', period='2025-08')
    store.publish_period(1, '2025-08', 'shipment', {}, august['id'],
                         view_scope(august['context']))
    _value, slot = default_shipment()
    assert slot['payload']['id'] == october['id']
    # A new router/store instance models a restart: the default entry still
    # resolves from the period index rather than the newest history view.
    restarted = _client(tmp_path, monkeypatch, cfg).get(
        '/api/cockpit/ai-publications?id=1&uiScope=default').json()
    restarted_shipment = next(item for item in restarted['slots'].values()
                              if item['stage'] == 'shipment')
    assert restarted_shipment['payload']['id'] == october['id']
    assert restarted_shipment['scopeMatch'] is True


def test_default_scope_marks_another_month_as_unmatched_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr('bi_agent.cockpit.periods.default_period', lambda: '2025-10')
    cfg = Config()
    store = Store(tmp_path / 'dataset' / 'cockpit' / 'history.sqlite3')
    september = _save_stage(store, cfg, 'shipment', 'analysis', period='2025-09')
    store.publish_period(1, '2025-09', 'shipment', {}, september['id'],
                         view_scope(september['context']))

    value = _client(tmp_path, monkeypatch, cfg).get(
        '/api/cockpit/ai-publications?id=1&uiScope=default').json()
    slot = next(item for item in value['slots'].values() if item['stage'] == 'shipment')
    assert value['requestedPeriod'] == '2025-10'
    assert value['scopeMatch'] is False and value['displayScope'] == 'default'
    assert slot['payload']['id'] == september['id']
    assert slot['scopeMatch'] is False and slot['periodMatch'] is False
    assert slot['displayScope'] == 'default'


def test_default_cards_and_startup_prefer_the_delivered_period(tmp_path, monkeypatch):
    monkeypatch.setattr('bi_agent.cockpit.periods.default_period', lambda: '2025-10')
    cfg = Config()
    store = Store(tmp_path / 'dataset' / 'cockpit' / 'history.sqlite3')
    october = _save_stage(store, cfg, 'shipment', 'analysis', period='2025-10')
    store.publish_period(1, '2025-10', 'shipment', {}, october['id'],
                         view_scope(october['context']))
    september = _save_stage(store, cfg, 'shipment', 'analysis', period='2025-09')
    store.publish_period(1, '2025-09', 'shipment', {}, september['id'],
                         view_scope(september['context']))
    client = _client(tmp_path, monkeypatch, cfg)

    cards = client.get('/api/cockpit/publications/cards',
                       params={'id': 1, 'page': 'analysis'}).json()
    assert cards['items']['shipment']['id'] == october['id']
    started = client.get('/api/cockpit/startup',
                         params={'id': 1, 'page': 'analysis'}).json()
    assert started['cardsByPage']['analysis']['shipment']['id'] == october['id']
    assert started['cards']['shipment']['id'] == october['id']


def test_exact_period_status_ignores_current_month_and_generic_preheat(tmp_path, monkeypatch):
    monkeypatch.setattr('bi_agent.cockpit.periods.default_period', lambda: '2025-10')
    cfg = Config()
    store = Store(tmp_path / 'dataset' / 'cockpit' / 'history.sqlite3')
    september = _save_stage(store, cfg, 'shipment', 'analysis', period='2025-09')
    store.publish_period(1, '2025-09', 'shipment', {}, september['id'],
                         view_scope(september['context']))
    lease = time.time() + 120
    store.set_refresh_state(
        period_target_scope(1, 'analysis', 'shipment', '2026-11'),
        'running', lease_until=lease)
    store.set_refresh_state(
        preheat_target_scope(1, 'analysis', 'shipment'),
        'running', lease_until=lease)

    client = _client(tmp_path, monkeypatch, cfg)
    value = client.get('/api/cockpit/ai-publications',
                       params={'id': 1, 'uiScope': _period_scope('2025-09')}).json()
    shipment = next(item for item in value['slots'].values() if item['stage'] == 'shipment')
    assert shipment['periodMatch'] is True
    assert shipment['payload']['id'] == september['id']
    assert shipment['update']['active'] is False
    assert shipment['refreshStatus'] not in {'running', 'checking', 'queued', 'waiting'}

    status = client.get('/api/cockpit/publications/status',
                        params={'id': 1, 'page': 'analysis',
                                'uiScope': _period_scope('2025-09')}).json()
    assert status['period'] == '2025-09' and status['periodMatch'] is True
    assert status['update']['status'] not in {'running', 'checking', 'queued', 'waiting'}


def test_default_status_uses_default_period_and_keeps_history_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr('bi_agent.cockpit.periods.default_period', lambda: '2025-10')
    cfg = Config()
    store = Store(tmp_path / 'dataset' / 'cockpit' / 'history.sqlite3')
    october = _save_stage(store, cfg, 'shipment', 'analysis', period='2025-10')
    store.publish_period(1, '2025-10', 'shipment', {}, october['id'],
                         view_scope(october['context']))
    september = _save_stage(store, cfg, 'shipment', 'analysis', period='2025-09')
    store.publish_period(1, '2025-09', 'shipment', {}, september['id'],
                         view_scope(september['context']))
    store.set_refresh_state(period_target_scope(1, 'analysis', 'shipment', '2025-10'),
                            'running', lease_until=time.time() + 120)
    store.set_refresh_state(period_target_scope(1, 'analysis', 'shipment', '2025-09'),
                            'frozen')
    client = _client(tmp_path, monkeypatch, cfg)

    default = client.get('/api/cockpit/publications/status',
                         params={'id': 1, 'page': 'analysis', 'uiScope': 'default'}).json()
    assert default['period'] == '2025-10' and default['periodMatch'] is True
    assert default['update']['status'] == 'running'

    history = client.get('/api/cockpit/publications/status',
                         params={'id': 1, 'page': 'analysis',
                                 'uiScope': _period_scope('2025-09')}).json()
    assert history['period'] == '2025-09' and history['periodMatch'] is True
    assert history['update']['status'] == 'frozen'
