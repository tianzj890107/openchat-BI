from copy import deepcopy
from datetime import date
from types import SimpleNamespace

from bi_agent.cockpit.opportunity_v2 import (
    ModelJSONOutputError, _customer_tier, _p0_cycle, _p2_cycle, apply_text_interpretation,
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


def _complete_risk_assessments(value):
    items = []
    for candidate in value['riskCandidates']:
        if candidate['ruleStatus'] == 'triggered':
            items.append(dict(
                code=candidate['code'], include=True, classification='confirmed',
                description='规则证据支持该风险成立，需结合业务核查。',
                evidenceIds=[candidate['evidenceIds'][0]],
            ))
        else:
            items.append(dict(
                code=candidate['code'], include=False,
                classification=('insufficient' if candidate['ruleStatus'] in {'indeterminate', 'insufficient'}
                                else 'not_applicable'),
                description='现有证据不足以确认该风险成立。',
                evidenceIds=[candidate['evidenceIds'][0]] if candidate['evidenceIds'] else [],
            ))
    return items


def _model_evaluated():
    fact_id = 'fact:1'
    risk_id = 'risk-1'
    risk = dict(
        id=risk_id, code='RK01', name='商机预测覆盖不足', title='商机预测覆盖不足',
        rule='当商机预测低于年度目标时触发', condition='预测 95 亿元 < 目标 319 亿元',
        ruleStatus='triggered', level='高', description='年度目标与预测存在缺口 10 亿元。',
        metricCodes=['M01'], observed=[dict(label='预测', value=95, unit='亿元')],
        missingEvidence=[], evidenceIds=[fact_id], impact={},
    )
    cause = dict(
        id='cause-1', causeCode='RC01', code='RC01', title='客户覆盖不足',
        description='战略客户商机覆盖不足 10 家。', kind='hypothesis',
        status='hypothesis', stage='opportunity', riskCodes=['RK01'],
        findingIds=[risk_id], evidenceIds=[fact_id],
    )
    advice = dict(
        id='advice-1', adviceCode='AC01', code='AC01', name='推进客户覆盖',
        action='完成战略客户商机覆盖', measure='逐户建立商机', object='战略客户',
        ownerRole='销售负责人', deadline='30天', deadlineType='days', deadlineDays=30,
        targetValue='覆盖率 100%', tracking='周度跟踪', priority='高', acceptance='形成清单',
        causeCodes=['RC01'], riskCodes=['RK01'], evidenceIds=[fact_id],
        actionType='investigation', governance=False, causeIds=['cause-1'],
        ownerConfirmed=False, deadlineConfirmed=False, linkedRiskCodes=['RK01'],
        detail='逐户建立商机',
    )
    result = dict(
        businessSummary='年度目标与预测存在缺口 10 亿元。',
        summary='年度目标与预测存在缺口 10 亿元。',
        causes=[dict(cause)], recommendations=[dict(advice)],
    )
    return dict(
        risks=[dict(risk)], riskCandidates=[dict(risk)],
        causeCandidates=[{key: cause[key] for key in (
            'code', 'title', 'description', 'kind', 'status', 'stage', 'riskCodes', 'evidenceIds'
        )}],
        adviceCandidates=[{key: advice[key] for key in (
            'code', 'name', 'action', 'measure', 'object', 'ownerRole', 'deadline',
            'deadlineType', 'deadlineDays', 'targetValue', 'tracking', 'priority',
            'acceptance', 'causeCodes', 'riskCodes', 'evidenceIds'
        )}],
        result=result,
        evidence=dict(
            facts=[dict(id=fact_id, label='目标缺口', value=10, unit='亿元',
                        definition='目标减预测')],
            records=[], evidence=[], counts={}, limitations=[],
        ),
        textSamples=[],
    )


def _answer_from_payload(payload, summary='商机经营存在需重点推进的问题，需要结合项目进展逐项核实。'):
    """A complete, contract-conforming model answer built from the model payload."""
    included, risks, risk_evidence = set(), [], {}
    for item in payload['ruleOutcomes']:
        if item['ruleStatus'] == 'triggered' and item['evidenceIds']:
            included.add(item['code'])
            risk_evidence[item['code']] = item['evidenceIds'][:1]
            risks.append(dict(code=item['code'], include=True, classification='confirmed',
                              title='本轮风险需重点核实',
                              description='本轮数据显示该风险成立，需要结合项目进展核实。',
                              evidenceIds=item['evidenceIds'][:1], opposingEvidenceIds=[]))
        else:
            risks.append(dict(code=item['code'], include=False,
                              classification=('insufficient' if item['ruleStatus'] == 'insufficient'
                                              else 'not_applicable')))
    causes, cause_codes = [], set()
    for item in payload['causeCandidates']:
        linked = set(item['riskCodes']) & included
        if linked:
            cited = item['evidenceIds'][:1] or risk_evidence[sorted(linked)[0]]
            causes.append(dict(code=item['code'], title='推进卡点待核实',
                               description='本轮项目进展显示推进存在卡点，需要人工复核。',
                               riskCodes=sorted(linked), evidenceIds=cited))
            cause_codes.add(item['code'])
    advice = []
    for item in payload['adviceCandidates']:
        linked = set(item['riskCodes']) & included
        if linked:
            cited = item['evidenceIds'][:1] or risk_evidence[sorted(linked)[0]]
            advice.append(dict(code=item['code'], action='逐项核实受影响商机并制定推进计划',
                               ownerRole='销售负责人', deadlineDays=15,
                               acceptance='形成逐项核查清单并确认结果',
                               riskCodes=sorted(linked),
                               causeCodes=sorted(set(item['causeCodes']) & cause_codes),
                               evidenceIds=cited))
    return dict(summary=summary, risks=risks, causes=causes, advice=advice)


def _strategic_value(**updates):
    return evaluate(_data(
        opportunities=[_opportunity()], allOpportunities=[deepcopy(_opportunity())],
        accounts=[dict(id='account-1', name='战略客户A', level='1', tier='strategic')],
        **updates,
    ))


def _payload_answer(value, **changes):
    """Capture the payload the model receives and answer it completely."""
    captured = []

    def interpreter(payload):
        captured.append(payload)
        answer = _answer_from_payload(payload)
        answer.update(changes)
        return answer
    return interpreter, captured


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
                      text_interpreter=_answer_from_payload,
                      progress=lambda phase, **detail: events.append((phase, detail)))
    phases = [phase for phase, _ in events]
    assert phases[0] == 'ontology'
    assert phases.count('fetching') >= 9
    assert phases[-3:] == ['rules', 'analysing', 'publishing']
    fetch = [detail for phase, detail in events if phase == 'fetching']
    assert fetch[-1]['completed'] == fetch[-1]['total'] == 9
    assert len(card['result']['queryCatalog']) == 9
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


