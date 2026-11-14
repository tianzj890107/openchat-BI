from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from pathlib import Path

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
    updates.setdefault('accounts', [dict(id='account-1', name='战略客户A', level='1', tier='strategic')])
    return evaluate(_data(
        opportunities=[_opportunity()], allOpportunities=[deepcopy(_opportunity())],
        **updates,
    ))


def _judge_no(request):
    return dict(established=False, reason='测试：判定不成立')


def test_v3_config_is_complete_and_rk07_has_no_contradictory_cause():
    config = load_config()
    assert config_version() == 'opportunity-v3-rules-8'
    assert len(config_digest()) == 64
    # The bid part (R10/R11/C02/S03, RK08/RK09, RC02, AC04/AC05) is excluded.
    assert len(config['metrics']) == 51
    assert len(config['risks']) == 8
    assert len(config['causes']) == 8
    assert len(config['advice']) == 10
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
    assert trace['ontology'] == '商机获取节点 V3 储能客户口径修订'
    assert trace['version'] == 'opportunity-v3-rules-8'
    assert len(trace['digest']) == 12
    assert len(trace['metrics']) == 51
    assert len(trace['risks']) == 8
    assert len(trace['causes']) == 8
    assert len(trace['advice']) == 10
    assert len(trace['rules']) == 31
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
    assert len(assessments) == 8
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
    # Ontology stage_facts: an unfinished stage runs to the cutoff whatever the
    # current stage enum; a finish after the cutoff is cut at the cutoff.
    assert _p0_cycle(_opportunity(createdAt='2026-01-01', stage='12', stage1End=None), measured) == 314
    assert _p0_cycle(_opportunity(createdAt='2026-01-01', stage='11', stage1End='2026-01-11'), measured) == 10
    assert _p0_cycle(_opportunity(createdAt='2026-10-01', stage='12', stage1End='2026-12-01'), measured) == 41
    assert _p2_cycle(_opportunity(stage2End='2026-05-01', stage3End='2026-04-01'), measured) is None

    base = _data(targets=dict(amount=1000.0, energy=1000.0, byProduct={}, byAccount={}))
    rows = [
        _opportunity(id='a', createdAt='2026-01-01', stage='11', stage1End=None, contract='confirmed'),
        _opportunity(id='b', createdAt='2026-01-01', stage='11', stage1End=None, contract='confirmed'),
    ]
    base.update(opportunities=rows, allOpportunities=deepcopy(rows))
    equal = evaluate(base, measured=measured)
    assert 'RK10' not in {risk['code'] for risk in equal['risks']}

    import bi_agent.cockpit.opportunity_v2 as module
    cycles = {'a': 10, 'b': 10, 'c': 20}
    monkeypatch.setattr(module, '_p0_cycle', lambda opp, _measured: cycles[opp['id']])
    boundary = _data(targets=dict(amount=1000.0, energy=1000.0, byProduct={}, byAccount={}))
    boundary_rows = [dict(rows[0], id=key, contract='confirmed') for key in cycles]
    boundary.update(opportunities=boundary_rows, allOpportunities=deepcopy(boundary_rows))
    assert 'RK10' not in {risk['code'] for risk in evaluate(boundary, measured=measured)['risks']}


def test_bid_part_is_removed_from_metrics_rules_risks_and_causes():
    config = load_config()
    removed = config['excluded']
    assert removed['topic'] == '投标'
    for kind in ('metrics', 'rules', 'risks', 'causes', 'advice'):
        assert removed[kind] and not set(removed[kind]) & set(config[kind])
    gone = {code for kind in ('metrics', 'rules', 'risks', 'causes', 'advice') for code in removed[kind]}
    for link in config['links'].values():
        assert not (set(link['causes']) | set(link['advice'])) & gone
    for kind in ('metrics', 'risks', 'causes', 'advice'):
        for item in config[kind].values():
            assert not {value for value in item.values() if isinstance(value, list)
                        for value in value if isinstance(value, str)} & gone
    # Even with bid rows that used to raise RK09, no bid risk, cause or fact appears.
    opportunity = dict(id='opp-1', name='同名项目', accountId='account-1', tier='strategic',
                       productType='1', stage='11', status='0', contract='not_confirmed',
                       createdAt='2026-01-01', forecastAmount=10.0, forecastEnergy=5.0)
    bids = [dict(id=f'bid-{n}', name=f'项目{n}', inputAt='2025-01-01', winnerAt=None,
                 cycleDays=300 + n * 100, inProgress=True) for n in range(3)]
    value = evaluate(_data(opportunities=[opportunity], allOpportunities=[deepcopy(opportunity)],
                           bids=bids,
                           accounts=[dict(id='account-1', name='客户A', level='1', tier='strategic')]))
    assert not {'RK08', 'RK09'} & {risk['code'] for risk in value['risks']}
    assert not {'RK08', 'RK09'} & {item['code'] for item in value['riskCandidates']}
    assert 'RC02' not in value['causeOutcomes']
    assert not {'R10', 'R11', 'S03', 'bidAmbiguous'} & set(value['metrics'])
    fact_ids = {item['id'] for item in value['evidence']['facts']}
    assert not {f'opp-v2:metric:{code}' for code in ('R10', 'R11', 'S03', 'S03-P1', 'S03-P2', 'BID-AMBIGUOUS')} & fact_ids
    assert not any('投标' in item for item in value['result'].get('limitations') or [])


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


def test_ac10_uses_coverage_wording():
    general = _opportunity(id='g1', accountId='a1', tier='general', stage='13',
                           contract='not_confirmed', forecastAmount=10.0, forecastEnergy=5.0)
    data = _data(opportunities=[general], allOpportunities=[deepcopy(general)],
                 accounts=[dict(id='a1', name='一般客户', level='3', tier='general')])
    value = evaluate(data)
    ac10 = next(item for item in value['result']['recommendations']
                if item['adviceCode'] == 'AC10')
    assert ac10['action'] == '将重点跟踪覆盖率提升至 70%（当前 0.0%）'


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


