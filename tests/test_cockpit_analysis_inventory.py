"""Persistent analysis inventory and model-analysis cadence."""
from pathlib import Path

from bi_agent.cockpit.store import Store


def _store(tmp_path):
    return Store(Path(tmp_path) / 'inventory.sqlite3')


def _seed(store, *, analyzed_at=1000.0, min_interval=1800):
    store.seed_analysis_inventory(
        'scope', identity=1, page='analysis', stage='shipment', period='2026-11',
        filters={}, result_id='analysis-1', result_kind='analysis', fingerprint='f1',
        data_as_of=900.0, analyzed_at=analyzed_at, min_interval=min_interval)


def test_analysis_inventory_table_persists_result_and_data_times(tmp_path):
    store = _store(tmp_path)
    _seed(store)
    row = store.analysis_inventory('scope')
    assert row['result_id'] == 'analysis-1'
    assert row['result_kind'] == 'analysis'
    assert row['fingerprint'] == 'f1'
    assert row['data_as_of'] == 900.0
    assert row['analyzed_at'] == 1000.0
    assert row['next_analysis_at'] == 2800.0


def test_changed_evidence_is_kept_as_one_latest_pending_version(tmp_path):
    store = _store(tmp_path)
    _seed(store)
    first = store.prepare_analysis(
        'scope', fingerprint='f2', data_as_of=1100, now=1100,
        min_interval=1800, coalesce_seconds=300)
    second = store.prepare_analysis(
        'scope', fingerprint='f3', data_as_of=1200, now=1200,
        min_interval=1800, coalesce_seconds=300)
    row = store.analysis_inventory('scope')
    assert first['allow'] is False
    assert second['allow'] is False
    assert row['status'] == 'pending'
    assert row['pending_fingerprint'] == 'f3'
    assert row['pending_data_as_of'] == 1200
    assert row['pending_since'] == 1100
    assert row['next_analysis_at'] == 2800


def test_changed_evidence_is_allowed_when_the_model_interval_is_due(tmp_path):
    store = _store(tmp_path)
    _seed(store)
    first = store.prepare_analysis(
        'scope', fingerprint='f2', data_as_of=2800, now=2800,
        min_interval=1800, coalesce_seconds=300)
    gate = store.prepare_analysis(
        'scope', fingerprint='f2', data_as_of=3100, now=3100,
        min_interval=1800, coalesce_seconds=300)
    assert first['allow'] is False
    assert gate['allow'] is True
    assert gate['reason'] == 'due'
    assert store.analysis_inventory('scope')['status'] == 'analyzing'


def test_coalescing_window_prevents_immediate_model_run(tmp_path):
    store = _store(tmp_path)
    _seed(store, analyzed_at=1000.0, min_interval=60)
    gate = store.prepare_analysis(
        'scope', fingerprint='f2', data_as_of=1100, now=1100,
        min_interval=60, coalesce_seconds=300)
    assert gate['allow'] is False
    assert gate['nextAnalysisAt'] == 1400


def test_record_result_clears_pending_and_starts_the_next_window(tmp_path):
    store = _store(tmp_path)
    _seed(store)
    store.prepare_analysis(
        'scope', fingerprint='f2', data_as_of=1100, now=1100,
        min_interval=1800, coalesce_seconds=300)
    row = store.record_analysis_inventory(
        'scope', result_id='analysis-2', result_kind='analysis', fingerprint='f2',
        data_as_of=2800, analyzed_at=2800, min_interval=1800,
        identity=1, page='analysis', stage='shipment', period='2026-11', filters={})
    assert row['result_id'] == 'analysis-2'
    assert row['status'] == 'current'
    assert row['pending_fingerprint'] == ''
    assert row['pending_since'] == 0
    assert row['next_analysis_at'] == 4600


def test_retry_and_reverted_evidence_do_not_reset_the_stock_silently(tmp_path):
    store = _store(tmp_path)
    _seed(store)
    store.prepare_analysis(
        'scope', fingerprint='f2', data_as_of=1100, now=1100,
        min_interval=1800, coalesce_seconds=300)
    store.mark_analysis_retry('scope', now=1200)
    retry = store.prepare_analysis(
        'scope', fingerprint='f2', data_as_of=1201, now=1201,
        min_interval=1800, coalesce_seconds=300)
    assert retry['allow'] is True
    reverted = store.mark_analysis_unchanged('scope', now=1300, latest_data_as_of=1300)
    assert reverted['status'] == 'current'
    assert reverted['pending_fingerprint'] == ''
    assert reverted['analyzed_at'] == 1000
