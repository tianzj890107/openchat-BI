from copy import deepcopy
from types import SimpleNamespace
import pytest
from bi_agent.llm.deepseek_compat import preserve_tool_observations,create_stream


def history(reasoning=None):
    turn=dict(role='assistant',content=None,tool_calls=[dict(id='a',type='function',function={'name':'query','arguments':'{}'})])
    if reasoning:turn['reasoning_content']=reasoning
    return [turn,dict(role='tool',tool_call_id='a',content='real evidence 42')]


def test_missing_reasoning_replays_real_outputs_as_observations_without_mutating_history():
    messages=history();before=deepcopy(messages)
    out=preserve_tool_observations(messages)
    assert len(out)==1 and out[0]['role']=='user'
    assert 'real evidence 42' in out[0]['content'] and 'toolCalls' in out[0]['content']
    assert messages==before
    assert preserve_tool_observations(history('real private reasoning'))==history('real private reasoning')


def test_reasoning_rejection_retries_once_before_stream_and_preserves_outputs():
    calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        if len(calls)==1:
            exc=RuntimeError('reasoning_content not passed back');exc.status_code=400;raise exc
        return iter([{'ok':True}])
    kwargs=dict(messages=history('actual trace'),extra_body={'thinking':{'type':'enabled'}})
    before=deepcopy(kwargs);client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    assert list(create_stream(client,kwargs,deepseek=True))==[{'ok':True}]
    assert len(calls)==2 and kwargs==before
    assert all(m['role']!='tool' for m in calls[1]['messages'])
    assert 'real evidence 42' in calls[1]['messages'][0]['content']
    assert calls[1]['extra_body']['thinking']['type']=='disabled'


def test_midstream_failure_never_replays_an_already_started_response():
    calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        def events():
            yield 'partial'
            raise RuntimeError('reasoning_content not passed back')
        return events()
    client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    stream=create_stream(client,dict(messages=history()),deepseek=True)
    assert next(stream)=='partial'
    with pytest.raises(RuntimeError):next(stream)
    assert len(calls)==1


def test_reasoning_is_committed_before_tool_response_event_can_interrupt_consumption():
    from bi_agent.runtime.session import AgentSession
    saved=[]
    session=SimpleNamespace(_turn_superseded=lambda *_:False,
        _commit_messages=lambda content,*_:saved.append(content) or True)
    thinking=[dict(type='thinking',thinking='real trace')]
    tools=[dict(type='tool_use',id='a',name='query',input={})]
    stream=AgentSession._emit_assistant_iteration(session,1,'tool_use','',tools,thinking,{})
    assert next(stream)['type']=='llm_response'
    assert saved[0]==thinking+tools
    stream.close()


def test_0731_trace_precedes_tool_end_and_survives_final_request_without_tools(monkeypatch):
    from bi_agent.llm import provider_team
    captured=[]
    delta=SimpleNamespace(reasoning_content='actual trace',content=None,
        tool_calls=[SimpleNamespace(index=0,id='a',function=SimpleNamespace(name='query',arguments='{}'))])
    def create(**kwargs):
        captured.append(kwargs)
        return iter([SimpleNamespace(usage=None,choices=[SimpleNamespace(delta=delta,finish_reason='tool_calls')])])
    monkeypatch.setattr(provider_team,'OpenAI',lambda **_:SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(provider_team,'_get_api_key',lambda:'test')
    monkeypatch.setattr(provider_team,'_convert_tools',lambda allowed:[] if not allowed else [{'type':'function','function':{'name':'query'}}])
    events=list(provider_team.stream(model_id='DeepSeek-V4-Flash-0731',messages=[dict(role='user',content='probe')],system_prompt='system',allowed_tools=['query'],max_tokens=100,temperature=0,thinking=False))
    assert next(i for i,e in enumerate(events) if e['type']=='thinking_block')<next(i for i,e in enumerate(events) if e['type']=='tool_use_end')
    msgs=[dict(role='assistant',content=[dict(type='thinking',thinking='actual trace'),dict(type='tool_use',id='a',name='query',input={})]),dict(role='user',content=[dict(type='tool_result',tool_use_id='a',content='42')])]
    list(provider_team.stream(model_id='DeepSeek-V4-Flash-0731',messages=msgs,system_prompt='system',allowed_tools=[],max_tokens=100,temperature=0,thinking=False))
    assert captured[-1]['messages'][1]['reasoning_content']=='actual trace'
    assert captured[-1]['messages'][2]['content']=='42'


def test_old_route_can_reject_optional_parameters_after_protocol_repair():
    calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        if len(calls)==1:raise RuntimeError('400 reasoning content not passed back')
        if len(calls)==2:raise RuntimeError('400 unsupported parameter thinking')
        return iter(['ok'])
    client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    kwargs=dict(messages=history('real trace'),extra_body={'thinking':{'type':'enabled'}},reasoning_effort='low')
    before=deepcopy(kwargs)
    assert list(create_stream(client,kwargs,deepseek=True))==['ok']
    assert len(calls)==3 and kwargs==before
    assert 'extra_body' not in calls[-1] and 'reasoning_effort' not in calls[-1]
    assert 'real evidence 42' in calls[-1]['messages'][0]['content']