def test_signed_coverage_is_over_the_forecast_total_not_the_target():
    # Ontology 2026-11-14 (R03 / BR-A02): coverage = signed forecast ÷ total
    # opportunity forecast, amount and energy separately; the target is not
    # the denominator, so a target far above the forecast does not lower it.
    signed = _opportunity(
        id='signed-1', contract='confirmed', forecastAmount=90.0, forecastEnergy=60.0,
        stage='14', createdAt='2026-01-01')
    unsigned = _opportunity(
        id='unsigned-1', contract='not_confirmed', forecastAmount=10.0, forecastEnergy=40.0,
        stage='14', createdAt='2026-01-01')
    data = _data(
        targets=dict(amount=1000.0, energy=1000.0,
                     byProduct={'1': dict(amount=1000.0, energy=1000.0)}, byAccount={}),
        opportunities=[signed, unsigned],
        allOpportunities=[deepcopy(signed), deepcopy(unsigned)],
    )
    value = evaluate(data, measured=date(2026, 11, 11))
    r03 = value['metrics']['R03']
    assert r03['signProgressAmount'] == 0.9 and r03['signProgressEnergy'] == 0.6
    # Amount coverage 90% is ahead of time progress (~86%), energy 60% is behind.
    assert r03['lagAmount'] < 0 < r03['lagEnergy']
    rk02 = next(risk for risk in value['risks'] if risk['code'] == 'RK02')
    assert '电量口径已签单覆盖率 60.0%' in rk02['description']
    assert '缺口' not in rk02['description']
    assert any('商机预测总额' in item for item in value['result']['limitations'])


def test_signed_coverage_and_unsigned_share_are_null_without_a_forecast_total():
    unsigned = _opportunity(id='u1', contract='not_confirmed', forecastAmount=0.0, forecastEnergy=None,
                            stage='14', createdAt='2026-01-01')
    value = evaluate(_data(opportunities=[unsigned], allOpportunities=[deepcopy(unsigned)]),
                     measured=date(2026, 11, 11))
    assert value['metrics']['R03']['signProgressAmount'] is None
    assert value['metrics']['R03']['signProgressEnergy'] is None
    assert 'RK02' not in {risk['code'] for risk in value['risks']}


def test_quarter_window_uses_the_unsigned_share_of_the_forecast_total():
    # Q4 window 25%: 30 unsigned of 100 forecast → 30% > 25%, while the
    # target gap (target 1000) must not be added to the share.
    signed = _opportunity(id='s', contract='confirmed', forecastAmount=70.0, forecastEnergy=99.0,
                          stage='14', createdAt='2026-01-01')
    unsigned = _opportunity(id='u', contract='not_confirmed', forecastAmount=30.0, forecastEnergy=1.0,
                            stage='14', createdAt='2026-01-01')
    data = _data(targets=dict(amount=1000.0, energy=1000.0, byProduct={}, byAccount={}),
                 opportunities=[signed, unsigned], allOpportunities=[deepcopy(signed), deepcopy(unsigned)])
    value = evaluate(data, measured=date(2026, 10, 2))
    rk02 = next(risk for risk in value['risks'] if risk['code'] == 'RK02')
    assert '第 4 季度未签单商机预测占比超过 25% 窗口阈值' in rk02['description']


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
    assert fetch[-1]['completed'] == fetch[-1]['total'] == 9
    assert len(card['result']['queryCatalog']) == 9
    assert '投标' not in {item['label'] for item in card['result']['queryCatalog']}
    assert any(item['label'] == '产品部销售缺口' for item in card['result']['queryCatalog'])
    assert all(item['sql'] for item in card['result']['queryCatalog'])




























def test_rc01_follows_br_c01_without_a_demand_confirmation_filter():
    # V3 BR-C01: an unsigned strategic P0 opportunity settles RC01 whatever
    # its demand approval status; demand confirmation is only a drill-down.
    opportunity = _opportunity(acneed='', stage='11', stage1End=None)
    data = _data(
        targets=dict(amount=100.0, energy=100.0, byProduct={}, byAccount={}),
        opportunities=[opportunity], allOpportunities=[deepcopy(opportunity)],
        accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic')],
    )
    value = evaluate(data)
    assert 'RC01' in {cause['causeCode'] for cause in value['result']['causes']}


