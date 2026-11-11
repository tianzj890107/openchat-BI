from copy import deepcopy
from datetime import date
from types import SimpleNamespace

from bi_agent.cockpit.opportunity_v2 import (
    _p0_cycle, _p2_cycle, apply_text_interpretation, build_card, collect,
    config_digest, config_version, default_ap_supplement, evaluate, load_config,
)


def _opportunity(**updates):
    value = dict(
        id='opp-1', name='测试商机', accountId='account-1', accountName='战略客户A',
        accountLevel='1', tier='strategic', productType='1', productName='电芯',
        stage='13', stageName='P2 方案推动', acneed='1', status='0', contract='not_confirmed',
        createdAt='2026-01-01', stage2End='2026-02-01', stage3End='2026-04-01',
        forecastAmount=10.0, forecastEnergy=5.0, orderCount=0, department='电芯产品部',
    )
    value.update(updates)
    return value


def _data(**updates):
    value = dict(
        period='2026', measurementDate='2026-11-11',
        targets=dict(amount=100.0, energy=100.0, byProduct={}, byAccount={}),
        opportunities=[], allOpportunities=[], accounts=[], bids=[], progress={},
        errors=[],
    )
    value.update(updates)
    return value


def test_v2_config_is_complete_and_rk07_has_no_contradictory_cause():
    config = load_config()
    assert config_version() == 'opportunity-v2-rules-1'
    assert len(config_digest()) == 64
    assert len(config['metrics']) == 25
    assert len(config['risks']) == 10
    assert len(config['causes']) == 8
    assert len(config['advice']) == 8
    assert config['links']['RK07']['causes'] == []
    assert config['links']['RK07']['advice'] == ['DS03']


