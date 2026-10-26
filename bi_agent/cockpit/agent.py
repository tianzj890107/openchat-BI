"""Bounded evidence-first agent using the main service's model provider.

The model must query the scoped evidence tool before submitting prose. It
cannot issue tasks, execute SQL, change data, or manufacture numeric cards.
"""
from __future__ import annotations
import json
import os
import threading
import time
from typing import Annotated, Literal
from pydantic import BaseModel, Field, ConfigDict
from open_claude.tools import register_tool
from bi_agent.llm.provider import stream_message

TOOL="CockpitEvidenceQuery"
SCHEMA=dict(name=TOOL,description="读取当前驾驶舱快照的事实、异常记录和证据；不能改变角色、范围或数据。",input_schema={"type":"object","properties":{"section":{"type":"string","enum":["facts","records","causes","all"]}},"required":["section"],"additionalProperties":False})
# Registration only installs a schema. Execution is request-local below.
register_tool(SCHEMA,lambda *_: "此工具只能在驾驶舱分析请求内使用")

class StrictModel(BaseModel):
    model_config=ConfigDict(extra="forbid")

class Cause(StrictModel):
    id:str=Field(min_length=1,max_length=80)
    title:str=Field(min_length=1,max_length=80)
    description:str=Field(min_length=1,max_length=320)
    status:Literal["supported","hypothesis"]
    evidenceIds:list[str]=Field(min_length=1,max_length=20)

class Recommendation(StrictModel):
    id:str=Field(min_length=1,max_length=80)
    causeIds:list[str]=Field(min_length=1,max_length=20)
    action:str=Field(min_length=1,max_length=160)
    ownerRole:str=Field(min_length=1,max_length=40)
    deadlineDays:int=Field(ge=1,le=365)
    acceptance:str=Field(min_length=1,max_length=180)
    detail:str=Field(default="",max_length=600)

class Result(StrictModel):
    summary:str=Field(min_length=1,max_length=800)
    causes:list[Cause]=Field(min_length=1,max_length=8)
    recommendations:list[Recommendation]=Field(min_length=1,max_length=8)
    limitations:list[Annotated[str,Field(min_length=1,max_length=300)]]=Field(min_length=1,max_length=10)


def validate_result(raw, evidence, seen):
    value=Result.model_validate(raw).model_dump()
    available={x["id"] for x in evidence["evidence"]}
    causes={x["id"] for x in value["causes"]}
    if len(causes)!=len(value["causes"]):raise ValueError("原因 ID 重复")
    if len({x["id"] for x in value["recommendations"]})!=len(value["recommendations"]):raise ValueError("建议 ID 重复")
    for cause in value["causes"]:
        if not set(cause["evidenceIds"]) <= available & seen:raise ValueError("原因引用未查询或不存在的证据")
        if cause["status"]=="supported" and not any(x in {r["id"] for r in evidence["records"] if r.get("causeSupport",True)} for x in cause["evidenceIds"]):
            raise ValueError("已支持原因必须引用具体处理记录，汇总指标不能证明原因")
    for action in value["recommendations"]:
        if not set(action["causeIds"]) <= causes:raise ValueError("建议引用未知原因")
    # Limitations are server-owned and cannot be removed by model output.
    value["limitations"]=list(dict.fromkeys(evidence["limitations"]+value["limitations"]))
    return value