def test_rc07_needs_an_explicit_empty_demand_input_per_br_c07():
    def causes(demand_input):
        focus = _opportunity(id='focus', forecastAmount=1.0, forecastEnergy=1.0)
        rest = _opportunity(id='rest', accountId='account-2', accountLevel='3', tier='general',
                            stage='11', stage1End=None, demandInput=demand_input,
                            forecastAmount=9.0, forecastEnergy=9.0)
        data = _data(opportunities=[focus, rest],
                     allOpportunities=[deepcopy(focus), deepcopy(rest)],
                     accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic')])
        return {cause['causeCode'] for cause in evaluate(data)['result']['causes']}
    assert 'RC07' in causes('0')
    assert 'RC07' not in causes('1')
    assert 'RC07' not in causes('')


def test_signing_follows_br_q02_order_linkage_not_the_contract_enum():
    config = load_config()
    assert 'BR-Q02' not in config.get('businessCorrections', {})
    seen = {}

    class Result:
        truncated = False
        rows = []

    class Reader:
        def run(self, sql, params, timeout_ms=0):
            seen[sql] = params
            return Result()

    class Snapshot:
        def __enter__(self):
            return Reader()

        def __exit__(self, *args):
            return False

    class Database:
        available = True
        config = SimpleNamespace(schema='ded_public', statement_timeout_ms=1000)

        def snapshot(self, **kwargs):
            return Snapshot()

        def run(self, sql, params, timeout_ms=0):
            return Reader().run(sql, params, timeout_ms)

    collect('2026', database=Database(), config=config, measurement_date='2026-11-11')
    opportunity_sql = [sql for sql in seen if 'AS contract_confirmation' in sql or 'AS contract_raw' in sql]
    assert len(opportunity_sql) >= 2  # detail + all; the full aggregate runs only on truncation
    for sql in opportunity_sql:
        assert 'new_contractconfirmation' not in sql
        assert 'EXISTS (SELECT 1 FROM' in sql and 'new_opportunity_id' in sql
    order_sql = next(sql for sql in seen if 'AS order_count' in sql)
    assert 'statecode' not in order_sql


def test_opportunity_queries_do_not_filter_on_approval_status_like_the_ontology():
    # The ontology metric SQL keeps every opportunity created by the cutoff;
    # the runtime SQL must not add new_approvalstatus = 3 on the opportunity
    # or the monthly forecast.  Truncating the detail also runs the full
    # aggregate, so all three opportunity queries are checked.
    config = load_config()
    seen = []

    class Result:
        def __init__(self, rows=(), truncated=False):
            self.rows = list(rows)
            self.truncated = truncated

    detail_row = dict(
        opportunity_id='o1', name='商机', account_id='a1', account_name='客户A', account_level='1',
        product_type='1', process_stage='11', acneed_status='', demand_input='', opportunity_status='0',
        contract_confirmation='0', created_at='2026-01-01', stage1_end=None, stage2_end=None,
        stage3_end=None, stage4_end=None, stage5_end=None, owner_id='u1', amount_yuan=1e8,
        forecast_amount_full_yuan=1e8, energy_gwh=1.0, month_rows=1, past_rows=0,
        past_amount_rows=0, energy_rows=1)

    class Reader:
        def run(self, sql, params, timeout_ms=0):
            seen.append(sql)
            if 'agg.month_rows, agg.energy_rows' in sql:
                return Result([detail_row], truncated=True)
            return Result()

    class Snapshot:
        def __enter__(self):
            return Reader()

        def __exit__(self, *args):
            return False

    class Database:
        available = True
        config = SimpleNamespace(schema='ded_public', statement_timeout_ms=1000)

        def snapshot(self, **kwargs):
            return Snapshot()

        def run(self, sql, params, timeout_ms=0):
            return Reader().run(sql, params, timeout_ms)

    collect('2026', database=Database(), config=config, measurement_date='2026-11-11')
    opportunity_sql = [sql for sql in seen if 'AS contract_confirmation' in sql or 'AS contract_raw' in sql]
    assert len(opportunity_sql) == 3
    for sql in opportunity_sql:
        assert 'new_approvalstatus =' not in sql and 'new_approvalstatus=' not in sql


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
            if 'new_target_esb' in sql and "'C05'" not in sql:
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
    # B01 energy reads new_month*_power and converts it with the ontology's
    # target_power_units_per_gwh (kWh ÷ 10^6): 30,000,000 kWh = 30 GWh.
    assert data['targets']['energy'] == 30.0


def test_target_energy_conversion_comes_from_the_ontology_sql():
    import re
    config = load_config()
    energy = config['overrides']['targetEnergy']
    b01 = config['metrics']['B01']['sql']
    declared = int(re.search(r"CAST\((\d+) AS DECIMAL\) AS target_power_units_per_gwh", b01).group(1))
    assert declared == 1_000_000  # BR-Q11: kWh ÷ 10^6
    assert energy['unitsPerGwh'] == declared and energy['nativeUnit'] == 'kWh'
    assert energy['fieldPattern'] == 'new_month{i}_power'
    assert {'B01', 'R01', 'R08', 'C03'} <= set(energy['metrics'])


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
            if 'agg.month_rows, agg.energy_rows' in sql:
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
            if 'agg.month_rows, agg.energy_rows' in sql:
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
    # BR-Q01: forecast amount only, so no past-month actuals are carried.
    assert 'pastAmountRows' not in data['opportunityAggregates'][0]


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
    assert fetch and fetch[-1]['completed'] == fetch[-1]['total'] == 9
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
    assert len(catalog) == 9
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
    value = _strategic_value(accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic'),
                                     dict(id='account-9', name='战略客户B', level='1', tier='strategic')])
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
        if request['kind'] == 'inference':
            return dict(causes=[dict(title='推理根因', description='依据取数推理', dataGaps='')])
        return dict(established=request['kind'] == 'cause', reason='进展文本显示卡点')
    judged = _judged(value, judge)
    causes = {item['code']: item for item in judged['ontologyJudgement']['causes']
              if not item.get('inferred')}
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
    assert [item['code'] for item in judgement['causes'] if not item.get('inferred')] == list(config['causes'])
    assert [item['code'] for item in judgement['advice']] == list(config['advice'])
    labels = {item['statusLabel'] for group in judgement.values() if isinstance(group, list)
              for item in group if isinstance(item, dict)}
    # The model's "no" on items whose inputs are missing reads as undecided.
    assert {'命中（规则判定）', '未命中（规则判定）', '无法判定（模型）'} <= labels
    assert judged['summary'].startswith('本轮 8 项本体风险中')


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


def _explained_and_orphan_risks(judged):
    causes = judged['ontologyJudgement']['causes']
    explained = {code for item in causes if item['established'] is True and not item.get('inferred')
                 for code in item.get('linkedRisks', [])}
    established = [item['riskCode'] for item in judged['findings']]
    return explained, [code for code in established if code not in explained]


def test_risks_without_an_ontology_cause_get_model_inferred_causes():
    value = _strategic_value()
    requests = []

    def judge(request):
        requests.append(request)
        if request['kind'] == 'inference':
            return dict(causes=[dict(title=f"{request['code']} 推理根因", description='依据 R02 数值推理',
                                     dataGaps='需补客户拜访记录')], note='')
        return dict(established=False, reason='模型判定不成立')
    judged = _judged(value, judge)
    explained, orphans = _explained_and_orphan_risks(judged)
    inference = [item for item in requests if item['kind'] == 'inference']
    # One call per established risk that no ontology cause explains, and only those.
    assert orphans and [item['code'] for item in inference] == orphans
    assert not {item['code'] for item in inference} & explained
    first = inference[0]
    assert first['risk']['code'] == orphans[0] and 'observed' in first['risk']
    linked = load_config()['links'][orphans[0]]['causes']
    assert [item['code'] for item in first['ontologyCauses']] == [code for code in load_config()['causes']
                                                                if code in linked]
    assert all(item['status'] for item in first['ontologyCauses'])
    assert 'metrics' in first['data']
    inferred = [item for item in judged['causes'] if item['inferred']]
    assert [item['causeCode'] for item in inferred] == [f'{code}-AI1' for code in orphans]
    assert all(item['decidedBy'] == 'model' and item['kind'] == 'hypothesis' for item in inferred)
    assert inferred[0]['riskCodes'] == [orphans[0]] and inferred[0]['missingEvidence'] == ['需补客户拜访记录']
    assert [d['causeCode'] for d in judged['analysisDimensions']][-len(inferred):] == [
        item['causeCode'] for item in inferred]
    # Inferred causes carry no ontology advice.
    assert not any(set(item['causeIds']) & {cause['id'] for cause in inferred}
                   for item in judged['recommendations'])
    trace = [item for item in judged['ontologyJudgement']['causes'] if item.get('inferred')]
    assert {item['statusLabel'] for item in trace} == {'模型推理（本体根因未命中）'}
    assert judged['ontologyJudgement']['inferenceCalls'] == len(orphans)
    assert '由模型在本体根因未命中时推理' in judged['summary']


