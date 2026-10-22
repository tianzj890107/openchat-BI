"""POC acceptance contracts: reconciliation, scope, evidence, cancellation and task flow."""
import threading
import time
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from bi_agent.cockpit.data import DemoSource, DEPARTMENTS, PERIODS
from bi_agent.cockpit.agent import run_analysis, validate_result
from bi_agent.cockpit.router import build_cockpit_router
from bi_agent.cockpit.store import Store


def valid_result(e):
    return dict(summary="当前演示记录显示交付卡点，需要逐单核实。",causes=[dict(id="c1",title="处理记录未闭环",description="处理记录支持存在卡点。",status="supported",evidenceIds=[e['records'][0]['id']])],recommendations=[dict(id="r1",causeIds=["c1"],action="核实处理记录并确认完成日期",ownerRole="运营负责人",acceptance="提供逐单关闭证据")],limitations=["演示数据"])

@pytest.mark.parametrize('period',PERIODS)
@pytest.mark.parametrize('department',DEPARTMENTS)
def test_snapshot_reconciles_across_scope(period,department):
    s=DemoSource().snapshot(period,department);m=s['metrics']
    assert m['overdue']==pytest.approx(sum(r['amount'] for r in s['rows']))
    assert m['backlog']==pytest.approx(m['overdue']+m['normal'])
    assert m['orders']==pytest.approx(m['actual']+m['backlog'])
    assert sum(c['amount'] for c in s['causes'])==pytest.approx(m['overdue'])
    assert sum(x['actual'] or 0 for x in s['monthly'])==pytest.approx(m['actual'])
    assert sum(x['actual'] for x in s['departments'])==pytest.approx(m['actual'])
    if department!=DEPARTMENTS[0]:assert all(r['department']==department for r in s['rows'])

def test_stages_do_not_reuse_shipping_causes():
    src=DemoSource();s=src.snapshot()
    for stage in ['bid','quotation','order','technical','guidance','opportunity']:
        e=src.evidence(s,stage)
        assert e['causes']==[]
        assert all(not r['id'].startswith('SO-') for r in e['records'])
        if stage!='order':assert all(r['amount'] is None for r in e['records'])

def test_evidence_gate_rejects_invented_or_unread_reference():
    src=DemoSource();e=src.evidence(src.snapshot(),'shipment');r=valid_result(e)
    with pytest.raises(ValueError):validate_result(r,e,set())
    r['causes'][0]['evidenceIds']=['invented']
    with pytest.raises(ValueError):validate_result(r,e,{'invented'})

def test_aggregate_cannot_prove_cause():
    src=DemoSource();e=src.evidence(src.snapshot(),'shipment');r=valid_result(e)
    r['causes'][0]['evidenceIds']=[e['facts'][0]['id']]
    with pytest.raises(ValueError):validate_result(r,e,{e['facts'][0]['id']})

def test_agent_really_calls_evidence_tool_before_completion():
    src=DemoSource();e=src.evidence(src.snapshot(),'shipment');calls=[]
    def provider(*args,**kwargs):
        calls.append(args)
        if len(calls)==1:yield dict(type='tool_use_end',id='t1',name='CockpitEvidenceQuery',input={'section':'all'})
        else:
            import json
            yield dict(type='text_delta',text=json.dumps(valid_result(e)))
    result,events=run_analysis(e,{},threading.Event(),lambda *a:None,provider)
    assert len(calls)==2 and events[0]['evidenceCount']>0
    assert '全部证据为 POC 演示记录' in result['limitations']

def test_agent_provider_failure_is_not_demo_success():
    src=DemoSource();e=src.evidence(src.snapshot(),'shipment')
    def provider(*args,**kwargs):yield {'type':'error','error':'no key'}
    with pytest.raises(RuntimeError):run_analysis(e,{},threading.Event(),lambda *a:None,provider)

def client(tmp_path, runner=None):
    app=FastAPI()
    if runner is None:runner=lambda e,c,stop,p:(valid_result(e),[dict(tool='CockpitEvidenceQuery',section='all',evidenceCount=len(e['evidence']))])
    app.include_router(build_cockpit_router(lambda:str(tmp_path),runner))
    return TestClient(app)

