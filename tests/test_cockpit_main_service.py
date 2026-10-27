"""Main-service execution, immutable delivery, engine isolation and rollout controls."""
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from bi_agent.cockpit.main_service import run_main_analysis, analysis_question
from bi_agent.cockpit.router import build_cockpit_router

CONTEXT=dict(id=1,engine='main',source='service',stage='shipment',period='2025-10',department='全部产品部',snapshotId='service-test')


def factory(events, messages=None, claims=None, choice=None):
    @contextmanager
    def make(context,cancel):
        yield SimpleNamespace(messages=messages or [],claims=claims or [],pending_choice_spec=choice),iter(events)
    return make


def test_adapter_does_not_rewrite_or_deliver_streamed_drafts():
    text='结论\n当前证据支持订单超期。\n根因分析\n原因仍需核实。\n行动建议\n核实对应质检放行记录。'
    events=[dict(type='cognitive_policy',mode='DIAGNOSTIC_ANALYSIS'),dict(type='text_delta',text='未经验证的错误根因'),dict(type='llm_response',text='旧候选',tool_uses=[]),dict(type='done',stop_reason='end_turn')]
    messages=[dict(role='assistant',content=[dict(type='text',text=text)])]
    result,trace=run_main_analysis(CONTEXT,threading.Event(),lambda *a:None,factory(events,messages,[dict(id='c1',statement='订单超期')]))
    assert result['narrative']==text
    assert result['causes']==[] and result['recommendations']==[]
    assert result['sections']['causes']=='原因仍需核实。'
    assert trace[0]['tool']=='MainServiceRoute'
    assert result['_status']=='completed'


def test_provider_error_and_no_done_never_deliver_intermediate_prose():
    for events in ([dict(type='text_delta',text='半截分析')],[dict(type='llm_response',text='尚未提交',tool_uses=[]),dict(type='done',stop_reason='end_turn')],[dict(type='error',message='private provider detail')]):
        with pytest.raises(RuntimeError):run_main_analysis(CONTEXT,threading.Event(),lambda *a:None,factory(events))


def test_clarification_and_blocked_answers_remain_explicit():
    result,_=run_main_analysis(CONTEXT,threading.Event(),lambda *a:None,factory([dict(type='awaiting_user_choice')],choice=dict(question='请选择销售口径',options=['发货','收入'])))
    assert result['_status']=='needs_input' and result['clarification']['question']=='请选择销售口径'
    result,_=run_main_analysis(CONTEXT,threading.Event(),lambda *a:None,factory([dict(type='done',stop_reason='answer_blocked')],[dict(role='assistant',content=[dict(type='text',text='证据不足')])]))
    assert result['_status']=='limited'
    assert '证据不足' in result['narrative']


def wait(client,aid):
    for _ in range(100):
        item=client.get('/api/cockpit/analyses/'+aid).json()
        if item['status'] not in {'queued','running'}:return item
        time.sleep(.01)
    raise AssertionError('task did not finish')


def test_main_route_is_injected_and_has_no_standalone_fallback(tmp_path):
    app=FastAPI();app.include_router(build_cockpit_router(lambda:tmp_path))
    client=TestClient(app)
    r=client.post('/api/cockpit/analyses',json=dict(engine='main',source='service'))
    assert r.status_code==503
    assert client.get('/api/cockpit/analyses').json()==[]


