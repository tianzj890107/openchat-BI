import threading
import time
import pytest
from bi_agent.runtime.tasks import TaskService


def wait(service, task):
    for _ in range(200):
        result = service.get(task['task_id'], task['task_token'])
        if result['status'] not in {'queued','running','cancelling'}:
            return result
        time.sleep(.01)
    raise AssertionError('task did not finish')


def test_task_events_and_ownership_survive_restart(tmp_path):
    path = tmp_path/'tasks.db'
    service = TaskService(path, lambda *args: iter([{'type':'text_delta','text':'answer'}, {'type':'done'}]))
    task = service.submit('question')
    assert wait(service, task)['status'] == 'completed'
    with pytest.raises(PermissionError):
        service.get(task['task_id'], 'wrong')
    assert service.get(task['task_id'],task['task_token'],after=1)['events'][0]['event']['type']=='done'
    service.close()
    service = TaskService(path, lambda *args: iter(()))
    assert service.get(task['task_id'],task['task_token'])['status']=='completed'
    service.close()


def test_cancel_is_cooperative_and_capacity_is_bounded(tmp_path):
    started = threading.Event()
    def runner(task_id, question, cancel):
        started.set()
        cancel.wait(2)
        yield {'type':'done'}
    service = TaskService(tmp_path/'tasks.db',runner,workers=1,capacity=1)
    task = service.submit('question')
    assert started.wait(1)
    with pytest.raises(RuntimeError,match='capacity'):
        service.submit('another')
    with pytest.raises(PermissionError):
        service.cancel(task['task_id'],'wrong')
    service.cancel(task['task_id'],task['task_token'])
    assert wait(service,task)['status']=='cancelled'
    service.close()


def test_missing_terminal_and_provider_failure_are_not_success(tmp_path):
    def runner(*args):
        yield {'type':'text_delta','text':'partial'}
        raise RuntimeError('secret-provider-key')
    service = TaskService(tmp_path/'tasks.db',runner)
    task = service.submit('question')
    result=wait(service,task)
    assert result['status']=='failed'
    assert 'secret-provider-key' not in str(result)
    service.close()


def test_restart_marks_incomplete_tasks_interrupted(tmp_path):
    import sqlite3
    path=tmp_path/'tasks.db'
    service=TaskService(path,lambda *args:iter(()))
    service.close()
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)',('unfinished',service._digest('token'),'running',0,0))
    service=TaskService(path,lambda *args:iter(()))
    assert service.get('unfinished','token')['status']=='interrupted'
    service.close()


def test_mcp_task_adapter_runs_shared_websession_and_preserves_browser(tmp_path,monkeypatch):
    import json
    import sqlite3
    from fastapi.testclient import TestClient
    import bi_agent.web.app as web
    from bi_agent.ontology.store import OntologyStore
    from bi_agent.concurrency import SessionSlotRegistry,AdmissionController,get_limits
    from open_claude.agent_def import AgentDef
    db=tmp_path/'data.db'
    sqlite3.connect(db).close()
    browser=object()
    for key,value in dict(cwd=str(tmp_path),ontology_backend='local',ontology_store=OntologyStore(),remote_ontology=None,
        db_path=str(db),use_doris=False,agent_def=AgentDef('test',tools=['AskUser']),
        sessions={'browser':browser},source_contexts={},session_slots=SessionSlotRegistry(),admission=AdmissionController(get_limits())).items():
        monkeypatch.setattr(web.STATE,key,value)
    monkeypatch.setattr(web,'_analysis_task_service',None)
    def provider(*args,**kwargs):
        yield dict(type='tool_use_end',id='ask1',name='AskUser',input=dict(question='请选择销售指标',options=['发货','收入']))
        yield dict(type='message_end',stop_reason='tool_use',usage={})
    monkeypatch.setattr('bi_agent.runtime.session.stream_message',provider)
    client=TestClient(web.app)
    endpoint='/api/mcp/tasks'
    init=client.post(endpoint,json=dict(jsonrpc='2.0',id=1,method='initialize',params={}))
    headers={'Mcp-Session-Id':init.headers['mcp-session-id']}
    def call(name,args):
        response=client.post(endpoint,headers=headers,json=dict(jsonrpc='2.0',id=2,method='tools/call',params=dict(name=name,arguments=args)))
        payload=response.json()['result']
        assert not payload.get('isError'),payload
        return json.loads(payload['content'][0]['text'])
    task=call('AnalysisTaskSubmit',dict(question='分析销售情况'))
    result=wait(web._analysis_task_service,task)
    assert result['status']=='needs_input',result
    assert any(e['event']['type']=='cognitive_policy' for e in result['events'])
    assert call('AnalysisTaskGet',dict(task_id=task['task_id'],task_token=task['task_token']))['status']=='needs_input'
    assert web.STATE.sessions=={'browser':browser}
    assert web.STATE.source_contexts=={}
    web._analysis_task_service.close()


