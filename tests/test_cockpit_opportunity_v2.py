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
    build_card('2026', database=Database(), measurement_date='2026-11-11',
               text_interpreter=None,
               progress=lambda phase, **detail: events.append((phase, detail)))
    phases = [phase for phase, _ in events]
    assert phases[0] == 'ontology'
    assert phases.count('fetching') >= 9
    assert phases[-3:] == ['rules', 'analysing', 'publishing']
    fetch = [detail for phase, detail in events if phase == 'fetching']
    assert fetch[-1]['completed'] == fetch[-1]['total'] == 9


def test_model_generated_text_is_validated_against_evidence_numbers_and_links():
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
    risk = value['risks'][0]
    cause = next(item for item in value['causeCandidates'] if item['code'] == 'RC02')
    advice = next(item for item in value['adviceCandidates'] if item['code'] == 'DS02')
    progress_id = value['textSamples'][0]['evidenceId']
    generated = apply_text_interpretation(value, lambda payload: {
        'summary': '模型结合规则结果与项目进展生成商机风险分析。',
        'risks': [dict(code=risk['code'], include=True, classification='confirmed',
                       description='规则证据显示该风险需要优先核查。',
                       evidenceIds=[risk['evidenceIds'][0]])],
        'causes': [dict(code=cause['code'], description='项目进展显示客户要求补充资质文件，需人工复核。',
                        riskCodes=['RK08'], evidenceIds=[progress_id])],
        'advice': [dict(code=advice['code'], action='推动客户补齐资质文件后进入投标',
                        riskCodes=['RK08'], causeCodes=['RC02'], evidenceIds=[progress_id])],
    })
    assert generated['status'] == 'completed'
    assert generated['summaryApplied'] is True
    assert generated['appliedRisks'] == [risk['code']]
    assert generated['appliedCauses'] == ['RC02']
    assert generated['appliedAdvice'] == ['DS02']
    assert value['result']['summary'].startswith('模型结合规则')
    assert next(item for item in value['risks'] if item['code'] == risk['code'])['description'] == '规则证据显示该风险需要优先核查。'
    assert next(item for item in value['result']['causes'] if item['causeCode'] == 'RC02')['description'].startswith('项目进展显示')
    assert next(item for item in value['result']['recommendations'] if item['adviceCode'] == 'DS02')['action'] == '推动客户补齐资质文件后进入投标'

    bad_value = evaluate(data)
    bad_risk = bad_value['risks'][0]
    bad = apply_text_interpretation(bad_value, lambda payload: {
        'summary': '新增 999 家客户逾期未完成',
        'risks': [dict(code='RK99', include=True, classification='confirmed',
                       description='模型自造风险', evidenceIds=[bad_risk['evidenceIds'][0]])],
        'causes': [dict(code='RC02', description='新增 999 家客户逾期未完成',
                        riskCodes=['RK01'], evidenceIds=[progress_id])],
        'advice': [dict(code='DS99', action='模型自造建议', riskCodes=['RK08'],
                        causeCodes=[], evidenceIds=[progress_id])],
    })
    assert bad['status'] == 'completed'
    assert bad['summaryApplied'] is False
    assert 'RK99' in bad['rejectedRisks']
    assert 'RC02' in bad['rejectedCauses']
    assert 'DS99' in bad['rejectedAdvice']
    assert '999' not in bad_value['result']['summary']
    assert all('999' not in item['description'] for item in bad_value['result']['causes'])

    uncited_value = evaluate(data)
    uncited = apply_text_interpretation(uncited_value, lambda payload: {
        'causes': [dict(code='RC02', description='项目进展显示客户要求补充资质文件，需人工复核。',
                        riskCodes=['RK08'], evidenceIds=['model-invented-evidence'])],
    })
    assert uncited['appliedCauses'] == []
    assert uncited['rejectedCauses'] == ['RC02']

    failed_value = evaluate(data)
    before = failed_value['result']['summary']
    def failure(_payload):
        raise RuntimeError('provider down')
    failed = apply_text_interpretation(failed_value, failure)
    assert failed['status'] == 'failed' and failed['modelCalls'] == 1
    assert failed_value['result']['summary'] == before


