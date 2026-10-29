"""Server-owned refresh: unchanged evidence never invokes the model."""
import json
import time
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bi_agent.cockpit.cards import CONTRACT
from bi_agent.cockpit.page_cache import PageRequest, build_page, page_fingerprint, page_scope, transport_identity
from bi_agent.cockpit.refresh import RefreshManager, RefreshScheduler, publication_status
from bi_agent.cockpit.router import build_cockpit_router
from bi_agent.cockpit.store import Store


class Config:
    base_url = 'http://ap.example/api/gateway2'
    batch_mode = 'individual'
    receipt_ttl = 3600

    def headers(self):
        return {'X-App-Id': 'refresh-test'}

    def identity(self):
        return 'source-refresh'


def _fixture(tmp_path):
    cfg = Config()
    store = Store(tmp_path / 'history.sqlite3')
    query = {'analysisConfig': {'indicators': [{'identifierCode': 'YWLN_M0036'}]},
             'commonConfig': {'filters': {'logic': 'AND', 'children': []}}}
    helmet = {'flowCode': 'SALES_CALIBER'}
    business = store.save_ap_result(1, 'analysis', query, {'value': 79.16}, cfg.receipt_ttl,
                                    cfg.identity(), transport_identity(cfg))
    graph = store.save_ap_result(1, 'helmet', helmet, {'nodes': []}, cfg.receipt_ttl,
                                 cfg.identity(), transport_identity(cfg))
    records = [business, graph]
    fingerprint = page_fingerprint(records)
    ids = {}
    for stage in ('shipment', 'opportunity'):
        context = dict(id=1, page='analysis', stage=stage, engine='main', dataSource='ap',
                       dataIdentity=cfg.identity(), dataFingerprint=fingerprint,
                       chartQueries=[json.dumps(query, sort_keys=True)])
        item = store.create_analysis('old-' + stage, context)
        store.update_analysis(item['id'], status='limited',
                              result=dict(summary='old card', cardContract=CONTRACT),
                              evidence={'facts': [], 'records': [], 'evidence': []})
        ids[stage] = item['id']
    page = build_page(PageRequest(id=1, page='analysis', uiScope='default',
                                  apReceiptIds=[business['id'], graph['id']], analysisIds=ids),
                      store, cfg, data_source='ap')
    scope = page_scope(cfg, 1, 'analysis', 'default', 'ap')
    assert store.publish_page(scope, page)
    return store, cfg, query, helmet, page


def _router_fixture(tmp_path):
    """Publish the same page into the store path the router resolves."""
    cfg = Config()
    store = Store(tmp_path / 'dataset' / 'cockpit' / 'history.sqlite3')
    query = {'analysisConfig': {'indicators': [{'identifierCode': 'YWLN_M0036'}]},
             'commonConfig': {'filters': {'logic': 'AND', 'children': []}}}
    business = store.save_ap_result(1, 'analysis', query, {'value': 79.16}, cfg.receipt_ttl,
                                    cfg.identity(), transport_identity(cfg))
    helmet = store.save_ap_result(1, 'helmet', {'flowCode': 'SALES_CALIBER'}, {'nodes': []},
                                  cfg.receipt_ttl, cfg.identity(), transport_identity(cfg))
    fingerprint = page_fingerprint([business, helmet])
    ids = {}
    for stage in ('shipment', 'opportunity'):
        item = store.create_analysis('old-' + stage, dict(
            id=1, page='analysis', stage=stage, engine='main', dataSource='ap',
            dataIdentity=cfg.identity(), dataFingerprint=fingerprint,
            chartQueries=[json.dumps(query, sort_keys=True)], period='2025-10',
            department='全部产品部'))
        store.update_analysis(item['id'], status='limited',
                              result=dict(summary='old card', cardContract=CONTRACT),
                              evidence={'facts': [], 'records': [], 'evidence': []})
        ids[stage] = item['id']
    page = build_page(PageRequest(id=1, page='analysis', uiScope='default',
                                  apReceiptIds=[business['id'], helmet['id']], analysisIds=ids),
                      store, cfg, data_source='ap')
    scope = page_scope(cfg, 1, 'analysis', 'default', 'ap')
    assert store.publish_page(scope, page)
    return store, cfg, page


