"""Local-only browser QA: deterministic AP and model fixtures, isolated temporary SQLite."""
import os,json,tempfile,time,copy,threading
from pathlib import Path
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import FileResponse,HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from bi_agent.cockpit.ap_gateway import APConfig
from bi_agent.cockpit.dashboard_source import RELEASE,receipt_material
from bi_agent.cockpit.publications import digest,view_scope
from bi_agent.cockpit.store import Store
from bi_agent.cockpit.cards import CONTRACT
from bi_agent.cockpit.page_cache import APReuse
import bi_agent.cockpit.router as router
ROOT=Path(__file__).resolve().parents[1];scratch=Path(tempfile.mkdtemp(prefix='cockpit-performance-qa-'));headers=scratch/'headers.json';headers.touch(mode=0o600);headers.write_text(json.dumps({'X-App-Id':'qa-fixture','Cookie':'qa-fixture'}));os.environ['COCKPIT_DATA_MODE']='ap'
state={'revision':1,'fail':False,'requests':[],'models':0,'runtimeDelayMs':0}
frozen=json.loads((ROOT/'bi_agent/web/static/cockpit/metadata/pdt-release-2109836674373566465/data-snapshots.json').read_text())
class Gateway:
 config=APConfig('http://fixture.invalid/api/gateway2',str(headers),2,2,1800)
 def query(self,kind,payload):
  state['requests'].append({'kind':kind,'payload':payload})
  time.sleep(.025)
  if state['fail']:raise HTTPException(502,'本地故障注入：AP更新失败')
  if kind=='helmet':
   candidates=[v['response']['data'] for k,v in frozen['requests'].items() if payload.get('flowCode') in k]
   if not candidates:raise HTTPException(502,'QA graph not found')
   return copy.deepcopy(candidates[-1])
  if kind=='batch':return [{'success':True,'code':200,'data':self.result(q)} for q in payload]
  return self.result(payload)
 def result(self,q):
  ac=q['analysisConfig'];dims=ac.get('dimensions',[]);metrics=ac.get('indicators',[]);columns=[dict(identifierCode=x['identifierCode'],label=x.get('alias',x['identifierCode']),type='DIMENSION' if x in dims else 'METRIC') for x in dims+metrics]
  rows=[]
  for i in range(2 if dims else 1):
   row={}
   for d in dims:
    code=d['identifierCode'];value=({'D007':['normal_uncompleted','overdue_uncompleted'],'D008':[2026,2025],'D001':[2026,2025],'D005':['服务','电工材料']}.get(code,['A','B']))[i];row[code]={'value':value}
   for m in metrics:row[m['identifierCode']]={'value':state['revision']*100+(i+1)*10}
   rows.append(row)
  return {'resultType':'TABLE','result':{'columns':columns,'rows':rows}}
gateway=Gateway();router.get_gateway=lambda:gateway
# Keep fault injection immediate; production APReuse is covered by concurrency unit tests.
router.APReuse=lambda **_:APReuse(ttl=0)
def context(req):
 st=Store(scratch/'dataset/cockpit/history.sqlite3');fp,selected=receipt_material(req.model_dump(),st)
 return dict(snapshotId='ap-'+fp,dataIdentity=gateway.config.identity(),dataFingerprint=digest(sorted(((json.dumps(v['request'],sort_keys=True),v['response']) for v in selected.values()),key=lambda v:json.dumps(v,sort_keys=True))))
def runner(c,cancel,progress):
 state['models']+=1;time.sleep(.1)
 return dict(summary='仅本地自动化测试卡片 '+str(state['revision']),causes=[],recommendations=[],limitations=['仅QA，不代表真实经营数据'],cardContract=CONTRACT,_status='limited',_evidence={'facts':[],'records':[],'evidence':[]}),[]
app=FastAPI();app.add_middleware(GZipMiddleware,minimum_size=256)
app.include_router(router.build_cockpit_router(lambda:scratch,main_runner=runner,main_context=context))
@app.get('/static/cockpit/metadata/runtime.json')
def runtime_json():
 if state['runtimeDelayMs']:time.sleep(state['runtimeDelayMs']/1000)
 return FileResponse(ROOT/'bi_agent/web/static/cockpit/metadata/runtime.json',media_type='application/json')