def test_a_failed_inference_is_reported_and_skipped():
    value = _strategic_value()

    def judge(request):
        if request['kind'] == 'inference':
            raise TimeoutError('模型超时')
        return dict(established=False, reason='模型判定不成立')
    judged = _judged(value, judge)
    _, orphans = _explained_and_orphan_risks(judged)
    assert orphans
    assert not any(item['inferred'] for item in judged['causes'])
    failed = [item for item in judged['ontologyJudgement']['causes'] if item.get('inferred')]
    assert [item['code'] for item in failed] == [f'{code}-AI' for code in orphans]
    assert all(item['statusLabel'] == '判断失败，已跳过' for item in failed)
    assert any(line.startswith(f'根因 {orphans[0]}-AI：') for line in judged['ontologyJudgement']['failures'])
    assert judged['findings']


def test_an_empty_inference_adds_no_cause_but_keeps_the_models_note():
    def judge(request):
        if request['kind'] == 'inference':
            return dict(causes=[], note='缺少客户拜访数据')
        return dict(established=False, reason='模型判定不成立')
    judged = _judged(_strategic_value(), judge)
    assert not any(item['inferred'] for item in judged['causes'])
    notes = [item for item in judged['ontologyJudgement']['causes'] if item.get('inferred')]
    assert notes and all(item['reason'] == '缺少客户拜访数据' and item['established'] is None for item in notes)
    assert {item['statusLabel'] for item in notes} == {'模型未能推理'}


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
    assert "DATE '2026-01-01' AS start_date" in sql and "DATE '2027-01-01' AS end_exclusive" in sql
    assert "'2025-01-01'" not in sql
    assert "TIMESTAMP '2026-11-11 23:59:59'" in sql and 'CURRENT_TIMESTAMP' not in sql
    assert not sql.endswith(';') and '%' not in sql
    other = _ontology_metric_sql(load_config(), 'C05', 2026, date(2026, 11, 11), schema='crm_copy')
    assert 'crm_copy.' in other and 'ded_public.' not in other
    assert _ontology_metric_sql(load_config(), 'NOPE', 2026, date(2026, 11, 11)) == ''


def test_every_ontology_metric_sql_binds_in_either_period_format():
    from bi_agent.cockpit.opportunity_v2 import _ontology_metric_sql
    config = load_config()
    for code, metric in config['metrics'].items():
        sql = _ontology_metric_sql(config, code, 2025, date(2025, 12, 31))
        assert sql.startswith('WITH'), code
        assert "DATE '2025-01-01' AS start_date" in sql and "DATE '2026-01-01' AS end_exclusive" in sql, code
        assert 'CURRENT_TIMESTAMP' not in sql.upper(), code
    # A literal "%" reaches the database unchanged: psycopg turns "%%" back into "%".
    from psycopg._queries import PostgresQuery
    from psycopg.adapt import Transformer
    c07 = _ontology_metric_sql(config, 'C07', 2025, date(2025, 12, 31))
    query = PostgresQuery(Transformer())
    query.convert(c07, ())
    assert '超平均周期 50% 的未签单商机' in query.query.decode('utf-8')
    # The older DATE '…' layout still binds.
    old = dict(config, metrics={'X': dict(code='X', sql=(
        "WITH parameters AS (SELECT DATE '2025-01-01' AS start_date, DATE '2026-01-01' AS end_exclusive, "
        "CURRENT_TIMESTAMP::timestamp AS observed_at) SELECT * FROM parameters"))})
    bound = _ontology_metric_sql(old, 'X', 2024, date(2024, 6, 30))
    assert "DATE '2024-01-01' AS start_date" in bound and "TIMESTAMP '2024-06-30 23:59:59'" in bound


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
    assert seen[0][1].startswith(judgement.ROLE_PROMPT)
    entry = judgement._ask(judgement.default_item_judge, dict(kind='cause', code='RC02'), None, '1/1')
    assert entry['decidedBy'] == 'none' and entry['established'] is None
    assert entry['error'].startswith('模型没有作答，而是发起了工具调用')
    assert entry['error'].endswith('已跳过')


def test_item_judge_uses_the_inference_prompt_for_unexplained_risks(monkeypatch):
    import bi_agent.llm.provider as provider
    from bi_agent.cockpit import opportunity_judgement as judgement
    from bi_agent.cockpit import opportunity_v2 as module

    seen = []

    def fake_stream(messages, system_prompt, allowed_tools, *args, **kwargs):
        seen.append((allowed_tools, system_prompt))
        return iter([dict(type='text_delta', text='{"causes": [{"title": "拜访不足", "description": "R09=30", '
                                                   '"dataGaps": ""}], "note": ""}'),
                     dict(type='message_end', stop_reason='end_turn', finish_reason='stop', usage={})])

    monkeypatch.setattr(provider, 'stream_message', fake_stream)
    monkeypatch.setattr(module, '_model_candidate_keys', lambda: ['route-a'])
    answer = judgement._infer(judgement.default_item_judge,
                              dict(kind='inference', code='RK07'), None, '1/1')
    assert seen[0][0] == [] and seen[0][1] == judgement.system_prompt(judgement.INFER_PROMPT)
    assert answer['causes'] == [dict(title='拜访不足', description='R09=30', dataGaps='')]
    assert answer['model'] == 'route-a'


