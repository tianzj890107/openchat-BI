from copy import deepcopy
import pytest
from bi_agent.cockpit.business_presentation import present_business_result,validate_dimensions
from bi_agent.cockpit.delivery import project_card,validate_reasoning
from bi_agent.cockpit.risk import build_risk_findings


def findings():
    return [dict(id='r1',kind='risk_fact',title='订单接收平均周期高于标杆',description='实际38天，标杆18天。',metricCodes=['ORDER_CYCLE'],evidenceIds=['e1'],riskDomain='sales'),
            dict(id='r2',kind='risk_fact',title='发货量连续三个月回落',description='7至9月分别30、20、10 GWh。',metricCodes=['VOLUME'],evidenceIds=['e2'],riskDomain='shipment'),
            dict(id='r3',kind='risk_fact',title='报价逾期未完成',description='逾期未完成电量3 GWh。',metricCodes=['QUOTE'],evidenceIds=['e3'],riskDomain='sales')]


def dimension(id, refs, evidence, title='流程时效'):
    return dict(id=id,stage='order' if refs==['r1'] else 'shipment',title=title,description='订单周期38天，对照标杆18天，延长20天。',findingIds=refs,evidenceIds=evidence)


def test_multiple_independent_risks_cannot_collapse_to_one_generic_dimension():
    value=dict(findings=findings(),analysisDimensions=[dimension('d1',['r1','r2','r3'],['e1','e2','e3'])])
    with pytest.raises(ValueError,match='多个|多组'):validate_dimensions(value,{'e1','e2','e3'})
    value['analysisDimensions']=[dimension('d1',['r1'],['e1']),dimension('d2',['r2','r3'],['e2','e3'],'时间趋势与报价状态')]
    validate_dimensions(value,{'e1','e2','e3'})
    value['analysisDimensions'][1]['evidenceIds']=['e2']
    with pytest.raises(ValueError,match='对应风险'):validate_dimensions(value,{'e1','e2','e3'})


def test_empty_metrics_are_limits_not_business_risks_or_summary():
    technical=dict(id='empty',kind='risk_fact',title='指标大面积返回空值，无法评估',description='目标未返回',metricCodes=['TARGET'],evidenceIds=['e1'])
    raw=dict(summary='订单接收周期38天，高于标杆18天；目标出货量为空，无法评估。跨环节结论必须同口径。',
             findings=findings()+[technical],causes=[{'title':'[待验证假设] 可能由排程变化'}],recommendations=[],limitations=[])
    before=deepcopy(raw);shown=present_business_result(raw)
    assert '38天' in shown['businessSummary'] and '空' not in shown['businessSummary'] and '同口径' not in shown['businessSummary']
    assert len(shown['findings'])==3 and len(shown['analysisDimensions'])==3
    assert any('目标出货量为空' in x for x in shown['limitations'])
    assert raw==before and shown['causes']==raw['causes']
    assert not build_risk_findings(dict(findings=[technical]),dict(evidence=[dict(id='e1')]),{},dict(stage='shipment'))


def test_data_only_result_has_no_business_summary_and_zero_is_not_missing():
    assert present_business_result(dict(summary='指标大面积返回空值，无法评估',findings=[]))['businessSummary']==''
    assert present_business_result(dict(summary='销售额为0亿元，目标10亿元',findings=[]))['businessSummary']=='销售额为0亿元，目标10亿元'


def test_technical_followups_are_not_business_recommendations():
    shown=present_business_result(dict(summary='订单逾期',findings=findings(),recommendations=[dict(id='data',action='补齐字段并确认口径'),dict(id='business',action='逐单核查逾期订单的交期与交付安排')]))
    assert [a['id'] for a in shown['recommendations']]==['business']
    assert any('补齐字段' in text for text in shown['limitations'])


def test_new_dimensions_survive_projection_and_hypotheses_are_not_renamed():
    fs=findings();dims=[dimension('d1',['r1'],['e1']),dimension('d2',['r2','r3'],['e2','e3'],'时间趋势与报价状态')]
    item=dict(id='a',status='limited',context={'stage':'combined'},result=dict(summary='周期38天，标杆18天',cardContract='cockpit-cards-v1',findings=fs,analysisDimensions=dims,causes=[],recommendations=[],limitations=[]),evidence=dict(facts=[],records=[],evidence=[dict(id=x) for x in ('e1','e2','e3')]))
    out=project_card(item,'sales-shipment-issues')
    assert out['result']['analysisDimensions']==dims
    assert out['result']['causes']==[]
    assert '跨环节结论' not in out['result']['businessSummary']


def test_thousands_separators_are_never_changed_to_clause_punctuation():
    shown=present_business_result(dict(summary='销售额1,000亿元，目标字段为空',findings=[]))
    assert shown['businessSummary']=='销售额1,000亿元'


