"""AP transport isolation and authoritative result receipts, without a live model."""
import json
import io
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from bi_agent.cockpit.ap_gateway import APConfig, APGateway, PATHS
from bi_agent.cockpit.dashboard_source import RELEASE, receipt_material
from bi_agent.cockpit.router import build_cockpit_router
from bi_agent.cockpit.store import Store

QUERY={'analysisConfig':{'dimensions':[], 'indicators':[{'identifierCode':'M0001','alias':'订单超期未发金额'}]},'commonConfig':{'pagination':{'pageNum':1,'pageSize':20}}}
DATA={'resultType':'TABLE','result':{'columns':[{'identifierCode':'M0001','label':'订单超期未发金额','type':'METRIC'}],'rows':[{'M0001':{'value':42.5}}]}}


class Opener:
    def __init__(self, response):self.response=response;self.calls=[]
    def open(self, request, timeout):
        self.calls.append((request,timeout))
        if isinstance(self.response,Exception):raise self.response
        return io.BytesIO(json.dumps(self.response).encode())


class SplitOpener:
    """Reject the combined indicator set, then answer each indicator alone."""
    def __init__(self, fail=''):
        self.calls = []
        self.fail = fail

    def open(self, request, timeout):
        payload = json.loads(request.data)
        self.calls.append(payload)
        indicators = (payload.get('analysisConfig') or {}).get('indicators') or []
        if len(indicators) > 1:
            return io.BytesIO(json.dumps({'success': False, 'data': None,
                'msg': '本地查询组合未配置: M|A,B,C|YWLN_D005|_'}).encode())
        code = indicators[0]['identifierCode']
        if code == self.fail:
            return io.BytesIO(json.dumps({'success': False, 'data': None,
                'msg': '本地查询组合未配置: ' + code}).encode())
        values = {'A': [1, 2, 3], 'B': [10, 20, 30], 'C': [100, 200, 300]}[code]
        names = ['战略客户', '重点客户', '一般客户']
        order = [0, 1, 2] if code != 'B' else [2, 1, 0]
        rows = [{**{'YWLN_D005': {'value': names[i]}}, code: {'value': values[i]}}
                for i in order]
        return io.BytesIO(json.dumps({'success': True, 'data': {
            'resultType': 'TABLE',
            'result': {'columns': [
                {'identifierCode': 'YWLN_D005', 'label': '客户等级', 'type': 'DIMENSION'},
                {'identifierCode': code, 'label': code, 'type': 'METRIC'}], 'rows': rows},
            'pagination': {'total': 3, 'pageNum': 1, 'pageSize': 10}}}).encode())


def config(tmp_path, **changes):
    headers=tmp_path/'ap-headers.json'
    headers.touch(mode=0o600,exist_ok=True)
    headers.write_text(json.dumps({'X-App-Id':'cockpit-app','X-Ontology-Repository-Id':'ap-repo','apifoxToken':'private-ap-test'}))
    return APConfig(**dict(base_url='http://ap.example/api/gateway2/x360',headers_file=str(headers),timeout=2,concurrency=1,receipt_ttl=60,batch_mode='native',**changes))


def test_gateway_base_owns_x360_instead_of_api_paths(tmp_path):
    assert all(not path.startswith('/x360') for path in PATHS.values())
    env=(Path(__file__).resolve().parents[1]/'.env.example').read_text()
    base=next(line for line in env.splitlines() if line.startswith('COCKPIT_AP_BASE_URL='))
    assert base.endswith('/x360')
    gateway=APGateway(config(tmp_path),Opener({'success':True,'data':DATA}))
    gateway.query('analysis',QUERY)
    request,_=gateway._opener.calls[0]
    assert request.full_url=='http://ap.example/api/gateway2/x360/v1/ontology/data/query'


