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

from ..llm.provider import stream_message
from ..llm.registry import list_models
from ..llm.runtime_config import (
    get_api_key_status,
    get_config as get_llm_config,
    set_api_key,
)
from ..ontology.store import OntologyStore
from ..report import ReportStore, parser_availability
from ..tools import register_all
from ..tools.graph_tools import GRAPH_TOOL_NAMES
from ..tools.sql_tools import (
    DEFAULT_DORIS_DATABASE,
    DEFAULT_DORIS_DRIVER,
    DEFAULT_DORIS_JDBC_URL,
    DEFAULT_DORIS_PASSWORD,
    DEFAULT_DORIS_USERNAME,
    DorisConn,
)
from .conversations import ConversationStore
from .session import WebSession


REPORT_AGENT_NAME = "report-analyst"
REPORTGEN_AGENT_NAME = "report-generator"

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
        self.ontology_path: str = ""
        # --- Doris (MySQL protocol) data source -------------------------
        # When `use_doris` is True the SQL tools query Apache Doris over the
        # MySQL wire protocol instead of the local SQLite `db_path`. The
        # connection params seed the 数据源设置 UI fields and can be overridden
        # via DORIS_* env vars. Password is empty by default ("当前没有密码").
        self.doris_jdbc_url: str = os.environ.get("DORIS_JDBC_URL", DEFAULT_DORIS_JDBC_URL)
        self.doris_driver: str = os.environ.get("DORIS_DRIVER", DEFAULT_DORIS_DRIVER)
        self.doris_username: str = os.environ.get("DORIS_USERNAME", DEFAULT_DORIS_USERNAME)
        self.doris_password: str = os.environ.get("DORIS_PASSWORD", DEFAULT_DORIS_PASSWORD)
        # Active Doris database (schema). SQL references tables db-qualified,
        # e.g. `ontology_demo_scm_po.poheader`.
        self.doris_database: str = os.environ.get("DORIS_DATABASE", DEFAULT_DORIS_DATABASE)
        self.use_doris: bool = False
        # --- Ontology retrieval mode ------------------------------------
        # "semantic" (default): retrieve ontology knowledge from the Excel
        # business-metadata via keyword/semantic lookup. "graph": retrieve via
        # a graph library (图库) alongside the Excel ontology. The graph
        # retrieval logic itself is not implemented yet — these fields only
        # carry the selected configuration so a later implementation can read
        # STATE.retrieval_mode / STATE.graph_path.
        self.retrieval_mode: str = os.environ.get("RETRIEVAL_MODE", "semantic")
        self.graph_path: str = os.environ.get("GRAPH_PATH", "")
        # --- Report-analysis mode ---------------------------------------
        # Multiple reports may be active simultaneously. The ordered list
        # below preserves the user's selection order so prompt sections,
        # attach-chip labels, and the agent's report-numbering all line up.
        self.report_store: Optional[ReportStore] = None
        self.report_session: Optional[WebSession] = None
        self.active_report_ids: list[str] = []
        self.report_with_db: bool = False
        # --- Conversation history (restorable 最近 list) -----------------
        self.conversation_store: Optional[ConversationStore] = None
        # --- 角色选择(用户画像 + Agent 回答风格偏好)-------------------
        # Injected into every session's system prompt so the agent adapts its
        # depth / terminology / tone. Empty = no role preference applied.
        self.user_role: str = ""
        self.agent_pref: str = ""


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
# 角色选择(用户画像 + Agent 回答风格)
# ---------------------------------------------------------------------------
# Each entry: key -> (label, prompt description). The selected pair is rendered
# into a system-prompt block so the agent adapts depth, terminology and tone.
USER_ROLES: dict[str, tuple[str, str]] = {
    "finance": (
        "财务分析师",
        "用户是财务分析师,熟悉会计科目、报表勾稽与口径;回答可使用专业财务术语,"
        "重点放在数字准确性、口径一致与异常勾稽。",
    ),
    "business": (
        "业务负责人",
        "用户是业务负责人,关注经营结果与业务动因;回答应少用纯财务术语,多用业务语言"
        "解释数字背后的经营含义,并给出可执行建议。",
    ),
    "exec": (
        "管理层",
        "用户是管理层(高管),时间有限;回答先给结论与关键风险/机会,再给少量支撑数据,"
        "避免冗长的过程细节。",
    ),
    "data": (
        "数据工程师",
        "用户是数据工程师,关注取数过程;回答可展示 SQL、涉及的表/字段、口径与数据来源,"
        "便于复核与复用。",
    ),
}
AGENT_PREFS: dict[str, tuple[str, str]] = {
    "audit": (
        "严谨审计型",
        "以严谨审计的口吻作答:强调口径定义、数据来源与可验证性,对不确定处主动标注"
        "假设与风险,不臆测。",
    ),
    "advisor": (
        "业务顾问型",
        "以业务顾问的口吻作答:在给出数据的同时提供洞察、归因与下一步建议。",
    ),
    "tutor": (
        "教学讲解型",
        "以教学讲解的口吻作答:解释关键概念与计算过程,循序渐进,必要时举例。",
    ),
    "concise": (
        "简洁高效型",
        "以简洁高效的口吻作答:直接给结论与关键数字,尽量精炼,避免冗长铺垫。",
    ),
}


