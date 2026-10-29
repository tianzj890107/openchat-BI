"""Cockpit API: read-only demo source, bounded analysis jobs, simulated tasks."""
from __future__ import annotations
import hashlib
import json
import threading
import time
import os
from copy import deepcopy
from html import escape
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, ConfigDict
from .data import DemoSource, DEPARTMENTS, PERIODS, NAMES
from .store import Store
from .agent import run_analysis
from .metadata import build_bundle
from .prototype import PrototypeSource
from .ap_gateway import APQuery, data_mode, get_gateway
from .publications import digest, legacy_publication_scope, legacy_view_scope, publication_scope, view_scope
from .page_cache import APReuse, PageLookup, PageRequest, build_page, legacy_page_scope, page_scope, transport_identity, compact_analysis
from .refresh import RefreshManager, RefreshScheduler, publication_status, scheduler_enabled, view_target_scope

RESULT_CONTRACT_VERSION="compact-v1"

class Context(BaseModel):
    model_config=ConfigDict(extra="forbid")
    id:int=Field(default=1,ge=1,le=2)
    period:Literal["2025-10","2025-09"]="2025-10"
    department:Literal["全部产品部","AIDC产品部","国内电力产品部","国际电力产品部"]="全部产品部"
    stage:Literal["opportunity","guidance","quotation","technical","bid","order","shipment"]="shipment"

    page:Literal["overview","operations","analysis"]="analysis"
    defaultView:bool=False
    source:Literal["demo","prototype","service"]="demo"
    engine:Literal["standalone","main"]="standalone"
    repositoryId:str=Field(default="",max_length=128)
    chartSnapshotId:str=Field(default="",max_length=160)
    apReceiptIds:list[str]=Field(default_factory=list,max_length=80)
    chartQueries:list[str]=Field(default_factory=list,max_length=80)
    unavailableQueries:list[str]=Field(default_factory=list,max_length=80)
    filters:dict[str,str|list[str]]=Field(default_factory=dict,max_length=20)
    baselineAnalysisId:str=Field(default="",pattern=r"^(|[a-f0-9]{32})$")
    clarifications:dict[str,str]=Field(default_factory=dict,max_length=10)

class AnalysisRequest(Context):
    refresh:bool=False

class Measure(BaseModel):
    model_config=ConfigDict(extra="forbid")
    id:str=Field(min_length=1,max_length=80)
    action:str=Field(min_length=1,max_length=1000)
    owner:str=Field(min_length=1,max_length=100)
    deadline:str=Field(min_length=1,max_length=120)
    acceptance:str=Field(min_length=1,max_length=600)

class TaskChange(BaseModel):
    model_config=ConfigDict(extra="forbid")
    id:int=Field(ge=1,le=2)
    revision:int=Field(ge=1)
    action:Literal["save","issue","accept","feedback","close"]
    title:str=Field(default="",max_length=180)
    goal:str=Field(default="",max_length=2000)
    feedback:str=Field(default="",max_length=3000)
    measures:list[Measure]=Field(default_factory=list,max_length=8)