def test_default_text_interpreter_repairs_malformed_json_once(monkeypatch):
    import bi_agent.llm.provider as provider
    from bi_agent.cockpit.opportunity_v2 import default_text_interpreter

    calls = []

    def fake_stream(messages, system_prompt, *args, **kwargs):
        calls.append((messages, system_prompt))
        if len(calls) == 1:
            return iter([
                dict(type='text_delta', text='{"summary":"缺少逗号" "risks":[]}'),
                dict(type='message_end', stop_reason='end_turn'),
            ])
        return iter([
            dict(type='text_delta', text='{"summary":"修复后的摘要","risks":[],"causes":[],"advice":[]}'),
            dict(type='message_end', stop_reason='end_turn'),
        ])

    monkeypatch.setattr(provider, 'stream_message', fake_stream)
    value = default_text_interpreter({'progressSamples': []})
    assert value['summary'] == '修复后的摘要'
    assert value.model_calls == 2
    assert 'JSON 修复器' in calls[1][1]


def test_default_text_interpreter_regenerates_truncated_json_once(monkeypatch):
    import bi_agent.llm.provider as provider
    from bi_agent.cockpit.opportunity_v2 import default_text_interpreter

    calls = []

    def fake_stream(messages, system_prompt, *args, **kwargs):
        calls.append((messages, system_prompt))
        if len(calls) == 1:
            return iter([
                dict(type='text_delta', text='{"summary":"输出被截断","risks":['),
                dict(type='message_end', stop_reason='max_tokens'),
            ])
        return iter([
            dict(type='text_delta', text='{"summary":"重新生成的摘要","risks":[],"causes":[],"advice":[]}'),
            dict(type='message_end', stop_reason='end_turn'),
        ])

    monkeypatch.setattr(provider, 'stream_message', fake_stream)
    value = default_text_interpreter({'progressSamples': []})
    assert value['summary'] == '重新生成的摘要'
    assert value.model_calls == 2
    assert '压缩文字' in calls[1][1]


