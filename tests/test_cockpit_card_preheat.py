"""Every delivered AI slot is a durable, server-side card target.

The dashboard declares its slots in ``insights.json``.  A slot that the user
has never opened must still get a saved card, and a card already saved for the
same stage must come back when the user switches to another page that shows
that stage.  Neither behaviour may depend on the browser being open.
"""
import json
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bi_agent.cockpit.cards import CONTRACT
from bi_agent.cockpit.page_cache import PageRequest, build_page, page_fingerprint, page_scope, transport_identity
from bi_agent.cockpit.publications import view_scope
from bi_agent.cockpit.refresh import RefreshManager, RefreshScheduler, preheat_target_scope
from bi_agent.cockpit.router import build_cockpit_router
from bi_agent.cockpit.store import Store
from bi_agent.cockpit.targets import SLOT_STAGES, configured_targets, slots, unmapped_slots

QUERIES = {
    'bid': {'analysisConfig': {'dimensions': [],
                              'indicators': [{'identifierCode': 'YWLN_M0034', 'alias': '中标金额'}]},
            'commonConfig': {'pagination': {'pageNum': 1, 'pageSize': 20}}},
    'quotation': {'analysisConfig': {'dimensions': [],
                                     'indicators': [{'identifierCode': 'YWLN_M0031', 'alias': '报价金额'}]},
                  'commonConfig': {'pagination': {'pageNum': 1, 'pageSize': 20}}},
    'order': {'analysisConfig': {'dimensions': [],
                                 'indicators': [{'identifierCode': 'YWLN_M0032', 'alias': '已中标未签单金额'}]},
              'commonConfig': {'pagination': {'pageNum': 1, 'pageSize': 20}}},
}
ANALYSIS_QUERIES = {
    **QUERIES,
    'opportunity': {'analysisConfig': {'dimensions': [],
                                      'indicators': [{'identifierCode': 'YWLN_M0023', 'alias': '商机获取金额'}]},
                    'commonConfig': {'pagination': {'pageNum': 1, 'pageSize': 20}}},
    'shipment': {'analysisConfig': {'dimensions': [],
                                   'indicators': [{'identifierCode': 'YWLN_M0036', 'alias': '发货金额'}]},
                 'commonConfig': {'pagination': {'pageNum': 1, 'pageSize': 20}}},
}
HELMET = {'flowCode': 'SALES_CALIBER'}


class Config:
    base_url = 'http://ap.example/api/gateway2'
    batch_mode = 'individual'
    receipt_ttl = 3600

    def headers(self):
        return {'X-App-Id': 'preheat-test'}

    def identity(self):
        return 'source-preheat'


def _analyse(store, cfg, stage, page, queries, fingerprint='f-' + 'page', data_identity=None):
    context = dict(id=1, page=page, stage=stage, engine='main', dataSource='ap',
                   dataIdentity=data_identity or cfg.identity(), dataFingerprint=fingerprint,
                   chartQueries=sorted(json.dumps(q, sort_keys=True) for q in queries),
                   period='2025-10', department='全部产品部')
    item = store.create_analysis('seed-' + stage, context)
    store.update_analysis(item['id'], status='limited',
                          result=dict(summary=stage + ' card', cardContract=CONTRACT),
                          evidence={'facts': [], 'records': [], 'evidence': []})
    store.publish(item['id'])
    return item


def _publish_operations(store, cfg, *, items=('bid',)):
    records = []
    for stage, query in QUERIES.items():
        records.append(store.save_ap_result(1, 'analysis', query, {'value': stage + '-value'},
                                            cfg.receipt_ttl, cfg.identity(), transport_identity(cfg)))
    records.append(store.save_ap_result(1, 'helmet', HELMET, {'nodes': []}, cfg.receipt_ttl,
                                        cfg.identity(), transport_identity(cfg)))
    fingerprint = page_fingerprint(records)
    analyses = {}
    for stage in items:
        item = _analyse(store, cfg, stage, 'operations', list(QUERIES.values()), fingerprint,
                        data_identity=cfg.identity())
        analyses[stage] = item['id']
    page = build_page(PageRequest(id=1, page='operations', uiScope='default',
                                  apReceiptIds=[record['id'] for record in records],
                                  analysisIds=analyses), store, cfg, data_source='ap')
    assert store.publish_page(page_scope(cfg, 1, 'operations', 'default', 'ap'), page)
    return page


