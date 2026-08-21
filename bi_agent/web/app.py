"""FastAPI app exposing the BI agent as a web chat with a live inspector panel."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from html import escape
from urllib.error import HTTPError, URLError
from urllib.request import Request as UpstreamRequest
from urllib.request import urlopen
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.gzip import GZipMiddleware

from open_claude.agent_def import AgentDef, get_agent_def_registry, load_agent_defs

from ..llm.provider import stream_message
from ..llm.registry import list_models
from ..llm.runtime_config import (
    get_api_key_status,
    get_config as get_llm_config,
    set_api_key,
)
from ..paths import (
    CHARTS_DIR,
    DATABASES_DIR,
    GRAPHS_DIR,
    HTML_DIR,
    SPREADSHEETS_DIR,
    project_path,
)
from ..ontology.store import OntologyStore
from ..ontology.remote import OntologyApiError, RemoteOntologyClient
from ..report import ReportStore, parser_availability
from ..tools import build_source_executors, register_all
from ..tools.graph_tools import GRAPH_TOOL_NAMES
from ..tools.sql_tools import (
    DEFAULT_DORIS_DATABASE,
    DEFAULT_DORIS_API_URL,
    DEFAULT_DORIS_DRIVER,
    DEFAULT_DORIS_JDBC_URL,
    DEFAULT_DORIS_PASSWORD,
    DEFAULT_DORIS_USERNAME,
    DorisConn,
    DorisHttpConn,
)
from .conversations import ConversationStore, sanitize_source_config
from .session import WebSession


logger = logging.getLogger(__name__)


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
        self.remote_ontology: Optional[RemoteOntologyClient] = None
        # The manager catalog is a runtime dependency for source switching,
        # not a process-startup dependency. Keep its last error for the UI.
        self.remote_catalog_error: str = ""
        self.remote_catalog_last_attempt: float = 0.0
        self.ontology_backend: str = os.environ.get("ONTOLOGY_BACKEND", "local").strip().lower()
        self.ontology_namespace: str = os.environ.get("ONTOLOGY_NAMESPACE", "").strip()
        self.agent_def: Optional[AgentDef] = None
        self.session: Optional[WebSession] = None
        # Named browser sessions own both their conversation and their source
        # snapshot. The legacy singleton remains the empty-id compatibility
        # path for existing API clients and tests.
        self.sessions: dict[str, WebSession] = {}
        self.source_contexts: dict[str, SimpleNamespace] = {}
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
        self.doris_api_url: str = os.environ.get("DORIS_API_URL", DEFAULT_DORIS_API_URL)
        self.use_doris: bool = False
        # --- Ontology retrieval mode ------------------------------------
        # "semantic" (default): retrieve ontology knowledge from the local
        # workbook or the configured remote ontology API. "graph": enable the
        # bounded GraphContext/GraphExpand tools; in remote mode these call the
        # production ontology service rather than the local workbook.
        self.retrieval_mode: str = os.environ.get("RETRIEVAL_MODE", "semantic")
        self.graph_path: str = os.environ.get("GRAPH_PATH", "")
        # --- Report-analysis mode ---------------------------------------
        # Multiple reports may be active simultaneously. The ordered list
        # below preserves the user's selection order so prompt sections,
        # attach-chip labels, and the agent's report-numbering all line up.
        self.report_store: Optional[ReportStore] = None
        self.report_session: Optional[WebSession] = None
        self.report_sessions: dict[str, WebSession] = {}
        self.report_ids_by_session: dict[str, list[str]] = {}
        self.report_db_by_session: dict[str, bool] = {}
        self.active_report_ids: list[str] = []
        self.report_with_db: bool = False
        # --- Conversation history (restorable 最近 list) -----------------
        self.conversation_store: Optional[ConversationStore] = None
        # Optional canonical history endpoint. Local development can point to
        # the server so every completed turn is mirrored there.
        self.conversation_sync_url: str = os.environ.get("CONVERSATION_SYNC_URL", "").strip().rstrip("/")
        # --- 角色选择(用户画像 + Agent 回答风格偏好)-------------------
        # Injected into every session's system prompt so the agent adapts its
        # depth / terminology / tone. Empty = no role preference applied.
        self.user_role: str = ""
        self.agent_pref: str = ""
        self.roles_by_session: dict[str, tuple[str, str]] = {}


STATE = AppState()


# Tool list for "启用数据库查询" mode — mirrors the report-analyst agent def.
# ChartGenerateMultiDim is included because deep-insight drill-down requires
# running multi-dim SQL queries; only meaningful when DB tools are on.
REPORT_DB_TOOLS: list[str] = [
    "OntologyQuery", "TermDisambiguate", "MetricLookup", "RelationLookup",
    "EntityDescribe", "ListBusinessObjects", "MetricDataQuery", "SQLRun", "ListTables",
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


def _role_values(session_id: Optional[str] = None) -> tuple[str, str]:
    key = _session_key(session_id)
    if key and key in STATE.roles_by_session:
        return STATE.roles_by_session[key]
    return STATE.user_role, STATE.agent_pref


def _role_block(session_id: Optional[str] = None) -> Optional[str]:
    """Render the 用户画像/回答风格 system-prompt block from STATE, or None."""
    user_role, agent_pref = _role_values(session_id)
    user = USER_ROLES.get(user_role)
    pref = AGENT_PREFS.get(agent_pref)
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


def _doris_http_conn(
    api_url: str,
    database: str,
    remote: Optional[RemoteOntologyClient] = None,
) -> DorisHttpConn:
    """Build a Doris connection carrying the active ontology identity."""
    client = remote if remote is not None else STATE.remote_ontology
    return DorisHttpConn(
        api_url,
        database,
        repository_id=(client.repository_id if client else ""),
        app_id=(client.app_id if client else ""),
        auth_token=(client.auth_token if client else ""),
    )


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
    #   - Team gateway models need TEAM_API_KEY
    # The server boots regardless; failures surface when the user hits that model.

    STATE.cwd = cwd
    STATE.db_path = db_path
    STATE.ontology_path = ontology_path
    STATE.use_doris = use_doris
    remote_mode = STATE.ontology_backend in {"production", "remote"}
    if remote_mode:
        # Production is remote-only: do not open, validate, or retain an Excel
        # workbook. The empty store only satisfies legacy render/session types;
        # every ontology executor and browse endpoint is remote-bound below.
        STATE.ontology_store = OntologyStore()
        try:
            STATE.remote_ontology = RemoteOntologyClient.from_env()
        except ValueError as e:
            raise RuntimeError(f"远程本体配置无效: {e}") from e
        try:
            catalog = _remote_repository_catalog(STATE.remote_ontology)
        except OntologyApiError as e:
            # The manager catalog is needed for source switching, not for
            # booting the workbench. Keep the configured repository and the
            # existing paired Doris defaults; ontology calls will report the
            # dependency error if the remote service is still down.
            STATE.remote_catalog_error = str(e)
            STATE.remote_catalog_last_attempt = time.monotonic()
            STATE.ontology_namespace = STATE.ontology_namespace or STATE.remote_ontology.namespace
            STATE.remote_ontology.namespace = STATE.ontology_namespace
            print(
                "[bi-agent-web] warning: remote ontology catalog unavailable; "
                f"source selection/query will report the dependency error: {e}"
            )
        else:
            STATE.remote_catalog_error = ""
            STATE.remote_catalog_last_attempt = 0.0
            repository = next((item for item in catalog if item["id"] == STATE.remote_ontology.repository_id), None)
            if repository is None:
                raise RuntimeError(f"远程本体库 {STATE.remote_ontology.repository_id} 不在可用目录中")
            if not repository["dorisDatabase"]:
                raise RuntimeError(f"远程本体库 {repository['name']} 未配置 dorisDatabase")
            if not repository["namespace"]:
                raise RuntimeError(f"远程本体库 {repository['name']} 未配置 namespaceCode")
            STATE.ontology_namespace = repository["namespace"]
            STATE.doris_database = repository["dorisDatabase"]
            STATE.remote_ontology.namespace = repository["namespace"]
        STATE.use_doris = True
    else:
        STATE.ontology_store = OntologyStore.from_xlsx(ontology_path)
        STATE.remote_ontology = None

    doris_conn = (
        _doris_http_conn(STATE.doris_api_url, STATE.doris_database, STATE.remote_ontology)
        if STATE.use_doris else None
    )
    register_all(
        STATE.ontology_store,
        db_path,
        doris=doris_conn,
        remote_ontology=STATE.remote_ontology,
    )
    STATE.sessions.clear()
    STATE.source_contexts.clear()
    STATE.report_sessions.clear()
    STATE.report_ids_by_session.clear()
    STATE.report_db_by_session.clear()
    STATE.roles_by_session.clear()

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
    migrated_titles = STATE.conversation_store.last_title_migrations
    if migrated_titles:
        print(f"[bi-agent-web] canonicalized {migrated_titles} conversation title(s)")
    print(
        f"[bi-agent-web] history_root={STATE.conversation_store.root} "
        f"scanned={STATE.conversation_store.last_title_migration_scanned} "
        f"corrected={migrated_titles} "
        f"unresolved={STATE.conversation_store.last_unresolved_title_migrations} "
        f"index_entries={STATE.conversation_store.last_index_rebuild_count} "
        "authority=local sync=disabled"
    )

    # Generated charts are served by the /charts route below so old files that
    # reference the public ECharts CDN can be rewritten to our local asset.
    project_path(cwd, CHARTS_DIR).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="BI Agent Web", version="0.1.0")
# Compress JSON and the large versioned frontend assets when the browser
# advertises gzip support. The threshold avoids spending CPU on tiny assets;
# Brotli can still be supplied by a reverse proxy without changing endpoints.
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)


@app.get("/charts/{filename:path}")
def serve_chart(filename: str):
    """Serve standalone charts with a local ECharts fallback.

    Historical chart HTML files were generated with a CDN script URL. Replacing
    that URL at response time keeps old history links renderable in offline or
    restricted browser environments too.
    """
    charts_dir = project_path(STATE.cwd, CHARTS_DIR)
    target = (charts_dir / filename).resolve()
    if charts_dir not in target.parents or not target.is_file():
        raise HTTPException(404, "图表不存在")
    if target.suffix.lower() == ".html":
        html = target.read_text(encoding="utf-8", errors="replace")
        html = html.replace(
            "https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js",
            "/static/vendor/echarts.min.js",
        )
        return HTMLResponse(html)
    return FileResponse(target)


class ChatRequest(BaseModel):
    message: str
    visible_user_text: Optional[str] = None
    session_id: Optional[str] = None


class ChoiceRequest(BaseModel):
    # Multi-select (preferred). Single-pick clients can send lists of length 1.
    choice_ids: Optional[List[str]] = None
    choice_labels: Optional[List[str]] = None
    # Back-compat: legacy single-pick fields.
    choice_id: Optional[str] = None
    choice_label: Optional[str] = None
    session_id: Optional[str] = None

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
    team_api_key: Optional[str] = None


# Sentinel `database` value meaning "use the Doris (MySQL protocol) source"
# instead of a local .db file. Surfaced as a selectable option in /api/sources.
DORIS_SOURCE_VALUE = "__doris_api__"
REMOTE_ONTOLOGY_PREFIX = "__metaerp_repository__:"
REMOTE_DORIS_PREFIX = "__doris_repository__:"
# Pseudo-source shown in 本体适配. It represents the production ontology
# service, not a local workbook.
METAERP_ONTOLOGY_VALUE = "__metaerp_ontology__"
LEGACY_PRODUCTION_ONTOLOGY_VALUE = "__production_ontology__"

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
- 它会综合活动/流程、实体关系、指标/维度/属性映射及图库中的其他有证据路径找到关联业务对象,展示关系方向与最短路径,再把这些对象作为新锚点下钻关联子树。
- **仅在已有上下文确实不够时调用**;够用就不必扩散。
"""