def wait(c,aid):
    for _ in range(100):
        a=c.get('/api/cockpit/analyses/'+aid).json()
        if a['status'] not in {'queued','running'}:return a
        time.sleep(.01)
    raise AssertionError('analysis did not finish')

def test_analysis_cache_is_scoped_and_tasks_are_idempotent(tmp_path):
    c=client(tmp_path);ctx={'stage':'shipment','id':1}
    a=wait(c,c.post('/api/cockpit/analyses',json=ctx).json()['id'])
    assert a['status']=='completed'
    assert c.post('/api/cockpit/analyses',json=ctx).json()['id']==a['id']
    b=c.post('/api/cockpit/analyses',json={**ctx,'department':'AIDC产品部'}).json()
    assert b['id']!=a['id']
    tid=c.post('/api/cockpit/analyses/'+a['id']+'/draft').json()['id']
    assert c.post('/api/cockpit/analyses/'+a['id']+'/draft').json()['id']==tid
    assert c.get('/api/cockpit/analyses/'+a['id']+'/report').status_code==200


def test_bootstrap_uses_single_numeric_id_identity(tmp_path):
    c=client(tmp_path);boot=c.get('/api/cockpit/bootstrap').json()
    assert boot['identityParameter']=='id'
    assert [role['id'] for role in boot['roles']]==[1,2]
    assert [role['name'] for role in boot['roles']]==['总裁','分析员']

def test_task_state_and_revision_guards_are_identity_neutral(tmp_path):
    c=client(tmp_path);a=wait(c,c.post('/api/cockpit/analyses',json={}).json()['id'])
    t=c.post('/api/cockpit/analyses/'+a['id']+'/draft').json();url='/api/cockpit/tasks/'+t['id']
    assert c.post(url,json=dict(id=2,revision=1,action='close',feedback='ok')).status_code==409
    t=c.post(url,json=dict(id=2,revision=1,action='issue')).json();assert t['status']=='issued'
    assert c.post(url,json=dict(id=1,revision=1,action='issue')).status_code==409
    t=c.post(url,json=dict(id=1,revision=t['revision'],action='accept')).json()
    assert c.post(url,json=dict(id=1,revision=t['revision'],action='feedback')).status_code==409
    t=c.post(url,json=dict(id=1,revision=t['revision'],action='feedback',feedback='演示证据已补充')).json()
    t=c.post(url,json=dict(id=2,revision=t['revision'],action='close',feedback='模拟验收通过')).json()
    assert t['status']=='closed' and t['simulated'] and len(t['audit'])==5

def test_cancelled_job_cannot_be_overwritten(tmp_path):
    started=threading.Event();release=threading.Event()
    def runner(e,c,stop,p):started.set();release.wait(2);return valid_result(e),[]
    c=client(tmp_path,runner);a=c.post('/api/cockpit/analyses',json={}).json();assert started.wait(1)
    assert c.post('/api/cockpit/analyses/'+a['id']+'/cancel').json()['status']=='cancelled'
    release.set();time.sleep(.05)
    assert c.get('/api/cockpit/analyses/'+a['id']).json()['status']=='cancelled'

def test_invalid_scope_and_missing_analysis(tmp_path):
    c=client(tmp_path)
    assert c.get('/api/cockpit/snapshot?period=2026-01').status_code==422
    assert c.post('/api/cockpit/analyses',json={'stage':'unknown'}).status_code==422
    assert c.get('/api/cockpit/analyses/missing').status_code==404

def test_restart_preserves_history_and_marks_interrupted(tmp_path):
    path=tmp_path/'history.sqlite3';s=Store(path);a=s.create_analysis('scope',{})
    s.recover();assert s.get_analysis(a['id'])['status']=='interrupted'
    assert Store(path).get_analysis(a['id']) is not None