def _analysis_factory(store, calls):
    def start(body, resolved):
        calls.append(body)
        context = {**body, **resolved, 'stageName': body['stage'], 'sourceMode': 'service'}
        item = store.create_analysis('new-' + body['stage'], context)
        store.update_analysis(item['id'], status='limited',
                              result=dict(summary='new card', cardContract=CONTRACT),
                              evidence={'facts': [], 'records': [], 'evidence': []})
        return store.get_analysis(item['id'])
    return start


def test_refresh_reuses_publication_when_evidence_is_unchanged(tmp_path):
    store, cfg, query, helmet, old = _fixture(tmp_path)
    calls = []
    manager = RefreshManager(store, cfg,
        lambda identity, kind, payload: {'value': 79.16} if kind == 'analysis' else {'nodes': []},
        _analysis_factory(store, calls), interval=900, poll=0.01, timeout=5)
    result = manager.refresh(old)
    assert result['status'] == 'published' and result['changed'] is False
    assert calls == []
    current = store.published_page(page_scope(cfg, 1, 'analysis', 'default', 'ap'))
    assert current['dataFingerprint'] == old['dataFingerprint']
    assert set(current['items']) == {'shipment', 'opportunity'}
    state = publication_status(store, page_scope(cfg, 1, 'analysis', 'default', 'ap'), current)
    assert state['update']['status'] == 'published'
    assert state['publicationVersion'] == current['version']


def test_unchanged_refresh_does_not_append_duplicate_snapshots(tmp_path):
    store, cfg, query, helmet, old = _fixture(tmp_path)
    def snapshots():
        with store.db() as db:
            return db.execute('SELECT COUNT(*) FROM page_snapshots').fetchone()[0]
    before = snapshots()
    manager = RefreshManager(store, cfg,
        lambda identity, kind, payload: {'value': 79.16} if kind == 'analysis' else {'nodes': []},
        _analysis_factory(store, []), interval=900, poll=0.01, timeout=5)
    assert manager.refresh(old)['status'] == 'published'
    assert snapshots() == before


def test_refresh_runs_model_only_after_fingerprint_changes(tmp_path):
    store, cfg, query, helmet, old = _fixture(tmp_path)
    calls = []
    manager = RefreshManager(store, cfg,
        lambda identity, kind, payload: {'value': 99.0} if kind == 'analysis' else {'nodes': []},
        _analysis_factory(store, calls), interval=900, poll=0.01, timeout=5)
    result = manager.refresh(old)
    assert result['status'] == 'published' and result['changed'] is True
    assert len(calls) == 2
    current = store.published_page(page_scope(cfg, 1, 'analysis', 'default', 'ap'))
    assert current['dataFingerprint'] != old['dataFingerprint']
    assert all(item['id'] not in {v['id'] for v in old['items'].values()} for item in current['items'].values())


def test_refresh_keeps_last_version_on_ap_failure(tmp_path):
    store, cfg, query, helmet, old = _fixture(tmp_path)
    calls = []
    def fail(identity, kind, payload):
        raise RuntimeError('AP unavailable')
    manager = RefreshManager(store, cfg, fail, _analysis_factory(store, calls),
                             interval=900, poll=0.01, timeout=5)
    result = manager.refresh(old)
    assert result['status'] == 'retry_wait'
    assert calls == []
    current = store.published_page(page_scope(cfg, 1, 'analysis', 'default', 'ap'))
    assert current['version'] == old['version']
    assert store.refresh_state(page_scope(cfg, 1, 'analysis', 'default', 'ap'))['status'] == 'retry_wait'