def test_light_transport_preserves_delivered_dimensions_instead_of_rebuilding_them():
    from bi_agent.cockpit.page_cache import compact_analysis
    from bi_agent.cockpit.delivery import publication_payload
    dimensions=[dimension('source-a',['r1'],['e1']),dimension('source-b',['r2','r3'],['e2','e3'],'时间与报价结构')]
    item=dict(id='test',status='limited',context={'stage':'combined'},result=dict(summary='订单周期38天，标杆18天',cardContract='cockpit-cards-v1',analysisDimensions=dimensions,findings=findings(),causes=[],recommendations=[],limitations=[]),evidence=dict(facts=[],records=[],evidence=[dict(id=x) for x in ('e1','e2','e3')]))
    wire=publication_payload(project_card(compact_analysis(item),'sales-shipment-issues'))
    assert wire['result']['analysisDimensions']==dimensions
    assert item['result']['analysisDimensions']==dimensions


def test_legacy_hypothesis_is_not_rebranded_as_business_dimension_or_fact():
    shown=present_business_result(dict(summary='可能因为产能不足导致交付延迟。',findings=[],causes=[dict(id='c1',title='[待验证假设] 产能不足')]))
    assert shown['businessSummary']=='' and shown['analysisDimensions']==[]
    assert shown['causes'][0]['title']=='[待验证假设] 产能不足'
    assert any('可能因为' in text for text in shown['limitations'])


def _undone_value(summary):
    return dict(summary=summary, findings=[], causes=[], limitations=[],
                recommendations=[dict(id='a1', actionType='investigation', causeIds=[], evidenceIds=['f1'],
                                      action='逐单核对商机逾期与完成状态', ownerRole='业务分析员',
                                      deadlineDays=3, acceptance='形成逐单状态核对清单')])


def _undone_evidence(**extra):
    value = dict(facts=[], records=[], evidence=[], limitations=[])
    value.update(extra)
    return value


def test_overdue_alone_cannot_become_overdue_and_unfinished():
    from bi_agent.cockpit.delivery import validate_reasoning
    value = _undone_value('商机逾期且未完成，需重点跟进。')
    with pytest.raises(ValueError, match='逾期未完成'):
        validate_reasoning(value, _undone_evidence(facts=[dict(id='f1', label='商机平均逾期天数', value=30)]),
                           stage='opportunity')
    validate_reasoning(value, _undone_evidence(facts=[dict(id='f1', label='商机逾期未完成数量', value=3)]),
                       stage='opportunity')
    validate_reasoning(value, _undone_evidence(records=[dict(id='f1', status='逾期未完成')]),
                       stage='opportunity')


def test_enum_description_is_not_evidence_for_unfinished_status():
    from bi_agent.cockpit.delivery import validate_reasoning
    value = _undone_value('商机逾期且未完成。')
    described = _undone_evidence(limitations=['状态区分正常完成、逾期完成、逾期未完成、临期未完成'],
                                 facts=[dict(id='f1', label='商机逾期天数', value=30)])
    with pytest.raises(ValueError, match='逾期未完成'):
        validate_reasoning(value, described, stage='opportunity')


def test_opportunity_signing_status_is_contract_state_not_order():
    from bi_agent.cockpit.business_presentation import business_finding
    finding=dict(id='r1',kind='risk_fact',title='抽样商机未签单7条',
                 description='商机明细状态为未签单7条、已签单2条。',metricCodes=['YWLN_M0023'],evidenceIds=['e1'])
    assert business_finding(finding)
    shown=present_business_result(dict(summary='商机明细未签单7条，已签单2条。',findings=[finding],limitations=[]))
    assert '合同签订未确认' in shown['findings'][0]['title']
    assert '合同已签订' in shown['findings'][0]['description']
    assert '合同签订未确认' in shown['businessSummary']


def test_order_unsigned_without_contract_semantics_remains_a_data_limit():
    from bi_agent.cockpit.business_presentation import business_finding
    finding=dict(id='r1',kind='risk_fact',title='订单未签单7笔',
                 description='订单未签单7笔。',metricCodes=['ORDER_COUNT'],evidenceIds=['e1'])
    assert not business_finding(finding)
    shown=present_business_result(dict(summary='订单未签单7笔。',findings=[finding],limitations=[]))
    assert shown['findings']==[]
    assert any('订单未签单' in text for text in shown['limitations'])


def test_recommendation_finding_ids_are_pruned_to_visible_risks():
    action=dict(id='a1',action='逐单核查客户与产品团队',acceptance='形成逐单清单',findingIds=['r1','r3'])
    shown=present_business_result(dict(summary='订单周期高于标杆。',findings=findings()[:1],
                                       recommendations=[action],limitations=[]))
    assert shown['recommendations'][0]['findingIds']==['r1']