def test_rule_first_card_is_delivered_to_the_page_as_judged():
    from bi_agent.cockpit.delivery import project_card, publication_payload
    from bi_agent.cockpit.opportunity_judgement import judge_card
    from bi_agent.cockpit.page_cache import compact_analysis
    value = _strategic_value(accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic'),
                                     dict(id='account-9', name='战略客户B', level='1', tier='strategic')])
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


def _captured_sql():
    """Run collect against a fake reader and return every SQL with its params.

    The detail is returned truncated so the full aggregate query runs too.
    """
    seen = {}

    class Result:
        def __init__(self, rows=(), truncated=False):
            self.rows = list(rows)
            self.truncated = truncated

    detail_row = dict(
        opportunity_id='o1', name='商机', account_id='a1', account_name='客户A', account_level='1',
        product_type='1', process_stage='11', acneed_status='', demand_input='', opportunity_status='0',
        contract_confirmation='0', created_at='2026-01-01', owner_id='u1', amount_yuan=1e8,
        forecast_amount_full_yuan=1e8, energy_gwh=1.0, month_rows=1, energy_rows=1)

    class Reader:
        def run(self, sql, params, timeout_ms=0):
            seen[sql] = list(params)
            if 'agg.month_rows, agg.energy_rows' in sql:
                return Result([detail_row], truncated=True)
            return Result()

    class Snapshot:
        def __enter__(self):
            return Reader()

        def __exit__(self, *args):
            return False

    class Database:
        available = True
        config = SimpleNamespace(schema='ded_public', statement_timeout_ms=1000)

        def snapshot(self, **kwargs):
            return Snapshot()

    collect('2025', database=Database(), config=load_config(), measurement_date='2025-12-31')
    return seen


def test_forecast_follows_br_q01_latest_version_forecast_amount_only():
    seen = _captured_sql()
    forecast = [sql for sql in seen if 'fr AS (' in sql]
    assert len(forecast) == 2  # detail and full aggregate
    for sql in forecast:
        # Latest version per opportunity-month, kept with rn = 1.
        assert "PARTITION BY x.new_opportunity_id, date_trunc('month', x.new_accountdate::timestamp)" in sql
        assert 'ORDER BY x.createdon DESC NULLS LAST, x.modifiedon DESC NULLS LAST' in sql
        assert 'WHERE m.rn = 1' in sql
        # Forecast amount only, no actuals, no state filter.
        assert 'new_amt_rmb' not in sql
        assert 'statecode' not in sql.split(') SELECT', 1)[0]
        # Year for the forecast window, then the measurement day for the cutoff.
        assert seen[sql] == [2025, date(2025, 12, 31)]


def test_targets_keep_the_latest_row_per_opportunity_and_year():
    sql = next(sql for sql in _captured_sql() if 'new_target_esb' in sql)
    assert ("PARTITION BY COALESCE(NULLIF(BTRIM(x.new_opportunity_id::text), ''), x.new_targetid::text), "
            "x.new_year ORDER BY x.createdon DESC NULLS LAST, x.new_targetid DESC NULLS LAST") in sql
    assert 'WHERE t.rn = 1' in sql and 'x.new_targetid IS NOT NULL' in sql


def test_opportunity_and_customer_rows_follow_the_ontology_base_tables():
    seen = _captured_sql()
    opportunity = [sql for sql in seen if 'AS contract_confirmation' in sql or 'AS contract_raw' in sql]
    assert len(opportunity) == 3
    for sql in opportunity:
        # One row per id, latest first; account level only from the customer.
        assert 'SELECT DISTINCT ON (x.opportunityid) x.*' in sql
        assert 'SELECT DISTINCT ON (y.accountid) y.*' in sql
        assert "COALESCE(a.new_accountlevel::text, '') AS account_level" in sql
        assert 'o.new_accountlevel' not in sql
        # The cutoff is the end of the measurement day; unknown creation kept.
        assert '(o.createdon IS NULL OR o.createdon < (%s::date + 1))' in sql
    customers = next(sql for sql in seen if 'AS opportunity_count' in sql and 'cov' in sql)
    coverage = customers.split('LEFT JOIN (SELECT z.', 1)[1].split(') cov', 1)[0]
    # R09 counts every linked opportunity: no creation, state or approval filter.
    assert 'createdon' not in coverage and 'statecode' not in coverage and 'approval' not in coverage


def test_r09_counts_strategic_customers_with_no_linked_opportunity_at_all():
    accounts = [
        dict(id='a-new', name='今年新建无商机', level='1', tier='strategic', createdAt='2026-03-01', opportunityCount=0),
        dict(id='a-old', name='往年创建无商机', level='1', tier='strategic', createdAt='2019-03-01', opportunityCount=0),
        dict(id='a-closed', name='只有已关闭商机', level='1', tier='strategic', createdAt='2019-03-01', opportunityCount=2),
    ]
    value = evaluate(_data(accounts=accounts))
    # Creation year does not matter; a customer with any linked opportunity is not counted.
    assert value['metrics']['R09'] == dict(count=2)
    rk07 = next(risk for risk in value['risks'] if risk['code'] == 'RK07')
    assert '2 家没有任何关联商机' in rk07['description']


def test_r08_pairs_customer_and_product_and_never_reads_a_missing_side_as_zero():
    opportunities = [
        _opportunity(id='o1', accountId='c1', productType='1', forecastAmount=3.0, forecastEnergy=1.0, monthRows=1),
        _opportunity(id='o2', accountId='c1', productType='2', forecastAmount=9.0, forecastEnergy=9.0, monthRows=1),
        _opportunity(id='o3', accountId='c2', productType='1', forecastAmount=1.0, forecastEnergy=1.0, monthRows=1),
    ]
    targets = dict(amount=30.0, energy=30.0, byProduct={}, byAccount={}, byAccountProduct={
        # c1 电芯: gap 2 / 1; c1 PACK: target below forecast, no gap.
        'c1|1': dict(accountId='c1', productType='1', amount=5.0, energy=2.0),
        'c1|2': dict(accountId='c1', productType='2', amount=4.0, energy=4.0),
        # c2 has no 电芯 target: the pair's gap stays empty, not 0 − 1.
        'c2|2': dict(accountId='c2', productType='2', amount=8.0, energy=8.0),
        # c3 has a target but no forecast: no opportunity, so BR-A06 does not apply.
        'c3|1': dict(accountId='c3', productType='1', amount=6.0, energy=6.0),
    })
    value = evaluate(_data(targets=targets, opportunities=opportunities,
                           allOpportunities=deepcopy(opportunities)))
    assert value['metrics']['R08'] == dict(count=1, pairs=1)
    rk06 = next(risk for risk in value['risks'] if risk['code'] == 'RK06')
    assert rk06['impact'] == dict(amount=2.0, energy=1.0, count=1)


