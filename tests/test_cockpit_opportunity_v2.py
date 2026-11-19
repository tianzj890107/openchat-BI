import re
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


def _coverage(progress=(0.0, 0.0), forecast=(0.0, 0.0)):
    return dict(progressAmount=progress[0], progressEnergy=progress[1],
                forecastAmount=forecast[0], forecastEnergy=forecast[1],
                rows=1, missingAmountRows=0, missingEnergyRows=0)


def _annual(progress=(0.0, 0.0), forecast=(10.0, 5.0), products=None, accounts=None, status='ok'):
    """The R03 全年覆盖预测 split: 进度 (signed, past months) and 预测 (from the observation month)."""
    return dict(status=status,
                products={'all': _coverage(progress, forecast),
                          **{key: _coverage(*parts) for key, parts in (products or {}).items()}},
                accounts={key: _coverage(*parts) for key, parts in (accounts or {}).items()})


def _data(**updates):
    value = dict(
        period='2026', measurementDate='2026-11-11',
        targets=dict(amount=100.0, energy=100.0, byProduct={}, byAccount={}),
        opportunities=[], allOpportunities=[], accounts=[], bids=[], progress={},
        errors=[], annualCoverage=_annual(),
    )
    value.update(updates)
    return value


def _ontology_cause_config():
    """The config with the ontology cause matching path (not the AI analysis)."""
    config = deepcopy(load_config())
    config['overrides']['causeAnalysis'] = dict(mode='ontology')
    return config


def _strategic_value(**updates):
    updates.setdefault('accounts', [dict(id='account-1', name='战略客户A', level='1', tier='strategic')])
    return evaluate(_data(
        opportunities=[_opportunity()], allOpportunities=[deepcopy(_opportunity())],
        **updates,
    ))


def _judge_no(request):
    return dict(established=False, reason='测试：判定不成立')


def test_v3_config_is_the_1117_ontology_with_three_risks():
    config = load_config()
    assert config_version() == 'opportunity-v3-rules-15'
    assert len(config_digest()) == 64
    assert config['source']['path'].endswith('亿纬锂能本体文件_1117.xlsx')
    # 第三版执行口径：只保留 RK01、RK06、RK11；RK02 签单进度滞后已去掉。
    assert list(config['risks']) == ['RK01', 'RK06', 'RK11']
    assert config['risks']['RK06']['name'] == '客户预测不足'
    assert config['risks']['RK11']['name'] == '商机推进超期，影响签单'
    assert len(config['metrics']) == 59 and {'C10', 'P0-09'} <= set(config['metrics'])
    assert len(config['causes']) == 8 and len(config['advice']) == 9
    assert {cause['method'] for cause in config['causes'].values()} == {'AI'}
    analysis = config['overrides']['causeAnalysis']
    # 1117 1119 BR-L01: 0～2 causes with independent evidence per risk.
    assert (analysis['mode'], analysis['minPerRisk'], analysis['maxPerRisk']) == ('ai', 0, 2)
    # Fixed stage baselines (BR-Q06) and the RK11 level bands.
    assert config['overrides']['stageBaselines'] == {'P0': 32.6, 'P1': 21.8, 'P2': 7.2, 'P3': 57.2, 'P4': 15.3}
    thresholds = config['overrides']['thresholds']
    assert (thresholds['stageBandStagesHigh'], thresholds['stageBandAmountHigh']) == (2, 10)
    assert 'signLagExtremePoints' not in thresholds and 'productGapRate' not in thresholds
    assert config['overrides']['customerTier']['strategic'] == ['1']
    assert config['overrides']['storageCustomerScope']['enabled']
    # Every metric SQL takes [start_date, end_exclusive, observed_at] as bound parameters.
    assert all(metric['sql'].count('%s') == 3 for metric in config['metrics'].values() if metric['sql'])
    assert not any('CURRENT_TIMESTAMP' in metric['sql'] for metric in config['metrics'].values())

def test_result_exposes_the_full_ontology_trace():
    value = evaluate(_data())
    trace = value['result']['ontologyTrace']
    assert trace['ontology'] == '商机获取节点 V3 本体文件_1117（第三版执行口径）'
    assert trace['version'] == 'opportunity-v3-rules-15'
    assert len(trace['digest']) == 12
    assert len(trace['metrics']) == 59
    assert len(trace['risks']) == 3
    assert len(trace['causes']) == 8
    assert len(trace['advice']) == 9
    assert len(trace['rules']) == len(load_config()['rules'])
    assert trace['risks'][0]['code'] == 'RK01' and trace['risks'][0]['name']
    assert set(trace['links']) == {'RK01', 'RK06', 'RK11'}
    br_a06 = next(item for item in trace['rules'] if item['code'] == 'BR-A06')
    assert br_a06['name'] and br_a06['description'] and br_a06['trigger']


