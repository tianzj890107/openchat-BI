"""FastAPI app exposing the BI agent as a web chat with a live inspector panel."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, List, Optional

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

# Hard cap so the multi-report system prompt doesn't blow past the model's
# context window. 5 × ~12k chars/report ≈ 60k chars total — same budget as
# the previous single-report path. Selecting more than this returns 400.
MAX_ACTIVE_REPORTS = 5
# Total character budget across all selected reports (split evenly).
TOTAL_REPORT_CHARS = 60_000


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
        # Multiple reports may be active simultaneously. The ordered list
        # below preserves the user's selection order so prompt sections,
        # attach-chip labels, and the agent's report-numbering all line up.
        self.report_store: Optional[ReportStore] = None
        self.report_session: Optional[WebSession] = None
        self.active_report_ids: list[str] = []
        self.report_with_db: bool = False


STATE = AppState()


# Tool list for "启用数据库查询" mode — mirrors the report-analyst agent def.
# ChartGenerateMultiDim is included because deep-insight drill-down requires
# running multi-dim SQL queries; only meaningful when DB tools are on.
REPORT_DB_TOOLS: list[str] = [
    "OntologyQuery", "TermDisambiguate", "MetricLookup", "RelationLookup",
    "EntityDescribe", "ListBusinessObjects", "SQLRun", "ListTables",
    "DescribeTable", "ChartGenerate", "ChartGenerateMultiDim",
    "TableGenerate", "AskUser",
]
# Pure-mode: visualization (chart + structured table over report data) and
# AskUser for disambiguation — no ontology/SQL. Table generation is part
# of the visualization-skill bundle the report-analyst SOP requires.
# ChartGenerateMultiDim NOT included: deep-insight drill-down depends on
# running per-dim SQL, which pure mode doesn't have access to.
REPORT_PURE_TOOLS: list[str] = ["ChartGenerate", "TableGenerate", "AskUser"]


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
    # Multi-select (preferred). Single-pick clients can send lists of length 1.
    choice_ids: Optional[List[str]] = None
    choice_labels: Optional[List[str]] = None
    # Back-compat: legacy single-pick fields.
    choice_id: Optional[str] = None
    choice_label: Optional[str] = None

    def normalized(self) -> tuple[List[str], List[str]]:
        ids = list(self.choice_ids or [])
        labels = list(self.choice_labels or [])
        if not ids and self.choice_id is not None:
            ids = [self.choice_id]
        if not labels and self.choice_label is not None:
            labels = [self.choice_label]
        if not ids or not labels or len(ids) != len(labels):
            raise HTTPException(
                400, "choice_ids/choice_labels must be non-empty lists of equal length",
            )
        return ids, labels


class ConfigUpdate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_key: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    thinking: Optional[bool] = None
    # API keys — pass a plain string to set, "" to clear, None/omit = no change
    anthropic_api_key: Optional[str] = None
    qwen_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None


def _project_root() -> Path:
    # Prefer the cwd configured at startup; fall back to repo root inferred from this file.
    if STATE.cwd:
        return Path(STATE.cwd)
    return Path(__file__).resolve().parents[2]


def _no_cache_file(path: Path) -> FileResponse:
    return FileResponse(
        path,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/")
def index() -> FileResponse:
    # Project main page: the standalone CEO dashboard (entry). The detailed
    # CEO cockpit is reachable at /ceo_cockpit.html; the BI workbench lives at
    # /workbench and is embedded as an iframe inside the floating AI assistant.
    page = _project_root() / "ceo_dashboard_standalone.html"
    if page.exists():
        return _no_cache_file(page)
    fallback = _project_root() / "ceo_cockpit.html"
    if fallback.exists():
        return _no_cache_file(fallback)
    return _no_cache_file(STATIC_DIR / "index.html")


@app.get("/ceo_cockpit.html")
def ceo_cockpit_page() -> FileResponse:
    return FileResponse(_project_root() / "ceo_cockpit.html")


@app.get("/asset_overdue_inventory.html")
def asset_overdue_inventory_page() -> FileResponse:
    return FileResponse(_project_root() / "asset_overdue_inventory.html")


@app.get("/workbench")
def workbench() -> FileResponse:
    return _no_cache_file(STATIC_DIR / "index.html")


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
            thinking=req.thinking,
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
        if "deepseek_api_key" in payload:
            set_api_key("deepseek", payload["deepseek_api_key"])
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
    ids, labels = req.normalized()

    def event_stream():
        try:
            for evt in session.continue_with_choice(ids, labels):
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
    # `report_ids` is the canonical multi-report field; `report_id`
    # remains for backward compatibility with the single-report client.
    # If both are sent, `report_ids` wins.
    report_ids: Optional[list[str]] = None
    report_id: Optional[str] = None
    # Default to True — users nearly always want DB cross-checking; pure
    # mode is the exception, not the rule.
    with_db: bool = True

    def resolve_ids(self) -> list[str]:
        if self.report_ids:
            ids = [r for r in self.report_ids if r]
        elif self.report_id:
            ids = [self.report_id]
        else:
            ids = []
        # Preserve order, drop duplicates.
        seen: set[str] = set()
        out: list[str] = []
        for rid in ids:
            if rid in seen:
                continue
            seen.add(rid)
            out.append(rid)
        return out


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
    # If the deleted report is in the active list, drop it. When the list
    # becomes empty, blow away the session — there's nothing left to
    # answer questions against, and the system prompt would carry stale
    # references to deleted files otherwise.
    if rid in STATE.active_report_ids:
        STATE.active_report_ids = [r for r in STATE.active_report_ids if r != rid]
        if STATE.active_report_ids:
            STATE.report_session = _build_report_session(
                STATE.active_report_ids, STATE.report_with_db,
            )
        else:
            STATE.report_session = None
    return JSONResponse({"ok": ok})


def _record_to_summary(rec: dict) -> dict:
    """The slim record shape the frontend consumes (no full text/tables)."""
    return {
        "id": rec["id"],
        "filename": rec.get("filename"),
        "ext": rec.get("ext"),
        "page_count": rec.get("page_count"),
        "tables_count": rec.get("tables_count"),
        "text_length": rec.get("text_length"),
        "uploaded_at": rec.get("uploaded_at"),
        "preview": rec.get("preview"),
    }


@app.get("/api/report/status")
def report_status() -> JSONResponse:
    actives: list[dict] = []
    if STATE.report_store:
        for rid in STATE.active_report_ids:
            rec = STATE.report_store.get(rid)
            if rec:
                actives.append(_record_to_summary(rec))
    # Backward-compat: keep `active_report` as the first one so older
    # clients don't break; new clients should read `active_reports`.
    legacy_active = actives[0] if actives else None
    return JSONResponse({
        "active_reports": actives,
        "active_report": legacy_active,
        "with_db": STATE.report_with_db,
        "has_session": STATE.report_session is not None,
    })


@app.post("/api/report/activate")
def report_activate(req: ReportActivate) -> JSONResponse:
    """Bind the given report(s) to a fresh report-analyst session."""
    store = _require_report_store()
    ids = req.resolve_ids()
    if not ids:
        raise HTTPException(400, "请至少提供一个 report_id")
    if len(ids) > MAX_ACTIVE_REPORTS:
        raise HTTPException(
            400,
            f"一次最多激活 {MAX_ACTIVE_REPORTS} 份报表(已选 {len(ids)} 份)",
        )

    actives: list[dict] = []
    for rid in ids:
        rec = store.get(rid)
        if not rec:
            raise HTTPException(404, f"report not found: {rid}")
        actives.append(_record_to_summary(rec))

    STATE.report_session = _build_report_session(ids, req.with_db)
    STATE.active_report_ids = ids
    STATE.report_with_db = req.with_db

    return JSONResponse({
        "ok": True,
        "active_reports": actives,
        # Backward-compat — first report as the legacy "single active".
        "active_report": actives[0] if actives else None,
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
    if STATE.active_report_ids and STATE.report_store is not None:
        recs = [STATE.report_store.get(rid) for rid in STATE.active_report_ids]
        recs = [r for r in recs if r]
        if recs:
            STATE.report_session.set_context_header(
                _report_context_header(recs, STATE.report_with_db)
            )
    return JSONResponse({"ok": True, "with_db": STATE.report_with_db})


@app.post("/api/report/session/reset")
def report_session_reset() -> JSONResponse:
    """Clear the chat history but keep the active reports + flag."""
    STATE.report_session = None
    if STATE.active_report_ids:
        STATE.report_session = _build_report_session(
            STATE.active_report_ids, STATE.report_with_db,
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
    ids, labels = req.normalized()

    def event_stream():
        try:
            for evt in session.continue_with_choice(ids, labels):
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


def _report_context_header(recs: list[dict], with_db: bool) -> str:
    """Render the `# 当前报表 ... # 数据库工具可用性: ...` header block.

    For multi-report sessions, list every active report numbered so the
    agent can refer to them as "报表 1 · filename" / "报表 2 · filename"
    in answers. The `with_db` marker stays on its own final line so both
    fresh-session creation and the mid-session toggle endpoint emit the
    SAME footer — flipping the checkbox must not desync the availability
    marker from the tool list.
    """
    n = len(recs)
    if n == 1:
        rec = recs[0]
        body = (
            f"- 文件名: {rec.get('filename')}\n"
            f"- 页数: {rec.get('page_count')}\n"
            f"- 表格数: {rec.get('tables_count')}\n"
            f"- 文本长度: {rec.get('text_length')} 字符"
        )
    else:
        lines = [f"共 {n} 份报表(回答时请用「报表 N · 文件名」前缀引用):"]
        for i, rec in enumerate(recs, 1):
            lines.append(
                f"- 报表 {i} · {rec.get('filename')} "
                f"({rec.get('page_count')} 页 / {rec.get('tables_count')} 表 / "
                f"{rec.get('text_length')} 字)"
            )
        body = "\n".join(lines)
    return (
        f"# 当前报表\n\n{body}\n"
        f"\n# 数据库工具可用性: {'enabled' if with_db else 'disabled'}"
    )


def _build_multi_report_block(report_ids: list[str]) -> str:
    """Concatenate prompt blocks for multiple reports under the same budget.

    The total character budget (TOTAL_REPORT_CHARS) is split evenly across
    all selected reports so a 5-report selection doesn't blow the context.
    Each section gets a `## 报表 N · filename` header so the agent can
    reference them unambiguously.
    """
    store = STATE.report_store
    if store is None or not report_ids:
        return "(报表内容为空)"
    per_report = max(2_000, TOTAL_REPORT_CHARS // max(1, len(report_ids)))
    sections: list[str] = []
    for i, rid in enumerate(report_ids, 1):
        rec = store.get(rid)
        block = store.get_prompt_block(rid, max_chars=per_report) or "(本报表内容为空)"
        fname = (rec or {}).get("filename") or rid
        header = f"## 报表 {i} · {fname}\n"
        sections.append(header + block)
    return "\n\n---\n\n".join(sections)


def _build_report_session(report_ids: list[str], with_db: bool) -> WebSession:
    """Create a fresh WebSession bound to the given report list + DB flag."""
    if not STATE.ontology_store or not STATE.report_store:
        raise HTTPException(500, "Server not configured; call configure() first.")
    if not report_ids:
        raise HTTPException(400, "report_ids is empty")
    if len(report_ids) > MAX_ACTIVE_REPORTS:
        raise HTTPException(
            400,
            f"一次最多激活 {MAX_ACTIVE_REPORTS} 份报表(传入 {len(report_ids)} 份)",
        )
    reg = get_agent_def_registry()
    report_agent = reg.get(REPORT_AGENT_NAME)
    if report_agent is None:
        raise HTTPException(
            500,
            f"Agent '{REPORT_AGENT_NAME}' not found — please restart the server after "
            f"adding .claude/agents/{REPORT_AGENT_NAME}.md",
        )
    recs: list[dict] = []
    for rid in report_ids:
        rec = STATE.report_store.get(rid)
        if not rec:
            raise HTTPException(404, f"report not found: {rid}")
        recs.append(rec)

    report_block = _build_multi_report_block(report_ids)
    header = _report_context_header(recs, with_db)
    tools = REPORT_DB_TOOLS if with_db else REPORT_PURE_TOOLS
    return WebSession(
        cwd=STATE.cwd,
        agent_def=report_agent,
        ontology_store=STATE.ontology_store,
        tools_override=tools,
        report_context_block=report_block,
        context_header=header,
    )