def test_transport_has_its_own_headers_paths_and_capacity(tmp_path,monkeypatch):
    monkeypatch.setenv('ONTOLOGY_AUTH_TOKEN','must-not-reach-ap')
    opener=Opener({'success':True,'data':DATA})
    gateway=APGateway(config(tmp_path),opener)
    assert gateway.query('analysis',QUERY)==DATA
    request,timeout=opener.calls[0]
    assert request.full_url=='http://ap.example/api/gateway2/x360/v1/ontology/data/query'
    assert request.get_method()=='POST' and timeout==pytest.approx(2,abs=0.2)
    assert 'must-not-reach-ap' not in str(request.headers)
    assert request.headers['X-ontology-repository-id']=='8'
    assert json.loads(request.data)==QUERY
    gateway._capacity.acquire()
    try:
        threading.Timer(0.1,gateway._capacity.release).start()
        assert gateway.query('analysis',QUERY)==DATA
    finally:
        if gateway._capacity.acquire(blocking=False):gateway._capacity.release()
    assert gateway.query('analysis',QUERY)==DATA


def test_saturated_gateway_times_out_instead_of_rejecting_immediately(tmp_path):
    from dataclasses import replace
    gateway=APGateway(replace(config(tmp_path),timeout=1),Opener({'success':True,'data':DATA}))
    gateway._capacity.acquire()
    started=time.monotonic()
    try:
        with pytest.raises(HTTPException) as error:gateway.query('analysis',QUERY)
        assert error.value.status_code==504 and '并发已满' not in str(error.value.detail)
        assert time.monotonic()-started>=0.5
    finally:gateway._capacity.release()


@pytest.mark.parametrize('failure',[TimeoutError('private-ap-test'),HTTPError('http://secret-url',401,'private-ap-test',{},None),{'success':False,'msg':'private-ap-test','data':DATA}, {'success':True}, {'success':True,'data':[]}])
def test_failures_are_bounded_sanitized_and_never_fall_back(tmp_path,failure):
    gateway=APGateway(config(tmp_path),Opener(failure))
    with pytest.raises(HTTPException) as error:gateway.query('batch',[QUERY])
    assert 'private-ap-test' not in str(error.value.detail)
    assert error.value.status_code in {502,504}
    assert gateway._capacity.acquire(blocking=False)
    gateway._capacity.release()


def test_only_fixed_read_interfaces_and_complete_batch(tmp_path):
    gateway=APGateway(config(tmp_path),Opener({'success':True,'data':[{'success':True,'data':DATA}]}))
    assert gateway.query('batch',[QUERY])[0]['data']==DATA
    with pytest.raises(HTTPException):gateway.query('batch',[QUERY,QUERY])
    with pytest.raises(HTTPException):gateway.query('http://foreign/write',{})
    with pytest.raises(HTTPException):gateway.query('analysis',{'url':'http://foreign'})
    assert len(gateway._opener.calls)==2


def test_receipts_bind_identity_scope_and_expiry_without_deleting_history(tmp_path):
    store=Store(tmp_path/'history.sqlite3')
    item=store.save_ap_result(1,'analysis',QUERY,DATA,60)
    context=dict(id=1,apReceiptIds=[item['id']],chartQueries=[json.dumps(QUERY)])
    fingerprint,selected=receipt_material(context,store)
    assert next(iter(selected.values()))['response']==DATA
    assert receipt_material(context,store)[0]==fingerprint
    for changes in ({'id':2},{'chartQueries':['{}']},{'apReceiptIds':[item['id'],item['id']]},{'apReceiptIds':['x'*32]}):
        with pytest.raises(ValueError):receipt_material({**context,**changes},store)
    with patch('bi_agent.cockpit.store.time.time',return_value=item['expiresAt']+1):
        with pytest.raises(ValueError):receipt_material(context,store)
        assert receipt_material(context,store,allow_expired=True)[0]==fingerprint
    assert store.get_ap_result(item['id'],1) # Expiry validation never deletes stored evidence.


