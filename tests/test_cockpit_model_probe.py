from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from bi_agent.cockpit import model_probe
from bi_agent.cockpit.router import build_cockpit_router


def test_probe_exercises_tool_history_without_business_data_or_session(monkeypatch):
    from bi_agent.llm import provider_team
    calls=[]
    monkeypatch.setattr(model_probe,'get_config',lambda:SimpleNamespace(model_key='team-configured'))
    monkeypatch.setattr(model_probe,'get_model',lambda _:dict(provider='team',model_id='DeepSeek-V4-Flash-0731'))
    def stream(**kwargs):
        calls.append(kwargs)
        if kwargs['allowed_tools']:
            yield dict(type='thinking_block',text='real private trace')
            yield dict(type='tool_use_end',id='probe-1',name=model_probe.TOOL,input={})
        else:
            assert kwargs['messages'][1]['content'][0]['thinking']=='real private trace'
            assert 'pong' in kwargs['messages'][2]['content'][0]['content']
            yield dict(type='text_delta',text='OK')
        yield dict(type='message_end',stop_reason='end_turn',usage={})
    monkeypatch.setattr(provider_team,'stream',stream)
    result=model_probe.probe()
    assert result['ok'] and result['toolRoundtrip'] and result['modelCalls']==2
    assert 'real private trace' not in str(result)
    assert len(calls)==2 and calls[1]['allowed_tools']==[]


def test_probe_redacts_upstream_error_and_never_exposes_credentials(monkeypatch):
    from bi_agent.llm import provider_team
    monkeypatch.setattr(model_probe,'get_config',lambda:SimpleNamespace(model_key='team-configured'))
    monkeypatch.setattr(model_probe,'get_model',lambda _:dict(provider='team',model_id='DeepSeek-V4-Flash-0731'))
    monkeypatch.setattr(provider_team,'stream',lambda **_:iter([dict(type='error',error='401 private-token example-password')]))
    result=model_probe.probe(tool_roundtrip=False)
    assert not result['ok'] and result['code']=='MODEL_AUTH_FAILED'
    assert 'private-token' not in str(result) and result['modelCalls']==1


def test_probe_api_rejects_unknown_fields_and_uses_only_configured_model(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(model_probe,'probe',lambda key,tools:calls.append((key,tools)) or dict(ok=True,modelCalls=1))
    app=FastAPI();app.include_router(build_cockpit_router(lambda:str(tmp_path)))
    client=TestClient(app)
    response=client.post('/api/cockpit/model/probe',json={'toolRoundtrip':False})
    assert response.status_code==200 and response.json()['ok']
    assert calls==[(None,False)]
    assert client.post('/api/cockpit/model/probe',json={'base_url':'http://other'}).status_code==422
    assert client.post('/api/cockpit/model/probe',json={'id':3}).status_code==422
    assert len(calls)==1


def test_probe_timeout_is_local_and_does_not_modify_normal_requests():
    import pytest
    from bi_agent.llm.runtime_config import request_config,scoped_request_timeout
    assert scoped_request_timeout() is None
    with request_config(request_timeout=20):assert scoped_request_timeout()==20
    with request_config(request_timeout=120):assert scoped_request_timeout()==120
    assert scoped_request_timeout() is None
    with pytest.raises(ValueError):
        with request_config(request_timeout=600):pass


def test_failed_probe_is_not_http_success(tmp_path,monkeypatch):
    monkeypatch.setattr(model_probe,'probe',lambda *_:dict(ok=False,code='MODEL_REASONING_PROTOCOL',connected=True))
    app=FastAPI();app.include_router(build_cockpit_router(lambda:str(tmp_path)))
    response=TestClient(app).post('/api/cockpit/model/probe',json={})
    assert response.status_code==502 and response.json()['connected']
    assert not response.json()['ok']