def test_contract_confirmation_drives_signing_and_unknown_is_not_zero():
    opportunity = _opportunity()
    data = _data(opportunities=[opportunity], allOpportunities=[deepcopy(opportunity)],
                 accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic')])
    value = evaluate(data)
    assert value['metrics']['R02']['amount'] == 10.0
    assert value['metrics']['R02']['energy'] == 5.0
    assert 'RK02' in {risk['code'] for risk in value['risks']}

    known = _opportunity(contract='confirmed')
    known_data = _data(opportunities=[known], allOpportunities=[deepcopy(known)])
    assert evaluate(known_data)['metrics']['R02']['amount'] == 0.0
    assert evaluate(known_data)['metrics']['R02']['energy'] == 0.0


def test_account_level_zero_is_strategic_and_uses_the_same_customer_scope():
    account = dict(id='level-zero', name='战略客户零级', level='0', tier='strategic')
    value = evaluate(_data(accounts=[account], allOpportunities=[]))
    assert value['metrics']['R09']['count'] == 1
    assert any(risk['code'] == 'RK07' for risk in value['risks'])


def test_rk07_is_never_linked_to_the_contradictory_rc01_hypothesis():
    no_opportunity = dict(id='account-empty', name='无商机战略客户', level='1', tier='strategic')
    p0 = _opportunity(id='opp-p0', accountId='account-p0', tier='strategic', stage='11',
                      acneed='1', stage1End=None, forecastAmount=1.0, forecastEnergy=1.0)
    data = _data(
        targets=dict(amount=100.0, energy=100.0, byProduct={}, byAccount={}),
        opportunities=[p0], allOpportunities=[deepcopy(p0)],
        accounts=[no_opportunity, dict(id='account-p0', name='战略客户P0', level='1', tier='strategic')],
    )
    value = evaluate(data)
    assert 'RK07' in {risk['code'] for risk in value['risks']}
    assert all('RK07' not in cause['riskCodes'] for cause in value['result']['causes'])
    rk07_finding_ids = {finding['id'] for finding in value['result']['findings']
                        if finding['riskCode'] == 'RK07'}
    assert all(not (set(cause['findingIds']) & rk07_finding_ids)
               for cause in value['result']['causes'])


def test_dynamic_period_is_strict_and_excludes_invalid_times(monkeypatch):
    measured = date(2026, 11, 11)
    valid = _opportunity(createdAt='2026-01-01', stage='11', stage1End=None)
    assert _p0_cycle(valid, measured) > 0
    assert _p0_cycle(_opportunity(createdAt='2026-10-01', stage='11', stage1End=None), measured) == 41
    assert _p0_cycle(_opportunity(createdAt='2026-12-01', stage='11', stage1End=None), measured) is None
    assert _p0_cycle(_opportunity(createdAt='2026-01-01', stage='12', stage1End=None), measured) is None
    assert _p2_cycle(_opportunity(stage2End='2026-05-01', stage3End='2026-04-01'), measured) is None

    base = _data(targets=dict(amount=1000.0, energy=1000.0, byProduct={}, byAccount={}))
    rows = [
        _opportunity(id='a', createdAt='2026-01-01', stage='11', stage1End=None, contract='confirmed'),
        _opportunity(id='b', createdAt='2026-01-01', stage='11', stage1End=None, contract='confirmed'),
    ]
    base.update(opportunities=rows, allOpportunities=deepcopy(rows))
    equal = evaluate(base, measured=measured)
    assert equal['metrics']['R10']['count'] == 0
    assert 'RK10' not in {risk['code'] for risk in equal['risks']}

    import bi_agent.cockpit.opportunity_v2 as module
    cycles = {'a': 10, 'b': 10, 'c': 20}
    monkeypatch.setattr(module, '_p0_cycle', lambda opp, _measured: cycles[opp['id']])
    boundary = _data(targets=dict(amount=1000.0, energy=1000.0, byProduct={}, byAccount={}))
    boundary_rows = [dict(rows[0], id=key, contract='confirmed') for key in cycles]
    boundary.update(opportunities=boundary_rows, allOpportunities=deepcopy(boundary_rows))
    assert 'RK10' not in {risk['code'] for risk in evaluate(boundary, measured=measured)['risks']}


def test_ambiguous_bid_name_never_becomes_not_bidding():
    opportunity = dict(id='opp-1', name='同名项目', accountId='account-1', tier='strategic',
                       productType='1', stage='11', status='0', contract='not_confirmed',
                       createdAt='2026-01-01', forecastAmount=10.0, forecastEnergy=5.0)
    bids = [
        dict(id='bid-1', name='同名项目', inputAt='2026-01-01', winnerAt=None,
             cycleDays=10, inProgress=True),
        dict(id='bid-2', name='同名项目', inputAt='2026-01-02', winnerAt=None,
             cycleDays=11, inProgress=True),
    ]
    value = evaluate(_data(allOpportunities=[opportunity], bids=bids,
                           accounts=[dict(id='account-1', name='客户A', level='1', tier='strategic')]))
    assert value['metrics']['bidAmbiguous'] == 1
    assert value['metrics']['R10']['count'] == 0
    assert 'RK08' not in {risk['code'] for risk in value['risks']}


def test_advice_is_inverted_from_cause_relations_and_keeps_risk_links():
    opportunity = _opportunity(accountId='account-1', stage='11', stage1End=None)
    data = _data(
        targets=dict(amount=100.0, energy=100.0, byProduct={}, byAccount={}),
        opportunities=[opportunity], allOpportunities=[deepcopy(opportunity)],
        accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic')],
    )
    value = evaluate(data)
    recommendations = value['result']['recommendations']
    assert recommendations
    assert {item['adviceCode'] for item in recommendations} >= {'DS01', 'DS03'}
    assert all(item.get('riskCodes') for item in recommendations)
    assert all(item.get('causeIds') for item in recommendations)
    assert all(cause.get('causeCode') for cause in value['result']['causes'])
    assert all(cause.get('findingIds') for cause in value['result']['causes'])
    finding_codes = {finding['riskCode'] for finding in value['result']['findings']}
    assert all(set(item['riskCodes']) <= finding_codes for item in recommendations)
    assert all(set(cause['riskCodes']) <= finding_codes for cause in value['result']['causes'])


def test_product_risk_uses_product_specific_signing_progress():
    confirmed = _opportunity(
        id='confirmed-product-1', accountId='account-1', tier='strategic', productType='1',
        contract='confirmed', forecastAmount=99.0, forecastEnergy=99.0, stage='11', createdAt='2025-01-01')
    pending_product_1 = _opportunity(
        id='pending-product-1', accountId='account-1', tier='strategic', productType='1',
        contract='not_confirmed', forecastAmount=1.0, forecastEnergy=1.0, stage='11', createdAt='2025-01-01')
    pending_product_2 = _opportunity(
        id='pending-product-2', accountId='account-1', tier='strategic', productType='2',
        contract='not_confirmed', forecastAmount=5.0, forecastEnergy=5.0, stage='11', createdAt='2025-01-01')
    data = _data(
        targets=dict(amount=150.0, energy=150.0,
                     byProduct={'1': dict(amount=100.0, energy=100.0),
                                '2': dict(amount=50.0, energy=50.0)}, byAccount={}),
        opportunities=[confirmed, pending_product_1, pending_product_2],
        allOpportunities=[deepcopy(confirmed), deepcopy(pending_product_1), deepcopy(pending_product_2)],
    )
    value = evaluate(data, measured=date(2026, 11, 11))
    codes = {risk['code'] for risk in value['risks']}
    assert 'RK05' in codes
    assert 'RK04' not in codes


def test_model_wording_cannot_add_numbers_causes_or_broken_phrases():
    opportunity = dict(id='opp-1', name='测试商机', accountId='account-1', accountName='客户A',
                       tier='strategic', productType='1', stage='11', status='0',
                       contract='not_confirmed', createdAt='2026-01-01',
                       forecastAmount=10.0, forecastEnergy=5.0)
    data = _data(
        opportunities=[deepcopy(opportunity)], allOpportunities=[opportunity],
        accounts=[dict(id='account-1', name='客户A', level='1', tier='strategic')],
        progress={'opp-1': [dict(id='p1', description='客户要求补充资质文件', startAt='2026-10-01')]},
    )
    value = evaluate(data)
    assert value['textSamples']
    good = apply_text_interpretation(value, lambda payload: {
        'causeDescriptions': {'RC02': '项目进展显示客户要求补充资质文件，需人工复核。'},
        'adviceActions': {'DS02': '推动客户补齐资质文件后进入投标'},
    })
    assert good['status'] == 'completed'
    assert good['causes'] == ['RC02']
    assert good['advice'] == ['DS02']

    bad_value = evaluate(data)
    bad = apply_text_interpretation(bad_value, lambda payload: {
        'causeDescriptions': {'RC02': '新增 999 家客户逾期未完成', 'RC99': '模型自造原因'},
        'adviceActions': {'DS99': '模型自造建议'},
    })
    assert bad['status'] == 'completed'
    assert bad['causes'] == [] and bad['advice'] == []
    assert '999' not in bad_value['result']['causes'][0]['description']


def test_unknown_acneed_status_is_not_a_verified_cause():
    opportunity = _opportunity(acneed='', stage='11', stage1End=None)
    data = _data(
        targets=dict(amount=100.0, energy=100.0, byProduct={}, byAccount={}),
        opportunities=[opportunity], allOpportunities=[deepcopy(opportunity)],
        accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic')],
    )
    value = evaluate(data)
    assert 'RC01' not in {cause['causeCode'] for cause in value['result']['causes']}


def test_default_text_interpreter_only_parses_bounded_json(monkeypatch):
    import bi_agent.llm.provider as provider
    from bi_agent.cockpit.opportunity_v2 import default_text_interpreter

    def fake_stream(*args, **kwargs):
        return iter([
            dict(type='text_delta', text='```json\n{"causeDescriptions":{"RC02":"有文本依据"},"adviceActions":{}}\n```'),
            dict(type='message_end', stop_reason='end_turn'),
        ])

    monkeypatch.setattr(provider, 'stream_message', fake_stream)
    value = default_text_interpreter({'progressSamples': [{'text': '资质待补'}]})
    assert value == {'causeDescriptions': {'RC02': '有文本依据'}, 'adviceActions': {}}


def test_target_rows_are_summed_not_distincted_by_customer_or_product():
    config = load_config()

    class Result:
        def __init__(self, rows):
            self.rows = rows

    class Database:
        available = True
        config = SimpleNamespace(schema='ded_public', statement_timeout_ms=1000)

        def __init__(self):
            self.target_calls = 0

        def run(self, sql, params, timeout_ms=0):
            if 'new_target_esb' in sql:
                self.target_calls += 1
                return Result([
                    dict(product_type_id='1', account_id='a', amount_yuan=100_000_000,
                         energy_kwh=10_000_000, rows=1),
                    dict(product_type_id='1', account_id='a', amount_yuan=200_000_000,
                         energy_kwh=20_000_000, rows=1),
                ])
            return Result([])

    database = Database()
    data = collect('2026', database=database, config=config, measurement_date='2026-11-11')
    assert database.target_calls == 1
    assert data['targets']['amount'] == 3.0
    assert data['targets']['energy'] == 30.0


def test_all_null_target_is_missing_not_zero_and_truncation_is_preserved():
    config = load_config()

    class Result:
        truncated = False

        def __init__(self, rows):
            self.rows = rows

    class Database:
        available = True
        config = SimpleNamespace(schema='ded_public', statement_timeout_ms=1000)

        def run(self, sql, params, timeout_ms=0):
            if 'new_target_esb' in sql:
                return Result([dict(product_type_id='1', account_id='a', amount_yuan=None,
                                    energy_kwh=None, amount_cells=0, energy_cells=0, rows=1)])
            return Result([])

    data = collect('2026', database=Database(), config=config, measurement_date='2026-11-11')
    assert data['targets']['amount'] is None
    assert data['targets']['energy'] is None

    class Truncated(Result):
        truncated = True

        def __init__(self):
            super().__init__([dict(product_type_id='1', account_id='a', amount_yuan=1,
                                   energy_kwh=1, amount_cells=12, energy_cells=12, rows=1)])

    class TruncatedDatabase(Database):
        def run(self, sql, params, timeout_ms=0):
            if 'new_target_esb' in sql:
                return Truncated()
            return Result([])

    limited = collect('2026', database=TruncatedDatabase(), config=config,
                      measurement_date='2026-11-11')
    assert limited['queryStatus']['销售目标'] == 'truncated'
    assert any(item['code'] == 'ROW_LIMIT' for item in limited['errors'])


def test_database_reads_share_a_single_snapshot():
    config = load_config()
    snapshots = []

    class Result:
        truncated = False
        rows = []

    class Reader:
        def run(self, sql, params, timeout_ms=0):
            return Result()

    class Snapshot:
        def __enter__(self):
            snapshots.append('open')
            return Reader()

        def __exit__(self, *args):
            return False

    class Database:
        available = True
        config = SimpleNamespace(schema='ded_public', statement_timeout_ms=1000)

        def snapshot(self):
            return Snapshot()

        def run(self, sql, params, timeout_ms=0):
            raise AssertionError('collect must use one shared snapshot')

    collect('2026', database=Database(), config=config, measurement_date='2026-11-11')
    assert snapshots == ['open']


def test_ap_supplement_can_keep_a_limited_card_but_never_invents_detail_rows():
    class Database:
        available = True
        config = SimpleNamespace(schema='ded_public', statement_timeout_ms=1000)

        def run(self, sql, params, timeout_ms=0):
            raise RuntimeError('database timeout')

    def supplement(_data):
        return {
            'B01': dict(amount=100.0, energy=100.0, source='AP 补充'),
            'B02': dict(amount=20.0, energy=10.0, source='AP 补充'),
        }

    item = build_card('2026', database=Database(), measurement_date='2026-11-11',
                      supplement=supplement)
    assert item['status'] == 'limited'
    assert item['metrics']['B01'] == dict(amount=100.0, energy=100.0)
    assert item['metrics']['B02'] == dict(amount=20.0, energy=10.0)
    assert 'RK01' in {risk['code'] for risk in item['risks']}
    assert item['evidence']['facts']
    assert item['evidence']['records'] == []
    assert any('AP 补充' in fact['source'] for fact in item['evidence']['facts'])


def test_default_ap_supplement_reads_only_implemented_aggregate_codes(monkeypatch):
    from bi_agent.cockpit import ap_gateway, query_capabilities

    request = dict(analysisConfig=dict(
        indicators=[dict(identifierCode=code) for code in
                    ('YWLN_M0002', 'YWLN_M0023', 'YWLN_M0022')],
        dimensions=[]))
    sliced = dict(analysisConfig=dict(
        indicators=[dict(identifierCode='YWLN_M0023')],
        dimensions=[dict(identifierCode='YWLN_D005')]))
    monkeypatch.setattr(query_capabilities, 'implemented_stage_requests',
                        lambda stage, period: [sliced, request])

    class Gateway:
        def __init__(self):
            self.calls = []

        def query(self, kind, payload):
            self.calls.append((kind, payload))
            return {'result': {'columns': [dict(identifierCode=code) for code in
                                            ('YWLN_M0002', 'YWLN_M0023', 'YWLN_M0022')],
                               'rows': [{code: dict(value=value) for code, value in (
                                   ('YWLN_M0002', 100), ('YWLN_M0023', 30),
                                   ('YWLN_M0022', 40))}]}}

    gateway = Gateway()
    monkeypatch.setattr(ap_gateway, 'get_gateway', lambda: gateway)
    data = _data(targets=dict(amount=None, energy=None, byProduct={}, byAccount={}),
                 opportunities=[], queryStatus={'商机预测': 'failed', '客户': 'failed'})
    result = default_ap_supplement(data)
    assert result['B01']['amount'] == 100.0
    assert result['B02']['amount'] == 30.0
    assert result['B02']['energy'] == 40.0
    assert 'B01' not in result or 'energy' not in result['B01']
    assert 'R09' not in result
    assert len(gateway.calls) == 1  # dimensioned slice is never used as an aggregate


def test_partial_query_failure_keeps_available_evidence_and_skips_dependent_rules():
    config = load_config()

    class Result:
        def __init__(self, rows):
            self.rows = rows

    class Database:
        available = True
        config = SimpleNamespace(schema='ded_public', statement_timeout_ms=1000)

        def run(self, sql, params, timeout_ms=0):
            if 'new_target_esb' in sql:
                raise RuntimeError('target timeout')
            if 'WITH agg AS' in sql:
                return Result([dict(
                    opportunity_id='opp-1', name='测试商机', account_id='account-1',
                    account_name='客户A', account_level='1', product_type='1',
                    process_stage='11', acneed_status='1', opportunity_status='0',
                    contract_confirmation='0', created_at='2026-01-01', stage1_end=None,
                    stage2_end=None, stage3_end=None, stage4_end=None, stage5_end=None,
                    owner_id='u1', amount_yuan=1_000_000_000, forecast_amount_full_yuan=1_000_000_000,
                    energy_gwh=5.0, month_rows=12, past_rows=10, past_amount_rows=10,
                    energy_rows=12,
                )])
            return Result([])

    data = collect('2026', database=Database(), config=config, measurement_date='2026-11-11')
    assert data['errors'][0]['stage'] == '销售目标'
    assert data['opportunities'][0]['id'] == 'opp-1'
    value = evaluate(data, config=config, measured=date(2026, 11, 11))
    assert value['metrics']['B01']['amount'] is None
    assert 'RK01' not in {risk['code'] for risk in value['risks']}


def test_all_core_query_failures_do_not_replace_the_last_card():
    config = load_config()

    class Database:
        available = True
        config = SimpleNamespace(schema='ded_public', statement_timeout_ms=1000)

        def run(self, sql, params, timeout_ms=0):
            raise RuntimeError('database timeout')

    try:
        collect('2026', database=Database(), config=config, measurement_date='2026-11-11')
    except Exception as exc:
        assert type(exc).__name__ == 'OpportunityV2Unavailable'
        assert '核心取数失败' in str(exc)
    else:
        raise AssertionError('core query failure must not produce a zero-valued card')