def test_result_exposes_rule_assessments_and_query_sql_for_evidence_details():
    opportunity = _opportunity()
    data = _data(opportunities=[opportunity], allOpportunities=[deepcopy(opportunity)],
                 accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic')])
    data['queryCatalog'] = [dict(label='销售目标', sql='SELECT 1', params=[2026],
                                 status='ok', durationSeconds=0.01, rowCount=1)]
    value = evaluate(data)
    assessments = value['result']['riskAssessments']
    assert len(assessments) == 3
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
    # RK02 签单进度滞后 was removed by the 1117 ontology: R02 stays a base fact only.
    assert 'RK02' not in {risk['code'] for risk in value['risks']}

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



def test_deadline_meta_keeps_original_text_instead_of_forcing_30_days():
    from bi_agent.cockpit.opportunity_v2 import _deadline_meta

    days, kind, text = _deadline_meta('按月')
    assert (days, kind, text) == (30, 'text', '按月')
    days, kind, text = _deadline_meta('按突破计划协同')
    assert (days, kind, text) == (30, 'text', '按突破计划协同')
    assert _deadline_meta('20 个工作日') == (20, 'days', '20 个工作日')





def test_gap_risk_states_target_progress_and_forecast():
    signed = _opportunity(id='s', contract='confirmed', forecastAmount=20.0, forecastEnergy=10.0,
                          stage='14', createdAt='2026-01-01')
    data = _data(opportunities=[signed], allOpportunities=[deepcopy(signed)],
                 annualCoverage=_annual(progress=(20.0, 10.0), forecast=(30.0, 40.0)))
    value = evaluate(data, measured=date(2026, 11, 11))
    rk01 = next(risk for risk in value['risks'] if risk['code'] == 'RK01')
    # 缺口 ＝ 目标 −（进度 ＋ 预测）: 100 − (20 + 30) = 50, 100 − (10 + 40) = 50.
    # 1117 1119 template: elapsed months 已签单, remaining months 剩余预测, 全年缺口.
    assert rk01['description'] == (
        '金额目标 100.00 亿元，1—10月已签单 20.00 亿元，11—12月剩余预测 30.00 亿元，'
        '全年缺口 50.00 亿元，缺口率 50.0%。'
        '电量目标 100.00 GWh，1—10月已签单 10.00 GWh，11—12月剩余预测 40.00 GWh，'
        '全年缺口 50.00 GWh，缺口率 50.0%。')
    # January has no elapsed months: the 已签单 clause is left out.
    january = evaluate(data, measured=date(2026, 1, 15))
    rk01_jan = next(risk for risk in january['risks'] if risk['code'] == 'RK01')
    assert '已签单' not in rk01_jan['description'] and '1—12月剩余预测' in rk01_jan['description']
    assert rk01['level'] == '高'
    assert value['metrics']['R01']['amount'] == 50.0
    facts = {item['id']: item for item in value['evidence']['facts']}
    assert facts['opp-v2:metric:R01-PROGRESS-AMOUNT']['value'] == 20.0
    assert facts['opp-v2:metric:R01-FORECAST-AMOUNT']['value'] == 30.0
    assert '1—10月已签单' in facts['opp-v2:metric:R01-PROGRESS-AMOUNT']['definition']
    # The B02 total forecast is not the coverage: no gap when 进度 ＋ 预测 reaches the target.
    covered = evaluate(_data(opportunities=[signed], allOpportunities=[deepcopy(signed)],
                             annualCoverage=_annual(progress=(60.0, 60.0), forecast=(40.0, 40.0))),
                       measured=date(2026, 11, 11))
    assert 'RK01' not in {risk['code'] for risk in covered['risks']}



def test_signing_rate_is_null_without_a_target():
    unsigned = _opportunity(id='u1', contract='not_confirmed', forecastAmount=10.0, forecastEnergy=None,
                            stage='14', createdAt='2026-01-01')
    value = evaluate(_data(targets=dict(amount=None, energy=0.0, byProduct={}, byAccount={}),
                           opportunities=[unsigned], allOpportunities=[deepcopy(unsigned)]),
                     measured=date(2026, 11, 11))
    assert value['metrics']['R03']['signProgressAmount'] is None
    assert value['metrics']['R03']['signProgressEnergy'] is None
    assert value['metrics']['R03']['annualCoverageRateAmount'] is None
    assert 'RK02' not in {risk['code'] for risk in value['risks']}



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
    assert fetch[-1]['completed'] == fetch[-1]['total'] == 14
    labels = [item['label'] for item in card['result']['queryCatalog']]
    assert len(labels) == 14 and '投标' not in labels
    # BR-V12: the product-team query no longer feeds a risk or cause.
    assert '产品部销售缺口' not in labels and '全年覆盖预测' not in labels
    assert {'商机预测缺口', '客户预测缺口', '阶段周期分档', 'P0在途超期', '战略重点商机储备', '无商机战略客户'} <= set(labels)
    r01 = next(item for item in card['result']['queryCatalog'] if item['label'] == '商机预测缺口')
    assert r01['params'] == [date(2026, 1, 1), date(2027, 1, 1), date(2026, 11, 11)]
    assert r01['metricCodes'] == ['R01', 'B01', 'B02']
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
            if 'new_target_esb' in sql and 'CAST(%s AS DATE)' not in sql:
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
    match = re.search(r"(?:CAST\((\d+) AS DECIMAL\)|(\d+)::numeric) AS target_power_units_per_gwh", b01)
    declared = int(match.group(1) or match.group(2))
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
    # The signed achievement needs the (truncated) detail and stays unknown;
    # the gap comes from its own full 全年覆盖预测 query, never the partial rows.
    assert value['metrics']['R03']['signProgressAmount'] is None
    assert value['metrics']['R01']['amount'] == 90.0
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
    assert fetch and fetch[-1]['completed'] == fetch[-1]['total'] == 14
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
    assert len(catalog) == 14
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


def _judged(value, judge, config=None):
    from bi_agent.cockpit.opportunity_judgement import judge_card
    return judge_card(value, config or load_config(), judge=judge)



def test_causes_follow_established_risks_and_advice_follows_established_causes():
    value = _strategic_value()
    requests = []

    def judge(request):
        requests.append(request)
        if request['kind'] == 'inference':
            return dict(causes=[dict(title='推理根因', description='依据取数推理', dataGaps='')])
        return dict(established=request['kind'] == 'cause', reason='进展文本显示卡点')
    judged = _judged(value, judge, _ontology_cause_config())
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
    config = _ontology_cause_config()
    judged = _judged(_strategic_value(), _judge_no, config)
    judgement = judged['ontologyJudgement']
    assert [item['code'] for item in judgement['risks']] == list(config['risks'])
    assert [item['code'] for item in judgement['causes'] if not item.get('inferred')] == list(config['causes'])
    assert [item['code'] for item in judgement['advice']] == list(config['advice'])
    labels = {item['statusLabel'] for group in judgement.values() if isinstance(group, list)
              for item in group if isinstance(item, dict)}
    assert '命中（规则判定）' in labels
    assert judged['summary'].startswith('本轮 3 项本体风险中')


def test_model_answers_are_taken_without_a_validation_pass():
    # Without the 全年覆盖预测 inputs RK01 cannot be settled by its rule.
    value = _strategic_value(annualCoverage={})

    def judge(request):
        # Unusual wording and an unknown level are accepted as given.
        return dict(established='成立', level='特别高', reason='x' * 900)
    judged = _judged(value, judge)
    model = [item for item in judged['findings'] if item['decidedBy'] == 'model']
    assert model and all(item['riskLevel'] == '' for item in model)
    assert all(len(item['description']) == 400 for item in model)


def test_without_a_model_undecided_items_are_skipped_and_reported():
    judged = _judged(_strategic_value(annualCoverage={}), None)
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
    judged = _judged(value, judge, _ontology_cause_config())
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
    judged = _judged(value, judge, _ontology_cause_config())
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
    judged = _judged(_strategic_value(), judge, _ontology_cause_config())
    assert not any(item['inferred'] for item in judged['causes'])
    notes = [item for item in judged['ontologyJudgement']['causes'] if item.get('inferred')]
    assert notes and all(item['reason'] == '缺少客户拜访数据' and item['established'] is None for item in notes)
    assert {item['statusLabel'] for item in notes} == {'模型未能推理'}



def test_ontology_metric_sql_is_bound_to_the_period_and_measurement_date():
    from bi_agent.cockpit.opportunity_v2 import _ontology_metric_sql, _ontology_params
    config = load_config()
    sql = _ontology_metric_sql(config, 'R01', 2026, date(2026, 11, 11))
    # 1117: the period and the observation day are bound parameters, not text.
    assert sql.startswith('WITH') and sql.count('%s') == 3
    assert 'CAST(%s AS DATE) AS start_date' in sql and 'CAST(%s AS TIMESTAMP) AS observed_at' in sql
    assert _ontology_params(sql, 2026, date(2026, 11, 11)) == [
        date(2026, 1, 1), date(2027, 1, 1), date(2026, 11, 11)]
    assert _ontology_params('SELECT 1', 2026, date(2026, 11, 11)) == []

def test_measurement_date_is_clamped_to_the_delivery_snapshot():
    from bi_agent.cockpit.opportunity_v2 import _measurement_date
    # 交付页面固定在 2025 年 10 月：年度与今后期间都只观察到 2025-10-31。
    assert _measurement_date('2025') == date(2025, 10, 31)
    assert _measurement_date('2025-10') == date(2025, 10, 31)
    assert _measurement_date('2025-11') == date(2025, 10, 31)
    assert _measurement_date('2026') == date(2025, 10, 31)
    # 快照之前的历史期间保持自己的期末。
    assert _measurement_date('2025-09') == date(2025, 9, 30)
    assert _measurement_date('2024') == date(2024, 12, 31)
    # 显式日期（测试/回放）仍然优先。
    assert _measurement_date('2025', '2025-12-31') == date(2025, 12, 31)


def test_snapshot_date_defaults_to_the_delivery_day_and_accepts_an_override(monkeypatch):
    from bi_agent.cockpit import periods
    monkeypatch.delenv('COCKPIT_SNAPSHOT_DATE', raising=False)
    assert periods.snapshot_date() == date(2025, 10, 31)
    monkeypatch.setenv('COCKPIT_SNAPSHOT_DATE', '2025-09-30')
    assert periods.snapshot_date() == date(2025, 9, 30)
    monkeypatch.setenv('COCKPIT_SNAPSHOT_DATE', 'not-a-date')
    assert periods.snapshot_date() == date(2025, 10, 31)


def test_year_grain_card_observes_the_delivery_snapshot_instead_of_the_year_end():
    class EmptyResult:
        truncated = False
        rows = []

    class Database:
        available = True
        config = SimpleNamespace(schema='ded_public', statement_timeout_ms=1000)

        def run(self, sql, params, timeout_ms=0):
            return EmptyResult()

    card = build_card('2025', database=Database(), judge=_judge_no)
    catalog = card['result']['queryCatalog']
    forecast = next(item for item in catalog if item['label'] == '商机预测')
    # 年度粒度也必须观察 2025-10-31，而不是 2025-12-31。
    assert forecast['params'] == [2025, date(2025, 10, 31)]
    for item in catalog:
        assert 'CURRENT_TIMESTAMP' not in item['sql'], item['label']
        assert date(2025, 12, 31) not in item['params'], item['label']


def test_every_ontology_metric_sql_binds_in_either_period_format():
    from bi_agent.cockpit.opportunity_v2 import _ontology_metric_sql, _ontology_params
    config = load_config()
    for code in config['metrics']:
        sql = _ontology_metric_sql(config, code, 2025, date(2025, 10, 31))
        assert sql.startswith('WITH'), code
        assert len(_ontology_params(sql, 2025, date(2025, 10, 31))) == sql.count('%s') == 3, code
        assert 'CURRENT_TIMESTAMP' not in sql.upper(), code
        # Any other percent sign is escaped, so the driver sends it unchanged.
        assert not re.search(r'%(?![s%])', sql.replace('%%', '')), code

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
    assert len(result['findings']) >= 1
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
    # R09 is now an RK06 cause input (RC09), not a risk of its own.
    assert 'RK07' not in {risk['code'] for risk in value['risks']}


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
    # 进度 ＋ 预测 per customer × product from the 全年覆盖预测 branch.
    annual = _annual(accounts={'c1|1': ((1.0, 0.5), (2.0, 0.5)), 'c1|2': ((4.0, 4.0), (5.0, 5.0)),
                               'c3|1': ((0.0, 0.0), (0.0, 0.0))})
    value = evaluate(_data(targets=targets, opportunities=opportunities,
                           allOpportunities=deepcopy(opportunities), annualCoverage=annual))
    assert value['metrics']['R08'] == dict(count=1, pairs=1)
    rk06 = next(risk for risk in value['risks'] if risk['code'] == 'RK06')
    assert rk06['impact'] == dict(amount=2.0, energy=1.0, count=1)
    assert rk06['description'] == (
        '1 家客户（1 个客户×产品组合）的已签单＋预测低于客户目标：'
        '金额目标 5.00 亿元，已签单 1.00 亿元＋预测 2.00 亿元，缺口合计 2.00 亿元；'
        '电量目标 2.00 GWh，已签单 0.50 GWh＋预测 0.50 GWh，缺口合计 1.00 GWh。')
    # Incomplete customer rows leave the customer gap unknown, not zero.
    partial = evaluate(_data(targets=targets, opportunities=opportunities,
                             allOpportunities=deepcopy(opportunities),
                             annualCoverage=dict(annual, status='truncated')))
    facts = {item['id']: item for item in partial['evidence']['facts']}
    assert facts['opp-v2:metric:R08']['value'] is None
    assert 'RK06' not in {risk['code'] for risk in partial['risks']}


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


def test_the_opportunity_card_uses_group_summaries_and_semantic_control():
    from bi_agent.cockpit import frozen
    assert 'opportunity-risk' not in frozen.SECTION_SUMMARY_STAGES
    source = (Path(__file__).resolve().parents[1] / 'bi_agent/cockpit/frozen.py').read_text(encoding='utf-8')
    assert 'semantic=semantic_rewriter if (enabled and semantic) else None' in source
    assert 'summarize_groups=summarize_risk_groups if enabled and summaries_enabled() else None' in source


def test_the_cell_product_risk_was_removed_but_r05_stays_as_evidence():
    # 风险规则修订: no independent 电芯 risk; R05 remains a pending-scale fact.
    pending = _opportunity(id='p', contract='not_confirmed', productType='1', forecastAmount=50.0,
                           forecastEnergy=50.0, stage='14', createdAt='2026-01-01')
    data = _data(targets=dict(amount=500.0, energy=500.0,
                              byProduct={'1': dict(amount=500.0, energy=500.0)}, byAccount={}),
                 opportunities=[pending], allOpportunities=[deepcopy(pending)],
                 annualCoverage=_annual(products={'1': ((0.0, 0.0), (50.0, 50.0))}))
    value = evaluate(data, measured=date(2026, 11, 11))
    assert 'RK04' not in {risk['code'] for risk in value['risks']}
    assert 'RK04' not in {item['code'] for item in value['riskCandidates']}
    assert value['metrics']['R05']['amount'] == 50.0


def _requests_for(value):
    from bi_agent.cockpit.opportunity_judgement import judge_card
    seen = []

    def judge(request):
        seen.append(request)
        return dict(causes=[]) if request['kind'] == 'inference' else dict(established=False, reason='x')
    judged = judge_card(value, _ontology_cause_config(), judge=judge)
    return seen, judged


def test_inference_reads_only_the_chain_metrics_with_their_ontology_caliber():
    seen, _ = _requests_for(_strategic_value())
    inference = [r for r in seen if r['kind'] == 'inference']
    assert inference
    config = load_config()
    import re
    codes = lambda text: set(re.findall(r'[A-Z]\d-\d{2}|[A-Z]+\d{2}', text))
    for request in inference:
        allowed = codes(config['risks'][request['code']]['indicators'])
        for cause in config['links'][request['code']]['causes']:
            allowed |= codes(config['causes'][cause]['indicators'])
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
    assert config['risks']['RK01']['name'] == '商机预测覆盖不足'
    assert config['risks']['RK06']['name'] == '客户预测不足'
    findings = _strategic_value()['result']['findings']
    assert findings
    for finding in findings:
        name = config['risks'][finding['riskCode']]['name']
        assert finding['title'].startswith(f"{finding['riskCode']} {name}")
    # A renamed risk in the ontology renames the card's row.
    renamed = deepcopy(load_config())
    renamed['risks']['RK06'] = dict(renamed['risks']['RK06'], name='改名后的风险')
    from bi_agent.cockpit.opportunity_v2 import _risk_name
    assert _risk_name(renamed, 'RK06') == '改名后的风险'


def test_the_attachment_ontology_has_storage_customer_scope():
    config = load_config()
    scope = config['overrides']['storageCustomerScope']
    assert scope['enabled'] and scope['source'] == 'BR-Q04'
    assert set(scope['metrics']) == {'R04', 'R08', 'R09', 'C01', 'C06', 'C08', 'C09'}
    assert config['fields']['LE05']['owninguser']['column'] == 'owninguser'
    assert config['overrides']['dynamicCycle']['completedOnly'] is True


def test_focus_tracking_counts_only_storage_customers():
    inside = _opportunity(id='in', storageCustomer=True)
    outside = _opportunity(id='out', accountId='account-2', accountName='战略客户B',
                           accountLevel='1', storageCustomer=False)
    value = evaluate(_data(opportunities=[inside, outside],
                           allOpportunities=[deepcopy(inside), deepcopy(outside)],
                           accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic'),
                                     dict(id='account-2', name='战略客户B', level='1', tier='strategic')]))
    facts = {f['id']: f for f in value['evidence']['facts']}
    assert facts['opp-v2:metric:R04-COUNT']['value'] == 1
    assert facts['opp-v2:metric:R04-AMOUNT']['value'] == 10.0
    assert facts['opp-v2:metric:B02-AMOUNT']['value'] == 20.0
    assert facts['opp-v2:metric:R04-COUNT']['definition'].startswith('储能客户名单内（BR-Q04）')
    # Legacy inputs that lack the scope flag retain their original behavior.
    legacy = evaluate(_data(opportunities=[_opportunity(id='a'), _opportunity(id='b')],
                            allOpportunities=[_opportunity(id='a'), _opportunity(id='b')]))
    legacy_facts = {f['id']: f for f in legacy['evidence']['facts']}
    assert legacy_facts['opp-v2:metric:R04-COUNT']['value'] == 2


