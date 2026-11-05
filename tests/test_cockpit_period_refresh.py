"""按期间缓存的刷新策略、合并队列与按环节刷新（第一阶段）。

这些用例先于实现编写：期间分类、pending 合并、按环节复用都必须在这里成立，
再向 ``bi_agent/cockpit`` 落地实现。
"""
import datetime as dt
import json
import time
from unittest.mock import patch

import pytest

from bi_agent.cockpit.cards import CONTRACT
from bi_agent.cockpit.page_cache import (PageRequest, build_page, page_fingerprint,
                                         page_scope, transport_identity)
from bi_agent.cockpit.refresh import RefreshManager
from bi_agent.cockpit.store import Store


NOW = dt.datetime(2026, 11, 5, 10, 0, 0)


@pytest.fixture(autouse=True)
def _default_active_period(monkeypatch):
    """Keep the delivered 2025-10 demo period active unless a test overrides it."""
    monkeypatch.setenv('COCKPIT_ACTIVE_PERIOD', '2025-10')
    monkeypatch.delenv('COCKPIT_PERIOD_MODE', raising=False)


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


def test_finishing_with_pending_requeues_within_the_minimum_gap(tmp_path, monkeypatch):
    monkeypatch.setenv('COCKPIT_REFRESH_MIN_RECHECK_SECONDS', '30')
    store = Store(tmp_path / 'queue.sqlite3')
    claim = _collect_claim(store)
    store.request_refresh('scope-1')
    assert store.finish_refresh('scope-1', claim['job_id'], claim['generation'], 'published',
                                next_check=time.time() + 900)
    state = store.refresh_state('scope-1')
    assert state['status'] == 'waiting'
    assert int(state['pending']) == 0
    assert time.time() + 29 <= state['next_check'] <= time.time() + 31
    assert 'scope-1' in store.due_refresh_scopes(time.time() + 31)


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
                       sourceMode='service', dataIdentity=cfg.identity(),
                       dataFingerprint=fingerprint,
                       period='2025-10', department='全部产品部',
                       chartQueries=[json.dumps(_query(metric), sort_keys=True)])
        item = store.create_analysis('old-' + stage, context)
        store.update_analysis(item['id'], status='limited',
                              result=dict(summary='old ' + stage, cardContract=CONTRACT),
                              evidence={'facts': [], 'records': [], 'evidence': []})
        store.publish(item['id'])
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


def test_frozen_preheat_target_resumes_when_its_period_is_active(tmp_path):
    from bi_agent.cockpit.refresh import RefreshScheduler, preheat_target_scope
    store = Store(tmp_path / 'scheduler.sqlite3')
    manager = RefreshManager(store, Config(), lambda *a, **k: {}, lambda *a, **k: None,
                             interval=900, poll=0.01, timeout=5)
    scheduler = RefreshScheduler(manager, store, scan_seconds=2)
    scope = preheat_target_scope(1, 'analysis', 'shipment')
    store.ensure_refresh_state(scope, next_check=0)
    store.set_refresh_state(scope, 'frozen', next_check=0)
    now = time.time()
    scheduler._seed({}, now, {}, {scope: (1, 'analysis', 'shipment')}, [])
    state = store.refresh_state(scope)
    assert state['status'] == 'waiting'
    assert state['next_check'] > now


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


# ------------------------------------------------- 验收补测（连续刷新/恢复/退避）

def _manager(store, cfg, query, start, **kwargs):
    return RefreshManager(store, cfg, query, start, interval=kwargs.pop('interval', 900),
                          poll=0.01, timeout=5, **kwargs)


