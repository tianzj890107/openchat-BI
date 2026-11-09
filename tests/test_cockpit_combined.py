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
                                    'period': '2025-10',
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


def test_card_context_period_must_match_even_when_ap_dates_match(tmp_path):
    store = Store(tmp_path/'db.sqlite');cards = fixture_cards(store)
    cards['shipment']['context']['period'] = '2025-09'
    body = cached_combined_request(store, 1, cards, period='2025-10')
    assert len(body['apReceiptIds']) == 2
    assert body['period'] == '2025-10'
    assert body['clarifications']['coverage'] == 'opportunity,order'


def test_requested_period_requires_two_matching_stage_cards(tmp_path):
    store = Store(tmp_path/'db.sqlite');cards = fixture_cards(store)
    cards['order']['context']['period'] = '2025-09'
    cards['shipment']['context']['period'] = '2025-09'
    with pytest.raises(ValueError, match='至少需要两个环节'):
        cached_combined_request(store, 1, cards, period='2025-10')


def test_missing_shipment_card_keeps_the_other_same_period_stages(tmp_path):
    store = Store(tmp_path/'db.sqlite');cards = fixture_cards(store)
    cards.pop('shipment')
    body = cached_combined_request(store, 1, cards)
    assert len(body['apReceiptIds']) == 2
    assert 'opportunity,order' in body['clarifications']['coverage']


def test_other_identity_cannot_be_reused(tmp_path):
    store = Store(tmp_path/'db.sqlite');cards = fixture_cards(store)
    with pytest.raises(ValueError):
        cached_combined_request(store, 2, cards)


def test_quotation_uses_helmet_state_not_risk_kpis(tmp_path):
    from bi_agent.cockpit.combined import cached_quotation_request
    store = Store(tmp_path/'db.sqlite');cards = fixture_cards(store)
    q = query('YWLN_M0031');q['analysisConfig']['dimensions'] = [{'identifierCode': 'YWLN_D021'}]
    store.save_ap_result(1, 'analysis', q, {'result': {}}, 1, 'conn')
    risk = query('YWLN_M0137')
    store.save_ap_result(1, 'analysis', risk, {'result': {}}, 1, 'conn')
    card = {'context': {'id': 1, 'dataIdentity': 'conn', 'chartQueries': [json.dumps(risk)]}}
    body = cached_quotation_request(store, 1, card)
    assert len(body['apReceiptIds']) == 1
    assert json.loads(body['chartQueries'][0]) == q
    kept, excluded = filter_stage_selected({'status': {'request': q}, 'risk': {'request': risk}}, 'quotation')
    assert list(kept) == ['status']
    assert excluded == ['risk']


def test_compact_quotation_retains_only_the_status_row_fields():
    from bi_agent.cockpit.page_cache import compact_analysis
    item = {'context': {'stage': 'quotation'}, 'evidence': {'records': [{'data': {
        '报价办理状态[YWLN_D021]': 'normal_completed', '报价电量[YWLN_M0031]': 25.57,
        'unrelated': 'not needed'}}]}}
    data = compact_analysis(item)['evidence']['records'][0]['data']
    assert data == {'报价办理状态[YWLN_D021]': 'normal_completed', '报价电量[YWLN_M0031]': 25.57}


def test_policy_stage_preheat_is_scoped_to_saved_identity_and_queries(tmp_path):
    from bi_agent.cockpit.combined import cached_stage_request
    store=Store(tmp_path/'history.sqlite3');cards=fixture_cards(store)
    body=cached_stage_request(store,1,'shipment',cards['shipment'])
    assert len(body['apReceiptIds'])==1
    assert body['stage']=='shipment'
    assert body['clarifications']['deliveryPolicy']=='investigation-v1'
    with pytest.raises(ValueError):cached_stage_request(store,2,'shipment',cards['shipment'])
