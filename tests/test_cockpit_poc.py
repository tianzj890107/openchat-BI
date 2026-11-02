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
    return dict(summary="当前演示记录显示交付卡点，需要逐单核实。",causes=[dict(id="c1",title="处理记录未闭环",description="处理记录支持存在卡点。",status="supported",evidenceIds=[e['records'][0]['id']])],recommendations=[dict(id="r1",causeIds=["c1"],action="核实处理记录并确认完成日期",ownerRole="运营负责人",deadlineDays=5,acceptance="提供逐单关闭证据",detail="按记录逐单核实责任人与承诺日期。")],limitations=["演示数据"])

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


def test_compact_result_contract_requires_short_action_and_deadline():
    src=DemoSource();e=src.evidence(src.snapshot(),'shipment');seen={e['records'][0]['id']}
    r=valid_result(e);r['recommendations'][0]['action']='过长建议'*41
    with pytest.raises(ValueError):validate_result(r,e,seen)
    r=valid_result(e);r['recommendations'][0].pop('deadlineDays')
    with pytest.raises(ValueError):validate_result(r,e,seen)
    r=valid_result(e);r['summary']='过长摘要'*201
    with pytest.raises(ValueError):validate_result(r,e,seen)

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
    assert t['measures'][0]['deadline']=='建议期限：5 个工作日（待确认）'
    assert '待确认' in t['measures'][0]['owner']
    assert t['measures'][0]['action'].startswith('建议：')
    assert c.post(url,json=dict(id=2,revision=1,action='close',feedback='ok')).status_code==409
    t=c.post(url,json=dict(id=2,revision=1,action='save',title='测试任务令',goal='完成核查',
        measures=[dict(id=t['measures'][0]['id'],action=t['measures'][0]['action'],
                       owner='运营负责人',deadline='3 个工作日',acceptance='提交核查清单',
                       ownerConfirmed=True,deadlineConfirmed=True)])).json()
    t=c.post(url,json=dict(id=2,revision=t['revision'],action='issue')).json();assert t['status']=='issued'
    assert c.post(url,json=dict(id=1,revision=t['revision'],action='issue')).status_code==409
    t=c.post(url,json=dict(id=1,revision=t['revision'],action='accept')).json()
    assert c.post(url,json=dict(id=1,revision=t['revision'],action='feedback')).status_code==409
    t=c.post(url,json=dict(id=1,revision=t['revision'],action='feedback',feedback='演示证据已补充')).json()
    t=c.post(url,json=dict(id=2,revision=t['revision'],action='close',feedback='模拟验收通过')).json()
    assert t['status']=='closed' and t['simulated'] and len(t['audit'])==6


def test_task_draft_accepts_legacy_analysis_without_deadline_days(tmp_path):
    store=Store(tmp_path/'history.sqlite3')
    analysis=store.create_analysis('legacy',{'stageName':'发货'})
    analysis=store.update_analysis(analysis['id'],status='completed',result=dict(recommendations=[dict(
        id='r1',action='核实超期订单',ownerRole='运营负责人',acceptance='完成逐单核实')]))
    task=store.draft(analysis)
    assert task['measures'][0]['deadline']=='建议期限：10 个工作日（待确认）'
    assert '待确认' in task['measures'][0]['owner']
    assert task['measures'][0]['action'].startswith('建议：')


def test_task_draft_can_start_from_a_limited_analysis(tmp_path):
    store=Store(tmp_path/'dataset'/'cockpit'/'history.sqlite3')
    analysis=store.create_analysis('limited-task',{'id':1,'stageName':'发货'})
    analysis=store.update_analysis(analysis['id'],status='limited',result=dict(
        summary='证据范围有限，但仍有可执行措施。',
        causes=[dict(id='c1',title='处理记录未闭环',description='记录显示仍有未关闭事项。',status='supported',evidenceIds=['q1'])],
        recommendations=[dict(id='r1',causeIds=['c1'],action='核实超期订单',ownerRole='运营负责人',deadlineDays=3,acceptance='提供逐单关闭证据')],
        limitations=['缺少部分金额明细']))
    app=FastAPI();app.include_router(build_cockpit_router(lambda:str(tmp_path)))
    c=TestClient(app)
    task=c.post('/api/cockpit/analyses/'+analysis['id']+'/draft')
    assert task.status_code==200, task.text
    assert task.json()['analysisId']==analysis['id']


