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