def test_ap_supplement_is_off_unless_explicitly_enabled():
    source = (Path(__file__).resolve().parents[1] / 'bi_agent/cockpit/frozen.py').read_text(encoding='utf-8')
    assert "os.getenv('COCKPIT_OPPORTUNITY_V2_AP_SUPPLEMENT', '0').strip().lower() in {'1', 'true', 'yes', 'on'}" in source


def test_every_card_model_call_starts_with_the_sales_operations_role(monkeypatch):
    from bi_agent.cockpit import opportunity_judgement as judgement
    role = judgement.ROLE_PROMPT
    assert role.startswith('你是储能业务销售运营分析师')
    for phrase in ('影响对象', '目标或阈值的差距', '「待核实」', '责任角色', '复检指标'):
        assert phrase in role
    for task in (judgement.JUDGE_PROMPT.format(kind='风险'), judgement.INFER_PROMPT):
        prompt = judgement.system_prompt(task)
        assert prompt.startswith(role) and '本次任务：' in prompt
        # One identity only: the task text no longer opens with its own "你是…".
        assert prompt.count('你是') == 1
    assert '待核实' in judgement.INFER_PROMPT
    monkeypatch.setenv('COCKPIT_OPPORTUNITY_ROLE_PROMPT', '你是测试角色。')
    assert judgement.system_prompt('x').startswith('你是测试角色。')
    monkeypatch.setenv('COCKPIT_OPPORTUNITY_ROLE_PROMPT', '  ')
    assert judgement.role_prompt() == role


def test_the_opportunity_card_has_no_section_summaries_but_semantic_control():
    from bi_agent.cockpit import frozen
    assert 'opportunity-risk' not in frozen.SECTION_SUMMARY_STAGES
    source = (Path(__file__).resolve().parents[1] / 'bi_agent/cockpit/frozen.py').read_text(encoding='utf-8')
    assert 'semantic=semantic_rewriter if (enabled and semantic) else None' in source


def test_product_signing_lag_uses_the_products_forecast_total():
    # R05 condition ②: 电芯 forecast 100 is above its target 50 (condition ①
    # does not hold); 50 signed of 100 is 50% coverage, behind ~86% time
    # progress, so RK04 holds.  Over the target it would read 100%.
    signed = _opportunity(id='s', contract='confirmed', productType='1', forecastAmount=50.0,
                          forecastEnergy=50.0, stage='14', createdAt='2026-01-01')
    pending = _opportunity(id='p', contract='not_confirmed', productType='1', forecastAmount=50.0,
                           forecastEnergy=50.0, stage='14', createdAt='2026-01-01')
    data = _data(targets=dict(amount=50.0, energy=50.0,
                              byProduct={'1': dict(amount=50.0, energy=50.0)}, byAccount={}),
                 opportunities=[signed, pending], allOpportunities=[deepcopy(signed), deepcopy(pending)])
    value = evaluate(data, measured=date(2026, 11, 11))
    assert 'RK04' in {risk['code'] for risk in value['risks']}


def _requests_for(value):
    from bi_agent.cockpit.opportunity_judgement import judge_card
    seen = []

    def judge(request):
        seen.append(request)
        return dict(causes=[]) if request['kind'] == 'inference' else dict(established=False, reason='x')
    judged = judge_card(value, load_config(), judge=judge)
    return seen, judged


def test_inference_reads_only_the_chain_metrics_with_their_ontology_caliber():
    seen, _ = _requests_for(_strategic_value())
    inference = [r for r in seen if r['kind'] == 'inference']
    assert inference
    config = load_config()
    for request in inference:
        risk_codes = [c for c in config['risks'][request['code']]['indicators'].split('、')]
        allowed = set(risk_codes)
        for cause in config['links'][request['code']]['causes']:
            allowed |= set(config['causes'][cause]['indicators'].split('、'))
        metrics = request['data']['metrics']
        # Only the metrics of this risk and its ontology causes, never the whole card.
        assert set(request['data']) == {'metrics'} and isinstance(metrics, list)
        assert {m['code'] for m in metrics} <= allowed
        for metric in metrics:
            assert metric['name'] == config['metrics'][metric['code']]['name']
            if 'values' in metric:
                assert metric['definition'] and all(v.get('unit') for v in metric['values'])
            else:
                assert metric['note'] == '本轮未取数，不能引用'
        assert request['risk']['ontology']['ontologyRule']['code'] == config['risks'][request['code']]['rule']
        assert all(cause['ontology']['code'] == cause['code'] for cause in request['ontologyCauses'])


def test_a_data_gap_in_the_ontology_cause_is_reported_not_inferred():
    # RK07 holds; its only ontology cause RC09 lacks recent-activity data.
    value = _strategic_value(accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic'),
                                       dict(id='account-9', name='战略客户B', level='1', tier='strategic')])
    assert value['causeOutcomes']['RC09']['ruleStatus'] == 'insufficient'
    seen, judged = _requests_for(value)
    assert 'RK07' in {f['riskCode'] for f in judged['findings']}
    assert not [r for r in seen if r['kind'] == 'inference' and r['code'] == 'RK07']
    entry = next(e for e in judged['ontologyJudgement']['causes'] if e['code'] == 'RK07-AI')
    assert entry['statusLabel'] == '待补数据，未推理' and entry['established'] is None
    assert entry['reason'].startswith('本体根因 RC09 战略客户开拓不足 缺少判定数据')
    assert not any(c['causeCode'].startswith('RK07-AI') for c in judged['causes'])