def _role_block() -> Optional[str]:
    """Render the 用户画像/回答风格 system-prompt block from STATE, or None."""
    user = USER_ROLES.get(STATE.user_role)
    pref = AGENT_PREFS.get(STATE.agent_pref)
    if not user and not pref:
        return None
    lines = ["# 用户画像与回答偏好", ""]
    if user:
        lines.append(f"- 自身角色:{user[0]} —— {user[1]}")
    if pref:
        lines.append(f"- 回答风格:{pref[0]} —— {pref[1]}")
    lines.append("")
    lines.append("请在保证数据准确的前提下,按上述用户角色与回答风格组织你的回答。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def configure(
    cwd: str,
    ontology_path: str,
    db_path: str,
    agent_name: str = "bi-analyst",
    use_doris: bool = False,
) -> None:
    """Load ontology, register tools, select agent def. Call once before serving."""
    # API keys are checked per-provider at call time:
    #   - Claude models need ANTHROPIC_API_KEY
    #   - Qwen models need DASHSCOPE_API_KEY (or QWEN_API_KEY)
    # The server boots regardless; failures surface when the user hits that model.

    STATE.cwd = cwd
    STATE.db_path = db_path
    STATE.ontology_path = ontology_path
    STATE.use_doris = use_doris
    STATE.ontology_store = OntologyStore.from_xlsx(ontology_path)
    doris_conn = (
        DorisConn(
            jdbc_url=STATE.doris_jdbc_url,
            username=STATE.doris_username,
            password=STATE.doris_password,
            driver=STATE.doris_driver,
            database=STATE.doris_database,
        )
        if use_doris
        else None
    )
    register_all(STATE.ontology_store, db_path, doris=doris_conn)

    load_agent_defs(cwd)
    reg = get_agent_def_registry()
    agent_def = reg.get(agent_name)
    if not agent_def:
        available = ", ".join(reg.list_names()) or "(none)"
        raise RuntimeError(f"Agent '{agent_name}' not found. Available: {available}")
    STATE.agent_def = agent_def

    # Report store (PDF/Word uploads for the report-analysis mode)
    STATE.report_store = ReportStore(cwd)

    # Conversation store (restorable history for the sidebar 「最近」list)
    STATE.conversation_store = ConversationStore(cwd)

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


# Sentinel `database` value meaning "use the Doris (MySQL protocol) source"
# instead of a local .db file. Surfaced as a selectable option in /api/sources.
DORIS_SOURCE_VALUE = "__doris_api__"