def test_task_mcp_auth_and_argument_boundaries(tmp_path,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from bi_agent.web.mcp_endpoint import build_mcp_router
    service=TaskService(tmp_path/'tasks.db',lambda *args:iter([{'type':'done'}]))
    app=FastAPI()
    app.include_router(build_mcp_router(get_source=lambda:None,build_doris=lambda *a:None,get_cwd=lambda:str(tmp_path),task_service_factory=lambda:service))
    client=TestClient(app)
    monkeypatch.setenv('ONTOLOGY_MCP_AUTH_TOKEN','private-test-token')
    body=dict(jsonrpc='2.0',id=1,method='initialize',params={})
    assert client.post('/api/mcp/tasks',json=body).status_code==401
    headers={'Authorization':'Bearer private-test-token'}
    response=client.post('/api/mcp/tasks',json=body,headers=headers)
    headers['Mcp-Session-Id']=response.headers['mcp-session-id']
    for name,args in [('TaskOrderCreate',{}),('AnalysisTaskSubmit',dict(question='question',session_id='browser'))]:
        result=client.post('/api/mcp/tasks',headers=headers,json=dict(jsonrpc='2.0',id=2,method='tools/call',params=dict(name=name,arguments=args))).json()
        assert result['result']['isError'] is True
    service.close()


def test_delegated_runtime_blocks_provider_invented_write_tool(tmp_path,monkeypatch):
    from bi_agent.runtime.session import AgentSession
    from bi_agent.ontology.store import OntologyStore
    from open_claude.agent_def import AgentDef
    session=AgentSession(str(tmp_path),AgentDef('test',tools=['AskUser']),OntologyStore())
    session.enforce_tool_allowlist=True
    called=[]
    monkeypatch.setattr('bi_agent.runtime.session.execute_tool',lambda *a:called.append(a))
    outcome=session._run_tool_boundary('TaskOrderCreate','forbidden',{},None)
    assert not called
    assert outcome.status != 'success'


def test_live_task_store_cannot_be_opened_by_another_owner(tmp_path):
    path=tmp_path/'tasks.db'
    service=TaskService(path,lambda *args:iter(()))
    try:
        with pytest.raises(RuntimeError,match='already_owned'):
            TaskService(path,lambda *args:iter(()))
    finally:
        service.close()


def test_queued_cancel_does_not_execute_and_keeps_records(tmp_path):
    started=threading.Event()
    release=threading.Event()
    seen=[]
    def runner(task_id,question,cancel):
        seen.append(question)
        started.set()
        release.wait(2)
        yield {'type':'done'}
    service=TaskService(tmp_path/'tasks.db',runner,workers=1,capacity=2)
    first=service.submit('first')
    assert started.wait(1)
    queued=service.submit('queued')
    service.cancel(queued['task_id'],queued['task_token'])
    release.set()
    assert wait(service,queued)['status']=='cancelled'
    assert wait(service,first)['status']=='completed'
    assert seen==['first']
    service.close()


@pytest.mark.parametrize('events,expected',[
    ([{'type':'text_delta','text':'partial'}],'failed'),
    ([{'type':'done','stop_reason':'max_tokens'}],'failed'),
    ([{'type':'done','stop_reason':'answer_blocked'}],'limited'),
])
def test_task_terminal_status_does_not_claim_partial_success(tmp_path,events,expected):
    service=TaskService(tmp_path/'tasks.db',lambda *args:iter(events))
    task=service.submit('question')
    assert wait(service,task)['status']==expected
    service.close()