def test_all_ontology_candidates_are_sent_to_the_model_and_assessed():
    value = evaluate(_data(
        opportunities=[_opportunity()], allOpportunities=[deepcopy(_opportunity())],
        accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic')],
    ))
    calls = []
    completed = apply_text_interpretation(value, lambda payload: calls.append(payload) or {})

    assert completed['status'] == 'completed'
    assert len(calls) == 1
    candidates = calls[0]['ruleOutcomes']
    assert len(candidates) == 10
    assert {item['code'] for item in candidates} == set(load_config()['risks'])
    assert {item['ruleStatus'] for item in candidates} >= {'triggered', 'not_triggered'}
    assert any(item['ruleStatus'] == 'indeterminate' for item in candidates)

    assessments = {item['code']: item for item in completed['riskAssessments']}
    assert set(assessments) == set(load_config()['risks'])
    assert value['result']['riskCandidateCount'] == 10
    assert value['result']['analysedRiskCount'] == 10
    assert assessments['RK04']['include'] is False
    assert assessments['RK04']['classification'] == 'not_applicable'
    assert assessments['RK05']['classification'] == 'insufficient'
    assert assessments['RK05']['opposingEvidenceIds'] == []
    assert value['result']['excludedRiskCodes']


def test_model_cannot_confirm_a_rule_the_program_did_not_trigger():
    value = evaluate(_data(
        opportunities=[_opportunity()], allOpportunities=[deepcopy(_opportunity())],
        accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic')],
    ))
    candidate = next(item for item in value['riskCandidates'] if item['code'] == 'RK04')
    assert candidate['ruleStatus'] == 'not_triggered'
    completed = apply_text_interpretation(value, lambda payload: {
        'risks': [dict(code='RK04', include=True, classification='confirmed',
                       description='模型认为产品结构风险成立。',
                       evidenceIds=[candidate['evidenceIds'][0]])],
    })

    assert 'RK04' in completed['rejectedRisks']
    assessment = next(item for item in completed['riskAssessments'] if item['code'] == 'RK04')
    assert assessment['include'] is False
    assert assessment['classification'] == 'not_applicable'
    assert 'RK04' not in value['result']['riskCodes']


def test_model_can_downgrade_a_triggered_rule_and_records_opposing_evidence():
    value = evaluate(_data(
        opportunities=[_opportunity()], allOpportunities=[deepcopy(_opportunity())],
        accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic')],
    ))
    candidate = next(item for item in value['riskCandidates'] if item['code'] == 'RK01')
    support = candidate['evidenceIds'][0]
    opposing = next(iter(value['evidence']['facts']))['id'] if value['evidence']['facts'] else support
    completed = apply_text_interpretation(value, lambda payload: {
        'risks': [dict(code='RK01', include=False, classification='insufficient',
                       description='目标与预测口径仍需核对，暂不确认风险成立。',
                       evidenceIds=[support], opposingEvidenceIds=[opposing])],
    })

    assessment = next(item for item in completed['riskAssessments'] if item['code'] == 'RK01')
    assert assessment['include'] is False
    assert assessment['classification'] == 'insufficient'
    assert assessment['supportingEvidenceIds'] == [support]
    assert assessment['opposingEvidenceIds'] == [opposing]
    assert 'RK01' in completed['modelExcludedRisks']
    assert 'RK01' in value['result']['modelExcludedRiskCodes']
    assert 'RK01' not in value['result']['riskCodes']


def test_model_cannot_cite_support_or_opposing_evidence_outside_the_payload():
    value = evaluate(_data(
        opportunities=[_opportunity()], allOpportunities=[deepcopy(_opportunity())],
        accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic')],
    ))
    candidate = next(item for item in value['riskCandidates'] if item['code'] == 'RK01')
    support = candidate['evidenceIds'][0]
    generated = apply_text_interpretation(value, lambda payload: {
        'risks': [dict(code='RK01', include=True, classification='confirmed',
                       description='模型引用未知证据支持风险。',
                       evidenceIds=[support], opposingEvidenceIds=['model-invented-evidence'])],
    })
    assert 'RK01' in generated['rejectedRisks']
    assessment = next(item for item in generated['riskAssessments'] if item['code'] == 'RK01')
    assert assessment['opposingEvidenceIds'] == []