def _client(tmp_path, monkeypatch, cfg, main_runner=None):
    import bi_agent.cockpit.router as router_module
    monkeypatch.setenv('COCKPIT_DATA_MODE', 'ap')
    monkeypatch.delenv('COCKPIT_REFRESH_ENABLED', raising=False)
    monkeypatch.setattr(router_module, 'get_gateway', lambda: SimpleNamespace(config=cfg))
    app = FastAPI()
    app.include_router(build_cockpit_router(
        lambda: str(tmp_path), main_runner=main_runner or (lambda *a: (_ for _ in ()).throw(
            AssertionError('opening the page must not call the model'))),
        main_context=lambda context: {}))
    return TestClient(app)


def test_startup_serves_published_cards_without_starting_analysis(tmp_path, monkeypatch):
    store, cfg, page = _router_fixture(tmp_path)
    client = _client(tmp_path, monkeypatch, cfg)
    started = client.get('/api/cockpit/startup?id=1&page=analysis').json()
    assert started['snapshot']['version'] == page['version']
    assert started['displayStale'] is False
    assert started['snapshot']['items']['shipment']['result']['summary'] == 'old card'
    status = client.get('/api/cockpit/publications/status?id=1&page=analysis').json()
    assert status['publicationVersion'] == page['version']
    assert status['displayStale'] is False
    assert status['scope'] == page_scope(cfg, 1, 'analysis', 'default', 'ap')
    # A page miss returns no evidence rather than silently mixing ranges.
    assert client.get('/api/cockpit/page?id=1&page=analysis&uiScope=other').json()['snapshot'] is None
    assert store.refresh_state(page_scope(cfg, 1, 'analysis', 'default', 'ap')) is None


def test_rotated_scope_key_is_display_only_and_never_evidence(tmp_path, monkeypatch):
    store, cfg, page = _router_fixture(tmp_path)
    with patch('bi_agent.cockpit.page_cache.config_version', return_value='new-components'):
        lookup = _client(tmp_path, monkeypatch, cfg).post(
            '/api/cockpit/page/lookup', json=dict(id=1, page='analysis', uiScope='default')).json()
    assert lookup['snapshot'] is None
    assert lookup['displaySnapshot']['version'] == page['version']
    assert lookup['displayStale'] is True
    assert lookup['status']['update']['status'] == 'stale-display'


def test_refresh_lease_blocks_duplicate_workers_and_recovers_after_expiry(tmp_path):
    store, cfg, _page = _router_fixture(tmp_path)
    scope = page_scope(cfg, 1, 'analysis', 'default', 'ap')
    assert store.claim_refresh(scope, now=1000, lease=120) is True
    assert store.claim_refresh(scope, now=1050, lease=120) is False
    assert store.refresh_state(scope)['status'] == 'running'
    assert store.claim_refresh(scope, now=1200, lease=120) is True
    assert store.set_refresh_state(scope, 'retry_wait', next_check=1400, error='AP unavailable')['last_error'] == 'AP unavailable'
    assert scope not in store.due_refresh_scopes(now=1300)
    assert scope in store.due_refresh_scopes(now=1450)


def test_manual_refresh_does_not_steal_a_live_lease(tmp_path):
    store, cfg, _page = _router_fixture(tmp_path)
    scope = page_scope(cfg, 1, 'analysis', 'default', 'ap')
    now = time.time()
    store.set_refresh_state(scope, 'running', next_check=now, lease_until=now + 120)
    assert store.request_refresh(scope, now=now) is False
    state = store.refresh_state(scope)
    assert state['status'] == 'running'
    assert state['lease_until'] >= now + 100