def test_item_requests_carry_the_ontology_and_ask_for_null_on_missing_data():
    from bi_agent.cockpit import opportunity_judgement as judgement
    seen, _ = _requests_for(_strategic_value())
    for request in [r for r in seen if r['kind'] in ('risk', 'cause')]:
        element = request['ontology']['element']
        assert element['code'] == request['code'] and element['ontologyRule']['description']
        assert isinstance(request['ontology']['metrics'], list)
    prompt = judgement.JUDGE_PROMPT.format(kind='风险')
    assert 'established 必须返回 null，不得返回 false' in prompt
    assert '按 values 中给出的单位原样引用，不得换算或改写单位' in prompt
    assert '不要把它换一种说法重新提出' in judgement.INFER_PROMPT


def test_every_query_names_the_metrics_it_feeds():
    from bi_agent.cockpit.opportunity_v2 import _QUERY_METRICS
    metrics = set(load_config()['metrics'])
    assert _QUERY_METRICS['客户'] == ['R09']
    assert all(set(codes) <= metrics for codes in _QUERY_METRICS.values())
    source = (Path(__file__).resolve().parents[1] / 'bi_agent/cockpit/opportunity_v2.py').read_text(encoding='utf-8')
    assert 'metricCodes=list(_QUERY_METRICS.get(label, []))' in source


def test_a_model_no_on_missing_inputs_is_recorded_as_undecided():
    from bi_agent.cockpit.opportunity_judgement import _ask
    missing = _ask(lambda request: dict(established=False, reason='没有拜访记录'),
                   dict(kind='cause', code='RC09', data=dict(missingInputs=['近期线索', '拜访'])), None, '1/1')
    assert missing['established'] is None
    assert missing['reason'].startswith('判定所需数据缺失（近期线索、拜访），按无法判定处理')
    complete = _ask(lambda request: dict(established=False, reason='数据显示不成立'),
                    dict(kind='cause', code='RC04', data=dict(missingInputs=[])), None, '1/1')
    assert complete['established'] is False
    held = _ask(lambda request: dict(established=True, reason='成立'),
                dict(kind='cause', code='RC09', data=dict(missingInputs=['拜访'])), None, '1/1')
    assert held['established'] is True


def test_semantic_control_rewords_rows_but_never_their_numbers():
    from bi_agent.cockpit.opportunity_judgement import control_risk_rows
    rows = [dict(riskCode='RK01', title='商机预测覆盖不足', riskLevel='高', decidedBy='rule',
                 description='金额缺口 12.30 亿元（目标 100.00 亿元、预测 87.70 亿元）。'),
            dict(riskCode='RK07', title='战略客户待突破（无商机）', riskLevel='高', decidedBy='rule',
                 description='战略客户中有 30 家没有任何关联商机。')]
    seen = []

    def rewrite(payload):
        seen.append(payload)
        return dict(items=[
            dict(code='RK01', description='商机预测较年度目标 100 亿元少 12.3 亿元（预测 87.7 亿元），覆盖不足。'),
            dict(code='RK07', description='31 家战略客户尚无商机。')])
    report = control_risk_rows(rows, load_config(), rewrite)
    # Same numbers, reworded: taken.  A changed number: the rule row stays.
    assert rows[0]['description'].startswith('商机预测较年度目标 100 亿元')
    assert rows[0]['ruleDescription'] == '金额缺口 12.30 亿元（目标 100.00 亿元、预测 87.70 亿元）。'
    assert rows[0]['semanticControl'] == 'model'
    assert rows[1]['description'] == '战略客户中有 30 家没有任何关联商机。' and rows[1]['semanticControl'] == 'kept'
    assert report['status'] == 'partial' and report['issues'] == ['RK07：数字与原句不一致，保留规则原句']
    # The model sees every row and each risk's ontology definition and rule.
    assert [item['code'] for item in seen[0]['items']] == ['RK01', 'RK07']
    assert seen[0]['ontology'][0]['definition'] and seen[0]['ontology'][0]['rule']

    def broken(payload):
        raise TimeoutError('slow')
    rows2 = [dict(rows[1])]
    failed = control_risk_rows(rows2, load_config(), broken)
    assert failed['status'] == 'failed' and rows2[0]['semanticControl'] == 'kept'
    assert control_risk_rows(rows2, load_config(), None)['status'] == 'skipped'


def test_each_risk_and_cause_lists_only_the_queries_its_evidence_came_from():
    from bi_agent.cockpit.opportunity_judgement import link_queries
    catalog = [dict(executionId='q-target', label='销售目标', metricCodes=['B01', 'R01', 'R05', 'R06', 'R08']),
               dict(executionId='q-opp', label='商机预测', metricCodes=['B02', 'R01', 'R08', 'P0-01', 'P0-02']),
               dict(executionId='q-account', label='客户', metricCodes=['R09']),
               dict(executionId='q-orders', label='订单关联', metricCodes=[])]
    result = dict(queryCatalog=catalog, findings=[
        dict(riskCode='RK07', evidenceIds=['opp-v2:metric:R09', 'opp-v2:account:a1'], metricCodes=['RK07', 'R09']),
        dict(riskCode='RK06', evidenceIds=['opp-v2:metric:R08'], metricCodes=['RK06', 'R08']),
        dict(riskCode='RK10', evidenceIds=['opp-v2:metric:P0-01', 'opp-v2:metric:P0-02'], metricCodes=['RK10'])],
        causes=[dict(causeCode='RC09', evidenceIds=['opp-v2:metric:R09']),
                dict(causeCode='RK07-AI1', inferred=True, evidenceIds=['opp-v2:metric:R09'])],
        analysisDimensions=[dict(causeCode='RC09', evidenceIds=['opp-v2:metric:R09'])])
    link_queries(result, load_config())
    findings = {f['riskCode']: f['queryIds'] for f in result['findings']}
    assert findings == dict(RK07=['q-account'], RK06=['q-target', 'q-opp'], RK10=['q-opp'])
    assert [c['queryIds'] for c in result['causes']] == [['q-account'], []]
    assert result['analysisDimensions'][0]['queryIds'] == ['q-account']
    from bi_agent.cockpit.opportunity_v2 import _QUERY_METRICS
    assert _QUERY_METRICS['订单关联'] == [] and _QUERY_METRICS['全部商机'] == []