def _publish_analysis(store, cfg, *, items=('opportunity', 'shipment')):
    records = []
    for stage, query in ANALYSIS_QUERIES.items():
        records.append(store.save_ap_result(1, 'analysis', query, {'value': stage + '-value'},
                                            cfg.receipt_ttl, cfg.identity(), transport_identity(cfg)))
    records.append(store.save_ap_result(1, 'helmet', HELMET, {'nodes': []}, cfg.receipt_ttl,
                                        cfg.identity(), transport_identity(cfg)))
    fingerprint = page_fingerprint(records)
    analyses = {}
    for stage in items:
        item = _analyse(store, cfg, stage, 'analysis', list(ANALYSIS_QUERIES.values()), fingerprint,
                        data_identity=cfg.identity())
        analyses[stage] = item['id']
    page = build_page(PageRequest(id=1, page='analysis', uiScope='default',
                                  apReceiptIds=[record['id'] for record in records],
                                  analysisIds=analyses), store, cfg, data_source='ap')
    assert store.publish_page(page_scope(cfg, 1, 'analysis', 'default', 'ap'), page)
    return page


def _publishing_factory(store, calls):
    def start(body, resolved):
        calls.append(body)
        context = {**body, **resolved, 'stageName': body['stage'], 'sourceMode': 'service'}
        item = store.create_analysis('preheat-%s-%s-%d' % (body['page'], body['stage'], len(calls)), context)
        store.update_analysis(item['id'], status='limited',
                              result=dict(summary='new ' + body['stage'], cardContract=CONTRACT),
                              evidence={'facts': [], 'records': [], 'evidence': []})
        store.publish(item['id'])
        store.bind_view(view_scope(item['context']), body['stage'], item['scope'])
        return store.get_analysis(item['id'])
    return start


def _client(tmp_path, monkeypatch, cfg):
    import bi_agent.cockpit.router as router_module
    monkeypatch.setenv('COCKPIT_DATA_MODE', 'ap')
    monkeypatch.delenv('COCKPIT_REFRESH_ENABLED', raising=False)
    monkeypatch.setattr(router_module, 'get_gateway', lambda: SimpleNamespace(config=cfg))
    app = FastAPI()
    app.include_router(build_cockpit_router(
        lambda: str(tmp_path), main_runner=lambda *a: (_ for _ in ()).throw(
            AssertionError('opening a page must not call the model')),
        main_context=lambda context: {}))
    return TestClient(app)


def test_every_delivered_slot_has_a_page_and_stage_target():
    delivered = slots()
    assert sorted(slot['id'] for slot in delivered) == sorted(SLOT_STAGES)
    assert unmapped_slots() == []
    targets = configured_targets()
    assert targets['overview'] == ()
    assert targets['operations'] == ('bid', 'order', 'quotation')
    assert targets['analysis'] == ('opportunity', 'order', 'shipment')


def test_saved_page_cards_and_cross_page_stage_cards_are_returned(tmp_path, monkeypatch):
    cfg = Config()
    store = Store(tmp_path / 'dataset' / 'cockpit' / 'history.sqlite3')
    _publish_operations(store, cfg, items=('bid',))
    # The order card was saved while the analysis page was open.  The
    # operations page shows the same business stage, so it must come back.
    quotation = _analyse(store, cfg, 'quotation', 'operations', [QUERIES['quotation']])
    store.bind_view(view_scope(quotation['context']), 'quotation', quotation['scope'])
    order = _analyse(store, cfg, 'order', 'analysis', [QUERIES['order']])
    store.bind_view(view_scope(order['context']), 'order', order['scope'])

    saved = _client(tmp_path, monkeypatch, cfg).get(
        '/api/cockpit/publications/cards?id=1&page=operations').json()
    cards = saved['items']
    assert set(cards) == {'bid', 'quotation', 'order'}
    assert saved['cardsVersion']
    assert all(item['result']['cardContract'] == CONTRACT for item in cards.values())


def test_startup_returns_every_saved_page_card_for_in_place_tab_switching(tmp_path, monkeypatch):
    cfg = Config()
    store = Store(tmp_path / 'dataset' / 'cockpit' / 'history.sqlite3')
    _publish_operations(store, cfg, items=('bid',))
    _publish_analysis(store, cfg, items=('opportunity', 'shipment'))

    started = _client(tmp_path, monkeypatch, cfg).get('/api/cockpit/startup?id=1&page=operations').json()
    assert set(started['cardsByPage']['operations']) == {'bid'}
    assert set(started['cardsByPage']['analysis']) == {'opportunity', 'shipment'}
    # The browser preloads one union, so switching to an unvisited tab never
    # has to open a model job just to discover an already saved card.
    assert set(started['cards']) == {'bid', 'opportunity', 'shipment'}
    assert started['cardsVersion']