def test_default_views_keeps_only_the_newest_card_for_each_stage(tmp_path):
    from bi_agent.cockpit.dashboard_source import RELEASE
    from bi_agent.cockpit.publications import view_scope
    store, cfg, _page = _router_fixture(tmp_path)
    contexts = []
    for fingerprint in ('old-card', 'new-card'):
        contexts.append(dict(id=1, engine='main', page='operations', stage='bid', source='service',
                             defaultView=True, chartSnapshotId=RELEASE, chartQueries=[],
                             period='2025-10', department='全部产品部', filters={}, repositoryId='',
                             clarifications={}, baselineAnalysisId='', dataSource='ap',
                             dataIdentity=cfg.identity(), dataFingerprint=fingerprint))
    ids = []
    for context in contexts:
        item = store.create_analysis('view-' + context['dataFingerprint'], context)
        store.update_analysis(item['id'], status='limited',
                              result=dict(summary=context['dataFingerprint'], cardContract=CONTRACT),
                              evidence={'facts': [], 'records': [], 'evidence': []})
        assert store.publish(item['id'])
        assert store.bind_view(view_scope(context), 'bid', item['scope'])
        ids.append(item['id'])
    rows = [row for row in store.default_views() if row[1] == 'bid' and
            (row[2].get('context') or {}).get('id') == 1]
    assert len(rows) == 1
    assert rows[0][2]['id'] == ids[-1]


def test_status_uses_card_state_when_a_page_has_no_snapshot(tmp_path, monkeypatch):
    from bi_agent.cockpit.dashboard_source import RELEASE
    from bi_agent.cockpit.publications import view_scope
    from bi_agent.cockpit.refresh import view_target_scope
    store, cfg, _page = _router_fixture(tmp_path)
    context = dict(id=1, engine='main', page='operations', stage='bid', source='service',
                   defaultView=True, chartSnapshotId=RELEASE, chartQueries=[],
                   period='2025-10', department='全部产品部', filters={}, repositoryId='',
                   clarifications={}, baselineAnalysisId='', dataSource='ap',
                   dataIdentity=cfg.identity(), dataFingerprint='ops-card')
    item = store.create_analysis('ops-card', context)
    store.update_analysis(item['id'], status='limited',
                          result=dict(summary='ops card', cardContract=CONTRACT),
                          evidence={'facts': [], 'records': [], 'evidence': []})
    assert store.publish(item['id'])
    assert store.bind_view(view_scope(context), 'bid', item['scope'])
    target = view_target_scope(view_scope(context), 'bid')
    store.set_refresh_state(target, 'waiting', next_check=time.time() + 900)
    client = _client(tmp_path, monkeypatch, cfg)
    status = client.get('/api/cockpit/publications/status?id=1&page=operations').json()
    assert status['update']['status'] == 'scheduled'
    assert status['update']['nextCheckAt'] > time.time() + 500
    assert status['cardsVersion']
    store.request_refresh(target)
    waiting = client.get('/api/cockpit/publications/status?id=1&page=operations').json()
    assert waiting['update']['status'] == 'waiting'


def test_scheduler_warms_default_scopes_only(tmp_path):
    store, cfg, page = _router_fixture(tmp_path)
    custom_scope = page_scope(cfg, 1, 'analysis', 'custom', 'ap')
    assert store.publish_page(custom_scope, dict(page, uiScope='custom'))
    calls = []
    manager = RefreshManager(
        store, cfg,
        lambda identity, kind, payload: {'value': 79.16} if kind == 'analysis' else {'nodes': []},
        _analysis_factory(store, calls), interval=900, poll=0.01, timeout=5)
    scheduler = RefreshScheduler(manager, store, scan_seconds=2, scope_limit=3)
    # A fresh deploy seeds the first check one interval ahead instead of
    # re-querying every default page the moment the process starts.
    assert scheduler.run_once(now=1000.0) == 0
    assert store.refresh_state(page_scope(cfg, 1, 'analysis', 'default', 'ap'))['next_check'] == 1900.0
    assert scheduler.run_once(now=1901.0) == 1
    assert calls == []
    assert store.refresh_state(page_scope(cfg, 1, 'analysis', 'default', 'ap'))['status'] == 'published'
    assert store.refresh_state(custom_scope) is None