# Retrieval modes for ontology knowledge. "semantic" = Excel-only keyword/
# semantic lookup (the original behavior); "graph" = graph-library retrieval
# (anchor on the graph, drill the sub-tree, diffuse for根因) which additionally
# needs a 图库 file. The graph-mode tools/SOP are applied in _ensure_session.
RETRIEVAL_MODES = ("semantic", "graph")
# Candidate graph-library file extensions scanned for the 图库源 dropdown.
GRAPH_PATTERNS = ("*.graphml", "*.gml", "*.kuzu", "*.graph", "*.ttl", "*.rdf")

# Graph-mode SOP addendum — appended to the bi-analyst system prompt when
# 检索模式 = 图库检索. It overrides steps 2/3 and augments step 5 (深度分析)
# with the图库扩散探索 skill; all other steps + delivery templates stay.
GRAPH_MODE_SOP = """# 图库检索模式 · SOP 调整(覆盖上文对应步骤)

当前检索模式 = **图库检索**。以下调整覆盖六步 SOP 的第 2、3 步与第 5 步(深度分析)的取数上下文方式;**其余步骤与各 Level 交付模板完全不变**。

## 第 1 步 · 意图识别(不变)
仍以识别 L1–L5 五种类型为目标,并对问题做分词,抽出其中的业务名词。

## 第 2 步 · 语义消歧(术语嫁接)
- 对问句中的业务名词,用 `TermDisambiguate` 在术语库(术语名称 + 别名)中检索。
- 若命中术语,把该术语定义以**括号形式嫁接**回用户问题,形成"完整问题"作为后续输入。例:"采购金额是多少" → 命中术语 → 以"采购金额(企业对外采购产品和服务的金额)是多少"推进。
- **若一个名词命中多个口径不同的术语、且无法从问句上下文唯一确定**(如"客户活跃度"对应月活/周活/订单活跃),**必须调用 `AskUser` 让用户选择后再嫁接**,不要默默挑一个。
- 未命中则保持原问句。

## 第 3 步 · 上下文准备(图库锚定 + 下钻)
- 把**原始问题**分别与业务对象库、指标库匹配,确定锚点,然后调用 `GraphContext`:
  - 先用 `query` 传业务名词,由系统在业务对象/指标库匹配锚点;**若返回多个候选锚点(业务对象或指标)且无法从问句唯一确定是哪一个,必须调用 `AskUser` 让用户确认**,再用其选定项的 `anchor` 编码调用 `GraphContext`;仅当候选唯一或问句已明示时才直接选定,不要替用户臆断。
  - **业务对象锚点** → 返回该业务对象 + 其下逻辑实体 / 业务属性 + 其下指标的行信息。
  - **指标锚点** → 返回该指标 + 可下钻维度 + 指标维度矩阵,并自动上挂其业务对象作为新锚点、下钻该业务对象全部行信息。
- **指标下钻维度的确认**:若锚点指标的可下钻维度多于 1 个、问句又没点明下钻方向,且问题属于 L2 及以上分析,**必须调用 `AskUser` 让用户选择主下钻维度**(可多选);问句已点明("按事业部""按季度")或只有单一维度则直接采用。
- `GraphContext` 的返回即已剪枝去重的背景上下文,直接作为后续规划与 SQL 的依据;无需再逐个 `EntityDescribe` / `MetricLookup`(仅在需要核对单个元素细节时才补用)。

## 第 4 步起 · 不变
规划 / SQL 执行 / 校验 / 交付,沿用上文六步 SOP 与各 Level 模板。

## 第 5 步 · 深度分析增强(仅 L3–L5,且上下文不足时)
若判定为 L3–L5(含根因分析),而 `GraphContext` 给到的上下文不足以支撑根因/决策,可自行使用「图库扩散探索」skill `GraphExpand`:
- 传入当前业务对象锚点(BOxxxx;传指标编码会自动定位其业务对象)。
- 它会沿"活动 → 所属流程(取整条流程行信息)"与"活动上下游(活动流流转)"找到上下游业务对象,作为新锚点下钻其全部行信息,补足跨域上下文。
- **仅在已有上下文确实不够时调用**;够用就不必扩散。
"""


