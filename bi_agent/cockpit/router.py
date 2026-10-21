"""Cockpit API: read-only demo source, bounded analysis jobs, simulated tasks."""
from __future__ import annotations
import hashlib
import json
import threading
from html import escape
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, ConfigDict
from .data import DemoSource, DEPARTMENTS, PERIODS, NAMES
from .store import Store
from .agent import run_analysis
from .metadata import build_bundle
from .prototype import PrototypeSource

class Context(BaseModel):
    model_config=ConfigDict(extra="forbid")
    role:Literal["president","analyst"]="president"
    period:Literal["2025-10","2025-09"]="2025-10"
    department:Literal["全部产品部","AIDC产品部","国内电力产品部","国际电力产品部"]="全部产品部"
    stage:Literal["opportunity","guidance","quotation","technical","bid","order","shipment"]="shipment"

    source:Literal["demo","prototype"]="demo"

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
    role:Literal["president","analyst"]
    revision:int=Field(ge=1)
    action:Literal["save","issue","accept","feedback","close"]
    title:str=Field(default="",max_length=180)
    goal:str=Field(default="",max_length=2000)
    feedback:str=Field(default="",max_length=3000)
    measures:list[Measure]=Field(default_factory=list,max_length=8)


def build_cockpit_router(get_cwd, runner=run_analysis):
    router=APIRouter(prefix="/api/cockpit",tags=["cockpit"])
    source=DemoSource();stores={};lock=threading.RLock();jobs={};capacity=threading.BoundedSemaphore(3)
    def store():
        path=str(Path(get_cwd()).resolve()/"dataset"/"cockpit"/"history.sqlite3")
        with lock:
            if path not in stores:
                value=Store(Path(path));value.recover();stores[path]=value
            return stores[path]
    def adapter(mode):return PrototypeSource() if mode=="prototype" else source
    def snap(context):
        try:return adapter(context.source).snapshot(context.period,context.department)
        except ValueError as exc:raise HTTPException(422,str(exc))
    def get_analysis(aid):
        value=store().get_analysis(aid)
        if not value:raise HTTPException(404,"分析记录不存在")
        return value
    def context_value(c,s):
        value=c.model_dump(exclude={"refresh"});value.update(stageName=NAMES[c.stage],snapshotId=s["snapshotId"],sourceMode=c.source)
        return value
    def scope(c,s):return hashlib.sha256(json.dumps(context_value(c,s),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    def worker(st,item,evidence,cancel):
        try:
            st.update_analysis(item["id"],status="running",evidence=evidence,progress="读取当前快照")
            def progress(message,events):st.update_analysis(item["id"],progress=message,events=list(events))
            result,events=runner(evidence,item["context"],cancel,progress)
            if cancel.is_set():raise InterruptedError()
            st.update_analysis(item["id"],status="completed",progress="分析完成",result=result,events=events)
        except InterruptedError:
            st.update_analysis(item["id"],status="cancelled",progress="已停止，可重新分析")
        except Exception as exc:
            message=str(exc) if isinstance(exc,(RuntimeError,TimeoutError)) else "分析执行失败，请重试"
            st.update_analysis(item["id"],status="failed",progress="分析未完成",error=message[:600])
        finally:
            with lock:jobs.pop(item["id"],None)
            capacity.release()

    @router.get("/bootstrap")
    def bootstrap():
        return dict(roles=[dict(id="president",name="总裁"),dict(id="analyst",name="分析员")],periods=PERIODS,departments=DEPARTMENTS,
            stages=[dict(id=k,name=v) for k,v in NAMES.items()],sourceMode="demo",supportsLiveSource=False,
            notice="演示数据与模拟任务，不写入业务系统；分析使用主服务模型。分析员对话使用 Fuxi。")

    @router.get("/metadata")
    def metadata():return build_bundle()

    @router.get("/snapshot")
    def snapshot(period:Literal["2025-10","2025-09"]="2025-10",department:Literal["全部产品部","AIDC产品部","国内电力产品部","国际电力产品部"]="全部产品部",source:Literal["demo","prototype"]="demo"):
        return snap(Context(period=period,department=department,source=source))

    @router.get("/evidence")
    def evidence(stage:Literal["opportunity","guidance","quotation","technical","bid","order","shipment"]="shipment",
                 period:Literal["2025-10","2025-09"]="2025-10",department:Literal["全部产品部","AIDC产品部","国内电力产品部","国际电力产品部"]="全部产品部",source:Literal["demo","prototype"]="demo"):
        return adapter(source).evidence(snap(Context(period=period,department=department,source=source)),stage)

    @router.post("/analyses")
    def analyse(req:AnalysisRequest):
        snapshot=snap(req);key=scope(req,snapshot);st=store()
        with lock:
            previous=st.list_analyses(key)
            for item in previous:
                if item["status"] in {"queued","running"} and item["id"] in jobs:return item
                if not req.refresh and item["status"]=="completed":return item
            if not capacity.acquire(blocking=False):raise HTTPException(429,"分析并发已满，请稍后重试")
            try:
                item=st.create_analysis(key,context_value(req,snapshot));cancel=threading.Event();jobs[item["id"]]=cancel
                thread=threading.Thread(target=worker,args=(st,item,adapter(req.source).evidence(snapshot,req.stage),cancel),daemon=True)
                thread.start()
            except Exception:
                jobs.pop(item["id"],None) if 'item' in locals() else None
                capacity.release();raise
        return item

    @router.get("/analyses")
    def history(role:Literal["president","analyst"]="president",period:str|None=None,department:str|None=None):
        # POC roles are presentation context, not authenticated identities.
        return [x for x in store().list_analyses() if x["context"]["role"]==role
            and (period is None or x["context"]["period"]==period) and (department is None or x["context"]["department"]==department)]

    @router.get("/analyses/{aid}")
    def analysis(aid:str):return get_analysis(aid)

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
        if item["status"]!="completed":raise HTTPException(409,"分析尚未完成")
        result=item["result"];ctx=item["context"]
        content=f'<h1>{escape(ctx["stageName"])}分析报告</h1><p>演示数据 · {escape(ctx["period"])} · {escape(ctx["department"])}</p><p>{escape(result["summary"])}</p><h2>原因与证据</h2>'
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
        if req.action in {"issue","close"} and req.role!="president":raise HTTPException(403,"请切换总裁视角确认")
        if req.action in {"accept","feedback"} and req.role!="analyst":raise HTTPException(403,"请切换分析员视角处理")
        payload={"feedback":req.feedback}
        if req.action=="save":
            if not req.title.strip() or not req.goal.strip() or not req.measures:raise HTTPException(422,"请补齐标题、目标及措施")
            payload=dict(title=req.title,goal=req.goal,measures=[x.model_dump() for x in req.measures])
        try:return store().mutate_task(tid,req.revision,req.action,payload)
        except KeyError:raise HTTPException(404,"任务不存在")
        except ValueError as exc:raise HTTPException(409,str(exc))

    return router