def test_scheduler_recovers_publication_when_config_version_rotates(tmp_path):
    with patch('bi_agent.cockpit.page_cache.config_version', return_value='old-components'):
        store, cfg, query, helmet, old = _fixture(tmp_path)
    new_scope = page_scope(cfg, 1, 'analysis', 'default', 'ap')
    assert store.published_page(new_scope) is None
    calls = []
    manager = RefreshManager(store, cfg,
        lambda identity, kind, payload: {'value': 79.16} if kind == 'analysis' else {'nodes': []},
        _analysis_factory(store, calls), interval=900, poll=0.01, timeout=5)
    scheduler = RefreshScheduler(manager, store, scan_seconds=2)
    store.set_refresh_state(new_scope, 'waiting', next_check=0)
    assert scheduler.run_once(now=10000.0) == 1
    assert store.published_page(new_scope) is not None
    # A rotated config version invalidates the delivered contract, so both
    # stages are re-analysed and republished under the new scope key.
    assert len(calls) == 2


def test_status_keeps_active_refresh_state_instead_of_stale_display(tmp_path, monkeypatch):
    with patch('bi_agent.cockpit.page_cache.config_version', return_value='old-components'):
        store, cfg, page = _router_fixture(tmp_path)
    new_scope = page_scope(cfg, 1, 'analysis', 'default', 'ap')
    store.set_refresh_state(new_scope, 'waiting', next_check=0)
    status = _client(tmp_path, monkeypatch, cfg).get(
        '/api/cockpit/publications/status?id=1&page=analysis').json()
    assert status['displayStale'] is True and status['update']['status'] == 'waiting'


def _capture_factory(store, calls):
    def start(body, resolved):
        calls.append((body, dict(resolved)))
        context = {**body, **resolved, 'stageName': body['stage'], 'sourceMode': 'service'}
        item = store.create_analysis('new-' + body['stage'], context)
        store.update_analysis(item['id'], status='limited',
                              result=dict(summary='new card', cardContract=CONTRACT),
                              evidence={'facts': [], 'records': [], 'evidence': []})
        return store.get_analysis(item['id'])
    return start


def _publishing_factory(store, calls):
    from bi_agent.cockpit.publications import view_scope as scope_for_view
    def start(body, resolved):
        calls.append((body, dict(resolved)))
        context = {**body, **resolved, 'stageName': body['stage'], 'sourceMode': 'service'}
        item = store.create_analysis('new-' + body['stage'], context)
        store.update_analysis(item['id'], status='limited',
                              result=dict(summary='new card', cardContract=CONTRACT),
                              evidence={'facts': [], 'records': [], 'evidence': []})
        assert store.publish(item['id'])
        store.bind_view(scope_for_view(context), body['stage'], item['scope'])
        return store.get_analysis(item['id'])
    return start


def test_refresh_uses_the_same_evidence_resolver_as_the_http_turn(tmp_path):
    from bi_agent.cockpit.dashboard_source import receipt_material
    store, cfg, query, helmet, old = _fixture(tmp_path)
    calls = []
    manager = RefreshManager(store, cfg,
        lambda identity, kind, payload: {'value': 99.0} if kind == 'analysis' else {'nodes': []},
        _capture_factory(store, calls), interval=900, poll=0.01, timeout=5)
    result = manager.refresh(old)
    assert result['status'] == 'published' and result['changed'] is True
    assert len(calls) == 2
    business = json.dumps(query, sort_keys=False)
    for body, resolved in calls:
        # Helmet graph data never becomes a business analysis receipt.
        assert [json.loads(value) for value in body['chartQueries']] == [query]
        assert all('flowCode' not in value for value in body['chartQueries'])
        context = {**body, **resolved}
        # The turn recomputes this exact fingerprint before running the model.
        fingerprint, _selected = receipt_material(context, store, allow_expired=True)
        assert resolved['snapshotId'] == 'ap-' + fingerprint
        assert resolved['dataFingerprint'] == old['dataFingerprint'] or resolved['dataFingerprint']
    current = store.published_page(page_scope(cfg, 1, 'analysis', 'default', 'ap'))
    assert current['dataSource'] == 'ap'
    assert current['dataFingerprint'] == calls[0][1]['dataFingerprint']