def build_cockpit_router(get_cwd, runner=run_analysis, *, main_runner=None, main_context=None):
    router=APIRouter(prefix="/api/cockpit",tags=["cockpit"])
    source=DemoSource();stores={};lock=threading.RLock();jobs={};capacity=threading.BoundedSemaphore(3)
    ap_reuse = APReuse()
    def store():
        path=str(Path(get_cwd()).resolve()/"dataset"/"cockpit"/"history.sqlite3")
        with lock:
            if path not in stores:
                value=Store(Path(path));value.recover();stores[path]=value
            return stores[path]

    def publication_lookup(identity, page, ui_scope):
        """Return the current publication plus a display-only last-known fallback."""
        if main_context is None or data_mode() != 'ap':
            return dict(snapshot=None, displaySnapshot=None, displayStale=False,
                        status=dict(publicationVersion='', update=dict(status='idle')))
        config=get_gateway().config
        scope=page_scope(config, identity, page, ui_scope)
        snapshot=store().published_page(scope)
        if snapshot is None:
            snapshot=store().published_page(legacy_page_scope(config, identity, page, ui_scope))
        display=(snapshot
                 or store().latest_page(identity, page, ui_scope, data_identity=config.identity())
                 or store().latest_page(identity, page, ui_scope, data_identity='postgres'))
        state=publication_status(store(), scope, snapshot or display)
        if snapshot is None and display is not None and state['update']['status'] in {'', 'idle'}:
            state['update']['status']='stale-display'
        return dict(snapshot=snapshot, displaySnapshot=display,
                    displayStale=bool(snapshot is None and display is not None), status=state)
    @router.get('/data/config')
    def data_config():
        mode=data_mode()
        return dict(mode=mode,available=main_context is not None,
            analysisConcurrency=1,source='Cockpit独立AP连接' if mode=='ap' else '交付快照回放',
            batchMode=os.getenv('COCKPIT_AP_BATCH_MODE','individual'))

    @router.post('/data/query')
    async def data_query(req:APQuery, request:Request):
        if main_context is None:raise HTTPException(503,'AP代理仅由主服务提供，请连接主服务Cockpit入口')
        if data_mode()!='ap':raise HTTPException(409,'当前为显式快照模式，不允许混用实时AP查询')
        gateway=get_gateway()
        if await request.is_disconnected():raise HTTPException(499,'看板请求已取消')
        auth_scope=transport_identity(gateway.config)
        result_store=store()
        def read():
            result = gateway.query(req.kind, req.payload)
            if transport_identity(gateway.config)!=auth_scope:raise HTTPException(409,'AP认证配置已变化，请重新取数')
            return result_store.save_ap_result(req.id, req.kind, req.payload, result,
                                          gateway.config.receipt_ttl, gateway.config.identity(), auth_scope,
                                          gateway.config.batch_mode if req.kind=='batch' else 'fixed-path')
        from .publications import digest
        key = digest(dict(connection=auth_scope, store=str(result_store.path), id=req.id,
                          kind=req.kind, payload=req.payload))
        receipt = await run_in_threadpool(ap_reuse.read, key, read)
        if await request.is_disconnected():raise HTTPException(499,'看板请求已取消，未保存分析凭据')
        return dict(data=receipt['response'],receiptId=receipt['id'],receivedAt=receipt['createdAt'],expiresAt=receipt['expiresAt'])

    def adapter(mode):return PrototypeSource() if mode=="prototype" else source
    def context_id(context):
        value=context.get("id")
        if value in (1,2):return int(value)
        # Preserve POC history created before external identity switched to id.
        return 1 if context.get("role")=="president" else 2
    def snap(context):
        if context.engine=='main':
            if context.baselineAnalysisId:raise HTTPException(422,'主服务路线独立取证，baselineAnalysisId仅用于独立材料对照')
            if main_runner is None or main_context is None:raise HTTPException(503,'此服务未接入主服务执行链，请访问主服务的同名Cockpit入口；不会自动降级')
            if context.source!='service':raise HTTPException(422,'主服务路线必须使用service数据源')
            return main_context(context)
        if context.source=='service':
            if not context.baselineAnalysisId:raise HTTPException(422,'独立实时对照必须指定主服务已完成任务的baselineAnalysisId，不能自行构造证据')
            baseline=get_analysis(context.baselineAnalysisId);bound=baseline['context']
            if bound.get('engine')!='main' or baseline['status'] not in {'completed','limited'}:raise HTTPException(409,'基线必须是主服务已交付任务')
            fields=('id','stage','period','department','filters')
            requested=context.model_dump()
            if any(requested.get(k)!=bound.get(k,{} if k=='filters' else None) for k in fields):raise HTTPException(422,'基线与当前身份、环节或筛选范围不一致')
            if context.repositoryId and context.repositoryId!=bound.get('repositoryId'):raise HTTPException(422,'基线本体库不一致')
            frozen=deepcopy(baseline.get('evidence') or {})
            if not frozen.get('facts') and not frozen.get('records'):raise HTTPException(409,'主服务基线没有业务证据，不允许仅凭受限说明生成独立根因')
            snapshot_id='frozen-'+hashlib.sha256(json.dumps(frozen,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:20]
            frozen['snapshotId']=snapshot_id
            return dict(snapshotId=snapshot_id,repositoryId=bound.get('repositoryId',''),dataBasis='主服务任务'+baseline['id']+'的冻结证据；只对比同批材料的归纳，不代表两套取数流程公平竞速',_evidence=frozen)
        if context.repositoryId or context.filters:raise HTTPException(422,'演示源不支持本体库和自定义筛选，不能忽略分析范围')
        try:return adapter(context.source).snapshot(context.period,context.department)
        except ValueError as exc:raise HTTPException(422,str(exc))
    def get_analysis(aid):
        value=store().get_analysis(aid)
        if not value:raise HTTPException(404,"分析记录不存在")
        return value
    def context_value(c,s):
        snapshot_id=s["snapshotId"]
        data_source=s.get("dataSource") or ('ap' if snapshot_id.startswith('ap-') else 'snapshot' if snapshot_id.startswith('dashboard-') else 'demo')
        value=c.model_dump(exclude={"refresh"});value.update(stageName=NAMES[c.stage],snapshotId=snapshot_id,sourceMode=c.source,engine=c.engine,repositoryId=s.get("repositoryId",c.repositoryId),dataSource=data_source,dataIdentity=s.get("dataIdentity",""),dataFingerprint=s.get("dataFingerprint",""),dataBasis=s.get("dataBasis","原型或演示证据，不是当前看板AP快照"),stageEvidence=s.get("stageEvidence") or {},pgReceiptIds=s.get("pgReceiptIds") or [],fallbackVersion=s.get("fallbackVersion",""),fallback=s.get("fallback") or {})
        return value
    def scope(c,s):
        if c.engine=="main":return publication_scope(context_value(c,s))
        value=context_value(c,s);value["resultContract"]=RESULT_CONTRACT_VERSION
        return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    def worker(st,item,evidence,cancel,execute):
        try:
            st.update_analysis(item["id"],status="running",evidence=evidence,progress="读取当前快照")
            def progress(message,events):st.update_analysis(item["id"],progress=message,events=list(events))
            result,events=execute(evidence,item["context"],cancel,progress)
            if cancel.is_set():raise InterruptedError()
            status=result.pop('_status','completed');actual_evidence=result.pop('_evidence',evidence);execution=result.pop('_execution',dict(engine=item['context']['engine']))
            execution.setdefault('durationSeconds',round(time.time()-item['createdAt'],3))
            with lock:
                st.update_analysis(item["id"],status=status,progress='待补充口径' if status=='needs_input' else '证据不足／受限交付' if status=='limited' else '分析完成',result=result,events=events,evidence=actual_evidence,execution=execution)
                if st.publish(item["id"]) and item["context"].get("defaultView"):
                    st.bind_view(view_scope(item["context"]),item["context"]["stage"],item["scope"])
        except InterruptedError:
            st.update_analysis(item["id"],status="cancelled",progress="已停止，可重新分析",execution=dict(engine=item["context"]["engine"],durationSeconds=round(time.time()-item["createdAt"],3)))
        except Exception as exc:
            message=str(exc) if isinstance(exc,(RuntimeError,TimeoutError)) else "分析执行失败，请重试"
            st.update_analysis(item["id"],status="failed",progress="分析未完成",error=message[:600],execution=dict(engine=item["context"]["engine"],durationSeconds=round(time.time()-item["createdAt"],3)))
        finally:
            with lock:jobs.pop(item["id"],None)
            capacity.release()

    @router.get("/bootstrap")
    def bootstrap():
        return dict(roles=[dict(id=1,name="总裁"),dict(id=2,name="分析员")],identityParameter="id",periods=PERIODS,departments=DEPARTMENTS,
            stages=[dict(id=k,name=v) for k,v in NAMES.items()],sourceMode=("ap" if main_context is not None and data_mode()=="ap" else "demo"),supportsLiveSource=main_context is not None and data_mode()=="ap",
            notice="看板数据来源以data/config为准；任务流转仍为模拟，不写入业务系统。两个 id 当前使用相同看板与功能，仅为将来差异化预留。")

    @router.get('/engines')
    def engines():return dict(default=os.environ.get('COCKPIT_ANALYSIS_ENGINE','main'),comparisonOnly=os.environ.get('COCKPIT_COMPARISON_ENABLED','true').lower() in {'true','1'},productionPolicy='统一选择一个引擎承载全部AI插槽，禁止按插槽混用或静默降级',engines=[dict(id='main',available=main_runner is not None),dict(id='standalone',available=True)])

    @router.get("/metadata")
    def metadata():return build_bundle()

    @router.get("/snapshot")
    def snapshot(period:Literal["2025-10","2025-09"]="2025-10",department:Literal["全部产品部","AIDC产品部","国内电力产品部","国际电力产品部"]="全部产品部",source:Literal["demo","prototype"]="demo"):
        return snap(Context(period=period,department=department,source=source))

    @router.get("/evidence")
    def evidence(stage:Literal["opportunity","guidance","quotation","technical","bid","order","shipment"]="shipment",
                 period:Literal["2025-10","2025-09"]="2025-10",department:Literal["全部产品部","AIDC产品部","国内电力产品部","国际电力产品部"]="全部产品部",source:Literal["demo","prototype"]="demo"):
        return adapter(source).evidence(snap(Context(period=period,department=department,source=source)),stage)

    def check_engine(engine):
        configured=os.environ.get('COCKPIT_ANALYSIS_ENGINE','main')
        comparison=os.environ.get('COCKPIT_COMPARISON_ENABLED','true').lower() in {'true','1'}
        if configured not in {'main','standalone'}:raise HTTPException(503,'无效的全局分析引擎配置')
        if not comparison and engine!=configured:raise HTTPException(422,'已固定全站统一分析引擎，禁止按插槽选择其他路线')

    @router.post("/analyses")
    def analyse(req:AnalysisRequest):
        return start_analysis(req)

    def start_analysis(req, resolved=None):
        check_engine(req.engine)
        snapshot=resolved if resolved is not None else snap(req);key=scope(req,snapshot);st=store()
        with lock:
            previous=st.list_analyses(key)
            for item in previous:
                if item["status"] in {"queued","running"} and item["id"] in jobs:return item
                if req.engine=="standalone" and not req.refresh and item["status"]=="completed":return item
            try:
                item=st.create_analysis(key,context_value(req,snapshot));cancel=threading.Event();jobs[item["id"]]=cancel
                evidence=(snapshot['_evidence'] if '_evidence' in snapshot else adapter(req.source).evidence(snapshot,req.stage)) if req.engine=='standalone' else {}
                execute=runner if req.engine=='standalone' else lambda e,c,stop,p:main_runner(c,stop,p)
                def run_queued():
                    # Capacity is a shared execution budget, not a user-facing
                    # error: hold the request in queued state and start it as
                    # soon as a slot frees instead of returning 429.
                    if not capacity.acquire(timeout=900):
                        st.update_analysis(item["id"],status="failed",progress="分析未完成",error="排队超时，请稍后重试")
                        with lock: jobs.pop(item["id"],None)
                        return
                    worker(st,item,evidence,cancel,execute)
                st.update_analysis(item["id"],status="queued",progress="排队中，等待分析槽位")
                thread=threading.Thread(target=run_queued,daemon=True)
                thread.start()
            except Exception:
                jobs.pop(item["id"],None) if 'item' in locals() else None
                raise
        return item

    @router.get('/analyses/published')
    def published_default(id:int=1,engine:Literal['main','standalone']='main',page:Literal['overview','operations','analysis']='analysis',compact:bool=False):
        if id not in (1,2):raise HTTPException(422,'无效身份')
        check_engine(engine)
        from .dashboard_source import RELEASE
        from .cards import CONTRACT
        identity=get_gateway().config.identity() if data_mode()=='ap' else RELEASE
        items={}
        sources=('ap','ap+pg','pg') if data_mode()=='ap' else ('snapshot',)
        identities=(identity,'postgres') if data_mode()=='ap' else (identity,)
        for data_source in sources:
            for data_identity in identities:
                context=dict(id=id,engine=engine,page=page,chartSnapshotId=RELEASE,
                             dataSource=data_source,dataIdentity=data_identity)
                found=store().published_view(view_scope(context))
                if (not found and data_mode()=='ap' and data_source=='ap'
                        and data_identity==identity):
                    found=store().published_view(legacy_view_scope(context))
                for stage,item in found.items():
                    current=items.get(stage)
                    if current is None or float(item.get('updatedAt') or 0)>=float(current.get('updatedAt') or 0):
                        items[stage]=item
        # A metadata/config rotation hides the keyed view but not the user's
        # last analysis.  Show it as display-only until the scheduler republishes.
        for data_identity in identities:
            for stage,item in store().latest_views(id,engine,page,data_identity=data_identity).items():
                if stage not in items:
                    items[stage]=dict(item,displayOnly=True)
        if compact:
            items={stage:({**compact_analysis(item),'displayOnly':True}
                          if item.get('displayOnly') else compact_analysis(item))
                   for stage,item in items.items()}
        return dict(items=items,cardContract=CONTRACT)

    @router.get('/page')
    def published_page(id:int=1,page:Literal['overview','operations','analysis']='overview',uiScope:str='default'):
        if id not in (1,2) or not 0<len(uiScope)<=16000:raise HTTPException(422,'无效页面范围')
        return publication_lookup(id, page, uiScope)

    @router.post('/page')
    def publish_page(req:PageRequest):
        if main_context is None or data_mode()!='ap':raise HTTPException(409,'整页缓存仅支持主服务实时AP路线')
        config=get_gateway().config
        key=page_scope(config,req.id,req.page,req.uiScope)
        page=build_page(req,store(),config,data_source='ap')
        if key!=page_scope(config,req.id,req.page,req.uiScope):raise HTTPException(409,'AP认证配置已变化，保留原版本')
        accepted=store().publish_page(key,page)
        return dict(accepted=accepted,snapshot=page if accepted else store().published_page(key))

    @router.post('/page/lookup')
    def lookup_page(req:PageLookup):
        return publication_lookup(req.id, req.page, req.uiScope)

    def cards_version(id, page):
        # Operations and penetration pages publish AI cards without a whole-page
        # snapshot, so the browser needs a version for those cards too.
        items=published_default(id,'main',page,False)['items'] if main_context is not None else {}
        return digest(sorted((stage,(item or {}).get('id',''),float((item or {}).get('updatedAt') or 0))
                             for stage,item in items.items()))

    @router.get('/publications/status')
    def publication_update(id:int=1,page:Literal['overview','operations','analysis']='overview',uiScope:str='default'):
        if id not in (1,2) or not 0<len(uiScope)<=16000:raise HTTPException(422,'无效页面范围')
        lookup=publication_lookup(id,page,uiScope)
        snapshot=lookup.get('snapshot') or lookup.get('displaySnapshot')
        return dict(id=id,page=page,uiScope=uiScope,snapshotVersion=(snapshot or {}).get('version',''),
                    cardsVersion=cards_version(id,page),
                    displayStale=lookup.get('displayStale',False),**(lookup.get('status') or {}))

    @router.get('/publications/cards')
    def publication_cards(id:int=1,page:Literal['overview','operations','analysis']='overview'):
        if id not in (1,2):raise HTTPException(422,'无效身份')
        from .cards import CONTRACT
        items=published_default(id,'main',page,True)['items'] if main_context is not None else {}
        return dict(items=items,cardContract=CONTRACT)

    @router.post('/publications/refresh')
    def request_publication_refresh(req:PageLookup):
        if main_context is None or data_mode()!='ap':raise HTTPException(409,'服务端刷新仅支持实时AP路线')
        config=get_gateway().config
        scope=page_scope(config,req.id,req.page,req.uiScope)
        body=(store().published_page(scope)
              or store().published_page(legacy_page_scope(config,req.id,req.page,req.uiScope))
              or store().latest_page(req.id,req.page,req.uiScope,data_identity=config.identity()))
        if body is not None:
            store().set_refresh_plan(scope,body)
            queued=store().request_refresh(scope)
            return dict(queued=queued,scope=scope,status='waiting' if queued else 'running',kind='page')
        # Operations and penetration pages may have published AI cards without
        # ever forming a whole-page snapshot.  Refresh those cards instead of
        # queueing a page scope that has no query plan.
        targets=[view_target_scope(view_key,stage) for view_key,stage,analysis in store().default_views(limit=2000)
                 if req.uiScope=='default'
                 and (analysis.get('context') or {}).get('id')==req.id
                 and (analysis.get('context') or {}).get('page')==req.page]
        if targets:
            queued=[target for target in dict.fromkeys(targets) if store().request_refresh(target)]
            return dict(queued=bool(queued),scope=scope,status='waiting' if queued else 'running',
                        kind='views',targets=len(set(targets)))
        raise HTTPException(409,'该范围还没有可复核的查询计划，请先在页面完成取数后再刷新')

    @router.get('/startup')
    def startup(id:int=1,page:Literal['overview','operations','analysis']='overview'):
        caps=engines();lookup=publication_lookup(id,page,'default')
        # Cards already published for this role/page are display-only until a
        # matching server publication replaces them.  Opening the page never
        # starts a model call by itself.
        cards=published_default(id,'main',page,True)['items'] if caps['default']=='main' and main_context is not None else {}
        return dict(engines=caps,dataConfig=data_config(),cards=cards,**lookup)

    @router.post('/analyses/refresh')
    def refresh_analysis(req:AnalysisRequest,compact:bool=False):
        check_engine(req.engine)
        if req.engine!='main':raise HTTPException(422,'持久卡片刷新仅适用于main路线')
        snapshot=snap(req);context=context_value(req,snapshot);key=scope(req,snapshot);st=store()
        with lock:
            cached=st.published(key)
            if cached is None and data_mode()=='ap' and context.get('dataSource')=='ap':
                cached=st.published(legacy_publication_scope(context))
            if req.defaultView and cached:st.bind_view(view_scope(context),req.stage,key)
            # Re-opening a page with unchanged AP values must not spend another model call.
            fresh=cached and cached['context'].get('dataFingerprint')==context.get('dataFingerprint')
            job=None if fresh and not req.refresh else start_analysis(req,snapshot)
            return dict(cached=compact_analysis(cached) if compact else cached,analysis=compact_analysis(job) if compact else job,scope=key,dataFingerprint=context.get("dataFingerprint"),refreshing=bool(job and job['status'] in {'queued','running'}))

    @router.get("/analyses")
    def history(id:int=1,period:str|None=None,department:str|None=None,engine:Literal["main","standalone"]|None=None):
        # id is the single Fuxi-facing identity parameter: 1=总裁, 2=分析员.
        if id not in (1,2):raise HTTPException(422,"id 只能是 1 或 2")
        return [x for x in store().list_analyses() if context_id(x["context"])==id
            and (engine is None or x["context"].get("engine","standalone")==engine)
            and (period is None or x["context"]["period"]==period) and (department is None or x["context"]["department"]==department)]

    @router.get("/analyses/{aid}")
    def analysis(aid:str,compact:bool=False):
        value=get_analysis(aid)
        return compact_analysis(value) if compact else value

    @router.post("/analyses/{aid}/cancel")
    def cancel(aid:str):
        item=get_analysis(aid)
        with lock:
            event=jobs.get(aid)
            if event:event.set()
        return store().update_analysis(aid,status="cancelled",progress="已停止，可重新分析") if item["status"] in {"queued","running"} else item

    @router.get("/analyses/{aid}/report",response_class=HTMLResponse)
    def report(aid:str):
        item=get_analysis(aid)
        if item["status"] not in {"completed","limited","needs_input"}:raise HTTPException(409,"分析尚未完成")
        result=item["result"];ctx=item["context"]
        labels={'ap':'页面本次实时AP结果','ap+pg':'页面AP结果＋主库同口径补查','snapshot':'交付AP快照','postgres':'Process360 PostgreSQL 只读结果','demo':'演示数据'}
        label=('主服务冻结证据（独立对照）' if ctx.get('engine')=='standalone' else labels.get(ctx.get('dataSource'),'未标明数据来源')) if ctx.get('sourceMode')=='service' else '演示数据'
        summary='' if result.get('narrative') else escape(result['summary'])
        display_scope='实际期间和部门以本次AP原始请求为准' if ctx.get('snapshotId','').startswith('ap-') else escape(ctx['period'])+' · '+escape(ctx['department'])
        content=f'<h1>{escape(ctx["stageName"])}分析报告</h1><p>{label} · {display_scope} · {escape(item["status"])}</p><p>{summary}</p>'
        if result.get('narrative'):content+='<pre style="white-space:pre-wrap">'+escape(result['narrative'])+'</pre>'
        for c in result["causes"]:content+=f'<h3>{escape(c["title"])}</h3><p>{escape(c["description"])}</p><p>证据：{escape(", ".join(c["evidenceIds"]))}</p>'
        content+='<h2>改善建议</h2>'
        for r in result["recommendations"]:content+=f'<p>{escape(r["action"])}｜建议责任角色：{escape(r["ownerRole"])}｜验收：{escape(r["acceptance"])}</p>'
        content+='<h2>证据明细</h2>'
        for e in item["evidence"]["evidence"]:content+=f'<p>{escape(e["id"])} · {escape(e["label"])} · {escape(str(e.get("value") if e.get("value") is not None else ""))}{escape(e.get("unit",""))} · {escape(e["definition"])}</p>'
        content+='<h2>适用限制</h2>'+''.join('<p>'+escape(x)+'</p>' for x in result['limitations'])
        return HTMLResponse('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>经营分析报告</title><style>body{max-width:980px;margin:48px auto;padding:0 24px;font:15px/1.8 system-ui;color:#253550}h1,h2{color:#254edb}p{overflow-wrap:anywhere}</style>'+content+'</html>',headers={"Content-Disposition":f'inline; filename="analysis-{aid}.html"'})

    @router.post("/analyses/{aid}/draft")
    def draft(aid:str):
        item=get_analysis(aid)
        if item["status"]!="completed":raise HTTPException(409,"只能基于已完成分析生成任务令草稿")
        if not item["result"].get("recommendations"):raise HTTPException(409,"当前主服务交付尚无结构化任务措施，请由分析员确认；不从正文猜测责任和期限")
        return store().draft(item)

    @router.get("/tasks")
    def tasks():return store().list_tasks()

    @router.get("/tasks/{tid}")
    def task(tid:str):
        value=store().get_task(tid)
        if not value:raise HTTPException(404,"任务不存在")
        return value

    @router.post("/tasks/{tid}")
    def change(tid:str,req:TaskChange):
        payload={"feedback":req.feedback}
        if req.action=="save":
            if not req.title.strip() or not req.goal.strip() or not req.measures:raise HTTPException(422,"请补齐标题、目标及措施")
            payload=dict(title=req.title,goal=req.goal,measures=[x.model_dump() for x in req.measures])
        try:return store().mutate_task(tid,req.revision,req.action,payload)
        except KeyError:raise HTTPException(404,"任务不存在")
        except ValueError as exc:raise HTTPException(409,str(exc))

    scheduler = None
    try:
        if main_context is not None and data_mode() == 'ap' and scheduler_enabled():
            config = get_gateway().config
            def start_refresh_analysis(body, resolved):
                return start_analysis(AnalysisRequest(**body), resolved=resolved)
            manager = RefreshManager(
                store(), config, lambda kind, payload: get_gateway().query(kind, payload),
                start_refresh_analysis,
                interval=int(os.getenv('COCKPIT_REFRESH_INTERVAL_SECONDS', '900')),
                timeout=int(os.getenv('COCKPIT_REFRESH_TIMEOUT_SECONDS', '1200')))
            scheduler = RefreshScheduler(
                manager, store(),
                scan_seconds=int(os.getenv('COCKPIT_REFRESH_SCAN_SECONDS', '20')))
            scheduler.start()
    except Exception as exc:
        # A scheduler/configuration failure must not prevent the dashboard from
        # serving its last published version; it is reported in the app log.
        print(f'[cockpit-refresh] disabled: {exc}')
    router._cockpit_refresh_scheduler = scheduler
    return router
