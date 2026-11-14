from bi_agent.cockpit.page_cache import compact_analysis
from bi_agent.cockpit.section_summary import (
    displayed_items, summarize_sections, validate_summaries, with_section_summaries)


def _result():
    return dict(
        findings=[dict(id=f'r{i}', title=f'风险{i}', description=f'涉及预测金额 {i}0 亿元') for i in range(1, 7)],
        analysisDimensions=[dict(id='c1', title='需求确认未落实', description='4 条战略客户商机需求未确认')],
        recommendations=[dict(id='a1', action='逐户补齐需求确认', ownerRole='销售负责人',
                              deadlineDays=10, acceptance='形成逐项核查清单')],
    )


def test_only_displayed_items_are_sent_for_summary():
    items = displayed_items(_result())
    # The card shows every established risk, so every one is summarised.
    assert [item['title'] for item in items['risks']] == [f'风险{i}' for i in range(1, 7)]
    assert items['causes'] == [dict(title='需求确认未落实', description='4 条战略客户商机需求未确认')]
    assert items['advice'] == [dict(action='逐户补齐需求确认', ownerRole='销售负责人',
                                    deadline='10 个工作日', acceptance='形成逐项核查清单')]


def test_each_section_is_summarised_from_its_own_items():
    seen = []

    def call(payload):
        seen.append(payload)
        return dict(riskSummary='四项风险涉及预测金额 10 至 40 亿元，需优先处理。',
                    causeSummary='4 条战略客户商机需求尚未确认。',
                    adviceSummary='由销售负责人在 10 个工作日内逐户补齐需求确认。')
    value = summarize_sections(_result(), stage_name='商机获取', call_model=call)
    assert value['status'] == 'completed' and value['modelCalls'] == 1 and value['issues'] == []
    assert value['riskSummary'].startswith('四项风险')
    assert value['basis'] == dict(risks=6, causes=1, advice=1)
    assert set(seen[0]) == {'stage', 'risks', 'causes', 'advice'}
    assert len(seen[0]['risks']) == 6


def test_numbers_from_another_section_are_rejected_and_repaired_once():
    answers = [
        # 90 and 7 appear in no displayed risk.
        dict(riskSummary='风险涉及 90 亿元和 7 条商机。', causeSummary='4 条商机需求未确认。',
             adviceSummary='10 个工作日内补齐。'),
        dict(riskSummary='风险涉及预测金额 10 亿元。', causeSummary='4 条商机需求未确认。',
             adviceSummary='10 个工作日内补齐。'),
    ]
    seen = []

    def call(payload):
        seen.append(payload)
        return answers[len(seen) - 1]
    value = summarize_sections(_result(), call_model=call)
    assert value['status'] == 'completed' and value['modelCalls'] == 2
    assert value['riskSummary'] == '风险涉及预测金额 10 亿元。'
    feedback = seen[1]['validationFeedback']
    assert feedback['issues'] == ['风险总结（riskSummary）：含本组条目中不存在的数字 7、90']
    assert feedback['previousAnswer']['riskSummary'].startswith('风险涉及 90')


def test_unusable_summaries_are_dropped_without_failing_the_card():
    summaries, issues = validate_summaries(
        dict(riskSummary='', causeSummary='原' * 200, adviceSummary='按期完成。'),
        displayed_items(_result()))
    assert summaries == dict(riskSummary='', causeSummary='', adviceSummary='按期完成。')
    assert issues == ['风险总结（riskSummary）：缺少总结', '原因总结（causeSummary）：超过 160 字（实际 200 字）']

    def broken(_payload):
        raise RuntimeError('model down password=hunter2')
    value = summarize_sections(_result(), call_model=broken)
    assert value['status'] == 'failed' and value['riskSummary'] == ''
    assert value['issues'][0].startswith('总结调用失败：RuntimeError') and 'hunter2' not in value['issues'][0]
    assert summarize_sections(dict(findings=[], analysisDimensions=[], recommendations=[])) is None


def test_card_item_gets_section_summaries_and_keeps_them_for_the_page(monkeypatch):
    item = dict(id='a', status='completed', context={}, result=dict(_result(), summary='整体摘要',
                                                                    cardContract='cockpit-cards-v1'))
    phases = []
    done = with_section_summaries(
        item, stage_name='订单接收', progress=lambda phase, **detail: phases.append(phase),
        summarizer=lambda result, stage_name='': dict(riskSummary='风险总结', causeSummary='',
                                                       adviceSummary='建议总结', status='partial'))
    assert phases == ['summarising']
    assert 'sectionSummaries' not in item['result']
    assert done['result']['sectionSummaries']['riskSummary'] == '风险总结'
    assert compact_analysis(done)['result']['sectionSummaries']['adviceSummary'] == '建议总结'

    def failing(result, stage_name=''):
        raise RuntimeError('boom')
    assert with_section_summaries(item, summarizer=failing) is item
    monkeypatch.setenv('COCKPIT_SECTION_SUMMARY_ENABLED', '0')
    assert with_section_summaries(item, summarizer=lambda *a, **k: dict(riskSummary='x')) is item


def test_summary_system_prompt_takes_a_card_role_first():
    from bi_agent.cockpit import section_summary
    role = '你是储能业务销售运营分析师，请用客观、简洁的经营汇报用语。'
    seen = []

    def fake_call(payload, *, timeout, max_tokens, system=section_summary.SYSTEM_PROMPT):
        seen.append(system)
        return dict(riskSummary='风险1 涉及预测金额 10 亿元', causeSummary='', adviceSummary=''), 'route'
    original = section_summary._call_model
    section_summary._call_model = fake_call
    try:
        summarize_sections(_result(), stage_name='商机获取', role=role)
        summarize_sections(_result(), stage_name='订单接收')
    finally:
        section_summary._call_model = original
    assert seen[0].startswith(role) and '本次任务：' in seen[0] and seen[0].count('你是') == 1
    # Cards without their own role keep the default summary prompt.
    assert seen[-1] == section_summary.SYSTEM_PROMPT
    done = with_section_summaries(dict(result=_result()), role=role,
                                  summarizer=lambda result, stage_name='', role='': dict(riskSummary=role))
    assert done['result']['sectionSummaries']['riskSummary'] == role
