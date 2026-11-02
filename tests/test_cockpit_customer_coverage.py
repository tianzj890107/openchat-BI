import pytest
from bi_agent.cockpit.customer_coverage import (BID, COUNT, CUSTOMER, HAS, MAX_CUSTOMERS,
                                               calculate, load, queries)
from bi_agent.cockpit.page_cache import compact_analysis


def responses(rows, total=3):
    return ({'result': {'rows': [{COUNT: {'value': total}}]}},
            {'result': {'rows': rows}})


def customer(key, has, bidding):
    return {CUSTOMER: {'identifierNumber': key, 'value': '相同名称'},
            HAS: {'value': has}, BID: {'value': bidding}}


def test_distinct_customer_ids_not_names_or_opportunity_rows():
    rows = [customer('a', '有商机', '否'), customer('b', '无商机', '否'),
            customer('c', '有商机', '是'), customer('a', '有商机', '否')]
    value = calculate(*responses(rows))
    assert value['totalCustomers'] == 3
    assert value['withOpportunityNotBidding'] == 1
    assert value['withoutOpportunity'] == 1


@pytest.mark.parametrize('rows,total,reason', [
    ([customer('a', True, False)], 10, 'UNIVERSE_MISMATCH'),
    ([customer(None, True, False)], 1, 'ID_MISSING'),
    ([customer('a', None, False)], 1, 'STATE_UNKNOWN'),
    ([customer('a', False, True)], 1, 'STATE_CONTRADICTED'),
    ([customer('a', True, True), customer('a', True, False)], 1, 'STATE_CONTRADICTED'),
    ([], None, 'COUNT_INVALID'),
    ([], -1, 'COUNT_INVALID'),
])
def test_missing_partial_and_conflicting_data_never_becomes_zero(rows, total, reason):
    with pytest.raises(ValueError, match=reason):
        calculate(*responses(rows, total))


def test_true_zero_and_truncated_result():
    assert calculate(*responses([], 0))['withoutOpportunity'] == 0
    a, b = responses([customer('a', True, False)], 1)
    b['pagination'] = {'total': 99}
    with pytest.raises(ValueError, match='TRUNCATED'):
        calculate(a, b)


def test_fixed_queries_preserve_filters_and_remove_pagination():
    filters = {'logic': 'AND', 'children': [{'identifierCode': 'YWLN_D044', 'value': ['2025-01-01','2025-12-31']}]}
    selected = {'q': {'request': {'analysisConfig': {'indicators': [{'identifierCode': COUNT}]},
                                 'commonConfig': {'filters': filters, 'pagination': {'pageSize': 10}}}}}
    total, detail = queries(selected)
    assert total['commonConfig'] == {'filters': filters}
    assert detail['commonConfig']['filters'] == filters
    assert detail['commonConfig']['pagination']['pageSize'] == MAX_CUSTOMERS
    assert [d['identifierCode'] for d in detail['analysisConfig']['dimensions']] == [CUSTOMER, HAS, BID]
    assert selected['q']['request']['commonConfig']['pagination']['pageSize'] == 10
    with pytest.raises(ValueError, match='SCOPE'):
        queries({})


def test_snapshot_does_not_query_live_or_fake_counts():
    def forbidden(*args):
        raise AssertionError('must not query')
    value = load({'stage': 'opportunity', 'snapshotId': 'dashboard-old'}, None, forbidden)
    assert value['status'] == 'unavailable'
    assert value['withoutOpportunity'] is None


def test_compaction_preserves_deterministic_customer_counts():
    counts = calculate(*responses([], 0))
    result = compact_analysis({'context': {'stage': 'opportunity'}, 'result': {'customerCoverage': counts}})
    assert result['result']['customerCoverage'] == counts


def test_background_queries_have_shared_budget_and_auditable_receipts(monkeypatch):
    selected = {'q': {'request': {'analysisConfig': {'indicators': [{'identifierCode': COUNT}]}}}}
    monkeypatch.setattr('bi_agent.cockpit.dashboard_source.receipt_material', lambda *a, **k: ('hash', selected))
    a, b = responses([customer('a', True, False)], 1)
    calls = []
    def read(identity, kind, query, **kwargs):
        calls.append((identity, kind, query, kwargs))
        return {'id': f'r{len(calls)}', 'createdAt': 100 + len(calls),
                'response': a if len(calls) == 1 else b}
    value = load({'stage': 'opportunity', 'snapshotId': 'ap-live', 'id': 2}, None, read)
    assert value['status'] == 'ready'
    assert value['receiptIds'] == ['r1', 'r2']
    assert value['observedAt'] == 101
    assert len(value['queryHash']) == 64
    assert calls[0][3]['_deadline'] == calls[1][3]['_deadline']


def test_upstream_failure_isolated_from_analysis_and_never_discloses_error(monkeypatch):
    selected = {'q': {'request': {'analysisConfig': {'indicators': [{'identifierCode': COUNT}]}}}}
    monkeypatch.setattr('bi_agent.cockpit.dashboard_source.receipt_material', lambda *a, **k: ('hash', selected))
    calls = []
    def read(*args, **kwargs):
        calls.append(args)
        raise RuntimeError('upstream private message')
    value = load({'stage': 'opportunity', 'snapshotId': 'ap-live', 'id': 1}, None, read)
    assert value['status'] == 'unavailable'
    assert value['reason'] == 'CUSTOMER_QUERY_FAILED'
    assert len(calls) == 1
    assert 'private' not in str(value)