class SourcesUpdate(BaseModel):
    """Switch the active ontology / database source. Omit a field to keep it."""
    ontology: Optional[str] = None   # xlsx filename, relative to cwd
    database: Optional[str] = None   # .db, generic Doris, or paired remote Doris value
    # Doris connection params (used when database == DORIS_SOURCE_VALUE)
    doris_jdbc_url: Optional[str] = None
    doris_api_url: Optional[str] = None
    doris_driver: Optional[str] = None
    doris_username: Optional[str] = None
    doris_password: Optional[str] = None
    doris_database: Optional[str] = None
    # Ontology retrieval mode ("semantic" | "graph") + an optional local graph
    # file. Remote graph mode is backed by the active remote repository API and
    # does not expose or consume this field.
    retrieval_mode: Optional[str] = None
    graph: Optional[str] = None
    session_id: Optional[str] = None


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
    blocks: List[ReportComposeBlock] = Field(default_factory=list)


def _project_root() -> Path:
    # Prefer the cwd configured at startup; fall back to repo root inferred from this file.
    if STATE.cwd:
        return Path(STATE.cwd)
    return Path(__file__).resolve().parents[2]


def _html_page(filename: str) -> Path:
    """Return a standalone page from the project's consolidated HTML folder."""
    return _project_root() / HTML_DIR / filename


def _cwd_file(name: str, *, label: str) -> Path:
    """Resolve a user-selected working-directory file without path escape."""
    root = Path(STATE.cwd).resolve()
    candidate = (root / str(name or "")).resolve()
    if candidate == root or root not in candidate.parents:
        raise HTTPException(400, f"{label}路径无效")
    # Accept basename-only values saved by releases that predate dataset/.
    # New API responses always contain the canonical relative path.
    if not candidate.exists() and Path(str(name)).parent == Path("."):
        suffix = candidate.suffix.lower()
        legacy_dir = (
            SPREADSHEETS_DIR if suffix in {".xlsx", ".xls"}
            else DATABASES_DIR if suffix == ".db"
            else GRAPHS_DIR if suffix in {Path(pat).suffix for pat in GRAPH_PATTERNS}
            else None
        )
        if legacy_dir is not None:
            migrated = project_path(root, legacy_dir) / candidate.name
            if migrated.is_file():
                candidate = migrated
    return candidate


def _cwd_relative_value(path: str) -> str:
    """Represent a configured source relative to cwd when it lives in-project."""
    if not path:
        return ""
    try:
        return Path(path).resolve().relative_to(Path(STATE.cwd).resolve()).as_posix()
    except ValueError:
        return os.path.basename(path)


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
def index(request: Request) -> RedirectResponse:
    # The standalone workbench is the primary entry point. The role dashboard
    # remains directly available at /dashboard.html for embedded/dashboard use.
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(url=f"/workbench{query}", status_code=307)


@app.get("/healthz")
def healthz() -> JSONResponse:
    """Dependency-free liveness/readiness probe; never invokes an LLM."""
    ontology_ready = (
        STATE.remote_ontology is not None
        if STATE.ontology_backend in {"production", "remote"}
        else STATE.ontology_store is not None
    )
    ready = bool(STATE.agent_def and ontology_ready and STATE.conversation_store)
    return JSONResponse(
        {"ok": ready, "configured": ready, "llm_call": False},
        status_code=200 if ready else 503,
    )


@app.get("/ceo_dashboard_standalone.html")
def ceo_dashboard_standalone_page() -> FileResponse:
    return _no_cache_file(_html_page("ceo_dashboard_standalone.html"))


@app.get("/ceo_cockpit.html")
def ceo_cockpit_page() -> FileResponse:
    return FileResponse(_html_page("ceo_cockpit.html"))


@app.get("/dashboard.html")
def role_dashboard_page() -> FileResponse:
    return _no_cache_file(_html_page("dashboard.html"))


@app.get("/asset_overdue_inventory.html")
def asset_overdue_inventory_page() -> FileResponse:
    return FileResponse(_html_page("asset_overdue_inventory.html"))


@app.get("/ceo_dashboard.html")
def ceo_dashboard_page() -> FileResponse:
    return _no_cache_file(_html_page("ceo_dashboard.html"))


@app.get("/new_analysis_nav_chat_board.html")
def analysis_nav_prototype_page() -> FileResponse:
    return _no_cache_file(_html_page("new_analysis_nav_chat_board.html"))


@app.get("/workbench")
def workbench() -> FileResponse:
    return _no_cache_file(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/api/meta")
def get_meta(session_id: str = "") -> JSONResponse:
    source = _source_for_session(session_id)
    if not STATE.agent_def or source.ontology_store is None:
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
        "ontology_stats": _remote_ontology_stats(source.remote_ontology) if source.remote_ontology else source.ontology_store.stats(),
        "db_path": os.path.basename(source.db_path),
        "cwd": STATE.cwd,
        "ontology_backend": "production" if source.ontology_backend == "remote" else source.ontology_backend,
        "ontology_service": {
            "configured": source.remote_ontology is not None,
            "base_url": source.remote_ontology.base_url if source.remote_ontology else "",
            "repository_id": source.remote_ontology.repository_id if source.remote_ontology else "",
        },
        "llm": {
            "models": list_models(),
            "current": cfg.to_dict(),
            "api_keys": get_api_key_status(),
        },
    })


def _remote_ontology_stats(client: RemoteOntologyClient) -> dict[str, int]:
    now = time.monotonic()
    cached = getattr(client, "_stats_cache", None)
    if cached and now - cached[0] <= client.cache_ttl:
        return dict(cached[1])
    stats: dict[str, int] = {}
    for type_name in (
        "Term", "BusinessObject", "LogicalEntity", "BusinessAttribute",
        "Indicator", "Dimension", "Rule", "TableNode", "Column",
    ):
        try:
            data = client.script_query("sql", f"SELECT count(*) AS count FROM {type_name}")
            rows = [row for result in data.get("results") or [] for row in result.get("rows") or []]
            value = (rows[0].get("count") if rows else 0) or 0
            stats[type_name] = int(_scalar_remote_value(value))
        except (OntologyApiError, TypeError, ValueError):
            stats[type_name] = 0
    client._stats_cache = (now, dict(stats))
    return stats


def _scalar_remote_value(value: Any) -> Any:
    while isinstance(value, list) and len(value) == 1:
        value = value[0]
    if isinstance(value, dict) and set(value) == {"value"}:
        return _scalar_remote_value(value["value"])
    return value


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
        if "team_api_key" in payload:
            set_api_key("team", payload["team_api_key"])
    except ValueError as e:
        raise HTTPException(400, str(e))

    return JSONResponse({
        "models": list_models(),
        "current": cfg.to_dict(),
        "api_keys": get_api_key_status(),
    })


def _remote_repository_catalog(client: RemoteOntologyClient) -> list[dict[str, Any]]:
    """Return the complete remote catalog with stable paired source values."""
    repositories: list[dict[str, Any]] = []
    page = 1
    seen_ids: set[str] = set()
    while page <= 100:
        listing = client.list_repositories(page=page, size=100)
        items = listing.get("items") if isinstance(listing, dict) else []
        if not isinstance(items, list) or not items:
            break
        for item in items:
            if not isinstance(item, dict) or item.get("id") is None:
                continue
            repository_id = str(item["id"])
            if repository_id in seen_ids:
                continue
            seen_ids.add(repository_id)
            # The repository manager currently returns `currentDatabase`;
            # older deployments called the same paired source field
            # `dorisDatabase`. Accept both without hard-coding a business DB.
            database = str(item.get("dorisDatabase") or item.get("currentDatabase") or "").strip()
            repositories.append({
                "id": repository_id,
                "name": str(item.get("name") or f"本体库 {repository_id}"),
                "description": str(item.get("description") or ""),
                "dorisDatabase": database,
                "namespace": str(item.get("namespaceCode") or item.get("namespace") or "").strip(),
                "value": f"{REMOTE_ONTOLOGY_PREFIX}{repository_id}",
                "databaseValue": f"{REMOTE_DORIS_PREFIX}{repository_id}" if database else "",
            })
        total = int(listing.get("total") or 0) if isinstance(listing, dict) else 0
        if (total and len(repositories) >= total) or (not total and len(items) < 100):
            break
        page += 1
    return repositories