def test_scheduler_preheats_targets_that_have_no_saved_card(tmp_path):
    cfg = Config()
    store = Store(tmp_path / 'history.sqlite3')
    page = _publish_operations(store, cfg, items=('bid',))
    _publish_analysis(store, cfg, items=('opportunity', 'shipment'))
    calls = []
    manager = RefreshManager(
        store, cfg, lambda identity, kind, payload: {'value': 'live'},
        _publishing_factory(store, calls), interval=900, poll=0.01, timeout=5)
    scheduler = RefreshScheduler(manager, store, scan_seconds=2, scope_limit=8)
    # A configured slot with no saved card is due immediately.  It must not
    # wait for the first 900-second maintenance interval.
    assert scheduler.run_once(now=1000.0) > 0
    for stage in ('bid', 'quotation', 'order'):
        assert store.refresh_state(preheat_target_scope(1, 'operations', stage))
    scheduler.run_once(now=1901.0)
    stages = {body['stage'] for body in calls}
    assert {'bid', 'quotation', 'order', 'shipment'} <= stages
    views = store.default_views()
    assert {(body['context']['page'], stage) for _key, stage, body in views} >= {
        ('operations', 'bid'), ('operations', 'quotation'), ('operations', 'order'),
        ('analysis', 'opportunity'), ('analysis', 'shipment'),
    }
    # 订单接收 is one business stage shared by both pages.  The API exposes it
    # under both slot ids, but preheat must not run a second model call merely
    # because the same stage is mounted on the penetration page.
    order_cards = [body for _key, stage, body in views
                   if stage == 'order' and body['context']['id'] == 1]
    assert len(order_cards) == 1
    # The stage card is bound to the operations page, not to whichever page
    # happened to publish it first.
    for stage in ('quotation', 'order'):
        card = store.latest_views(1, 'main', 'operations').get(stage)
        assert card and card['context']['page'] == 'operations'
    del page


def test_scheduler_can_seed_a_role_from_a_saved_query_plan_without_reusing_evidence(tmp_path):
    cfg = Config()
    store = Store(tmp_path / 'history.sqlite3')
    query = QUERIES['quotation']
    context = dict(id=2, page='operations', stage='quotation', engine='main', dataSource='ap',
                   dataIdentity=cfg.identity(), dataFingerprint='role-2-plan',
                   chartQueries=[json.dumps(query, sort_keys=True)], period='2025-10',
                   department='全部产品部')
    item = store.create_analysis('role-2-quotation', context)
    store.update_analysis(item['id'], status='limited',
                          result=dict(summary='role 2 card', cardContract=CONTRACT),
                          evidence={'facts': [], 'records': [], 'evidence': []})
    store.publish(item['id'])
    store.bind_view(view_scope(context), 'quotation', item['scope'])
    calls = []
    manager = RefreshManager(
        store, cfg, lambda identity, kind, payload: {'value': 'live'},
        _publishing_factory(store, calls), interval=900, poll=0.01, timeout=5)
    scheduler = RefreshScheduler(manager, store, scan_seconds=2, scope_limit=8)
    assert scheduler.run_once(now=1000.0) > 0
    role_one = store.latest_views(1, 'main', 'operations').get('quotation')
    assert role_one and role_one['context']['id'] == 1
    assert any(body['id'] == 1 and body['stage'] == 'quotation' for body in calls)


def test_unchanged_preheat_does_not_call_the_model_twice(tmp_path):
    cfg = Config()
    store = Store(tmp_path / 'history.sqlite3')
    _publish_operations(store, cfg, items=('bid',))
    calls = []
    manager = RefreshManager(
        store, cfg, lambda identity, kind, payload: {'value': 'live'},
        _publishing_factory(store, calls), interval=900, poll=0.01, timeout=5)
    scheduler = RefreshScheduler(manager, store, scan_seconds=2, scope_limit=8)
    scheduler.run_once(now=1000.0)
    scheduler.run_once(now=1901.0)
    first = len(calls)
    assert first >= 2
    scheduler.run_once(now=2802.0)
    assert len(calls) == first