def test_stream_interruption_repairs_the_partial_body(monkeypatch):
    import bi_agent.llm.provider as provider
    from bi_agent.cockpit.opportunity_v2 import default_text_interpreter

    calls = []

    def fake_stream(messages, system_prompt, *args, **kwargs):
        calls.append((messages, system_prompt))
        if len(calls) == 1:
            def interrupted():
                yield dict(type='text_delta', text='{"summary":"部分正文","risks":[],"causes":[],"advice":[]}')
                raise RuntimeError('stream disconnected')
            return interrupted()
        return iter([
            dict(type='text_delta', text='{"summary":"修复后的摘要","risks":[],"causes":[],"advice":[]}'),
            dict(type='message_end', stop_reason='end_turn'),
        ])

    monkeypatch.setattr(provider, 'stream_message', fake_stream)
    value = default_text_interpreter({'progressSamples': []})
    assert value['summary'] == '修复后的摘要'
    assert value.model_calls == 2
    assert 'JSON 修复器' in calls[1][1]
    assert '部分正文' in calls[1][0][0]['content']


def test_stream_error_event_repairs_the_partial_body(monkeypatch):
    import bi_agent.llm.provider as provider
    from bi_agent.cockpit.opportunity_v2 import default_text_interpreter

    calls = []

    def fake_stream(messages, system_prompt, *args, **kwargs):
        calls.append((messages, system_prompt))
        if len(calls) == 1:
            return iter([
                dict(type='text_delta', text='{"summary":"中断前的正文","risks":[]}'),
                dict(type='error', error='upstream reset'),
            ])
        return iter([
            dict(type='text_delta', text='{"summary":"错误恢复摘要","risks":[],"causes":[],"advice":[]}'),
            dict(type='message_end', stop_reason='end_turn'),
        ])

    monkeypatch.setattr(provider, 'stream_message', fake_stream)
    value = default_text_interpreter({'progressSamples': []})
    assert value['summary'] == '错误恢复摘要'
    assert value.model_calls == 2
    assert 'JSON 修复器' in calls[1][1]


def test_stream_without_message_end_repairs_the_partial_body(monkeypatch):
    import bi_agent.llm.provider as provider
    from bi_agent.cockpit.opportunity_v2 import default_text_interpreter

    calls = []

    def fake_stream(messages, system_prompt, *args, **kwargs):
        calls.append((messages, system_prompt))
        if len(calls) == 1:
            return iter([
                dict(type='text_delta', text='{"summary":"缺少结束事件","risks":[],"causes":[],"advice":[]}'),
            ])
        return iter([
            dict(type='text_delta', text='{"summary":"结束事件恢复摘要","risks":[],"causes":[],"advice":[]}'),
            dict(type='message_end', stop_reason='end_turn'),
        ])

    monkeypatch.setattr(provider, 'stream_message', fake_stream)
    value = default_text_interpreter({'progressSamples': []})
    assert value['summary'] == '结束事件恢复摘要'
    assert value.model_calls == 2
    assert 'JSON 修复器' in calls[1][1]


def test_repair_call_uses_the_remaining_total_budget(monkeypatch):
    from bi_agent.cockpit import opportunity_v2 as module

    clock = {'now': 100.0}
    calls = []
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock['now'])

    def fake_read(provider, messages, system_prompt, key, *, max_tokens, timeout, step=""):
        calls.append(timeout)
        if len(calls) == 1:
            clock['now'] += 120.0
            raise module.ModelJSONOutputError(
                '模型输出不是合法 JSON', raw_text='{"summary":', stop_reason='end_turn',
            )
        return ('{"summary":"预算内修复","risks":[],"causes":[],"advice":[]}', 'end_turn', {})

    monkeypatch.setattr(module, '_read_model_stream', fake_read)
    value = module._analyse_with_model(
        object(), 'route-a', [{'role': 'user', 'content': '分析'}], 'system',
        max_tokens=1200, timeout=180,
    )
    assert value['summary'] == '预算内修复'
    assert calls == [180, 60]


def test_repair_is_skipped_when_the_total_budget_is_spent(monkeypatch):
    from bi_agent.cockpit import opportunity_v2 as module

    clock = {'now': 100.0}
    calls = []
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock['now'])

    def fake_read(provider, messages, system_prompt, key, *, max_tokens, timeout, step=""):
        calls.append(timeout)
        clock['now'] += 179.0
        raise module.ModelJSONOutputError(
            '模型输出不是合法 JSON', raw_text='{"summary":', stop_reason='end_turn',
        )

    monkeypatch.setattr(module, '_read_model_stream', fake_read)
    try:
        module._analyse_with_model(
            object(), 'route-a', [{'role': 'user', 'content': '分析'}], 'system',
            max_tokens=1200, timeout=180,
        )
    except module.ModelJSONOutputError as exc:
        assert '总预算已用尽' in str(exc)
        assert exc.attempts == 1
    else:
        raise AssertionError('spent budget must not start another model call')
    assert calls == [180]