def test_refresh_supplements_failed_business_queries_from_postgres(tmp_path, monkeypatch):
    from bi_agent.cockpit import pg_fallback
    store, cfg, query, helmet, old = _fixture(tmp_path)
    calls = []

    def fake_supplement(context, local_store, *, query_fn=None, limit=4, stage=None):
        assert stage is None
        payload = json.loads(context['unavailableQueries'][0])
        response = {'resultType': 'TABLE', 'result': {'columns': [
            {'identifierCode': 'YWLN_M0036', 'label': '发货金额', 'type': 'METRIC',
             'unit': '亿元', 'decimals': 2}],
            'rows': [{'YWLN_M0036': {'value': 79.16, 'render': {'unit': '亿元'}}}]},
            'pagination': {'pageNum': 1, 'pageSize': 20, 'total': 1}}
        item = local_store.save_ap_result(int(context['id']), 'pg', payload, response, 3600,
                                          'pg:ywln_crm', pg_fallback.version(), 'postgres')
        return {'pg:' + item['id']: dict(request=payload, response=response,
                                         receivedAt=item['createdAt'], source='pg',
                                         receiptId=item['id'], connectionId=item['connectionId'],
                                         transport='postgres')}, []

    monkeypatch.setattr(pg_fallback, 'supplement', fake_supplement)

    def query_transport(identity, kind, payload):
        if kind == 'helmet':
            return {'nodes': []}
        raise RuntimeError('AP timeout')

    manager = RefreshManager(store, cfg, query_transport, _capture_factory(store, calls),
                             interval=900, poll=0.01, timeout=5)
    result = manager.refresh(old)
    assert result['status'] == 'published'
    page = store.published_page(page_scope(cfg, 1, 'analysis', 'default', 'ap'))
    assert page['dataSource'] == 'pg' and page['dataIdentity'] == 'postgres'
    assert any(entry['kind'] == 'pg' for entry in page['entries'])
    assert calls and all(entry[1]['pgReceiptIds'] for entry in calls)


def test_scheduler_maintains_published_stage_cards_without_a_page_snapshot(tmp_path):
    from bi_agent.cockpit.dashboard_source import RELEASE
    from bi_agent.cockpit.publications import view_scope
    from bi_agent.cockpit.refresh import view_target_scope
    cfg = Config()
    store = Store(tmp_path / 'history.sqlite3')
    query = {'analysisConfig': {'indicators': [{'identifierCode': 'YWLN_M0036'}]},
             'commonConfig': {'filters': {'logic': 'AND', 'children': []}}}
    context = dict(id=1, engine='main', page='analysis', stage='shipment', source='service',
                   defaultView=True, chartSnapshotId=RELEASE,
                   chartQueries=[json.dumps(query, sort_keys=True, separators=(',', ':'))],
                   period='2025-10', department='全部产品部', filters={}, repositoryId='',
                   clarifications={}, baselineAnalysisId='', dataSource='ap',
                   dataIdentity=cfg.identity(), dataFingerprint='old-fingerprint')
    item = store.create_analysis('old-shipment', context)
    store.update_analysis(item['id'], status='limited',
                          result=dict(summary='old card', cardContract=CONTRACT),
                          evidence={'facts': [], 'records': [], 'evidence': []})
    assert store.publish(item['id'])
    store.bind_view(view_scope(context), 'shipment', item['scope'])
    assert store.published_page(page_scope(cfg, 1, 'analysis', 'default', 'ap')) is None
    calls = []
    manager = RefreshManager(store, cfg, lambda identity, kind, payload: {'value': 80.0},
                             _publishing_factory(store, calls), interval=900, poll=0.01, timeout=5)
    scheduler = RefreshScheduler(manager, store, scan_seconds=2)
    assert scheduler.run_once(now=1000.0) == 0
    [(view_key, stage, _body)] = store.default_views()
    target = view_target_scope(view_key, stage)
    assert store.refresh_state(target)['next_check'] == 1900.0
    assert scheduler.run_once(now=1901.0) == 1
    assert calls
    published = store.published_view(view_scope({**calls[0][0], **calls[0][1],
                                                 'sourceMode': 'service', 'stageName': 'shipment'}))
    assert published['shipment']['result']['summary'] == 'new card'
    assert store.refresh_state(target)['status'] == 'published'