def test_proxy_returns_exact_result_and_receipt_without_extra_fetch(tmp_path,monkeypatch):
    import bi_agent.cockpit.router as router
    monkeypatch.setenv('COCKPIT_DATA_MODE','ap')
    gateway=APGateway(config(tmp_path),Opener({'success':True,'data':DATA}))
    monkeypatch.setattr(router,'get_gateway',lambda:gateway)
    app=FastAPI();app.include_router(build_cockpit_router(lambda:tmp_path,main_context=lambda c:{}))
    client=TestClient(app)
    response=client.post('/api/cockpit/data/query',json=dict(id=1,kind='analysis',payload=QUERY))
    assert response.status_code==200,response.text
    body=response.json();assert body['data']==DATA
    store=Store(tmp_path/'dataset/cockpit/history.sqlite3')
    material=receipt_material(dict(id=1,apReceiptIds=[body['receiptId']],chartQueries=[json.dumps(QUERY)]),store)
    assert next(iter(material[1].values()))['response']==body['data']
    assert len(gateway._opener.calls)==1
    assert client.post('/api/cockpit/data/query',json=dict(kind='analysis',payload=QUERY,url='http://evil')).status_code==422
    assert 'private-ap-test' not in response.text


def test_http_queries_share_the_same_short_lived_receipt_and_report_timing(tmp_path,monkeypatch):
    import bi_agent.cockpit.router as router
    monkeypatch.setenv('COCKPIT_DATA_MODE','ap')
    monkeypatch.setenv('COCKPIT_AP_REUSE_SECONDS','300')
    gateway=APGateway(config(tmp_path),Opener({'success':True,'data':DATA}))
    monkeypatch.setattr(router,'get_gateway',lambda:gateway)
    app=FastAPI();app.include_router(build_cockpit_router(lambda:tmp_path,main_context=lambda c:{}))
    client=TestClient(app)
    first=client.post('/api/cockpit/data/query',json=dict(id=1,kind='analysis',payload=QUERY)).json()
    second=client.post('/api/cockpit/data/query',json=dict(id=1,kind='analysis',payload=QUERY)).json()
    assert first['receiptId']==second['receiptId'] and len(gateway._opener.calls)==1
    assert {'backendQueueMs','upstreamMs','receiptWaitMs','serverTotalMs'} <= set(first['timings'])
    assert second['timings']['cacheHit'] is True and 'receiptWaitMs' in second['timings']


def test_completed_http_queries_are_not_reused_by_default(tmp_path,monkeypatch):
    import bi_agent.cockpit.router as router
    monkeypatch.setenv('COCKPIT_DATA_MODE','ap')
    monkeypatch.delenv('COCKPIT_AP_REUSE_SECONDS',raising=False)
    gateway=APGateway(config(tmp_path),Opener({'success':True,'data':DATA}))
    monkeypatch.setattr(router,'get_gateway',lambda:gateway)
    app=FastAPI();app.include_router(build_cockpit_router(lambda:tmp_path,main_context=lambda c:{}))
    client=TestClient(app)
    first=client.post('/api/cockpit/data/query',json=dict(id=1,kind='analysis',payload=QUERY)).json()
    second=client.post('/api/cockpit/data/query',json=dict(id=1,kind='analysis',payload=QUERY)).json()
    assert first['receiptId']!=second['receiptId'] and len(gateway._opener.calls)==2
    assert first['timings']['cacheHit'] is False and second['timings']['cacheHit'] is False


def test_sidecar_and_snapshot_mode_cannot_start_live_proxy(tmp_path,monkeypatch):
    app=FastAPI();app.include_router(build_cockpit_router(lambda:tmp_path))
    client=TestClient(app)
    assert client.get('/api/cockpit/data/config').json()['available'] is False
    assert client.post('/api/cockpit/data/query',json=dict(kind='analysis',payload=QUERY)).status_code==503
    app=FastAPI();app.include_router(build_cockpit_router(lambda:tmp_path,main_context=lambda c:{}))
    monkeypatch.setenv('COCKPIT_DATA_MODE','snapshot')
    assert TestClient(app).post('/api/cockpit/data/query',json=dict(kind='analysis',payload=QUERY)).status_code==409