def run_analysis(evidence, context, cancel, on_progress, provider=stream_message):
    prompt='''你是储能经营驾驶舱分析员。先调用 CockpitEvidenceQuery 取证，再仅返回 JSON，不要 Markdown。
所有数据是演示数据。不要发明数据、因果、人员、外部信息或已实现收益。只分析当前环节和筛选范围。
汇总指标不能证明根因；supported 只表示演示处理记录支持，不是实际业务验证；推断标为 hypothesis。
数值事实由服务端卡片展示，正文不要重复数字或自行预测。
输出必须短而可执行，建议按原型“措施 / 责任角色 / 期限 / 验收”呈现，详细背景不得塞进 action。
输出字段严格为：summary（不超过200字）；causes 数组 [{id,title（不超过24字）,description（不超过100字）,status:"supported"或"hypothesis",evidenceIds:[已查询证据ID]}]；
recommendations 数组 [{id,causeIds:[原因ID],action（不超过50字）,ownerRole（只写一个责任角色，不超过20字）,deadlineDays（1-365的整数，预计完成工作日）,acceptance（不超过50字）,detail（可选的补充说明，不超过200字）}]；
limitations 字符串数组（每项不超过80字）。禁止输出额外字段。每项建议引用原因。证据不足要直说并提出核实动作。'''
    if evidence.get('sourceMode')=='service':
        prompt=prompt.replace('所有数据是演示数据。','证据来自主服务本轮真实查询的冻结材料，不得冒充新查询；context中的旧period和department字段只作协议标签，实际范围以证据中的AP原始请求为准；causeSupport=false的原始行不能证明因果关系，只能形成待验证假设。')
    messages=[{"role":"user","content":json.dumps(dict(context=context,request="诊断当前环节风险，给出可追溯原因和具体改善建议"),ensure_ascii=False)}]
    seen=set(); started=time.monotonic();events=[]
    for iteration in range(6):
        if cancel.is_set():raise InterruptedError("分析已停止")
        if time.monotonic()-started>150:raise TimeoutError("分析超过时间预算，请重试")
        on_progress("读取证据" if not seen else "分析原因与改善措施",events)
        text=[];tools=[];blocks=[]
        for event in provider(messages,prompt,[TOOL],os.environ.get("COCKPIT_MODEL_KEY","team-configured"),4096,.2,False,cancel_event=cancel):
            if cancel.is_set():raise InterruptedError("分析已停止")
            if time.monotonic()-started>150:raise TimeoutError("分析超过时间预算")
            if event["type"]=="error":raise RuntimeError("模型服务调用失败，请检查主服务模型配置后重试")
            if event["type"]=="text_delta":text.append(event.get("text",""))
            if event["type"]=="tool_use_end":tools.append(event)
        if text:blocks.append({"type":"text","text":"".join(text)})
        for t in tools:blocks.append({"type":"tool_use","id":t["id"],"name":t["name"],"input":t.get("input",{})})
        messages.append({"role":"assistant","content":blocks or [{"type":"text","text":""}]})
        if tools:
            replies=[]
            for tool in tools:
                section=tool.get("input",{}).get("section","all")
                if tool["name"]!=TOOL or section not in {"facts","records","causes","all"}:
                    result={"error":"工具或参数无效"}
                else:
                    # Keep tool context bounded; the full list stays available in the UI.
                    records=evidence["records"]
                    sample=records if len(records)<=24 else [records[round(i*(len(records)-1)/23)] for i in range(24)]
                    identifiers={r["id"] for r in sample}|{f["id"] for f in evidence["facts"]}
                    selected=[x for x in evidence["evidence"] if x["id"] in identifiers]
                    subset=sample if section=="records" else evidence.get(section,[])[:24]
                    result={**evidence,"records":sample,"evidence":selected} if section=="all" else {section:subset,"evidence":selected,"limitations":evidence["limitations"]}
                    result["recordWindow"]="最多均匀抽取24条演示处理记录；样本不可外推比例，汇总事实覆盖全部当前范围"
                    seen.update(x["id"] for x in result["evidence"])
                    events.append(dict(tool=TOOL,section=section,evidenceCount=len(seen)))
                replies.append({"type":"tool_result","tool_use_id":tool["id"],"content":json.dumps(result,ensure_ascii=False)})
            messages.append({"role":"user","content":replies});continue
        try:
            if not seen:raise ValueError("请先调用取证工具")
            raw="".join(text).strip()
            if raw.startswith("```"):raw=raw.split("\n",1)[1].rsplit("```",1)[0]
            result=validate_result(json.loads(raw),evidence,seen)
            on_progress("证据引用与结构校验通过",events)
            return result,events
        except (ValueError,TypeError) as exc:
            messages.append({"role":"user","content":"交付校验未通过："+str(exc)[:1200]+"。请修正 JSON，证据必须真实查询。"})
    raise RuntimeError("分析未能通过证据与结构校验，请重试")