def test_model_json_failure_keeps_raw_tail_for_diagnostics(monkeypatch):
    import bi_agent.llm.provider as provider
    from bi_agent.cockpit.opportunity_v2 import ModelJSONOutputError, default_text_interpreter

    def fake_stream(messages, system_prompt, *args, **kwargs):
        return iter([
            dict(type='text_delta', text='{"summary":"始终不合法" "risks":[]}'),
            dict(type='message_end', stop_reason='end_turn'),
        ])

    monkeypatch.setattr(provider, 'stream_message', fake_stream)
    try:
        default_text_interpreter({'progressSamples': []})
    except ModelJSONOutputError as exc:
        assert exc.attempts == 2
        assert exc.raw_text.startswith('{"summary"')
        assert 'JSON 解析失败' in str(exc)
    else:
        raise AssertionError('malformed model JSON must not be accepted')


def test_transport_timeout_retries_the_next_model_route(monkeypatch):
    import bi_agent.llm.provider as provider
    from bi_agent.cockpit import opportunity_v2 as module

    seen = []

    def fake_stream(messages, system_prompt, allowed, key, **kwargs):
        seen.append(key)
        if key == 'route-a':
            raise RuntimeError('Team API stream error: ReadTimeout: timed out')
        return iter([
            dict(type='text_delta', text='{"summary":"备用路由摘要","risks":[],"causes":[],"advice":[]}'),
            dict(type='message_end', stop_reason='end_turn'),
        ])

    monkeypatch.setattr(provider, 'stream_message', fake_stream)
    monkeypatch.setattr(module, '_model_candidate_keys', lambda: ['route-a', 'route-b'])
    value = module.default_text_interpreter({'progressSamples': []})
    assert value['summary'] == '备用路由摘要'
    assert seen == ['route-a', 'route-b']


def test_local_model_uses_only_the_configured_route(monkeypatch):
    from bi_agent.llm import registry
    from bi_agent.cockpit import opportunity_v2 as module

    models = [dict(key='team-configured', provider='team',
                   model_id='customer-local-qwen', supports_thinking=False)]
    monkeypatch.setattr(registry, 'MODELS', models)
    monkeypatch.setattr(registry, 'get_default_model_key', lambda: 'team-configured')
    monkeypatch.delenv(module._MODEL_KEY_ENV, raising=False)
    assert module._model_candidate_keys() == ['team-configured']


def test_fallback_route_uses_the_remaining_180_second_budget(monkeypatch):
    from bi_agent.cockpit import opportunity_v2 as module

    calls = []

    def fake_analyse(provider, key, messages, system_prompt, *, max_tokens, timeout, step=''):
        calls.append((key, timeout))
        if key == 'route-a':
            raise RuntimeError('Team API stream error: ReadTimeout: timed out')
        return module.ModelJSONResult(
            dict(summary='备用路由摘要', risks=[], causes=[], advice=[]),
        )

    monkeypatch.setattr(module, '_model_candidate_keys', lambda: ['route-a', 'route-b'])
    monkeypatch.setattr(module, '_analyse_with_model', fake_analyse)
    monkeypatch.setenv(module._MODEL_TIMEOUT_ENV, '180')
    value = module.default_text_interpreter({'progressSamples': []})
    assert value['summary'] == '备用路由摘要'
    assert [key for key, _ in calls] == ['route-a', 'route-b']
    assert all(0 < timeout <= 180 for _, timeout in calls)




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
                      supplement=supplement, text_interpreter=_answer_from_payload)
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