def test_manual_refresh_never_steals_a_running_lease(tmp_path, monkeypatch):
    store, cfg, page = _router_fixture(tmp_path)
    scope = page_scope(cfg, 1, 'analysis', 'default', 'ap')
    assert store.claim_refresh(scope, lease=600)
    before = store.refresh_state(scope)
    body = _client(tmp_path, monkeypatch, cfg).post(
        '/api/cockpit/publications/refresh',
        json=dict(id=1, page='analysis', uiScope='default')).json()
    after = store.refresh_state(scope)
    assert body['queued'] is False and body['status'] == 'running'
    assert after['status'] == 'running' and after['lease_until'] == before['lease_until']


def test_manual_refresh_rejects_a_scope_without_a_query_plan(tmp_path, monkeypatch):
    store, cfg, _page = _router_fixture(tmp_path)
    client = _client(tmp_path, monkeypatch, cfg)
    response = client.post('/api/cockpit/publications/refresh',
                           json=dict(id=1, page='analysis', uiScope='never-loaded'))
    assert response.status_code == 409
    assert store.refresh_state(page_scope(cfg, 1, 'analysis', 'never-loaded', 'ap')) is None


def test_refresh_view_recovers_a_postgres_only_card(tmp_path, monkeypatch):
    from bi_agent.cockpit import pg_fallback
    from bi_agent.cockpit.dashboard_source import RELEASE
    from bi_agent.cockpit.publications import view_scope
    cfg = Config()
    store = Store(tmp_path / 'history.sqlite3')
    query = {'analysisConfig': {'indicators': [{'identifierCode': 'YWLN_M0036'}]},
             'commonConfig': {'filters': {'logic': 'AND', 'children': []}}}
    encoded = json.dumps(query, sort_keys=True, separators=(',', ':'))
    context = dict(id=1, engine='main', page='analysis', stage='shipment', source='service',
                   defaultView=True, chartSnapshotId=RELEASE, chartQueries=[],
                   unavailableQueries=[encoded], period='2025-10', department='全部产品部',
                   filters={}, repositoryId='', clarifications={}, baselineAnalysisId='',
                   dataSource='pg', dataIdentity='postgres', dataFingerprint='old-fingerprint')
    item = store.create_analysis('old-pg', context)
    store.update_analysis(item['id'], status='limited',
                          result=dict(summary='old pg card', cardContract=CONTRACT),
                          evidence={'facts': [], 'records': [], 'evidence': []})
    store.publish(item['id'])
    store.bind_view(view_scope(context), 'shipment', item['scope'])

    def fake_supplement(local_context, local_store, *, query_fn=None, limit=4, stage=None):
        payload = json.loads(local_context['unavailableQueries'][0])
        response = {'resultType': 'TABLE', 'result': {'columns': [], 'rows': []},
                    'pagination': {'pageNum': 1, 'pageSize': 20, 'total': 0}}
        receipt = local_store.save_ap_result(int(local_context['id']), 'pg', payload, response,
                                             3600, 'pg:ywln_crm', pg_fallback.version(), 'postgres')
        return {'pg:' + receipt['id']: dict(request=payload, response=response,
                                            receivedAt=receipt['createdAt'], source='pg',
                                            receiptId=receipt['id'],
                                            connectionId=receipt['connectionId'],
                                            transport='postgres')}, []

    monkeypatch.setattr(pg_fallback, 'supplement', fake_supplement)
    calls = []

    def query_transport(identity, kind, payload):
        raise RuntimeError('AP still unavailable')

    manager = RefreshManager(store, cfg, query_transport, _publishing_factory(store, calls),
                             interval=900, poll=0.01, timeout=5)
    [(view_key, stage, _body)] = store.default_views()
    result = manager.refresh_view(view_key, stage, store.get_analysis(item['id']))
    assert result['status'] == 'published' and result['changed'] is True
    assert calls and calls[0][0]['apReceiptIds'] == []
    assert calls[0][1]['dataSource'] == 'pg'
    published = store.published_view(view_scope({**calls[0][0], **calls[0][1],
                                                 'sourceMode': 'service', 'stageName': 'shipment'}))
    assert published['shipment']['result']['summary'] == 'new card'


