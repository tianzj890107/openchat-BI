import json
import threading
from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bi_agent.cockpit.frozen import FrozenAnnualStore, FrozenAnnualService, FrozenCockpitSurface, STAGES


def fixture(tmp_path):
    body={'period':'2026','createdAt':1,'basis':'test annual evidence','items':{}}
    for stage in STAGES:
        body['items'][stage]={'id':stage,'status':'limited','updatedAt':1,
            'context':{'stage':stage,'period':'2026','id':1},
            'result':{'cardContract':'cockpit-cards-v1','summary':'年度分析结果',
                      'causes':[],'recommendations':[],'limitations':['测试证据范围有限']},
            'evidence':{'facts':[],'records':[]}}
    seed=tmp_path/'seed.json';seed.write_text(json.dumps(body))
    return FrozenAnnualStore(tmp_path/'release.db',seed),seed,body


def test_first_open_all_roles_and_scopes_never_recompute(tmp_path):
    store,_,_=fixture(tmp_path);calls=[]
    service=FrozenAnnualService(store,lambda period:calls.append(period))
    client=TestClient(FrozenCockpitSurface(FastAPI(),service))
    version=store.read()['version']
    for role in (1,2):
        for scope in ('default','month-filter'):
            data=client.get('/api/cockpit/ai-publications',params={'id':role,'uiScope':scope}).json()
            assert (data['readyCount'],data['missingCount'],data['updatingCount'])==(15,0,0)
            assert data['version']==version
            assert data['appliesToPageFilters'] is False
    for endpoint in ('analyses','analyses/refresh','publications/refresh','stages/order/preheat'):
        assert client.post('/api/cockpit/'+endpoint,json={'stage':'order'}).status_code==200
    assert calls==[]


def test_atomic_manual_refresh_dedup_and_failure_retains_published(tmp_path):
    store,seed,body=fixture(tmp_path);started=threading.Event();finish=threading.Event();done=threading.Event()
    old=store.read()['version'];calls=[]
    def recompute(period):
        calls.append(period);started.set();finish.wait(5)
        candidate=deepcopy(body);candidate['createdAt']=2
        return candidate
    original_finish=store.finish
    def mark(*args):original_finish(*args);done.set()
    store.finish=mark
    service=FrozenAnnualService(store,recompute)
    assert service.refresh()['queued'];assert started.wait(2)
    assert not service.refresh()['queued'];assert store.read()['version']==old
    finish.set();assert done.wait(2)
    assert calls==['2026'];assert store.read()['version']!=old
    new=store.read()['version']
    # A restart imports no older seed over a successful manual publication.
    assert FrozenAnnualStore(store.path,seed).read()['version']==new
    done.clear();service.recompute=lambda p: {'period':p,'items':{}}
    service.refresh();assert done.wait(2)
    assert store.job()['status']=='failed';assert store.read()['version']==new


def test_startup_and_html_same_release_with_compression(tmp_path):
    from starlette.middleware.gzip import GZipMiddleware
    from starlette.responses import HTMLResponse
    store,_,_=fixture(tmp_path);app=FastAPI();app.add_middleware(GZipMiddleware,minimum_size=1)
    @app.get('/cockpit/analysis')
    def page():return HTMLResponse('<html><head></head><body>test</body></html>')
    @app.get('/api/cockpit/startup')
    def startup():return {'cards':{},'cardsByPage':{}}
    client=TestClient(FrozenCockpitSurface(app,FrozenAnnualService(store)))
    assert 'COCKPIT_FIXED_ANNUAL=true' in client.get('/cockpit/analysis').text
    data=client.get('/api/cockpit/startup?page=analysis').json()
    assert data['cards'] and data['cardsVersion']==store.read()['version']


def test_risk_shortlist_limits_display_without_rewriting_analysis(tmp_path, monkeypatch):
    store,_,_=fixture(tmp_path);version=store.read()['version']
    monkeypatch.setattr('bi_agent.cockpit.frozen.summarize_risk_counts', lambda slots: {
        domain: {'count':10,'findings':[{'id':str(i),'title':'风险'+str(i)} for i in range(10)]}
        for domain in ('sales','shipment')})
    result=FrozenAnnualService(store).envelope(1)
    for domain in ('sales','shipment'):
        assert result['riskCounts'][domain]['count']==3
        assert result['riskCounts'][domain]['totalCount']==10
        assert len(result['riskCounts'][domain]['findings'])==3
    assert store.read()['version']==version