def test_three_consecutive_refreshes_keep_publishing(tmp_path, monkeypatch):
    monkeypatch.setenv('COCKPIT_ACTIVE_PERIOD', '2025-10')
    store, cfg, page, _q = _two_stage_page(tmp_path)
    calls = []

    def start(body, resolved):
        calls.append(body['stage'])
        context = {**body, **resolved, 'stageName': body['stage'], 'sourceMode': 'service'}
        item = store.create_analysis('new-' + body['stage'], context)
        store.update_analysis(item['id'], status='limited',
                              result=dict(summary='new', cardContract=CONTRACT),
                              evidence={'facts': [], 'records': [], 'evidence': []})
        return store.get_analysis(item['id'])

    def query(identity, kind, payload):
        text = json.dumps(payload, sort_keys=True)
        return {'value': 88.8} if 'YWLN_M0022' in text else {'value': 19.02}

    manager = _manager(store, cfg, query, start)
    current = page
    scope = page_scope(cfg, 1, 'analysis', 'default', 'ap')
    for round_index in range(3):
        if round_index:
            assert store.request_refresh(scope, now=time.time())
        result = manager.refresh(current)
        assert result['status'] == 'published', (round_index, result)
        current = store.published_page(page_scope(cfg, 1, 'analysis', 'default', 'ap'))
    # Only the first round may call the model: evidence never changed again.
    assert calls == ['opportunity']


def test_frozen_scope_resumes_when_it_becomes_current_again(tmp_path, monkeypatch):
    from bi_agent.cockpit.refresh import RefreshScheduler
    monkeypatch.setenv('COCKPIT_ACTIVE_PERIOD', '2026-11')
    scope_json = json.dumps([['setFilterConditions:f1', {'value': '2025-10'}]])
    store, cfg, page, _q = _two_stage_page(tmp_path, ui_scope=scope_json)
    scope = page_scope(cfg, 1, 'analysis', scope_json, 'ap')
    manager = _manager(store, cfg, lambda *a, **k: {}, lambda *a, **k: None)
    scheduler = RefreshScheduler(manager, store, scan_seconds=2, scope_limit=1)
    scheduler.run_once(now=time.time())
    assert store.refresh_state(scope)['status'] == 'frozen'
    monkeypatch.setenv('COCKPIT_ACTIVE_PERIOD', '2025-10')
    scheduler.run_once(now=time.time())
    state = store.refresh_state(scope)
    assert state['status'] != 'frozen'
    assert float(state['next_check']) > 0


def test_pending_does_not_skip_failure_backoff(tmp_path):
    store = Store(tmp_path / 'queue.sqlite3')
    claim = _collect_claim(store)
    store.request_refresh('scope-1')
    now = time.time()
    store.finish_refresh('scope-1', claim['job_id'], claim['generation'], 'retry_wait',
                         next_check=now + 300, error='AP unavailable')
    state = store.refresh_state('scope-1')
    assert state['status'] == 'waiting'
    assert state['next_check'] >= now + 300


def test_pending_does_not_skip_the_minimum_recheck_interval(tmp_path, monkeypatch):
    monkeypatch.setenv('COCKPIT_REFRESH_MIN_RECHECK_SECONDS', '90')
    store = Store(tmp_path / 'queue.sqlite3')
    claim = _collect_claim(store)
    store.request_refresh('scope-1')
    now = time.time()
    store.finish_refresh('scope-1', claim['job_id'], claim['generation'], 'published',
                         next_check=now + 900)
    state = store.refresh_state('scope-1')
    assert state['next_check'] >= now + 89


def test_pending_never_unfreezes_a_frozen_scope(tmp_path):
    store = Store(tmp_path / 'queue.sqlite3')
    claim = _collect_claim(store)
    store.request_refresh('scope-1')
    now = time.time()
    store.finish_refresh('scope-1', claim['job_id'], claim['generation'], 'frozen', next_check=0)
    state = store.refresh_state('scope-1')
    assert state['status'] == 'frozen'
    assert float(state['next_check']) == 0


# ------------------------------------------------------- 期间模式与边界

def test_live_mode_uses_business_timezone_month(monkeypatch):
    from bi_agent.cockpit import periods
    monkeypatch.delenv('COCKPIT_ACTIVE_PERIOD', raising=False)
    monkeypatch.delenv('COCKPIT_PERIOD_MODE', raising=False)
    monkeypatch.setenv('COCKPIT_BUSINESS_TIMEZONE', 'Asia/Shanghai')
    value = periods.active_period(dt.datetime(2026, 12, 1, 0, 30))
    assert value == '2026-12'


def test_backfill_mode_requires_an_explicit_period(monkeypatch):
    from bi_agent.cockpit import periods
    monkeypatch.setenv('COCKPIT_PERIOD_MODE', 'backfill')
    monkeypatch.setenv('COCKPIT_ACTIVE_PERIOD', '2025-10')
    assert periods.active_period(dt.datetime(2026, 12, 1)) == '2025-10'


