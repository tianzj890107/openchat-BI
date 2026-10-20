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
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

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

Executor = Callable[[dict[str, Any], str], str]

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
    "OutputGateCheck",
)

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
    return schemas


def _mcp_tool(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": schema["name"],
        "description": (schema.get("description") or "").strip(),
        "inputSchema": schema.get("input_schema") or {"type": "object"},
        "annotations": {
            "readOnlyHint": True,
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
        del cwd
        report = _gate_rules().check(dict(params or {}))
        return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    return run


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
    canvas_schema, canvas_factory = _canvas_tools().SPECS[0]
    del canvas_schema
    executors["CanvasGenerate"] = canvas_factory()
    executors["AnalysisRoute"] = _route_executor()
    executors["OutputGateCheck"] = _gate_executor()
    return executors


class McpRuntime:
    """Protocol state plus a source-bound executor cache."""

    def __init__(self, *, get_source: Callable[[], Any], build_doris: Callable[..., Any],
                 get_cwd: Callable[[], str], executor_factory: Callable[[Any], dict[str, Executor]] | None = None,
                 exposed_tools: tuple[str, ...] | None = None) -> None:
        self.get_source = get_source
        self.build_doris = build_doris
        self.get_cwd = get_cwd
        self.executor_factory = executor_factory
        requested = tuple(exposed_tools or _configured_tools())
        self.exposed = tuple(name for name in requested if name not in MCP_DENIED_TOOLS)
        self._sessions: dict[str, float] = {}
        self._lock = threading.RLock()
        self._cache_signature: tuple[Any, ...] | None = None
        self._cache_executors: dict[str, Executor] = {}
        self._cache_schemas: dict[str, dict[str, Any]] = {}
        self._source_free: dict[str, Executor] = {
            "AnalysisRoute": _route_executor(),
            "OutputGateCheck": _gate_executor(),
        }

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

    def call_tool(self, name: str, arguments: dict[str, Any], base_url: str = "") -> str:
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
        result = executor(dict(arguments or {}), cwd)
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
                text = self.call_tool(name, arguments, base_url)
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
                     exposed_tools: tuple[str, ...] | None = None) -> APIRouter:
    runtime = McpRuntime(
        get_source=get_source,
        build_doris=build_doris,
        get_cwd=get_cwd,
        executor_factory=executor_factory,
        exposed_tools=exposed_tools,
    )
    router = APIRouter()

    @router.get("/api/mcp/health")
    def mcp_health() -> dict[str, Any]:
        return {"ok": True, "server": SERVER_NAME, "version": SERVER_VERSION, "protocol": MCP_PROTOCOL_VERSION}

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