def test_real_main_api_uses_same_result_and_leaves_existing_sources_untouched(tmp_path,monkeypatch):
    import bi_agent.web.app as web
    import bi_agent.cockpit.router as router
    from open_claude.agent_def import AgentDef
    from bi_agent.ontology.store import OntologyStore
    from bi_agent.concurrency import SessionSlotRegistry, AdmissionController, get_limits
    monkeypatch.setenv('COCKPIT_DATA_MODE','ap')
    existing=object();ontology=OntologyStore()
    for key,value in dict(cwd=str(tmp_path),agent_def=AgentDef('test',tools=['AskUser']),sessions={'user':existing},
            ontology_store=ontology,source_contexts={},session_slots=SessionSlotRegistry(),admission=AdmissionController(get_limits())).items():
        monkeypatch.setattr(web.STATE,key,value)
    gateway=APGateway(config(tmp_path),Opener({'success':True,'data':DATA}))
    monkeypatch.setattr(router,'get_gateway',lambda:gateway)
    client=TestClient(web.app)
    receipt=client.post('/api/cockpit/data/query',json=dict(id=1,kind='analysis',payload=QUERY)).json()
    calls=[]
    def provider(*a,**k):
        calls.append(1)
        if len(calls)==1:
            yield dict(type='tool_use_end',id='read',name='Cockpit-DashboardQuery',input={'queryId':receipt['receiptId']+':0'})
        else:
            from tests.test_cockpit_card_delivery import candidate
            yield dict(type='tool_use_end',id='deliver',name='CockpitDeliverCards',input=candidate())
        yield dict(type='message_end',stop_reason='tool_use',usage={})
    from tests.test_cockpit_main_service import wait
    with patch('bi_agent.web.session.stream_message',side_effect=provider), patch.object(web,'_source_for_session',side_effect=AssertionError('must not touch original source')):
        task=client.post('/api/cockpit/analyses',json=dict(id=1,engine='main',source='service',stage='shipment',chartSnapshotId=RELEASE,
            chartQueries=[json.dumps(QUERY)],apReceiptIds=[receipt['receiptId']])).json()
        assert 'id' in task,task
        done=wait(client,task['id'])
    assert done['status']=='limited',done
    assert done['evidence']['facts'] and done['evidence']['facts'][0]['value']==42.5
    assert done['evidence']['records'][0]['data']=={'订单超期未发金额[M0001]':42.5}
    assert '页面本次实时AP响应' in done['result']['limitations'][0]
    assert len(gateway._opener.calls)==1
    assert web.STATE.sessions=={'user':existing} and web.STATE.ontology_store is ontology
    assert client.post('/api/cockpit/analyses',json=dict(engine='main',source='service',chartQueries=[json.dumps(QUERY)],apReceiptIds=[receipt['receiptId']],repositoryId='original-repo')).status_code==422


def test_private_credentials_and_bad_config_never_fall_back(tmp_path,monkeypatch):
    cfg=config(tmp_path)
    if __import__('os').name=='posix':
        __import__('pathlib').Path(cfg.headers_file).chmod(0o644)
        with pytest.raises(HTTPException) as error:cfg.headers()
        assert error.value.status_code==503
    monkeypatch.delenv('COCKPIT_AP_BASE_URL',raising=False)
    monkeypatch.setenv('ONTOLOGY_BASE_URL','http://must-not-be-used')
    with pytest.raises(HTTPException):APConfig.load()


def test_waiting_cockpit_analysis_can_cancel_without_acquiring_main_admission(monkeypatch):
    import bi_agent.web.app as web
    semaphore=threading.BoundedSemaphore(1);semaphore.acquire()
    monkeypatch.setattr(web,'_cockpit_analysis_capacity',semaphore)
    cancel=threading.Event();cancel.set()
    with patch.object(web,'_begin_turn',side_effect=AssertionError('no main slot for queued cancelled job')):
        with pytest.raises(InterruptedError):web._cockpit_main_runner({},cancel,lambda *a:None)
    semaphore.release()


