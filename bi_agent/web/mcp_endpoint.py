"""Remote MCP endpoint embedded in the BI agent web service.

This is the Fuxi-facing transport for the existing analysis tools.  It is
intentionally a thin protocol adapter: the tools themselves are the same
executors the web UI uses (``build_source_executors``), so a remote caller
sees the real ontology/metric/chart tools rather than a second orchestration
implementation.

Transport: MCP Streamable HTTP (JSON-RPC over POST, optional SSE framing).
No client credentials are required; the service is expected to sit behind the
company ingress / IP allow-list and uses the same demo2 configuration as the
web application.
"""

from __future__ import annotations

import asyncio
import importlib.util
import hashlib
import json
import logging
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from ..integrations.fuxi_todo import FuxiTodoClient, FuxiTodoError
from ..process360 import tools as process360_tools
from ..process360.execute import _assert_no_phone
from ..process360 import audit as process360_audit
from ..process360.dispatch import dispatch_action, dispatch_draft, execution_key
from ..process360.identity import (
    PrincipalScope,
    active_principal_payload,
    reset_active_principal,
    set_active_principal,
)
from ..process360.request_context import (
    FORBIDDEN_CLIENT_FIELDS,
    active_request_context,
    reject_client_identity_fields,
    reset_request_context,
    resolve_request_context,
    set_request_context,
)
from ..paths import DATASET_DIR, project_path
from ..tools import (
    ask_user,
    build_source_executors,
    chart_multidim_tools,
    chart_tools,
    graph_tools,
    ontology_tools,
    remote_specs,
    sql_tools,
    table_tools,
)
from ..tools import remote_ontology_tools

LOGGER = logging.getLogger(__name__)

Executor = Callable[[dict[str, Any], str], str]

#: Business tools whose identity is always resolved by the server.
PROCESS360_TOOL_NAMES: frozenset[str] = frozenset(process360_tools.EXECUTORS)
SERVER_PRINCIPAL_TOOLS: frozenset[str] = PROCESS360_TOOL_NAMES | {"TaskOrderCreate"}
PLAN_REQUIRED_TOOLS: frozenset[str] = frozenset({
    "Process360Query",
    "Process360Analyze",
    "Process360Draft",
    "Process360Verify",
    "Process360Compare",
    "Process360Structure",
    "Process360ProcessFlow",
    "Process360Progress",
    "Process360Forecast",
    "Process360Solutions",
})

PLAN_TOOL_STAGES = {
    "Process360Query": "S03",
    "Process360Compare": "S03",
    "Process360Structure": "S03",
    "Process360ProcessFlow": "S03",
    "Process360Analyze": "S04",
    "Process360Draft": "S05",
    "Process360Solutions": "S05",
    "Process360Progress": "S06",
    "Process360Verify": "S07",
    "Process360Forecast": "S07",
}

MCP_PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "ontology-analytics-mcp"
SERVER_VERSION = "0.2.0"
SESSION_TTL_SECONDS = 60 * 60

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MCP_PACKAGE = Path(os.environ.get("ONTOLOGY_MCP_PACKAGE", _REPO_ROOT / "ontology-analytics-mcp"))
_SKILL_ROOT = Path(os.environ.get("ONTOLOGY_SKILL_ROOT", _REPO_ROOT / "ontology-analytics-skill"))
_CANVAS_DIR = DATASET_DIR / "canvas"

_MODULE_CACHE: dict[str, Any] = {}
_MODULE_LOCK = threading.RLock()


def _load_module(name: str, path: Path) -> Any:
    with _MODULE_LOCK:
        cached = _MODULE_CACHE.get(name)
        if cached is not None:
            return cached
        if not path.is_file():
            raise RuntimeError(f"module file not found: {path}")
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load module: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        _MODULE_CACHE[name] = module
        return module


def _fast_tools():
    return _load_module("ontology_mcp_fast_tools", _MCP_PACKAGE / "fast_tools.py")


def _canvas_tools():
    return _load_module("ontology_mcp_canvas_tools", _MCP_PACKAGE / "canvas_tool.py")


def _route_rules():
    return _load_module("ontology_skill_route", _SKILL_ROOT / "scripts" / "route.py")


def _gate_rules():
    return _load_module("ontology_skill_gates", _SKILL_ROOT / "scripts" / "gates.py")


ANALYSIS_ROUTE_SCHEMA: dict[str, Any] = {
    "name": "AnalysisRoute",
    "description": (
        "确定性路由：判断问题的分析档位（L1 事实、L2 对比、L3 根因、L4 决策、"
        "L5 预测）、是否需要澄清或拒答，并给出建议工具链。任何经营/财务分析前先调用。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "用户原话"},
            "allowed_tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可选的本轮工具白名单；缺省使用服务端已暴露工具。",
            },
        },
        "required": ["question"],
    },
}