def test_model_failure_does_not_replace_the_published_card():
    from bi_agent.cockpit.opportunity_v2 import OpportunityV2ModelUnavailable

    class Result:
        truncated = False
        rows = []

    class Database:
        available = True
        config = SimpleNamespace(schema='ded_public', statement_timeout_ms=1000)

        def run(self, sql, params, timeout_ms=0):
            return Result()

    def broken(_payload):
        raise RuntimeError('model connection failed')

    def capture(entry):
        captured.append(entry)
        return dict(diagnosticId='diag-model')

    captured = []
    try:
        build_card('2026', database=Database(), measurement_date='2026-11-11',
                   text_interpreter=broken, diagnostic_reporter=capture)
    except OpportunityV2ModelUnavailable as exc:
        assert exc.phase == 'model'
        assert exc.code == 'MODEL_ANALYSIS_INCOMPLETE'
        assert exc.model_status == 'failed'
        assert exc.public_message.splitlines()[0] == '原因：无法连接模型服务'
        assert '模型返回：model connection failed' in exc.public_message
    else:
        raise AssertionError('model failure must not publish template output')
    assert captured and captured[0]['phase'] == 'model'




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
                      text_interpreter=_answer_from_payload)
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
                      text_interpreter=_answer_from_payload)
    item = next(q for q in card['result']['queryCatalog'] if q['label'] == '销售目标')
    assert item['truncated'] is True
    assert item['rowCount'] == 150
    assert item['sampleRowCount'] == item['sampleLimit']
    assert item['sampleTruncated'] is True
    assert len(item['sampleRows']) == item['sampleLimit']


def test_model_writes_every_card_text_from_ontology_context():
    value = _strategic_value(
        progress={'opp-1': [dict(id='p1', description='客户要求补充资质文件', startAt='2026-10-01')]})
    interpreter, captured = _payload_answer(value)
    status = apply_text_interpretation(value, interpreter)
    assert status['status'] == 'completed' and status['analysisMode'] == 'model'
    payload = captured[0]
    # The ontology chain is sent as context: every candidate risk, cause and advice.
    assert {item['code'] for item in payload['ruleOutcomes']} == set(load_config()['risks'])
    assert payload['causeCandidates'] and payload['adviceCandidates']
    result = value['result']
    assert result['summary'] == result['businessSummary'] == _answer_from_payload(payload)['summary']
    assert result['findings']
    assert all(item['title'] == '本轮风险需重点核实' for item in result['findings'])
    assert all(item['description'] == '本轮数据显示该风险成立，需要结合项目进展核实。'
               for item in result['findings'])
    assert result['causes'] and all(item['title'] == '推进卡点待核实' for item in result['causes'])
    for item in result['recommendations']:
        assert item['action'] == '逐项核实受影响商机并制定推进计划'
        assert item['ownerRole'] == '销售负责人' and item['deadlineDays'] == 15
        assert item['acceptance'] == '形成逐项核查清单并确认结果'
        assert 'targetValue' not in item and 'tracking' not in item
    assert result['analysisDimensions']
    assert 'textFallbackSections' not in result


def test_model_text_is_never_filled_from_ontology_candidates():
    value = _model_evaluated()
    status = apply_text_interpretation(value, lambda payload: {
        'summary': '商机获取存在覆盖缺口，需要优先推进战略客户转化。',
        'risks': [dict(code='RK01', include=True, classification='confirmed')],
        'causes': [dict(code='RC01')],
        'advice': [dict(code='AC01')],
    })
    assert status['status'] == 'rejected'
    assert status['error'] == 'MODEL_ANALYSIS_REJECTED'
    assert status['rejectedRisks'] == ['RK01']
    assert '模型未完成全部已命中风险的判断' in status['modelErrorMessage']


def test_missing_or_invalid_risk_judgement_rejects_the_whole_analysis():
    value = _strategic_value()
    interpreter, _ = _payload_answer(value)

    triggered = next(item['code'] for item in value['riskCandidates']
                     if item['ruleStatus'] == 'triggered')

    def omit_triggered(payload):
        answer = interpreter(payload)
        answer['risks'] = [item for item in answer['risks'] if item['code'] != triggered]
        return answer
    status = apply_text_interpretation(value, omit_triggered)
    assert status['status'] == 'rejected' and status['missingRiskCodes'] == [triggered]
    assert status['repairAttempted'] is True

    value = _strategic_value()
    candidate = next(item for item in value['riskCandidates'] if item['ruleStatus'] != 'triggered')

    def confirm_untriggered(payload):
        answer = interpreter(payload)
        for item in answer['risks']:
            if item['code'] == candidate['code']:
                item.update(include=True, classification='confirmed', title='模型改判成立',
                            description='模型认为风险成立。',
                            evidenceIds=candidate['evidenceIds'][:1])
        return answer
    status = apply_text_interpretation(value, confirm_untriggered)
    assert status['status'] == 'rejected' and candidate['code'] in status['rejectedRisks']