class SourcesUpdate(BaseModel):
    """Switch the active ontology / database source. Omit a field to keep it."""
    ontology: Optional[str] = None   # xlsx filename, relative to cwd
    database: Optional[str] = None   # .db filename, or DORIS_SOURCE_VALUE for Doris
    # Doris connection params (used when database == DORIS_SOURCE_VALUE)
    doris_jdbc_url: Optional[str] = None
    doris_driver: Optional[str] = None
    doris_username: Optional[str] = None
    doris_password: Optional[str] = None
    doris_database: Optional[str] = None
    # Ontology retrieval mode ("semantic" | "graph") + the selected 图库 file
    # (only meaningful in graph mode). Graph retrieval is not implemented yet.
    retrieval_mode: Optional[str] = None
    graph: Optional[str] = None


class GraphBuildRequest(BaseModel):
    """Build a NetworkX graph library (.graphml) from an ontology xlsx."""
    ontology: str  # xlsx filename, relative to cwd


class ReportComposeBlock(BaseModel):
    """One dashboard content block fed to the report-compose LLM call."""
    idx: int
    kind: str = "text"          # "text" | "table" | "chart"
    title: str = ""
    content: str = ""


class ReportComposeRequest(BaseModel):
    blocks: List[ReportComposeBlock] = []


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
    # Project main page: the role dashboard (entry). The standalone CEO dashboard
    # is reachable at /ceo_dashboard_standalone.html and the detailed CEO cockpit
    # at /ceo_cockpit.html; the BI workbench lives at /workbench and is embedded
    # as the Meta-ERP 智能分析助手 inside the dashboard's i-Agent view.
    page = _project_root() / "dashboard.html"
    if page.exists():
        return _no_cache_file(page)
    fallback = _project_root() / "ceo_dashboard_standalone.html"
    if fallback.exists():
        return _no_cache_file(fallback)
    return _no_cache_file(STATIC_DIR / "index.html")


@app.get("/ceo_dashboard_standalone.html")
def ceo_dashboard_standalone_page() -> FileResponse:
    return _no_cache_file(_project_root() / "ceo_dashboard_standalone.html")


@app.get("/ceo_cockpit.html")
def ceo_cockpit_page() -> FileResponse:
    return FileResponse(_project_root() / "ceo_cockpit.html")


@app.get("/dashboard.html")
def role_dashboard_page() -> FileResponse:
    return _no_cache_file(_project_root() / "dashboard.html")


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


@app.get("/api/sources")
def get_sources_endpoint() -> JSONResponse:
    """List available ontology (.xlsx) and database (.db) files in the
    working directory, flagging the currently active one."""
    cwd = Path(STATE.cwd)

    def _scan(pattern: str) -> list[str]:
        return sorted(
            p.name for p in cwd.glob(pattern)
            if p.is_file() and not p.name.startswith("~$")
        )

    # Doris (MySQL protocol) is offered as a pseudo-source alongside the local
    # .db files. When active, `database.active` points at the sentinel value.
    db_options = _scan("*.db") + [DORIS_SOURCE_VALUE]
    db_active = DORIS_SOURCE_VALUE if STATE.use_doris else os.path.basename(STATE.db_path)

    # Graph-library candidates for the 图库源 dropdown (graph retrieval mode).
    graph_options: list[str] = []
    for pat in GRAPH_PATTERNS:
        graph_options.extend(_scan(pat))
    graph_options = sorted(set(graph_options))

    return JSONResponse({
        "ontology": {
            "options": _scan("*.xlsx"),
            "active": os.path.basename(STATE.ontology_path),
        },
        "database": {
            "options": db_options,
            "active": db_active,
        },
        "retrieval": {
            "mode": STATE.retrieval_mode,
            "graph": {
                "options": graph_options,
                "active": os.path.basename(STATE.graph_path) if STATE.graph_path else "",
            },
        },
        "doris": {
            "value": DORIS_SOURCE_VALUE,
            "active": STATE.use_doris,
            "jdbc_url": STATE.doris_jdbc_url,
            "driver": STATE.doris_driver,
            "username": STATE.doris_username,
            "password": STATE.doris_password,
            "database": STATE.doris_database,
        },
    })