def test_customer_gap_excludes_customers_outside_the_storage_list():
    def run(flag):
        pair = dict(accountId='account-1', productType='1', amount=50.0, energy=None)
        if flag is not None:
            pair['storageCustomer'] = flag
        return evaluate(_data(
            targets=dict(amount=100.0, energy=100.0, byProduct={}, byAccount={},
                         byAccountProduct={'account-1|1': pair}),
            opportunities=[_opportunity(monthRows=1)], allOpportunities=[_opportunity()],
            annualCoverage=_annual(accounts={'account-1|1': ((0.0, 0.0), (10.0, 5.0))})))
    facts = lambda value: {f['id']: f for f in value['evidence']['facts']}
    assert facts(run(True))['opp-v2:metric:R08']['value'] == 1
    assert facts(run(False))['opp-v2:metric:R08']['value'] == 0
    assert facts(run(None))['opp-v2:metric:R08']['value'] == 1


def test_stage_mean_excludes_in_flight_samples():
    # Two finished P0 stages (10 and 20 days) and one still running for 300 days.
    done_a = _opportunity(id='a', stage='11', createdAt='2026-01-01', stage1End='2026-01-11', stage2End=None, stage3End=None)
    done_b = _opportunity(id='b', stage='11', createdAt='2026-01-01', stage1End='2026-01-21', stage2End=None, stage3End=None)
    running = _opportunity(id='c', stage='11', createdAt='2026-01-15', stage1End=None, stage2End=None, stage3End=None)
    value = evaluate(_data(opportunities=[done_a, done_b, running],
                           allOpportunities=[deepcopy(done_a), deepcopy(done_b), deepcopy(running)]))
    facts = {f['id']: f for f in value['evidence']['facts']}
    assert facts['opp-v2:metric:P0-01']['value'] == 15.0
    assert '在途不计入均值' in facts['opp-v2:metric:P0-01']['definition']
    assert facts['opp-v2:metric:P0-02']['value'] == 1
    # RK10 is no longer a risk of its own (1117: it is the P0 cause RC13 under RK11).
    assert 'RK10' not in {r['code'] for r in value['risks']}


