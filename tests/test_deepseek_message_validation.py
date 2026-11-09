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