@app.put("/api/sources")
def put_sources_endpoint(req: SourcesUpdate) -> JSONResponse:
    """Switch the active ontology / database at runtime. Re-registers the
    BI tools against the new sources and resets sessions so the change
    takes effect on the next turn."""
    cwd = Path(STATE.cwd)
    changed: list[str] = []

    if req.ontology:
        op = cwd / req.ontology
        if not op.is_file():
            raise HTTPException(400, f"本体文件不存在: {req.ontology}")
        try:
            store = OntologyStore.from_xlsx(str(op))
        except Exception as e:  # surface load errors to the UI
            raise HTTPException(400, f"本体文件无法加载: {req.ontology} — {e}")
        STATE.ontology_store = store
        STATE.ontology_path = str(op)
        changed.append("ontology")

    if req.database == DORIS_SOURCE_VALUE:
        # Switch the SQL tools to Doris (MySQL protocol). Empty fields fall
        # back to the stored/default connection params (password may be blank).
        jdbc = (req.doris_jdbc_url or STATE.doris_jdbc_url or "").strip()
        username = req.doris_username if req.doris_username is not None else STATE.doris_username
        password = req.doris_password if req.doris_password is not None else STATE.doris_password
        driver = (req.doris_driver or STATE.doris_driver or DEFAULT_DORIS_DRIVER).strip()
        database = (req.doris_database or STATE.doris_database or DEFAULT_DORIS_DATABASE).strip()
        if not jdbc:
            raise HTTPException(400, "请填写 Doris JDBC 地址(例如 jdbc:mysql://host:9030/db)")
        try:
            DorisConn(
                jdbc_url=jdbc, username=username, password=password,
                driver=driver, database=database,
            )
        except ValueError as e:
            raise HTTPException(400, f"Doris JDBC 地址无法解析: {e}")
        STATE.doris_jdbc_url = jdbc
        STATE.doris_username = username
        STATE.doris_password = password
        STATE.doris_driver = driver
        STATE.doris_database = database
        STATE.use_doris = True
        changed.append("database")
    elif req.database:
        dp = cwd / req.database
        if not dp.is_file():
            raise HTTPException(400, f"数据库文件不存在: {req.database}")
        STATE.db_path = str(dp)
        STATE.use_doris = False
        changed.append("database")

    # Retrieval mode (semantic | graph) + optional 图库 file. In graph mode the
    # data session is rebuilt with the 图库检索 tools + SOP (see _ensure_session).
    if req.retrieval_mode is not None:
        mode = req.retrieval_mode.strip()
        if mode not in RETRIEVAL_MODES:
            raise HTTPException(400, f"未知检索模式: {req.retrieval_mode}")
        if mode != STATE.retrieval_mode:
            STATE.retrieval_mode = mode
            changed.append("retrieval_mode")

    if req.graph:
        gp = cwd / req.graph
        if not gp.is_file():
            raise HTTPException(400, f"图库文件不存在: {req.graph}")
        if str(gp) != STATE.graph_path:
            STATE.graph_path = str(gp)
            changed.append("graph")

    if changed:
        # register_tool is idempotent — this rebinds the ontology/SQL tools to
        # the new store + db_path (or Doris connection).
        doris_conn = (
            DorisConn(
                jdbc_url=STATE.doris_jdbc_url,
                username=STATE.doris_username,
                password=STATE.doris_password,
                driver=STATE.doris_driver,
                database=STATE.doris_database,
            )
            if STATE.use_doris
            else None
        )
        register_all(STATE.ontology_store, STATE.db_path, doris=doris_conn)
        # Reset sessions so the new system prompt / ontology take effect.
        STATE.session = None
        STATE.report_session = None
        STATE.active_report_ids = []

    return JSONResponse({
        "changed": changed,
        "ontology": os.path.basename(STATE.ontology_path),
        "database": DORIS_SOURCE_VALUE if STATE.use_doris else os.path.basename(STATE.db_path),
        "doris_jdbc_url": STATE.doris_jdbc_url if STATE.use_doris else "",
        "doris_database": STATE.doris_database if STATE.use_doris else "",
        "retrieval_mode": STATE.retrieval_mode,
        "graph": os.path.basename(STATE.graph_path) if STATE.graph_path else "",
    })