def test_storage_scope_sql_follows_owner_team_member_customer():
    source = (Path(__file__).resolve().parents[1] / 'bi_agent/cockpit/opportunity_v2.py').read_text(encoding='utf-8')
    for fragment in ("sa.{ac[account_owner_field]}::text IN (", "su.{sm['teamid']}::text IN (",
                     "stm.{sm['systemuserid']}::text IN (", "sow.{oc[owner_field]}::text FROM {opp_src} sow",
                     "(sc.account_id IS NOT NULL) AS storage_customer",
                     "AND a.{ac['accountid']}::text IN (SELECT account_id FROM {storage_sql} sc)",
                     "GROUP BY 1,2,3,4,5,6,7"):
        assert fragment in source, fragment


def test_stage_bands_use_the_attachment_and_respect_the_branch_snapshot():
    from bi_agent.cockpit.opportunity_v2 import _QUERY_METRICS, _stage_band_sql

    config = load_config()
    codes = ['R12', 'R13', 'R14', 'R15', 'R16', 'R17']
    assert _QUERY_METRICS['阶段周期分档'] == codes
    assert all(config['metrics'][code]['category'] == '商机转化风险' for code in codes)
    assert config['risks']['RK11']['category'] == '商机转化风险'
    assert config['risks']['RK11']['rule'] == 'BR-A11'
    thresholds = config['overrides']['thresholds']
    assert thresholds['stageBandStagesHigh'] == 2 and thresholds['stageBandAmountHigh'] == 10
    sql = _stage_band_sql(config, 2025, date(2025, 10, 31))
    assert "WHERE code IN ('R12', 'R13', 'R14', 'R15', 'R16', 'R17')" in sql
    # 1117: bound observation day, fixed stage baselines and a de-duplicated severe summary.
    assert 'CAST(%s AS TIMESTAMP) AS observed_at' in sql and 'v.finished_at < p.effective_end_exclusive' in sql
    assert "WHEN 'P0' THEN 32.6" in sql and '严重超期汇总_跨阶段去重' in sql