def test_invented_numbers_or_evidence_reject_instead_of_falling_back():
    value = _strategic_value()
    interpreter, _ = _payload_answer(value, summary='新增 999 家客户风险。')
    before = deepcopy(value['result'])
    status = apply_text_interpretation(value, interpreter)
    assert status['status'] == 'rejected'
    assert '摘要' in status['modelErrorMessage']
    assert value['result'] == before

    value = _strategic_value()
    base, _ = _payload_answer(value)

    def invented_evidence(payload):
        answer = base(payload)
        for item in answer['risks']:
            if item['include']:
                item['opposingEvidenceIds'] = ['model-invented-evidence']
        return answer
    status = apply_text_interpretation(value, invented_evidence)
    assert status['status'] == 'rejected' and status['rejectedRisks']


def test_included_risks_need_model_causes_and_advice():
    value = _strategic_value()
    interpreter, _ = _payload_answer(value, causes=[], advice=[])
    status = apply_text_interpretation(value, interpreter)
    assert status['status'] == 'rejected'
    assert '根因' in status['modelErrorMessage']

    value = _strategic_value()
    base, _ = _payload_answer(value)

    def advice_without_owner(payload):
        answer = base(payload)
        for item in answer['advice']:
            item.pop('ownerRole')
        return answer
    status = apply_text_interpretation(value, advice_without_owner)
    assert status['status'] == 'rejected' and status['rejectedAdvice']


def test_invalid_model_json_is_rejected_and_does_not_touch_the_card():
    value = _model_evaluated()
    before = deepcopy(value['result'])

    def broken(_payload):
        raise ModelJSONOutputError('模型未返回合法 JSON', raw_text='{"risks": [',
                                   repair_text='{"risks"', attempts=2)

    status = apply_text_interpretation(value, broken)
    assert status['status'] == 'rejected'
    assert status['error'] == 'MODEL_OUTPUT_INVALID'
    assert status['modelCalls'] == 2
    assert status['modelRawResponseTail'] == '{"risks": ['
    assert value['result'] == before


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


def test_build_card_without_model_raises_instead_of_using_templates():
    from bi_agent.cockpit.opportunity_v2 import OpportunityV2ModelUnavailable
    try:
        build_card('2026', database=_empty_database(), measurement_date='2026-11-11')
    except OpportunityV2ModelUnavailable as exc:
        assert exc.model_error == 'MODEL_DISABLED'
        assert '必须由模型生成' in exc.public_message
    else:
        raise AssertionError('a card without model analysis must not be built')


def test_rejected_model_answer_is_not_published():
    from bi_agent.cockpit.opportunity_v2 import OpportunityV2ModelUnavailable

    def broken(_payload):
        raise ModelJSONOutputError('模型未返回合法 JSON', raw_text='not json', attempts=1)

    try:
        build_card('2026', database=_empty_database(), measurement_date='2026-11-11',
                   text_interpreter=broken)
    except OpportunityV2ModelUnavailable as exc:
        assert exc.model_status == 'rejected'
        assert exc.model_error == 'MODEL_OUTPUT_INVALID'
        assert exc.public_message.splitlines()[0] == '原因：模型输出格式不对'
        assert '模型返回：模型未返回合法 JSON' in exc.public_message
    else:
        raise AssertionError('a rejected model answer must not publish a card')


def test_published_card_is_written_by_the_model():
    card = build_card('2026', database=_empty_database(), measurement_date='2026-11-11',
                      text_interpreter=_answer_from_payload)
    assembly = card['result']['analysisAssembly']
    assert assembly == dict(cardWriter='model', modelContract='ontology-context-v1',
                            modelStatus='completed', modelAnalysisUsed=True)
    assert card['result']['businessSummary'] == card['result']['summary']
    assert 'retention' not in card['execution']


def test_model_prompt_treats_ontology_as_context_not_template(monkeypatch):
    import bi_agent.llm.provider as provider
    from bi_agent.cockpit import opportunity_v2 as module

    captured = []

    def fake_stream(messages, system_prompt, *args, **kwargs):
        captured.append(system_prompt)
        return iter([
            dict(type='text_delta', text='{"summary":"摘要","risks":[],"causes":[],"advice":[]}'),
            dict(type='message_end', stop_reason='end_turn'),
        ])

    monkeypatch.setattr(provider, 'stream_message', fake_stream)
    monkeypatch.setattr(module, '_model_candidate_keys', lambda: ['route-a'])
    module.default_text_interpreter({'progressSamples': []})
    prompt = captured[0]
    assert '分析链与上下文约束' in prompt and '不是结论模板' in prompt
    assert '不得照抄候选' in prompt
    assert 'ownerRole' in prompt and 'acceptance' in prompt and 'deadlineDays' in prompt
    assert '程序会用本体候选字段补齐' not in prompt


