import json

import pytest

from bi_agent.llm.context_budget import (
    ContextBudgetExceeded, cockpit_context_limit, estimate_request, estimate_tokens, fit_request)
from bi_agent.llm.runtime_config import request_config, scoped_context_budget


def _query_result(index, rows=24):
    return json.dumps(dict(
        queryId=f'q{index}', source='ap',
        data=dict(rows=[{'客户[YWLN_D001]': f'客户{index}-{row}', '金额[YWLN_M0002]': row * 1.5,
                         '说明': '订单接收环节的明细记录' * 6} for row in range(rows)]),
        scope=dict(request={'filters': ['2025'] * 40}),
        provenance=dict(query='{"metric":"YWLN_M0002","filters":"全部产品部"}' * 30),
        evidenceIds=[f'ev-{index}-{n}' for n in range(5)],
    ), ensure_ascii=False)


def _session_messages(batches=3):
    messages = [dict(role='user', content='请分析订单接收环节的经营异常' * 60)]
    for batch in range(batches):
        messages.append(dict(role='assistant', content=[dict(type='tool_use', id=f't{batch}',
                                                             name='Cockpit-DashboardQuery', input={})]))
        messages.append(dict(role='user', content=[dict(
            type='tool_result', tool_use_id=f't{batch}',
            content=_query_result(batch * 6 + item)) for item in range(6)]))
    return messages


def test_estimate_weights_chinese_above_ascii():
    assert estimate_tokens('商机' * 100) > estimate_tokens('ab' * 100)
    # Calibration point: one customer request was billed at about 0.44
    # tokens per character; a mix that is one third Chinese estimates above.
    sample = ('商机预测覆盖不足' + '{"value": 12.5, "unit": "x"}') * 200
    cjk = sum(1 for ch in sample if '一' <= ch <= '鿿')
    assert 0.2 < cjk / len(sample) < 0.4
    assert estimate_tokens(sample) > len(sample) * 0.44


def test_request_within_budget_is_unchanged_and_output_is_capped():
    messages = [dict(role='user', content='你好')]
    fitted, max_tokens, report = fit_request(messages, '系统', [], limit=11999,
                                             max_tokens=16384, min_output=2500)
    assert fitted is messages and report['compressed'] == 0
    assert max_tokens == 11999 - estimate_request(messages, '系统', [])


def test_tool_results_are_compressed_as_json_and_keep_evidence_ids():
    messages = _session_messages()
    before = json.dumps(messages, ensure_ascii=False)
    fitted, max_tokens, report = fit_request(messages, '系统提示' * 200, [dict(name='x')],
                                             limit=11999, max_tokens=16384, min_output=2500)
    assert json.dumps(messages, ensure_ascii=False) == before  # original untouched
    assert report['compressed'] > 0
    assert estimate_request(fitted, '系统提示' * 200, [dict(name='x')]) + 2500 <= 11999
    assert max_tokens >= 2500
    for message in fitted:
        for block in message['content'] if isinstance(message['content'], list) else []:
            if block.get('type') == 'tool_result':
                value = json.loads(block['content'])
                assert len(value['evidenceIds']) == 5
                assert value['data']['rows']


def test_request_that_cannot_fit_is_refused_before_sending():
    with pytest.raises(ContextBudgetExceeded) as caught:
        fit_request([dict(role='user', content='问题')], '系统' * 20000, [],
                    limit=11999, max_tokens=4000, min_output=2500)
    assert caught.value.limit == 11999 and '未发送请求' in str(caught.value)


def test_dispatcher_lowers_max_tokens_and_reports_budget_errors(monkeypatch):
    import bi_agent.llm.provider as provider
    seen = []

    def fake_unbounded(messages, system_prompt, allowed_tools, model_key, max_tokens, *rest):
        seen.append(max_tokens)
        yield dict(type='message_end', stop_reason='end_turn', usage={})

    monkeypatch.setattr(provider, '_stream_message_unbounded', fake_unbounded)
    with request_config(context_limit=11999, min_output_tokens=2500):
        list(provider.stream_message([dict(role='user', content='你好')], '系统', [], 'k', 16384, 0))
        events = list(provider.stream_message([dict(role='user', content='问')], '系统' * 20000,
                                              [], 'k', 16384, 0))
    assert seen and seen[0] < 11999
    assert len(seen) == 1
    assert events[0]['type'] == 'error' and events[0]['error_code'] == 'CONTEXT_BUDGET_EXCEEDED'
    # Without a scoped budget nothing changes.
    list(provider.stream_message([dict(role='user', content='你好')], '系统', [], 'k', 16384, 0))
    assert seen[-1] == 16384


def test_scoped_budget_validation_and_cockpit_default(monkeypatch):
    with pytest.raises(ValueError):
        with request_config(context_limit=0):
            pass
    with request_config(context_limit=11999):
        assert scoped_context_budget() == (11999, 1999)
    assert scoped_context_budget() is None
    # Off by default; a deployment opts in with the gateway's cap.
    monkeypatch.delenv('COCKPIT_MODEL_CONTEXT_TOKENS', raising=False)
    assert cockpit_context_limit() is None
    monkeypatch.setenv('COCKPIT_MODEL_CONTEXT_TOKENS', '11999')
    assert cockpit_context_limit() == 11999
    monkeypatch.setenv('COCKPIT_MODEL_CONTEXT_TOKENS', '0')
    assert cockpit_context_limit() is None


def test_cockpit_model_calls_run_under_the_budget(monkeypatch):
    import bi_agent.llm.provider as provider
    from bi_agent.cockpit import opportunity_judgement, opportunity_v2, section_summary
    budgets = []

    def fake_stream(*args, **kwargs):
        budgets.append(scoped_context_budget())
        return iter([dict(type='text_delta', text='{"established": false, "reason": "x", '
                                                  '"riskSummary": "", "causeSummary": "", "adviceSummary": ""}'),
                     dict(type='message_end', stop_reason='end_turn', usage={})])

    monkeypatch.setattr(provider, 'stream_message', fake_stream)
    monkeypatch.delenv('COCKPIT_MODEL_CONTEXT_TOKENS', raising=False)
    monkeypatch.setattr(opportunity_v2, '_model_candidate_keys', lambda: ['route-a'])
    opportunity_judgement.default_item_judge(dict(kind='risk', code='RK01'))
    assert budgets == [None]  # no budget unless configured
    budgets.clear()
    monkeypatch.setenv('COCKPIT_MODEL_CONTEXT_TOKENS', '11999')
    monkeypatch.setattr(opportunity_v2, '_model_candidate_keys', lambda: ['route-a'])
    opportunity_judgement.default_item_judge(dict(kind='risk', code='RK01'))
    section_summary._call_model(dict(risks=[]), timeout=30, max_tokens=1500)
    assert budgets == [(11999, 400), (11999, 600)]


def test_main_chain_card_task_fits_after_compression():
    """Rough shape of the order/shipment card request with 18 prepared queries."""
    from bi_agent.cockpit.cards import SCHEMA
    system = '你是储能经营驾驶舱的只读数据分析助手。' + '本次为主服务固定卡片任务' * 60
    messages = _session_messages(batches=3)
    estimated = estimate_request(messages, system, [SCHEMA])
    assert estimated > 11999  # the raw request would not fit
    fitted, max_tokens, report = fit_request(messages, system, [SCHEMA], limit=11999,
                                             max_tokens=16384, min_output=2500)
    assert estimate_request(fitted, system, [SCHEMA]) + max_tokens <= 11999
    assert max_tokens >= 2500 and report['compressed'] > 0