def _stage_bands(**counts):
    from bi_agent.cockpit.opportunity_v2 import STAGE_BAND_CODES, _stage_band_rows

    stages = ('商机获取', '商机获取', '技术交流', '技术交流', '方案推动', '方案推动')
    return _stage_band_rows([
        {'指标序号': code, '数量': counts.get(code, 0), '金额_亿元': counts.get(code, 0) * 3,
         '电量_GWh': counts.get(code, 0) * 1.5,
         '分组明细及缺口': {'阶段': stage, '各产品动态平均周期及样本数': [
             {'产品类型': '电芯', '平均周期天': 40, '参与平均样本数': 12}]}}
        for code, stage in zip(STAGE_BAND_CODES, stages)
    ])


def test_rk11_requires_a_severe_band_supported_by_the_query():
    watch_only = _strategic_value(stageBands=_stage_bands(R12=4, R14=1), stageBandStatus='ok')
    assert 'RK11' not in _judged(watch_only, _judge_no)['riskCodes']
    missing = _strategic_value(stageBands={}, stageBandStatus='error')
    judged = _judged(missing, lambda request: dict(established=True))
    rk11 = next(a for a in judged['riskAssessments'] if a['code'] == 'RK11')
    assert not rk11['include'] and rk11['assessmentSource'] == 'unevaluated'


def test_grouped_card_delivers_model_summaries_and_all_rk11_statuses(monkeypatch):
    from bi_agent.cockpit import opportunity_v2
    from bi_agent.cockpit.delivery import project_card
    from bi_agent.cockpit.page_cache import compact_analysis
    from bi_agent.cockpit.section_summary import summarize_risk_groups

    bands = _stage_bands(R12=4, R13=2, R15=1)
    bands['R15']['energy'] = None
    bands['R17']['meanKnown'] = False
    data = _data(opportunities=[_opportunity()], allOpportunities=[_opportunity()],
                 stageBands=bands, stageBandStatus='ok',
                 queryCatalog=[dict(executionId='stage-bands', metricCodes=list(bands))])
    monkeypatch.setattr(opportunity_v2, 'collect', lambda *args, **kwargs: data)
    prompts = []

    def model(payload):
        prompts.append(payload)
        return {'summaries': {'商机覆盖风险': '商机预测存在缺口。',
                              '商机转化风险': '商机获取阶段有 2 条商机达到超期高档。'}}

    card = build_card('2026', measurement_date='2026-11-11', judge=_judge_no,
                      summarize_groups=lambda groups: summarize_risk_groups(groups, call_model=model))
    result = compact_analysis(project_card(card, 'opportunity-risk'))['result']
    findings = {finding['id']: finding for finding in result['findings']}
    groups = {group['category']: group for group in result['riskGroups']}
    coverage = groups['商机覆盖风险']
    conversion = groups['商机转化风险']
    assert 'RK01' in {findings[fid]['riskCode'] for fid in coverage['findingIds']}
    assert coverage['summary'] == '商机预测存在缺口。'
    assert conversion['summary'] == '商机获取阶段有 2 条商机达到超期高档。'
    assert len(prompts) == 1 and set(prompts[0]['groups']) == set(groups)
    rk11 = next(findings[fid] for fid in conversion['findingIds'] if findings[fid]['riskCode'] == 'RK11')
    assert rk11['riskLevel'] == '高' and rk11['decidedBy'] == 'rule' and rk11['queryIds'] == ['stage-bands']
    # Only the severe band (≥ 50% over the baseline), one line per stage.
    assert [(m['code'], m['status'], m['count']) for m in rk11['metricDetails']] == [
        ('R13', 'triggered', 2), ('R15', 'triggered', 1), ('R17', 'unknown', None),
    ]
    assert rk11['metricDetails'][0]['amount'] == 6.0 and rk11['metricDetails'][0]['energy'] == 3.0
    assert rk11['metricDetails'][1]['energy'] is None


