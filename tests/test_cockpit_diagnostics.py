from contextlib import contextmanager
from copy import deepcopy
import json
from types import SimpleNamespace
import threading

import pytest
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient

from bi_agent.cockpit.diagnostics import AnalysisFailure,diagnostic_scope,record_failure,redact
from bi_agent.cockpit.main_service import run_main_analysis
from bi_agent.cockpit.store import Store


def test_original_model_error_and_last_tool_survive_without_credentials(tmp_path,monkeypatch):
    monkeypatch.setenv('TEAM_API_KEY','sample-model-secret')
    @contextmanager
    def factory(context,cancel):
        yield SimpleNamespace(claims=[]),iter([
            {'type':'tool_start','name':'CockpitDeliverCards'},
            {'type':'error','message':'provider 429 api_key=sample-model-secret Bearer unknown.jwt.signature','error_code':'RATE_LIMIT'}])
    with pytest.raises(AnalysisFailure) as failure:
        run_main_analysis({},threading.Event(),lambda *a:None,factory)
    store=Store(tmp_path/'history.sqlite3')
    value=record_failure(store,failure.value,phase='analysis',stage='shipment',analysis_id='task-1',duration=12)
    assert value['message'].startswith('provider 429')
    assert value['lastTool']=='CockpitDeliverCards' and value['errorCode']=='RATE_LIMIT'
    assert 'sample-model-secret' not in json.dumps(value) and 'unknown.jwt.signature' not in json.dumps(value)
    assert Store(store.path).list_diagnostics(stage='shipment')[0]['analysisId']=='task-1'


def test_diagnostics_capture_full_ap_root_cause_without_changing_public_error(tmp_path,monkeypatch):
    from bi_agent.cockpit.router import build_cockpit_router
    class Config:
        base_url='http://ap.example';batch_mode='individual';receipt_ttl=60
        def headers(self):return {}
        def identity(self):return 'test'
    class Gateway:
        config=Config()
        def query(self,*args,**kwargs):
            exc=HTTPException(502,'AP query failed')
            exc.diagnostic_message='bad SQL grammar '+('SELECT q '*1000)+' ERROR: column input_time does not exist'
            raise exc
    monkeypatch.setattr('bi_agent.cockpit.router.get_gateway',lambda:Gateway())
    monkeypatch.setenv('COCKPIT_REFRESH_ENABLED','0');monkeypatch.setenv('COCKPIT_DATA_MODE','ap')
    app=FastAPI();app.include_router(build_cockpit_router(lambda:str(tmp_path),main_context=lambda req:{}))
    client=TestClient(app)
    with diagnostic_scope(stage='order',runId='run-1'):
        response=client.post('/api/cockpit/data/query',json={'id':1,'kind':'analysis','payload':{'analysisConfig':{}}})
    assert response.status_code==502 and response.json()['detail']=='AP query failed'
    diagnostic_id=response.headers['X-Cockpit-Diagnostic-Id']
    values=client.get('/api/cockpit/diagnostics?id=1&stage=order').json()['items']
    assert len(values)==1 and values[0]['diagnosticId']==diagnostic_id
    assert values[0]['phase']=='ap_query' and values[0]['runId']=='run-1'
    assert 'column input_time does not exist' in values[0]['message']
    assert len(values[0]['queryHash'])==64 and len(values[0]['message'])<1600
    assert client.get('/api/cockpit/diagnostics?id=2').json()['items']==[]
    assert client.get('/api/cockpit/diagnostics?limit=1000').status_code==422


def test_config_header_and_connection_password_redaction(tmp_path,monkeypatch):
    headers=tmp_path/'headers.json';headers.write_text(json.dumps({'Authorization':'Bearer header-private','Cookie':'session=private; a=b'}))
    monkeypatch.setenv('COCKPIT_AP_HEADERS_FILE',str(headers))
    text=redact('Bearer header-private Cookie="session=private; a=b" postgres://user:db-secret@host/db')
    assert all(v not in text for v in ['header-private','session=private','db-secret'])


def test_model_diagnostic_is_attached_to_the_failed_task(tmp_path,monkeypatch):
    import time
    from bi_agent.cockpit.router import build_cockpit_router
    monkeypatch.setenv('COCKPIT_REFRESH_ENABLED','0')
    def context(req):return {'snapshotId':'service-fixture','dataSource':'ap','dataFingerprint':'test'}
    def runner(context,cancel,progress):
        raise AnalysisFailure('provider request timed out',phase='model_request',code='PROVIDER_TIMEOUT')
    app=FastAPI();app.include_router(build_cockpit_router(lambda:str(tmp_path),main_context=context,main_runner=runner))
    client=TestClient(app)
    job=client.post('/api/cockpit/analyses',json={'id':1,'engine':'main','source':'service','stage':'shipment'}).json()
    for _ in range(100):
        item=client.get('/api/cockpit/analyses/'+job['id']).json()
        if item['status']=='failed':break
        time.sleep(.01)
    assert item['status']=='failed'
    diagnostic=item['execution']['diagnostic']
    assert diagnostic['analysisId']==job['id'] and diagnostic['phase']=='model_request'
    assert diagnostic['errorCode']=='PROVIDER_TIMEOUT' and diagnostic['message']=='provider request timed out'
    assert diagnostic['diagnosticId'] in item['error']
    assert client.get('/api/cockpit/diagnostics?stage=shipment').json()['items'][0]==diagnostic


def test_redaction_handles_driver_named_password_and_unknown_url_tokens(monkeypatch):
    monkeypatch.setenv('PROCESS360_PG_PASSWORD','postgres')
    text=redact('postgres://user:unknown-db-password@host/db access_token=unknown-access-token Authorization: Bearer unknown-provider-token')
    assert 'unknown-db-password' not in text
    assert 'unknown-access-token' not in text
    assert 'unknown-provider-token' not in text


def test_whole_page_rejection_has_persisted_diagnostic(tmp_path,monkeypatch):
    from bi_agent.cockpit.router import build_cockpit_router
    from test_cockpit_page_cache import fixture
    store,cfg,req,_=fixture(tmp_path)
    monkeypatch.setenv('COCKPIT_DATA_MODE','ap')
    monkeypatch.setenv('COCKPIT_REFRESH_ENABLED','0')
    monkeypatch.setattr('bi_agent.cockpit.router.get_gateway',lambda:SimpleNamespace(config=cfg))
    # The router owns its history location; use a controlled rejection to avoid
    # copying real data and to exercise HTTP response/log correlation.
    def reject(*args,**kwargs):
        exc=HTTPException(422,'AI插槽未完整交付，保留上次完整版本')
        exc.diagnostic_message='page=analysis missingStages=shipment'
        raise exc
    monkeypatch.setattr('bi_agent.cockpit.router.build_page',reject)
    app=FastAPI();app.include_router(build_cockpit_router(lambda:str(tmp_path),main_context=lambda req:{}))
    client=TestClient(app)
    response=client.post('/api/cockpit/page',json=req.model_dump())
    assert response.status_code==422
    diagnostic=client.get('/api/cockpit/diagnostics?id=1').json()['items'][0]
    assert diagnostic['phase']=='page_publication'
    assert diagnostic['diagnosticId']==response.headers['X-Cockpit-Diagnostic-Id']
    assert 'missingStages=shipment' in diagnostic['message']
