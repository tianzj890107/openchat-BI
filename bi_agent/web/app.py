"""FastAPI app exposing the BI agent as a web chat with a live inspector panel."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from open_claude.agent_def import AgentDef, get_agent_def_registry, load_agent_defs

from ..llm.registry import list_models
from ..llm.runtime_config import (
    get_api_key_status,
    get_config as get_llm_config,
    set_api_key,
)
from ..ontology.store import OntologyStore
from ..report import ReportStore, parser_availability
from ..tools import register_all
from .session import WebSession


REPORT_AGENT_NAME = "report-analyst"


STATIC_DIR = Path(__file__).parent / "static"


class AppState:
    """Singleton holding the ontology store and the (single) active session."""

    def __init__(self) -> None:
        self.cwd: str = ""
        self.ontology_store: Optional[OntologyStore] = None
        self.agent_def: Optional[AgentDef] = None
        self.session: Optional[WebSession] = None
        self.db_path: str = ""
        # --- Report-analysis mode ---------------------------------------
        self.report_store: Optional[ReportStore] = None
        self.report_session: Optional[WebSession] = None
        self.active_report_id: Optional[str] = None
        self.report_with_db: bool = False


STATE = AppState()


# Tool list for "启用数据库查询" mode — mirrors the report-analyst agent def.
REPORT_DB_TOOLS: list[str] = [
    "OntologyQuery", "TermDisambiguate", "MetricLookup", "RelationLookup",
    "EntityDescribe", "ListBusinessObjects", "SQLRun", "ListTables",
    "DescribeTable", "ChartGenerate", "AskUser",
]
# Pure-mode: only chart generation (over report data) and AskUser for
# disambiguation — no ontology/SQL.
REPORT_PURE_TOOLS: list[str] = ["ChartGenerate", "AskUser"]


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def configure(
    cwd: str,
    ontology_path: str,
    db_path: str,
    agent_name: str = "bi-analyst",
) -> None:
    """Load ontology, register tools, select agent def. Call once before serving."""
    # API keys are checked per-provider at call time:
    #   - Claude models need ANTHROPIC_API_KEY
    #   - Qwen models need DASHSCOPE_API_KEY (or QWEN_API_KEY)
    # The server boots regardless; failures surface when the user hits that model.

    STATE.cwd = cwd
    STATE.db_path = db_path
    STATE.ontology_store = OntologyStore.from_xlsx(ontology_path)
    register_all(STATE.ontology_store, db_path)

    load_agent_defs(cwd)
    reg = get_agent_def_registry()
    agent_def = reg.get(agent_name)
    if not agent_def:
        available = ", ".join(reg.list_names()) or "(none)"
        raise RuntimeError(f"Agent '{agent_name}' not found. Available: {available}")
    STATE.agent_def = agent_def

    # Report store (PDF/Word uploads for the report-analysis mode)
    STATE.report_store = ReportStore(cwd)

    # Serve generated charts so the chat-card "open" link works.
    charts_dir = Path(cwd) / "bi_charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/charts", StaticFiles(directory=str(charts_dir)), name="charts")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="BI Agent Web", version="0.1.0")


class ChatRequest(BaseModel):
    message: str


class ChoiceRequest(BaseModel):
    choice_id: str
    choice_label: str


class ConfigUpdate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_key: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    # API keys — pass a plain string to set, "" to clear, None/omit = no change
    anthropic_api_key: Optional[str] = None
    qwen_api_key: Optional[str] = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/api/meta")
def get_meta() -> JSONResponse:
    if not STATE.agent_def or not STATE.ontology_store:
        raise HTTPException(500, "Server not configured")
    agent = STATE.agent_def
    cfg = get_llm_config()
    reg = get_agent_def_registry()
    report_agent = reg.get(REPORT_AGENT_NAME)
    return JSONResponse({
        "agent": {
            "name": agent.name,
            "description": agent.description,
            "model": agent.model,
            "tools": agent.tools or [],
            "welcome_message": agent.welcome_message,
        },
        "report_agent": ({
            "name": report_agent.name,
            "description": report_agent.description,
            "model": report_agent.model,
            "welcome_message": report_agent.welcome_message,
        } if report_agent else None),
        "report_parser": parser_availability(),
        "ontology_stats": STATE.ontology_store.stats(),
        "db_path": os.path.basename(STATE.db_path),
        "cwd": STATE.cwd,
        "llm": {
            "models": list_models(),
            "current": cfg.to_dict(),
            "api_keys": get_api_key_status(),
        },
    })


@app.get("/api/config")
def get_config_endpoint() -> JSONResponse:
    cfg = get_llm_config()
    return JSONResponse({
        "models": list_models(),
        "current": cfg.to_dict(),
        "api_keys": get_api_key_status(),
    })


@app.put("/api/config")
def put_config_endpoint(req: ConfigUpdate) -> JSONResponse:
    cfg = get_llm_config()
    try:
        cfg.update(
            model_key=req.model_key,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    # API keys: only act when the field was present in the request body
    # (Optional[str] = None means "not sent"; empty string means "clear it").
    payload = req.model_dump(exclude_unset=True)
    try:
        if "anthropic_api_key" in payload:
            set_api_key("anthropic", payload["anthropic_api_key"])
        if "qwen_api_key" in payload:
            set_api_key("qwen", payload["qwen_api_key"])
    except ValueError as e:
        raise HTTPException(400, str(e))

    return JSONResponse({
        "models": list_models(),
        "current": cfg.to_dict(),
        "api_keys": get_api_key_status(),
    })


@app.get("/api/system-prompt")
def get_system_prompt(mode: str = "data") -> JSONResponse:
    if mode == "report":
        if STATE.report_session is None:
            return JSONResponse({"system_prompt": "(尚未激活任何报表,选择一份报表后将显示对应的 system prompt。)"})
        return JSONResponse({"system_prompt": STATE.report_session.system_prompt})
    _ensure_session()
    return JSONResponse({"system_prompt": STATE.session.system_prompt})


@app.get("/api/ontology/seen")
def get_ontology_seen(mode: str = "data") -> JSONResponse:
    session = STATE.report_session if mode == "report" else STATE.session
    if session is None:
        return JSONResponse({"entities": []})
    items = list(session.ontology_seen.values())
    items.sort(key=lambda r: (r["kind"], r["code"]))
    return JSONResponse({"entities": items})


@app.get("/api/ontology/all")
def get_ontology_all() -> JSONResponse:
    """Full ontology dump (for the "browse" side panel)."""
    if not STATE.ontology_store:
        raise HTTPException(500, "Ontology not loaded")
    s = STATE.ontology_store
    def _bundle(collection, kind):
        return [
            {"code": e.code, "kind": kind, "name": getattr(e, "name", e.code) or e.code}
            for e in collection.values()
        ]
    return JSONResponse({
        "terms": _bundle(s.terms, "term"),
        "business_objects": _bundle(s.business_objects, "business_object"),
        "logical_entities": _bundle(s.logical_entities, "logical_entity"),
        "metrics": _bundle(s.metrics, "metric"),
        "activities": _bundle(s.activities, "activity"),
        "rules": _bundle(s.rules, "rule"),
    })


@app.post("/api/session/reset")
def reset_session() -> JSONResponse:
    STATE.session = None
    return JSONResponse({"ok": True})


@app.post("/api/chat")
def chat(req: ChatRequest):
    _ensure_session()
    session = STATE.session

    message = (req.message or "").strip()
    if not message:
        raise HTTPException(400, "empty message")

    def event_stream():
        try:
            for evt in session.generate_turn(message):
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
        except Exception as e:
            err = {"type": "error", "message": f"{type(e).__name__}: {e}"}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/choice")
def choice(req: ChoiceRequest):
    """Resume a turn that paused on an AskUser tool call."""
    if not STATE.session:
        raise HTTPException(400, "No active session")
    session = STATE.session
    if not session.pending_tool_use_id:
        raise HTTPException(400, "No pending user choice")

    def event_stream():
        try:
            for evt in session.continue_with_choice(req.choice_id, req.choice_label):
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
        except Exception as e:
            err = {"type": "error", "message": f"{type(e).__name__}: {e}"}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Report-analysis mode (PDF/Word upload + Q&A)
# ---------------------------------------------------------------------------


class ReportActivate(BaseModel):
    report_id: str
    # Default to True — users nearly always want DB cross-checking; pure
    # mode is the exception, not the rule.
    with_db: bool = True


class ReportConfigUpdate(BaseModel):
    with_db: bool


@app.post("/api/report/upload")
async def report_upload(file: UploadFile = File(...)) -> JSONResponse:
    """Receive one PDF/Word file, parse it, stash it in the report store."""
    store = _require_report_store()
    filename = file.filename or ""
    if not filename:
        raise HTTPException(400, "missing filename")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in {".pdf", ".docx"}:
        raise HTTPException(400, f"不支持的文件类型: {ext}  (仅支持 .pdf / .docx)")
    avail = parser_availability()
    if ext == ".pdf" and not avail.get("pdf"):
        raise HTTPException(500, "服务器未安装 pymupdf,无法解析 PDF。请 `pip install pymupdf`")
    if ext == ".docx" and not avail.get("docx"):
        raise HTTPException(500, "服务器未安装 python-docx,无法解析 Word。请 `pip install python-docx`")

    data = await file.read()
    try:
        record = store.save(filename=filename, data=data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"解析失败: {type(e).__name__}: {e}")
    return JSONResponse(record.to_dict())


@app.get("/api/report/list")
def report_list() -> JSONResponse:
    store = _require_report_store()
    items = [r.to_dict() for r in store.list()]
    return JSONResponse({"items": items})


@app.delete("/api/report/{rid}")
def report_delete(rid: str) -> JSONResponse:
    store = _require_report_store()
    ok = store.delete(rid)
    if STATE.active_report_id == rid:
        STATE.active_report_id = None
        STATE.report_session = None
    return JSONResponse({"ok": ok})


@app.get("/api/report/status")
def report_status() -> JSONResponse:
    active = None
    if STATE.active_report_id and STATE.report_store:
        rec = STATE.report_store.get(STATE.active_report_id)
        if rec:
            active = {
                "id": rec["id"],
                "filename": rec.get("filename"),
                "ext": rec.get("ext"),
                "page_count": rec.get("page_count"),
                "tables_count": rec.get("tables_count"),
                "text_length": rec.get("text_length"),
                "uploaded_at": rec.get("uploaded_at"),
                "preview": rec.get("preview"),
            }
    return JSONResponse({
        "active_report": active,
        "with_db": STATE.report_with_db,
        "has_session": STATE.report_session is not None,
    })


@app.post("/api/report/activate")
def report_activate(req: ReportActivate) -> JSONResponse:
    """Bind the given report to a fresh report-analyst session."""
    store = _require_report_store()
    rec = store.get(req.report_id)
    if not rec:
        raise HTTPException(404, f"report not found: {req.report_id}")

    STATE.report_session = _build_report_session(req.report_id, req.with_db)
    STATE.active_report_id = req.report_id
    STATE.report_with_db = req.with_db

    return JSONResponse({
        "ok": True,
        "active_report": {
            "id": rec["id"],
            "filename": rec.get("filename"),
            "ext": rec.get("ext"),
            "page_count": rec.get("page_count"),
            "tables_count": rec.get("tables_count"),
            "text_length": rec.get("text_length"),
            "uploaded_at": rec.get("uploaded_at"),
            "preview": rec.get("preview"),
        },
        "with_db": STATE.report_with_db,
    })


@app.put("/api/report/config")
def report_config(req: ReportConfigUpdate) -> JSONResponse:
    """Flip the 启用数据库查询 switch without discarding the chat history.

    Rebuilds BOTH the tool whitelist AND the availability-marker header so
    the agent doesn't see a mismatch (stale header said 'disabled' while
    the new tool list includes SQLRun — which was the original bug).
    """
    if STATE.report_session is None:
        raise HTTPException(400, "No active report session")
    STATE.report_with_db = bool(req.with_db)
    new_tools = REPORT_DB_TOOLS if STATE.report_with_db else REPORT_PURE_TOOLS
    STATE.report_session.set_tools_override(new_tools)
    if STATE.active_report_id and STATE.report_store is not None:
        rec = STATE.report_store.get(STATE.active_report_id)
        if rec:
            STATE.report_session.set_context_header(
                _report_context_header(rec, STATE.report_with_db)
            )
    return JSONResponse({"ok": True, "with_db": STATE.report_with_db})


@app.post("/api/report/session/reset")
def report_session_reset() -> JSONResponse:
    """Clear the chat history but keep the active report + flag."""
    STATE.report_session = None
    if STATE.active_report_id:
        STATE.report_session = _build_report_session(
            STATE.active_report_id, STATE.report_with_db,
        )
    return JSONResponse({"ok": True})


@app.post("/api/report/chat")
def report_chat(req: ChatRequest):
    session = STATE.report_session
    if session is None:
        raise HTTPException(400, "No active report session — activate a report first")
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(400, "empty message")

    def event_stream():
        try:
            for evt in session.generate_turn(message):
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
        except Exception as e:
            err = {"type": "error", "message": f"{type(e).__name__}: {e}"}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/report/choice")
def report_choice(req: ChoiceRequest):
    session = STATE.report_session
    if session is None or not session.pending_tool_use_id:
        raise HTTPException(400, "No pending user choice")

    def event_stream():
        try:
            for evt in session.continue_with_choice(req.choice_id, req.choice_label):
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
        except Exception as e:
            err = {"type": "error", "message": f"{type(e).__name__}: {e}"}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_session() -> None:
    if STATE.session is None:
        if not STATE.agent_def or not STATE.ontology_store:
            raise HTTPException(500, "Server not configured; call configure() first.")
        STATE.session = WebSession(
            cwd=STATE.cwd,
            agent_def=STATE.agent_def,
            ontology_store=STATE.ontology_store,
        )


def _require_report_store() -> ReportStore:
    if STATE.report_store is None:
        raise HTTPException(500, "Server not configured; call configure() first.")
    return STATE.report_store


def _report_context_header(rec: dict, with_db: bool) -> str:
    """Render the `# 当前报表 ... # 数据库工具可用性: ...` header block.

    Kept as a module-level helper so both fresh-session creation and the
    mid-session toggle endpoint build the SAME header — otherwise flipping
    the checkbox would desync the availability marker from the tool list.
    """
    return (
        f"# 当前报表\n\n"
        f"- 文件名: {rec.get('filename')}\n"
        f"- 页数: {rec.get('page_count')}\n"
        f"- 表格数: {rec.get('tables_count')}\n"
        f"- 文本长度: {rec.get('text_length')} 字符\n"
        f"\n# 数据库工具可用性: {'enabled' if with_db else 'disabled'}"
    )


def _build_report_session(report_id: str, with_db: bool) -> WebSession:
    """Create a fresh WebSession bound to the given report + DB-tools flag."""
    if not STATE.ontology_store or not STATE.report_store:
        raise HTTPException(500, "Server not configured; call configure() first.")
    reg = get_agent_def_registry()
    report_agent = reg.get(REPORT_AGENT_NAME)
    if report_agent is None:
        raise HTTPException(
            500,
            f"Agent '{REPORT_AGENT_NAME}' not found — please restart the server after "
            f"adding .claude/agents/{REPORT_AGENT_NAME}.md",
        )
    rec = STATE.report_store.get(report_id)
    if not rec:
        raise HTTPException(404, f"report not found: {report_id}")
    report_block = STATE.report_store.get_prompt_block(report_id) or "(报表内容为空)"
    header = _report_context_header(rec, with_db)
    tools = REPORT_DB_TOOLS if with_db else REPORT_PURE_TOOLS
    return WebSession(
        cwd=STATE.cwd,
        agent_def=report_agent,
        ontology_store=STATE.ontology_store,
        tools_override=tools,
        report_context_block=report_block,
        context_header=header,
    )