def test_coverage_group_keeps_a_rule_summary_when_the_model_summary_is_rejected(monkeypatch):
    from bi_agent.cockpit import opportunity_v2
    from bi_agent.cockpit.delivery import project_card
    from bi_agent.cockpit.page_cache import compact_analysis
    from bi_agent.cockpit.section_summary import summarize_risk_groups

    bands = _stage_bands(R12=4, R13=2, R15=1)
    data = _data(opportunities=[_opportunity()], allOpportunities=[_opportunity()],
                 stageBands=bands, stageBandStatus='ok',
                 queryCatalog=[dict(executionId='stage-bands', metricCodes=list(bands))])
    monkeypatch.setattr(opportunity_v2, 'collect', lambda *args, **kwargs: data)
    calls = []

    def model(payload):
        calls.append(payload)
        # The coverage summary invents 9999 both times; conversion passes first time.
        return {'summaries': {'商机覆盖风险': '预测缺口约 9999 亿元。',
                              '商机转化风险': '商机获取阶段有 2 条商机达到超期高档。'}}

    card = build_card('2026', measurement_date='2026-11-11', judge=_judge_no,
                      summarize_groups=lambda groups: summarize_risk_groups(groups, call_model=model))
    result = compact_analysis(project_card(card, 'opportunity-risk'))['result']
    findings = {finding['id']: finding for finding in result['findings']}
    groups = {group['category']: group for group in result['riskGroups']}
    coverage, conversion = groups['商机覆盖风险'], groups['商机转化风险']
    assert conversion['summary'] == '商机获取阶段有 2 条商机达到超期高档。'
    assert conversion['summarySource'] == 'model'
    assert coverage['summarySource'] == 'rule'
    assert coverage['summary'].startswith(f"本类共 {len(coverage['findingIds'])} 项风险：")
    assert '9999' not in coverage['summary']
    for fid in coverage['findingIds']:
        assert findings[fid]['riskLevel'] in coverage['summary']
    assert len(calls) == 2 and set(calls[1]['groups']) == {'商机覆盖风险'}
    assert '9999' in calls[1]['validationFeedback']['issues']['商机覆盖风险']



def _ai_judge(answers, seen):
    """A model that answers the global cause analysis from ``answers`` in order."""
    def judge(request):
        seen.append(request)
        if request['kind'] == 'global_causes':
            return answers.pop(0) if answers else dict(risks=[])
        return dict(established=False, reason='模型判定不成立')
    return judge


def test_ai_root_causes_come_from_one_global_analysis_of_the_established_risks():
    value = _strategic_value()
    seen = []
    first = {}

    def answer(request):
        first.update(request)
        return dict(risks=[dict(code=risk['code'], causes=[
            dict(title=f"{risk['code']} 根因{name}", description=text, dataGaps=gaps,
                 evidence=[risk['metrics'][0]['code']])
            for name, text, gaps in (('甲', '依据输入数据推理', '需补客户拜访记录'), ('乙', '结合风险关联推理', ''),
                                     ('丙', '超出上限', ''))]) for risk in request['risks']])

    def judge(request):
        seen.append(request)
        if request['kind'] == 'global_causes':
            return answer(request)
        return dict(established=False, reason='模型判定不成立')
    judged = _judged(value, judge)
    established = [item['riskCode'] for item in judged['findings']]
    calls = [item for item in seen if item['kind'] == 'global_causes']
    # One call covering every established risk with its own metric results.
    assert len(calls) == 1 and [risk['code'] for risk in first['risks']] == established
    # 0～2 causes per risk; the ontology 根因 page is the context of each risk.
    assert first['causesPerRisk'] == dict(min=0, max=2)
    assert all(risk['metrics'] and 'judgement' in risk for risk in first['risks'])
    assert all(risk['ontologyCauses'] for risk in first['risks'])
    assert all(item['code'].startswith('RC') and item['name'] for risk in first['risks']
               for item in risk['ontologyCauses'])
    assert not [item for item in seen if item['kind'] in ('cause', 'inference')]
    # Each cause stays its own item under its risk; the third is over the limit.
    causes = judged['causes']
    assert [item['causeCode'] for item in causes] == [
        f'{code}-AI{index}' for code in established for index in (1, 2)]
    assert all(item['analysis'] == 'ai' and item['inferred'] and item['decidedBy'] == 'model' for item in causes)
    assert all(len(item['findingIds']) == 1 for item in causes)
    assert causes[0]['missingEvidence'] == ['需补客户拜访记录']
    trace = judged['ontologyJudgement']
    assert not any(item['code'].startswith('RC') for item in trace['causes'])
    assert {item['statusLabel'] for item in trace['causes']} == {'AI 全局分析'}
    # AI causes carry no ontology cause code, so no ontology advice applies.
    assert judged['recommendations'] == []
    assert {item['statusLabel'] for item in trace['advice']} == {'根因由 AI 全局分析给出，未关联本体行动建议'}
    assert trace['inferenceCalls'] == 1
    assert '根因由 AI 依据成立风险及其指标结果全局分析给出' in judged['summary']


def test_ai_root_causes_never_contradict_their_risk_figures():
    from bi_agent.cockpit.opportunity_judgement import _conflicts_risk

    risk = dict(judgement='金额目标 120.00 亿元，已签单 20.00 亿元（1—9月）＋预测 40.00 亿元（10—12月），'
                          '缺口 60.00 亿元，缺口率 50.0%。')
    assert '缺口 55' in _conflicts_risk(dict(title='储备不足', description='全年缺口 55 亿元来自电芯'), risk) \
        or _conflicts_risk(dict(title='储备不足', description='，缺口 55 亿元来自电芯'), risk)
    assert _conflicts_risk(dict(title='储备不足', description='，缺口率 50% 主要来自电芯'), risk) == ''
    # A different object's figure (储能客户缺口) is not the risk's own figure.
    assert _conflicts_risk(dict(title='储备不足', description='其中储能客户缺口 12.5 亿元'), risk) == ''


def test_ai_root_causes_quote_only_input_numbers_and_cover_every_risk():
    value = _strategic_value()
    established = [item['riskCode'] for item in _judged(value, _judge_no)['findings']]
    first, *rest = established
    seen = []
    owned ={'RK01': 'R01', 'RK06': 'R08', 'RK11': 'R13'}
    invented = dict(risks=[dict(code=first, causes=[dict(title='预测偏低', description='缺口约 98765.4 亿元', dataGaps='',
                                                         evidence=[owned[first]])])])
    fixed = dict(risks=[dict(code=code, causes=[dict(title=f'推进节奏偏慢{index}', description='依据输入数据', dataGaps='',
                                                     evidence=[owned[code]])])
                        for index, code in enumerate(established)])
    judged = _judged(value, _ai_judge([invented, fixed], seen))
    calls = [item for item in seen if item['kind'] == 'global_causes']
    # The invented number is sent back once (0 causes is allowed, so the
    # uncovered risks are not asked again).
    assert len(calls) == 2
    feedback = '；'.join(calls[1]['validationFeedback'])
    assert '98765.4' in feedback
    assert {item['causeCode'] for item in judged['causes']} == {f'{code}-AI1' for code in established}
    assert '98765.4' not in ''.join(item['description'] for item in judged['causes'])

    # A model that keeps failing leaves the risks without causes: “暂无可验证根因”.
    failing = _judged(value, _ai_judge([invented, invented], []))
    assert {item['causeCode'] for item in failing['causes']} == set()
    assert {finding['causeNote'] for finding in failing['findings']} == {'暂无可验证根因'}
    missing = [item for item in failing['ontologyJudgement']['causes'] if item['code'].endswith('-AI')]
    assert {item['code'] for item in missing} == {f'{code}-AI' for code in established}
    assert all(item['established'] is None for item in missing)