def test_individual_batch_uses_exact_single_ap_queries_in_order_and_never_calls_native(tmp_path):
    from dataclasses import replace
    opener=Opener({'success':True,'data':DATA})
    cfg=replace(config(tmp_path),batch_mode='individual')
    gateway=APGateway(cfg,opener)
    second={**QUERY,'commonConfig':{'filters':{'department':'B'}}}
    result=gateway.query('batch',[QUERY,second])
    assert result==[{'success':True,'data':DATA},{'success':True,'data':DATA}]
    assert [json.loads(r.data) for r,_ in opener.calls]==[QUERY,second]
    assert all(r.full_url.endswith('/v1/ontology/data/query') for r,_ in opener.calls)
    assert all(timeout<=cfg.timeout for _,timeout in opener.calls)


def test_individual_batch_refuses_partial_results_when_any_child_fails(tmp_path):
    from dataclasses import replace
    class FailSecond(Opener):
        def open(self,request,timeout):
            if self.calls:raise HTTPError('http://ap.example',500,'private-failure',{},None)
            return super().open(request,timeout)
    gateway=APGateway(replace(config(tmp_path),batch_mode='individual'),FailSecond({'success':True,'data':DATA}))
    with pytest.raises(HTTPException) as error:gateway.query('batch',[QUERY,{**QUERY,'commonConfig':{'pagination':{'pageNum':2}}}])
    assert error.value.status_code==502 and 'private-failure' not in error.value.detail
    assert gateway._capacity.acquire(blocking=False)
    gateway._capacity.release()


def test_individual_batch_has_one_overall_deadline(tmp_path):
    from dataclasses import replace
    gateway=APGateway(replace(config(tmp_path),timeout=1,batch_mode='individual'),Opener({'success':True,'data':DATA}))
    with patch('bi_agent.cockpit.ap_gateway.time.monotonic',side_effect=[0,0,0,2]):
        with pytest.raises(HTTPException) as error:gateway.query('batch',[QUERY,QUERY])
    assert error.value.status_code==504 and len(gateway._opener.calls)==1


def test_invalid_batch_mode_is_a_configuration_error(monkeypatch):
    monkeypatch.setenv('COCKPIT_AP_BASE_URL','http://ap.example/api/gateway2/x360')
    monkeypatch.setenv('COCKPIT_AP_BATCH_MODE','invented')
    with pytest.raises(HTTPException) as error:APConfig.load()
    assert error.value.status_code==503


def test_ontology_gateway_code_envelope_and_repository_override(monkeypatch,tmp_path):
    monkeypatch.setenv('COCKPIT_AP_BASE_URL','http://ap.example/api/gateway2/x360')
    monkeypatch.setenv('COCKPIT_AP_HEADERS_FILE',str(config(tmp_path).headers_file))
    monkeypatch.setenv('COCKPIT_AP_REPOSITORY_ID','8')
    gateway=APGateway(APConfig.load(),Opener({'code':200,'data':DATA}))
    assert gateway.query('analysis',QUERY)==DATA
    request,_=gateway._opener.calls[0]
    assert request.headers['X-ontology-repository-id']=='8'


def test_individual_batch_deduplicates_equal_children_without_losing_positions(tmp_path):
    from dataclasses import replace
    opener=Opener({'success':True,'data':DATA})
    gateway=APGateway(replace(config(tmp_path),batch_mode='individual'),opener)
    result=gateway.query('batch',[QUERY,QUERY,QUERY])
    assert len(result)==3 and len(opener.calls)==1
    result[0]['data']['result']['rows'].clear()
    assert result[1]['data']['result']['rows']


