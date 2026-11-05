"""按期间缓存的刷新策略、合并队列与按环节刷新（第一阶段）。

这些用例先于实现编写：期间分类、pending 合并、按环节复用都必须在这里成立，
再向 ``bi_agent/cockpit`` 落地实现。
"""
import datetime as dt
import json
import time

from bi_agent.cockpit.cards import CONTRACT
from bi_agent.cockpit.page_cache import (PageRequest, build_page, page_fingerprint,
                                         page_scope, transport_identity)
from bi_agent.cockpit.refresh import RefreshManager
from bi_agent.cockpit.store import Store


NOW = dt.datetime(2026, 11, 5, 10, 0, 0)


# ---------------------------------------------------------------- 期间策略

def test_current_period_refreshes_on_interval():
    from bi_agent.cockpit import periods
    policy = periods.policy_for('2026-11', now=NOW, active='2026-11', interval=900)
    assert policy['kind'] == 'current'
    assert policy['recheckAfter'] == 900
    assert policy['activePeriod'] == '2026-11'


def test_previous_period_refreshes_inside_grace_window():
    from bi_agent.cockpit import periods
    policy = periods.policy_for('2026-10', now=NOW, active='2026-11',
                                interval=900, grace_days=7)
    assert policy['kind'] == 'grace'
    assert policy['recheckAfter'] == 900


def test_previous_period_freezes_after_grace_window():
    from bi_agent.cockpit import periods
    policy = periods.policy_for('2026-10', now=dt.datetime(2026, 11, 20, 10, 0),
                                active='2026-11', interval=900, grace_days=7)
    assert policy['kind'] == 'historical'
    assert policy['recheckAfter'] is None


def test_historical_period_is_frozen():
    from bi_agent.cockpit import periods
    policy = periods.policy_for('2025-10', now=NOW, active='2026-11', interval=900)
    assert policy['kind'] == 'historical'
    assert policy['recheckAfter'] is None


def test_year_period_follows_the_same_active_period():
    from bi_agent.cockpit import periods
    assert periods.policy_for('2026', now=NOW, active='2026-11')['kind'] == 'current'
    assert periods.policy_for('2025', now=NOW, active='2026-11')['kind'] == 'historical'


def test_unknown_period_keeps_the_existing_interval():
    from bi_agent.cockpit import periods
    policy = periods.policy_for('', now=NOW, active='2026-11', interval=900)
    assert policy['kind'] == 'unknown'
    assert policy['recheckAfter'] == 900


def test_period_of_scope_reads_default_month_and_year():
    from bi_agent.cockpit import periods
    assert periods.period_of_scope('default', '2025-10') == '2025-10'
    assert periods.period_of_scope(None, '2025-10') == '2025-10'
    scope = json.dumps([['setFilterConditions:f1', {'value': '2025-10'}]])
    assert periods.period_of_scope(scope, '') == '2025-10'
    scope = json.dumps([['setFilterConditions:f1', {'label': '2025年10月'}]])
    assert periods.period_of_scope(scope, '') == '2025-10'
    scope = json.dumps([['setButtonGrainSelection:g1', {'value': '2025'}]])
    assert periods.period_of_scope(scope, '') == '2025'


# ---------------------------------------------------------------- 合并队列

def _collect_claim(store, scope='scope-1'):
    store.ensure_refresh_state(scope, next_check=time.time() - 1)
    claim = store.claim_refresh_info(scope, lease=60)
    assert claim and claim['job_id']
    return claim


def test_running_scope_collects_one_pending_instead_of_dropping_the_request(tmp_path):
    store = Store(tmp_path / 'queue.sqlite3')
    claim = _collect_claim(store)
    assert store.request_refresh('scope-1') is False  # no second task queued
    state = store.refresh_state('scope-1')
    assert state['status'] == 'running'
    assert int(state['pending']) == 1
    assert state['job_id'] == claim['job_id']
    # A second request must not create a second queued task.
    assert store.request_refresh('scope-1', now=time.time() + 5) is False
    state = store.refresh_state('scope-1')
    assert int(state['pending']) == 1
    assert state['pending_since'] >= time.time() - 1


def test_pending_state_carries_the_latest_request_time(tmp_path):
    store = Store(tmp_path / 'queue.sqlite3')
    _collect_claim(store)
    store.request_refresh('scope-1', now=1000.0)
    store.request_refresh('scope-1', now=1234.0)
    state = store.refresh_state('scope-1')
    assert float(state['pending_since']) == 1234.0