def _severe_bands(summary=None, **counts):
    """R12–R17 rows of the 1117 band SQL, with its cross-stage severe summary."""
    from bi_agent.cockpit.opportunity_v2 import STAGE_BAND_CODES, _stage_band_rows

    stages = ('商机获取', '商机获取', '技术交流', '技术交流', '方案推动', '方案推动')
    summary = summary if summary is not None else dict(
        opportunity_count=300, stage_record_count=358, amount_yi=123.456, energy_gwh=45.6,
        hit_stage_count=3, missing_amount_opportunities=0)
    return _stage_band_rows([
        {'指标序号': code, '数量': counts.get(code, 0), '金额_亿元': counts.get(code, 0) * 0.5,
         '电量_GWh': counts.get(code, 0) * 0.1,
         '分组明细及缺口': {'阶段': stage, '严重超期汇总_跨阶段去重': summary,
                       '各产品静态基线及有效正周期样本数': [{'产品类型': '电芯', '静态基线天': 32.6, '有效正周期样本数': 9}]}}
        for code, stage in zip(STAGE_BAND_CODES, stages)])


def test_rk11_lists_only_severe_overruns_and_states_the_deduplicated_total():
    value = _strategic_value(stageBands=_severe_bands(R12=40, R13=200, R14=5, R15=100, R17=58),
                             stageBandStatus='ok')
    rk11 = next(risk for risk in value['risks'] if risk['code'] == 'RK11')
    # BR-V09: counted once per opportunity across stages, forecast summed once.
    assert rk11['description'] == '300 条商机在已结束阶段出现严重超期，涉及预测金额 123.46 亿元，涉及预测电量 45.60 GWh。'
    assert rk11['level'] == '高'  # three stages hit
    # Only the severe band is listed, one line per stage; the < 50% band is not shown.
    assert [(item['code'], item['stage'], item['count']) for item in rk11['metricDetails']] == [
        ('R13', '商机获取', 200), ('R15', '技术交流', 100), ('R17', '方案推动', 58)]
    assert all(item['band'] == '严重超期' for item in rk11['metricDetails'])
    assert rk11['metricDetails'][0]['amountText'] == '涉及预测金额 100.00 亿元'
    # One stage, amount below 10 亿元 → 中; an incomplete amount leaves the level open.
    one = _strategic_value(stageBands=_severe_bands(dict(opportunity_count=4, amount_yi=6.0, energy_gwh=1.0,
                                                         hit_stage_count=1), R13=4), stageBandStatus='ok')
    assert next(r for r in one['risks'] if r['code'] == 'RK11')['level'] == '中'
    partial = _strategic_value(stageBands=_severe_bands(dict(opportunity_count=4, amount_yi=6.0, hit_stage_count=1,
                                                             missing_amount_opportunities=1), R13=4),
                               stageBandStatus='ok')
    rk11 = next(r for r in partial['risks'] if r['code'] == 'RK11')
    assert rk11['level'] == '' and '已记录预测金额 6.00 亿元' in rk11['description']
    assert '预测电量待核实' in rk11['description']


def test_rk01_reads_the_ontology_r01_query_for_the_whole_scope():
    r01 = dict(queryStatus='ok', detail=[
        dict(product_type='PACK', target_amount=50.0, progress_amount=1.0, forecast_amount=1.0),
        dict(product_type='全部', target_amount=120.0, target_energy=30.0, progress_amount=20.0,
             progress_energy=5.0, forecast_amount=40.0, forecast_energy=10.0)])
    value = evaluate(_data(ontologyResults=dict(R01=r01)), measured=date(2025, 10, 31))
    rk01 = next(risk for risk in value['risks'] if risk['code'] == 'RK01')
    assert rk01['description'].startswith(
        '金额目标 120.00 亿元，1—9月已签单 20.00 亿元，10—12月剩余预测 40.00 亿元，全年缺口 60.00 亿元，缺口率 50.0%。')
    facts = {item['id']: item for item in value['evidence']['facts']}
    assert facts['opp-v2:metric:B01-AMOUNT']['value'] == 120.0
    # A failed R01 query leaves RK01 undecided rather than using another source.
    failed = evaluate(_data(ontologyResults=dict(R01=dict(queryStatus='failed'))), measured=date(2025, 10, 31))
    assert {item['code']: item['ruleStatus'] for item in failed['riskCandidates']}['RK01'] == 'insufficient'


def test_rk06_is_judged_on_the_r08_positive_gap_summary():
    summary = {'任一口径正缺口客户数': 5,
               '金额口径': {'缺口客户数': 4, '战略客户数': 0, '重点客户数': 1, '客户等级未知数': 0,
                        '目标金额_亿元': 50.0, '进度金额_亿元': 10.0, '剩余预测金额_亿元': 15.0, '缺口金额_亿元': 25.0},
               '电量口径': {'缺口客户数': 0}}
    r08 = dict(queryStatus='ok', detail=[dict(account_id='a1', account_name='客户A', gap_amount=3.0,
                                               **{'风险专用正缺口汇总': summary})])
    value = evaluate(_data(ontologyResults=dict(R08=r08)), measured=date(2025, 10, 31))
    rk06 = next(risk for risk in value['risks'] if risk['code'] == 'RK06')
    assert rk06['name'] == '客户预测不足'
    assert rk06['description'] == ('共 5 家客户存在缺口。金额口径涉及 4 家，目标 50.00 亿元，'
                                   '已签单 10.00 亿元，剩余预测 15.00 亿元，缺口合计 25.00 亿元。')
    assert rk06['level'] == '中'  # no strategic customer among the gaps
    assert value['metrics']['R08']['count'] == 5
    no_gap = dict(r08, detail=[{'风险专用正缺口汇总': dict(summary, **{'任一口径正缺口客户数': 0})}])
    assert 'RK06' not in {r['code'] for r in evaluate(_data(ontologyResults=dict(R08=no_gap)))['risks']}