OUTPUT_GATE_SCHEMA: dict[str, Any] = {
    "name": "OutputGateCheck",
    "description": (
        "交付前闸门：检查证据引用、预测披露、图表抑制、只读 SQL 和总额/分月对账。"
        "返回 verdict=pass/warn/reject；reject 时不得把候选结论作为最终交付。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {"type": "string", "description": "候选最终回答"},
            "question": {"type": "string", "description": "用户原话"},
            "forecast_kind": {"type": "string", "enum": ["predictive", "scenario", "stored"]},
            "forecast_assumption": {"type": "string"},
            "sql": {"type": "string", "description": "本轮实际执行的 SQL（如有）"},
            "runId": {"type": "string", "description": "Process360Analyze 的冻结运行；提供时闸门绑定该数据版本"},
            "canvasId": {"type": "string", "description": "CanvasGenerate 返回的 canvasId"},
            "artifactHash": {
                "type": "string",
                "description": "CanvasGenerate 返回的 artifactHash；提供 canvasId 时必填",
            },
            "planId": {"type": "string", "description": "本次分析所属的服务端执行计划"},
            "queryId": {"type": "string", "description": "本次分析消费的服务端查询结果"},
            "deliveryKind": {
                "type": "string",
                "enum": ["analysis_report", "fact_answer"],
                "description": "缺省为 analysis_report，必须有 Canvas 产物；fact_answer 才允许纯文字交付",
            },
            "chart": {"type": "object", "description": "图表工具名和参数"},
            "reconcile": {
                "type": "object",
                "properties": {
                    "parent": {"type": "number"},
                    "children": {"type": "array", "items": {"type": "number"}},
                },
            },
            "claims": {
                "type": "array",
                "items": {"type": "object"},
                "description": "结构化断言列表；有数字结论时建议传入。",
            },
        },
    },
}

TASK_ORDER_CREATE_SCHEMA: dict[str, Any] = {
    "name": "TaskOrderCreate",
    "description": (
        "把用户确认的一条行动建议直接推送到 Fuxi 风险待办。只在用户点击"
        "“发送任务令/转督办”后调用，不要在分析生成阶段自动调用。"
        "Process360 建议卡必须传 draft_id、draft_hash、action_id 和宿主 principal；"
        "标题、正文和场景从服务端可信草稿回读，不采用调用方改写。"
        "recipients_raw 必须是当前用户或责任人的真实手机号；空数组会变成"
        "Fuxi 全员广播，因此本工具拒绝空接收人。调用方不应把手机号写进 HTML 或日志。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action_id": {"type": "string", "description": "行动在 Canvas/会话中的稳定 ID"},
            "draft_id": {"type": "string", "description": "Process360Draft 返回的可信草稿 ID"},
            "draft_hash": {"type": "string", "description": "Process360Draft 返回的草稿签名"},
            "idempotency_key": {"type": "string", "description": "可选持久化幂等键；缺省由 draftId + actionId 生成"},
            "retry": {"type": "boolean", "description": "仅对上次 Fuxi 网络/拒绝失败使用同一幂等键重试"},
            "title": {"type": "string", "description": "旧版通用任务标题；Process360 草稿模式忽略"},
            "content": {"type": "string", "description": "旧版通用任务正文；Process360 草稿模式忽略"},
            "recipients_raw": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string"},
                "description": "接收人手机号；由 Fuxi 宿主提供，禁止模型猜测",
            },
            "severity": {
                "type": "string",
                "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
                "description": "严重程度；缺省按 MEDIUM",
            },
            "due_at": {"type": "string", "description": "ISO 8601 UTC 截止时间，可选"},
            "owner_ref": {"type": "string", "description": "责任人账号，可选"},
            "owner_name": {"type": "string", "description": "责任人姓名，可选"},
            "source_todo_id": {"type": "string", "description": "稳定来源 ID；缺省由 action_id/canvas_id 生成"},
            "canvas_id": {"type": "string", "description": "Canvas 产物 ID，用于幂等"},
            "category": {"type": "string", "description": "Fuxi 分类，缺省为智能分析任务令"},
            "impact_text": {"type": "string", "description": "影响说明，可选"},
            "evidence": {
                "type": "array",
                "items": {"type": "object"},
                "description": "证据材料，原样写入 Fuxi evidence",
            },
            "caliber_meta": {
                "type": "object",
                "description": "分析来源、指标编码、Artifact URL 等追溯信息",
            },
        },
        "required": ["action_id", "recipients_raw"],
    },
}

#: Tools shown to Fuxi.  Deliberately excludes AnalysisRun (the old one-call
#: wrapper), TodoWrite, AskUser and every raw-SQL/schema tool.
DEFAULT_EXPOSED_TOOLS: tuple[str, ...] = (
    "AnalysisRoute",
    "Ontology-SemanticQuery",
    "Ontology-TermDisambiguate",
    "MetricCalculation",
    "Ontology-RelationQuery",
    "Ontology-EntityDescribe",
    "ListBusinessObjects",
    "Ontology-GraphContext",
    "Ontology-GraphExpand",
    "Ontology-MetricQuery",
    "MetricFactQuery",
    "ChartGenerate",
    "ChartGenerateMultiDim",
    "TableGenerate",
    "CanvasGenerate",
    "TaskOrderCreate",
    "OutputGateCheck",
    "Process360Route",
    "Process360Search",
    "Process360Context",
    "Process360Query",
    "Process360Analyze",
    "Process360Draft",
    "Process360Verify",
    "Process360Plan",
    "Process360Explore",
    "Process360Compare",
    "Process360Structure",
    "Process360ProcessFlow",
    "Process360Progress",
    "Process360Forecast",
    "Process360Solutions",
)

WRITE_TOOLS = frozenset({"TaskOrderCreate"})

#: Even an environment override may not expose these.
MCP_DENIED_TOOLS: frozenset[str] = frozenset({
    "AnalysisRun",
    "TodoWrite",
    "AskUser",
    "Ontology-FactQuery",
    "ListTables",
    "DescribeTable",
})