def test_grace_days_environment_variable_is_honoured(monkeypatch):
    from bi_agent.cockpit import periods
    monkeypatch.setenv('COCKPIT_PERIOD_GRACE_DAYS', '0')
    policy = periods.policy_for('2026-10', now=dt.datetime(2026, 11, 2, 9),
                                active='2026-11', interval=900)
    assert policy['kind'] == 'historical'
    assert policy['recheckAfter'] is None


def test_previous_periods_cover_month_and_year_across_new_year(monkeypatch):
    from bi_agent.cockpit import periods
    monkeypatch.setenv('COCKPIT_PERIOD_GRACE_DAYS', '7')
    assert periods.policy_for('2026-12', now=dt.datetime(2027, 1, 3),
                              active='2027-01')['kind'] == 'grace'
    assert periods.policy_for('2026', now=dt.datetime(2027, 1, 3),
                              active='2027-01')['kind'] == 'grace'


# ----------------------------------------------------------- 期间目录与预热

def test_period_catalog_reads_the_explicit_preheat_list(monkeypatch):
    from bi_agent.cockpit import periods
    monkeypatch.setenv('COCKPIT_PREHEAT_PERIODS', '2025-09, 2025年8月,2025-09')
    assert periods.period_catalog(now=dt.datetime(2025, 10, 5, 9)) == [
        '2025-10', '2025', '2025-09', '2025-08']
    monkeypatch.delenv('COCKPIT_PREHEAT_PERIODS')
    assert periods.period_catalog(now=dt.datetime(2025, 10, 20, 9)) == [
        '2025-10', '2025']


def test_period_catalog_follows_the_active_month_without_configuration(monkeypatch):
    from bi_agent.cockpit import periods
    monkeypatch.setenv('COCKPIT_ACTIVE_PERIOD', '2026-11')
    assert periods.period_catalog(now=dt.datetime(2026, 11, 5, 9)) == [
        '2026-11', '2026', '2026-10']


def test_period_coverage_separates_ready_and_missing(tmp_path, monkeypatch):
    from bi_agent.cockpit.refresh import period_coverage
    store, cfg, page, _q = _two_stage_page(tmp_path)
    coverage = period_coverage(store, ['2025-10', '2025-09'])
    assert coverage['total'] == 2 * 2 * 5
    assert coverage['ready'] >= 2  # shipment + opportunity of 2025-10
    assert coverage['missing'] > 0
    by_period = {row['period'] for row in coverage['periods'] if row['status'] == 'ready'}
    assert by_period == {'2025-10'}


def test_preheat_period_publishes_when_a_plan_for_that_period_exists(tmp_path):
    store, cfg, page, _q = _two_stage_page(tmp_path)
    manager = _manager(store, cfg, lambda i, k, p: {'value': 19.02},
                       _analysis_factory_factory(store))
    result = manager.preheat_period(1, 'analysis', 'shipment', '2025-10')
    assert result['status'] in {'published', 'frozen'}
    assert result['period'] == '2025-10'


def test_preheat_period_generates_a_plan_for_an_unseen_period(tmp_path):
    store, cfg, page, _q = _two_stage_page(tmp_path)
    calls = []
    manager = _manager(store, cfg, lambda i, k, p: {'value': 1},
                       _analysis_factory_factory(store, calls))
    result = manager.preheat_period(1, 'analysis', 'shipment', '2024-01')
    assert result['status'] in {'published', 'frozen'}
    assert calls
    assert (1, 'shipment', '2024-01') in store.published_stage_periods()


def _analysis_factory_factory(store, calls=None):
    calls = [] if calls is None else calls

    def start(body, resolved):
        calls.append(body['stage'])
        context = {**body, **resolved, 'stageName': body['stage'], 'sourceMode': 'service'}
        item = store.create_analysis('new-' + body['stage'], context)
        store.update_analysis(item['id'], status='limited',
                              result=dict(summary='new', cardContract=CONTRACT),
                              evidence={'facts': [], 'records': [], 'evidence': []})
        return store.get_analysis(item['id'])
    return start