_SOURCE_CONTEXT_FIELDS = (
    "ontology_store", "remote_ontology", "ontology_backend", "ontology_namespace", "ontology_path",
    "db_path", "use_doris", "doris_jdbc_url", "doris_driver",
    "doris_username", "doris_password", "doris_database", "doris_api_url",
    "retrieval_mode", "graph_path", "remote_catalog_error", "remote_catalog_last_attempt",
)


def _session_key(session_id: Optional[str]) -> str:
    return str(session_id or "").strip()[:128]


def _snapshot_source(source: Any = None) -> SimpleNamespace:
    source = source or STATE
    return SimpleNamespace(**{
        name: getattr(source, name) for name in _SOURCE_CONTEXT_FIELDS
    })


def _source_for_session(session_id: Optional[str]) -> Any:
    key = _session_key(session_id)
    if not key:
        return STATE
    if key not in STATE.source_contexts:
        STATE.source_contexts[key] = _snapshot_source()
    return STATE.source_contexts[key]


def _source_binding_signature(source: Any) -> tuple[Any, ...]:
    remote = source.remote_ontology
    return (
        source.ontology_backend,
        remote.repository_id if remote else "",
        source.ontology_namespace,
        source.ontology_path,
        source.use_doris,
        source.db_path,
        source.doris_api_url,
        source.doris_jdbc_url,
        source.doris_driver,
        source.doris_username,
        source.doris_password,
        source.doris_database,
    )