@app.post("/api/graph/build")
def build_graph_endpoint(req: GraphBuildRequest) -> JSONResponse:
    """Build a NetworkX graph library from the given ontology xlsx and write it
    as `<stem>.graphml` in the working dir (so it appears in the 图库源 list).
    Nodes = ontology elements; edges = 实体关系 (ER) + 本体元模型关系 (meta)."""
    cwd = Path(STATE.cwd)
    op = cwd / req.ontology
    if not op.is_file():
        raise HTTPException(400, f"本体文件不存在: {req.ontology}")
    out = cwd / (op.stem + ".graphml")
    try:
        from ..ontology.graph import build_from_xlsx
        stats = build_from_xlsx(str(op), str(out))
    except ImportError as e:
        raise HTTPException(500, f"未安装 networkx,无法构建图库: {e}")
    except Exception as e:
        raise HTTPException(400, f"图库构建失败: {e}")
    return JSONResponse({"graph": out.name, "stats": stats})


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


# ---------------------------------------------------------------------------
# 角色选择(用户画像 + Agent 回答风格)
# ---------------------------------------------------------------------------
class RolesRequest(BaseModel):
    user_role: str = ""    # key in USER_ROLES, or "" to clear
    agent_pref: str = ""   # key in AGENT_PREFS, or "" to clear


@app.get("/api/roles")
def get_roles() -> JSONResponse:
    return JSONResponse({
        "user_role": STATE.user_role,
        "agent_pref": STATE.agent_pref,
        "user_role_options": [{"key": k, "label": v[0], "desc": v[1]} for k, v in USER_ROLES.items()],
        "agent_pref_options": [{"key": k, "label": v[0], "desc": v[1]} for k, v in AGENT_PREFS.items()],
    })


@app.put("/api/roles")
def put_roles(req: RolesRequest) -> JSONResponse:
    # Validate against the known taxonomy; unknown keys clear the slot.
    STATE.user_role = req.user_role if req.user_role in USER_ROLES else ""
    STATE.agent_pref = req.agent_pref if req.agent_pref in AGENT_PREFS else ""
    block = _role_block()
    # Apply to live sessions so the change takes effect on the next turn —
    # no conversation reset needed.
    if STATE.session is not None:
        STATE.session.set_role_block(block)
    if STATE.report_session is not None:
        STATE.report_session.set_role_block(block)
    return JSONResponse({"ok": True, "user_role": STATE.user_role, "agent_pref": STATE.agent_pref})


# ---------------------------------------------------------------------------
# Conversation history (restorable 「最近」list)
# ---------------------------------------------------------------------------
class ConversationSaveRequest(BaseModel):
    mode: str = "data"                  # "data" | "report"
    title: Optional[str] = None
    chat_html: str = ""
    dashboard_html: str = ""
    cid: Optional[str] = None           # update in place when the browser has one


class ConversationRestoreRequest(BaseModel):
    id: str


def _require_conversation_store() -> ConversationStore:
    if STATE.conversation_store is None:
        raise HTTPException(500, "Server not configured; call configure() first.")
    return STATE.conversation_store