def test_finishing_with_pending_schedules_an_immediate_recheck(tmp_path):
    store = Store(tmp_path / 'queue.sqlite3')
    claim = _collect_claim(store)
    store.request_refresh('scope-1')
    assert store.finish_refresh('scope-1', claim['job_id'], claim['generation'], 'published',
                                next_check=time.time() + 900)
    state = store.refresh_state('scope-1')
    assert state['status'] == 'waiting'
    assert int(state['pending']) == 0
    assert state['next_check'] <= time.time() + 1
    assert 'scope-1' in store.due_refresh_scopes(time.time() + 1)


def test_queue_stats_report_pending_requests(tmp_path):
    store = Store(tmp_path / 'queue.sqlite3')
    _collect_claim(store)
    store.request_refresh('scope-1')
    assert store.refresh_queue_stats(now=time.time())['pendingCount'] == 1


# ------------------------------------------------- 历史冻结不进入调度队列

def test_frozen_scope_is_not_due_but_still_readable(tmp_path):
    store = Store(tmp_path / 'queue.sqlite3')
    store.ensure_refresh_state('scope-1', next_check=time.time() - 1)
    claim = store.claim_refresh_info('scope-1', lease=60)
    assert store.finish_refresh('scope-1', claim['job_id'], claim['generation'],
                                'frozen', next_check=0)
    state = store.refresh_state('scope-1')
    assert state['status'] == 'frozen'
    assert 'scope-1' not in store.due_refresh_scopes(time.time() + 3600)


# ---------------------------------------------------------- 按环节独立刷新

class Config:
    base_url = 'http://ap.example/api/gateway2'
    batch_mode = 'individual'
    receipt_ttl = 3600

    def headers(self):
        return {'X-App-Id': 'period-test'}

    def identity(self):
        return 'source-period'


def _query(metric, value=1):
    return {'analysisConfig': {'indicators': [{'identifierCode': metric}]},
            'commonConfig': {'filters': {'logic': 'AND', 'children': []},
                             'pagination': {'pageNum': 1, 'pageSize': 10}},
            'expected': value}


def _two_stage_page(tmp_path, ui_scope='default'):
    cfg = Config()
    store = Store(tmp_path / 'history.sqlite3')
    shipment_q = _query('YWLN_M0036')
    opportunity_q = _query('YWLN_M0022')
    shipment = store.save_ap_result(1, 'analysis', shipment_q, {'value': 19.02},
                                    cfg.receipt_ttl, cfg.identity(), transport_identity(cfg))
    opportunity = store.save_ap_result(1, 'analysis', opportunity_q, {'value': 103.01},
                                       cfg.receipt_ttl, cfg.identity(), transport_identity(cfg))
    helmet = store.save_ap_result(1, 'helmet', {'flowCode': 'SALES_CALIBER'}, {'nodes': []},
                                  cfg.receipt_ttl, cfg.identity(), transport_identity(cfg))
    records = [shipment, opportunity, helmet]
    fingerprint = page_fingerprint(records)
    ids = {}
    for stage, metric in (('shipment', 'YWLN_M0036'), ('opportunity', 'YWLN_M0022')):
        context = dict(id=1, page='analysis', stage=stage, engine='main', dataSource='ap',
                       dataIdentity=cfg.identity(), dataFingerprint=fingerprint,
                       period='2025-10', department='全部产品部',
                       chartQueries=[json.dumps(_query(metric), sort_keys=True)])
        item = store.create_analysis('old-' + stage, context)
        store.update_analysis(item['id'], status='limited',
                              result=dict(summary='old ' + stage, cardContract=CONTRACT),
                              evidence={'facts': [], 'records': [], 'evidence': []})
        ids[stage] = item['id']
    page = build_page(PageRequest(id=1, page='analysis', uiScope=ui_scope,
                                  apReceiptIds=[shipment['id'], opportunity['id'], helmet['id']],
                                  analysisIds=ids),
                      store, cfg, data_source='ap')
    scope = page_scope(cfg, 1, 'analysis', ui_scope, 'ap')
    assert store.publish_page(scope, page)
    return store, cfg, page, (shipment_q, opportunity_q, shipment['id'], opportunity['id'])


def test_refresh_only_reanalyses_the_stage_whose_evidence_changed(tmp_path):
    store, cfg, page, (shipment_q, opportunity_q, _sid, _oid) = _two_stage_page(tmp_path)
    calls = []

    def start(body, resolved):
        calls.append(body)
        context = {**body, **resolved, 'stageName': body['stage'], 'sourceMode': 'service'}
        item = store.create_analysis('new-' + body['stage'], context)
        store.update_analysis(item['id'], status='limited',
                              result=dict(summary='new ' + body['stage'], cardContract=CONTRACT),
                              evidence={'facts': [], 'records': [], 'evidence': []})
        return store.get_analysis(item['id'])

    def query(identity, kind, payload):
        as_text = json.dumps(payload, sort_keys=True)
        if 'YWLN_M0022' in as_text:
            return {'value': 88.8}
        return {'value': 19.02}

    before = dict(page['items'])
    manager = RefreshManager(store, cfg, query, start, interval=900, poll=0.01, timeout=5)
    result = manager.refresh(page)
    assert result['status'] == 'published'
    assert [call['stage'] for call in calls] == ['opportunity']
    published = store.published_page(page_scope(cfg, 1, 'analysis', 'default', 'ap'))
    assert published['items']['shipment']['id'] == before['shipment']['id']
    assert published['items']['opportunity']['id'] != before['opportunity']['id']


