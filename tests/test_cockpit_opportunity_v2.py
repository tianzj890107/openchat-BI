from copy import deepcopy
from datetime import date
from types import SimpleNamespace

from bi_agent.cockpit.opportunity_v2 import (
    _customer_tier, _p0_cycle, _p2_cycle,
    build_card, collect, config_digest, config_version, default_ap_supplement, evaluate,
    load_config,
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


def _strategic_value(**updates):
    return evaluate(_data(
        opportunities=[_opportunity()], allOpportunities=[deepcopy(_opportunity())],
        accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic')],
        **updates,
    ))


def _judge_no(request):
    return dict(established=False, reason='测试：判定不成立')


def test_v3_config_is_complete_and_rk07_has_no_contradictory_cause():
    config = load_config()
    assert config_version() == 'opportunity-v3-rules-3'
    assert len(config_digest()) == 64
    assert len(config['metrics']) == 55
    assert len(config['risks']) == 10
    assert len(config['causes']) == 9
    assert len(config['advice']) == 12
    assert config['overrides']['customerTier']['strategic'] == ['1']
    assert config['overrides']['customerTier']['priority'] == ['2']
    assert config['overrides']['customerTier']['generalCatchAll'] is True
    assert config['metrics']['B02']['sqlStatus']
    assert 'new_whprice' in config['metrics']['B02']['sql']
    assert config['links']['RK07']['causes'] == ['RC09']
    assert config['links']['RK07']['advice'] == ['AC02', 'AC03']


def test_result_exposes_the_full_ontology_trace():
    value = evaluate(_data())
    trace = value['result']['ontologyTrace']
    assert trace['ontology'] == '商机获取节点 V3'
    assert trace['version'] == 'opportunity-v3-rules-3'
    assert len(trace['digest']) == 12
    assert len(trace['metrics']) == 55
    assert len(trace['risks']) == 10
    assert len(trace['causes']) == 9
    assert len(trace['advice']) == 12
    assert len(trace['rules']) == 35
    assert trace['risks'][0]['code'] == 'RK01' and trace['risks'][0]['name']
    assert trace['links']['RK07'] == {'risk': 'RK07', 'causes': ['RC09'],
                                      'advice': ['AC02', 'AC03']}
    br_a07 = next(item for item in trace['rules'] if item['code'] == 'BR-A07')
    assert br_a07['name'] and br_a07['description'] and br_a07['trigger']


def test_result_exposes_rule_assessments_and_query_sql_for_evidence_details():
    opportunity = _opportunity()
    data = _data(opportunities=[opportunity], allOpportunities=[deepcopy(opportunity)],
                 accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic')])
    data['queryCatalog'] = [dict(label='销售目标', sql='SELECT 1', params=[2026],
                                 status='ok', durationSeconds=0.01, rowCount=1)]
    value = evaluate(data)
    assessments = value['result']['riskAssessments']
    assert len(assessments) == 10
    triggered = next(item for item in assessments if item['ruleStatus'] == 'triggered')
    assert triggered['rule'] and triggered['condition']
    assert triggered['metricCodes']
    assert value['result']['queryCatalog'] == data['queryCatalog']


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


def test_customer_levels_follow_v3_dr04_dr05_dr06():
    config = load_config()
    assert _customer_tier('1', config) == 'strategic'
    assert _customer_tier('2', config) == 'priority'
    assert _customer_tier('0', config) == 'general'
    assert _customer_tier('3', config) == 'general'
    assert _customer_tier('4', config) == 'general'
    assert _customer_tier('', config) == 'unknown'


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
    assert all(not (cause['causeCode'] == 'RC01' and 'RK07' in cause['riskCodes'])
               for cause in value['result']['causes'])
    assert any(cause['causeCode'] == 'RC09' and 'RK07' in cause['riskCodes']
               for cause in value['result']['causes'])
    rk07_finding_ids = {finding['id'] for finding in value['result']['findings']
                        if finding['riskCode'] == 'RK07'}
    assert all(not (set(cause['findingIds']) & rk07_finding_ids)
               for cause in value['result']['causes'] if cause['causeCode'] == 'RC01')


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
    assert {item['adviceCode'] for item in recommendations} >= {'AC01'}
    assert all(item.get('riskCodes') for item in recommendations)
    assert all(item.get('causeIds') for item in recommendations)
    assert all(cause.get('causeCode') for cause in value['result']['causes'])
    assert all(cause.get('findingIds') for cause in value['result']['causes'])
    finding_codes = {finding['riskCode'] for finding in value['result']['findings']}
    assert all(set(item['riskCodes']) <= finding_codes for item in recommendations)
    assert all(set(cause['riskCodes']) <= finding_codes for cause in value['result']['causes'])


def test_no_opportunity_strategic_customer_uses_rc09_advice_and_keeps_deadline_text():
    data = _data(accounts=[dict(id='account-empty', name='无商机战略客户', level='1',
                                tier='strategic')], queryStatus=dict(客户='ok'))
    value = evaluate(data)
    assert 'RK07' in {risk['code'] for risk in value['risks']}
    causes = [cause for cause in value['result']['causes'] if cause['causeCode'] == 'RC09']
    # V3 defines RC09 as "no recent lead/visit/demand record" without a day
    # window; without that window the cause stays a data gap instead of a
    # verified finding.
    assert causes and causes[0]['kind'] == 'data_gap'
    assert causes[0]['missingEvidence']
    recommendations = value['result']['recommendations']
    assert {'AC02', 'AC03'} <= {item['adviceCode'] for item in recommendations}
    assert all(item['deadline'] for item in recommendations)
    assert all(item['deadlineType'] == 'days' for item in recommendations)


def test_deadline_meta_keeps_original_text_instead_of_forcing_30_days():
    from bi_agent.cockpit.opportunity_v2 import _deadline_meta

    days, kind, text = _deadline_meta('按月')
    assert (days, kind, text) == (30, 'text', '按月')
    days, kind, text = _deadline_meta('按突破计划协同')
    assert (days, kind, text) == (30, 'text', '按突破计划协同')
    assert _deadline_meta('20 个工作日') == (20, 'days', '20 个工作日')


def test_ac05_is_governance_investigation_and_ac10_uses_coverage_wording():
    general = _opportunity(id='g1', accountId='a1', tier='general', stage='13',
                           contract='not_confirmed', forecastAmount=10.0, forecastEnergy=5.0)
    data = _data(opportunities=[general], allOpportunities=[deepcopy(general)],
                 accounts=[dict(id='a1', name='一般客户', level='3', tier='general')])
    value = evaluate(data)
    ac10 = next(item for item in value['result']['recommendations']
                if item['adviceCode'] == 'AC10')
    assert ac10['action'] == '将重点跟踪覆盖率提升至 70%（当前 0.0%）'

    opportunity = _opportunity(accountId='account-1', stage='11', stage1End=None, bidding='no')
    value = evaluate(_data(
        opportunities=[opportunity], allOpportunities=[deepcopy(opportunity)],
        accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic')],
        progress={'opp-1': [dict(id='p1', description='客户要求补充资质文件',
                                 startAt='2026-10-01')]},
    ))
    ac05 = next(item for item in value['adviceCandidates'] if item['code'] == 'AC05')
    assert ac05['actionType'] == 'investigation'
    assert ac05['governance'] is True


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


def test_unknown_contract_does_not_reduce_confirmed_signing_coverage():
    confirmed = _opportunity(
        id='confirmed-1', contract='confirmed', forecastAmount=100.0, forecastEnergy=100.0,
        stage='14', createdAt='2026-01-01')
    unknown = _opportunity(
        id='unknown-1', contract='unknown', forecastAmount=20.0, forecastEnergy=20.0,
        stage='14', createdAt='2026-01-01')
    data = _data(
        targets=dict(amount=100.0, energy=100.0,
                     byProduct={'1': dict(amount=100.0, energy=100.0)}, byAccount={}),
        opportunities=[confirmed, unknown],
        allOpportunities=[deepcopy(confirmed), deepcopy(unknown)],
    )
    value = evaluate(data, measured=date(2026, 11, 11))
    assert value['metrics']['R03']['signProgressAmount'] == 1.0
    assert value['metrics']['R03']['signProgressEnergy'] == 1.0
    assert value['metrics']['R02']['unknownAmount'] == 20.0
    assert 'RK02' not in {risk['code'] for risk in value['risks']}
    assert any('合同状态未知不计入已签或未签' in item for item in value['result']['limitations'])


def test_build_card_reports_internal_steps_in_execution_order():
    class EmptyResult:
        truncated = False
        rows = []

    class Database:
        available = True
        config = SimpleNamespace(schema='ded_public', statement_timeout_ms=1000)

        def run(self, sql, params, timeout_ms=0):
            return EmptyResult()

    events = []
    card = build_card('2026', database=Database(), measurement_date='2026-11-11',
                      judge=_judge_no,
                      progress=lambda phase, **detail: events.append((phase, detail)))
    phases = [phase for phase, _ in events]
    assert phases[0] == 'ontology'
    assert phases.count('fetching') >= 9
    assert phases.index('rules') < phases.index('analysing') and phases[-1] == 'publishing'
    assert set(phases[phases.index('analysing') + 1:-1]) <= {'judging'}
    fetch = [detail for phase, detail in events if phase == 'fetching']
    assert fetch[-1]['completed'] == fetch[-1]['total'] == 10
    assert len(card['result']['queryCatalog']) == 10
    assert any(item['label'] == '产品部销售缺口' for item in card['result']['queryCatalog'])
    assert all(item['sql'] for item in card['result']['queryCatalog'])




























def test_unknown_acneed_status_is_not_a_verified_cause():
    opportunity = _opportunity(acneed='', stage='11', stage1End=None)
    data = _data(
        targets=dict(amount=100.0, energy=100.0, byProduct={}, byAccount={}),
        opportunities=[opportunity], allOpportunities=[deepcopy(opportunity)],
        accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic')],
    )
    value = evaluate(data)
    assert 'RC01' not in {cause['causeCode'] for cause in value['result']['causes']}


def test_local_model_uses_only_the_configured_route(monkeypatch):
    from bi_agent.llm import registry
    from bi_agent.cockpit import opportunity_v2 as module

    models = [dict(key='team-configured', provider='team',
                   model_id='customer-local-qwen', supports_thinking=False)]
    monkeypatch.setattr(registry, 'MODELS', models)
    monkeypatch.setattr(registry, 'get_default_model_key', lambda: 'team-configured')
    monkeypatch.delenv(module._MODEL_KEY_ENV, raising=False)
    assert module._model_candidate_keys() == ['team-configured']


def test_opportunity_card_uses_only_the_configured_model(monkeypatch):
    from bi_agent.llm import registry
    from bi_agent.cockpit import opportunity_v2 as module

    models = [dict(key='team-configured', provider='team',
                   model_id='direct-deepseek-v4-flash', supports_thinking=True)]
    monkeypatch.setattr(registry, 'MODELS', models)
    monkeypatch.setattr(registry, 'get_default_model_key', lambda: 'team-configured')
    monkeypatch.delenv(module._MODEL_KEY_ENV, raising=False)
    assert module._model_candidate_keys() == ['team-configured']


def test_explicit_model_key_env_pins_a_route(monkeypatch):
    from bi_agent.llm import registry
    from bi_agent.cockpit import opportunity_v2 as module

    models = [
        dict(key='team-configured', provider='team',
             model_id='direct-deepseek-v4-flash', supports_thinking=True),
        dict(key='customer-local', provider='team',
             model_id='customer-local-model', supports_thinking=False),
    ]
    monkeypatch.setattr(registry, 'MODELS', models)
    monkeypatch.setattr(registry, 'get_default_model_key', lambda: 'team-configured')
    monkeypatch.setenv(module._MODEL_KEY_ENV, 'customer-local')
    assert module._model_candidate_keys() == ['customer-local']


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
            # The ontology C05 query also reads the target table; it is not the target read.
            if 'new_target_esb' in sql and "'C05'::text" not in sql:
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
    # B01 energy now reads new_month*_power (MWh), so the same row values are
    # converted with the MWh divisor.
    assert data['targets']['energy'] == 30_000.0


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


def test_database_failure_fails_the_card_instead_of_an_ap_only_card():
    from bi_agent.cockpit.opportunity_v2 import OpportunityV2Unavailable

    class Database:
        available = True
        config = SimpleNamespace(schema='ded_public', statement_timeout_ms=1000)

        def run(self, sql, params, timeout_ms=0):
            raise RuntimeError('database timeout')

    supplied = []

    def supplement(_data):
        supplied.append(True)
        return {'B01': dict(amount=100.0, energy=100.0), 'B02': dict(amount=20.0, energy=10.0)}

    try:
        build_card('2026', database=Database(), measurement_date='2026-11-11',
                   supplement=supplement, judge=_judge_no)
    except OpportunityV2Unavailable as exc:
        assert exc.code == 'CORE_FETCH_FAILED'
    else:
        raise AssertionError('no card may be built when the database read failed')
    assert supplied == []


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


def test_truncated_detail_uses_full_aggregate_for_rules_and_skips_partial_cycles():
    partial = _opportunity(id='partial', contract='not_confirmed', forecastAmount=1.0,
                           forecastEnergy=1.0)
    data = _data(
        targets=dict(amount=100.0, energy=100.0,
                     byProduct={'1': dict(amount=50.0, energy=50.0)}, byAccount={}),
        opportunities=[partial], allOpportunities=[deepcopy(partial)],
        detailComplete=False, allOpportunitiesComplete=True, aggregatesComplete=True,
        opportunityAggregates=[dict(
            contract='not_confirmed', tier='strategic', accountLevel='1', productType='1',
            accountId='account-1', accountName='战略客户A', stage='11', count=10,
            amount=30.0, amountFull=35.0, energy=20.0, monthRows=120,
            pastRows=100, pastAmountRows=20, energyRows=120,
        )],
    )
    value = evaluate(data, measured=date(2026, 11, 11))
    assert value['metrics']['B02'] == dict(amount=30.0, energy=20.0)
    assert value['metrics']['R02']['amount'] == 30.0
    assert value['metrics']['R04']['count'] == 10
    assert 'RK01' in {risk['code'] for risk in value['risks']}
    assert 'RK10' not in {risk['code'] for risk in value['risks']}
    assert any('全量聚合' in item for item in value['result']['limitations'])


def test_collect_parses_and_marks_complete_full_aggregate_when_detail_is_truncated():
    config = load_config()

    class Result:
        def __init__(self, rows, truncated=False):
            self.rows = rows
            self.truncated = truncated

    class Reader:
        def run(self, sql, params, timeout_ms=0):
            if 'agg.month_rows, agg.past_rows' in sql:
                return Result([dict(
                    opportunity_id='partial', name='截断明细', account_id='account-1',
                    account_name='客户A', account_level='1', product_type='1',
                    process_stage='11', acneed_status='1', opportunity_status='0',
                    contract_confirmation='0', created_at='2026-01-01', stage1_end=None,
                    stage2_end=None, stage3_end=None, stage4_end=None, stage5_end=None,
                    owner_id='u1', amount_yuan=1_000_000_000,
                    forecast_amount_full_yuan=1_000_000_000, energy_gwh=5.0,
                    month_rows=12, past_rows=10, past_amount_rows=10, energy_rows=12,
                )], truncated=True)
            if 'AS contract_raw' in sql:
                return Result([dict(
                    contract_raw='0', account_level='1', product_type='1',
                    account_id='account-1', account_name='客户A', process_stage='11',
                    opportunity_count=10, amount_yuan=3_000_000_000,
                    forecast_amount_full_yuan=3_500_000_000, energy_gwh=20.0,
                    month_rows=120, past_rows=100, past_amount_rows=20, energy_rows=120,
                )])
            return Result([])

    class Snapshot:
        def __enter__(self):
            return Reader()

        def __exit__(self, *args):
            return False

    class Database:
        available = True
        config = SimpleNamespace(schema='ded_public', statement_timeout_ms=1000)

        def snapshot(self):
            return Snapshot()

    data = collect('2026', database=Database(), config=config, measurement_date='2026-11-11')
    assert data['detailComplete'] is False
    assert data['aggregatesComplete'] is True
    assert data['opportunityAggregates'][0]['count'] == 10
    assert data['opportunityAggregates'][0]['amount'] == 30.0
    assert data['opportunityAggregates'][0]['energy'] == 20.0
    assert data['opportunityAggregates'][0]['pastAmountRows'] == 20


def test_truncated_detail_without_aggregate_never_uses_partial_sums():
    partial = _opportunity(id='partial', contract='not_confirmed', forecastAmount=1.0,
                           forecastEnergy=1.0)
    data = _data(
        targets=dict(amount=100.0, energy=100.0, byProduct={}, byAccount={}),
        opportunities=[partial], allOpportunities=[deepcopy(partial)],
        detailComplete=False, allOpportunitiesComplete=True, aggregatesComplete=False,
        opportunityAggregates=[],
    )
    value = evaluate(data, measured=date(2026, 11, 11))
    assert value['metrics']['B02']['amount'] is None
    assert value['metrics']['B02']['energy'] is None
    assert 'RK01' not in {risk['code'] for risk in value['risks']}
    assert any('截断明细不参与' in item for item in value['result']['limitations'])


def test_a_failed_model_call_skips_only_that_item():
    class Result:
        truncated = False
        rows = []

    class Database:
        available = True
        config = SimpleNamespace(schema='ded_public', statement_timeout_ms=1000)

        def run(self, sql, params, timeout_ms=0):
            return Result()

    calls = []

    def judge(request):
        calls.append(request['code'])
        if len(calls) == 1:
            raise RuntimeError('model connection failed')
        return dict(established=False, reason='数据不足以判定')

    card = build_card('2026', database=Database(), measurement_date='2026-11-11', judge=judge)
    judgement = card['result']['ontologyJudgement']
    failed = [item for item in judgement['risks'] if item.get('error')]
    assert [item['code'] for item in failed] == [calls[0]]
    assert failed[0]['statusLabel'] == '判断失败，已跳过'
    assert failed[0]['error'].startswith('无法连接模型服务：model connection failed')
    assert len(calls) > 1
    assert card['status'] == 'limited'
    assert any(calls[0] in item for item in card['result']['dataDiagnostics'])


def test_evidence_counts_distinguish_facts_records_and_references():
    from bi_agent.cockpit.delivery import evidence_count

    value = evaluate(_data(
        opportunities=[_opportunity()], allOpportunities=[deepcopy(_opportunity())],
        accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic')],
    ))
    counts = value['evidence']['counts']
    assert counts['facts'] >= 1
    assert counts['records'] >= 0
    assert counts['distinct'] == evidence_count(value['evidence'])
    assert counts['distinct'] <= counts['facts'] + counts['records'] + counts['referenced']


def test_collect_uses_three_snapshot_readers_and_reports_query_progress():
    import threading
    import time
    from contextlib import contextmanager

    class Result:
        truncated = False
        rows = []

    active = 0
    max_active = 0
    lock = threading.Lock()

    class Reader:
        def run(self, sql, params, timeout_ms=0):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.01)
                return Result()
            finally:
                with lock:
                    active -= 1

        def cancel(self):
            pass

    class Database:
        available = True
        config = SimpleNamespace(schema='ded_public', statement_timeout_ms=1000)

        @contextmanager
        def snapshot_group(self, workers=3):
            assert workers == 3
            yield [Reader() for _ in range(3)]

        def run(self, sql, params, timeout_ms=0):
            raise AssertionError('parallel path must use snapshot_group readers')

    events = []
    data = collect('2026', database=Database(), config=load_config(),
                   measurement_date='2026-11-11',
                   progress=lambda phase, **detail: events.append((phase, detail)))
    assert max_active >= 2
    fetch = [detail for phase, detail in events if phase == 'fetching']
    assert fetch and fetch[-1]['completed'] == fetch[-1]['total'] == 10
    assert all('query' in detail and 'queryDurationSeconds' in detail for detail in fetch)
    assert data['queryStatus']['商机预测'] == 'ok'




def test_query_catalog_keeps_execution_record_and_result_snapshot():
    class RowResult:
        truncated = False
        rows = [dict(account_id='A1', amount_yuan=1_000_000_000, energy_kwh=2_000_000)]

    class Database:
        available = True
        config = SimpleNamespace(schema='ded_public', database='ywln_gov',
                                 host='127.0.0.1', port=5432,
                                 statement_timeout_ms=1000)

        def run(self, sql, params, timeout_ms=0):
            return RowResult()

    card = build_card('2026', database=Database(), measurement_date='2026-11-11',
                      judge=_judge_no)
    catalog = card['result']['queryCatalog']
    assert len(catalog) == 10
    for item in catalog:
        assert item['executionId'] and len(item['executionId']) == 32
        assert item['startedAt'] and item['finishedAt']
        assert item['durationMs'] >= 0
        assert item['resultHash'] and len(item['resultHash']) == 64
        assert item['database'] == 'ywln_gov' and item['schema'] == 'ded_public'
        assert isinstance(item['sampleRows'], list)
        assert isinstance(item['truncated'], bool)
    target = next(item for item in catalog if item['label'] == '销售目标')
    assert target['sampleRowCount'] == 1
    assert target['sampleTruncated'] is False
    forecast = next(item for item in catalog if item['label'] == '商机预测')
    assert 'new_whprice' in forecast['sql']
    assert 'new_forecast_amt_rmb / NULLIF(m.new_whprice, 0)' in forecast['sql']
    assert target['sampleRows'][0]['account_id'] == 'A1'
    assert target['aggregation']


def test_query_catalog_sample_rows_are_capped_and_flagged():
    class RowResult:
        truncated = True
        rows = [dict(idx=index) for index in range(150)]

    class Database:
        available = True
        config = SimpleNamespace(schema='ded_public', database='ywln_gov',
                                 host='127.0.0.1', port=5432,
                                 statement_timeout_ms=1000)

        def run(self, sql, params, timeout_ms=0):
            return RowResult()

    card = build_card('2026', database=Database(), measurement_date='2026-11-11',
                      judge=_judge_no)
    item = next(q for q in card['result']['queryCatalog'] if q['label'] == '销售目标')
    assert item['truncated'] is True
    assert item['rowCount'] == 150
    assert item['sampleRowCount'] == item['sampleLimit']
    assert item['sampleTruncated'] is True
    assert len(item['sampleRows']) == item['sampleLimit']


def _empty_database():
    class EmptyResult:
        truncated = False
        rows = []

    class Database:
        available = True
        config = SimpleNamespace(schema='ded_public', statement_timeout_ms=1000)

        def run(self, sql, params, timeout_ms=0):
            return EmptyResult()
    return Database()


def test_model_failures_are_classified_for_the_user():
    from bi_agent.cockpit.opportunity_v2 import classify_model_failure

    def category(**status):
        return classify_model_failure(dict(status='failed', **status))[0]

    assert category(modelErrorMessage="Team API request failed: Error code: 400 - "
                    "{'error': {'code': 'context_length_exceeded'}}") == '上下文超出模型限制'
    assert category(modelErrorMessage='Error code: 401 - invalid api key') == '模型服务认证失败'
    assert category(modelErrorMessage='Error code: 429 - rate limit reached') == '模型服务限流或额度不足'
    assert category(modelErrorMessage='Error code: 404 - model_not_found') == '模型不存在或名称配置错误'
    assert category(modelErrorMessage='APITimeoutError: Request timed out.') == '模型请求超时'
    assert category(modelErrorMessage='Error code: 503 - service unavailable') == '模型服务端异常'
    assert category(modelErrorType='ModelEmptyResponse', modelFinishReason='content_filter',
                    modelErrorMessage='模型未返回正文') == '模型拒绝回答或内容被安全过滤'
    assert category(modelErrorType='ModelEmptyResponse', modelErrorMessage='模型未返回正文',
                    modelStopReason='max_tokens') == '输出预算被耗尽'
    assert category(modelErrorType='ModelEmptyResponse', modelErrorMessage='模型未返回正文') \
        == '模型连接中途断开'
    assert category(error='MODEL_OUTPUT_INVALID', modelErrorType='ModelJSONOutputError',
                    modelStopReason='max_tokens', modelErrorMessage='模型输出达到 token 上限') \
        == '输出超过长度上限'
    assert category(error='MODEL_DISABLED') == '未启用模型判断'


def _judged(value, judge):
    from bi_agent.cockpit.opportunity_judgement import judge_card
    return judge_card(value, load_config(), judge=judge)


def test_rules_decide_first_and_only_undecided_items_reach_the_model_one_by_one():
    value = _strategic_value()
    status = {item['code']: item['ruleStatus'] for item in value['riskCandidates']}
    undecided = [code for code, state in status.items() if state == 'insufficient']
    assert undecided
    requests = []

    def judge(request):
        requests.append(request)
        return dict(established=request['kind'] == 'risk', level='中', reason='模型依据取数判定')
    judged = _judged(value, judge)
    risk_requests = [item for item in requests if item['kind'] == 'risk']
    # One call per undecided risk, carrying only that risk's rule and data.
    assert [item['code'] for item in risk_requests] == undecided
    assert all(set(item['rule']) == {'code', 'name', 'condition', 'levelRule'} for item in risk_requests)
    assert all('observed' in item['data'] for item in risk_requests)
    findings = {item['riskCode']: item for item in judged['findings']}
    triggered = [code for code, state in status.items() if state == 'triggered']
    # Every established risk is shown: rule ones and model ones, no limit.
    assert set(findings) == set(triggered) | set(undecided)
    assert len(findings) > 4
    assert {findings[code]['decidedBy'] for code in triggered} == {'rule'}
    assert {findings[code]['decidedBy'] for code in undecided} == {'model'}
    assert findings[undecided[0]]['description'] == '模型依据取数判定'
    # Rule-settled risks never reach the model.
    assert not {item['code'] for item in risk_requests} & (set(status) - set(undecided))


def test_causes_follow_established_risks_and_advice_follows_established_causes():
    value = _strategic_value()
    requests = []

    def judge(request):
        requests.append(request)
        return dict(established=request['kind'] == 'cause', reason='进展文本显示卡点')
    judged = _judged(value, judge)
    causes = {item['code']: item for item in judged['ontologyJudgement']['causes']}
    established = {item['riskCode'] for item in judged['findings']}
    links = load_config()['links']
    for code, entry in causes.items():
        related = {risk for risk in established if code in (links.get(risk) or {}).get('causes', [])}
        if not related:
            assert entry['decidedBy'] == 'unevaluated' and entry['established'] is None
    cause_requests = [item for item in requests if item['kind'] == 'cause']
    for item in cause_requests:
        assert value['causeOutcomes'][item['code']]['ruleStatus'] == 'insufficient'
        assert item['linkedRisks'] and all(link['code'] in established for link in item['linkedRisks'])
    hit = {item['causeCode'] for item in judged['causes']}
    assert hit
    advice = {item['code']: item for item in judged['ontologyJudgement']['advice']}
    specs = load_config()['advice']
    for code, entry in advice.items():
        assert entry['established'] is bool(set(specs[code]['causes']) & hit)
    assert {item['adviceCode'] for item in judged['recommendations']} == {
        code for code, entry in advice.items() if entry['established']}
    assert all(item['decidedBy'] == 'rule' for item in judged['recommendations'])


def test_every_item_is_listed_with_its_status_for_the_ontology_display():
    judged = _judged(_strategic_value(), _judge_no)
    judgement = judged['ontologyJudgement']
    config = load_config()
    assert [item['code'] for item in judgement['risks']] == list(config['risks'])
    assert [item['code'] for item in judgement['causes']] == list(config['causes'])
    assert [item['code'] for item in judgement['advice']] == list(config['advice'])
    labels = {item['statusLabel'] for group in judgement.values() if isinstance(group, list)
              for item in group if isinstance(item, dict)}
    assert {'命中（规则判定）', '未命中（规则判定）', '未命中（模型判定）'} <= labels
    assert judged['summary'].startswith('本轮 10 项本体风险中')


def test_model_answers_are_taken_without_a_validation_pass():
    value = _strategic_value()

    def judge(request):
        # Unusual wording and an unknown level are accepted as given.
        return dict(established='成立', level='特别高', reason='x' * 900)
    judged = _judged(value, judge)
    model = [item for item in judged['findings'] if item['decidedBy'] == 'model']
    assert model and all(item['riskLevel'] == '' for item in model)
    assert all(len(item['description']) == 400 for item in model)


def test_without_a_model_undecided_items_are_skipped_and_reported():
    judged = _judged(_strategic_value(), None)
    errors = [item for item in judged['ontologyJudgement']['risks'] if item.get('error')]
    assert errors and all(item['error'] == '未启用模型判断，已跳过' for item in errors)
    assert judged['ontologyJudgement']['failures']


def test_rc04_rule_uses_the_product_team_gap_query():
    base = dict(targets=dict(amount=100.0, energy=100.0, byProduct={}, byAccount={}))
    short = evaluate(_data(**base, productTeamGaps=[
        dict(team='储能电芯产品部', gapAmount=-3.5, gapEnergy=None, status='目标与实绩已配对'),
        dict(team='PACK 产品部', gapAmount=1.2, gapEnergy=0.4, status='目标与实绩已配对')]))
    outcome = short['causeOutcomes']['RC04']
    assert outcome['ruleStatus'] == 'triggered'
    assert '储能电芯产品部 金额差 -3.50 亿元' in outcome['description']
    fine = evaluate(_data(**base, productTeamGaps=[
        dict(team='PACK 产品部', gapAmount=1.2, gapEnergy=0.4, status='目标与实绩已配对')]))
    assert fine['causeOutcomes']['RC04']['ruleStatus'] == 'not_triggered'
    unknown = evaluate(_data(**base, productTeamGaps=[], productTeamGapStatus='failed'))
    assert unknown['causeOutcomes']['RC04']['ruleStatus'] == 'insufficient'
    assert 'failed' in unknown['causeOutcomes']['RC04']['reason']


def test_ontology_metric_sql_is_bound_to_the_period_and_measurement_date():
    from bi_agent.cockpit.opportunity_v2 import _ontology_metric_sql
    sql = _ontology_metric_sql(load_config(), 'C05', 2026, date(2026, 11, 11))
    assert "DATE '2026-01-01' AS start_date, DATE '2027-01-01' AS end_exclusive" in sql
    assert "TIMESTAMP '2026-11-11 23:59:59'" in sql and 'CURRENT_TIMESTAMP' not in sql
    assert not sql.endswith(';') and '%' not in sql
    other = _ontology_metric_sql(load_config(), 'C05', 2026, date(2026, 11, 11), schema='crm_copy')
    assert 'crm_copy.' in other and 'ded_public.' not in other
    assert _ontology_metric_sql(load_config(), 'NOPE', 2026, date(2026, 11, 11)) == ''


def test_item_judge_sends_no_tools_and_reports_a_tool_call_as_its_error(monkeypatch):
    import bi_agent.llm.provider as provider
    from bi_agent.cockpit import opportunity_judgement as judgement
    from bi_agent.cockpit import opportunity_v2 as module

    seen = []
    replies = iter([
        [dict(type='text_delta', text='{"established": true, "level": "高", "reason": "缺口 10 亿元"}'),
         dict(type='message_end', stop_reason='end_turn', finish_reason='stop', usage={})],
        [dict(type='tool_use_end', id='c1', name='Ontology-MetricQuery', input={}),
         dict(type='message_end', stop_reason='tool_use', finish_reason='tool_calls', usage={})],
    ])

    def fake_stream(messages, system_prompt, allowed_tools, *args, **kwargs):
        seen.append((allowed_tools, system_prompt))
        return iter(next(replies))

    monkeypatch.setattr(provider, 'stream_message', fake_stream)
    monkeypatch.setattr(module, '_model_candidate_keys', lambda: ['route-a'])
    answer = judgement.default_item_judge(dict(kind='risk', code='RK01'))
    assert answer['established'] is True and answer['_model'] == 'route-a'
    assert seen[0][0] == [] and '这一条风险' in seen[0][1]
    entry = judgement._ask(judgement.default_item_judge, dict(kind='cause', code='RC02'), None, '1/1')
    assert entry['decidedBy'] == 'none' and entry['established'] is None
    assert entry['error'].startswith('模型没有作答，而是发起了工具调用')
    assert entry['error'].endswith('已跳过')


def test_rule_first_card_is_delivered_to_the_page_as_judged():
    from bi_agent.cockpit.delivery import project_card, publication_payload
    from bi_agent.cockpit.opportunity_judgement import judge_card
    from bi_agent.cockpit.page_cache import compact_analysis
    value = _strategic_value()
    judged = judge_card(value, load_config(), judge=lambda request: dict(
        established=True, level='中', reason='模型判定成立'))
    item = dict(id='x', status='completed',
                context=dict(stage='opportunity', slotId='opportunity-risk', period='2026'),
                result=dict(value['result'], **judged, cardContract='cockpit-cards-v1'),
                evidence=value['evidence'])
    result = publication_payload(project_card(compact_analysis(item), 'opportunity-risk'))['result']
    # Same risks, order, wording, level and decision source as the judgement.
    assert [(f['riskCode'], f['title'], f['riskLevel'], f['decidedBy']) for f in result['findings']] == [
        (f['riskCode'], f['title'], f['riskLevel'], f['decidedBy']) for f in judged['findings']]
    assert len(result['findings']) > 4
    assert [d['causeCode'] for d in result['analysisDimensions']] == [c['causeCode'] for c in judged['causes']]
    assert [r['action'] for r in result['recommendations']] == [r['action'] for r in judged['recommendations']]
    assert result['ontologyJudgement'] == judged['ontologyJudgement']
    assert all(f['riskKey'] == 'opp-v2:' + f['riskCode'] for f in result['findings'])


def test_ontology_sql_passes_the_read_only_guard():
    from bi_agent.cockpit.opportunity_v2 import _ontology_metric_sql
    from bi_agent.process360.db import ensure_read_only
    sql = _ontology_metric_sql(load_config(), 'C05', 2025, date(2025, 12, 31))
    # The workbook SQL opens with "--" comments; the guard needs SELECT/WITH first.
    assert sql.startswith('WITH') and '--' not in sql
    ensure_read_only(sql)


def test_risk_trace_resolves_rule_ontology_and_metrics():
    from bi_agent.cockpit.opportunity_judgement import judge_card
    judged = judge_card(_strategic_value(), load_config(), judge=_judge_no)
    config = load_config()
    metric_codes = set(config['metrics'])
    rule_codes = {item['code'] for item in config['rules'].values()}
    for item in judged['riskAssessments']:
        assert item['rule'] in rule_codes
        assert item['metricCodes'] and set(item['metricCodes']) <= metric_codes
    rk01 = next(item for item in judged['riskAssessments'] if item['code'] == 'RK01')
    assert rk01['metricCodes'] == ['R01', 'B01', 'B02']