def test_reasoning_only_stream_is_explained_with_call_context(monkeypatch):
    import bi_agent.llm.provider as provider
    from bi_agent.cockpit import opportunity_v2 as module

    def fake_stream(messages, system_prompt, *args, **kwargs):
        return iter([
            dict(type='thinking_block', text='推' * 500),
            dict(type='message_end', stop_reason='end_turn', finish_reason='stop',
                 usage=dict(input_tokens=21000, output_tokens=12000)),
        ])

    monkeypatch.setattr(provider, 'stream_message', fake_stream)
    monkeypatch.setattr(module, '_model_candidate_keys', lambda: ['route-a'])
    value = _model_evaluated()
    status = apply_text_interpretation(value, module.default_text_interpreter)
    assert status['status'] == 'failed'
    assert status['modelErrorType'] == 'ModelEmptyResponse'
    assert status['modelReasoningChars'] == 500
    assert status['modelFinishReason'] == 'stop'
    assert status['modelRoute'] == 'route-a' and status['modelInputChars'] > 0
    message = module._model_failure_message(status)
    lines = message.splitlines()
    assert lines[0] == '原因：模型只输出了推理过程，没有正文'
    assert any(line.startswith('调用情况：模型 route-a · 输入约 ') for line in lines)
    assert '推理内容 500 字' in message and '输出 token 12000' in message
    assert lines[-1].startswith('建议：改用不带推理的模型路由')


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
    assert category(error='MODEL_ANALYSIS_REJECTED',
                    modelErrorMessage='模型未完成全部本体风险判断：RK03') == '模型分析不符合要求'
    assert category(error='MODEL_DISABLED') == '未启用模型分析'


def test_model_request_exposes_no_tools_and_tool_call_answers_are_explained(monkeypatch):
    import bi_agent.llm.provider as provider
    from bi_agent.cockpit import opportunity_v2 as module

    seen = []

    def fake_stream(messages, system_prompt, allowed_tools, *args, **kwargs):
        seen.append(allowed_tools)
        return iter([
            dict(type='tool_use_start', id='call-1', name='Ontology-MetricQuery'),
            dict(type='tool_use_end', id='call-1', name='Ontology-MetricQuery', input={}),
            dict(type='message_end', stop_reason='tool_use', finish_reason='tool_calls',
                 usage=dict(input_tokens=11809, output_tokens=48)),
        ])

    monkeypatch.setattr(provider, 'stream_message', fake_stream)
    monkeypatch.setattr(module, '_model_candidate_keys', lambda: ['route-a'])
    status = apply_text_interpretation(_model_evaluated(), module.default_text_interpreter)
    # None would expose every registered tool; the analysis step must send none.
    assert seen == [[]]
    assert status['status'] == 'failed'
    assert status['modelToolCalls'] == ['Ontology-MetricQuery']
    message = module._model_failure_message(status)
    assert message.splitlines()[0] == '原因：模型没有作答，而是发起了工具调用'
    assert 'Ontology-MetricQuery' in message


def test_failure_details_cover_request_calls_answer_and_rejections(monkeypatch):
    import bi_agent.llm.provider as provider
    from bi_agent.cockpit import opportunity_v2 as module

    def fake_stream(messages, system_prompt, allowed_tools, *args, **kwargs):
        return iter([
            dict(type='text_delta', text='{"summary":"商机存在缺口","risks":[{"code":"RK01",'
                 '"include":true,"classification":"confirmed","title":"覆盖不足"}],'
                 '"causes":[],"advice":[]}'),
            dict(type='message_end', stop_reason='end_turn', finish_reason='stop',
                 usage=dict(input_tokens=11809, output_tokens=96)),
        ])

    monkeypatch.setattr(provider, 'stream_message', fake_stream)
    monkeypatch.setattr(module, '_model_candidate_keys', lambda: ['route-a'])
    status = apply_text_interpretation(_model_evaluated(), module.default_text_interpreter)
    assert status['status'] == 'rejected'
    assert status['rejectionReasons'] == {'risks': ['RK01：缺少风险说明']}
    assert status['repairAttempted'] is True and status['modelCalls'] == 2
    sections = {item['title']: item['lines'] for item in module._model_failure_details(status)}
    assert list(sections) == ['请求内容', '调用过程', '错误原文', '第一次回答的校验问题（已发回模型修正）',
                              '修正后仍未通过的明细', '模型原始返回（节选）']
    assert sections['第一次回答的校验问题（已发回模型修正）'] == ['风险 RK01：缺少风险说明']
    assert sections['调用过程'][1].startswith('第 2 次 · 按校验意见修正')
    request = '\n'.join(sections['请求内容'])
    assert '模型：route-a' in request and '附带工具：0 个' in request
    assert '本体风险候选 1 条' in request and 'max_tokens=12000' in request
    call = sections['调用过程'][0]
    assert call.startswith('第 1 次 · 生成分析') and '结束原因 stop' in call
    assert '输入 11809 token' in call and '输出 96 token' in call
    assert sections['修正后仍未通过的明细'] == ['风险 RK01：缺少风险说明']
    assert sections['模型原始返回（节选）'] == [
        '开头：{"summary":"商机存在缺口","risks":[{"code":"RK01","include":true,'
        '"classification":"confirmed","title":"覆盖不足"}],"causes":[],"advice":[]}']