@pytest.mark.parametrize('period',PERIODS)
def test_monthly_targets_forecasts_and_quotation_counts_reconcile(period):
    src=DemoSource();s=src.snapshot(period)
    assert sum(x['target'] for x in s['monthly'])==pytest.approx(s['metrics']['target'])
    assert sum((x['actual'] or 0)+(x['forecast'] or 0) for x in s['monthly'])==pytest.approx(s['metrics']['forecast'])
    e=src.evidence(s,'quotation')
    risk=next(x for x in s['risks'] if x['id']=='quotation')
    assert risk['metric']==len(e['records'])
    assert sum(x['value'] for x in e['facts'] if ':product:' in x['id'])==risk['metric']


def test_cockpit_page_uses_separate_assets_and_subpath(monkeypatch,tmp_path):
    from bi_agent.web import app as module
    monkeypatch.setattr(module,'APP_ROOT_PATH','/gateway/analytics')
    monkeypatch.setattr(module.STATE,'cwd',str(tmp_path))
    c=TestClient(module.app)
    redirect=c.get('/cockpit?id=2&metric=sales',follow_redirects=False)
    assert redirect.status_code==307
    assert redirect.headers['location']=='/gateway/analytics/cockpit/overview?id=2&metric=sales'
    for page in ['home','overview','operations','analysis']:
        pages=[c.get(f'/cockpit/{page}?id={identity}') for identity in (1,2)]
        assert all(response.status_code==200 for response in pages)
        assert pages[0].text==pages[1].text
        for response in pages:
            assert f'<meta name="cockpit-page" content="{page}">' in response.text
            assert '/gateway/analytics/static/cockpit/cockpit.js' in response.text
            assert '@@APP_ROOT_PATH@@' not in response.text
            assert '@@COCKPIT_PAGE@@' not in response.text
            assert 'class="rail"' not in response.text
            assert 'class="topbar"' not in response.text
            assert 'class="filterbar"' not in response.text
            assert 'class="page-heading"' not in response.text
    assert c.get('/static/cockpit/vendor/pro-bi-ui.min.js').status_code==200
    assert c.get('/static/cockpit/metadata/runtime.json').status_code==200
    assert c.get('/static/cockpit/layout/views.json').status_code==404
    assert c.get('/cockpit/not-a-page').status_code==404
    assert c.get('/api/cockpit/bootstrap').json()['supportsLiveSource'] is False


def test_failed_analysis_cannot_create_task_or_report(tmp_path):
    def runner(*args):raise RuntimeError('模型服务调用失败')
    c=client(tmp_path,runner);a=wait(c,c.post('/api/cockpit/analyses',json={}).json()['id'])
    assert a['status']=='failed' and a['result'] is None
    assert c.post('/api/cockpit/analyses/'+a['id']+'/draft').status_code==409
    assert c.get('/api/cockpit/analyses/'+a['id']+'/report').status_code==409


def test_tool_window_is_bounded_and_covers_entire_quotation_list():
    import json
    src=DemoSource();e=src.evidence(src.snapshot(),'quotation');seen=[]
    def provider(messages,*args,**kwargs):
        if not seen:
            seen.append(True)
            yield dict(type='tool_use_end',id='t1',name='CockpitEvidenceQuery',input={'section':'all'})
        else:
            tool=json.loads(messages[-1]['content'][0]['content'])
            assert len(tool['records'])==24
            assert tool['records'][0]['id']==e['records'][0]['id']
            assert tool['records'][-1]['id']==e['records'][-1]['id']
            assert len({r['department'] for r in tool['records']})==3
            out=valid_result(e)
            yield dict(type='text_delta',text=json.dumps(out))
    result,_=run_analysis(e,{},threading.Event(),lambda *a:None,provider)
    assert result['summary']


def test_scoped_history_survives_new_router_instance(tmp_path):
    c=client(tmp_path);a=wait(c,c.post('/api/cockpit/analyses',json={'id':2}).json()['id'])
    c2=client(tmp_path)
    assert c2.get('/api/cockpit/analyses/'+a['id']).json()['status']=='completed'
    assert c2.get('/api/cockpit/analyses?id=1').json()==[]
    assert c2.get('/api/cockpit/analyses?id=2').json()[0]['id']==a['id']
    assert c2.post('/api/cockpit/analyses',json={'role':'president'}).status_code==422