def test_unchanged_stages_reuse_their_analysis_and_the_page_still_publishes(tmp_path):
    store, cfg, page, _queries = _two_stage_page(tmp_path)
    calls = []

    def start(body, resolved):
        calls.append(body)
        context = {**body, **resolved, 'stageName': body['stage'], 'sourceMode': 'service'}
        item = store.create_analysis('new-' + body['stage'], context)
        store.update_analysis(item['id'], status='limited',
                              result=dict(summary='new', cardContract=CONTRACT),
                              evidence={'facts': [], 'records': [], 'evidence': []})
        return store.get_analysis(item['id'])

    def query(identity, kind, payload):
        return {'value': 103.01} if 'YWLN_M0022' in json.dumps(payload) else {'value': 19.02}

    manager = RefreshManager(store, cfg, query, start, interval=900, poll=0.01, timeout=5)
    result = manager.refresh(page)
    assert result['status'] == 'published' and result['changed'] is False
    assert calls == []


def test_failed_refresh_keeps_the_last_publication(tmp_path):
    store, cfg, page, _queries = _two_stage_page(tmp_path)

    def fail(identity, kind, payload):
        raise RuntimeError('AP unavailable')

    manager = RefreshManager(store, cfg, fail, lambda *a, **k: None,
                             interval=900, poll=0.01, timeout=5)
    result = manager.refresh(page)
    assert result['status'] == 'retry_wait'
    published = store.published_page(page_scope(cfg, 1, 'analysis', 'default', 'ap'))
    assert published['version'] == page['version']


def test_historical_scope_is_frozen_after_a_successful_refresh(tmp_path, monkeypatch):
    monkeypatch.setenv('COCKPIT_ACTIVE_PERIOD', '2026-11')
    scope = json.dumps([['setFilterConditions:f1', {'value': '2025-10'}]])
    store, cfg, page, _queries = _two_stage_page(tmp_path, ui_scope=scope)
    def query(identity, kind, payload):
        return {'value': 103.01} if 'YWLN_M0022' in json.dumps(payload) else {'value': 19.02}

    manager = RefreshManager(store, cfg, query, lambda *a, **k: None,
                             interval=900, poll=0.01, timeout=5)
    result = manager.refresh(page)
    assert result['status'] == 'frozen'
    state = store.refresh_state(page_scope(cfg, 1, 'analysis', scope, 'ap'))
    assert state['status'] == 'frozen'
    assert float(state['next_check']) == 0


def test_frozen_preheat_target_is_not_requeued_by_the_scheduler(tmp_path):
    from bi_agent.cockpit.refresh import RefreshScheduler, preheat_target_scope
    store = Store(tmp_path / 'scheduler.sqlite3')
    manager = RefreshManager(store, Config(), lambda *a, **k: {}, lambda *a, **k: None,
                             interval=900, poll=0.01, timeout=5)
    scheduler = RefreshScheduler(manager, store, scan_seconds=2)
    scope = preheat_target_scope(1, 'analysis', 'shipment')
    store.ensure_refresh_state(scope, next_check=0)
    store.set_refresh_state(scope, 'frozen', next_check=0)
    scheduler._seed({}, time.time(), {}, {scope: (1, 'analysis', 'shipment')}, [])
    state = store.refresh_state(scope)
    assert state['status'] == 'frozen'
    assert float(state['next_check']) == 0


def test_scheduler_seeds_a_historical_page_scope_as_frozen(tmp_path, monkeypatch):
    from bi_agent.cockpit.refresh import RefreshScheduler
    monkeypatch.setenv('COCKPIT_ACTIVE_PERIOD', '2026-11')
    scope_json = json.dumps([['setFilterConditions:f1', {'value': '2025-10'}]])
    store, cfg, page, _queries = _two_stage_page(tmp_path, ui_scope=scope_json)
    manager = RefreshManager(store, cfg, lambda *a, **k: {}, lambda *a, **k: None,
                             interval=900, poll=0.01, timeout=5)
    scheduler = RefreshScheduler(manager, store, scan_seconds=2, scope_limit=1)
    scheduler.run_once(now=time.time())
    state = store.refresh_state(page_scope(cfg, 1, 'analysis', scope_json, 'ap'))
    assert state['status'] == 'frozen'
    assert float(state['next_check']) == 0
