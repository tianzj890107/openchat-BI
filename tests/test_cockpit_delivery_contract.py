"""Per-slot delivery contract and reasoning checks."""
import json
import time

import pytest

from bi_agent.cockpit.cards import CONTRACT, card_delivery_state
from bi_agent.cockpit.delivery import (
    KIND_LABELS, SLOT_SPECS, checkable_acceptance, classify_cause,
    project_card, validate_reasoning,
)
from bi_agent.cockpit.store import Store


def _cause(cid='c1', title='异常', description='说明', status='hypothesis', evidence=('e1',)):
    return dict(id=cid, title=title, description=description, status=status,
                evidenceIds=list(evidence))


def _action(cid='r1', cause='c1', action='核查订单计划交付期', owner='运营负责人', days=5,
            acceptance='形成逐单核查清单'):
    return dict(id=cid, causeIds=[cause], action=action, ownerRole=owner,
                deadlineDays=days, acceptance=acceptance)


def _value(causes=None, actions=None, summary='当前范围存在异常，需要核实。'):
    return dict(summary=summary, causes=causes or [], recommendations=actions or [],
                limitations=[])


def _evidence(records=None, facts=None, limitations=None, **extra):
    value = dict(facts=facts or [], records=records or [], evidence=[],
                 limitations=limitations or [])
    value.update(extra)
    return value


def test_money_and_energy_cannot_be_compared_without_a_bridge():
    value = _value(
        causes=[_cause(title='变更金额占比不足 5%', description='金额口径不足以解释出货电量缺口')],
    )
    with pytest.raises(ValueError) as error:
        validate_reasoning(value, _evidence(), stage='combined')
    assert '金额与电量' in str(error.value)


def test_unverified_set_arithmetic_is_rejected_and_verified_one_passes():
    value = _value(causes=[_cause(
        title='取消变更与中标未签',
        description='取消变更订单电量加中标未签电量不足以解释出货缺口')])
    with pytest.raises(ValueError) as error:
        validate_reasoning(value, _evidence(), stage='combined')
    assert '相加' in str(error.value) or '对应关系' in str(error.value)
    validate_reasoning(value, _evidence(setOverlapVerified=True), stage='combined')


def test_phenomenon_cannot_be_delivered_as_cause():
    value = _value(causes=[_cause(
        title='缺口集中在国内团队', description='由于国内团队客户目标为空导致缺口')])
    with pytest.raises(ValueError) as error:
        validate_reasoning(value, _evidence(facts=[dict(label='客户目标', value=None)]))
    assert '异常表现' in str(error.value) or '结构定位' in str(error.value)


def test_target_conflict_must_be_visible_in_summary():
    evidence = _evidence(limitations=['两个来源的目标总量口径冲突，尚不能汇总'])
    with pytest.raises(ValueError) as error:
        validate_reasoning(_value(summary='发货完成度存在明显缺口。'), evidence, stage='combined')
    assert '口径冲突' in str(error.value)
    validate_reasoning(_value(
        summary='各自口径下发货完成度偏低，但目标总量口径冲突，尚不能汇总对账。'),
        evidence, stage='combined')


def test_acceptance_must_be_checkable():
    assert checkable_acceptance('形成逐单核查清单')
    assert not checkable_acceptance('缺口不再扩大')
    with pytest.raises(ValueError) as error:
        validate_reasoning(_value(actions=[_action(acceptance='缺口不再扩大')]), _evidence())
    assert '验收' in str(error.value)


def test_missing_overdue_status_only_allows_verification_actions():
    evidence = _evidence(limitations=['发货状态查询无数据，超期明细缺失'])
    with pytest.raises(ValueError) as error:
        validate_reasoning(_value(
            causes=[_cause(title='超期原因：排产延误', description='排产延误导致超期')],
            actions=[_action(action='提升排产效率')]), evidence, stage='shipment')
    message = str(error.value)
    assert '发货' in message
    validate_reasoning(_value(
        causes=[_cause(title='超期状态数据缺失', description='当前没有逐单超期状态记录')],
        actions=[_action(action='核查并补齐订单状态与计划交付期')]), evidence, stage='shipment')


def test_classify_cause_separates_verified_fact_structure_and_gap():
    assert classify_cause(_cause(status='supported', evidence=('r1',)), {'r1'}) == 'verified'
    assert classify_cause(_cause(title='缺口集中在华东团队')) == 'structure'
    assert classify_cause(_cause(title='客户目标为空')) == 'data_gap'
    assert classify_cause(_cause(title='出货量低于目标', description='缺口扩大')) == 'fact'
    assert classify_cause(_cause(title='排产延误', description='可能受物料影响')) == 'hypothesis'
    assert KIND_LABELS['hypothesis'] == '待验证假设'


