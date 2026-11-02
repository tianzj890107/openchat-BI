from bi_agent.cockpit.risk import build_risk_findings, summarize_risk_counts


def finding(title, codes, domain='sales', evidence=('e1',)):
    return dict(kind='risk_fact', id=title, title=title, metricCodes=codes,
                evidenceIds=list(evidence), riskDomain=domain)


def slot(stage, findings):
    return dict(stage=stage, status='ready', scopeMatch=True,
                payload=dict(id='analysis-'+stage, result=dict(findings=findings)))


def test_same_business_risk_across_labels_codes_and_combined_card_counts_once():
    a = finding('全年实际出货量显著低于目标出货量', ['YWLN_M0006','YWLN_M0007'], 'shipment')
    b = finding('出货量低于目标', ['label:出货量'], 'shipment')
    c = finding('实际出货量显著低于同口径目标出货量', ['YWLN_M0006','YWLN_M0007'], 'shipment')
    slots = {'node':slot('shipment',[a,b]), 'combined':slot('combined',[c])}
    counts = summarize_risk_counts(slots)['shipment']
    assert counts['count'] == len(counts['findings']) == 1
    assert counts['findings'][0]['riskKey'] == 'shipment:shipment-target-gap'
    assert len(counts['findings'][0]['sources']) == 3


def test_combined_and_node_opportunity_gap_merge_despite_different_metric_sets():
    a = finding('商机预测金额覆盖目标不足且缺口集中', ['YWLN_M0002','YWLN_M0140'])
    b = finding('商机预测金额覆盖不足目标', ['YWLN_M0002','YWLN_M0023','YWLN_M0140'])
    c = finding('未签单商机金额为零', ['YWLN_M0023'])
    result = summarize_risk_counts({'node':slot('opportunity',[a,c]),'combined':slot('combined',[b])})
    assert result['sales']['count'] == 2


def test_shipment_risk_in_opportunity_card_is_not_lost():
    f = finding('客户等级口径实际发货电量低于目标电量',
                ['YWLN_M_CUSTOMER_TARGET_ENERGY','YWLN_M_CUSTOMER_ACTUAL_ENERGY'], 'shipment')
    result = summarize_risk_counts({'opportunity':slot('opportunity',[f])})
    assert result['shipment']['count'] == 1
    assert result['sales']['count'] == 0


def test_distinct_risks_with_same_measure_do_not_collapse():
    a = finding('商机金额异常减少', ['CUSTOM_AMOUNT'])
    b = finding('商机金额异常集中', ['CUSTOM_AMOUNT'])
    evidence = dict(evidence=[dict(id='e1')])
    findings = build_risk_findings(dict(findings=[a,b]), evidence, {}, {'stage':'opportunity'})
    assert len(findings) == 2
    result = summarize_risk_counts({'node':slot('opportunity',findings)})
    assert result['sales']['count'] == 2


def test_node_projection_also_merges_automatic_label_target_gap():
    a = finding('全年实际出货量显著低于目标出货量', ['YWLN_M0006','YWLN_M0007'], 'shipment')
    evidence = dict(evidence=[dict(id='e1')], facts=[
        dict(id='t',label='目标出货量',value=100),dict(id='a',label='实际出货量',value=40)])
    result = build_risk_findings(dict(findings=[a]),evidence,{},dict(stage='shipment'))
    assert len(result) == 1


def test_order_change_wording_in_summary_and_node_is_one_issue():
    a = finding('订单接收存在订单取消与订单变更金额', ['YWLN_M0033'])
    b = finding('订单接收金额中存在取消与变更金额', ['YWLN_M0033'])
    result = summarize_risk_counts({'node':slot('order',[a]),'combined':slot('combined',[b])})
    assert result['sales']['count'] == 1


def test_delivery_accepts_distinct_issues_on_one_measure():
    from bi_agent.cockpit.agent import validate_result
    from bi_agent.cockpit.cards import Cards
    a = finding('商机金额异常减少', ['CUSTOM_AMOUNT'])
    b = finding('商机金额异常集中', ['CUSTOM_AMOUNT'])
    value = dict(summary='风险事实',causes=[],recommendations=[],limitations=['测试限制'],findings=[a,b])
    evidence = dict(facts=[],records=[],evidence=[dict(id='e1')],limitations=[])
    assert len(validate_result(value,evidence,{'e1'},result_model=Cards)['findings']) == 2