def test_ai_root_causes_must_not_repeat_their_risk():
    from bi_agent.cockpit.opportunity_judgement import _repeats_risk

    risk = dict(name='商机预测覆盖不足',
                judgement='金额目标 120.00 亿元，已签单 20.00 亿元（1—9月）＋预测 40.00 亿元（10—12月），缺口 60.00 亿元，缺口率 50.0%。')
    assert _repeats_risk(dict(title='商机预测覆盖不足', description='x'), risk)
    assert '复述' in _repeats_risk(dict(title='储备不足', description='缺口 60.00 亿元，缺口率 50.0%'), risk)
    assert '数字' in _repeats_risk(dict(title='储备不足', description='目标 120 亿元而已签单 20 加预测 40'), risk)
    assert _repeats_risk(dict(title='战略客户需求未确认', description='C01 有 12 条战略客户 P0 商机未签单'), risk) == ''
    # The model is asked once more when a cause restates its risk; what still repeats is dropped.
    value = _strategic_value()
    established = [item['riskCode'] for item in _judged(value, _judge_no)['findings']]
    seen = []
    owned = {'RK01': 'R01', 'RK06': 'R08', 'RK11': 'R13'}
    restate = dict(risks=[dict(code=code, causes=[dict(title='风险复述', description=value['risks'][0]['description'],
                                                        dataGaps='', evidence=[owned[code]])]) for code in established])
    judged = _judged(value, _ai_judge([restate, restate], seen))
    calls = [item for item in seen if item['kind'] == 'global_causes']
    assert len(calls) == 2 and '根因不得重复风险已有内容' in '；'.join(calls[1]['validationFeedback'])
    from bi_agent.cockpit.opportunity_judgement import GLOBAL_CAUSE_PROMPT
    assert '根因不得复述该风险 judgement' in GLOBAL_CAUSE_PROMPT
    # 1117 1119 BR-L01: what still repeats after the retry is dropped and the
    # risk shows “暂无可验证根因”.
    assert not judged['causes']
    assert {finding['causeNote'] for finding in judged['findings']} == {'暂无可验证根因'}
    # Without any usable cause, each risk says why under it.
    empty = _judged(value, _ai_judge([dict(risks=[]), dict(risks=[])], []))
    assert not empty['causes']
    assert all(finding['causeNote'] for finding in empty['findings'])


def test_ai_root_causes_follow_the_1119_publishing_rules():
    from bi_agent.cockpit.opportunity_judgement import (
        _forbidden, _inflight_sentence, _tidy, _untraceable_numbers)
    from bi_agent.cockpit.opportunity_v2 import _volume_phrase

    def cause(text, title='原因'):
        return dict(title=title, description=text)
    # No overall “商机储备不足” on any risk; RK06 may describe its own gap customers.
    assert _forbidden('RK01', cause('商机储备严重不足，后续签单承接乏力'))
    assert _forbidden('RK11', cause('整体商机池不足'))
    assert _forbidden('RK06', cause('全局商机储备偏少'))
    assert _forbidden('RK06', cause('存在缺口的客户中战略及重点客户的商机储备不足，占比 8.4%')) == ''
    # C10 strategic reserve belongs to RK06 only.
    assert _forbidden('RK01', cause('战略及重点客户的商机储备占比 8.4%'))
    # P0-09 never comes from the model, on any risk.
    assert _forbidden('RK11', cause('截至观察日仍处于商机获取阶段的商机有 9 个'))
    assert _forbidden('RK01', cause('在途商机拖累需求确认'))
    # BR-D02: small business counts are checked too; month spans and codes are labels.
    assert _untraceable_numbers('有 3 家客户', {'5'}) == ['3']
    assert _untraceable_numbers('1—9月已签单，P0-09 与 R13 对比', set()) == []
    # Wording: no “反映”, business stage names.
    assert _tidy('数据反映出P0阶段停留较长，正缺口客户集中') == '商机获取阶段停留较长，存在缺口的客户集中'
    # Completeness wording (BR-V09) and the fixed P0-09 sentence (BR-V12).
    assert _volume_phrase('金额', 5.0, '亿元', 4, 0) == '涉及预测金额 5.00 亿元'
    assert _volume_phrase('金额', 5.0, '亿元', 4, 1) == '已记录预测金额 5.00 亿元'
    assert _volume_phrase('金额', None, '亿元', 4, 4) == '预测金额待核实'
    assert _inflight_sentence(dict(count=9, amount=2.5, energy=None, missingAmount=0)) == (
        '截至观察日，仍处于商机获取阶段且严重超期的商机有 9 个，涉及预测金额 2.50 亿元。')


def test_ai_root_causes_use_only_their_own_risk_evidence():
    value = _strategic_value()
    established = [item['riskCode'] for item in _judged(value, _judge_no)['findings']]
    assert 'RK01' in established
    seen = []
    # RK01 citing RK06's C10 is evidence from another risk: dropped after the retry.
    borrowed = dict(risks=[dict(code='RK01', causes=[dict(title='客户结构集中', description='依据输入数据',
                                                          dataGaps='', evidence=['C10'])])])
    judged = _judged(value, _ai_judge([borrowed, borrowed], seen))
    feedback = '；'.join(seen[-1]['validationFeedback'])
    assert '不属于该风险的指标 C10' in feedback
    assert 'RK01' not in {code for item in judged['causes'] for code in item['riskCodes']}
    # The model never receives P0-09.
    request = next(item for item in seen if item['kind'] == 'global_causes')
    assert all(metric['code'] != 'P0-09' for risk in request['risks'] for metric in risk['metrics'])


def test_the_ontology_queries_bind_period_and_observation_day():
    from bi_agent.cockpit.opportunity_v2 import _ontology_specs

    specs = _ontology_specs(load_config(), 2025, date(2025, 10, 31))
    assert [label for label, _, _ in specs] == ['商机预测缺口', '客户预测缺口', 'P0在途超期', '战略重点商机储备', '无商机战略客户']
    assert all(params == [date(2025, 1, 1), date(2026, 1, 1), date(2025, 10, 31)] for _, _, params in specs)
    assert all(sql.count('%s') == 3 for _, sql, _ in specs)


def test_judgement_output_budget_comes_from_the_env_context_tokens(monkeypatch):
    from bi_agent.cockpit.opportunity_judgement import _output_tokens
    from bi_agent.llm.context_budget import estimate_request

    messages = [dict(role='user', content='{"risks": []}')]
    monkeypatch.delenv('COCKPIT_MODEL_CONTEXT_TOKENS', raising=False)
    assert _output_tokens(messages, 'prompt', 1500) == 1500
    # .env COCKPIT_MODEL_CONTEXT_TOKENS: the output may use what the input leaves.
    monkeypatch.setenv('COCKPIT_MODEL_CONTEXT_TOKENS', '300000')
    assert _output_tokens(messages, 'prompt', 1500) == 300000 - estimate_request(messages, 'prompt')