def test_manual_refresh_uses_public_query_data_envelope(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from bi_agent.cockpit.frozen import recompute_from_router
    app=FastAPI()
    expected={"rows":[{"value":17}]}
    @app.post('/api/cockpit/data/query')
    def query():
        return dict(data=expected,receiptId='query-receipt',receivedAt=1,expiresAt=100)
    captured={}
    class Manager:
        def __init__(self,store,config,query,start,**kwargs):
            captured['query']=query
    monkeypatch.setattr('bi_agent.cockpit.refresh.RefreshManager',Manager)
    monkeypatch.setattr('bi_agent.cockpit.ap_gateway.get_gateway',lambda:SimpleNamespace(config=object()))
    recompute_from_router(app,tmp_path)
    assert captured['query'](1,'analysis',{'analysisConfig':{}})==expected


def test_priority_incremental_publication_and_failure_isolation(tmp_path):
    store,_,body=fixture(tmp_path)
    entered=threading.Event();release=threading.Event();second=threading.Event();finish_second=threading.Event();done=threading.Event()
    calls=[]
    class Runner:
        def run_stage(self,period,stage):
            calls.append(stage)
            if len(calls)==1:
                entered.set();assert release.wait(5)
            if len(calls)==2:
                second.set();assert finish_second.wait(5)
            if stage=='order':raise RuntimeError('stage source unavailable')
            item=deepcopy(body['items'][stage]);item['updatedAt']=2
            return item
    original_finish=store.finish
    def finished(*args):original_finish(*args);done.set()
    store.finish=finished
    service=FrozenAnnualService(store,Runner())
    client=TestClient(FrozenCockpitSurface(FastAPI(),service))
    r=client.post('/api/cockpit/publications/refresh',json={'manual':True,'slotId':'shipment-risk-summary','page':'analysis','visibleSlots':['opportunity-risk']})
    assert r.status_code==200 and entered.wait(2)
    assert calls==['shipment']
    # Reprioritize an existing job; never start a competing model execution.
    response=client.post('/api/cockpit/publications/priority',json={'slotId':'quote-summary','page':'operations'})
    assert response.status_code==200
    release.set();assert second.wait(2)
    current=store.read()
    assert current['items']['shipment']['updatedAt']==2
    assert current['items']['quotation']['updatedAt']==1
    assert calls==['shipment','quotation']
    assert service.envelope(1)['readyCount']==15
    finish_second.set();assert done.wait(3)
    current=store.read()
    assert current['items']['order']['updatedAt']==1
    assert current['items']['bid']['updatedAt']==2
    assert len(calls)==len(set(calls))==6
    assert store.job()['status']=='partial'
    failure=store.job()['failedStages'][0]
    assert failure['stage']=='order' and failure['code']=='RuntimeError'
    from bi_agent.cockpit.store import Store
    assert Store(store.path.parent/'history.sqlite3').list_diagnostics()[0]['diagnosticId']==failure['diagnosticId']


def test_manual_card_refresh_requeues_a_completed_stage_in_the_running_round(tmp_path):
    store,_,_=fixture(tmp_path)
    service=FrozenAnnualService(store,lambda period:None)
    assert store.claim()
    service.pending=['shipment','combined']
    service.completed=['opportunity']
    service.active='shipment'
    service.phase='analysing'
    service._progress()

    client=TestClient(FrozenCockpitSurface(FastAPI(),service))
    response=client.post('/api/cockpit/publications/refresh',json={
        'manual':True,'slotId':'opportunity-risk','page':'analysis'}).json()

    assert response['queued'] is False and response['status']=='running'
    assert service.pending[0]=='opportunity'
    assert 'opportunity' not in service.completed
    assert response['manualUpdate']['pendingStages'][0]=='opportunity'
    assert response['manualUpdate']['activeStage']=='shipment'

    service.active='opportunity'
    service.pending=['shipment']
    service._progress()
    service.refresh('opportunity-risk','analysis')
    assert service.pending.count('opportunity')==0


def test_independent_combined_failure_does_not_retry_or_block_other_stages(tmp_path):
    store,_,body=fixture(tmp_path);calls=[];done=threading.Event()
    class Runner:
        def run_stage(self,period,stage):
            calls.append(stage)
            if stage=='combined':raise RuntimeError('No independent evidence available')
            item=deepcopy(body['items'][stage]);item['updatedAt']=3;return item
    original=store.finish
    def finished(*args):original(*args);done.set()
    store.finish=finished
    service=FrozenAnnualService(store,Runner())
    service.refresh('sales-shipment-issues','analysis')
    assert done.wait(3)
    assert calls[0]=='combined' and calls.count('combined')==1
    assert store.job()['status']=='partial'
    assert store.read()['items']['combined']['updatedAt']==1
    assert store.read()['items']['opportunity']['updatedAt']==3


def test_visibility_updates_and_page_reads_cannot_start_analysis(tmp_path):
    store,_,_=fixture(tmp_path);calls=[]
    service=FrozenAnnualService(store,lambda period:calls.append(period))
    client=TestClient(FrozenCockpitSurface(FastAPI(),service))
    assert client.post('/api/cockpit/publications/priority',json={'slotId':'quote-summary'}).status_code==200
    assert client.post('/api/cockpit/publications/priority',json={'visibleSlots':['unknown']}).status_code==422
    assert client.get('/api/cockpit/ai-publications').status_code==200
    assert calls==[] and store.job()['status']=='idle'


def test_combined_priority_can_overtake_other_stage_tasks(tmp_path):
    store,_,_=fixture(tmp_path);service=FrozenAnnualService(store,lambda p:None)
    store.claim()
    service.pending=['opportunity','order','combined']
    service.prioritize('sales-shipment-issues','analysis')
    assert service.pending==['combined','opportunity','order']
    assert service.store.job()['pendingStages']==service.pending
    client=TestClient(FrozenCockpitSurface(FastAPI(),service))
    assert client.post('/api/cockpit/publications/priority',json={'visibleSlots':[{}]}).status_code==422


def test_legacy_cached_helper_can_limit_its_saved_input_set(monkeypatch):
    from types import SimpleNamespace
    from bi_agent.cockpit.refresh import RefreshManager
    cards={stage:{'id':stage} for stage in ('opportunity','order','shipment')}
    monkeypatch.setattr('bi_agent.cockpit.combined.published_period_stage_cards',lambda *a,**k:cards)
    manager=RefreshManager(None,SimpleNamespace(identity=lambda:'test'),None,None)
    assert manager._period_stage_cards(1,'2026')==cards
    manager.combined_fresh_stages={'order','opportunity'}
    assert set(manager._period_stage_cards(1,'2026'))=={'order','opportunity'}


def test_fixed_annual_ignores_legacy_whole_page_publication(tmp_path):
    store,_,_=fixture(tmp_path)
    service=FrozenAnnualService(store,lambda p:None)
    before=store.read()['version']
    client=TestClient(FrozenCockpitSurface(FastAPI(),service))
    response=client.post('/api/cockpit/page',json={'id':1,'page':'analysis','analysisIds':{}})
    assert response.status_code==200 and response.json()['skipped'] is True
    assert response.json()['accepted'] is False
    assert store.read()['version']==before and store.job()['status']=='idle'


def test_manifest_is_lightweight_and_stages_have_conditional_versions(tmp_path):
    store,_,body=fixture(tmp_path)
    for item in body['items'].values():
        item['evidence']['facts']=[{'id':str(n),'label':'test','value':n,'claim':{'statement':'proof'*100}} for n in range(100)]
        item['evidence']['evidence']=[{'id':str(n),'definition':'proof'*100} for n in range(100)]
    store.publish(body)
    service=FrozenAnnualService(store)
    client=TestClient(FrozenCockpitSurface(FastAPI(),service))
    full=client.get('/api/cockpit/ai-publications?id=1')
    manifest=client.get('/api/cockpit/ai-publications?id=1&format=manifest')
    assert len(manifest.content)<len(full.content)/10
    value=manifest.json()
    assert value['transport']=='stage-manifest-v1'
    assert all('payload' not in slot and 'lastSuccessfulPublication' not in slot for slot in value['slots'].values())
    stage=client.get('/api/cockpit/ai-publications/stages/shipment?id=1')
    assert stage.json()['evidence']['facts'][0]['value']==0
    assert all('evidence' not in slot['payload'] for slot in stage.json()['slots'].values())
    assert client.get('/api/cockpit/ai-publications/stages/shipment?id=1',headers={'If-None-Match':stage.headers['etag']}).status_code==304
    item=deepcopy(body['items']['order']);item['updatedAt']=5
    store.publish_stage('order',item)
    updated=client.get('/api/cockpit/ai-publications?id=1&format=manifest').json()
    assert updated['stageVersions']['shipment']==value['stageVersions']['shipment']
    assert updated['stageVersions']['order']!=value['stageVersions']['order']


def test_combined_can_run_first_without_other_successes_and_empty_result_retains_old(tmp_path):
    store,_,body=fixture(tmp_path);calls=[];done=threading.Event()
    class Runner:
        def run_stage(self,period,stage):
            calls.append(stage)
            item=deepcopy(body['items'][stage]);item['updatedAt']=10
            if stage=='quotation':item['execution']={'stopReason':'stage_no_evidence'}
            return item
    original=store.finish
    def finish(*args):original(*args);done.set()
    store.finish=finish
    service=FrozenAnnualService(store,Runner())
    service.refresh('sales-shipment-issues','analysis')
    assert done.wait(3)
    assert calls[0]=='combined' and calls.count('combined')==1
    assert store.read()['items']['combined']['updatedAt']==10
    assert store.read()['items']['quotation']['updatedAt']==1
    assert 'quotation' not in store.job()['completedStages']
    assert store.job()['failedStages'][0]['stage']=='quotation'
    assert store.job()['heartbeatAt']>0


def test_full_evidence_is_read_on_demand_and_old_analysis_is_not_mislabelled(tmp_path):
    store,_,body=fixture(tmp_path)
    body['items']['combined']['evidence']['facts']=[{'id':'proof','label':'amount','value':42,'claim':{'statement':'full original proof'}}]
    store.publish(body)
    service=FrozenAnnualService(store)
    client=TestClient(FrozenCockpitSurface(FastAPI(),service))
    path='/api/cockpit/ai-publications/stages/combined/evidence?id=1&analysisId=combined'
    response=client.get(path)
    assert response.status_code==200
    assert response.json()['evidence']['facts'][0]['claim']['statement']=='full original proof'
    assert client.get(path.replace('analysisId=combined','analysisId=outdated')).status_code==409
    assert store.job()['status']=='idle'