def _configured_tools() -> tuple[str, ...]:
    raw = (os.environ.get("ONTOLOGY_MCP_EXPOSED_TOOLS") or "").strip()
    if not raw:
        return DEFAULT_EXPOSED_TOOLS
    requested = tuple(item.strip() for item in raw.split(",") if item.strip())
    return tuple(name for name in requested if name not in MCP_DENIED_TOOLS)


def _source_snapshot(source: Any) -> SimpleNamespace:
    fields = (
        "ontology_store", "remote_ontology", "ontology_backend", "ontology_namespace",
        "ontology_path", "db_path", "use_doris", "doris_jdbc_url", "doris_driver",
        "doris_username", "doris_password", "doris_database", "doris_api_url",
        "retrieval_mode", "graph_path",
    )
    return SimpleNamespace(**{name: getattr(source, name, None) for name in fields})


def _source_signature(source: Any) -> tuple[Any, ...]:
    remote = source.remote_ontology
    return (
        id(source.ontology_store),
        remote.repository_id if remote else "",
        str(getattr(remote, "base_url", "") if remote else ""),
        source.ontology_namespace,
        source.ontology_path,
        source.use_doris,
        source.db_path,
        source.doris_api_url,
        source.doris_jdbc_url,
        source.doris_database,
        source.retrieval_mode,
    )


def _tool_schemas(source: Any) -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    for module in (
        ontology_tools, graph_tools, sql_tools, chart_tools,
        chart_multidim_tools, table_tools, ask_user,
    ):
        for schema, _factory in module.SPECS:
            schemas[str(schema["name"])] = schema
    if source.remote_ontology is not None:
        for schema, _executor in remote_specs(source.remote_ontology):
            schemas[str(schema["name"])] = schema
    else:
        # Keep the remote schemas visible before configure()/catalog warm-up;
        # execution still fails closed with tool_not_available if no client is
        # bound to the current source.
        for schema in (
            remote_ontology_tools.ONTOLOGY_QUERY_SCHEMA,
            remote_ontology_tools.TERM_DISAMBIGUATE_SCHEMA,
            remote_ontology_tools.METRIC_LOOKUP_SCHEMA,
            remote_ontology_tools.RELATION_LOOKUP_SCHEMA,
            remote_ontology_tools.ENTITY_DESCRIBE_SCHEMA,
            remote_ontology_tools.LIST_BUSINESS_OBJECTS_SCHEMA,
            remote_ontology_tools.GRAPH_CONTEXT_SCHEMA,
            remote_ontology_tools.GRAPH_EXPAND_SCHEMA,
            remote_ontology_tools.METRIC_DATA_QUERY_SCHEMA,
        ):
            schemas[str(schema["name"])] = schema

    fast = _fast_tools()
    schemas[str(fast.SCHEMA["name"])] = fast.SCHEMA

    canvas_schema, _canvas_factory = _canvas_tools().SPECS[0]
    schemas[str(canvas_schema["name"])] = canvas_schema
    schemas["AnalysisRoute"] = ANALYSIS_ROUTE_SCHEMA
    schemas["OutputGateCheck"] = OUTPUT_GATE_SCHEMA
    schemas["TaskOrderCreate"] = TASK_ORDER_CREATE_SCHEMA
    for schema in process360_tools.SPECS:
        schemas[str(schema["name"])] = schema
    return schemas


def _mcp_tool(schema: dict[str, Any]) -> dict[str, Any]:
    name = schema["name"]
    read_only = name not in WRITE_TOOLS
    return {
        "name": name,
        "description": (schema.get("description") or "").strip(),
        "inputSchema": schema.get("input_schema") or {"type": "object"},
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    }


def _route_executor() -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        del cwd
        question = str(params.get("question") or "").strip()
        if not question:
            return "AnalysisRoute error: question is required"
        allowed = params.get("allowed_tools")
        if not isinstance(allowed, list) or not allowed:
            allowed = list(DEFAULT_EXPOSED_TOOLS)
        decision = _route_rules().decide(question, [str(item) for item in allowed])
        return json.dumps(decision, ensure_ascii=False, indent=2)
    return run


