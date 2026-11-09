"""Cockpit API: read-only demo source, bounded analysis jobs, simulated tasks."""
from __future__ import annotations
import hashlib
import inspect
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
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from .data import DemoSource, DEPARTMENTS, PERIODS, NAMES
from .store import Store
from .diagnostics import record_failure, current_scope, diagnostic_scope
from .agent import run_analysis
from .cards import CONTRACT, card_delivery_state, valid_card
from .delivery import project_card, publication_payload
from .risk import summarize_risk_counts
from .metadata import build_bundle
from .prototype import PrototypeSource
from .ap_gateway import APQuery, data_mode, get_gateway
from .publications import (config_version, digest, legacy_publication_scope, legacy_view_scope,
                           publication_scope, view_scope)
from .page_cache import APReuse, PageLookup, PageRequest, build_page, legacy_page_scope, page_scope, transport_identity, compact_analysis
from .targets import PAGES, REGISTRY_VERSION, slot_registry, target_page, target_stages
from .ai_tables import (TABLE_MAPPING_VERSION, TABLE_SPECS, TableQuery, annotate_rows,
                        build_ap_query, preheat_table, result_rows, table_cache_key,
                        table_scope_key)
from .refresh import (RefreshManager, RefreshScheduler, publication_status, scheduler_enabled,
                      custom_refresh_expiry, preheat_target_scope, refresh_business_key,
                      stage_card_status, view_target_scope, period_target_scope,
                      period_card_status, analysis_cadence, record_period_publication)
from . import periods

RESULT_CONTRACT_VERSION="compact-v1"


def _default_display_scope(ui_scope: str) -> bool:
    """Whether the delivered page is still on its empty default filter.

    A grain-only selection is an explicit period choice, not the default.  It
    is resolved by ``_read_period`` to the current year or month so the slot
    and table reads still share one exact period index.
    """
    if ui_scope in (None, '', 'default'):
        return True
    try:
        changes = json.loads(ui_scope)
    except (TypeError, ValueError):
        return False
    return isinstance(changes, list) and not changes


def _read_period(ui_scope: str, fallback: str = '') -> str:
    """Exact period a read should use, including the delivered default page.

    ``default`` and the date-less month-grain state are not "no period"; they
    display the delivery's default month.  Resolving them here keeps every read
    entry (slots, status, tables) on the same period index instead of falling
    back to whichever historical preheat was published last.
    """
    if _default_display_scope(ui_scope):
        return periods.default_period()
    if periods.scope_is_period(ui_scope):
        state = periods.period_state(ui_scope, fallback)
        return (periods.normalise(state.get('period'))
                or periods.default_period(period_type=state.get('grain') or ''))
    return ''

class Context(BaseModel):
    model_config=ConfigDict(extra="forbid")
    id:int=Field(default=1,ge=1,le=2)
    period:str=Field(default="",max_length=7)
    department:Literal["全部产品部","AIDC产品部","国内电力产品部","国际电力产品部"]="全部产品部"
    stage:Literal["opportunity","guidance","quotation","technical","bid","order","shipment","combined"]="shipment"

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

    @field_validator('period', mode='before')
    @classmethod
    def _valid_period(cls, value):
        if value in (None, ''):
            return ''
        period = periods.normalise(value)
        if not period:
            raise ValueError('期间必须为 YYYY 或 YYYY-MM')
        return period

    @model_validator(mode='after')
    def _fill_default_period(self):
        if not self.period:
            # The bundled demo/prototype fixtures only contain the original
            # delivery month.  Live/main-service requests use the customer's
            # current business year instead of pinning that fixture month.
            self.period = (PERIODS[0] if self.source in {'demo', 'prototype'}
                           else periods.default_period())
        return self

class AnalysisRequest(Context):
    refresh:bool=False

class DraftRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    id:int|None=Field(default=None,ge=1,le=2)
    recommendationIds:list[str]|None=Field(default=None,max_length=20)

class Measure(BaseModel):
    model_config=ConfigDict(extra="forbid")
    id:str=Field(min_length=1,max_length=80)
    action:str=Field(min_length=1,max_length=1000)
    owner:str=Field(min_length=1,max_length=100)
    deadline:str=Field(min_length=1,max_length=120)
    acceptance:str=Field(min_length=1,max_length=600)
    ownerConfirmed:bool=False
    deadlineConfirmed:bool=False

class TaskChange(BaseModel):
    model_config=ConfigDict(extra="forbid")
    id:int=Field(ge=1,le=2)
    revision:int=Field(ge=1)
    action:Literal["save","issue","accept","feedback","close"]
    title:str=Field(default="",max_length=180)
    goal:str=Field(default="",max_length=2000)
    feedback:str=Field(default="",max_length=3000)
    measures:list[Measure]=Field(default_factory=list,max_length=8)


class TaskDispatch(BaseModel):
    model_config=ConfigDict(extra="forbid")
    id:int=Field(ge=1,le=2)
    retry:bool=False