@app.get("/api/sources")
def get_sources_endpoint(session_id: str = "") -> JSONResponse:
    """List selectable, paired ontology and database sources."""
    source = _source_for_session(session_id)
    cwd = Path(STATE.cwd).resolve()

    def _scan(directory: Path, pattern: str) -> list[str]:
        root = project_path(cwd, directory)
        return sorted(
            p.relative_to(cwd).as_posix() for p in root.glob(pattern)
            if p.is_file() and not p.name.startswith("~$")
        )

    # The local graph file remains visible as a read-only compatibility hint in
    # remote mode, but remote graph retrieval never consumes it.
    graph_options: list[str] = []
    production_source = source.ontology_backend in {"production", "remote"}
    for pat in GRAPH_PATTERNS:
        graph_options.extend(_scan(GRAPHS_DIR, pat))
    graph_options = sorted(set(graph_options))
    local_ontology_options = [] if production_source else _scan(SPREADSHEETS_DIR, "*.xlsx")
    ontology_options = local_ontology_options + [METAERP_ONTOLOGY_VALUE]
    # The production service exposes all selectable repositories through the
    # documented manager endpoint. Keep the local Excel entries as offline
    # fallbacks, and expose each remote repository by its stable id.
    remote_repositories: list[dict[str, Any]] = []
    if source.remote_ontology is not None:
        # Do not make every settings-page open wait for a dead manager
        # endpoint. Retry after a short cooldown so recovery is picked up
        # without requiring a process restart.
        catalog_retry_due = (
            not source.remote_catalog_error
            or time.monotonic() - source.remote_catalog_last_attempt >= 30
        )
        try:
            if catalog_retry_due:
                source.remote_catalog_last_attempt = time.monotonic()
                remote_repositories = _remote_repository_catalog(source.remote_ontology)
                source.remote_catalog_error = ""
                source.remote_catalog_last_attempt = 0.0
        except OntologyApiError as exc:
            # A manager outage must not make the active atomic source disappear
            # from either settings page. Keep the current pair selectable; new
            # repository switches remain unavailable until the catalog recovers.
            repository_id = source.remote_ontology.repository_id
            source.remote_catalog_error = source.remote_catalog_error or str(exc)
            remote_repositories = [{
                "id": repository_id,
                "name": f"本体库 {repository_id}（目录暂不可用）",
                "description": "",
                "dorisDatabase": source.doris_database,
                "namespace": source.ontology_namespace or source.remote_ontology.namespace,
                "value": f"{REMOTE_ONTOLOGY_PREFIX}{repository_id}",
                "databaseValue": f"{REMOTE_DORIS_PREFIX}{repository_id}",
            }]
        if not remote_repositories and source.remote_catalog_error:
            repository_id = source.remote_ontology.repository_id
            remote_repositories = [{
                "id": repository_id,
                "name": f"本体库 {repository_id}（目录暂不可用）",
                "description": "",
                "dorisDatabase": source.doris_database,
                "namespace": source.ontology_namespace or source.remote_ontology.namespace,
                "value": f"{REMOTE_ONTOLOGY_PREFIX}{repository_id}",
                "databaseValue": f"{REMOTE_DORIS_PREFIX}{repository_id}",
            }]
    if remote_repositories:
        # Keep the original local Excel sources and append the real remote
        # repository catalog. Repository IDs remain internal option values.
        ontology_options = local_ontology_options + [repo["value"] for repo in remote_repositories]
    ontology_active = (
        METAERP_ONTOLOGY_VALUE
        if source.ontology_backend in {"production", "remote"}
        else _cwd_relative_value(source.ontology_path)
    )
    if source.remote_ontology is not None:
        current_repo_value = f"{REMOTE_ONTOLOGY_PREFIX}{source.remote_ontology.repository_id}"
        if any(repo["value"] == current_repo_value for repo in remote_repositories):
            ontology_active = current_repo_value

    # Every managed remote repository declares exactly one Doris database.
    # Surface those pairs as first-class database choices; keep the generic
    # Doris value for backwards-compatible custom schemas.
    remote_db_options = [
        repo["databaseValue"] for repo in remote_repositories if repo["databaseValue"]
    ]
    local_db_options = [] if production_source else _scan(DATABASES_DIR, "*.db")
    db_options = local_db_options + remote_db_options + ([] if production_source else [DORIS_SOURCE_VALUE])
    db_active = _cwd_relative_value(source.db_path)
    if source.use_doris:
        paired = next((
            repo for repo in remote_repositories
            if repo["dorisDatabase"] == source.doris_database
            and (
                source.remote_ontology is None
                or repo["id"] == source.remote_ontology.repository_id
            )
        ), None)
        db_active = paired["databaseValue"] if paired else DORIS_SOURCE_VALUE
    return JSONResponse({
        "atomic_source": {
            "repository_id": source.remote_ontology.repository_id if source.remote_ontology else "",
            "namespace": source.ontology_namespace if source.remote_ontology else "",
            "doris_database": source.doris_database if source.remote_ontology else "",
        },
        "ontology": {
            "options": ontology_options,
            "active": ontology_active,
            "production": {
                "value": METAERP_ONTOLOGY_VALUE,
                "label": "MetaERP",
                "active": ontology_active == METAERP_ONTOLOGY_VALUE,
                "base_url": source.remote_ontology.base_url if source.remote_ontology else os.environ.get("ONTOLOGY_BASE_URL", ""),
                "repository_id": source.remote_ontology.repository_id if source.remote_ontology else os.environ.get("ONTOLOGY_REPOSITORY_ID", ""),
            },
            "remote_repositories": remote_repositories,
            "remote_status": {
                "available": not bool(source.remote_catalog_error),
                "message": source.remote_catalog_error,
            },
        },
        "database": {
            "options": db_options,
            "active": db_active,
            "remote_databases": remote_repositories,
        },
        "retrieval": {
            "mode": source.retrieval_mode,
            "graph": {
                "options": graph_options,
                "active": _cwd_relative_value(source.graph_path) if source.graph_path else "",
            },
        },
        "doris": {
            "value": DORIS_SOURCE_VALUE,
            "active": source.use_doris,
            "api_url": source.doris_api_url,
            "jdbc_url": source.doris_jdbc_url,
            "driver": source.doris_driver,
            "username": source.doris_username,
            # Never return the configured password to the browser.  A blank
            # optional value on PUT means "keep the existing password".
            "password": "",
            "database": source.doris_database,
        },
    }, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


@app.put("/api/sources")
def put_sources_endpoint(req: SourcesUpdate) -> JSONResponse:
    """Apply a source switch as one state transaction."""
    key = _session_key(req.session_id)
    source = _source_for_session(key)
    fields = list(_SOURCE_CONTEXT_FIELDS)
    if not key:
        fields.extend(("session", "report_session", "active_report_ids"))
    snapshot = {name: getattr(source, name) for name in fields}
    try:
        response = _put_sources_endpoint_impl(req, source, register_global=not key)
        changed = json.loads(response.body).get("changed") or []
        if key and changed:
            STATE.sessions.pop(key, None)
            STATE.report_sessions.pop(key, None)
            STATE.report_ids_by_session.pop(key, None)
            STATE.report_db_by_session.pop(key, None)
        return response
    except Exception:
        for name, value in snapshot.items():
            setattr(source, name, value)
        # Best-effort rebind; preserve the original validation error.
        try:
            if key:
                raise RuntimeError("session-local source does not use global registry")
            previous_doris = (
                _doris_http_conn(
                    snapshot["doris_api_url"],
                    snapshot["doris_database"],
                    snapshot["remote_ontology"],
                )
                if snapshot["use_doris"] else None
            )
            register_all(
                snapshot["ontology_store"],
                snapshot["db_path"],
                doris=previous_doris,
                remote_ontology=snapshot["remote_ontology"],
            )
        except Exception:
            pass
        raise


def _put_sources_endpoint_impl(
    req: SourcesUpdate,
    source: Any = None,
    *,
    register_global: bool = True,
) -> JSONResponse:
    """Switch the active ontology / database at runtime. Re-registers the
    BI tools against the new sources and resets sessions so the change
    takes effect on the next turn."""
    source = source or STATE
    binding_before = _source_binding_signature(source)
    cwd = Path(STATE.cwd)
    changed: list[str] = []

    def _mark(name: str) -> None:
        if name not in changed:
            changed.append(name)

    ontology_repo_id = ""
    if req.ontology and req.ontology.startswith(REMOTE_ONTOLOGY_PREFIX):
        ontology_repo_id = req.ontology[len(REMOTE_ONTOLOGY_PREFIX):].strip()
        if not ontology_repo_id:
            raise HTTPException(400, "本体库 ID 不能为空")

    database_repo_id = ""
    if req.database and req.database.startswith(REMOTE_DORIS_PREFIX):
        database_repo_id = req.database[len(REMOTE_DORIS_PREFIX):].strip()
        if not database_repo_id:
            raise HTTPException(400, "Doris 数据库对应的本体库 ID 不能为空")

    seed_remote = source.remote_ontology
    if (
        ontology_repo_id
        or database_repo_id
        or req.ontology in {METAERP_ONTOLOGY_VALUE, LEGACY_PRODUCTION_ONTOLOGY_VALUE}
    ):
        if seed_remote is None:
            try:
                seed_remote = RemoteOntologyClient.from_env()
            except ValueError as e:
                raise HTTPException(400, f"生产本体库配置无效: {e}") from e
        if req.ontology in {METAERP_ONTOLOGY_VALUE, LEGACY_PRODUCTION_ONTOLOGY_VALUE}:
            ontology_repo_id = seed_remote.repository_id

    if ontology_repo_id and database_repo_id and ontology_repo_id != database_repo_id:
        raise HTTPException(400, "本体库与数据库不属于同一数据源,请重新选择")

    paired_repo_id = database_repo_id or ontology_repo_id
    if paired_repo_id:
        assert seed_remote is not None
        same_remote_pair = (
            source.remote_ontology is not None
            and source.remote_ontology.repository_id == paired_repo_id
            and bool(source.ontology_namespace or source.remote_ontology.namespace)
            and bool(source.doris_database)
        )
        if same_remote_pair:
            # Re-saving settings, or changing only retrieval mode/API transport,
            # must keep working during a temporary manager-catalog outage. The
            # current context is already an authoritative, previously validated
            # atomic pair, so a new catalog lookup is unnecessary.
            repository = {
                "id": paired_repo_id,
                "name": f"本体库 {paired_repo_id}",
                "namespace": source.ontology_namespace or source.remote_ontology.namespace,
                "dorisDatabase": source.doris_database,
            }
        else:
            try:
                catalog = _remote_repository_catalog(seed_remote)
            except OntologyApiError as e:
                raise HTTPException(502, f"无法读取本体库与数据库映射: {e}") from e
            repository = next((item for item in catalog if item["id"] == paired_repo_id), None)
        if repository is None:
            raise HTTPException(400, f"未找到本体库 ID {paired_repo_id}")
        paired_database = repository["dorisDatabase"]
        if not paired_database:
            raise HTTPException(400, f"本体库 {repository['name']} 未配置 dorisDatabase")
        if not repository["namespace"]:
            raise HTTPException(400, f"本体库 {repository['name']} 未配置 namespaceCode")

        # The repository and its declared Doris database are one atomic source.
        # Selecting either side always updates both sides before tools are rebound.
        source.remote_ontology = RemoteOntologyClient(
            seed_remote.base_url,
            paired_repo_id,
            app_id=seed_remote.app_id,
            auth_token=seed_remote.auth_token,
            namespace=repository["namespace"],
            timeout=seed_remote.timeout,
        )
        source.ontology_backend = "production"
        source.ontology_namespace = repository["namespace"]
        api_url = (req.doris_api_url or source.doris_api_url or DEFAULT_DORIS_API_URL).strip()
        if not api_url.startswith(("http://", "https://")):
            raise HTTPException(400, "请填写 Doris HTTP API 地址(例如 http://host:30834/agent/doris/query)")
        try:
            _doris_http_conn(api_url, paired_database, source.remote_ontology)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        source.doris_api_url = api_url
        source.doris_database = paired_database
        source.doris_jdbc_url = (req.doris_jdbc_url or source.doris_jdbc_url or "").strip()
        source.doris_driver = (req.doris_driver or source.doris_driver or DEFAULT_DORIS_DRIVER).strip()
        if req.doris_username is not None:
            source.doris_username = req.doris_username
        if req.doris_password is not None:
            source.doris_password = req.doris_password
        source.use_doris = True
        _mark("ontology")
        _mark("database")
    elif req.ontology:
        op = _cwd_file(req.ontology, label="本体文件")
        if not op.is_file():
            raise HTTPException(400, f"本体文件不存在: {req.ontology}")
        same_local = (
            source.remote_ontology is None
            and source.ontology_backend == "local"
            and Path(source.ontology_path).resolve() == op.resolve()
        )
        if not same_local:
            try:
                store = OntologyStore.from_xlsx(str(op))
            except Exception as e:  # surface load errors to the UI
                raise HTTPException(400, f"本体文件无法加载: {req.ontology} — {e}")
            source.ontology_store = store
            source.ontology_path = str(op)
            source.ontology_backend = "local"
            source.remote_ontology = None
            _mark("ontology")

    if not paired_repo_id and req.database == DORIS_SOURCE_VALUE:
        # Switch the SQL tools to the team's Doris HTTP query API.
        api_url = (req.doris_api_url or source.doris_api_url or DEFAULT_DORIS_API_URL).strip()
        jdbc = (req.doris_jdbc_url or source.doris_jdbc_url or "").strip()
        username = req.doris_username if req.doris_username is not None else source.doris_username
        password = req.doris_password if req.doris_password is not None else source.doris_password
        driver = (req.doris_driver or source.doris_driver or DEFAULT_DORIS_DRIVER).strip()
        database = (req.doris_database or source.doris_database or DEFAULT_DORIS_DATABASE).strip()
        if not api_url.startswith(("http://", "https://")):
            raise HTTPException(400, "请填写 Doris HTTP API 地址(例如 http://host:30834/agent/doris/query)")
        # Doris schema names are validated by DorisHttpConn before mutating
        # the global source state, so malformed input returns a clear 400
        # instead of a later metadata-query failure.
        try:
            _doris_http_conn(api_url, database)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        source.doris_jdbc_url = jdbc
        source.doris_api_url = api_url
        source.doris_username = username
        source.doris_password = password
        source.doris_driver = driver
        source.doris_database = database
        source.use_doris = True
        _mark("database")
    elif not paired_repo_id and req.database:
        dp = _cwd_file(req.database, label="数据库文件")
        if not dp.is_file():
            raise HTTPException(400, f"数据库文件不存在: {req.database}")
        if source.use_doris or Path(source.db_path).resolve() != dp.resolve():
            source.db_path = str(dp)
            source.use_doris = False
            _mark("database")

    if not paired_repo_id and source.remote_ontology is not None and source.use_doris:
        # A remote repository is never allowed to drift onto a custom schema.
        # All normal remote switches took the paired branch above; reaching
        # this check with a different schema means a caller tried to bypass it.
        try:
            active_catalog = _remote_repository_catalog(source.remote_ontology)
        except OntologyApiError as exc:
            raise HTTPException(502, f"无法校验原子数据源: {exc}") from exc
        active_repo = next((item for item in active_catalog if item["id"] == source.remote_ontology.repository_id), None)
        if active_repo is None or source.doris_database != active_repo["dorisDatabase"]:
            raise HTTPException(400, "远程本体库必须与其 dorisDatabase 作为一个原子数据源切换")

    # Retrieval mode (semantic | graph). A local graph file is only accepted
    # for local/development sources; remote graph retrieval uses the active
    # remote repository API and has no local graph_path setting.
    if req.retrieval_mode is not None:
        mode = req.retrieval_mode.strip()
        if mode not in RETRIEVAL_MODES:
            raise HTTPException(400, f"未知检索模式: {req.retrieval_mode}")
        if mode != source.retrieval_mode:
            source.retrieval_mode = mode
            changed.append("retrieval_mode")

    if source.remote_ontology is not None or source.ontology_backend in {"production", "remote"}:
        if source.graph_path:
            source.graph_path = ""
            _mark("graph")
    elif req.graph:
        gp = _cwd_file(req.graph, label="图库文件")
        if not gp.is_file():
            raise HTTPException(400, f"图库文件不存在: {req.graph}")
        if str(gp) != source.graph_path:
            source.graph_path = str(gp)
            changed.append("graph")

    if _source_binding_signature(source) == binding_before:
        changed = [name for name in changed if name not in {"ontology", "database"}]

    if changed:
        # register_tool is idempotent — this rebinds the ontology/SQL tools to
        # the new store + db_path (or Doris connection).
        try:
            doris_conn = (
                _doris_http_conn(source.doris_api_url, source.doris_database, source.remote_ontology)
                if source.use_doris
                else None
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        if register_global:
            register_all(
                source.ontology_store,
                source.db_path,
                doris=doris_conn,
                remote_ontology=source.remote_ontology,
            )
        # Reset sessions so the new system prompt / ontology take effect.
        if source is STATE:
            STATE.session = None
            STATE.report_session = None
            STATE.active_report_ids = []

    return JSONResponse({
        "changed": changed,
        "ontology": (
            f"{REMOTE_ONTOLOGY_PREFIX}{source.remote_ontology.repository_id}"
            if source.remote_ontology is not None
            else _cwd_relative_value(source.ontology_path)
        ),
        "database": (
            f"{REMOTE_DORIS_PREFIX}{source.remote_ontology.repository_id}"
            if source.use_doris and source.remote_ontology is not None
            else DORIS_SOURCE_VALUE
            if source.use_doris
            else _cwd_relative_value(source.db_path)
        ),
        "doris_jdbc_url": source.doris_jdbc_url if source.use_doris else "",
        "doris_database": source.doris_database if source.use_doris else "",
        "namespace": source.ontology_namespace if source.remote_ontology else "",
        "retrieval_mode": source.retrieval_mode,
        "graph": (
            _cwd_relative_value(source.graph_path)
            if source.graph_path else ""
        ),
    })


@app.post("/api/graph/build")
def build_graph_endpoint(req: GraphBuildRequest) -> JSONResponse:
    """Build a NetworkX graph library from the given ontology xlsx and write it
    as `<stem>.graphml` in `dataset/graphs` (so it appears in the 图库源 list).
    Nodes = ontology elements; edges = 实体关系 (ER) + 本体元模型关系 (meta)."""
    cwd = Path(STATE.cwd)
    op = _cwd_file(req.ontology, label="本体文件")
    if not op.is_file():
        raise HTTPException(400, f"本体文件不存在: {req.ontology}")
    graph_dir = project_path(cwd, GRAPHS_DIR)
    graph_dir.mkdir(parents=True, exist_ok=True)
    out = graph_dir / (op.stem + ".graphml")
    try:
        from ..ontology.graph import build_from_xlsx
        stats = build_from_xlsx(str(op), str(out))
    except ImportError as e:
        raise HTTPException(500, f"未安装 networkx,无法构建图库: {e}")
    except Exception as e:
        raise HTTPException(400, f"图库构建失败: {e}")
    return JSONResponse({"graph": out.relative_to(cwd).as_posix(), "stats": stats})


@app.get("/api/system-prompt")
def get_system_prompt(mode: str = "data", session_id: str = "") -> JSONResponse:
    if mode == "report":
        session, _, _ = _report_context_state(session_id)
        if session is None:
            return JSONResponse({"system_prompt": "(尚未激活任何报表,选择一份报表后将显示对应的 system prompt。)"})
        return JSONResponse({"system_prompt": session.system_prompt})
    session = _ensure_session(session_id)
    return JSONResponse({"system_prompt": session.system_prompt})


@app.get("/api/ontology/seen")
def get_ontology_seen(mode: str = "data", session_id: str = "") -> JSONResponse:
    key = _session_key(session_id)
    session = _report_context_state(session_id)[0] if mode == "report" else (
        STATE.sessions.get(key) if key else STATE.session
    )
    if session is None:
        return JSONResponse({"entities": []})
    items = list(session.ontology_seen.values())
    items.sort(key=lambda r: (r["kind"], r["code"]))
    return JSONResponse({"entities": items})


@app.get("/api/ontology/all")
def get_ontology_all(session_id: str = "") -> JSONResponse:
    """Full ontology dump (for the "browse" side panel)."""
    source = _source_for_session(session_id)
    if source.remote_ontology is not None:
        result: dict[str, list[dict[str, str]]] = {
            "terms": [], "business_objects": [], "logical_entities": [],
            "attributes": [], "relations": [], "metrics": [], "dimensions": [],
            "activities": [], "processes": [], "rules": [], "meta_relations": [],
        }
        mappings = {
            "Term": ("terms", "term"),
            "BusinessObject": ("business_objects", "business_object"),
            "LogicalEntity": ("logical_entities", "logical_entity"),
            "BusinessAttribute": ("attributes", "attribute"),
            "Indicator": ("metrics", "metric"),
            "Dimension": ("dimensions", "dimension"),
            "Rule": ("rules", "rule"),
        }
        for type_name, (bucket, kind) in mappings.items():
            try:
                rows = source.remote_ontology.list_objects(type_name, 5000)
            except OntologyApiError as exc:
                raise HTTPException(502, f"远程本体浏览失败({type_name}): {exc}") from exc
            result[bucket] = [{
                "code": str(row.get("code") or row.get("identifierCode") or ""),
                "kind": kind,
                "name": str(row.get("label") or row.get("name") or row.get("code") or ""),
            } for row in rows]
        return JSONResponse(result)
    if source.ontology_store is None:
        raise HTTPException(500, "Ontology not loaded")
    s = source.ontology_store
    def _bundle(collection, kind):
        return [
            {"code": e.code, "kind": kind, "name": getattr(e, "name", e.code) or e.code}
            for e in collection.values()
        ]
    return JSONResponse({
        "terms": _bundle(s.terms, "term"),
        "business_objects": _bundle(s.business_objects, "business_object"),
        "logical_entities": _bundle(s.logical_entities, "logical_entity"),
        "attributes": _bundle(s.attributes, "attribute"),
        "relations": _bundle(s.relations, "relation"),
        "metrics": _bundle(s.metrics, "metric"),
        "dimensions": _bundle(s.dimensions, "dimension"),
        "activities": _bundle(s.activities, "activity"),
        "processes": _bundle(s.processes, "process"),
        "rules": _bundle(s.rules, "rule"),
        "meta_relations": _bundle(s.meta_relations, "meta_relation"),
    })


@app.post("/api/session/reset")
def reset_session(session_id: str = "") -> JSONResponse:
    key = _session_key(session_id)
    if key:
        STATE.sessions.pop(key, None)
    else:
        STATE.session = None
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# 角色选择(用户画像 + Agent 回答风格)
# ---------------------------------------------------------------------------
class RolesRequest(BaseModel):
    user_role: str = ""    # key in USER_ROLES, or "" to clear
    agent_pref: str = ""   # key in AGENT_PREFS, or "" to clear
    session_id: Optional[str] = None


@app.get("/api/roles")
def get_roles(session_id: str = "") -> JSONResponse:
    user_role, agent_pref = _role_values(session_id)
    return JSONResponse({
        "user_role": user_role,
        "agent_pref": agent_pref,
        "user_role_options": [{"key": k, "label": v[0], "desc": v[1]} for k, v in USER_ROLES.items()],
        "agent_pref_options": [{"key": k, "label": v[0], "desc": v[1]} for k, v in AGENT_PREFS.items()],
    }, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


@app.put("/api/roles")
def put_roles(req: RolesRequest) -> JSONResponse:
    # Validate against the known taxonomy; unknown keys clear the slot.
    user_role = req.user_role if req.user_role in USER_ROLES else ""
    agent_pref = req.agent_pref if req.agent_pref in AGENT_PREFS else ""
    key = _session_key(req.session_id)
    if key:
        STATE.roles_by_session[key] = (user_role, agent_pref)
    else:
        STATE.user_role = user_role
        STATE.agent_pref = agent_pref
    block = _role_block(req.session_id)
    # Apply to live sessions so the change takes effect on the next turn —
    # no conversation reset needed.
    data_session = STATE.sessions.get(key) if key else STATE.session
    report_session = STATE.report_sessions.get(key) if key else STATE.report_session
    if data_session is not None:
        data_session.set_role_block(block)
    if report_session is not None:
        report_session.set_role_block(block)
    return JSONResponse({"ok": True, "user_role": user_role, "agent_pref": agent_pref})


# ---------------------------------------------------------------------------
# Conversation history (restorable 「最近」list)
# ---------------------------------------------------------------------------
class ConversationSaveRequest(BaseModel):
    mode: str = "data"                  # "data" | "report"
    title: Optional[str] = None
    chat_html: str = ""
    dashboard_html: str = ""
    ontology_html: str = ""
    tools_html: str = ""
    llm_html: str = ""
    sop_steps: list[dict[str, Any]] = Field(default_factory=list)
    # The active ontology/database context for this snapshot. Passwords are
    # deliberately excluded by the client and are never persisted.
    source_config: Optional[dict[str, Any]] = None
    cid: Optional[str] = None           # update in place when the browser has one
    first_user_question: str = ""       # visible first question captured by the browser
    session_id: Optional[str] = None


class ConversationRestoreRequest(BaseModel):
    id: str
    session_id: Optional[str] = None


def _require_conversation_store() -> ConversationStore:
    if STATE.conversation_store is None:
        raise HTTPException(500, "Server not configured; call configure() first.")
    return STATE.conversation_store


def _session_for_mode(mode: str, session_id: Optional[str] = None) -> Optional[WebSession]:
    if mode == "report":
        key = _session_key(session_id)
        return STATE.report_sessions.get(key) if key else STATE.report_session
    key = _session_key(session_id)
    return STATE.sessions.get(key) if key else STATE.session


def _conversation_sync(method: str, path: str, payload: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """Best-effort backend-to-backend history sync; never blocks local use."""
    base = STATE.conversation_sync_url
    if not base:
        return None
    try:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        req = Request(base + path, data=data, headers=headers, method=method.upper())
        # Sync is best-effort and must never hold the local UI for the old
        # five-second network timeout. The local store is authoritative for
        # interactive reads; writes/deletes can tolerate a short mirror wait.
        with urlopen(req, timeout=0.8) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return None


def _history_ontology_entities(session: WebSession, messages: list[Any]) -> list[dict[str, Any]]:
    """Rebuild ontology hits from persisted tool results.

    Older conversation snapshots may have stale/missing ``ontology_html``.
    The tool result text is the durable source of truth, and it already
    contains the structured ``[CODE] label (Type)`` lines emitted by the
    remote ontology tools.  Reusing WebSession's source-aware parser keeps
    this migration identical to live analysis and avoids any LLM/API call.
    """
    tool_names: dict[str, str] = {}
    session.ontology_seen.clear()
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        blocks = message.get("content")
        if not isinstance(blocks, list):
            continue
        role = message.get("role")
        if role == "assistant":
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_id = str(block.get("id") or "")
                    name = str(block.get("name") or "")
                    if tool_id and name:
                        tool_names[tool_id] = name
            continue
        if role != "user":
            continue
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            content = block.get("content")
            if isinstance(content, list):
                content = "".join(
                    str(item.get("text") or "") for item in content
                    if isinstance(item, dict)
                )
            tool_name = tool_names.get(str(block.get("tool_use_id") or ""))
            session._extract_entities(str(content or ""), tool_name)
    return list(session.ontology_seen.values())


def _infer_history_source_config(messages: list[Any]) -> dict[str, str]:
    """Infer a Doris/repository source for snapshots created before source
    context was persisted.

    SQL tool results retain the schema used by the historical turn. This is a
    safe migration hint for old records; records without an identifiable
    ``ontology_*`` schema keep the currently selected source.
    """
    try:
        text = json.dumps(messages or [], ensure_ascii=False)
    except (TypeError, ValueError):
        return {}
    schemas = re.findall(
        r"\b(?:from|join|update|into)\s+([A-Za-z_][\w]*)\.",
        text,
        flags=re.IGNORECASE,
    )
    schemas = [schema for schema in schemas if schema.lower().startswith("ontology_")]
    if not schemas:
        return {}
    database = schemas[-1]
    lower = database.lower()
    repository_by_schema = (
        ("ontology_guangfeng", "__metaerp_repository__:4"),
        ("ontology_test", "__metaerp_repository__:2"),
        ("ontology_dev", "__metaerp_repository__:1"),
        ("ontology_demometaerp", "__metaerp_repository__:3"),
        ("ontology_demo", "__metaerp_repository__:3"),
    )
    source = {
        "database": DORIS_SOURCE_VALUE,
        "doris_database": database,
    }
    for prefix, repository in repository_by_schema:
        if lower.startswith(prefix):
            source["ontology"] = repository
            break
    return source


def _render_history_ontology_cards(entities: list[dict[str, Any]]) -> str:
    """Render migrated entity records using the same card contract as JS."""
    kind_labels = {
        "term": "术语", "business_object": "业务对象", "logical_entity": "逻辑实体",
        "attribute": "属性", "relation": "关系", "metric": "指标", "activity": "活动",
        "rule": "规则", "dimension": "维度", "process": "流程",
        "meta_relation": "元模型关系", "table_node": "表节点", "column": "列",
    }
    cards: list[str] = []
    for entity in entities:
        kind = str(entity.get("kind") or "ontology")
        code = str(entity.get("code") or "")
        key = str(entity.get("entity_key") or "")
        source = str(entity.get("source") or "")
        name = str(entity.get("name") or code)
        display = str(entity.get("display") or "")
        kind_label = kind_labels.get(kind, kind.upper())
        cards.append(
            f'<div class="entity-card {escape(kind)}" data-code="{escape(code)}" '
            f'data-entity-key="{escape(key)}" data-source="{escape(source)}">'
            f'<div class="entity-head"><span class="entity-kind-tag">{escape(kind_label)}</span>'
            f'<span class="entity-code">{escape(code)}</span>'
            f'<span class="entity-name">{escape(name)}</span>'
            '<span class="entity-chevron">›</span></div>'
            f'<div class="entity-body">{escape(display)}</div></div>'
        )
    return "".join(cards)


def _load_conversation_record(store: ConversationStore, cid: str) -> Optional[dict[str, Any]]:
    """Load only from the local authoritative conversation store."""
    return store.get(cid)


def _current_source_config(source: Any = None) -> dict[str, str]:
    """Return the non-secret source identity currently bound to the process."""
    source = source or STATE
    ontology = (
        f"__metaerp_repository__:{source.remote_ontology.repository_id}"
        if source.remote_ontology is not None
        else _cwd_relative_value(source.ontology_path)
    )
    database = DORIS_SOURCE_VALUE if source.use_doris else _cwd_relative_value(source.db_path)
    if source.use_doris and source.remote_ontology is not None:
        database = f"{REMOTE_DORIS_PREFIX}{source.remote_ontology.repository_id}"
    return sanitize_source_config({
        "ontology": ontology,
        "database": database,
        "retrieval_mode": source.retrieval_mode,
        "graph": _cwd_relative_value(source.graph_path),
        "doris_api_url": source.doris_api_url,
        "doris_jdbc_url": source.doris_jdbc_url,
        "doris_driver": source.doris_driver,
        "doris_username": source.doris_username,
        "doris_database": source.doris_database,
    })


def _history_source_matches_current(source_config: dict[str, str], source: Any = None) -> bool:
    if not source_config:
        return False
    current = _current_source_config(source)
    return all(str(current.get(key, "")) == str(value) for key, value in source_config.items())


def _resolved_history_source(rec: dict[str, Any]) -> dict[str, str]:
    source_config = sanitize_source_config(rec.get("source_config"))
    if source_config:
        return source_config
    return _infer_history_source_config(rec.get("messages") or [])


def _conversation_preview_payload(rec: dict[str, Any], requested_id: str) -> dict[str, Any]:
    metadata = ConversationStore._metadata(rec)
    preview = metadata.get("preview") if isinstance(metadata.get("preview"), list) else []
    # A few very old snapshots contain only rendered HTML. Keep that format as
    # a last-resort preview rather than making the legacy transcript invisible.
    legacy_preview_html = ""
    if not preview and rec.get("chat_html"):
        legacy_preview_html = str(rec.get("chat_html") or "")[:1_000_000]
    source_config = _resolved_history_source(rec)
    return {
        "id": rec.get("id") or requested_id,
        "title": metadata.get("title") or "未命名对话",
        "first_user_question": metadata.get("first_user_question") or "",
        "mode": metadata.get("mode") or "data",
        "preview": preview,
        "chat_html_preview": legacy_preview_html,
        "turn_count": metadata.get("turn_count", 0),
        "source_config_needs_restore": bool(source_config),
        "has_ontology_html": bool(rec.get("ontology_html")),
    }


def _activate_conversation_record(
    store: ConversationStore,
    rec: dict[str, Any],
    requested_id: str,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    """Restore only server-side context; HTML is deliberately not touched here."""
    mode = rec.get("mode") if rec.get("mode") in ("data", "report") else "data"
    messages = rec.get("messages") if isinstance(rec.get("messages"), list) else []
    source_restore_error = ""
    source_config = _resolved_history_source(rec)

    # Source switching is expensive (ontology load + tool registration). It is
    # skipped when the historical source is already the active source.
    source = _source_for_session(session_id)
    if source_config and not _history_source_matches_current(source_config, source):
        allowed_source_fields = {
            "ontology", "database", "retrieval_mode", "graph",
            "doris_api_url", "doris_jdbc_url", "doris_driver",
            "doris_username", "doris_database",
        }
        try:
            put_sources_endpoint(SourcesUpdate(session_id=session_id, **{
                key: value
                for key, value in source_config.items()
                if key in allowed_source_fields and value not in (None, "")
            }))
        except HTTPException as exc:
            source_restore_error = str(exc.detail or exc)
        except Exception as exc:  # malformed/removed old sources are non-fatal
            source_restore_error = str(exc)

    context_restored = False
    if mode == "report":
        session = _session_for_mode("report", session_id)
        if session is not None:
            session.messages = list(messages)
            session.first_user_question = str(rec.get("first_user_question") or "")
            session.pending_tool_use_id = None
            session.pending_choice_spec = None
            session._pending_sibling_results = []
            context_restored = True
    else:
        if _session_key(session_id) or STATE.session is None:
            session = _ensure_session(session_id)
        else:
            session = STATE.session
        if session is not None:
            session.messages = list(messages)
            session.first_user_question = str(rec.get("first_user_question") or "")
            session.pending_tool_use_id = None
            session.pending_choice_spec = None
            session._pending_sibling_results = []
            context_restored = True

    # New snapshots already contain rendered ontology HTML. Only old records
    # need the compatibility scan/migration, which can be noticeably costly.
    active_session = _session_for_mode(mode, session_id)
    if active_session is not None and not str(rec.get("ontology_html") or "").strip():
        migrated_entities = _history_ontology_entities(active_session, messages)
        if migrated_entities:
            migrated_html = _render_history_ontology_cards(migrated_entities)
            if migrated_html != (rec.get("ontology_html") or ""):
                rec["ontology_html"] = migrated_html
                store.update_ontology_html(str(rec.get("id") or requested_id), migrated_html)

    return {
        "id": rec.get("id") or requested_id,
        "mode": mode,
        "title": ConversationStore._metadata(rec).get("title") or "未命名对话",
        "first_user_question": ConversationStore._metadata(rec).get("first_user_question") or "",
        "source_config": source_config,
        "source_restore_error": source_restore_error,
        "context_restored": context_restored,
    }


@app.get("/api/conversations")
def list_conversations(mode: Optional[str] = None) -> JSONResponse:
    store = _require_conversation_store()
    # Do not wait for CONVERSATION_SYNC_URL here. The local metadata index is
    # intentionally the fast path; remote mirroring is handled on writes and
    # a remote outage must not hide locally available history.
    return JSONResponse({"conversations": store.list(mode)})


@app.post("/api/conversations/save")
def save_conversation(req: ConversationSaveRequest) -> JSONResponse:
    """Snapshot the active session of `mode` (its messages) + the supplied
    client-rendered chat/dashboard HTML, so it can be relisted and restored."""
    store = _require_conversation_store()
    mode = req.mode if req.mode in ("data", "report") else "data"
    session = _session_for_mode(mode, req.session_id)
    safe_source_config = sanitize_source_config(req.source_config)
    messages = list(session.messages) if session else []
    summary = store.save(
        mode=mode,
        title=req.title or "未命名对话",
        messages=messages,
        chat_html=req.chat_html,
        dashboard_html=req.dashboard_html,
        ontology_html=req.ontology_html,
        tools_html=req.tools_html,
        llm_html=req.llm_html,
        sop_steps=req.sop_steps,
        # An empty client snapshot means metadata was unavailable; on an
        # update it must not erase the source already captured for the record.
        source_config=safe_source_config or None,
        cid=req.cid,
        first_user_question_override=(
            req.first_user_question.strip()
            or (session.first_user_question if session else "")
        ),
    )
    # Local storage is authoritative. A configured sync URL is intentionally
    # not consulted here: an old mirror must never overwrite the canonical
    # title, id, timestamp, or mode returned to the browser.
    return JSONResponse(summary)


@app.post("/api/conversations/restore")
def restore_conversation(req: ConversationRestoreRequest) -> JSONResponse:
    """Legacy all-at-once restore endpoint kept for older clients."""
    store = _require_conversation_store()
    rec = _load_conversation_record(store, req.id)
    if not rec:
        raise HTTPException(404, f"conversation not found: {req.id}")
    activated = _activate_conversation_record(store, rec, req.id, req.session_id)
    return JSONResponse({
        **activated,
        "chat_html": rec.get("chat_html") or "",
        "dashboard_html": rec.get("dashboard_html") or "",
        "ontology_html": rec.get("ontology_html") or "",
        "tools_html": rec.get("tools_html") or "",
        "llm_html": rec.get("llm_html") or "",
        "sop_steps": rec.get("sop_steps") or [],
    })


@app.get("/api/conversations/{cid}/preview")
def preview_conversation(cid: str) -> JSONResponse:
    """Return only metadata and a bounded text transcript for fast rendering."""
    store = _require_conversation_store()
    rec = _load_conversation_record(store, cid)
    if not rec:
        raise HTTPException(404, f"conversation not found: {cid}")
    return JSONResponse(_conversation_preview_payload(rec, cid))


@app.get("/api/conversations/{cid}/assets")
def conversation_assets(cid: str) -> JSONResponse:
    """Return renderable assets without restoring process-global context."""
    store = _require_conversation_store()
    rec = _load_conversation_record(store, cid)
    if not rec:
        raise HTTPException(404, f"conversation not found: {cid}")
    return JSONResponse({
        "id": rec.get("id") or cid,
        "mode": rec.get("mode") or "data",
        # chat_html is included for visual fidelity with existing snapshots;
        # it is loaded after the lightweight preview and never sent by list().
        "chat_html": rec.get("chat_html") or "",
        "dashboard_html": rec.get("dashboard_html") or "",
        "ontology_html": rec.get("ontology_html") or "",
        "tools_html": rec.get("tools_html") or "",
        "llm_html": rec.get("llm_html") or "",
        "sop_steps": rec.get("sop_steps") or [],
    })


@app.post("/api/conversations/{cid}/activate")
def activate_conversation(cid: str, session_id: str = "") -> JSONResponse:
    """Restore messages/source/session after the preview is visible."""
    store = _require_conversation_store()
    rec = _load_conversation_record(store, cid)
    if not rec:
        raise HTTPException(404, f"conversation not found: {cid}")
    return JSONResponse(_activate_conversation_record(store, rec, cid, session_id))


@app.get("/api/conversations/{cid}/record")
def get_conversation_record(cid: str) -> JSONResponse:
    """Internal read endpoint used by a development client syncing history."""
    store = _require_conversation_store()
    rec = store.get(cid)
    if not rec:
        raise HTTPException(404, f"conversation not found: {cid}")
    return JSONResponse({"conversation": rec})


@app.delete("/api/conversations/{cid}")
def delete_conversation(cid: str) -> JSONResponse:
    store = _require_conversation_store()
    local_ok = store.delete(cid)
    return JSONResponse({"ok": bool(local_ok)})


@app.post("/api/chat")
def chat(req: ChatRequest):
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(400, "empty message")
    session = _ensure_session(req.session_id)

    def event_stream():
        try:
            for evt in session.generate_turn(message, req.visible_user_text):
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
    key = _session_key(req.session_id)
    session = STATE.sessions.get(key) if key else STATE.session
    if not session:
        raise HTTPException(400, "No active session")
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
# Task alert (行动 → 转督办) proxy to the external task-order service
# ---------------------------------------------------------------------------

TASK_ALERT_LEVELS = {"ALERT", "WARNING"}


def _task_alert_enabled() -> bool:
    """Feature flag; the task-alert integration stays ON by default even when
    the current network cannot reach the upstream service."""
    value = os.environ.get("TASK_ALERT_API_ENABLED")
    if value is None or not value.strip():
        return True
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _task_alert_timeout() -> float:
    try:
        return max(0.5, min(float(os.environ.get("TASK_ALERT_TIMEOUT_SECONDS", "10")), 120.0))
    except ValueError:
        return 10.0


def _parse_task_alert_response(body: str) -> tuple[bool, Optional[str], Optional[str]]:
    """Parse the upstream task-alert response.

    The upstream returns HTTP 200 even for business failures, so success must
    be judged from the JSON body (``success``/``code``). Returns
    ``(success, task_id, error_message)``.
    """
    try:
        data = json.loads(body)
    except (ValueError, json.JSONDecodeError):
        return False, None, "上游返回非 JSON 响应"
    if not isinstance(data, dict):
        return False, None, "上游返回格式异常"
    success_flag = data.get("success", True)
    code = data.get("code")
    if success_flag is False or (code is not None and code not in (200, 0)):
        message = data.get("message") or f"上游业务错误 code={code}"
        return False, None, str(message)
    task_id: Optional[str] = None
    raw = data.get("data")
    if isinstance(raw, str) and raw.strip():
        task_id = raw.strip()
    elif isinstance(raw, dict):
        for inner in ("taskId", "task_id", "id", "orderId", "order_id"):
            value = raw.get(inner)
            if isinstance(value, (str, int)):
                task_id = str(value)
                break
    if task_id is None:
        for key in ("taskId", "task_id", "id", "orderId", "order_id"):
            value = data.get(key)
            if isinstance(value, (str, int)):
                task_id = str(value)
                break
    return True, task_id, None

class TaskAlertCreateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    assignee: Optional[str] = None
    level: Optional[str] = None
    bpDefinitionId: Optional[str] = None
    clientRequestId: Optional[str] = None


# In-process idempotency keyed by clientRequestId: successes are cached so a
# repeat submission never re-creates a task order; failures are never cached
# so the user can retry. The lock also guards concurrent duplicate requests.
_task_alert_successes: dict[str, dict[str, Any]] = {}
_task_alert_inflight: set[str] = set()
_task_alert_lock = threading.Lock()


@app.post("/api/task-alert/manual-create")
def task_alert_manual_create(req: TaskAlertCreateRequest):
    if not _task_alert_enabled():
        raise HTTPException(403, "任务令接口未启用")
    title = (req.title or "").strip()
    content = (req.content or "").strip()
    if not title:
        raise HTTPException(422, "title 不能为空")
    if not content:
        raise HTTPException(422, "content 不能为空")
    level = (req.level or os.environ.get("TASK_ALERT_DEFAULT_LEVEL") or "WARNING").strip().upper()
    if level not in TASK_ALERT_LEVELS:
        raise HTTPException(422, "level 只允许 ALERT 或 WARNING")
    assignee = (req.assignee or os.environ.get("TASK_ALERT_DEFAULT_ASSIGNEE") or "").strip()
    bp_definition_raw = (req.bpDefinitionId or os.environ.get("TASK_ALERT_DEFAULT_BP_DEFINITION_ID") or "").strip()
    bp_definition_id: Optional[int] = None
    if bp_definition_raw:
        if not bp_definition_raw.isdigit():
            raise HTTPException(422, "bpDefinitionId 必须是数字")
        bp_definition_id = int(bp_definition_raw)
    if not assignee:
        raise HTTPException(422, "assignee 不能为空")
    client_request_id = (req.clientRequestId or "").strip()
    api_url = (os.environ.get("TASK_ALERT_API_URL") or "").strip()
    if not api_url:
        raise HTTPException(500, "未配置任务令服务地址(TASK_ALERT_API_URL)")

    with _task_alert_lock:
        if client_request_id and client_request_id in _task_alert_successes:
            return _task_alert_successes[client_request_id]
        if client_request_id and client_request_id in _task_alert_inflight:
            raise HTTPException(409, "任务令创建中,请勿重复提交")
        if client_request_id:
            _task_alert_inflight.add(client_request_id)

    payload = {
        "title": title,
        "content": content,
        "assignee": assignee,
        "level": level,
    }
    if bp_definition_id is not None:
        payload["bpDefinitionId"] = bp_definition_id

    def _finish_failure() -> None:
        if client_request_id:
            with _task_alert_lock:
                _task_alert_inflight.discard(client_request_id)

    try:
        upstream = UpstreamRequest(
            api_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urlopen(upstream, timeout=_task_alert_timeout()) as response:
            raw = response.read().decode("utf-8", errors="replace")
        success, task_id, error_message = _parse_task_alert_response(raw)
        if not success:
            _finish_failure()
            logger.warning("task alert upstream business failure")
            raise HTTPException(502, f"任务令服务创建失败:{error_message}")
        result = {"ok": True, "taskId": task_id, "clientRequestId": client_request_id or None}
        logger.info(
            "task alert created clientRequestId=%s taskId=%s upstream_status=200",
            client_request_id or "-", task_id,
        )
        if client_request_id:
            with _task_alert_lock:
                _task_alert_successes[client_request_id] = result
                _task_alert_inflight.discard(client_request_id)
        return result
    except HTTPError as exc:
        _finish_failure()
        logger.warning("task alert upstream http error code=%s", exc.code)
        raise HTTPException(502, f"任务令服务返回 HTTP {exc.code}")
    except TimeoutError:
        _finish_failure()
        logger.warning("task alert upstream timeout")
        raise HTTPException(504, "任务令服务超时")
    except URLError as exc:
        _finish_failure()
        reason = getattr(exc, "reason", None)
        logger.warning("task alert upstream connection failure")
        raise HTTPException(502, f"任务令服务连接失败:{reason or '网络不可达'}")
    except OSError as exc:
        _finish_failure()
        logger.warning("task alert upstream os error")
        raise HTTPException(502, f"任务令服务连接失败:{exc}")


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
    session_id: Optional[str] = None

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
    session_id: Optional[str] = None


def _report_context_state(session_id: Optional[str]) -> tuple[Optional[WebSession], list[str], bool]:
    key = _session_key(session_id)
    if not key:
        return STATE.report_session, STATE.active_report_ids, STATE.report_with_db
    return (
        STATE.report_sessions.get(key),
        list(STATE.report_ids_by_session.get(key, [])),
        STATE.report_db_by_session.get(key, True),
    )


def _set_report_context(
    session_id: Optional[str], session: Optional[WebSession], ids: list[str], with_db: bool,
) -> None:
    key = _session_key(session_id)
    if not key:
        STATE.report_session = session
        STATE.active_report_ids = list(ids)
        STATE.report_with_db = with_db
        return
    if session is None:
        STATE.report_sessions.pop(key, None)
    else:
        STATE.report_sessions[key] = session
    STATE.report_ids_by_session[key] = list(ids)
    STATE.report_db_by_session[key] = with_db


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
    # The uploaded report store is shared, while report conversations are
    # session-scoped. Remove the deleted report from every browser context so
    # no user keeps a prompt referencing a file that no longer exists.
    for key, active_ids in list(STATE.report_ids_by_session.items()):
        if rid not in active_ids:
            continue
        remaining = [item for item in active_ids if item != rid]
        with_db = STATE.report_db_by_session.get(key, True)
        session = (
            _build_report_session(remaining, with_db, _source_for_session(key), key)
            if remaining else None
        )
        _set_report_context(key, session, remaining, with_db)
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
def report_status(session_id: str = "") -> JSONResponse:
    session, active_ids, with_db = _report_context_state(session_id)
    actives: list[dict] = []
    if STATE.report_store:
        for rid in active_ids:
            rec = STATE.report_store.get(rid)
            if rec:
                actives.append(_record_to_summary(rec))
    # Backward-compat: keep `active_report` as the first one so older
    # clients don't break; new clients should read `active_reports`.
    legacy_active = actives[0] if actives else None
    return JSONResponse({
        "active_reports": actives,
        "active_report": legacy_active,
        "with_db": with_db,
        "has_session": session is not None,
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

    source = _source_for_session(req.session_id)
    session = _build_report_session(ids, req.with_db, source, req.session_id)
    _set_report_context(req.session_id, session, ids, req.with_db)

    return JSONResponse({
        "ok": True,
        "active_reports": actives,
        # Backward-compat — first report as the legacy "single active".
        "active_report": actives[0] if actives else None,
        "with_db": req.with_db,
    })


@app.put("/api/report/config")
def report_config(req: ReportConfigUpdate) -> JSONResponse:
    """Flip the 启用数据库查询 switch without discarding the chat history.

    Rebuilds BOTH the tool whitelist AND the availability-marker header so
    the agent doesn't see a mismatch (stale header said 'disabled' while
    the new tool list includes SQLRun — which was the original bug).
    """
    session, active_ids, _ = _report_context_state(req.session_id)
    if session is None:
        raise HTTPException(400, "No active report session")
    with_db = bool(req.with_db)
    new_tools = REPORT_DB_TOOLS if with_db else REPORT_PURE_TOOLS
    session.set_tools_override(new_tools)
    if active_ids and STATE.report_store is not None:
        recs = [STATE.report_store.get(rid) for rid in active_ids]
        recs = [r for r in recs if r]
        if recs:
            session.set_context_header(
                _report_context_header(recs, with_db)
            )
    _set_report_context(req.session_id, session, active_ids, with_db)
    return JSONResponse({"ok": True, "with_db": with_db})


@app.post("/api/report/session/reset")
def report_session_reset(session_id: str = "", clear_reports: bool = False) -> JSONResponse:
    """Clear report chat history, optionally detaching the active reports."""
    _, active_ids, with_db = _report_context_state(session_id)
    if clear_reports:
        _set_report_context(session_id, None, [], with_db)
        return JSONResponse({"ok": True, "active_reports": []})
    session = None
    if active_ids:
        session = _build_report_session(
            active_ids, with_db, _source_for_session(session_id), session_id,
        )
    _set_report_context(session_id, session, active_ids, with_db)
    return JSONResponse({"ok": True})


@app.post("/api/report/generate")
def report_generate(session_id: str = "") -> JSONResponse:
    """Start a report-GENERATION session — runs IN report mode on the
    report-generator agent (ontology + DB tools), not bound to any
    uploaded report. The wizard sends the report config as the first
    chat message; the agent searches data and assembles the report.
    """
    source = _source_for_session(session_id)
    if source.ontology_store is None:
        raise HTTPException(500, "Server not configured; call configure() first.")
    reg = get_agent_def_registry()
    gen_agent = reg.get(REPORTGEN_AGENT_NAME)
    if gen_agent is None:
        raise HTTPException(
            500,
            f"Agent '{REPORTGEN_AGENT_NAME}' not found — 请在添加 "
            f".claude/agents/{REPORTGEN_AGENT_NAME}.md 后重启服务。",
        )
    doris = _doris_http_conn(source.doris_api_url, source.doris_database, source.remote_ontology) if source.use_doris else None
    executors = build_source_executors(source.ontology_store, source.db_path, doris=doris, remote_ontology=source.remote_ontology)
    session = WebSession(
        cwd=STATE.cwd,
        agent_def=gen_agent,
        ontology_store=source.ontology_store,
        tools_override=REPORT_DB_TOOLS,
        context_header="# 任务类型: 标准报表生成\n# 数据库工具可用性: enabled",
        role_block=_role_block(session_id),
        ontology_backend=("remote" if source.ontology_backend in {"remote", "production"} else "local"),
        ontology_repository_id=(source.remote_ontology.repository_id if source.remote_ontology else ""),
        tool_executors=executors,
    )
    _set_report_context(session_id, session, [], True)
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
    session = _session_for_mode("report", req.session_id)
    if session is None:
        raise HTTPException(400, "No active report session — activate a report first")
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(400, "empty message")

    def event_stream():
        try:
            for evt in session.generate_turn(message, req.visible_user_text):
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
    session = _session_for_mode("report", req.session_id)
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

def _ensure_session(session_id: Optional[str] = None) -> WebSession:
    key = _session_key(session_id)
    existing = STATE.sessions.get(key) if key else STATE.session
    if existing is not None:
        return existing
    source = _source_for_session(key)
    if not STATE.agent_def or source.ontology_store is None:
        raise HTTPException(500, "Server not configured; call configure() first.")
    try:
        doris = (
            _doris_http_conn(source.doris_api_url, source.doris_database, source.remote_ontology)
            if source.use_doris else None
        )
    except ValueError as exc:
        raise HTTPException(500, f"数据源配置无效: {exc}") from exc
    executors = build_source_executors(
        source.ontology_store,
        source.db_path,
        doris=doris,
        remote_ontology=source.remote_ontology,
    )
    tools_override = None
    headers: list[str] = []
    if source.remote_ontology is not None:
        headers.append(
            "# 当前原子数据源\n"
            f"- repository_id: {source.remote_ontology.repository_id}\n"
            f"- namespace: {source.ontology_namespace or source.remote_ontology.namespace}\n"
            f"- doris_database: {source.doris_database}"
        )
    if source.retrieval_mode == "graph":
        base = list(STATE.agent_def.tools or [])
        tools_override = base + [t for t in GRAPH_TOOL_NAMES if t not in base]
        headers.append(GRAPH_MODE_SOP)
    session = WebSession(
        cwd=STATE.cwd,
        agent_def=STATE.agent_def,
        ontology_store=source.ontology_store,
        tools_override=tools_override,
        context_header="\n\n".join(headers) or None,
        role_block=_role_block(key),
        ontology_backend=("remote" if source.ontology_backend in {"remote", "production"} else "local"),
        ontology_repository_id=(source.remote_ontology.repository_id if source.remote_ontology else ""),
        tool_executors=executors,
    )
    if key:
        STATE.sessions[key] = session
    else:
        STATE.session = session
    return session


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


def _build_report_session(
    report_ids: list[str],
    with_db: bool,
    source: Any = None,
    session_id: Optional[str] = None,
) -> WebSession:
    """Create a fresh WebSession bound to the given report list + DB flag."""
    source = source or STATE
    if source.ontology_store is None or not STATE.report_store:
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
    doris = (
        _doris_http_conn(source.doris_api_url, source.doris_database, source.remote_ontology)
        if source.use_doris else None
    )
    executors = build_source_executors(
        source.ontology_store,
        source.db_path,
        doris=doris,
        remote_ontology=source.remote_ontology,
    )
    return WebSession(
        cwd=STATE.cwd,
        agent_def=report_agent,
        ontology_store=source.ontology_store,
        tools_override=tools,
        report_context_block=report_block,
        context_header=header,
        role_block=_role_block(session_id),
        ontology_backend=("remote" if source.ontology_backend in {"remote", "production"} else "local"),
        ontology_repository_id=(source.remote_ontology.repository_id if source.remote_ontology else ""),
        tool_executors=executors,
    )