def _period_analysis(store, period, *, identity=1, stage='shipment',
                     data_identity='source-period-test'):
    """Create a deliverable analysis for period-index read/coverage tests."""
    context = dict(id=identity, engine='main', page='analysis', stage=stage,
                   source='service', period=period, department='全部产品部',
                   filters={}, repositoryId='', chartSnapshotId='release',
                   chartQueries=[], dataSource='ap', dataIdentity=data_identity,
                   dataFingerprint='fingerprint-' + period, sourceMode='service')
    item = store.create_analysis('period-' + period + '-' + stage, context)
    store.update_analysis(item['id'], status='limited', result=dict(
        summary='period ' + period, causes=[], recommendations=[], limitations=[],
        cardContract=CONTRACT), evidence={'facts': [], 'records': [], 'evidence': []})
    return item['id']


# ------------------------------------- 验收第二轮：期间索引/计划/退避/解析

def test_view_scope_separates_two_months():
    from bi_agent.cockpit.publications import view_scope
    base = dict(id=1, engine='main', page='analysis', stage='shipment',
                chartSnapshotId='release', dataSource='ap', dataIdentity='ap-1',
                filters={}, sourceMode='service')
    assert view_scope(dict(base, period='2025-09')) != view_scope(dict(base, period='2025-10'))


def test_period_publication_index_keeps_every_month(tmp_path):
    store = Store(tmp_path / 'periods.sqlite3')
    a09 = _period_analysis(store, '2025-09')
    a10 = _period_analysis(store, '2025-10')
    store.publish_period(1, '2025-09', 'shipment', '{"filters":[]}', a09, 'v-09')
    store.publish_period(1, '2025-10', 'shipment', '{"filters":[]}', a10, 'v-10')
    assert store.published_period(1, '2025-09', 'shipment', '{"filters":[]}')['analysis_id'] == a09
    assert store.published_period(1, '2025-10', 'shipment', '{"filters":[]}')['analysis_id'] == a10
    assert (1, 'shipment', '2025-09') in store.published_stage_periods()
    assert (1, 'shipment', '2025-10') in store.published_stage_periods()


def test_seed_periods_keeps_retry_backoff(tmp_path):
    from bi_agent.cockpit.refresh import RefreshScheduler, period_target_scope
    store = Store(tmp_path / 'scheduler.sqlite3')
    manager = _manager(store, Config(), lambda *a, **k: {}, lambda *a, **k: None)
    scheduler = RefreshScheduler(manager, store, scan_seconds=2)
    scope = period_target_scope(1, 'analysis', 'shipment', '2025-11')
    later = time.time() + 600
    store.ensure_refresh_state(scope, next_check=later)
    store.set_refresh_state(scope, 'retry_wait', next_check=later, error='AP down')
    scheduler._seed_periods(time.time(), {scope: (1, 'analysis', 'shipment', '2025-11')})
    state = store.refresh_state(scope)
    assert state['status'] == 'retry_wait'
    assert state['next_check'] >= later - 1


def test_period_plan_substitutes_the_requested_date_range(tmp_path):
    from bi_agent.cockpit.refresh import RefreshManager
    store = Store(tmp_path / 'plan.sqlite3')
    manager = _manager(store, Config(), lambda *a, **k: {}, lambda *a, **k: None)
    template = {'analysisConfig': {'indicators': [{'identifierCode': 'YWLN_M0036'}]},
                'commonConfig': {'filters': {'logic': 'AND', 'children': [
                    {'identifierCode': 'YWLN_D044',
                     'operator': {'code': 'BETWEEN', 'type': 'DATE'},
                     'valueType': 'ABSOLUTE',
                     'value': ['2025-01-01', '2025-12-31']}]}}}
    with patch('bi_agent.cockpit.refresh.delivered_component_requests',
               return_value=[template]), \
         patch('bi_agent.cockpit.refresh.delivered_stage_requests', return_value=[]):
        _context, requests = manager._stage_requests(1, 'analysis', 'shipment', period='2024-03')
    assert requests
    item = requests[0]['commonConfig']['filters']['children'][0]
    assert item['value'] == ['2024-03-01', '2024-03-31']