def build_cockpit_router(get_cwd, runner=run_analysis, *, main_runner=None, main_context=None,
                         task_dispatcher=None):
    router=APIRouter(prefix="/api/cockpit",tags=["cockpit"])
    source=DemoSource();stores={};lock=threading.RLock();jobs={};capacity=threading.BoundedSemaphore(3)
    try:
        # Completed AP receipts are not reused by default.  Identical requests
        # that overlap in flight are still coalesced below, but a later request
        # must reach AP again instead of replaying a previous response.
        reuse_ttl = max(0, min(900, int(os.getenv('COCKPIT_AP_REUSE_SECONDS', '0'))))
    except ValueError:
        reuse_ttl = 0
    ap_reuse = APReuse(ttl=reuse_ttl)
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

    def period_publication(identity, stage, ui_scope, *, filters=None, period=None,
                           compact=True):
        """Read an exact period-stage publication when the scope is date-only.

        The period index is independent of the newest default card.  This is
        the single read rule used by AI slots, table annotations and status:
        a requested month/year is served from its own entry, and only a miss
        falls back to the display-only latest card.
        """
        if period is None:
            if ui_scope in ('', 'default') or not periods.scope_is_period(ui_scope):
                return None
            state = periods.period_state(ui_scope, '')
            period = state.get('period')
        period = periods.normalise(period)
        if not period:
            return None
        data_identity = get_gateway().config.identity() if data_mode() == 'ap' else ''
        hit = store().published_period(identity, period, stage, filters or {},
                                       data_identity=data_identity or None)
        if not hit:
            return None
        item = store().get_analysis(hit['analysis_id'])
        context = (item or {}).get('context') or {}
        if (not item or item.get('status') not in {'completed', 'limited'}
                or not valid_card(item)
                or int(context.get('id') or 0) != int(identity)
                or context.get('stage') != stage
                or context.get('engine') != 'main'
                or periods.normalise(context.get('period')) != period):
            return None
        if data_identity and str(context.get('dataIdentity') or '') != str(data_identity):
            return None
        return compact_analysis(item) if compact else item
    @router.get('/data/config')
    def data_config():
        mode=data_mode()
        return dict(mode=mode,available=main_context is not None,
            analysisConcurrency=1,source='Cockpit独立AP连接' if mode=='ap' else '交付快照回放',
            batchMode=os.getenv('COCKPIT_AP_BATCH_MODE','individual'))

    def _query_receipt(identity, kind, payload, *, timing=None, _deadline=None):
        """One shared read path for page requests and background refresh.

        The cache/coalescing key includes the role, transport identity, store
        and exact payload.  A scheduler therefore waits on the same in-flight
        page query instead of sending a duplicate to AP.
        """
        gateway=get_gateway()
        auth_scope=transport_identity(gateway.config)
        result_store=store()
        diagnostic_context=current_scope()
        inherited_deadline=diagnostic_context.get('fetchDeadline')
        if inherited_deadline is not None:
            _deadline=min(_deadline,inherited_deadline) if _deadline is not None else inherited_deadline
        def read():
            try:
                if 'timing' in inspect.signature(gateway.query).parameters:
                    kwargs = {'timing': timing}
                    if _deadline is not None:
                        kwargs['_deadline'] = _deadline
                    result=gateway.query(kind,payload,**kwargs)
                else:
                    result=gateway.query(kind,payload)
            except Exception as exc:
                diagnostic=record_failure(result_store,exc,phase='ap_query',identity=identity,
                    stage=diagnostic_context.get('stage',''),run_id=diagnostic_context.get('runId',''),
                    duration=time.monotonic()-started,
                    query_hash=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest())
                exc.diagnostic_id=diagnostic['diagnosticId']
                if isinstance(exc,HTTPException):
                    exc.headers={**(exc.headers or {}),'X-Cockpit-Diagnostic-Id':diagnostic['diagnosticId']}
                raise
            if transport_identity(gateway.config)!=auth_scope:
                raise HTTPException(409,'AP认证配置已变化，请重新取数')
            return result_store.save_ap_result(identity,kind,payload,result,
                gateway.config.receipt_ttl,gateway.config.identity(),auth_scope,
                gateway.config.batch_mode if kind=='batch' else 'fixed-path')
        key=digest(dict(connection=auth_scope,store=str(result_store.path),id=identity,
                        deadlineClass='ai' if inherited_deadline is not None else 'display',
                        kind=kind,payload=payload))
        started=time.monotonic()
        trace={} if timing is None else timing
        timeout=getattr(gateway.config,'timeout',200)
        wait_timeout = max(35,float(timeout)+10) if _deadline is None else max(.01, _deadline-time.monotonic())
        receipt=ap_reuse.read(key,read,timeout=wait_timeout,trace=trace)
        if timing is not None:
            timing['receiptWaitMs']=round((time.monotonic()-started)*1000,1)
        return receipt

    def query_receipt(identity, kind, payload, *, timing=None, _deadline=None):
        started=time.monotonic()
        try:
            return _query_receipt(identity,kind,payload,timing=timing,_deadline=_deadline)
        except Exception as exc:
            if not getattr(exc,'diagnostic_id',None):
                diagnostic=record_failure(store(),exc,phase='ap_query_setup',identity=identity,
                    duration=time.monotonic()-started,
                    query_hash=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest())
                exc.diagnostic_id=diagnostic['diagnosticId']
                if isinstance(exc,HTTPException):
                    exc.headers={**(exc.headers or {}),'X-Cockpit-Diagnostic-Id':diagnostic['diagnosticId']}
            raise

    @router.post('/data/query')
    async def data_query(req:APQuery, request:Request):
        if main_context is None:raise HTTPException(503,'AP代理仅由主服务提供，请连接主服务Cockpit入口')
        if data_mode()!='ap':raise HTTPException(409,'当前为显式快照模式，不允许混用实时AP查询')
        if await request.is_disconnected():raise HTTPException(499,'看板请求已取消')
        timing={}
        started=time.monotonic()
        receipt = await run_in_threadpool(query_receipt, req.id, req.kind, req.payload, timing=timing)
        if await request.is_disconnected():raise HTTPException(499,'看板请求已取消，未保存分析凭据')
        timing['serverTotalMs']=round((time.monotonic()-started)*1000,1)
        return dict(data=receipt['response'],receiptId=receipt['id'],receivedAt=receipt['createdAt'],
                    expiresAt=receipt['expiresAt'],timings=timing)

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
        value['diagnosticRunId']=current_scope().get('runId','')
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
            if item['context'].get('stage') == 'opportunity' and item['context'].get('engine') == 'main':
                from .customer_coverage import load as load_customer_coverage
                result['customerCoverage'] = load_customer_coverage(item['context'], st, query_receipt)
                if cancel.is_set():raise InterruptedError()
            execution.setdefault('durationSeconds',round(time.time()-item['createdAt'],3))
            with lock:
                st.update_analysis(item["id"],status=status,progress='待补充口径' if status=='needs_input' else '证据不足／受限交付' if status=='limited' else '分析完成',result=result,events=events,evidence=actual_evidence,execution=execution)
                if st.publish(item["id"]) and item["context"].get("defaultView"):
                    view_key=view_scope(item["context"])
                    st.bind_view(view_key,item["context"]["stage"],item["scope"])
                    record_period_publication(st,item["context"],item["id"],view_key)
        except InterruptedError:
            st.update_analysis(item["id"],status="cancelled",progress="已停止，可重新分析",execution=dict(engine=item["context"]["engine"],durationSeconds=round(time.time()-item["createdAt"],3)))
        except Exception as exc:
            duration=round(time.time()-item['createdAt'],3)
            diagnostic=record_failure(st,exc,phase='analysis_execution',identity=context_id(item['context']),
                stage=item['context'].get('stage',''),analysis_id=item['id'],
                run_id=item['context'].get('diagnosticRunId',''),duration=duration)
            message='分析执行失败，请查看后台诊断：'+diagnostic['diagnosticId']
            st.update_analysis(item['id'],status='failed',progress='分析未完成',error=message,
                execution=dict(engine=item['context']['engine'],durationSeconds=duration,diagnostic=diagnostic))
        finally:
            with lock:jobs.pop(item["id"],None)
            capacity.release()

    @router.get("/bootstrap")
    def bootstrap():
        return dict(roles=[dict(id=1,name="总裁"),dict(id=2,name="分析员")],identityParameter="id",periods=PERIODS,departments=DEPARTMENTS,
            stages=[dict(id=k,name=v) for k,v in NAMES.items()],sourceMode=("ap" if main_context is not None and data_mode()=="ap" else "demo"),supportsLiveSource=main_context is not None and data_mode()=="ap",
            periodConfig=dict(defaultPeriod=periods.default_period(),defaultPeriodType='year',mode=periods.period_mode(),activePeriod=periods.active_period(),preheatPeriods=periods.period_catalog()),
            notice="看板数据来源以data/config为准；任务流转仍为模拟，不写入业务系统。两个 id 当前使用相同看板与功能，仅为将来差异化预留。")

    @router.get('/engines')
    def engines():return dict(default=os.environ.get('COCKPIT_ANALYSIS_ENGINE','main'),comparisonOnly=os.environ.get('COCKPIT_COMPARISON_ENABLED','true').lower() in {'true','1'},productionPolicy='统一选择一个引擎承载全部AI插槽，禁止按插槽混用或静默降级',engines=[dict(id='main',available=main_runner is not None),dict(id='standalone',available=True)])

    @router.get("/metadata")
    def metadata():return build_bundle()

    @router.get("/snapshot")
    def snapshot(period:str|None=None,department:Literal["全部产品部","AIDC产品部","国内电力产品部","国际电力产品部"]="全部产品部",source:Literal["demo","prototype"]="demo"):
        return snap(Context(period=period or PERIODS[0],department=department,source=source))

    @router.get("/evidence")
    def evidence(stage:Literal["opportunity","guidance","quotation","technical","bid","order","shipment"]="shipment",
                 period:str|None=None,department:Literal["全部产品部","AIDC产品部","国内电力产品部","国际电力产品部"]="全部产品部",source:Literal["demo","prototype"]="demo"):
        return adapter(source).evidence(snap(Context(period=period or PERIODS[0],department=department,source=source)),stage)

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

    def cancel_analysis_job(aid):
        """Cooperate with a running scheduler job without deleting its record."""
        item=store().get_analysis(aid)
        if not item or item.get('status') not in {'queued','running'}:
            return item
        with lock:
            event=jobs.get(aid)
            if event is not None:event.set()
        return store().update_analysis(aid,status="cancelled",progress="已停止，可重新分析")

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
        # A saved whole-page version already contains delivered cards.  They
        # must come back on their own, not only after a per-stage click.
        for data_identity in identities:
            body=store().latest_page(id,page,'default',data_identity=data_identity)
            for stage,item in ((body or {}).get('items') or {}).items():
                if not item:continue
                current=items.get(stage)
                if current is None or float(item.get('updatedAt') or 0)>=float(current.get('updatedAt') or 0):
                    items[stage]=item
        # One business stage can be shown by two pages (for example 订单接收 on
        # the operations and penetration pages).  The saved card is stage-level,
        # so switching pages must not hide it.
        for stage in target_stages(page):
            if stage in items:continue
            found=None
            for other in PAGES:
                if other==page:continue
                # Older deployments published a complete page before binding
                # its cards as standalone views.  Keep that history usable when
                # the same business stage is shown by another page.
                for data_identity in identities:
                    body=store().latest_page(id,other,'default',data_identity=data_identity)
                    candidate=((body or {}).get('items') or {}).get(stage)
                    if candidate and (found is None or float(candidate.get('updatedAt') or 0)>float(found.get('updatedAt') or 0)):
                        found=candidate
                for data_identity in identities:
                    candidate=store().latest_views(id,engine,other,data_identity=data_identity).get(stage)
                    if candidate and (found is None or float(candidate.get('updatedAt') or 0)>float(found.get('updatedAt') or 0)):
                        found=candidate
            if found:items[stage]=found
        if compact:
            items={stage:({**compact_analysis(item),'displayOnly':True}
                          if item.get('displayOnly') else compact_analysis(item))
                   for stage,item in items.items()}
        return dict(items=items,cardContract=CONTRACT)

    def period_default_cards(identity, page_name, compact=True):
        """Default-scope cards with the delivered period taking precedence.

        The default view can contain a historical preheat if history was
        published last.  Reading the period index first keeps the default page
        stable; the newest view remains only a display fallback for stages that
        have no card for the delivered period yet.
        """
        items=published_default(identity,'main',page_name,compact)['items'] if main_context is not None else {}
        if main_context is None or data_mode()!='ap':
            return items
        period=periods.default_period()
        if not period:
            return items
        for stage in target_stages(page_name):
            card=period_publication(identity,stage,'default',period=period,compact=compact)
            if card:
                items[stage]=card
        return items

    def slot_publications(identity:int, ui_scope:str) -> dict:
        """Read all configured AI slots from persisted publications only.

        This path intentionally touches no AP endpoint, no analysis job and no
        page-data preparation.  The slot registry is fixed, so the response has
        the same 15 keys before and after a tab/node switch.  Several slots may
        share one stage publication; that is the same result delivered to each
        of their component contracts, not a fabricated per-card analysis.
        """
        is_default_scope = ui_scope in ('', 'default') or _default_display_scope(ui_scope)
        period_only_scope = is_default_scope or periods.scope_is_period(ui_scope)
        requested_period = _read_period(ui_scope) if period_only_scope else ''
        period_items = {}
        if requested_period:
            for stage in {slot['stage'] for slot in slot_registry()}:
                card = period_publication(identity, stage, ui_scope,
                                          period=requested_period)
                if card:
                    period_items[stage] = card
        page_cards = {}
        # Always expose the last successful default-scope card.  For a custom
        # filter it is explicitly marked as a display-only fallback, so a page
        # reload cannot turn every AI slot into a blank "missing" card while the
        # server is preparing the new scope.
        if main_context is not None:
            for page_name in ('operations', 'analysis'):
                page_cards[page_name] = period_default_cards(identity, page_name)

        stage_items = {}
        for items in page_cards.values():
            for stage, item in items.items():
                if not valid_card(item):
                    continue
                current = stage_items.get(stage)
                if current is None or float(item.get('updatedAt') or 0) >= float(current.get('updatedAt') or 0):
                    stage_items[stage] = item

        def refresh_for(slot, item, period='', exact=False):
            keys = []
            if exact:
                if period:
                    keys.append(period_target_scope(identity, target_page(slot['stage']) or slot['page'],
                                                    slot['stage'],
                                                    period))
            elif period:
                # A display-only fallback is waiting for this selected period,
                # not for whichever default card happens to be newest.
                keys.append(period_target_scope(identity, target_page(slot['stage']) or slot['page'],
                                                slot['stage'],
                                                period))
            else:
                keys.append(preheat_target_scope(identity, slot['page'], slot['stage']))
            context = (item or {}).get('context') or {}
            if context and not period:
                keys.append(view_target_scope(view_scope(context), slot['stage']))
            states = [store().refresh_state(key) or {} for key in keys]
            now = time.time()

            def effective(value):
                status = str(value.get('status') or 'idle')
                if (status == 'waiting' and float(value.get('next_check') or 0) > now + 5
                        and float(value.get('lease_until') or 0) <= now):
                    return 'scheduled'
                return status

            statuses = [effective(value) for value in states]
            active = ['running', 'checking', 'queued', 'waiting', 'retry_wait']
            if 'running' in statuses or 'checking' in statuses:
                update_status = 'running'
            elif 'queued' in statuses:
                update_status = 'queued'
            elif 'waiting' in statuses:
                update_status = 'waiting'
            elif 'retry_wait' in statuses:
                update_status = 'retry_wait'
            elif 'published' in statuses:
                update_status = 'published'
            elif 'scheduled' in statuses:
                update_status = 'scheduled'
            else:
                update_status = statuses[0] if statuses else 'idle'
            errors = [str(value.get('last_error') or '') for value in states if value.get('last_error')]
            next_checks = [float(value.get('next_check') or 0) for value in states if float(value.get('next_check') or 0) > 0]
            return dict(
                status=update_status,
                active=update_status in active,
                attempt=max((int(value.get('attempt') or 0) for value in states), default=0),
                lastCheckedAt=max((float(value.get('updated') or 0) for value in states), default=0),
                nextCheckAt=min(next_checks, default=0),
                lastRefreshError='; '.join(errors)[:500],
            )

        slots = {}
        default_scope_match = _default_display_scope(ui_scope)
        for slot in slot_registry():
            exact = period_items.get(slot['stage'])
            item = exact or stage_items.get(slot['stage'])
            context_period = periods.normalise(((item or {}).get('context') or {}).get('period'))
            same_period = bool(requested_period and context_period == requested_period
                               and period_only_scope)
            update = refresh_for(slot, item, requested_period,
                                 exact=bool(exact))
            payload = publication_payload(project_card(item, slot['slotId']))
            delivery = card_delivery_state(payload, slot['slotId'])
            status = 'ready' if delivery['renderable'] else 'missing'
            slots[slot['slotId']] = dict(
                **slot,
                status=status,
                contentStatus=delivery['status'],
                contentComplete=delivery['complete'],
                contentGaps=delivery['gaps'],
                evidenceCount=delivery['evidenceCount'],
                riskFindingCount=delivery['riskFindingCount'],
                generatedAt=float((item or {}).get('updatedAt') or 0),
                dataAsOf=float(((item or {}).get('context') or {}).get('updatedAt') or
                               (item or {}).get('updatedAt') or 0),
                lastSuccessfulPublication=payload,
                lastSuccessfulAt=float((item or {}).get('updatedAt') or 0),
                scopeMatch=bool(exact) or same_period or (
                    not requested_period and default_scope_match),
                periodMatch=bool(exact),
                displayScope=('default' if is_default_scope else 'period') if exact
                             else ('default' if item else ''),
                refreshStatus=update['status'],
                lastRefreshError=update['lastRefreshError'],
                update=update,
                payload=payload,
            )

        expected = len(slots)
        ready = sum(1 for item in slots.values() if item['status'] == 'ready')
        matched = [value['scopeMatch'] for value in slots.values()
                   if value['status'] == 'ready']
        scope_match = bool(matched) and all(matched)
        has_period = any(value['periodMatch'] for value in slots.values()) and not is_default_scope
        complete = sum(1 for item in slots.values() if item['contentComplete'])
        limited = sum(1 for item in slots.values() if item['contentStatus'] == 'limited')
        missing = expected - ready
        updating = sum(1 for item in slots.values() if item['update']['active'])
        version = digest([
            (slot_id, value['status'], value['contentStatus'], (value.get('payload') or {}).get('id', ''),
             float((value.get('payload') or {}).get('updatedAt') or 0))
            for slot_id, value in sorted(slots.items())
        ])
        checked = max((value['update']['lastCheckedAt'] for value in slots.values()), default=0)
        next_check = min((value['update']['nextCheckAt'] for value in slots.values()
                          if value['update']['nextCheckAt'] > 0), default=0)
        errors = [value['lastRefreshError'] for value in slots.values() if value['lastRefreshError']]
        return dict(
            scopeKey=(ui_scope if ui_scope == 'default' else digest({'id': identity, 'scope': ui_scope})),
            requestedScope=ui_scope,
            requestedPeriod=requested_period,
            scopeMatch=scope_match,
            displayScope='period' if has_period else ('default' if slots and ready else ''),
            registryVersion=REGISTRY_VERSION,
            contractVersion=CONTRACT,
            version=version,
            expectedCount=expected,
            readyCount=ready,
            renderableCount=ready,
            publishedCount=ready,
            completeCount=complete,
            limitedCount=limited,
            incompleteCount=ready-complete,
            targetCount=expected,
            missingCount=missing,
            updatingCount=updating,
            riskCounts=summarize_risk_counts(slots),
            generatedAt=max((value['generatedAt'] for value in slots.values()), default=0),
            dataAsOf=max((value['dataAsOf'] for value in slots.values()), default=0),
            update=dict(status='running' if updating else ('retry_wait' if errors else 'idle'),
                        lastCheckedAt=checked, nextCheckAt=next_check,
                        error='; '.join(errors)[:500]),
            slots=slots,
        )

    @router.post('/ai-tables/{table_key}/query')
    def query_ai_table(table_key:str, req:TableQuery):
        if main_context is None or data_mode()!='ap':raise HTTPException(409,'AI表格仅支持主服务实时AP路线')
        spec=TABLE_SPECS.get(table_key)
        if spec is None:raise HTTPException(404,'未知的AI表格')
        try:
            payload=build_ap_query(table_key,req)
        except (ValueError,TypeError) as exc:
            diagnostic=record_failure(store(),exc,phase='request_validation',identity=req.id,stage=spec['stage'])
            raise HTTPException(422,str(exc),headers={'X-Cockpit-Diagnostic-Id':diagnostic['diagnosticId']}) from None
        scope_key=table_scope_key(req.ui_scope)
        cache_key=table_cache_key(req.id,table_key,scope_key,payload)
        cached=store().get_ai_table_snapshot(cache_key,req.id,table_key,scope_key)
        default_scope=scope_key in ('','default') or _default_display_scope(scope_key)
        period_only_scope=default_scope or periods.scope_is_period(scope_key)
        requested_period=((periods.normalise(req.period) or _read_period(scope_key, req.period))
                          if period_only_scope else '')
        card=None
        analysis_scope='none'
        period_card=(period_publication(req.id,spec['stage'],scope_key,period=requested_period,
                                        compact=False)
                     if requested_period else None)
        if period_card:
            card=period_card
            analysis_scope='period'
        elif default_scope:
            try:
                card=period_default_cards(req.id,spec['page'],False).get(spec['stage'])
                analysis_scope='default' if card else 'none'
            except Exception:
                card=None
        else:
            try:
                # A custom scope may already have its own complete page
                # publication.  Use that exact card so table facts and AI
                # annotations share one business range; never borrow the
                # preheated default card for a different filter.
                snapshot=publication_lookup(req.id,spec['page'],scope_key).get('snapshot') or {}
                card=(snapshot.get('items') or {}).get(spec['stage'])
                analysis_scope=scope_key if card else 'none'
            except Exception:
                card=None

        def response_for(rows,total,*,cache_status,generated_at=0):
            annotated,meta=annotate_rows(table_key,rows,card)
            meta.update(
                cacheStatus=cache_status,
                generatedAt=float(generated_at or 0),
                scopeKey=scope_key,
                scopeMatch=default_scope or bool(period_card),
                analysisScopeMatch=bool(card),
                analysisScope=analysis_scope,
                analysisPeriod=requested_period if period_card else '',
                mappingVersion=TABLE_MAPPING_VERSION,
                source='api-cache' if cache_status=='hit' else meta.get('source','ap+structured-analysis'),
            )
            return dict(rows=annotated,total=total if total is not None else len(annotated),meta=meta)

        if req.cache_only:
            if cached is None:
                return response_for([],0,cache_status='missing')
            return response_for(cached.get('rows') or [],cached.get('total'),
                                cache_status='hit',generated_at=cached.get('createdAt'))

        with diagnostic_scope(stage=spec['stage']):
            receipt=query_receipt(req.id,'analysis',payload)
        try:
            rows,total=result_rows(receipt['response'])
        except ValueError as exc:
            diagnostic=record_failure(store(),exc,phase='ap_response',identity=req.id,stage=spec['stage'])
            raise HTTPException(502,str(exc),headers={'X-Cockpit-Diagnostic-Id':diagnostic['diagnosticId']}) from None
        cached_body=dict(rows=rows,total=total,createdAt=time.time(),query=payload)
        store().save_ai_table_snapshot(cache_key,req.id,table_key,scope_key,cached_body)
        return response_for(rows,total,cache_status='refreshed',generated_at=cached_body['createdAt'])

    def preheat_ai_table(identity:int, table_key:str):
        """Persist the same default table query the browser will ask for."""
        return preheat_table(store(),identity,table_key,query_receipt)

    def preheat_ai_tables():
        for identity in (1,2):
            for table_key in TABLE_SPECS:
                try:
                    preheat_ai_table(identity,table_key)
                except Exception as exc:
                    print(f'[cockpit-table-preheat] {identity}/{table_key}: {exc}')

    @router.get('/page')
    def published_page(id:int=1,page:Literal['overview','operations','analysis']='overview',uiScope:str='default'):
        if id not in (1,2) or not 0<len(uiScope)<=16000:raise HTTPException(422,'无效页面范围')
        return publication_lookup(id, page, uiScope)

    @router.post('/page')
    def publish_page(req:PageRequest):
        if main_context is None or data_mode()!='ap':raise HTTPException(409,'整页缓存仅支持主服务实时AP路线')
        config=get_gateway().config
        key=page_scope(config,req.id,req.page,req.uiScope)
        try:
            page=build_page(req,store(),config,data_source='ap')
        except Exception as exc:
            diagnostic=record_failure(store(),exc,phase='page_publication',identity=req.id)
            if isinstance(exc,HTTPException):
                exc.headers={**(exc.headers or {}),'X-Cockpit-Diagnostic-Id':diagnostic['diagnosticId']}
            raise
        if key!=page_scope(config,req.id,req.page,req.uiScope):raise HTTPException(409,'AP认证配置已变化，保留原版本')
        accepted=store().publish_page(key,page)
        return dict(accepted=accepted,snapshot=page if accepted else store().published_page(key))

    @router.post('/page/lookup')
    def lookup_page(req:PageLookup):
        return publication_lookup(req.id, req.page, req.uiScope)

    def cards_version(items):
        # Operations and penetration pages publish AI cards without a whole-page
        # snapshot, so the browser needs a version for those cards too.
        return digest(sorted((stage,(item or {}).get('id',''),float((item or {}).get('updatedAt') or 0))
                             for stage,item in items.items()))

    @router.get('/publications/status')
    def publication_update(id:int=1,page:Literal['overview','operations','analysis']='overview',uiScope:str='default'):
        if id not in (1,2) or not 0<len(uiScope)<=16000:raise HTTPException(422,'无效页面范围')
        lookup=publication_lookup(id,page,uiScope)
        snapshot=lookup.get('snapshot') or lookup.get('displaySnapshot')
        items=published_default(id,'main',page,False)['items'] if main_context is not None else {}
        is_default_scope=uiScope in ('','default') or _default_display_scope(uiScope)
        period_only_scope=is_default_scope or periods.scope_is_period(uiScope)
        requested_period=_read_period(uiScope) if period_only_scope else ''
        period_items={}
        if requested_period and period_only_scope:
            for stage in set(target_stages(page)):
                card=period_publication(id,stage,uiScope,period=requested_period)
                if card:period_items[stage]=card
        if period_items:
            items={**items,**period_items}
        status=lookup.get('status') or {}
        # Operations/penetration cards are published independently of a
        # whole-page snapshot.  Their aggregate state is the page's real
        # refresh state; otherwise the page would stay "updating" forever after
        # a successful card refresh.
        if items and not lookup.get('snapshot') and not lookup.get('displaySnapshot'):
            card_status=stage_card_status(store(),id,page)
            if card_status:status=card_status
        # An exact period card owns its own status.  Only tasks for that period
        # and its stages may make it look active; the current month or a generic
        # default-preheat task must not leak into a frozen historical card.
        exact_period_status = bool(period_items) or (period_only_scope and not is_default_scope)
        if exact_period_status and requested_period:
            period_status=period_card_status(store(),id,page,requested_period)
            if period_status:
                status={**status,**period_status}
        if period_items:
            status=dict(status,period=requested_period,
                        analyzedAt=max((float(value.get('updatedAt') or 0)
                                        for value in period_items.values()),default=0))
        payload=dict(id=id,page=page,uiScope=uiScope,
                     snapshotVersion='' if period_items else (snapshot or {}).get('version',''),
                     cardsVersion=cards_version(items),
                     period=requested_period,periodMatch=bool(period_items),
                     displayStale=(False if period_items else
                                   (bool(items) if period_only_scope and not is_default_scope
                                    else lookup.get('displayStale',False))))
        payload.update(status)
        if period_only_scope:
            payload['period']=requested_period
        payload['periodMatch']=bool(period_items)
        return payload

    @router.get('/publications/period-coverage')
    def publication_period_coverage(periods:str=''):
        from .periods import period_catalog
        from .refresh import period_coverage
        catalog=[item.strip() for item in periods.split(',') if item.strip()] or period_catalog()
        data_identity=(get_gateway().config.identity()
                       if data_mode()=='ap' and main_context is not None else None)
        return period_coverage(store(), catalog, data_identity=data_identity)

    @router.get('/publications/cards')
    def publication_cards(id:int=1,page:Literal['overview','operations','analysis']='overview'):
        if id not in (1,2):raise HTTPException(422,'无效身份')
        from .cards import CONTRACT
        items=period_default_cards(id,page)
        return dict(items=items,cardContract=CONTRACT,cardsVersion=cards_version(items))

    @router.post('/stages/{stage}/preheat')
    def preheat_stage(stage: Literal['opportunity', 'order', 'shipment'], req: PageLookup):
        if req.uiScope != 'default':
            raise HTTPException(422, '只允许默认口径定向预热')
        from .combined import cached_stage_request
        from .dashboard_source import page_analysis_context
        cards = {}
        for page_name in ('operations', 'analysis'):
            cards.update(published_default(req.id, 'main', page_name, False)['items'])
        try:
            body = cached_stage_request(store(), req.id, stage, cards.get(stage) or {})
            resolved = page_analysis_context(body, store(), resolve_fallback=False, allow_expired=True)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        resolved['dataBasis'] = '按新交付规则分析已保存环节凭据；未额外查询AP/PG，观察时间以原记录为准'
        return start_analysis(AnalysisRequest(**body), resolved=resolved)

    @router.post('/quotation/preheat')
    def preheat_quotation(req: PageLookup):
        if req.page != 'operations' or req.uiScope != 'default':
            raise HTTPException(422, '当前仅支持默认报价口径')
        from .combined import cached_quotation_request
        from .dashboard_source import page_analysis_context
        card = published_default(req.id, 'main', 'operations', False)['items'].get('quotation')
        try:
            body = cached_quotation_request(store(), req.id, card or {})
            resolved = page_analysis_context(body, store(), resolve_fallback=False, allow_expired=True)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        resolved['dataBasis'] = '运营头盔图报价办理状态的已保存AP响应，未额外取数'
        return start_analysis(AnalysisRequest(**body), resolved=resolved)

    @router.post('/combined/preheat')
    def preheat_combined(req: PageLookup):
        if req.page != 'analysis' or req.uiScope != 'default':
            raise HTTPException(422, '当前仅支持默认口径共同分析')
        from .combined import cached_combined_request, published_period_stage_cards
        from .dashboard_source import page_analysis_context
        period = periods.default_period()
        data_identity = get_gateway().config.identity() if data_mode() == 'ap' else None
        cards = published_period_stage_cards(store(), req.id, period,
                                             data_identity=data_identity)
        if len(cards) < 2:
            raise HTTPException(409, '等待同期间商机、订单和发货分析完成后再生成共同分析')
        try:
            body = cached_combined_request(store(), req.id, cards, period=period)
            resolved = page_analysis_context(body, store(), resolve_fallback=False, allow_expired=True)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        resolved['dataBasis'] = '跨环节已保存AP响应联合分析；未重新查询AP或数据库，取数时间以各凭据为准'
        return start_analysis(AnalysisRequest(**body), resolved=resolved)

    @router.get('/ai-publications')
    def ai_publications(id:int=1,uiScope:str='default',scopeKey:str=''):
        if id not in (1,2):raise HTTPException(422,'无效身份')
        scope=(scopeKey or uiScope or 'default').strip()
        if not 0<len(scope)<=16000:raise HTTPException(422,'无效发布范围')
        return slot_publications(id,scope)

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
            expires=0 if req.uiScope=='default' else custom_refresh_expiry()
            queued=store().request_refresh(
                scope, business_key=refresh_business_key('page',req.id,req.page,
                                                         ui_scope=req.uiScope),
                config_version=config_version(), expires=expires)
            return dict(queued=queued,scope=scope,status='waiting' if queued else 'running',kind='page')
        # Operations and penetration pages may have published AI cards without
        # ever forming a whole-page snapshot.  Refresh those cards instead of
        # queueing a page scope that has no query plan.
        targets=[view_target_scope(view_key,stage) for view_key,stage,analysis in store().default_views(limit=2000)
                 if req.uiScope=='default'
                 and (analysis.get('context') or {}).get('id')==req.id
                 and (analysis.get('context') or {}).get('page')==req.page
                 and view_scope(analysis.get('context') or {})==view_key]
        if targets:
            contexts={view_target_scope(view_key,stage):(view_key,stage,analysis)
                      for view_key,stage,analysis in store().default_views(limit=2000)}
            queued=[]
            for target in dict.fromkeys(targets):
                _key,stage,analysis=contexts[target]
                context=analysis.get('context') or {}
                if store().request_refresh(
                        target, business_key=refresh_business_key(
                            'view',req.id,context.get('page') or req.page,stage),
                        config_version=config_version(), expires=0):
                    queued.append(target)
            return dict(queued=bool(queued),scope=scope,status='waiting' if queued else 'running',
                        kind='views',targets=len(set(targets)))
        raise HTTPException(409,'该范围还没有可复核的查询计划，请先在页面完成取数后再刷新')

    @router.get('/startup')
    def startup(id:int=1,page:Literal['overview','operations','analysis']='overview'):
        caps=engines();lookup=publication_lookup(id,page,'default')
        # Return every saved slot card, not only the active tab.  The SDK keeps
        # all three tabs mounted while routes change, so a preloaded card makes
        # tab switches instant and prevents opening a tab from starting a new
        # model call.  Opening a page never starts an analysis by itself.
        cards_by_page={}
        if caps['default']=='main' and main_context is not None:
            cards_by_page={name:period_default_cards(id,name) for name in PAGES}
        cards={}
        for page_cards in cards_by_page.values():
            for stage,item in page_cards.items():
                current=cards.get(stage)
                if current is None or float((item or {}).get('updatedAt') or 0)>=float(current.get('updatedAt') or 0):
                    cards[stage]=item
        return dict(engines=caps,dataConfig=data_config(),cards=cards,
                    cardsByPage=cards_by_page,cardsVersion=cards_version(cards),**lookup)

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

    @router.get('/diagnostics')
    def diagnostics(id:int=1,stage:str|None=None,limit:int=20):
        if id not in (1,2) or limit<1 or limit>100 or (stage is not None and stage not in NAMES):
            raise HTTPException(422,'Invalid diagnostic filters')
        return dict(items=store().list_diagnostics(id,stage=stage,limit=limit))

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
        get_analysis(aid)
        return cancel_analysis_job(aid)

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
    def draft(aid:str,req:DraftRequest|None=None):
        item=get_analysis(aid)
        if item["status"] not in {"completed","limited"}:raise HTTPException(409,"只能基于已完成或受限分析生成任务令草稿")
        req=req or DraftRequest()
        if req.id is not None and req.id!=context_id(item["context"]):
            raise HTTPException(403,"建议不属于当前分析身份")
        if not item["result"].get("recommendations"):
            raise HTTPException(409,"当前缺少明确核查对象或必要口径，暂不能生成任务草稿")
        try:
            return store().draft(item,req.recommendationIds)
        except ValueError as exc:
            raise HTTPException(409,str(exc))

    @router.post("/tasks/{tid}/dispatch")
    def dispatch_task(tid:str, req:TaskDispatch):
        item=store().get_task(tid)
        if not item:raise HTTPException(404,"任务不存在")
        context=item.get("context") or {}
        if int(context.get("id") or 0)!=req.id:raise HTTPException(403,"任务不属于当前身份")
        if item.get('contractVersion')=='cockpit-task-order-v2':
            pending=[str(measure.get('id')) for measure in item.get('measures') or []
                     if not measure.get('ownerConfirmed') or not measure.get('deadlineConfirmed')]
            if pending:
                raise HTTPException(409,"请先确认责任角色和期限："+'、'.join(pending))
        if item.get("status")!="draft":raise HTTPException(409,"任务令已下发，不能重复发送；如需补发请新建任务令")
        analysis=get_analysis(str(item.get("analysisId") or ""))
        result=analysis.get("result") or {}
        actions=[]
        evidence="\n".join(result.get("limitations") or [])[:4000]
        from .deadline import dispatch_deadline
        for measure in item.get("measures") or []:
            try:
                due_at = dispatch_deadline(measure.get('deadline'))
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            action_id=f"{tid}-{measure.get('id')}"
            content="\n".join([
                f"任务令：{item.get('title','')}",
                f"类型：{'核查任务' if measure.get('actionType')=='investigation' else '处置任务'}",
                f"目标：{item.get('goal','')}",
                f"措施：{measure.get('action','')}",
                f"责任角色：{measure.get('owner','')}",
                f"期限：{measure.get('deadline','')}",
                f"验收：{measure.get('acceptance','')}",
                f"关联证据：{'、'.join(measure.get('evidenceIds') or []) or '历史草稿未提供'}",
            ])
            actions.append(dict(
                id=action_id, actionId=action_id, itemType="TODO",
                dispatchTool="TaskOrderCreate", title=measure.get("action") or "发货风险处置",
                content=content, evidence=evidence, ownerName=measure.get("owner",""),
                dueAt=due_at, severity="MEDIUM", scenario="COCKPIT",
                category="智能分析任务令",
            ))
        if not actions:raise HTTPException(409,"草稿没有可下发措施")
        recipients=[x.strip() for x in (os.getenv('COCKPIT_TASK_ORDER_RECIPIENTS') or '18837823993').split(',') if x.strip()]
        if task_dispatcher is not None:
            results=task_dispatcher(actions=actions, recipients=recipients, identity=req.id)
        else:
            from ..process360.identity import PrincipalScope
            from ..process360.service import Process360Service
            from ..process360.dispatch import dispatch_canvas_action
            service=Process360Service(cwd=get_cwd())
            poc=PrincipalScope.poc()
            principal=dict(poc.to_dict())
            # This endpoint is only reached after an explicit cockpit click.
            # The server owns the recipient and never accepts a phone from the
            # browser; keep the principal server-resolved as well.
            principal.update(canDispatch=True, source="cockpit-click-authorized")
            results=[dispatch_canvas_action(service, action=action, recipients=recipients,
                                            principal=principal, expected_item_type="TODO", retry=req.retry)
                     for action in actions]
        accepted=sum(1 for value in results if value.get("accepted") is True)
        if accepted==len(results):
            try:item=store().mutate_task(tid,item["revision"],"issue",dict(dispatch=results))
            except (KeyError,ValueError):pass
        return dict(accepted=accepted==len(results),acceptedCount=accepted,total=len(results),
                    results=results,task=item,message=("任务令已下发" if accepted==len(results)
                                                       else "部分任务令未下发，请查看回执后重试"))

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
            cadence = analysis_cadence()
            manager = RefreshManager(
                store(), config,
                lambda identity, kind, payload: query_receipt(identity, kind, payload)['response'],
                start_refresh_analysis,
                interval=int(os.getenv('COCKPIT_REFRESH_INTERVAL_SECONDS', '900')),
                timeout=int(os.getenv('COCKPIT_REFRESH_TIMEOUT_SECONDS', '1200')),
                analysis_interval=cadence['minIntervalSeconds'],
                coalesce_seconds=cadence['coalesceSeconds'],
                cancel_analysis=cancel_analysis_job)
            scheduler = RefreshScheduler(
                manager, store(),
                scan_seconds=int(os.getenv('COCKPIT_REFRESH_SCAN_SECONDS', '20')),
                scope_limit=int(os.getenv('COCKPIT_REFRESH_SCOPE_LIMIT', '1')))
            scheduler.start()
            threading.Thread(target=preheat_ai_tables,daemon=True,
                             name='cockpit-ai-table-preheat').start()
    except Exception as exc:
        # A scheduler/configuration failure must not prevent the dashboard from
        # serving its last published version; it is reported in the app log.
        print(f'[cockpit-refresh] disabled: {exc}')
    router._cockpit_refresh_scheduler = scheduler
    return router