def test_missing_target_facts_make_rk01_indeterminate_and_block_confirmation():
    value = evaluate(_data(
        targets=dict(amount=None, energy=None, byProduct={}, byAccount={}),
        opportunities=[_opportunity()], allOpportunities=[deepcopy(_opportunity())],
    ))
    candidate = next(item for item in value['riskCandidates'] if item['code'] == 'RK01')
    assert candidate['ruleStatus'] in {'indeterminate', 'not_triggered'}
    completed = apply_text_interpretation(value, lambda payload: {
        'risks': [dict(code='RK01', include=True, classification='confirmed',
                       description='模型在目标缺失时确认覆盖不足。',
                       evidenceIds=[candidate['evidenceIds'][0]])],
    })
    assessment = next(item for item in completed['riskAssessments'] if item['code'] == 'RK01')
    assert assessment['include'] is False
    assert assessment['classification'] in {'insufficient', 'not_applicable'}


def test_model_runs_without_text_samples_and_generates_nonempty_analysis():
    opportunity = _opportunity(acneed='', stage='11', stage1End=None)
    value = evaluate(_data(
        opportunities=[opportunity], allOpportunities=[deepcopy(opportunity)],
        accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic')],
    ))
    calls = []
    completed = apply_text_interpretation(value, lambda payload: calls.append(payload) or {})
    assert len(calls) == 1 and calls[0]['progressSamples'] == []
    assert completed['status'] == 'completed' and completed['modelCalls'] == 1
    assert completed['appliedCauses'] == []

    value = evaluate(_data(
        opportunities=[_opportunity()], allOpportunities=[deepcopy(_opportunity())],
        accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic')],
        progress={'opp-1': [dict(id='p1', description='客户要求补充资质文件', startAt='2026-10-01')]},
    ))
    risk = value['risks'][0]
    progress_id = value['textSamples'][0]['evidenceId']
    filled = apply_text_interpretation(value, lambda payload: {
        'summary': '模型结合商机规则和项目进展完成本轮分析。',
        'risks': [dict(code=risk['code'], include=True, classification='confirmed',
                       description='规则证据显示该风险需要优先核查。', evidenceIds=[risk['evidenceIds'][0]])],
        'causes': [dict(code='RC02', description='项目进展显示客户要求补充资质文件，需人工复核。',
                        riskCodes=['RK08'], evidenceIds=[progress_id])],
        'advice': [dict(code='DS02', action='推动客户补齐资质文件后进入投标',
                        riskCodes=['RK08'], causeCodes=['RC02'], evidenceIds=[progress_id])],
    })
    assert filled['appliedCauses'] == ['RC02'] and filled['appliedAdvice'] == ['DS02']
    assert value['result']['summary'].startswith('模型结合')
    assert next(item for item in value['result']['causes'] if item['causeCode'] == 'RC02')['description'].startswith('项目进展显示')
    assert next(item for item in value['result']['recommendations'] if item['adviceCode'] == 'DS02')['action'] == '推动客户补齐资质文件后进入投标'

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
            dict(type='text_delta', text='```json\n{"summary":"模型摘要","risks":[{"code":"RK08","include":true,"classification":"confirmed","description":"风险说明","evidenceIds":["opp-v2:progress:p1"]}],"causes":[{"code":"RC02","description":"有文本依据","riskCodes":["RK08"],"evidenceIds":["opp-v2:progress:p1"]}],"advice":[]}\n```'),
            dict(type='message_end', stop_reason='end_turn'),
        ])

    monkeypatch.setattr(provider, 'stream_message', fake_stream)
    value = default_text_interpreter({'progressSamples': [{'evidenceId': 'opp-v2:progress:p1', 'text': '资质待补'}]})
    assert value['summary'] == '模型摘要'
    assert value['risks'][0]['code'] == 'RK08'
    assert value['causes'][0]['code'] == 'RC02'
    assert value['advice'] == []


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
