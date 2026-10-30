import json
import pytest
from bi_agent.cockpit.combined import cached_combined_request
from bi_agent.cockpit.store import Store
from bi_agent.cockpit.dashboard_source import filter_stage_selected


def query(code, start='2025-01-01'):
    return {'analysisConfig': {'indicators': [{'identifierCode': code}]},
            'commonConfig': {'filters': {'children': [{'identifierCode': 'YWLN_D044',
                'operator': {'type': 'DATE', 'code': 'BETWEEN'},
                'value': [start, '2025-12-31'], 'valueType': 'ABSOLUTE'}]}}}


def fixture_cards(store):
    cards = {}
    for stage, code in [('opportunity', 'YWLN_M0023'), ('order', 'YWLN_M0032'), ('shipment', 'YWLN_M0035')]:
        q = query(code)
        store.save_ap_result(1, 'analysis', q, {'result': {}}, 1, 'conn')
        cards[stage] = {'context': {'id': 1, 'dataIdentity': 'conn', 'department': '全部产品部',
                                    'chartQueries': [json.dumps(q)], 'unavailableQueries': []}}
    return cards


def test_cached_composite_uses_all_stages_without_querying(tmp_path):
    store = Store(tmp_path/'db.sqlite');cards = fixture_cards(store)
    body = cached_combined_request(store, 1, cards)
    assert body['stage'] == 'combined'
    assert len(body['apReceiptIds']) == 3
    assert len(body['chartQueries']) == 3
    kept, _ = filter_stage_selected({str(i): {'request': json.loads(q)} for i,q in enumerate(body['chartQueries'])}, 'combined')
    assert len(kept) == 3


def test_other_period_is_excluded(tmp_path):
    store = Store(tmp_path/'db.sqlite');cards = fixture_cards(store)
    cards['opportunity']['context']['chartQueries'] = [json.dumps(query('YWLN_M0023', '2024-01-01'))]
    body = cached_combined_request(store, 1, cards)
    assert len(body['apReceiptIds']) == 2


def test_other_identity_cannot_be_reused(tmp_path):
    store = Store(tmp_path/'db.sqlite');cards = fixture_cards(store)
    with pytest.raises(ValueError):
        cached_combined_request(store, 2, cards)