def _session_for_mode(mode: str) -> Optional[WebSession]:
    return STATE.report_session if mode == "report" else STATE.session


@app.get("/api/conversations")
def list_conversations(mode: Optional[str] = None) -> JSONResponse:
    store = _require_conversation_store()
    return JSONResponse({"conversations": store.list(mode)})


@app.post("/api/conversations/save")
def save_conversation(req: ConversationSaveRequest) -> JSONResponse:
    """Snapshot the active session of `mode` (its messages) + the supplied
    client-rendered chat/dashboard HTML, so it can be relisted and restored."""
    store = _require_conversation_store()
    mode = req.mode if req.mode in ("data", "report") else "data"
    session = _session_for_mode(mode)
    messages = list(session.messages) if session else []
    summary = store.save(
        mode=mode,
        title=req.title or "未命名对话",
        messages=messages,
        chat_html=req.chat_html,
        dashboard_html=req.dashboard_html,
        cid=req.cid,
    )
    return JSONResponse(summary)


@app.post("/api/conversations/restore")
def restore_conversation(req: ConversationRestoreRequest) -> JSONResponse:
    """Reinstate a stored conversation: reload its messages into the matching
    session (so the user can keep chatting) and return the saved HTML so the
    browser can re-render the transcript + dashboard."""
    store = _require_conversation_store()
    rec = store.get(req.id)
    if not rec:
        raise HTTPException(404, f"conversation not found: {req.id}")
    mode = rec.get("mode") or "data"
    messages = rec.get("messages") or []
    context_restored = False
    if mode == "report":
        # Report sessions are bound to uploaded reports; only reinstate context
        # when one is active. Otherwise the transcript is restored visually only.
        if STATE.report_session is not None:
            STATE.report_session.messages = list(messages)
            STATE.report_session.pending_tool_use_id = None
            STATE.report_session.pending_choice_spec = None
            STATE.report_session._pending_sibling_results = []
            context_restored = True
    else:
        _ensure_session()
        STATE.session.messages = list(messages)
        STATE.session.pending_tool_use_id = None
        STATE.session.pending_choice_spec = None
        STATE.session._pending_sibling_results = []
        context_restored = True
    return JSONResponse({
        "id": rec.get("id"),
        "mode": mode,
        "title": rec.get("title"),
        "chat_html": rec.get("chat_html") or "",
        "dashboard_html": rec.get("dashboard_html") or "",
        "context_restored": context_restored,
    })


@app.delete("/api/conversations/{cid}")
def delete_conversation(cid: str) -> JSONResponse:
    store = _require_conversation_store()
    return JSONResponse({"ok": store.delete(cid)})


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


@app.post("/api/report/generate")
def report_generate() -> JSONResponse:
    """Start a report-GENERATION session — runs IN report mode on the
    report-generator agent (ontology + DB tools), not bound to any
    uploaded report. The wizard sends the report config as the first
    chat message; the agent searches data and assembles the report.
    """
    if not STATE.ontology_store:
        raise HTTPException(500, "Server not configured; call configure() first.")
    reg = get_agent_def_registry()
    gen_agent = reg.get(REPORTGEN_AGENT_NAME)
    if gen_agent is None:
        raise HTTPException(
            500,
            f"Agent '{REPORTGEN_AGENT_NAME}' not found — 请在添加 "
            f".claude/agents/{REPORTGEN_AGENT_NAME}.md 后重启服务。",
        )
    STATE.report_session = WebSession(
        cwd=STATE.cwd,
        agent_def=gen_agent,
        ontology_store=STATE.ontology_store,
        tools_override=REPORT_DB_TOOLS,
        context_header="# 任务类型: 标准报表生成\n# 数据库工具可用性: enabled",
    )
    STATE.active_report_ids = []
    STATE.report_with_db = True
    return JSONResponse({"ok": True})