def test_period_plan_adds_the_date_filter_when_the_template_has_none(tmp_path):
    from bi_agent.cockpit.refresh import RefreshManager
    store = Store(tmp_path / 'plan.sqlite3')
    manager = _manager(store, Config(), lambda *a, **k: {}, lambda *a, **k: None)
    undated = {'analysisConfig': {'indicators': [{'identifierCode': 'YWLN_M0036'}]},
               'commonConfig': {'filters': {'logic': 'AND', 'children': []}}}
    with patch('bi_agent.cockpit.refresh.delivered_component_requests', return_value=[undated]), \
         patch('bi_agent.cockpit.refresh.delivered_stage_requests', return_value=[]):
        _context, requests = manager._stage_requests(1, 'analysis', 'shipment', period='2024-03')
    assert requests
    item = requests[0]['commonConfig']['filters']['children'][0]
    assert item['identifierCode'] == 'YWLN_D044'
    assert item['value'] == ['2024-03-01', '2024-03-31']


def test_period_plan_wraps_an_or_root_with_an_and_date_condition(tmp_path):
    from bi_agent.cockpit.refresh import RefreshManager
    store = Store(tmp_path / 'plan.sqlite3')
    manager = _manager(store, Config(), lambda *a, **k: {}, lambda *a, **k: None)
    customer = {'identifierCode': 'YWLN_D006', 'operator': {'code': 'EQ'},
                'valueType': 'ABSOLUTE', 'value': '客户A'}
    template = {'analysisConfig': {'indicators': [{'identifierCode': 'YWLN_M0036'}]},
                'commonConfig': {'filters': {'logic': 'OR', 'children': [customer]}}}
    with patch('bi_agent.cockpit.refresh.delivered_component_requests',
               return_value=[template]), \
         patch('bi_agent.cockpit.refresh.delivered_stage_requests', return_value=[]):
        _context, requests = manager._stage_requests(1, 'analysis', 'shipment', period='2024-03')
    filters = requests[0]['commonConfig']['filters']
    assert filters['logic'] == 'AND'
    assert filters['children'][0] == {'logic': 'OR', 'children': [customer]}
    assert filters['children'][1]['identifierCode'] == 'YWLN_D044'
    assert filters['children'][1]['value'] == ['2024-03-01', '2024-03-31']


def test_period_plan_refuses_an_unsupported_existing_date_operator(tmp_path):
    from bi_agent.cockpit.refresh import RefreshManager
    store = Store(tmp_path / 'plan.sqlite3')
    manager = _manager(store, Config(), lambda *a, **k: {}, lambda *a, **k: None)
    template = {'analysisConfig': {'indicators': [{'identifierCode': 'YWLN_M0036'}]},
                'commonConfig': {'filters': {'logic': 'AND', 'children': [
                    {'identifierCode': 'YWLN_D044',
                     'operator': {'code': 'EQUAL', 'type': 'DATE'},
                     'valueType': 'ABSOLUTE', 'value': ['2025-01-01', '2025-12-31']}]}}}
    with patch('bi_agent.cockpit.refresh.delivered_component_requests',
               return_value=[template]), \
         patch('bi_agent.cockpit.refresh.delivered_stage_requests', return_value=[]):
        _context, requests = manager._stage_requests(1, 'analysis', 'shipment', period='2024-03')
    assert requests == []


def test_period_plan_refuses_a_payload_it_cannot_date_scope(tmp_path):
    from bi_agent.cockpit.refresh import RefreshManager
    store = Store(tmp_path / 'plan.sqlite3')
    manager = _manager(store, Config(), lambda *a, **k: {}, lambda *a, **k: None)
    unusable = {'analysisConfig': {'indicators': [{'identifierCode': 'YWLN_M0036'}]}}
    with patch('bi_agent.cockpit.refresh.delivered_component_requests', return_value=[unusable]), \
         patch('bi_agent.cockpit.refresh.delivered_stage_requests', return_value=[]):
        _context, requests = manager._stage_requests(1, 'analysis', 'shipment', period='2024-03')
    assert requests == []