def _gate_executor() -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        payload = dict(params or {})
        canvas_id = str(payload.pop("canvasId", "") or "").strip()
        expected = str(payload.pop("artifactHash", "") or "").strip()
        run_id = str(payload.pop("runId", "") or "").strip()
        plan_id = str(payload.pop("planId", "") or "").strip()
        query_id = str(payload.pop("queryId", "") or "").strip()
        delivery_kind = str(payload.pop("deliveryKind", "") or "analysis_report").strip()
        report = _gate_rules().check(payload)
        hard = list(report.get("hard_issues") or [])
        artifact_record = None
        if delivery_kind not in {"analysis_report", "fact_answer"}:
            hard.append("delivery_kind_invalid")
        if delivery_kind == "analysis_report" and (not canvas_id or not expected):
            hard.append("artifact_reference_required")
        if canvas_id or expected:
            artifact = {"canvasId": canvas_id, "artifactHash": expected}
            target = None
            if canvas_id:
                candidate = (project_path(cwd or os.getcwd(), _CANVAS_DIR) / f"{canvas_id}.html").resolve()
                canvas_dir = project_path(cwd or os.getcwd(), _CANVAS_DIR).resolve()
                if candidate.parent == canvas_dir and candidate.is_file():
                    target = candidate
            if target is None:
                hard.append("artifact_missing")
            else:
                actual = hashlib.sha256(target.read_bytes()).hexdigest()
                artifact["actualHash"] = actual
                if not expected:
                    hard.append("artifact_hash_required")
                elif actual != expected:
                    hard.append("artifact_hash_mismatch")
            report["artifact"] = artifact
        if run_id:
            record = process360_audit.store().get_run(run_id)
            baseline = ((record or {}).get("payload") or {}).get("baseline") or {}
            if not record:
                hard.append("analysis_run_not_found")
            else:
                report["runId"] = run_id
                report["dataSnapshot"] = {
                    key: baseline.get(key)
                    for key in ("baselineHash", "objectSetHash", "complete", "fullObjectCount")
                }
                if baseline and baseline.get("complete") is False:
                    hard.append("frozen_baseline_incomplete")
        if hard:
            report["hard_issues"] = sorted(dict.fromkeys(hard))
            report["verdict"] = "reject"
        artifact = report.get("artifact")
        if isinstance(artifact, dict) and artifact.get("actualHash"):
            context = active_request_context()
            artifact_id = uuid.uuid4().hex
            artifact["artifactId"] = artifact_id
            artifact_record = process360_audit.store().save_artifact(
                artifact_id=artifact_id,
                artifact_hash=str(artifact.get("actualHash") or ""),
                request_id=context.request_id if context else "",
                plan_id=plan_id,
                query_id=query_id,
                run_id=run_id,
                tenant=context.tenant_id if context else "",
                principal=context.principal_id if context else "",
                gate_result=report,
            )
            report["artifactRegistry"] = {
                "artifactId": artifact_record.get("id"),
                "checkedAt": artifact_record.get("checked_at"),
            }
        return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    return run


def _task_order_executor() -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        client = FuxiTodoClient()
        draft_id = str(params.get("draft_id") or "").strip()
        if draft_id:
            context = active_request_context()
            if context is None:
                raise ValueError("principal is resolved by the server and is required for dispatch")
            service = process360_tools.Process360Service(cwd=cwd)
            result = dispatch_action(
                service,
                draft_id=draft_id,
                draft_hash=str(params.get("draft_hash") or ""),
                action_id=str(params.get("action_id") or ""),
                request_id=context.request_id,
                recipients=params.get("recipients_raw") or [],
                principal=context.principal.to_dict(),
                retry=bool(params.get("retry")),
                client=client,
            )
            return json.dumps(result, ensure_ascii=False, indent=2)
        meta = params.get("caliber_meta") if isinstance(params.get("caliber_meta"), dict) else {}
        if (
            str(params.get("source") or "") == "boulderai-anaylize-todo"
            or meta.get("dispatchTool") == "TaskOrderCreate"
            or meta.get("scenario")
            or params.get("task_template")
        ):
            raise ValueError("Process360 action requires draft_id, draft_hash, action_id and principal")
        _assert_no_phone(json.dumps({
            key: params.get(key)
            for key in ("title", "content", "impact_text", "owner_name", "owner_ref",
                        "evidence", "caliber_meta")
        }, ensure_ascii=False))
        try:
            result = client.create_todo(
                title=str(params.get("title") or ""),
                content=str(params.get("content") or ""),
                recipients_raw=params.get("recipients_raw") or [],
                action_id=str(params.get("action_id") or ""),
                source_todo_id=str(params.get("source_todo_id") or "").strip() or None,
                canvas_id=str(params.get("canvas_id") or ""),
                severity=params.get("severity"),
                category=params.get("category"),
                due_at=params.get("due_at"),
                owner_ref=params.get("owner_ref"),
                owner_name=params.get("owner_name"),
                impact_text=params.get("impact_text"),
                evidence=params.get("evidence"),
                caliber_meta=params.get("caliber_meta"),
            )
        except FuxiTodoError:
            raise
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        if not result.get("ok"):
            raise FuxiTodoError(
                "Fuxi rejected the task order: "
                + json.dumps(result.get("errors") or [], ensure_ascii=False),
                payload=result,
            )
        return json.dumps(result, ensure_ascii=False, indent=2)
    return run


def _plan_block(tool: str, issue: Mapping[str, Any], *, plan_id: str = "", step_id: str = "") -> str:
    return json.dumps(
        {
            "schema": "process360.result.v1",
            "stage": PLAN_TOOL_STAGES.get(tool, "S00"),
            "status": "needs_clarification",
            "tool": tool,
            "planId": plan_id or None,
            "stepId": step_id or None,
            "gaps": [dict(issue)],
            "limitations": ["计划校验未通过，业务工具未执行。"],
        },
        ensure_ascii=False,
        indent=2,
    )


def _enforce_process360_plan(
    name: str,
    params: dict[str, Any],
    cwd: str,
    context: Any,
) -> str | None:
    if name not in PLAN_REQUIRED_TOOLS:
        return None
    service = process360_tools.Process360Service(cwd=cwd)
    plan_id = str(params.get("planId") or params.get("plan_id") or "").strip()
    step_id = str(params.get("stepId") or params.get("step_id") or "").strip()
    issue = service.validate_plan_step(
        plan_id,
        step_id,
        name,
        str(params.get("scenario") or ""),
        context.principal,
        scope=params.get("scope"),
        require_plan=True,
    )
    if issue:
        return _plan_block(name, issue, plan_id=plan_id, step_id=step_id)
    record = service.store.get_plan(plan_id) or {}
    plan_scope = (record.get("payload") or {}).get("scope")
    if not params.get("scope") and isinstance(plan_scope, dict):
        params["scope"] = dict(plan_scope)
    return None