def test_engine_context_cache_and_production_lock(tmp_path,monkeypatch):
    seen=[]
    def run(c,stop,p):
        seen.append(c);return dict(summary='主服务交付',causes=[],recommendations=[],limitations=[],_evidence=dict(facts=[],records=[],evidence=[])),[]
    app=FastAPI();app.include_router(build_cockpit_router(lambda:tmp_path,main_runner=run,main_context=lambda c:dict(snapshotId='server-source',repositoryId='verified')))
    c=TestClient(app)
    request=dict(engine='main',source='service',chartSnapshotId='chart-1')
    first=c.post('/api/cockpit/analyses',json=request).json();done=wait(c,first['id'])
    assert done['context']['engine']=='main' and done['context']['repositoryId']=='verified'
    assert done['execution']['engine']=='main'
    again=c.post('/api/cockpit/analyses',json=request).json();wait(c,again['id'])
    assert again['id']!=first['id'] # Source identity is not a database snapshot.
    assert c.post('/api/cockpit/analyses',json=dict(source='prototype',filters={'customer':'S1'})).status_code==422
    monkeypatch.setenv('COCKPIT_COMPARISON_ENABLED','false');monkeypatch.setenv('COCKPIT_ANALYSIS_ENGINE','main')
    assert c.post('/api/cockpit/analyses',json=dict(engine='standalone')).status_code==422
    assert c.get('/api/cockpit/engines').json()['comparisonOnly'] is False


def test_real_websession_policy_runs_before_any_model(tmp_path):
    from bi_agent.web.session import WebSession
    from bi_agent.ontology.store import OntologyStore
    from open_claude.agent_def import AgentDef
    session=WebSession(cwd=str(tmp_path),agent_def=AgentDef(name='test',description='test',model='team-configured',tools=['AskUser'],max_iterations=2),ontology_store=OntologyStore())
    def provider(*a,**k):
        yield dict(type='tool_use_end',id='ask1',name='AskUser',input=dict(question='确认销售口径',options=['发货','收入']))
        yield dict(type='message_end',stop_reason='tool_use',usage={})
    @contextmanager
    def real(context,cancel):yield session,session.generate_turn(analysis_question(context))
    with patch('bi_agent.web.session.stream_message',side_effect=provider):
        result,events=run_main_analysis(CONTEXT,threading.Event(),lambda *a:None,real)
    assert result['_status']=='needs_input'
    assert events[0]['tool']=='MainServiceRoute'
    assert result['clarification']['question']=='确认销售口径'


def test_real_main_api_uses_shared_admission_and_preserves_user_sessions(tmp_path,monkeypatch):
    monkeypatch.setenv('COCKPIT_DATA_MODE','snapshot')
    import sqlite3
    import bi_agent.web.app as web
    from bi_agent.ontology.store import OntologyStore
    from bi_agent.concurrency import SessionSlotRegistry, AdmissionController, get_limits
    from open_claude.agent_def import AgentDef
    db=tmp_path/'data.sqlite';sqlite3.connect(db).close()
    user_session=object()
    for key,value in dict(cwd=str(tmp_path),ontology_backend='local',ontology_store=OntologyStore(),remote_ontology=None,
            db_path=str(db),use_doris=False,agent_def=AgentDef('test',tools=['AskUser']),
            sessions={'existing-user':user_session},source_contexts={},session_slots=SessionSlotRegistry(),admission=AdmissionController(get_limits())).items():
        monkeypatch.setattr(web.STATE,key,value)
    def provider(*a,**k):
        yield dict(type='tool_use_end',id='ask1',name='AskUser',input=dict(question='请选择销售指标',options=['发货','收入']))
        yield dict(type='message_end',stop_reason='tool_use',usage={})
    with patch('bi_agent.web.session.stream_message',side_effect=provider):
        client=TestClient(web.app)
        from bi_agent.cockpit.dashboard_source import RELEASE, SNAPSHOT
        import json
        query=next(iter(json.loads(SNAPSHOT.read_text())['analysis']))
        item=client.post('/api/cockpit/analyses',json=dict(engine='main',source='service',chartSnapshotId=RELEASE,chartQueries=[query])).json()
        assert 'id' in item,item
        done=wait(client,item['id'])
    assert done['status']=='needs_input',done
    assert done['result']['clarification']['question']=='请选择销售指标'
    assert done['execution']['route']['mode']
    assert web.STATE.sessions=={'existing-user':user_session}
    assert web.STATE.source_contexts=={}
    assert client.post('/api/cockpit/analyses',json=dict(engine='main',source='service',repositoryId='unbound')).status_code==422