def test_risk_rows_take_their_names_from_the_ontology_risk_sheet():
    config = load_config()
    assert config['risks']['RK03']['name'] == '战略及重点客户存在缺口'
    assert config['risks']['RK07']['name'] == '战略客户签单存在缺口，且较多待突破（无商机）'
    assert config['risks']['RK10']['description'] == '商机获取阶段单笔周期超过平均周期 1.5 倍'
    findings = _strategic_value()['result']['findings']
    assert findings
    for finding in findings:
        name = config['risks'][finding['riskCode']]['name']
        assert finding['title'].startswith(f"{finding['riskCode']} {name}")
    # A renamed risk in the ontology renames the card's row.
    renamed = load_config()
    renamed['risks']['RK03'] = dict(renamed['risks']['RK03'], name='改名后的风险')
    from bi_agent.cockpit.opportunity_v2 import _risk_name
    assert _risk_name(renamed, 'RK03') == '改名后的风险'


def test_the_ontology_storage_customer_scope_is_configured_from_br_q04():
    config = load_config()
    scope = config['overrides']['storageCustomerScope']
    assert scope['enabled'] is True and scope['source'] == 'BR-Q04'
    assert scope['rule'].startswith('储能客户范围：最新商机负责人ownerid→团队人员systemuserid→团队teamid')
    assert set(scope['metrics']) == {'R04', 'R08', 'R09', 'C01', 'C06', 'C08', 'C09'}
    assert config['fields']['LE05']['owninguser']['column'] == 'owninguser'
    assert config['overrides']['dynamicCycle']['completedOnly'] is True
    assert config['risks']['RK07']['description'].startswith('仅储能客户名单内。')


def test_focus_tracking_counts_only_storage_customers():
    inside = _opportunity(id='in', storageCustomer=True)
    outside = _opportunity(id='out', accountId='account-2', storageCustomer=False)
    value = evaluate(_data(opportunities=[inside, outside],
                           allOpportunities=[deepcopy(inside), deepcopy(outside)],
                           accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic')]))
    facts = {f['id']: f for f in value['evidence']['facts']}
    # R04 keeps the customer in the 储能客户名单 only; B02 / R02 still cover every opportunity.
    assert facts['opp-v2:metric:R04-COUNT']['value'] == 1
    assert facts['opp-v2:metric:R04-AMOUNT']['value'] == 10.0
    assert facts['opp-v2:metric:B02-AMOUNT']['value'] == 20.0
    assert facts['opp-v2:metric:R04-COUNT']['definition'].startswith('储能客户名单内（BR-Q04）')
    # Inputs collected without the scope flag are not narrowed.
    legacy = evaluate(_data(opportunities=[_opportunity(id='a'), _opportunity(id='b')],
                            allOpportunities=[_opportunity(id='a'), _opportunity(id='b')]))
    legacy_facts = {f['id']: f for f in legacy['evidence']['facts']}
    assert legacy_facts['opp-v2:metric:R04-COUNT']['value'] == 2


def test_customer_gap_ignores_customers_outside_the_storage_list():
    def run(flag):
        pair = dict(accountId='account-1', productType='1', amount=50.0, energy=None)
        if flag is not None:
            pair['storageCustomer'] = flag
        return evaluate(_data(
            targets=dict(amount=100.0, energy=100.0, byProduct={}, byAccount={},
                         byAccountProduct={'account-1|1': pair}),
            opportunities=[_opportunity(monthRows=1)], allOpportunities=[_opportunity()]))
    facts = lambda value: {f['id']: f for f in value['evidence']['facts']}
    assert facts(run(True))['opp-v2:metric:R08']['value'] == 1
    assert facts(run(False))['opp-v2:metric:R08']['value'] == 0
    assert 'RK06' not in {f['riskCode'] for f in run(False)['result']['findings']}
    assert facts(run(None))['opp-v2:metric:R08']['value'] == 1


def test_stage_mean_counts_only_completed_samples():
    # Two finished P0 stages (10 and 20 days) and one still running for 300 days.
    done_a = _opportunity(id='a', stage='11', createdAt='2026-01-01', stage1End='2026-01-11', stage2End=None, stage3End=None)
    done_b = _opportunity(id='b', stage='11', createdAt='2026-01-01', stage1End='2026-01-21', stage2End=None, stage3End=None)
    running = _opportunity(id='c', stage='11', createdAt='2026-01-15', stage1End=None, stage2End=None, stage3End=None)
    value = evaluate(_data(opportunities=[done_a, done_b, running],
                           allOpportunities=[deepcopy(done_a), deepcopy(done_b), deepcopy(running)]))
    facts = {f['id']: f for f in value['evidence']['facts']}
    assert facts['opp-v2:metric:P0-01']['value'] == 15.0
    assert '在途不计入均值' in facts['opp-v2:metric:P0-01']['definition']
    # The running stage is still compared with that mean and is overdue.
    assert facts['opp-v2:metric:P0-02']['value'] == 1
    rk10 = next(r for r in value['risks'] if r['code'] == 'RK10')
    assert '已结束样本平均周期 1.5 倍' in rk10['description'] and '平均周期 15.0 天' in rk10['description']


def test_storage_scope_sql_follows_owner_team_member_customer():
    source = (Path(__file__).resolve().parents[1] / 'bi_agent/cockpit/opportunity_v2.py').read_text(encoding='utf-8')
    for fragment in ("sa.{ac[account_owner_field]}::text IN (", "su.{sm['teamid']}::text IN (",
                     "stm.{sm['systemuserid']}::text IN (", "sow.{oc[owner_field]}::text FROM {opp_src} sow",
                     "(sc.account_id IS NOT NULL) AS storage_customer",
                     "AND a.{ac['accountid']}::text IN (SELECT account_id FROM {storage_sql} sc)",
                     "GROUP BY 1,2,3,4,5,6,7"):
        assert fragment in source, fragment
