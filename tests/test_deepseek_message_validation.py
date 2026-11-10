from copy import deepcopy

import pytest

from bi_agent.llm.provider_deepseek import _convert_messages
from bi_agent.llm import registry, provider_team


@pytest.mark.parametrize('include_reasoning',[True,False])
def test_interrupted_assistant_turns_are_not_sent_as_empty_messages(include_reasoning):
    messages=[{'role':'user','content':'analyse'},
        {'role':'assistant','content':[{'type':'thinking','thinking':'private reasoning'}]},
        {'role':'assistant','content':[]},
        {'role':'assistant','content':'  '},
        {'role':'assistant','content':[{'type':'text','text':''}]},
        {'role':'user','content':'continue'}]
    before=deepcopy(messages)
    result=_convert_messages(messages,'system',include_reasoning=include_reasoning)
    assert [m['role'] for m in result]==['system','user','user']
    assert messages==before


@pytest.mark.parametrize('convert',[_convert_messages,provider_team._convert_messages])
def test_tool_only_assistant_and_results_keep_pairing_and_reasoning(convert):
    messages=[{'role':'assistant','content':[{'type':'thinking','thinking':'trace'},
        {'type':'tool_use','id':'call-1','name':'query','input':{'year':2026}}]},
        {'role':'user','content':[{'type':'tool_result','tool_use_id':'call-1','content':'42'}]},
        {'role':'assistant','content':[{'type':'text','text':'answer'}]}]
    result=convert(messages,'system',include_reasoning=True)
    assert result[1]['tool_calls'][0]['id']=='call-1'
    assert result[1]['reasoning_content']=='trace'
    assert result[2]['tool_call_id']=='call-1' and result[2]['content']=='42'
    assert result[3]['content']=='answer'
    hidden=convert(messages,'system',include_reasoning=False)
    assert 'reasoning_content' not in hidden[1] and hidden[1]['tool_calls']


def test_deepseek_team_fallbacks_stay_in_deepseek_family(monkeypatch):
    monkeypatch.setattr(registry,'MODELS',[
        {'key':'primary','provider':'team','model_id':'direct-deepseek-v4-flash'},
        {'key':'mimo','provider':'team','model_id':'mimo-v2.5'},
        {'key':'glm','provider':'team','model_id':'glm-5.2'},
        {'key':'backup','provider':'team','model_id':'deepseek-v4-flash-0731'},
        {'key':'direct','provider':'deepseek','model_id':'deepseek-v4-flash'}])
    assert registry.fallback_model_keys('primary')==['backup']


def test_interrupted_multi_tool_turn_gets_explicit_missing_result_without_losing_real_result():
    messages=[{'role':'assistant','content':[
        {'type':'tool_use','id':'a','name':'query','input':{}},
        {'type':'tool_use','id':'b','name':'query','input':{}}]},
        {'role':'user','content':[{'type':'tool_result','tool_use_id':'b','content':'real result'}]},
        {'role':'assistant','content':'continue'}]
    before=deepcopy(messages)
    result=_convert_messages(messages,'system')
    assert [m.get('tool_call_id') for m in result[2:4]]==['a','b']
    assert 'tool_result_missing' in result[2]['content']
    assert result[3]['content']=='real result' and result[4]['content']=='continue'
    assert messages==before


def test_unpaired_and_duplicate_tool_outputs_never_break_request_sequence():
    messages=[{'role':'user','content':[{'type':'tool_result','tool_use_id':'orphan','content':'history'}]},
        {'role':'assistant','content':[{'type':'tool_use','id':'a','name':'query','input':{}}]},
        {'role':'user','content':[{'type':'tool_result','tool_use_id':'a','content':'first'},
                                 {'type':'tool_result','tool_use_id':'a','content':'duplicate'}]}]
    out=_convert_messages(messages,'system')
    assert out[1]['role']=='user' and 'Historical unpaired' in out[1]['content']
    assert [m for m in out if m['role']=='tool']==[{'role':'tool','tool_call_id':'a','content':'first'}]


@pytest.mark.parametrize('env_mode,visible_thinking,expected_mode',[
    ('true',False,'enabled'),
    ('false',True,'disabled'),
    (None,True,'enabled'),
    (None,False,'disabled'),
])
def test_team_tool_reasoning_survives_display_and_requested_mode_changes(monkeypatch, env_mode, visible_thinking, expected_mode):
    from types import SimpleNamespace
    captured=[]
    def create(**kwargs):
        captured.append(kwargs)
        return iter(())
    monkeypatch.setattr(provider_team, 'OpenAI',lambda **_:SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(provider_team, '_get_api_key',lambda:'test-key')
    monkeypatch.setattr(provider_team, '_convert_tools', lambda _: [{'type':'function','function':{'name':'query','parameters':{'type':'object'}}}])
    monkeypatch.delenv('TEAM_ENABLE_THINKING',raising=False)
    if env_mode is None:monkeypatch.delenv('TEAM_DEEPSEEK_ENABLE_THINKING',raising=False)
    else:monkeypatch.setenv('TEAM_DEEPSEEK_ENABLE_THINKING',env_mode)
    messages=[{'role':'user','content':'analyse'},
        {'role':'assistant','content':[{'type':'thinking','thinking':'actual provider trace'},
            {'type':'tool_use','id':'read','name':'query','input':{}}]},
        {'role':'user','content':[{'type':'tool_result','tool_use_id':'read','content':'42'}]}]
    original=deepcopy(messages)
    events=list(provider_team.stream(model_id='direct-deepseek-v4-flash',messages=messages,
        system_prompt='system',allowed_tools=['query'],max_tokens=512,temperature=.2,thinking=visible_thinking))
    assert not any(e['type']=='error' for e in events)
    request=captured[0]
    assert request['extra_body']=={'thinking':{'type':expected_mode}}
    assistant=next(m for m in request['messages'] if m['role']=='assistant')
    assert assistant.get('reasoning_content')=='actual provider trace'
    assert request['messages'][-1]['tool_call_id']=='read'
    assert messages==original


def test_direct_deepseek_keeps_actual_tool_reasoning_even_when_hidden(monkeypatch):
    from types import SimpleNamespace
    from bi_agent.llm import provider_deepseek
    calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        return iter(())
    monkeypatch.setattr(provider_deepseek,'OpenAI',lambda **_:SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(provider_deepseek,'_get_api_key',lambda:'test-key')
    monkeypatch.setattr(provider_deepseek,'_convert_tools',lambda _:[{'type':'function','function':{'name':'query','parameters':{'type':'object'}}}])
    messages=[{'role':'assistant','content':[{'type':'thinking','thinking':'actual provider trace'},
        {'type':'tool_use','id':'real-call','name':'query','input':{}}]},
        {'role':'user','content':[{'type':'tool_result','tool_use_id':'real-call','content':'42'}]}]
    result=list(provider_deepseek.stream(model_id='deepseek-v4-flash',messages=messages,
        system_prompt='system',allowed_tools=['query'],max_tokens=512,temperature=.2,thinking=False))
    assert not any(e['type']=='error' for e in result)
    assert calls[0]['extra_body']=={'thinking':{'type':'disabled'}}
    assert calls[0]['messages'][1]['reasoning_content']=='actual provider trace'