def test_period_state_prefers_the_year_grain_over_a_stale_month():
    from bi_agent.cockpit import periods
    scope = json.dumps([
        ['setFilterConditions:f1', {'value': '2025-10'}],
        ['setButtonGrainSelection:g1', 'YEAR'],
        ['setFilterConditions:f2', {'value': '2026'}],
    ])
    state = periods.period_state(scope, '')
    assert state['periodType'] == 'year'
    assert state['period'] == '2026'


def test_two_months_stay_independently_readable(tmp_path):
    store, cfg, page, _q = _two_stage_page(tmp_path)
    sept = _period_analysis(store, '2025-09')
    october = _period_analysis(store, '2025-10')
    store.publish_period(1, '2025-09', 'shipment', {}, sept, 'view-sept')
    store.publish_period(1, '2025-10', 'shipment', {}, october, 'view-oct')
    assert store.published_period(1, '2025-09', 'shipment', {})['analysis_id'] == sept
    assert store.published_period(1, '2025-10', 'shipment', {})['view_key'] == 'view-oct'
    # The page's own default view is untouched by the extra period.
    current = store.published_page(page_scope(cfg, 1, 'analysis', 'default', 'ap'))
    assert current['items']['shipment']['id'] == page['items']['shipment']['id']


def test_restart_keeps_finished_periods_without_requeueing(tmp_path):
    from bi_agent.cockpit.refresh import RefreshScheduler, period_target_scope
    path = tmp_path / 'restart.sqlite3'
    store = Store(path)
    analysis_id = _period_analysis(store, '2025-10')
    store.publish_period(1, '2025-10', 'shipment', {}, analysis_id, 'view-oct')
    manager = _manager(store, Config(), lambda *a, **k: {}, lambda *a, **k: None)
    scheduler = RefreshScheduler(manager, store, scan_seconds=2)
    scope = period_target_scope(1, 'analysis', 'shipment', '2025-10')
    scheduler._seed_periods(time.time(), {scope: (1, 'analysis', 'shipment', '2025-10')})
    reopened = Store(path)
    assert (1, 'shipment', '2025-10') in reopened.published_stage_periods()
    state = reopened.refresh_state(scope)
    assert state['status'] not in {'waiting', 'queued'} or state['next_check'] > time.time()


def test_period_coverage_excludes_an_old_config_version(tmp_path):
    from bi_agent.cockpit.refresh import period_coverage
    store, _cfg, _page, _q = _two_stage_page(tmp_path)
    before = period_coverage(store, ['2025-10'])
    assert before['ready'] >= 2
    with patch('bi_agent.cockpit.publications.config_version', return_value='rotated-config'):
        after = period_coverage(store, ['2025-10'])
    assert after['ready'] == 0


def test_unvisited_month_is_preheated_from_a_generated_plan(tmp_path):
    store = Store(tmp_path / 'plan.sqlite3')
    template = {'analysisConfig': {'indicators': [{'identifierCode': 'YWLN_M0036'}]},
                'commonConfig': {'filters': {'logic': 'AND', 'children': [
                    {'identifierCode': 'YWLN_D044',
                     'operator': {'code': 'BETWEEN', 'type': 'DATE'},
                     'valueType': 'ABSOLUTE',
                     'value': ['2025-01-01', '2025-12-31']}]}}}
    calls = []

    def start(body, resolved):
        calls.append(dict(body))
        context = {**body, **resolved, 'stageName': body['stage'], 'sourceMode': 'service'}
        item = store.create_analysis('new-' + body['stage'], context)
        store.update_analysis(item['id'], status='limited',
                              result=dict(summary='new', cardContract=CONTRACT),
                              evidence={'facts': [], 'records': [], 'evidence': []})
        return store.get_analysis(item['id'])

    manager = _manager(store, Config(), lambda i, k, p: {'value': 1}, start)
    with patch('bi_agent.cockpit.refresh.delivered_component_requests',
               return_value=[template]), \
         patch('bi_agent.cockpit.refresh.delivered_stage_requests', return_value=[]):
        result = manager.preheat_period(1, 'analysis', 'shipment', '2024-03')
    assert result['status'] in {'published', 'frozen'}
    assert calls and calls[0]['period'] == '2024-03'
    assert (1, 'shipment', '2024-03') in store.published_stage_periods()