def test_routes_keep_separate_cache_and_never_share_demo_results(tmp_path):
    def standalone(e,c,stop,p):return dict(summary='独立演示结果',causes=[],recommendations=[],limitations=[]),[]
    def main(c,stop,p):return dict(summary='主服务实时结果',causes=[],recommendations=[],limitations=[]),[]
    app=FastAPI();app.include_router(build_cockpit_router(lambda:tmp_path,runner=standalone,main_runner=main,
        main_context=lambda c:dict(snapshotId='configured-source',repositoryId='1')))
    client=TestClient(app)
    a=client.post('/api/cockpit/analyses',json=dict(engine='standalone',source='prototype')).json();wait(client,a['id'])
    b=client.post('/api/cockpit/analyses',json=dict(engine='main',source='service')).json();wait(client,b['id'])
    assert a['scope']!=b['scope']
    assert len(client.get('/api/cockpit/analyses?engine=main').json())==1
    assert len(client.get('/api/cockpit/analyses?engine=standalone').json())==1
    again=client.post('/api/cockpit/analyses',json=dict(engine='standalone',source='prototype')).json()
    assert again['id']==a['id']


def test_frozen_main_evidence_is_server_owned_and_scope_checked(tmp_path):
    seen=[]
    packet=dict(sourceMode='service',snapshotId='source-id',stage='shipment',facts=[dict(id='fact1',label='已取数事实',value=1,unit='单')],records=[],evidence=[dict(id='fact1',label='已取数事实',value=1,unit='单',definition='测试查询结果')],causes=[],limitations=[])
    def main(c,stop,p):return dict(summary='原始主服务结果',causes=[],recommendations=[],limitations=[],_evidence=packet),[]
    def standalone(e,c,stop,p):
        seen.append((e,c));return dict(summary='冻结材料分析',causes=[],recommendations=[],limitations=[]),[]
    app=FastAPI();app.include_router(build_cockpit_router(lambda:tmp_path,runner=standalone,main_runner=main,main_context=lambda c:dict(snapshotId='source-id',repositoryId='1')))
    client=TestClient(app)
    baseline=client.post('/api/cockpit/analyses',json=dict(engine='main',source='service')).json();wait(client,baseline['id'])
    request=dict(engine='standalone',source='service',baselineAnalysisId=baseline['id'])
    item=client.post('/api/cockpit/analyses',json=request).json();done=wait(client,item['id'])
    assert done['status']=='completed'
    assert seen[0][0]['facts']==packet['facts']
    assert seen[0][0]['snapshotId'].startswith('frozen-')
    assert done['context']['baselineAnalysisId']==baseline['id']
    assert client.post('/api/cockpit/analyses',json={**request,'id':2}).status_code==422
    assert client.post('/api/cockpit/analyses',json={**request,'stage':'order'}).status_code==422
    assert client.post('/api/cockpit/analyses',json=dict(engine='standalone',source='service')).status_code==422
    assert client.get('/api/cockpit/analyses/'+baseline['id']).json()['evidence']['snapshotId']=='source-id'


def test_raw_query_row_cannot_be_upgraded_to_supported_root_cause():
    from bi_agent.cockpit.agent import validate_result
    row=dict(id='q1',causeSupport=False)
    evidence=dict(records=[row],evidence=[dict(id='q1')],limitations=[])
    result=dict(summary='存在异常',causes=[dict(id='c1',title='原因',description='未经独立验证',status='supported',evidenceIds=['q1'])],recommendations=[dict(id='r1',causeIds=['c1'],action='核实',ownerRole='分析员',deadlineDays=1,acceptance='核实证据')],limitations=['待确认'])
    with pytest.raises(ValueError):validate_result(result,evidence,{'q1'})
    result['causes'][0]['status']='hypothesis'
    assert validate_result(result,evidence,{'q1'})['causes'][0]['status']=='hypothesis'
