"""Server-owned refresh: unchanged evidence never invokes the model."""
import json
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
        lambda kind, payload: {'value': 79.16} if kind == 'analysis' else {'nodes': []},
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
        lambda kind, payload: {'value': 79.16} if kind == 'analysis' else {'nodes': []},
        _analysis_factory(store, []), interval=900, poll=0.01, timeout=5)
    assert manager.refresh(old)['status'] == 'published'
    assert snapshots() == before


def test_refresh_runs_model_only_after_fingerprint_changes(tmp_path):
    store, cfg, query, helmet, old = _fixture(tmp_path)
    calls = []
    manager = RefreshManager(store, cfg,
        lambda kind, payload: {'value': 99.0} if kind == 'analysis' else {'nodes': []},
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
    def fail(kind, payload):
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


def test_scheduler_warms_default_scopes_only(tmp_path):
    store, cfg, page = _router_fixture(tmp_path)
    custom_scope = page_scope(cfg, 1, 'analysis', 'custom', 'ap')
    assert store.publish_page(custom_scope, dict(page, uiScope='custom'))
    calls = []
    manager = RefreshManager(
        store, cfg,
        lambda kind, payload: {'value': 79.16} if kind == 'analysis' else {'nodes': []},
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