def _card():
    return dict(
        id='a1', updatedAt=time.time(), status='limited',
        evidence=_evidence(records=[dict(id='e1', causeSupport=False, order='SO-1')]),
        result=dict(
            cardContract=CONTRACT,
            summary='发货完成度偏低，需核实。',
            causes=[_cause('c1', '缺口集中在国内团队', '由于客户目标为空导致'),
                    _cause('c2', '记录支持的处理未闭环', '处理记录显示质检未放行', 'supported', ('e1',))],
            recommendations=[_action('r1', 'c1', '核查客户目标', '运营负责人', 5, '缺口不再扩大')],
            limitations=['发货状态缺失']))


def test_quote_status_card_delivers_status_only():
    projected = project_card(_card(), 'quote-summary')
    assert projected['result']['causes'] == []
    assert projected['result']['recommendations'] == []
    assert '只交付报价状态概况' in projected['result']['summary']
    assert projected['result']['deliveryContract'] == 'cockpit-delivery-v2'


def test_bid_card_labels_phenomena_and_suggests_measures():
    projected = project_card(_card(), 'bid-summary')
    result = projected['result']
    assert result['causes']
    assert result['causes'][0]['title'].startswith('[异常表现]') or \
        result['causes'][0]['title'].startswith('[结构定位]')
    assert '不是已确认原因' in result['causes'][0]['description']
    if result['recommendations']:
        action = result['recommendations'][0]
        assert action['action'].startswith('建议：')
        assert '待确认' in action['ownerRole']
        assert '清单' in action['acceptance'] or '对账' in action['acceptance']


def test_shipment_overdue_slots_do_not_reuse_target_gap_analysis():
    card = _card()
    card['evidence'] = _evidence(limitations=['发货状态查询无数据'])
    card['result']['causes'] = [
        _cause('c1', '出货量低于目标', '缺口扩大'),
        _cause('c2', '发货状态数据缺失', '没有逐单超期状态记录'),
    ]
    projected = project_card(card, 'shipment-overdue-note')
    kinds = {cause['kind'] for cause in projected['result']['causes']}
    assert kinds <= {'data_gap'}
    assert '不复用出货目标缺口分析' in projected['result']['summary']


def test_order_sign_card_discloses_missing_signing_structure():
    projected = project_card(_card(), 'order-sign-summary')
    assert '不能解释签单结构' in projected['result']['summary']


def test_unsupported_set_inference_is_removed_from_summary():
    card = _card()
    card['result']['summary'] = '订单取消/变更与中标未签的量级不足以解释该缺口。'
    projected = project_card(card, 'sales-shipment-issues')
    summary = projected['result']['summary']
    assert '不足以解释' not in summary
    assert '尚不能建立与出货缺口的对应关系' in summary


def test_cross_unit_inference_is_removed_from_summary():
    card = _card()
    card['result']['summary'] = '变更取消金额占比不足 5%，难以解释出货量缺口。'
    projected = project_card(card, 'sales-shipment-issues')
    summary = projected['result']['summary']
    assert '难以解释' not in summary
    assert '金额与电量口径不同' in summary


def test_cross_unit_inference_is_removed_from_causes_and_dependent_actions():
    card = _card()
    card['result']['causes'] = [
        _cause('money-energy', '订单取消变更量级有限',
               '变更与取消金额合计占比不足5%，难以解释出货量达成缺口'),
        _cause('valid', '出货完成度低于目标', '实际出货量低于目标'),
    ]
    card['result']['recommendations'] = [
        _action('drop', 'money-energy'),
        _action('keep', 'valid'),
    ]
    projected = project_card(card, 'sales-shipment-issues')
    ids = {cause['id'] for cause in projected['result']['causes']}
    assert ids == {'valid'}
    assert [action['id'] for action in projected['result']['recommendations']] == ['keep']


def test_separate_money_and_energy_observations_are_not_removed():
    card = _card()
    card['result']['causes'] = [_cause(
        'separate', '商机覆盖不足',
        '商机预测金额152.74亿元覆盖目标321.90亿元，商机预测电量44.86GWh对目标91.96GWh')]
    projected = project_card(card, 'sales-shipment-issues')
    assert [cause['id'] for cause in projected['result']['causes']] == ['separate']