def test_published_default_returns_postgres_fallback_cards(tmp_path, monkeypatch):
    from bi_agent.cockpit.dashboard_source import RELEASE
    from bi_agent.cockpit.publications import view_scope
    store, cfg, _page = _router_fixture(tmp_path)
    context = dict(id=1, engine='main', page='analysis', stage='shipment', source='service',
                   defaultView=True, chartSnapshotId=RELEASE, chartQueries=[],
                   period='2025-10', department='全部产品部', filters={}, repositoryId='',
                   clarifications={}, baselineAnalysisId='', dataSource='pg',
                   dataIdentity='postgres', dataFingerprint='pg-fingerprint')
    item = store.create_analysis('pg-card', context)
    store.update_analysis(item['id'], status='limited',
                          result=dict(summary='pg card', cardContract=CONTRACT),
                          evidence={'facts': [], 'records': [], 'evidence': []})
    assert store.publish(item['id'])
    store.bind_view(view_scope(context), 'shipment', item['scope'])
    saved = _client(tmp_path, monkeypatch, cfg).get(
        '/api/cockpit/analyses/published?id=1&page=analysis').json()['items']
    assert saved['shipment']['id'] == item['id']
    assert saved['shipment']['context']['dataSource'] == 'pg'


def test_manual_refresh_of_a_custom_scope_is_executed_by_the_scheduler(tmp_path, monkeypatch):
    store, cfg, page = _router_fixture(tmp_path)
    custom = page_scope(cfg, 1, 'analysis', 'department-B', 'ap')
    assert store.publish_page(custom, dict(page, uiScope='department-B'))
    client = _client(tmp_path, monkeypatch, cfg)
    queued = client.post('/api/cockpit/publications/refresh',
                         json=dict(id=1, page='analysis', uiScope='department-B')).json()
    assert queued['queued'] is True and queued['kind'] == 'page'
    assert store.refresh_state(custom)['status'] == 'waiting'
    calls = []
    manager = RefreshManager(store, cfg,
        lambda identity, kind, payload: {'value': 79.16} if kind == 'analysis' else {'nodes': []},
        _analysis_factory(store, calls), interval=900, poll=0.01, timeout=5)
    scheduler = RefreshScheduler(manager, store, scan_seconds=2)
    assert scheduler.run_once(now=time.time() + 1) == 1
    assert store.refresh_state(custom)['status'] == 'published'
    # Unchanged custom evidence reuses the last complete page and spends no model call.
    assert calls == []


def test_rotated_card_key_still_displays_the_last_analysis(tmp_path, monkeypatch):
    from bi_agent.cockpit.dashboard_source import RELEASE
    from bi_agent.cockpit.publications import view_scope
    store, cfg, _page = _router_fixture(tmp_path)
    context = dict(id=1, engine='main', page='analysis', stage='shipment', source='service',
                   defaultView=True, chartSnapshotId=RELEASE, chartQueries=[],
                   period='2025-10', department='全部产品部', filters={}, repositoryId='',
                   clarifications={}, baselineAnalysisId='', dataSource='ap',
                   dataIdentity=cfg.identity(), dataFingerprint='old-fingerprint')
    item = store.create_analysis('old-card', context)
    store.update_analysis(item['id'], status='limited',
                          result=dict(summary='last analysis', cardContract=CONTRACT),
                          evidence={'facts': [], 'records': [], 'evidence': []})
    with patch('bi_agent.cockpit.publications.config_version', return_value='before-metadata-sync'):
        old_key = view_scope(context)
    store.publish(item['id'])
    store.bind_view(old_key, 'shipment', item['scope'])
    saved = _client(tmp_path, monkeypatch, cfg).get(
        '/api/cockpit/analyses/published?id=1&page=analysis').json()['items']
    assert saved['shipment']['id'] == item['id']
    assert saved['shipment']['displayOnly'] is True