@app.get('/cockpit/{page}',response_class=HTMLResponse)
def page(page:str):
 html=(ROOT/'bi_agent/web/static/cockpit/index.html').read_text().replace('@@APP_ROOT_PATH@@','').replace('@@COCKPIT_PAGE@@',page).replace('@@COCKPIT_VERSION@@','perf-qa-1')
 return HTMLResponse(html,headers={'Cache-Control':'no-store'})
@app.get('/debug/state')
def debug():
 st=Store(scratch/'dataset/cockpit/history.sqlite3')
 with st.db() as db:pages=db.execute('SELECT count(*) FROM page_snapshot_views').fetchone()[0]
 with st.db() as db:scopes=[json.loads(r[0])['uiScope'] for r in db.execute('SELECT p.body FROM page_snapshot_views v JOIN page_snapshots p ON p.id=v.snapshot_id') ]
 return dict(revision=state['revision'],fail=state['fail'],apiCalls=len(state['requests']),models=state['models'],pages=pages,scopes=scopes,requests=state['requests'])
@app.post('/debug/reset')
def reset():
 """Reset only this process's temporary fixture store; never touches user data."""
 global scratch
 scratch=Path(tempfile.mkdtemp(prefix='cockpit-performance-qa-'))
 state.update(revision=1,fail=False,requests=[],models=0,runtimeDelayMs=0)
 return {'ok':True}
@app.post('/debug/seed-risk-cards')
def seed_risk_cards(count:int=3):
 """Publish deterministic default-scope risk cards into this process's temp store."""
 count=max(1,min(int(count),4))
 st=Store(scratch/'dataset/cockpit/history.sqlite3')
 identity=gateway.config.identity()
 pages={'bid':'operations','quotation':'operations','order':'operations',
        'opportunity':'analysis','shipment':'analysis','combined':'analysis'}
 for stage,page in pages.items():
  scope='qa-risk-'+stage
  context=dict(id=1,engine='main',page=page,stage=stage,source='service',
    period='2025-10',department='全部产品部',filters={},chartSnapshotId=RELEASE,
    dataSource='ap',dataIdentity=identity)
  has_risks=stage in {'opportunity','shipment'}
  causes=[dict(id=f'qa-cause-{i+1}',title=['客户等级分布缺口','产品结构缺口','订单处理缺口','区域覆盖缺口'][i],
    description='本地浏览器验收用风险定位，不代表真实经营结论。',status='hypothesis',
    evidenceIds=[f'qa-evidence-{i+1}']) for i in range(count)] if has_risks else []
  findings=[dict(id=f'qa-risk-{i+1}',kind='risk_fact',
    title=['客户覆盖低于目标','产品覆盖低于目标','订单处理低于目标','区域覆盖低于目标'][i],
    description='本地浏览器验收用风险事实，不代表真实经营结论。',
    metricCodes=[f'QA_RISK_{i+1}'],evidenceIds=[f'qa-evidence-{i+1}'],
    riskDomain='sales' if stage=='opportunity' else 'shipment') for i in range(count)] if has_risks else []
  result=dict(summary='本地浏览器验收风险卡片',causes=causes,recommendations=[],findings=findings,
    limitations=['仅本地自动化测试，不代表真实业务结论'],cardContract=CONTRACT)
  evidence=dict(facts=[],records=[],evidence=[dict(id=f'qa-evidence-{i+1}',
    claim='本地浏览器验收证据') for i in range(count)] if has_risks else [],
    limitations=['仅本地自动化测试'])
  item=st.create_analysis(scope,context)
  st.update_analysis(item['id'],status='limited',progress='QA',result=result,evidence=evidence)
  if not st.publish(item['id']):raise HTTPException(500,'QA卡片发布失败')
  if not st.bind_view(view_scope(context),stage,scope):raise HTTPException(500,'QA卡片绑定失败')
 return {'ok':True,'count':count,'stages':list(pages)}
@app.post('/debug/change')
async def change(req:Request):
 args=await req.json()
 for k in ['revision','fail','runtimeDelayMs']:
  if k in args:state[k]=args[k]
 return {'ok':True}
app.mount('/static',StaticFiles(directory=ROOT/'bi_agent/web/static'),name='static')
if __name__=='__main__':
 import uvicorn
 uvicorn.run(app,host='127.0.0.1',port=8896,log_level='error')