def test_helmet_proxy_preserves_upstream_ywln_config(tmp_path,monkeypatch):
    import bi_agent.cockpit.router as router
    monkeypatch.setenv('COCKPIT_DATA_MODE','ap')
    opportunity={"dimension":[{"identifierCode":"YWLN_D020"}],"measure":[{"identifierCode":"YWLN_M0022"}]}
    quotation={"dimension":[{"identifierCode":"YWLN_D021"}],"measure":[{"identifierCode":"YWLN_M0031"}]}
    helmet={"helmetGlobalConfig":None,"edges":[],"nodes":[
        {"code":"BUSINESS_OPPORTUNITY_ACQUISITION","meta":{"helmetConfig":{
            "dataConfig":json.dumps(opportunity),"statusMappings":[]}}},
        {"code":"QUOTATION","meta":{"helmetConfig":{"dataConfig":json.dumps(quotation)}}}]}
    gateway=APGateway(config(tmp_path),Opener({'success':True,'data':helmet}))
    monkeypatch.setattr(router,'get_gateway',lambda:gateway)
    app=FastAPI();app.include_router(build_cockpit_router(lambda:tmp_path,main_context=lambda c:{}))
    response=TestClient(app).post('/api/cockpit/data/query',json=dict(
        id=1,kind='helmet',payload={'flowCode':'FULL_PROCESS_OPERATIONS_MANAGEMENT'}))
    assert response.status_code==200,response.text
    nodes=response.json()['data']['nodes']
    assert json.loads(nodes[0]['meta']['helmetConfig']['dataConfig'])==opportunity
    assert json.loads(nodes[1]['meta']['helmetConfig']['dataConfig'])==quotation


def test_ap_timeout_supports_three_minute_budget_and_caps_above_it(monkeypatch,tmp_path):
    monkeypatch.setenv('COCKPIT_AP_BASE_URL','http://ap.example/api/gateway2/x360')
    monkeypatch.setenv('COCKPIT_AP_HEADERS_FILE',str(config(tmp_path).headers_file))
    monkeypatch.setenv('COCKPIT_AP_TIMEOUT_SECONDS','180')
    assert APConfig.load().timeout==180
    monkeypatch.setenv('COCKPIT_AP_TIMEOUT_SECONDS','600')
    assert APConfig.load().timeout==240


def test_queue_wait_and_upstream_share_one_deadline(tmp_path):
    """A page waiting for capacity must not then get a full second budget."""
    from dataclasses import replace
    opener=Opener({'success':True,'data':DATA})
    gateway=APGateway(replace(config(tmp_path),timeout=1),opener)
    waits=[]
    class Capacity:
        def acquire(self,timeout=None):waits.append(timeout);return True
        def release(self):pass
    gateway._capacity=Capacity()
    with patch('bi_agent.cockpit.ap_gateway.time.monotonic',side_effect=[0,0.5,0.6,0.7]):
        assert gateway.query('analysis',QUERY)==DATA
    assert waits==[pytest.approx(0.5)]
    assert opener.calls[0][1]==pytest.approx(0.4)
    assert opener.calls[0][1]<1


def test_sql_root_cause_is_kept_for_backend_diagnostics_only(tmp_path):
    message='PreparedStatementCallback; bad SQL grammar ['+('SELECT q.*, '*300)+'] ERROR: column input_time does not exist'
    gateway=APGateway(config(tmp_path),Opener({'success':False,'message':message}))
    with pytest.raises(HTTPException) as failure:
        gateway.query('analysis',QUERY)
    assert failure.value.status_code==502
    assert len(failure.value.detail)<300
    assert 'column input_time does not exist' in failure.value.diagnostic_message


class AggregateSplitOpener:
    def __init__(self):
        self.calls = []

    def open(self, request, timeout):
        payload = json.loads(request.data)
        self.calls.append(payload)
        indicators = (payload.get('analysisConfig') or {}).get('indicators') or []
        if len(indicators) > 1:
            return io.BytesIO(json.dumps({'success': False, 'data': None,
                'msg': '本地查询组合未配置: aggregate'}).encode())
        code = indicators[0]['identifierCode']
        return io.BytesIO(json.dumps({'success': True, 'data': {
            'resultType': 'TABLE',
            'result': {'columns': [{'identifierCode': code, 'label': code, 'type': 'METRIC'}],
                       'rows': [{code: {'value': {'A': 7, 'B': 9}[code]}}]},
            'pagination': {'total': 1, 'pageNum': 1, 'pageSize': 20}}}).encode())


def combination_query(*codes):
    return {'analysisConfig': {
        'dimensions': [{'identifierCode': 'YWLN_D005', 'label': '客户等级'}],
        'indicators': [{'identifierCode': code, 'label': code} for code in codes]},
        'commonConfig': {'filters': {'logic': 'AND', 'children': []},
                         'pagination': {'pageNum': 1, 'pageSize': 10},
                         'sorts': [{'identifierCode': 'A', 'order': 'DESC'}]}}