def test_task_dispatch_uses_server_recipient_and_only_issues_after_full_success(tmp_path,monkeypatch):
    monkeypatch.delenv('COCKPIT_TASK_ORDER_RECIPIENTS',raising=False)
    calls=[]
    def runner(evidence,context,stop,progress):
        return valid_result(evidence),[dict(tool='CockpitEvidenceQuery',section='all',evidenceCount=len(evidence['evidence']))]
    def dispatcher(*,actions,recipients,identity):
        calls.append(dict(actions=actions,recipients=recipients,identity=identity))
        return [dict(accepted=True,status='ok',message='已提交',actionId=item['id']) for item in actions]
    app=FastAPI();app.include_router(build_cockpit_router(lambda:str(tmp_path),
        runner=runner,task_dispatcher=dispatcher))
    c=TestClient(app)
    a=wait(c,c.post('/api/cockpit/analyses',json={'id':1,'stage':'shipment'}).json()['id'])
    task=c.post('/api/cockpit/analyses/'+a['id']+'/draft').json()
    task_id=task['id']
    edited=c.post('/api/cockpit/tasks/'+task_id,json=dict(
        id=1,revision=task['revision'],action='save',title='发货超期订单处置',
        goal='在期限内关闭可验证的超期事项',
        measures=[dict(id=task['measures'][0]['id'],action='核实并关闭超期订单',
                       owner='运营负责人',deadline='3 个工作日',acceptance='逐单提供关闭证据',
                       ownerConfirmed=True,deadlineConfirmed=True)]))
    assert edited.status_code==200, edited.text
    edited=edited.json()
    assert edited['measures'][0]['action']=='核实并关闭超期订单'

    result=c.post('/api/cockpit/tasks/'+task_id+'/dispatch',json={'id':1,'retry':False})
    assert result.status_code==200, result.text
    payload=result.json()
    assert payload['accepted'] is True and payload['task']['status']=='issued'
    assert calls[0]['recipients']==['18837823993']
    assert calls[0]['identity']==1
    assert all(item['itemType']=='TODO' for item in calls[0]['actions'])
    assert c.get('/api/cockpit/tasks/'+task_id).json()['dispatch'][0]['accepted'] is True
    assert c.post('/api/cockpit/tasks/'+task_id+'/dispatch',json={'id':1,'retry':False}).status_code==409


def test_partial_task_dispatch_keeps_the_draft_status_and_replays_receipts(tmp_path):
    def dispatcher(*,actions,recipients,identity):
        return [dict(accepted=index==0,status='ok' if index==0 else 'blocked',
                     message='已提交' if index==0 else '接收人配置不可用') for index,_ in enumerate(actions)]
    def two_measure_runner(evidence,context,stop,progress):
        result=valid_result(evidence)
        result['recommendations'].append(dict(id='r2',causeIds=['c1'],action='更新客户交付承诺',
            ownerRole='客户经理',deadlineDays=5,acceptance='客户确认新交付日期'))
        return result,[dict(tool='CockpitEvidenceQuery',section='all',evidenceCount=len(evidence['evidence']))]
    app=FastAPI();app.include_router(build_cockpit_router(lambda:str(tmp_path),
        runner=two_measure_runner,task_dispatcher=dispatcher))
    c=TestClient(app)
    a=wait(c,c.post('/api/cockpit/analyses',json={'id':1,'stage':'shipment'}).json()['id'])
    task=c.post('/api/cockpit/analyses/'+a['id']+'/draft').json()
    saved=c.post('/api/cockpit/tasks/'+task['id'],json=dict(
        id=1,revision=task['revision'],action='save',title=task['title'],goal=task['goal'],
        measures=[dict(id=item['id'],action=item['action'],owner=item['owner'],deadline=item['deadline'],
                       acceptance=item['acceptance'],ownerConfirmed=True,deadlineConfirmed=True)
                  for item in task['measures']]))
    assert saved.status_code==200, saved.text
    result=c.post('/api/cockpit/tasks/'+task['id']+'/dispatch',json={'id':1,'retry':False})
    assert result.status_code==200, result.text
    body=result.json()
    assert body['accepted'] is False and body['acceptedCount']==1 and body['total']==2
    assert c.get('/api/cockpit/tasks/'+task['id']).json()['status']=='draft'


def test_cockpit_task_dispatch_imports_the_process360_service_module():
    from pathlib import Path
    source=Path(__file__).resolve().parents[1]/'bi_agent'/'cockpit'/'router.py'
    text=source.read_text(encoding='utf-8')
    assert 'from ..process360.service import Process360Service' in text
    assert 'from .process360.service' not in text
    assert 'from .process360.tools' not in text


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
    home=c.get('/cockpit/home?id=2',follow_redirects=False)
    assert home.status_code==307
    assert home.headers['location']=='/gateway/analytics/cockpit/overview?id=2'
    for page in ['overview','operations','analysis']:
        pages=[c.get(f'/cockpit/{page}?id={identity}') for identity in (1,2)]
        assert all(response.status_code==200 for response in pages)
        assert pages[0].text==pages[1].text
        for response in pages:
            assert f'<meta name="cockpit-page" content="{page}">' in response.text
            assert '/gateway/analytics/static/cockpit/cockpit.js' in response.text
            assert '@@APP_ROOT_PATH@@' not in response.text
            assert '@@COCKPIT_PAGE@@' not in response.text
            assert '@@COCKPIT_VERSION@@' not in response.text
            assert '<meta name="cockpit-version" content="' in response.text
            assert 'class="rail"' not in response.text
            assert 'class="topbar"' not in response.text
            assert 'class="filterbar"' not in response.text
            assert 'class="page-heading"' not in response.text
    assert c.get('/static/cockpit/vendor/pro-bi-ui.min.js').status_code==200
    assert c.get('/static/cockpit/metadata/runtime.json').status_code==200
    assert c.get('/static/cockpit/layout/views.json').status_code==404
    assert c.get('/static/cockpit/insight-components/index.js').status_code==200
    assert c.get('/cockpit/not-a-page').status_code==404
    assert c.get('/api/cockpit/bootstrap').json()['supportsLiveSource'] is True


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