def test_rejection_reasons_name_the_exact_problem():
    value = _strategic_value()
    base, _ = _payload_answer(value)

    def broken(payload):
        answer = base(payload)
        answer['causes'][0]['evidenceIds'] = ['model-invented-evidence']
        for item in answer['advice']:
            item['deadlineDays'] = 0
        return answer
    status = apply_text_interpretation(value, broken)
    assert status['status'] == 'rejected'
    reasons = status['rejectionReasons']
    assert any('引用了不允许的证据编号 model-invented-evidence' in item for item in reasons['causes'])
    assert all('deadlineDays 不是 1-365 的整数（实际 0）' in item for item in reasons['advice'])


def test_rule_settled_risks_never_fail_the_card_for_their_label():
    """Customer case: classification 'not_triggered' on a risk the rule did not trigger."""
    value = _strategic_value()
    base, _ = _payload_answer(value)
    settled = [item['code'] for item in value['riskCandidates'] if item['ruleStatus'] != 'triggered']
    assert len(settled) >= 2

    def confused(payload):
        answer = base(payload)
        # One rule-settled risk carries the ruleStatus vocabulary, another is omitted.
        answer['risks'] = [item for item in answer['risks'] if item['code'] != settled[1]]
        for item in answer['risks']:
            if item['code'] == settled[0]:
                item['classification'] = 'not_triggered'
        return answer
    status = apply_text_interpretation(value, confused)
    assert status['status'] == 'completed'
    assert 'repairAttempted' not in status
    assessments = {item['code']: item for item in status['riskAssessments']}
    assert assessments[settled[0]]['include'] is False
    assert assessments[settled[0]]['classification'] in {'insufficient', 'not_applicable'}
    assert assessments[settled[1]]['assessmentSource'] == 'rule'
    assert settled[0] not in value['result']['riskCodes']


def test_rejected_analysis_is_repaired_once_by_the_model():
    value = _strategic_value()
    base, _ = _payload_answer(value)
    seen = []

    def interpreter(payload):
        seen.append(payload.get('validationFeedback'))
        answer = base(payload)
        if payload.get('validationFeedback') is None:
            answer['summary'] = '年度目标数据缺失，战略客户推进需要重点关注。'
        return answer
    status = apply_text_interpretation(value, interpreter)
    assert status['status'] == 'completed'
    assert status['repairAttempted'] is True and status['modelCalls'] == 2
    assert seen[0] is None
    feedback = seen[1]
    assert feedback['issues'] == ['摘要 摘要含实现说明用语“缺失”']
    assert feedback['previousAnswer']['summary'].startswith('年度目标数据缺失')
    assert status['firstRejectionReasons'] == {'summary': ['摘要含实现说明用语“缺失”']}
    assert '缺失' not in value['result']['summary']


def test_repair_feedback_numbers_are_not_whitelisted():
    value = _strategic_value()
    base, _ = _payload_answer(value)

    def interpreter(payload):
        answer = base(payload)
        answer['summary'] = '新增 999 家客户风险。'
        return answer
    status = apply_text_interpretation(value, interpreter)
    # 999 appears in previousAnswer on the repair round but is still not evidence.
    assert status['status'] == 'rejected' and status['repairAttempted'] is True
    assert status['rejectionReasons']['summary'] == ['摘要含输入中不存在的数字 999']