def _llm_complete(
    system_prompt: str,
    user_text: str,
    max_tokens: int = 3000,
    temperature: float = 0.3,
) -> str:
    """One-shot LLM completion — no tools, no agent loop. Returns the
    concatenated text. Raises RuntimeError on a provider error."""
    cfg = get_llm_config()
    chunks: list[str] = []
    for evt in stream_message(
        messages=[{"role": "user", "content": user_text}],
        system_prompt=system_prompt,
        allowed_tools=None,
        model_key=cfg.model_key,
        max_tokens=max_tokens,
        temperature=temperature,
        thinking=False,
    ):
        etype = evt.get("type")
        if etype == "text_delta":
            chunks.append(evt.get("text", ""))
        elif etype == "error":
            raise RuntimeError(evt.get("error", "LLM provider error"))
    return "".join(chunks).strip()


def _parse_json_object(raw: str) -> Optional[dict]:
    """Best-effort: extract the first {...} JSON object from an LLM reply."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        obj = json.loads(s[a:b + 1])
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


@app.post("/api/report/compose")
def report_compose(req: ReportComposeRequest) -> JSONResponse:
    """One LLM call: integrate the dashboard content blocks into a formal
    report-document structure — title, executive summary, and a sectioned
    table-of-contents with a per-section intro paragraph. The frontend
    then assembles the Word doc, interleaving the real tables/charts."""
    blocks = req.blocks or []
    if not blocks:
        raise HTTPException(400, "no content blocks to compose")

    lines = []
    for b in blocks:
        c = " ".join((b.content or "").split())
        if len(c) > 600:
            c = c[:600] + "…"
        lines.append(
            f"[{b.idx}] 类型={b.kind} 标题={b.title or '(无)'} 内容={c or '(无)'}"
        )
    manifest = "\n".join(lines)

    system_prompt = (
        "你是一名资深报表编辑。用户会给你一份报表的「内容块清单」"
        "(每块有编号、类型 text/table/chart、标题、内容摘要)。"
        "请把这些内容块整合成一份正式报表文档的结构,并**只输出 JSON**"
        "(不要 markdown 代码围栏、不要任何额外文字)。\n\n"
        "JSON 结构:\n"
        '{\n'
        '  "title": "报表标题(简洁专业)",\n'
        '  "summary": "执行摘要,150-300字,综述核心情况与结论",\n'
        '  "sections": [\n'
        '    {"heading": "一、章节标题", "intro": "本节简介段落,60-150字",'
        ' "blocks": [内容块编号数组]}\n'
        '  ]\n'
        "}\n\n"
        "规则:章节 3-6 个,按主题归类;每个内容块必须且只能归入一个章节的 "
        "blocks;blocks 用清单里的编号;heading 带「一、二、三、」序号;"
        "不要编造清单里没有的数据。"
    )
    user_text = (
        f"报表内容块清单(共 {len(blocks)} 块):\n{manifest}\n\n"
        "请把以上内容整合为报表文档结构,按要求只输出 JSON。"
    )
    try:
        raw = _llm_complete(system_prompt, user_text, max_tokens=3000)
    except Exception as e:
        raise HTTPException(502, f"大模型调用失败: {e}")
    plan = _parse_json_object(raw)
    if not plan or not isinstance(plan.get("sections"), list):
        raise HTTPException(502, "大模型未返回可解析的报表结构")
    return JSONResponse(plan)


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
        tools_override = None
        context_header = None
        if STATE.retrieval_mode == "graph":
            base = list(STATE.agent_def.tools or [])
            tools_override = base + [t for t in GRAPH_TOOL_NAMES if t not in base]
            context_header = GRAPH_MODE_SOP
        STATE.session = WebSession(
            cwd=STATE.cwd,
            agent_def=STATE.agent_def,
            ontology_store=STATE.ontology_store,
            tools_override=tools_override,
            context_header=context_header,
            role_block=_role_block(),
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
        role_block=_role_block(),
    )