def test_unsupported_attrition_clause_is_removed_from_mixed_summary():
    card = _card()
    card['result']['summary'] = '订单取消变更量级有限，发货办理状态证据缺失。'
    projected = project_card(card, 'sales-shipment-issues')
    summary = projected['result']['summary']
    assert '订单取消变更量级有限' not in summary
    assert '发货办理状态证据缺失' in summary


def test_actions_with_dangling_cause_references_are_dropped():
    card = _card()
    card['result']['recommendations'] = [dict(
        id='r1', causeIds=['c1', 'signed-unsigned-scope'], action='核查订单',
        ownerRole='运营负责人', deadlineDays=5, acceptance='形成核查清单')]
    projected = project_card(card, 'sales-shipment-issues')
    ids = {cause['id'] for cause in projected['result']['causes']}
    for action in projected['result']['recommendations']:
        assert set(action['causeIds']) <= ids


def test_title_level_observation_and_data_quality_classification():
    assert classify_cause(_cause(title='出货完成度低于目标',
                                 description='该缺口影响了全年节奏')) == 'fact'
    assert classify_cause(_cause(title='客户目标存在空值')) == 'data_gap'
    assert classify_cause(_cause(title='交付风险集中在国内团队')) == 'structure'


def test_status_slots_do_not_require_cause_or_action_for_completeness():
    item = dict(status='limited', evidence=_evidence(records=[dict(id='e1')]),
                result=dict(cardContract=CONTRACT, summary='状态概况', causes=[],
                            recommendations=[], limitations=[]))
    assert card_delivery_state(item, 'quote-summary')['gaps'] == ['ANALYSIS_LIMITED']
    assert 'CAUSES_EMPTY' in card_delivery_state(item, 'opportunity-risk')['gaps']


def test_evidence_count_counts_overlapping_ids_once():
    item = dict(status='limited', evidence=dict(
        facts=[dict(id='e1')], records=[dict(id='e1')], evidence=[dict(id='e1')],
        limitations=[]),
        result=dict(cardContract=CONTRACT, summary='状态', causes=[],
                    recommendations=[], limitations=[]))
    assert card_delivery_state(item, 'quote-summary')['evidenceCount'] == 1


def test_every_registered_insight_slot_has_a_contract():
    from bi_agent.cockpit.targets import slot_registry
    missing = [slot['slotId'] for slot in slot_registry() if slot['slotId'] not in SLOT_SPECS]
    assert not missing


def test_task_draft_marks_suggested_owner_deadline_and_checkable_acceptance(tmp_path):
    store = Store(tmp_path / 'history.sqlite3')
    result = dict(
        cardContract=CONTRACT, summary='存在风险',
        causes=[_cause('c1', '处理未闭环', '处理记录显示未闭环', 'supported')],
        recommendations=[_action('r1', 'c1', '核查处理记录', '运营负责人', 5, '缺口不再扩大')],
        limitations=['待确认'])
    analysis = dict(id='a1', context=dict(stageName='发货'), result=result)
    card = store.draft(analysis)
    measure = card['measures'][0]
    assert measure['action'].startswith('建议：')
    assert '建议角色，待确认' in measure['owner']
    assert measure['deadline'].startswith('建议期限：')
    assert '清单' in measure['acceptance'] or '对账' in measure['acceptance']


def test_summary_notes_and_generation_instructions_are_clean():
    from bi_agent.cockpit.delivery import sanitize_summary, _with_note, _strip_causal, classify_cause
    assert '短摘要' not in sanitize_summary('存在逾期。短摘要不含业务数字，具体数值见事实字段。', {})
    assert _with_note('存在逾期。', '请核查。') == '存在逾期。请核查。'
    assert _strip_causal('尚不能归因为某一环节问题') == '尚不能归因为某一环节问题'
    assert classify_cause({'title': '口径冲突与发货证据缺口'}) == 'data_gap'


def test_publication_trim_preserves_history_and_display_fields():
    from bi_agent.cockpit.delivery import publication_payload
    raw = {'context': {'stage': 'quotation', 'chartQueries': ['large']}, 'evidence': {
        'records': [{'data': {'YWLN_D021': 'normal_completed'}}],
        'facts': [{'value': 0, 'claim': {'id': 'x', 'statement': 'value=0', 'provenance': {'query': 'large'}}}]}}
    value = publication_payload(raw)
    assert 'chartQueries' not in value['context']
    assert 'provenance' not in value['evidence']['facts'][0]['claim']
    assert value['evidence']['records'] == raw['evidence']['records']
    assert raw['context']['chartQueries'] == ['large']