def _record_plan_step_outcome(name: str, params: Mapping[str, Any], output: str) -> None:
    if name not in PLAN_REQUIRED_TOOLS:
        return
    context = active_request_context()
    if context is None:
        return
    plan_id = str(params.get("planId") or params.get("plan_id") or "").strip()
    step_id = str(params.get("stepId") or params.get("step_id") or "").strip()
    if not plan_id or not step_id:
        return
    try:
        payload = json.loads(output) if isinstance(output, str) else {}
    except ValueError:
        payload = {}
    result_status = str(payload.get("status") or "").lower()
    status = "completed" if result_status in {"ok", "partial", "not_applicable"} else "blocked"
    refs = {
        key: payload.get(key)
        for key in ("queryId", "runId", "planId", "draftId", "baselineId", "actionId")
        if payload.get(key)
    }
    try:
        process360_audit.store().record_plan_step(
            plan_id=plan_id,
            step_id=step_id,
            request_id=context.request_id,
            tool=name,
            status=status,
            input_hash=hashlib.sha256(
                json.dumps(params, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest(),
            refs=refs,
        )
    except Exception:  # noqa: BLE001 - step history is an audit side effect
        return


def _render_executors() -> dict[str, Executor]:
    """Pure render tools: no source, no data binding, always available."""
    executors: dict[str, Executor] = {}
    for module in (chart_tools, chart_multidim_tools, table_tools):
        for schema, factory in module.SPECS:
            executors[str(schema["name"])] = factory()
    return executors


def _build_executors(source: Any, build_doris: Callable[..., Any]) -> dict[str, Executor]:
    doris = (
        build_doris(source.doris_api_url, source.doris_database, source.remote_ontology)
        if source.use_doris else None
    )
    executors: dict[str, Executor] = dict(build_source_executors(
        source.ontology_store,
        source.db_path,
        doris=doris,
        remote_ontology=source.remote_ontology,
    ))
    metric = executors.get("Ontology-MetricQuery")
    if metric is not None:
        executors["MetricFactQuery"] = _fast_tools().make_executor(
            metric, executors.get("Ontology-SemanticQuery")
        )
    executors.update(_render_executors())
    canvas_schema, canvas_factory = _canvas_tools().SPECS[0]
    del canvas_schema
    executors["CanvasGenerate"] = canvas_factory()
    executors["AnalysisRoute"] = _route_executor()
    executors["OutputGateCheck"] = _gate_executor()
    executors["TaskOrderCreate"] = _task_order_executor()
    return executors


class McpRuntime:
    """Protocol state plus a source-bound executor cache."""

    def __init__(self, *, get_source: Callable[[], Any], build_doris: Callable[..., Any],
                 get_cwd: Callable[[], str], executor_factory: Callable[[Any], dict[str, Executor]] | None = None,
                 exposed_tools: tuple[str, ...] | None = None,
                 principal_provider: Callable[[], dict[str, Any]] | None = None) -> None:
        self.get_source = get_source
        self.build_doris = build_doris
        self.get_cwd = get_cwd
        self.executor_factory = executor_factory
        self.principal_provider = principal_provider
        requested = tuple(exposed_tools or _configured_tools())
        self.exposed = tuple(name for name in requested if name not in MCP_DENIED_TOOLS)
        self._sessions: dict[str, float] = {}
        self._lock = threading.RLock()
        self._cache_signature: tuple[Any, ...] | None = None
        self._cache_executors: dict[str, Executor] = {}
        self._cache_schemas: dict[str, dict[str, Any]] = {}
        source_free: dict[str, Executor] = {
            "AnalysisRoute": _route_executor(),
            "OutputGateCheck": _gate_executor(),
            "TaskOrderCreate": _task_order_executor(),
            **_render_executors(),
            **process360_tools.EXECUTORS,
        }
        if executor_factory is None:
            # The real source path builds CanvasGenerate itself; an injected
            # factory stays authoritative for tests and embedders.
            source_free["CanvasGenerate"] = _canvas_tools().SPECS[0][1]()
        self._source_free: dict[str, Executor] = source_free

    def principal_payload(self) -> dict[str, Any]:
        """Server-resolved identity for Process360 business tools."""
        if self.principal_provider is not None:
            resolved = self.principal_provider()
            return dict(resolved) if resolved else {}
        return PrincipalScope.poc().to_dict()

    def missing_executors(self) -> tuple[str, ...]:
        """Declared-but-unroutable tools.  Empty means the registry is sound."""
        try:
            schemas, executors = self._runtime()
        except Exception:  # noqa: BLE001 - source may not be configured yet
            schemas, executors = {}, dict(self._source_free)
        known = set(executors) | set(self._source_free)
        return tuple(
            name for name in self.exposed
            if name in schemas and name not in known
        )

    # -- session lifecycle -------------------------------------------------
    def _prune(self) -> None:
        cutoff = time.monotonic() - SESSION_TTL_SECONDS
        for sid, seen in list(self._sessions.items()):
            if seen < cutoff:
                self._sessions.pop(sid, None)

    def create_session(self) -> str:
        sid = uuid.uuid4().hex
        with self._lock:
            self._prune()
            self._sessions[sid] = time.monotonic()
        return sid

    def touch_session(self, session_id: str) -> bool:
        with self._lock:
            self._prune()
            if session_id not in self._sessions:
                return False
            self._sessions[session_id] = time.monotonic()
            return True

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    # -- tools -------------------------------------------------------------
    def _runtime(self) -> tuple[dict[str, dict[str, Any]], dict[str, Executor]]:
        source = _source_snapshot(self.get_source())
        signature = _source_signature(source)
        with self._lock:
            if signature == self._cache_signature and self._cache_executors:
                return self._cache_schemas, self._cache_executors
        if self.executor_factory is not None:
            executors = dict(self.executor_factory(source))
        else:
            executors = _build_executors(source, self.build_doris)
        schemas = _tool_schemas(source)
        executors = {name: fn for name, fn in executors.items() if name in self.exposed}
        schemas = {name: schema for name, schema in schemas.items() if name in self.exposed}
        with self._lock:
            self._cache_signature = signature
            self._cache_executors = executors
            self._cache_schemas = schemas
        return schemas, executors

    def list_tools(self) -> list[dict[str, Any]]:
        source = _source_snapshot(self.get_source())
        schemas = _tool_schemas(source)
        return [_mcp_tool(schemas[name]) for name in self.exposed if name in schemas]

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        base_url: str = "",
        *,
        conversation_id: str = "",
        request_id: str = "",
    ) -> str:
        if name in MCP_DENIED_TOOLS or name not in self.exposed:
            raise PermissionError(f"tool_not_allowed: {name}")
        if name in self._source_free:
            executor = self._source_free[name]
        else:
            _schemas, executors = self._runtime()
            executor = executors.get(name)
        if executor is None:
            raise LookupError(f"tool_not_available: {name}")
        cwd = self.get_cwd() or os.getcwd()
        params = dict(arguments or {})
        token = None
        plan_block = None
        if name in SERVER_PRINCIPAL_TOOLS:
            reject_client_identity_fields(params)
            context = resolve_request_context(
                principal=self.principal_payload(),
                conversation_id=conversation_id,
                request_id=request_id or uuid.uuid4().hex,
                surface="mcp",
            )
            token = set_request_context(context)
            process360_audit.ensure_request()
            plan_block = _enforce_process360_plan(name, params, cwd, context)
        try:
            if plan_block is not None:
                result = plan_block
                process360_audit.record_step(name, params, result)
            else:
                try:
                    result = executor(params, cwd)
                except Exception as exc:
                    if name in PROCESS360_TOOL_NAMES:
                        process360_audit.record_step(
                            name,
                            params,
                            json.dumps(
                                {
                                    "status": "blocked",
                                    "errorType": type(exc).__name__,
                                },
                                ensure_ascii=False,
                            ),
                        )
                        _record_plan_step_outcome(
                            name,
                            params,
                            json.dumps({"status": "blocked"}, ensure_ascii=False),
                        )
                    raise
                _record_plan_step_outcome(name, params, result)
        finally:
            if token is not None:
                reset_request_context(token)
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        if name == "CanvasGenerate":
            text = _with_artifact_url(text, cwd, base_url)
        return text

    def handle(self, payload: dict[str, Any], session_id: str | None,
               base_url: str) -> tuple[str | None, dict[str, Any] | None]:
        request_id = payload.get("id")
        method = str(payload.get("method") or "")
        params = payload.get("params") or {}

        if method == "initialize":
            sid = session_id or self.create_session()
            requested = params.get("protocolVersion") if isinstance(params, dict) else None
            return sid, _response(request_id, {
                "protocolVersion": requested or MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (
                    "这是硕磐智能分析的远程 MCP。经营/财务数据问题请先调用 "
                    "AnalysisRoute，再按可见工具执行：Ontology-SemanticQuery 确认指标，"
                    "MetricFactQuery 取数与对账，ChartGenerate/TableGenerate 出图/表，"
                    "CanvasGenerate 生成整页 HTML，OutputGateCheck 做交付校验。"
                    "Process360 问题先调用 Process360Route，按 SOP 选择步骤：问数用 Process360Query 后停止，"
                    "诊断用 Process360Analyze，仅明确要求草稿时用 Process360Draft；复验用 "
                    "Process360Verify。任务令只用 TaskOrderCreate，接收手机号由 Fuxi 宿主提供。"
                    "不要调用 AnalysisRun、原始 SQL、TodoWrite 或 AskUser；"
                    "歧义时直接把选项问用户。CanvasGenerate 返回的 Artifact URL 是最终交付链接。"
                ),
            })

        if method.startswith("notifications/"):
            return session_id, None
        if not session_id or not self.touch_session(session_id):
            raise McpHttpError(400, "Mcp-Session-Id header is required")
        if method == "ping":
            return session_id, _response(request_id, {})
        if method == "tools/list":
            return session_id, _response(request_id, {"tools": self.list_tools()})
        if method == "resources/list":
            return session_id, _response(request_id, {"resources": []})
        if method == "prompts/list":
            return session_id, _response(request_id, {"prompts": []})
        if method == "tools/call":
            if not isinstance(params, dict):
                return session_id, _error(request_id, -32602, "tools/call params must be an object")
            name = str(params.get("name") or params.get("tool") or "")
            arguments = params.get("arguments")
            if arguments is None:
                arguments = params.get("params") or {}
            if not isinstance(arguments, dict):
                return session_id, _error(request_id, -32602, "tool arguments must be an object")
            try:
                text = self.call_tool(
                    name,
                    arguments,
                    base_url,
                    conversation_id=session_id or "",
                    request_id=str(
                        request_id if request_id is not None else uuid.uuid4().hex
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                return session_id, _tool_error(request_id, f"{type(exc).__name__}: {exc}"[:800])
            return session_id, _response(request_id, {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            })
        if method == "shutdown":
            return session_id, _response(request_id, {})
        return session_id, _error(request_id, -32601, f"method not found: {method}")


class McpHttpError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_error(request_id: Any, message: str) -> dict[str, Any]:
    return _response(request_id, {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    })


def _with_artifact_url(text: str, cwd: str, base_url: str) -> str:
    try:
        _cleaned, spec = _canvas_tools().extract_canvas_spec(text)
        if not isinstance(spec, dict):
            return text
        saved = str(spec.get("saved_path") or "").strip()
        if not saved:
            return text
        canvas_dir = project_path(cwd, _CANVAS_DIR).resolve()
        path = Path(saved)
        if not path.is_absolute():
            path = Path(cwd) / path
        path = path.resolve()
        if path.parent != canvas_dir or path.suffix.lower() != ".html":
            return text
        base = (os.environ.get("MCP_PUBLIC_BASE_URL") or base_url or "").rstrip("/")
        if not base:
            return text
        url = f"{base}/api/mcp/artifacts/{quote(path.name)}"
        return f"{text}\n\nArtifact URL: {url}"
    except Exception:  # noqa: BLE001
        return text


def _wants_sse(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    return "text/event-stream" in accept and "application/json" not in accept


def _sse(payload: dict[str, Any]) -> StreamingResponse:
    body = f"id: {payload.get('id', '')}\nevent: message\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
    return StreamingResponse(iter([body]), media_type="text/event-stream")


def _authorized(request: Request) -> bool:
    expected = (os.environ.get("ONTOLOGY_MCP_AUTH_TOKEN") or "").strip()
    if not expected:
        return True
    return (request.headers.get("authorization") or "").strip() == f"Bearer {expected}"


def build_mcp_router(*, get_source: Callable[[], Any], build_doris: Callable[..., Any],
                     get_cwd: Callable[[], str],
                     executor_factory: Callable[[Any], dict[str, Executor]] | None = None,
                     exposed_tools: tuple[str, ...] | None = None,
                     request_principal: Callable[[Request], dict[str, Any]] | None = None) -> APIRouter:
    runtime = McpRuntime(
        get_source=get_source,
        build_doris=build_doris,
        get_cwd=get_cwd,
        executor_factory=executor_factory,
        exposed_tools=exposed_tools,
    )
    router = APIRouter()
    principal_for_request = request_principal or (lambda request: runtime.principal_payload())

    def http_context(request: Request, *, surface: str, request_id: str = ""):
        conversation_id = (
            request.headers.get("x-fuxi-conversation-id")
            or request.headers.get("x-conversation-id")
            or ""
        )
        return resolve_request_context(
            principal=principal_for_request(request),
            conversation_id=conversation_id,
            request_id=request_id or uuid.uuid4().hex,
            surface=surface,
        )

    @router.post("/api/process360/task-orders")
    async def process360_task_order(request: Request):
        """Page-initiated dispatch.  Body carries draft references only."""
        if not _authorized(request):
            raise HTTPException(401, "unauthorized")
        try:
            body = await request.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"invalid JSON body: {exc}") from exc
        if not isinstance(body, dict):
            raise HTTPException(400, "body must be an object")
        try:
            reject_client_identity_fields(body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        forbidden_context = set(body) & {"conversationId", "surface", "principalId", "grantScope"}
        if forbidden_context:
            raise HTTPException(
                400,
                "会话与执行上下文由服务端解析；页面不得提交 "
                + ", ".join(sorted(forbidden_context)),
            )
        draft_id = str(body.get("draftId") or "").strip()
        draft_hash = str(body.get("draftHash") or "").strip()
        action_id = str(body.get("actionId") or "").strip()
        request_id = str(body.get("requestId") or uuid.uuid4().hex)
        if not draft_id or not draft_hash or not action_id:
            return JSONResponse(
                {
                    "schema": "process360.dispatch.v1",
                    "status": "blocked",
                    "accepted": False,
                    "message": "缺少 draftId / draftHash / actionId，旧版建议需重新生成",
                    "receipt": None,
                    "draftId": draft_id,
                    "actionId": action_id,
                    "requestId": request_id,
                },
                status_code=200,
            )
        service = process360_tools.Process360Service(cwd=get_cwd() or os.getcwd())
        context = http_context(request, surface="canvas", request_id=request_id)
        token = set_request_context(context)
        process360_audit.ensure_request("canvas")
        try:
            result = await asyncio.to_thread(
                dispatch_draft,
                service,
                draft_id=draft_id,
                draft_hash=draft_hash,
                action_id=action_id,
                request_id=request_id,
            )
        finally:
            reset_request_context(token)
        return JSONResponse(result)

    @router.get("/api/process360/requests/{request_id}")
    def process360_request_trail(request_id: str, request: Request) -> dict[str, Any]:
        """Read the recorded step trail for one Fuxi conversation."""
        if not _authorized(request):
            raise HTTPException(401, "unauthorized")
        context = http_context(request, surface="web")
        token = set_request_context(context)
        try:
            record = process360_audit.request_trail(request_id)
        finally:
            reset_request_context(token)
        if not record:
            raise HTTPException(404, "request not found")
        return {
            "requestId": record.get("id"),
            "surface": record.get("surface"),
            "createdAt": record.get("created_at"),
            "steps": record.get("steps") or [],
        }

    @router.get("/api/process360/task-orders")
    def process360_task_order_status(request: Request) -> dict[str, Any]:
        """Look up the stored execution result for a draft action."""
        if not _authorized(request):
            raise HTTPException(401, "unauthorized")
        draft_id = (request.query_params.get("draftId") or "").strip()
        action_id = (request.query_params.get("actionId") or "").strip()
        if not draft_id or not action_id:
            raise HTTPException(400, "draftId and actionId are required")
        service = process360_tools.Process360Service(cwd=get_cwd() or os.getcwd())
        context = http_context(request, surface="canvas")
        draft = service.store.get_draft(draft_id)
        owned = bool(
            draft
            and draft.get("tenant") == context.tenant_id
            and draft.get("principal") == context.principal_id
        )
        record = (
            service.store.get_execution(execution_key(context.tenant_id, draft_id, action_id))
            if owned else None
        )
        if not record:
            return {
                "schema": "process360.dispatch.v1",
                "status": "unconfirmed",
                "accepted": False,
                "message": "尚无执行记录，结果待确认",
                "receipt": None,
                "draftId": draft_id,
                "actionId": action_id,
                "requestId": "",
            }
        response = record.get("response") or {}
        state = str(response.get("status") or record.get("status") or "unconfirmed").lower()
        mapped = {
            "ok": "ok",
            "succeeded": "ok",
            "unknown": "unknown",
            "rejected": "rejected",
            "blocked": "blocked",
            "sending": "unconfirmed",
            "in_progress": "unconfirmed",
        }.get(state, "unconfirmed")
        return {
            "schema": "process360.dispatch.v1",
            "status": mapped,
            "accepted": mapped == "ok",
            "message": {
                "ok": "任务令已创建",
                "unknown": "请求可能已送达，执行结果待确认",
                "rejected": "Fuxi 明确拒绝任务令",
                "blocked": "任务令未创建",
            }.get(mapped, "执行结果待确认"),
            "receipt": response.get("receipt"),
            "gaps": response.get("gaps") or [],
            "draftId": draft_id,
            "actionId": action_id,
            "requestId": record.get("request_id") or "",
        }

    @router.get("/api/mcp/health")
    def mcp_health() -> dict[str, Any]:
        missing = runtime.missing_executors()
        if missing:
            LOGGER.warning("MCP tools declared without an executor: %s", ", ".join(missing))
        return {
            "ok": True,
            "server": SERVER_NAME,
            "version": SERVER_VERSION,
            "protocol": MCP_PROTOCOL_VERSION,
            "missingExecutors": list(missing),
        }

    @router.post("/api/mcp")
    async def mcp_post(request: Request):
        if not _authorized(request):
            raise HTTPException(401, "unauthorized")
        try:
            payload = await request.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"invalid JSON-RPC body: {exc}") from exc
        session_id = (request.headers.get("mcp-session-id") or "").strip() or None
        base_url = str(request.base_url).rstrip("/")

        async def one(item: dict[str, Any]):
            sid, response = await asyncio.to_thread(runtime.handle, item, session_id, base_url)
            return sid, response

        if isinstance(payload, list):
            results = []
            for item in payload:
                if not isinstance(item, dict):
                    continue
                _sid, response = await one(item)
                if response is not None:
                    results.append(response)
            return JSONResponse(results)
        if not isinstance(payload, dict):
            raise HTTPException(400, "JSON-RPC body must be an object or array")
        try:
            sid, response = await one(payload)
        except McpHttpError as exc:
            return JSONResponse(
                _error(payload.get("id"), -32000, str(exc)),
                status_code=exc.status,
                headers={"Mcp-Session-Id": session_id or ""} if session_id else None,
            )
        if response is None:
            return Response(status_code=202)
        headers = {"Mcp-Session-Id": sid} if sid else None
        if _wants_sse(request):
            sse = _sse(response)
            if headers:
                sse.headers.update(headers)
            return sse
        return JSONResponse(response, headers=headers)

    @router.delete("/api/mcp")
    def mcp_delete(request: Request) -> Response:
        if not _authorized(request):
            raise HTTPException(401, "unauthorized")
        session_id = (request.headers.get("mcp-session-id") or "").strip()
        if not session_id:
            raise HTTPException(400, "Mcp-Session-Id header is required")
        runtime.delete_session(session_id)
        return Response(status_code=204)

    @router.get("/api/mcp")
    def mcp_get() -> Response:
        return Response(status_code=405, headers={"Allow": "POST, DELETE"})

    @router.get("/api/mcp/artifacts/{filename}")
    def mcp_artifact(filename: str):
        canvas_dir = project_path(get_cwd() or os.getcwd(), _CANVAS_DIR).resolve()
        target = (canvas_dir / filename).resolve()
        if target.parent != canvas_dir or not target.is_file() or target.suffix.lower() != ".html":
            raise HTTPException(404, "artifact not found")
        return FileResponse(target, media_type="text/html; charset=utf-8")

    return router
