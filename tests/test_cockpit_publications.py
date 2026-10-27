"""A last successful publication survives restarts, refresh failures and new receipts."""
import json
import threading
import time
from fastapi import FastAPI
from fastapi.testclient import TestClient
from bi_agent.cockpit.cards import CONTRACT
from bi_agent.cockpit.router import build_cockpit_router
from bi_agent.cockpit.publications import publication_scope
from bi_agent.cockpit.dashboard_source import RELEASE
from bi_agent.cockpit.store import Store


def request(**changes):
    return dict(id=1,engine='main',source='service',page='analysis',defaultView=True,stage='shipment',chartSnapshotId=RELEASE,
        chartQueries=['{"analysisConfig":{"indicators":[{"identifierCode":"M0001"}]}}'],**changes)


def test_persistent_refresh_keeps_last_result_and_isolates_filters(tmp_path,monkeypatch):
    monkeypatch.setenv('COCKPIT_DATA_MODE','snapshot')
    hold=threading.Event();calls=[];revision=['A'];fail=[False]
    def main(c,stop,progress):
        calls.append(c)
        if len(calls)>1:hold.wait(3)
        if fail[0]:raise RuntimeError('AP分析暂时失败')
        return dict(summary='完整卡片'+revision[0],causes=[],recommendations=[],limitations=['待核实'],cardContract=CONTRACT,_status='limited'),[]
    def app():
        result=FastAPI();result.include_router(build_cockpit_router(lambda:tmp_path,main_runner=main,
            main_context=lambda r:dict(snapshotId='dashboard-'+revision[0],dataIdentity=RELEASE,dataFingerprint=revision[0])))
        return TestClient(result)
    client=app()
    first=client.post('/api/cockpit/analyses/refresh',json=request()).json()
    assert first['cached'] is None and first['analysis']['id']
    for _ in range(100):
        saved=client.get('/api/cockpit/analyses/published?id=1&engine=main&page=analysis').json()['items']
        if saved:break
        time.sleep(.01)
    assert saved['shipment']['result']['summary']=='完整卡片A'
    again=client.post('/api/cockpit/analyses/refresh',json=request()).json()
    assert again['analysis'] is None and again['cached']['id']==first['analysis']['id'] and len(calls)==1
    # Recreated router models a server restart: only SQLite survives.
    assert app().get('/api/cockpit/analyses/published?id=1&engine=main&page=analysis').json()['items']['shipment']['id']==first['analysis']['id']
    revision[0]='B';fail[0]=True
    second=client.post('/api/cockpit/analyses/refresh',json=request()).json()
    duplicate=client.post('/api/cockpit/analyses/refresh',json=request()).json()
    assert second['cached']['id']==first['analysis']['id']
    assert duplicate['analysis']['id']==second['analysis']['id']
    assert client.get('/api/cockpit/analyses/published?id=1&page=analysis').json()['items']['shipment']['id']==first['analysis']['id']
    # Changing dimension creates a cache miss; it cannot show the old filter's content.
    changed=request();changed.update(defaultView=False,chartQueries=['{"analysisConfig":{"indicators":[{"identifierCode":"M0001"}]},"commonConfig":{"filters":{"department":"B"}}}'])
    new_filter=client.post('/api/cockpit/analyses/refresh',json=changed).json()
    assert new_filter['cached'] is None
    hold.set()
    for _ in range(100):
        if client.get('/api/cockpit/analyses/'+second['analysis']['id']).json()['status']=='failed':break
        time.sleep(.01)
    assert client.get('/api/cockpit/analyses/published?id=1&page=analysis').json()['items']['shipment']['id']==first['analysis']['id']
    assert client.get('/api/cockpit/analyses/published?id=2&page=analysis').json()['items']=={}
    assert client.get('/api/cockpit/analyses/published?id=1&page=operations').json()['items']=={}


def test_scope_ignores_transport_receipts_but_keeps_source_and_actual_filters():
    c=request();c['dataIdentity']='source-A'
    key=publication_scope(c)
    assert publication_scope(dict(c,apReceiptIds=['new'],snapshotId='different-response',defaultView=False))==key
    assert publication_scope(dict(c,dataIdentity='source-B'))!=key
    assert publication_scope(dict(c,id=2))!=key
    assert publication_scope(dict(c,clarifications={'answer':'已确认'}))!=key
    assert publication_scope(dict(c,chartQueries=['{"otherFilter":"B"}']))!=key


def test_incomplete_or_older_task_cannot_replace_last_success(tmp_path):
    store=Store(tmp_path/'history.sqlite3')
    a=store.create_analysis('scope',{});b=store.create_analysis('scope',{})
    store.update_analysis(b['id'],status='limited',result=dict(cardContract=CONTRACT))
    assert store.publish(b['id'])
    store.update_analysis(a['id'],status='limited',result=dict(cardContract=CONTRACT))
    store.publish(a['id']);assert store.published('scope')['id']==b['id']
    bad=store.create_analysis('scope',{});store.update_analysis(bad['id'],status='completed',result=dict(summary='没有卡片契约'))
    assert store.publish(bad['id']) is False
    assert store.published('scope')['id']==b['id']


def test_failed_cancelled_and_incomplete_jobs_never_publish(tmp_path):
    store=Store(tmp_path/'history.sqlite3')
    for status in ['failed','cancelled','needs_input','interrupted']:
        item=store.create_analysis('scope',{})
        store.update_analysis(item['id'],status=status,result=dict(cardContract=CONTRACT))
        assert not store.publish(item['id'])
    assert store.published('scope') is None