def test_combination_rejection_splits_by_indicator_and_merges_dimensions(tmp_path):
    opener = SplitOpener()
    gateway = APGateway(config(tmp_path), opener)
    merged = gateway.query('analysis', combination_query('A', 'B', 'C'))
    assert merged['resultType'] == 'TABLE'
    assert [column['identifierCode'] for column in merged['result']['columns']] == ['YWLN_D005', 'A', 'B', 'C']
    rows = {row['YWLN_D005']['value']: row for row in merged['result']['rows']}
    assert {name: {code: row[code]['value'] for code in ('A', 'B', 'C')} for name, row in rows.items()} == {
        '战略客户': {'A': 1, 'B': 10, 'C': 100},
        '重点客户': {'A': 2, 'B': 20, 'C': 200},
        '一般客户': {'A': 3, 'B': 30, 'C': 300}}
    assert [row['YWLN_D005']['value'] for row in merged['result']['rows']] == ['战略客户', '重点客户', '一般客户']
    assert [len((call.get('analysisConfig') or {}).get('indicators') or []) for call in opener.calls] == [3, 1, 1, 1]
    assert merged['pagination'] == {'total': 3, 'pageNum': 1, 'pageSize': 10}


def test_combination_split_merges_aggregate_rows(tmp_path):
    gateway = APGateway(config(tmp_path), AggregateSplitOpener())
    payload = {'analysisConfig': {'dimensions': [], 'indicators': [
        {'identifierCode': 'A'}, {'identifierCode': 'B'}]},
        'commonConfig': {'pagination': {'pageNum': 1, 'pageSize': 20}}}
    merged = gateway.query('analysis', payload)
    assert [column['identifierCode'] for column in merged['result']['columns']] == ['A', 'B']
    assert merged['result']['rows'] == [{'A': {'value': 7}, 'B': {'value': 9}}]


def test_combination_split_never_returns_partial_metrics(tmp_path):
    gateway = APGateway(config(tmp_path), SplitOpener(fail='B'))
    with pytest.raises(HTTPException) as error:
        gateway.query('analysis', combination_query('A', 'B', 'C'))
    assert error.value.status_code == 502
    assert '本地查询组合未配置' in error.value.detail and 'B' in error.value.detail


def test_individual_batch_also_splits_rejected_analysis_combination(tmp_path):
    from dataclasses import replace
    gateway = APGateway(replace(config(tmp_path), batch_mode='individual'), SplitOpener())
    result = gateway.query('batch', [combination_query('A', 'B', 'C')])
    assert result[0]['success'] is True
    assert [column['identifierCode'] for column in result[0]['data']['result']['columns']] == [
        'YWLN_D005', 'A', 'B', 'C']


def test_http_receipt_keeps_original_combination_and_merged_table(tmp_path, monkeypatch):
    import bi_agent.cockpit.router as router
    monkeypatch.setenv('COCKPIT_DATA_MODE', 'ap')
    gateway = APGateway(config(tmp_path), SplitOpener())
    monkeypatch.setattr(router, 'get_gateway', lambda: gateway)
    app = FastAPI(); app.include_router(build_cockpit_router(lambda: tmp_path, main_context=lambda c: {}))
    client = TestClient(app)
    payload = combination_query('A', 'B', 'C')
    body = client.post('/api/cockpit/data/query', json=dict(id=1, kind='analysis', payload=payload)).json()
    assert [column['identifierCode'] for column in body['data']['result']['columns']] == ['YWLN_D005', 'A', 'B', 'C']
    store = Store(tmp_path / 'dataset' / 'cockpit' / 'history.sqlite3')
    fingerprint, selected = receipt_material(
        dict(id=1, apReceiptIds=[body['receiptId']], chartQueries=[json.dumps(payload)]), store)
    assert fingerprint
    assert [column['identifierCode'] for column in next(iter(selected.values()))['response']['result']['columns']] == [
        'YWLN_D005', 'A', 'B', 'C']