def test_projection_keeps_structured_risk_facts_and_drops_reasons_or_gaps():
    item = dict(
        id='risk-card', updatedAt=time.time(), status='limited',
        context=dict(stage='opportunity', snapshotId='snapshot-risk'),
        evidence=_evidence(records=[dict(id='e1'), dict(id='e2')]),
        result=dict(
            cardContract=CONTRACT,
            summary='商机覆盖存在缺口。',
            causes=[_cause('c-gap', '客户目标为空', '目标字段缺失')],
            recommendations=[],
            limitations=[],
            findings=[
                dict(id='f1', kind='risk_fact', title='商机覆盖低于目标',
                     description='当前证据支持覆盖缺口', metricCodes=['OPP_GAP'],
                     evidenceIds=['e1'], riskDomain='sales'),
                dict(id='f2', kind='risk_fact', title='商机覆盖未达年度目标',
                     description='同一指标的另一表述', metricCodes=['OPP_GAP'],
                     evidenceIds=['e2'], riskDomain='sales'),
            ],
        ),
    )
    projected = project_card(item, 'opportunity-risk')
    findings = projected['result']['findings']
    assert len(findings) == 1
    assert findings[0]['kind'] == 'risk_fact'
    assert findings[0]['scopeKey'] == 'snapshot-risk'
    assert projected['result']['riskFindingCount'] == 1


def test_target_and_actual_facts_create_one_programmatic_metric_risk():
    item = dict(
        id='metric-card', updatedAt=time.time(), status='limited',
        context=dict(stage='shipment', snapshotId='snapshot-shipment'),
        evidence=_evidence(facts=[
            dict(id='target', label='目标出货量', value=60, unit='GWh', definition='年度目标'),
            dict(id='actual', label='实际出货量', value=19.02, unit='GWh', definition='实际完成'),
        ]),
        result=dict(cardContract=CONTRACT, summary='出货量低于目标。', causes=[],
                    recommendations=[], limitations=[]),
    )
    projected = project_card(item, 'shipment-risk-summary')
    findings = projected['result']['findings']
    assert len(findings) == 1
    assert findings[0]['kind'] == 'risk_fact'
    assert findings[0]['riskDomain'] == 'shipment'
    assert set(findings[0]['evidenceIds']) == {'target', 'actual'}


def test_legacy_fact_cause_still_supplies_a_risk_fact_without_reanalysis():
    item = dict(
        id='legacy-card', updatedAt=time.time(), status='limited',
        context=dict(stage='shipment', snapshotId='snapshot-legacy'),
        evidence=_evidence(records=[dict(id='e1')]),
        result=dict(cardContract=CONTRACT, summary='出货量低于目标。',
                    causes=[_cause('c1', '出货量低于年度目标', '实际出货量低于目标')],
                    recommendations=[], limitations=[]),
    )
    projected = project_card(item, 'shipment-risk-summary')
    findings = projected['result']['findings']
    assert len(findings) == 1
    assert findings[0]['kind'] == 'risk_fact'
    assert findings[0]['riskDomain'] == 'shipment'


def test_risk_counts_separate_sales_and_shipment_and_require_complete_sources():
    from bi_agent.cockpit.risk import summarize_risk_counts

    def slot(stage, finding, scope_match=True):
        return dict(stage=stage, status='ready', scopeMatch=scope_match,
                    payload=dict(result=dict(findings=[finding])))

    sales = dict(id='sales-1', kind='risk_fact', title='销售额低于目标',
                 metricCodes=['SALES_GAP'], riskDomain='sales')
    shipment = dict(id='shipment-1', kind='risk_fact', title='出货量低于目标',
                    metricCodes=['SHIPMENT_GAP'], riskDomain='shipment')
    counts = summarize_risk_counts({
        'opportunity-risk': slot('opportunity', sales),
        'opportunity-coverage-note': slot('opportunity', dict(sales)),
        'shipment-risk-summary': slot('shipment', shipment),
    })
    assert counts['sales']['count'] == 1
    assert counts['shipment']['count'] == 1
    assert counts['sales']['known'] is True
    assert counts['shipment']['known'] is True

    counts = summarize_risk_counts({
        'opportunity-risk': slot('opportunity', sales),
        'opportunity-coverage-note': dict(stage='opportunity', status='missing', payload=None),
        'shipment-risk-summary': slot('shipment', shipment),
    })
    assert counts['sales']['known'] is False
    assert counts['sales']['count'] == 1
