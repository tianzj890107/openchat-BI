"""
WebSession — a conversation wrapper that emits structured events for SSE.

This is a thin reimplementation of open_claude.repl.Conversation's turn loop
that yields events instead of printing via rich.Console. Each event is a
JSON-serializable dict suitable for `data: <json>\\n\\n` SSE framing.

Event types:
    user_message        {text}
    iteration_start     {iteration}
    llm_request         {iteration, model, message_count, last_message}
    text_delta          {text}
    tool_start          {id, name}
    tool_input          {id, name, input}
    tool_result         {id, name, input, output, duration_ms, ontology_entities}
    llm_response        {iteration, text, tool_uses, stop_reason, usage}
    done                {stop_reason, iterations}
    error               {message}
"""

from __future__ import annotations

import copy
import logging
import re
import time
from dataclasses import replace
from typing import Any, Callable, Generator, Optional

from open_claude.agent_def import AgentDef
from open_claude.prompt import build_system_prompt
from bi_agent.tools.analysis_policy import (
    extract_action_items,
    has_effective_action,
    has_root_cause_section,
    split_action_item,
)
from open_claude.skills.bundled import init_bundled_skills
from open_claude.skills.registry import load_skills
from open_claude.tokens import CostTracker
from open_claude.tools import execute_tool

from ..concurrency import (
    ResourceCancelled,
    SessionSlot,
    TurnLease,
    set_current_cancel,
)


class TurnContext:
    """Per-turn ownership snapshot captured by the SSE layer.

    Holds the slot, the turn's single-use lease and the turn's cancel event.
    The turn loop captures this object ONCE at turn start; a later turn may
    overwrite ``session._turn_ctx`` but the running turn keeps its own
    reference.  A superseded turn therefore always observes its OWN cancel
    event set and its OWN lease invalidated — it can never mistake a newer
    turn's state for its own (which matters when a restore reuses the same
    WebSession object in place).
    """

    __slots__ = ("slot", "lease", "cancel")

    def __init__(self, slot: SessionSlot, lease: TurnLease, cancel: "threading.Event") -> None:
        self.slot = slot
        self.lease = lease
        self.cancel = cancel

from ..llm.provider import get_model_id, stream_message
from ..llm.registry import get_model
from ..llm.runtime_config import get_config as get_llm_config
from ..ontology.store import OntologyStore
from ..tools.ask_user import ASK_USER_TOOL_NAME
from ..tools.chart_multidim_tools import extract_multidim_chart_spec
from ..tools.chart_policy import chart_skip_reason, skipped_chart_output
from ..tools.chart_tools import extract_chart_spec
from ..tools.table_tools import extract_table_spec
from ..tools.todo_tools import extract_todo_spec
from ..display_names import (
    is_valid_name,
    looks_like_code,
    normalize_display_params,
)


logger = logging.getLogger(__name__)


def _is_thinking_param_error(message: str) -> bool:
    """True when the gateway rejected the request because the model does
    not support the DeepSeek-only ``thinking`` parameter (LiteLLM's
    UnsupportedParamsError)."""
    lower = str(message or "").lower()
    return "unsupportedparams" in lower and "thinking" in lower


VISIBLE_THINKING_CN_RULE = (
    "当前已启用可见思考。面向用户展示的思考摘要必须使用简体中文，保持简短、概括和可读；"
    "不得展示逐 token 推理、隐藏指令、内部系统提示词或完整思维链。"
    "工具参数、SQL、代码、字段名和专有名词保持原样。"
)
from ..reliability import (
    AnalysisContext, Association, Claim, ClaimLevel,
    LimitationType, Provenance, QueryResult, RelationType, ValidationStatus,
    association_claim,
    claims_from_query_result, detect_conflicts, enrich_query_result,
    reconcile_query_results, relation_evidence_status, render_claim, render_narrative,
    soften_evidence_language, validate_claims,
)

# Only real data queries may become later data sources, reconciliation
# candidates or claim inputs.  Display/metadata/utility tools are consumed by
# the UI or the LLM but must never feed back into the analysis state.
DATA_QUERY_TOOLS = frozenset({"Ontology-FactQuery", "Ontology-MetricQuery"})
# Relation/context tools contribute an Association claim only when their
# output carries explicit edge/path evidence.
RELATION_TOOLS = frozenset({"Ontology-RelationQuery", "Ontology-GraphContext", "Ontology-GraphExpand"})


# Ontology codes carried in ontology-tool output, surfaced to the 本体 inspector
# panel.  Repositories do not share a single global code namespace (for
# example BO0005 can mean different things in different repositories), so the
# source/type/code tuple is the identity used by the caller below.
ENTITY_CODE_RE = re.compile(
    r"\b[A-Z][A-Z0-9_]{0,31}\d{3,8}\b"
)
REMOTE_ENTITY_LINE_RE = re.compile(
    r"^\s*\[(?P<code>[A-Z][A-Z0-9_]{0,31}\d{3,8})\]"
    r"\s*(?P<label>[^\n(]+?)\s*(?:\((?P<type>[^)]+)\))?\s*$",
    re.MULTILINE,
)

# --- Render-tool enforcement ----------------------------------------------
# Tools whose output produces a dashboard card. If a turn contains
# SQL/data fetch but no render tool — or the assistant typed a Markdown
# table into the chat — we re-prompt the model to call TableGenerate.
RENDER_TOOLS = {"TableGenerate", "ChartGenerate", "ChartGenerateMultiDim"}
DATA_FETCH_TOOLS = {"Ontology-FactQuery", "Ontology-MetricQuery"}

# --- 6-step analysis SOP -------------------------------------------------
# Steps are 1-based (01..06): 意图识别 / 本体模型匹配 / 深度思考&分析规划 /
# 数据获取和可视化 / 根因分析 / 决策行动.  Structured ``sop_progress`` events
# are emitted only at real stage transitions; the frontend mirrors them and
# completes all six steps solely on a terminal ``done`` event.
SOP_STEP_INTENT = 1
SOP_STEP_ONTOLOGY = 2
SOP_STEP_PLANNING = 3
SOP_STEP_QUERY = 4
SOP_STEP_ROOTCAUSE = 5
SOP_STEP_DECISION = 6

# Tool -> (SOP step, detail).  Query tools (Ontology-FactQuery / Ontology-MetricQuery) are
# handled separately because they own the planning/execute/result cycle.
_SOP_TOOL_STEP: dict[str, tuple[int, str]] = {
    "Ontology-SemanticQuery": (SOP_STEP_ONTOLOGY, "本体语义匹配"),
    "Ontology-TermDisambiguate": (SOP_STEP_ONTOLOGY, "术语匹配"),
    "MetricCalculation": (SOP_STEP_ONTOLOGY, "指标匹配"),
    "Ontology-GraphContext": (SOP_STEP_ONTOLOGY, "加载 Ontology 对象模型"),
    "Ontology-EntityDescribe": (SOP_STEP_ONTOLOGY, "加载 Ontology 对象模型"),
    "ListBusinessObjects": (SOP_STEP_ONTOLOGY, "加载 Ontology 对象模型"),
    "Ontology-GraphExpand": (SOP_STEP_ONTOLOGY, "加载业务流程与规则"),
    "Ontology-RelationQuery": (SOP_STEP_ONTOLOGY, "加载业务流程与规则"),
    "ListTables": (SOP_STEP_QUERY, "读取数据表结构"),
    "DescribeTable": (SOP_STEP_QUERY, "读取数据表结构"),
    "TableGenerate": (SOP_STEP_QUERY, "生成数据表格"),
    "ChartGenerate": (SOP_STEP_QUERY, "生成图表"),
    "ChartGenerateMultiDim": (SOP_STEP_QUERY, "生成图表"),
}

# Matches a Markdown table separator row, e.g. "| --- | :---: | ---: |"
_MD_TABLE_SEP_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$",
    re.MULTILINE,
)


def _has_markdown_table(text: str) -> bool:
    return bool(text) and bool(_MD_TABLE_SEP_RE.search(text))


RESPONSE_PRESENTATION_RULES = """# 输出展示规范
- 本规则优先于 Agent 定义中任何旧的表情模板:正文、标题、结论和建议只使用纯文字或标准 Markdown,不要输出装饰性表情符号、图标前缀或图标专用加粗标记。
- 结论、根因分析、行动建议以及图表/表格类型徽标由界面自动生成，回答中不要重复输出这些图标或徽标。
- 保留必要的 Markdown 加粗、列表和表格结构，但不要用表情符号替代标题层级或项目符号。

# 分析深度与卡片约束
- 先按用户原问题的整体语义判断 L1–L5，不要只按关键词匹配：L1 只交付数据/图表/结论；L2 只定位异常、偏差、波动和问题；L3 交付根因证据链、证据验证和 1–2 条建议雏形；L4 交付包含效果/成本/风险/周期并带推荐项的完整方案；L5 交付包含责任视角、时间节点、完成标准、监控指标和复盘机制的执行计划。
- L1 不主动做根因或建议，L2 不主动展开根因；“怎么办/给方案/如何改善”是 L4 语义，不等同于 L3 根因意图；“执行计划/落地/监控/复盘”是 L5 语义。
- 只要最终回答出现“根因分析”“根因证据链”或“根因”章节，同一轮无条件必须继续输出“行动建议”“建议雏形”“执行建议”或“建议”章节；不能因为用户没有明确要求建议而结束。
- 行动建议必须基于已验证的根因证据，至少给 1–2 条具体动作，不重复根因，不写空泛的“加强管理”，也不能声称动作已经执行。
- 使用纯文字标题“结论”“根因分析”“行动建议”，不要用表情符号作为标题或机器标记。
- 每轮分析继承当前 AnalysisContext；只在用户或明确分析步骤改变时更新对应范围。
- 字段名、表名和模型常识只能作为提示；数据不足时明确说明，Proxy 不能冒充请求指标。
- 关联不等于因果；没有额外验证机制时只能输出关联或排查假设，不能宣称已确认原因。
- 多个查询结果冲突时先 reconciliation；无法解决就披露冲突，不要挑选一个数字。
- 最终结论强度必须匹配 FACT / ASSOCIATION / INFERENCE / VERIFIED Claim 等级。
- Claim 是事实可靠性护栏，不是回答模板：明确的数据事实必须有查询或本体证据；允许输出确定性计算、趋势解释、合理推断、排查方向和行动建议，但必须用与证据强度相符的措辞，不能把推断伪装成已经确认的事实。
- 数字不参与最终回答门禁：任何数字格式、舍入、单位换算、比例或派生计算都不得触发整段重写、阻断或空回答；数字可靠性依靠取数口径、来源说明和回答措辞保障。
- 已取得可用查询结果时必须给出用户可见的最终回答；证据校验器异常或仅发现因果措辞偏强等软风险时，不得返回空白，应保留候选答案并局部降调。
"""


class WebSession:
    """One browser session = one Conversation + one event stream."""

    def __init__(
        self,
        cwd: str,
        agent_def: AgentDef,
        ontology_store: OntologyStore,
        max_iterations: Optional[int] = None,
        *,
        tools_override: Optional[list[str]] = None,
        report_context_block: Optional[str] = None,
        context_header: Optional[str] = None,
        role_block: Optional[str] = None,
        ontology_backend: str = "local",
        ontology_repository_id: str = "",
        tool_executors: Optional[dict[str, Callable[[dict[str, Any], str], str]]] = None,
    ) -> None:
        self.cwd = cwd
        self.agent_def = agent_def
        self.ontology_store = ontology_store
        self.messages: list[dict[str, Any]] = []
        self.first_user_question = ""
        self.cost_tracker = CostTracker()
        self.max_iterations = max_iterations or agent_def.max_iterations or 40

        # --- Per-session overrides ----------------------------------------
        # tools_override: if not None, takes precedence over agent_def.tools
        # report_context_block: appended to the system prompt under
        #   `# 报表上下文`. context_header (optional) shows a short status
        #   line (e.g., "# 数据库工具可用性: enabled")
        self._tools_override: Optional[list[str]] = (
            list(tools_override) if tools_override is not None else None
        )
        self._report_context_block: Optional[str] = report_context_block
        self._context_header: Optional[str] = context_header
        # role_block: 用户画像 + 回答风格偏好(角色选择页设置),注入系统提示。
        self._role_block: Optional[str] = role_block
        # The local workbook remains available for fallback tools, but it is
        # not authoritative when the active ontology source is remote.
        self.ontology_backend = str(ontology_backend or "local").strip().lower()
        self.ontology_repository_id = str(ontology_repository_id or "").strip()
        # Source-facing tools are captured per browser session. Render and
        # utility tools continue to use the shared immutable registry.
        self._tool_executors = dict(tool_executors or {})
        self.analysis_context = AnalysisContext()
        self.query_results: list[QueryResult] = []
        self.claims: list[Claim] = []
        self.reconciliation_conflicts: list[str] = []
        self._turn_results: list[QueryResult] = []

        # Skills & system prompt (skills must be loaded before prompt build)
        init_bundled_skills()
        load_skills(cwd)
        self.system_prompt = self._build_system_prompt()

        # Aggregate history of ontology entities seen this session (dedup by
        # source/type/code so separate repositories cannot overwrite each other).
        self.ontology_seen: dict[str, dict[str, Any]] = {}

        # Pending AskUser tool_use whose result must be supplied by the user.
        # When non-None, the next call to run_loop() must start by appending a
        # synthetic tool_result for this id, not a fresh user message.
        self.pending_tool_use_id: Optional[str] = None
        self.pending_choice_spec: Optional[dict[str, Any]] = None
        self._pending_sibling_results: list[dict[str, Any]] = []
        # Per-turn chart policy state.  This is deterministic and intentionally
        # independent of the LLM provider: list/enumeration requests whose
        # chart values are all identical should render as a table only.
        self._active_user_text = ""
        self._chart_suppressed_this_turn = False
        self._table_rendered_this_turn = False
        self._user_turn_count = 0
        # Structured 6-step SOP tracking (1-based steps).
        self._sop_last_step: Optional[int] = None
        self._sop_query_failed = False

        # --- Phase-1 concurrency coordination ---------------------------
        # Set by the web layer for every turn: the per-session slot (busy /
        # generation / cancel) and the generation captured at turn start.
        self._turn_ctx: Optional[TurnContext] = None

        # Automatic quota fallback is scoped to the CURRENT turn only.  The
        # fallback model is never persisted to the user's saved model choice;
        # the next user turn restarts on the explicitly selected model.
        self._turn_fallback_model_key: Optional[str] = None

    # ------------------------------------------------------------------
    # System-prompt construction (honours per-session overrides)
    # ------------------------------------------------------------------

    @property
    def allowed_tools(self) -> Optional[list[str]]:
        """Effective tool whitelist for the current session."""
        if self._tools_override is not None:
            return self._tools_override
        return self.agent_def.tools

    def _build_system_prompt(self) -> str:
        # If tools_override is set, build against a shallow clone of the
        # agent_def so build_system_prompt's tool listing reflects it.
        if self._tools_override is not None:
            effective_def = copy.copy(self.agent_def)
            effective_def.tools = list(self._tools_override)
        else:
            effective_def = self.agent_def
        prompt = build_system_prompt(self.cwd, agent_def=effective_def)
        extras: list[str] = []
        extras.append("# AnalysisContext\n\n" + str(self.analysis_context.to_dict()))
        if self._context_header:
            extras.append(self._context_header.strip())
        extras.append(RESPONSE_PRESENTATION_RULES.strip())
        if self._role_block:
            extras.append(self._role_block.strip())
        if self._report_context_block:
            extras.append(
                "# 报表上下文\n\n(以下内容来自用户上传的报表,请将其作为回答的主要依据)\n\n"
                + self._report_context_block.strip()
            )
        if extras:
            prompt = prompt.rstrip() + "\n\n" + "\n\n".join(extras) + "\n"
        return prompt

    def set_tools_override(self, tools: Optional[list[str]]) -> None:
        """
        Change the effective tool whitelist mid-session (e.g., user toggled
        the '启用数据库查询' checkbox). Rebuilds the system prompt so the
        tool listing matches what the LLM will actually be allowed to call.
        """
        self._tools_override = list(tools) if tools is not None else None
        self.system_prompt = self._build_system_prompt()

    def set_role_block(self, block: Optional[str]) -> None:
        """
        Update the 用户画像/回答风格 block mid-session (角色选择页保存时调用).
        Rebuilds the system prompt so the next turn reflects the new role
        preferences — no conversation reset required.
        """
        self._role_block = block
        self.system_prompt = self._build_system_prompt()

    def set_context_header(self, header: Optional[str]) -> None:
        """
        Update the `# 当前报表 ... # 数据库工具可用性: ...` marker block
        mid-session. Must be called together with `set_tools_override` when
        flipping the db-query toggle, otherwise the agent will see a stale
        availability marker and refuse to use the tools it actually has.
        """
        self._context_header = header
        self.system_prompt = self._build_system_prompt()

    def update_analysis_context(self, changes: dict[str, Any]) -> AnalysisContext:
        """Merge explicit scope changes while preserving omitted fields."""
        self.analysis_context = self.analysis_context.merge(changes)
        self.system_prompt = self._build_system_prompt()
        return self.analysis_context

    def record_query_result(self, tool_name: str, params: dict[str, Any], output: str) -> QueryResult | None:
        """Normalize a data-query result, build claims, and reconcile drilldowns.

        Only real data queries enter ``query_results`` / ``_turn_results`` so
        display tools can never become a later data source or a reconciliation
        candidate.  Relation tools produce an Association claim only when the
        output carries explicit edge evidence; lookup tools may still emit
        missing/proxy disclosures through their params.
        """
        context_changes: dict[str, Any] = {}
        if params.get("metric_codes"):
            context_changes["metrics"] = params["metric_codes"]
        elif params.get("metric"):
            context_changes["metrics"] = (params["metric"],)
        for key in ("dimensions", "filters", "time_scope", "entity_scope", "comparison_scope"):
            if params.get(key) not in (None, "", [], {}):
                context_changes[key] = params[key]
        if context_changes:
            self.update_analysis_context(context_changes)

        if tool_name in RELATION_TOOLS:
            has_evidence, status = relation_evidence_status(output)
            if has_evidence:
                relation = Association(
                    from_entity=params.get("from_entity") or "source",
                    to_entity=params.get("to_entity") or "target",
                    relation_type=RelationType.ONTOLOGY_RELATION,
                    evidence=(f"association-{len(self.claims)}",),
                )
                self.claims.append(association_claim(
                    relation,
                    claim_id=f"association-{len(self.claims)}",
                    statement="工具结果显示业务对象之间存在关联路径",
                ))
            else:
                self.claims.append(Claim(
                    id=f"relation-missing-{len(self.claims)}",
                    statement="关系检索未返回可验证的关联路径证据",
                    level=ClaimLevel.FACT,
                    limitations=(LimitationType.RELATION_MISSING,),
                ))
            return None

        is_data_query = tool_name in DATA_QUERY_TOOLS
        if not is_data_query and not (params.get("requested_measure") and params.get("available") is False):
            return None

        scope = {key: params[key] for key in (
            "metric", "metric_codes", "dimensions", "filters", "time_scope",
            "entity_scope", "comparison_scope") if key in params and params[key] not in (None, "", [], {})}
        semantic: dict[str, Any] = {"tool": tool_name}
        for key in ("metric", "metric_code", "metric_codes", "semantic_type", "unit",
                    "value", "parent_value", "child_values", "requested_measure",
                    "available", "proxy"):
            if key in params:
                semantic[key] = params[key]
        result = QueryResult(
            data=output,
            scope=scope or self.analysis_context.to_dict(),
            semantic=semantic,
            provenance=Provenance(source=tool_name, query=str(params.get("query") or "")),
        )
        result = enrich_query_result(result)
        semantic = dict(result.semantic)
        if is_data_query:
            self.query_results.append(result)
            self._turn_results.append(result)
            self.claims.extend(claims_from_query_result(result, f"{tool_name}-{len(self.query_results)}"))
            if "parent_value" in semantic:
                self.claims.append(Claim(
                    id=f"{tool_name}-{len(self.query_results)}-parent",
                    statement=f"parent={semantic['parent_value']}", level=ClaimLevel.FACT,
                    scope=result.scope, supports=(f"{tool_name}-{len(self.query_results)}",),
                    provenance=result.provenance,
                ))
            if isinstance(semantic.get("child_values"), (list, tuple)):
                self.claims.extend(Claim(
                    id=f"{tool_name}-{len(self.query_results)}-child-{index}",
                    statement=f"child[{index}]={value}", level=ClaimLevel.FACT,
                    scope=result.scope, supports=(f"{tool_name}-{len(self.query_results)}",),
                    provenance=result.provenance,
                ) for index, value in enumerate(semantic["child_values"]))
        if params.get("requested_measure") and params.get("available") is False:
            self.claims.append(Claim(
                id=f"missing-{len(self.query_results)}",
                statement=f"请求指标 {params['requested_measure']} 当前无法直接计算",
                level=ClaimLevel.FACT,
                scope=result.scope,
                limitations=(LimitationType.DATA_MISSING,),
                provenance=result.provenance,
            ))
            if params.get("proxy"):
                self.claims.append(Claim(
                    id=f"proxy-{len(self.query_results)}",
                    statement=f"可使用代理指标 {params['proxy']} 观察相关趋势，但不等价于原指标",
                    level=ClaimLevel.INFERENCE,
                    scope=result.scope,
                    limitations=(LimitationType.INSUFFICIENT_EVIDENCE,),
                    semantic={"semantic_type": "PROXY", "requested_measure": params["requested_measure"]},
                    provenance=result.provenance,
                ))
        if is_data_query:
            reconciliation = reconcile_query_results(self._turn_results)
            conflict = detect_conflicts(self._turn_results)
            if (reconciliation and reconciliation.status == ValidationStatus.REJECT) or conflict.status == ValidationStatus.REJECT:
                issue = reconciliation.issues[0] if reconciliation and reconciliation.issues else conflict.issues[0]
                self.reconciliation_conflicts.append(issue)
                self.claims = [replace(
                    claim,
                    limitations=tuple(dict.fromkeys((*claim.limitations, LimitationType.CONFLICTING_EVIDENCE))),
                ) for claim in self.claims]
        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_turn(self, user_text: str, visible_user_text: Optional[str] = None) -> Generator[dict[str, Any], None, None]:
        """Yield events for one user turn (user message → assistant → tools → ...)."""
        # Refuse to even start when the turn was already superseded (e.g. a
        # restore reused this session while the request was queued): no user
        # message may be appended to the new session's history.
        if self._turn_superseded():
            yield {"type": "session_superseded"}
            return
        # A new user turn always restarts on the user's explicitly selected
        # model; any automatic fallback from a previous turn is released here.
        self._turn_fallback_model_key = None
        self._user_turn_count += 1
        self._active_user_text = str(user_text or "")
        self._sop_last_step = None
        self._sop_query_failed = False
        visible = str(visible_user_text if visible_user_text is not None else user_text or "")
        visible = re.sub(r"\s+", " ", visible).strip()[:60]
        if visible and not self.first_user_question:
            self.first_user_question = visible
        self._chart_suppressed_this_turn = False
        self._table_rendered_this_turn = False
        self._turn_results = []
        self.claims = []
        self.reconciliation_conflicts = []
        self.messages.append({"role": "user", "content": user_text})
        yield {"type": "user_message", "text": user_text}
        yield self._sop_event(SOP_STEP_INTENT, "用户问题解析", allow_backward=False)
        yield from self._run_loop()

    def continue_with_choice(
        self,
        choice_ids: list[str] | str,
        choice_labels: list[str] | str,
    ) -> Generator[dict[str, Any], None, None]:
        """Resume a turn that paused on an AskUser call.

        Accepts either lists (multi-select) or single strings (legacy single-pick).
        The deferred AskUser tool_use gets its synthetic tool_result here
        (the user's selection(s)). Any sibling tool_uses that were executed
        before the pause contribute their cached results in the same user
        message, so every tool_use in the prior assistant turn has a
        matching tool_result.
        """
        if isinstance(choice_ids, str):
            choice_ids = [choice_ids]
        if isinstance(choice_labels, str):
            choice_labels = [choice_labels]
        if not choice_ids or not choice_labels or len(choice_ids) != len(choice_labels):
            yield {"type": "error", "message": "invalid choice payload"}
            return

        if not self.pending_tool_use_id:
            yield {"type": "error", "message": "no pending choice"}
            return
        if self._turn_superseded():
            yield {"type": "session_superseded"}
            return
        tool_use_id = self.pending_tool_use_id
        sibling_results = getattr(self, "_pending_sibling_results", []) or []
        self.pending_tool_use_id = None
        self.pending_choice_spec = None
        self._pending_sibling_results = []

        if len(choice_labels) == 1:
            content_text = f"User selected: {choice_labels[0]} (id={choice_ids[0]})"
        else:
            joined = "、".join(
                f"{lbl} (id={cid})"
                for cid, lbl in zip(choice_ids, choice_labels)
            )
            content_text = f"User selected {len(choice_labels)} options: {joined}"
        user_content = list(sibling_results) + [{
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": content_text,
        }]
        self.messages.append({"role": "user", "content": user_content})
        yield {
            "type": "user_choice_resolved",
            "tool_use_id": tool_use_id,
            "choice_ids": list(choice_ids),
            "choice_labels": list(choice_labels),
            # Legacy single-pick mirrors for any old client code:
            "choice_id": choice_ids[0],
            "choice_label": choice_labels[0],
        }
        yield from self._run_loop()

    # ------------------------------------------------------------------
    # Turn loop
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Phase-1 concurrency helpers
    # ------------------------------------------------------------------

    def _active_model_key(self) -> str:
        """Model key used for LLM calls in the current turn.

        An automatic quota fallback only applies to the current turn: it is
        never persisted to the saved user model choice, and the next user
        turn starts again on the user's explicitly selected model.
        """
        cfg = get_llm_config()
        return self._turn_fallback_model_key or cfg.model_key

    def _turn_superseded(self, turn_ctx: Optional[TurnContext] = None) -> bool:
        """True when this turn was cancelled or its session generation moved
        on (reset / restore / activate / source switch).  A superseded turn
        must stop committing anything and exit with ``session_superseded``.

        Ownership is checked via the turn's captured context: the generation
        must still match AND the slot must still be owned by this turn's
        lease token.  A stale lease (old turn, new owner) is superseded."""
        ctx = turn_ctx if turn_ctx is not None else getattr(self, "_turn_ctx", None)
        if ctx is None:
            return False
        if ctx.cancel.is_set():
            return True
        return ctx.slot.is_superseded(ctx.lease, ctx.cancel)

    def _commit_messages(
        self,
        content: list[dict[str, Any]],
        turn_ctx: Optional[TurnContext] = None,
    ) -> bool:
        """Append one assistant turn to ``self.messages`` atomically with the
        supersession check (under the slot lock), so a reset/restore racing a
        commit can never leave a torn message list on the new session."""
        ctx = turn_ctx if turn_ctx is not None else getattr(self, "_turn_ctx", None)
        if ctx is not None:
            with ctx.slot.lock:
                if ctx.slot.is_superseded(ctx.lease, ctx.cancel):
                    return False
                self.messages.append({"role": "assistant", "content": content})
                return True
        self.messages.append({"role": "assistant", "content": content})
        return True

    def _run_loop(self) -> Generator[dict[str, Any], None, None]:
        # Capture the turn's ownership context ONCE.  A newer turn (after a
        # reset/restore that reuses this session object) may overwrite
        # ``self._turn_ctx``, but this running turn keeps its own reference
        # so supersession checks and commits always use ITS lease/cancel.
        turn_ctx = getattr(self, "_turn_ctx", None)
        stop_reason = "end_turn"
        # Per-turn render-enforcement bookkeeping
        called_tools_this_turn: set[str] = set()
        text_concat_this_turn: str = ""
        enforced_render: bool = False
        enforced_answer_validation: bool = False
        root_cause_seen = False
        delivery_blocked = False

        for iteration in range(self.max_iterations):
            if self._turn_superseded(turn_ctx):
                yield {"type": "session_superseded"}
                return
            yield {"type": "iteration_start", "iteration": iteration}

            cfg = get_llm_config()
            active_model_key = self._active_model_key()
            current_model_id = get_model_id(active_model_key)

            yield {
                "type": "llm_request",
                "iteration": iteration,
                "model": current_model_id,
                "model_key": active_model_key,
                "max_tokens": cfg.max_tokens,
                "temperature": cfg.temperature,
                "message_count": len(self.messages),
                "messages_snapshot": self._snapshot_messages(),
            }

            # While structured claims exist, every no-tool response is a
            # candidate final narrative: its text deltas are buffered and only
            # committed (streamed + persisted) after the claim/render gates
            # below accept it. Tool-bearing responses always stream live.
            defer_text = bool(self.claims)
            stop_reason, text_buffer, tool_uses, usage, thinking_blocks = (
                yield from self._stream_one_response(iteration, defer_text=defer_text, turn_ctx=turn_ctx)
            )

            # A provider error already emitted an SSE error event. Do not
            # append a partial assistant message or emit `done`, otherwise the
            # browser saves an incomplete turn as if it completed normally.
            if stop_reason == "error":
                return
            if stop_reason == "superseded":
                yield {"type": "session_superseded"}
                return

            # The turn may have been cancelled / superseded while the model
            # stream was in flight (the sync request cannot be interrupted).
            # Stop here: no llm_response, no tool execution, no history write.
            if self._turn_superseded(turn_ctx):
                yield {"type": "session_superseded"}
                return

            # A deferred response that still requested tools carries only
            # interstitial text (never a claim-validated narrative), so release
            # it right away, before the tool results are emitted.
            if defer_text and tool_uses and text_buffer:
                yield {"type": "text_delta", "text": text_buffer}

            # Step 05 (根因分析) is never entered just because a data query ran:
            # L1/L2 取数与异常定位 must not fabricate root-cause work.  The
            # backend only emits step 05 when the committed narrative really
            # contains a root-cause section (see _emit_assistant_iteration);
            # a later query still rewinds to planning inside _sop_for_tool.

            # No-tool responses while claims exist stay buffered until they
            # pass claim validation; nothing visible or persisted yet.
            candidate_pending = bool(self.claims) and not tool_uses

            if not candidate_pending:
                committed = yield from self._emit_assistant_iteration(
                    iteration, stop_reason, text_buffer,
                    tool_uses, thinking_blocks, usage, turn_ctx,
                )
                if not committed:
                    yield {"type": "session_superseded"}
                    return
                # Track this iteration's tool calls + text for render enforcement
                for tu in tool_uses:
                    called_tools_this_turn.add(tu["name"])
                if text_buffer:
                    text_concat_this_turn += "\n" + text_buffer
                    root_cause_seen = root_cause_seen or has_root_cause_section(text_buffer)

            if stop_reason != "tool_use" or not tool_uses:
                # ---- Render enforcement ------------------------------------
                # Trigger when the agent fetched data (Ontology-FactQuery) or wrote a
                # Markdown table into the chat, but never called any of the
                # rendering tools. Inject one corrective user message and
                # re-prompt; only fires once per turn to avoid loops.
                allowed = set(self.allowed_tools or [])
                has_render_tool_available = bool(allowed & RENDER_TOOLS)
                fetched_data = bool(called_tools_this_turn & DATA_FETCH_TOOLS)
                check_text = text_concat_this_turn
                if text_buffer:
                    check_text = f"{check_text}\n{text_buffer}".strip()
                wrote_md_table = _has_markdown_table(check_text)
                rendered = bool(called_tools_this_turn & RENDER_TOOLS)
                table_rendered = (
                    "TableGenerate" in called_tools_this_turn
                    or self._table_rendered_this_turn
                )
                suppressed_chart_needs_table = (
                    self._chart_suppressed_this_turn and not table_rendered
                )

                if (
                    not enforced_render
                    and has_render_tool_available
                    and (fetched_data or wrote_md_table or suppressed_chart_needs_table)
                    and (not rendered or suppressed_chart_needs_table)
                ):
                    enforced_render = True
                    reasons: list[str] = []
                    if fetched_data:
                        reasons.append("已经执行了 `Ontology-FactQuery` 取数")
                    if wrote_md_table:
                        reasons.append("回复正文里直接写了 Markdown 表格")
                    if suppressed_chart_needs_table:
                        reasons.append("列表型问题的图表数值全部相同")
                    reason_text = "且".join(reasons)
                    if suppressed_chart_needs_table:
                        reminder = (
                            "⚠️ **渲染规则提醒**\n\n"
                            f"你这一轮{reason_text}。该问题属于枚举/列表展示，"
                            "不要重试 ChartGenerate；现在只调用 **`TableGenerate`** "
                            "输出完整表格，再用 1~2 句话给结论。"
                        )
                    else:
                        reminder = (
                            "⚠️ **强制纪律检查 · 渲染工具未调用**\n\n"
                            f"你这一轮{reason_text},但**没有调用** `TableGenerate` / "
                            "`ChartGenerate` / `ChartGenerateMultiDim`,看板和对话里都不会出现"
                            "结构化卡片,直接违反 SOP。\n\n"
                            "**现在立刻补做**:\n"
                            "1. 调用 **`TableGenerate`** 把核心数据渲染成表格卡片"
                            "(必须;列名、数据行、可选 footer 都给齐,不要再粘 Markdown 表)。\n"
                            "2. 如果数据有时间趋势 / 维度对比意义,在表格之后再追加一次 "
                            "**`ChartGenerate`** 渲染折线 / 柱状 / 饼图。\n"
                            "3. 渲染完成后用 1~2 句话给结论,不要复述表格里已经有的数字。\n\n"
                            "⚠️ 不要再用纯文本或 Markdown 表代替工具调用。"
                        )
                    self.messages.append({"role": "user", "content": reminder, "internal": True})
                    yield {
                        "type": "render_enforce",
                        "iteration": iteration,
                        "reasons": reasons,
                        "called_tools": sorted(called_tools_this_turn),
                        "message": reminder,
                    }
                    continue  # re-prompt LLM with the reminder appended

                if self.claims:
                    # Validate ONLY this candidate's own text. The
                    # concatenation of previous drafts must never be fed back
                    # in, otherwise a stale rejected draft would poison the
                    # check for the freshly generated narrative.
                    try:
                        validation = validate_claims(self.claims, text_buffer or "")
                    except Exception as exc:
                        # Validator availability must never become answer
                        # availability. Keep the candidate, emit an observable
                        # warning and preserve the factual guard for later turns.
                        logger.exception("evidence validator failed")
                        yield {
                            "type": "answer_validation",
                            "status": "warning",
                            "issues": [f"validator error: {type(exc).__name__}"],
                        }
                        validation = None
                    if validation is not None and validation.status == ValidationStatus.ALLOW_WITH_WARNING:
                        original_text = text_buffer
                        text_buffer = soften_evidence_language(text_buffer or "", validation.findings)
                        yield {
                            "type": "answer_validation",
                            "status": "warning",
                            "issues": list(validation.issues),
                            "adjusted": text_buffer != original_text,
                        }
                    if validation is not None and validation.status == ValidationStatus.REJECT:
                        if enforced_answer_validation:
                            fallback_text = self._blocked_answer_fallback(validation.issues)
                            yield {
                                "type": "answer_blocked",
                                "status": "blocked",
                                "issues": list(validation.issues),
                                "message": "部分叙述未通过结构化证据校验，已改为展示安全兜底回答。",
                            }
                            # Never leave the user with ontology/tool activity
                            # and no answer.  Rejected drafts remain hidden, but
                            # a deterministic evidence-only narrative is both
                            # streamed and persisted as the final delivery.
                            yield {"type": "text_delta", "text": fallback_text}
                            committed = yield from self._emit_assistant_iteration(
                                iteration,
                                "answer_blocked",
                                fallback_text,
                                [],
                                [],
                                usage,
                                turn_ctx,
                            )
                            if not committed:
                                yield {"type": "session_superseded"}
                                return
                            text_concat_this_turn += "\n" + fallback_text
                            delivery_blocked = True
                            break
                        enforced_answer_validation = True
                        claim_lines = "\n".join(
                            f"- [{claim.level.value}] {claim.statement}"
                            + (f"（限制：{'、'.join(str(x.value if hasattr(x, 'value') else x) for x in claim.limitations)}）" if claim.limitations else "")
                            for claim in self.claims
                        )
                        reminder = (
                            "最终回答存在必须修正的事实一致性问题："
                            + "；".join(validation.issues)
                            + "。明确的数据事实必须有证据支持；允许做确定性计算、分析、假设和建议，"
                              "但不得把推断伪装成已确认事实，必须披露冲突、代理指标和证据限制。\n"
                            + claim_lines
                        )
                        self.messages.append({"role": "user", "content": reminder, "internal": True})
                        yield {"type": "claim_context", "claims": [claim.id for claim in self.claims]}
                        yield {"type": "answer_validation", "status": "rejected", "issues": list(validation.issues)}
                        continue

                # ---- Commit the validated candidate ----------------------
                # The buffered narrative passed every gate: replay its text
                # deltas to the browser, emit llm_response and persist it to
                # history in one step. Rejected/discarded candidates never
                # reach this point, so only one final narrative is visible.
                if candidate_pending:
                    if text_buffer:
                        yield {"type": "text_delta", "text": text_buffer}
                    committed = yield from self._emit_assistant_iteration(
                        iteration, stop_reason, text_buffer,
                        tool_uses, thinking_blocks, usage, turn_ctx,
                    )
                    if not committed:
                        yield {"type": "session_superseded"}
                        return
                    for tu in tool_uses:
                        called_tools_this_turn.add(tu["name"])
                    if text_buffer:
                        text_concat_this_turn += "\n" + text_buffer
                        root_cause_seen = root_cause_seen or has_root_cause_section(text_buffer)

                break

            # If any tool_use is AskUser, run the siblings now (if any) and
            # pause. We cache the sibling results so continue_with_choice
            # can emit ONE user message containing results for every
            # tool_use_id — the API rule is that every tool_use in an
            # assistant turn needs a matching tool_result in the next
            # user turn.
            ask_user_tu = next((tu for tu in tool_uses if tu["name"] == ASK_USER_TOOL_NAME), None)
            if ask_user_tu:
                sibling_results: list[dict[str, Any]] = []
                for tu in tool_uses:
                    if tu["id"] == ask_user_tu["id"]:
                        continue
                    yield from self._sop_for_tool(tu["name"], tu.get("input") or {})
                    t0 = time.time()
                    output, chart_was_suppressed = self._execute_tool(tu, turn_ctx)
                    if tu["name"] in DATA_QUERY_TOOLS:
                        if str(output).startswith("Error"):
                            self._sop_query_failed = True
                            yield self._sop_event(SOP_STEP_QUERY, "查询失败，准备调整方案")
                        else:
                            yield self._sop_event(SOP_STEP_QUERY, "解析查询结果")
                    self.record_query_result(tu["name"], tu.get("input") or {}, output)
                    self._chart_suppressed_this_turn |= chart_was_suppressed
                    duration_ms = int((time.time() - t0) * 1000)
                    display_output, chart = extract_chart_spec(output)
                    display_output, table = extract_table_spec(display_output)
                    display_output, multi_chart = extract_multidim_chart_spec(display_output)
                    display_output, todos = extract_todo_spec(display_output)
                    self._table_rendered_this_turn |= table is not None
                    llm_output = display_output if (chart or table or multi_chart or todos) else output
                    entities = self._extract_entities(display_output, tu["name"])
                    yield {
                        "type": "tool_result",
                        "id": tu["id"],
                        "name": tu["name"],
                        "input": tu["input"],
                        "output": display_output,
                        "duration_ms": duration_ms,
                        "ontology_entities": entities,
                        "chart": chart,
                        "table": table,
                        "multi_chart": multi_chart,
                        "todos": (todos or {}).get("todos") if todos else None,
                    }
                    sibling_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": llm_output,
                    })
                self._pending_sibling_results = sibling_results

                spec = dict(ask_user_tu.get("input") or {})
                self.pending_tool_use_id = ask_user_tu["id"]
                self.pending_choice_spec = spec
                yield from self._sop_for_tool(ask_user_tu["name"], spec)
                yield {
                    "type": "user_choice_requested",
                    "tool_use_id": ask_user_tu["id"],
                    "question": spec.get("question", "请选择"),
                    "options": spec.get("options", []),
                    "context": spec.get("context", ""),
                }
                yield {"type": "awaiting_user_choice"}
                return

            # Normal tool execution path
            tool_results: list[dict[str, Any]] = []
            for tu in tool_uses:
                yield from self._sop_for_tool(tu["name"], tu.get("input") or {})
                t0 = time.time()
                output, chart_was_suppressed = self._execute_tool(tu)
                if tu["name"] in DATA_QUERY_TOOLS:
                    if str(output).startswith("Error"):
                        self._sop_query_failed = True
                        yield self._sop_event(SOP_STEP_QUERY, "查询失败，准备调整方案")
                    else:
                        yield self._sop_event(SOP_STEP_QUERY, "解析查询结果")
                self.record_query_result(tu["name"], tu.get("input") or {}, output)
                self._chart_suppressed_this_turn |= chart_was_suppressed
                duration_ms = int((time.time() - t0) * 1000)

                # Pull out chart/table specs if present; keep the display text
                # for the UI, strip the JSON blocks before sending back to the LLM.
                display_output, chart = extract_chart_spec(output)
                display_output, table = extract_table_spec(display_output)
                display_output, multi_chart = extract_multidim_chart_spec(display_output)
                display_output, todos = extract_todo_spec(display_output)
                self._table_rendered_this_turn |= table is not None
                llm_output = display_output if (chart or table or multi_chart or todos) else output

                entities = self._extract_entities(display_output, tu["name"])
                yield {
                    "type": "tool_result",
                    "id": tu["id"],
                    "name": tu["name"],
                    "input": tu["input"],
                    "output": display_output,
                    "duration_ms": duration_ms,
                    "ontology_entities": entities,
                    "chart": chart,
                    "table": table,
                    "multi_chart": multi_chart,
                    "todos": (todos or {}).get("todos") if todos else None,
                }
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": llm_output,
                })

            self.messages.append({"role": "user", "content": tool_results})

        # A model can consume every main-loop iteration on ontology/schema
        # tools and never emit a no-tool narrative.  The tool events are useful
        # diagnostics but are not a user answer, so close the turn with a
        # deterministic limitation summary instead of a blank delivery.
        if not text_concat_this_turn.strip():
            fallback_text = self._no_narrative_fallback(called_tools_this_turn)
            yield {"type": "text_delta", "text": fallback_text}
            committed = yield from self._emit_assistant_iteration(
                self.max_iterations,
                "max_iterations",
                fallback_text,
                [],
                [],
                {},
                turn_ctx,
            )
            if not committed:
                yield {"type": "session_superseded"}
                return
            text_concat_this_turn = fallback_text

        # ------------------------------------------------------------------
        # Action delivery gate: a turn that delivered root cause MUST also
        # deliver at least one concrete action item. The repair phase has its
        # own counter (independent of max_iterations) and never executes
        # tools, so a root cause that appeared on the last main iteration
        # still gets its repair chances and no SQL/chart/table re-runs.
        # ------------------------------------------------------------------
        max_action_repairs = 2
        action_repairs = 0
        action_blocked = False
        if root_cause_seen and not has_effective_action(text_concat_this_turn):
            for _ in range(max_action_repairs):
                if self._turn_superseded(turn_ctx):
                    yield {"type": "session_superseded"}
                    return
                action_repairs += 1
                if action_repairs == 1:
                    reminder = (
                        "本轮回复已经出现根因章节,但还没有有效行动建议,不能结束本轮。"
                        "请基于本轮已经验证的根因证据,继续补充一个标题为‘行动建议’"
                        "(或‘管理建议’‘决策建议’‘下一步行动’等)的小节,给出 1–2 条具体动作;"
                        "每条都要有明确动作对象和执行方式,不要写‘加强管理’‘持续关注’等空话,"
                        "不要声称动作已经执行,不要重复根因分析,不要使用表情符号。"
                    )
                else:
                    reminder = (
                        "上一轮补写仍然没有有效行动建议。请只补充行动建议文本:"
                        "标题为‘行动建议’(或‘管理建议’‘决策建议’‘下一步行动’等),"
                        "给出 1–2 条可执行的具体动作并对应根因证据;"
                        "不要调用任何工具,不要重新执行已经完成的取数、图表或表格。"
                    )
                self.messages.append({"role": "user", "content": reminder, "internal": True})
                yield {
                    "type": "action_repair",
                    "attempt": action_repairs,
                    "message": reminder,
                }
                repair_iteration = self.max_iterations + action_repairs
                cfg = get_llm_config()
                active_model_key = self._active_model_key()
                yield {
                    "type": "llm_request",
                    "iteration": repair_iteration,
                    "model": get_model_id(active_model_key),
                    "model_key": active_model_key,
                    "max_tokens": cfg.max_tokens,
                    "temperature": cfg.temperature,
                    "message_count": len(self.messages),
                    "messages_snapshot": self._snapshot_messages(),
                }
                repair_stop, repair_text, repair_tools, repair_usage, repair_thinking = (
                    yield from self._stream_one_response(repair_iteration, turn_ctx=turn_ctx)
                )
                if repair_stop == "error":
                    return
                if repair_stop == "superseded" or self._turn_superseded(turn_ctx):
                    yield {"type": "session_superseded"}
                    return
                # The repair phase never executes tools: a model that still
                # requests one must not surface a dangling tool card (no
                # tool_result will ever follow) nor pollute the conversation
                # context.  Only tool names are logged — never SQL/inputs.
                if repair_tools:
                    logger.warning(
                        "action_repair tool_uses dropped turn=%s tools=%s",
                        self._user_turn_count,
                        ",".join(sorted({str(tu.get("name", "?")) for tu in repair_tools})),
                    )
                yield {
                    "type": "llm_response",
                    "iteration": repair_iteration,
                    "text": repair_text,
                    "tool_uses": [],
                    "stop_reason": repair_stop,
                    "usage": repair_usage,
                }
                repair_content: list[dict[str, Any]] = []
                repair_content.extend(repair_thinking)
                if repair_text:
                    repair_content.append({"type": "text", "text": repair_text})
                # Tool calls in a repair response are NOT executed: executing
                # them could re-run SQL/charts. History keeps only the text so
                # the next reminder can ask for a pure-text supplement.
                if repair_content and not self._commit_messages(repair_content, turn_ctx):
                    yield {"type": "session_superseded"}
                    return
                if repair_text:
                    text_concat_this_turn += "\n" + repair_text
                if has_effective_action(text_concat_this_turn):
                    break
            else:
                action_blocked = True
                yield {
                    "type": "delivery_incomplete",
                    "reason": "action_missing",
                    "attempts": action_repairs,
                    "message": "本轮根因分析后连续补写仍未生成有效行动建议,交付不完整。",
                }
                logger.warning(
                    "delivery_incomplete action_missing turn=%s repairs=%s",
                    self._user_turn_count,
                    action_repairs,
                )

        if self._turn_superseded(turn_ctx):
            yield {"type": "session_superseded"}
            return

        if root_cause_seen and not action_blocked:
            items: list[dict[str, Any]] = []
            for raw in extract_action_items(text_concat_this_turn):
                parsed = split_action_item(raw)
                items.append({
                    "title": (parsed.get("title") or raw)[:80],
                    "content": parsed.get("content") or raw,
                    "evidence": parsed.get("evidence"),
                })
            if items:
                yield {
                    "type": "action_recommendations",
                    "turn": self._user_turn_count,
                    "items": items,
                }

        yield self._sop_event(SOP_STEP_DECISION, "正在返回用户结果")

        yield {
            "type": "done",
            "stop_reason": (
                "delivery_incomplete" if action_blocked
                else ("answer_blocked" if delivery_blocked else stop_reason)
            ),
        }

    def _blocked_answer_fallback(self, issues: Any) -> str:
        """Evidence-only answer used after both narrative repairs fail."""
        claim_lines = [render_claim(claim) for claim in self.claims]
        confirmed = "\n".join(f"- {line}" for line in claim_lines if line)
        if not confirmed:
            confirmed = "- 本轮尚未形成可验证的数据事实。"
        return (
            "结论\n\n"
            "本轮工具检索已完成，但自动证据校验发现最终叙述包含无法由结构化结果确认的"
            "数字或确定性判断，因此未展示原候选回答。\n\n"
            "当前可确认的证据\n\n"
            f"{confirmed}\n\n"
            "后续处理\n\n"
            "需要重新执行或补全数据查询的结构化结果后，才能给出包含相关数字的业务结论。"
        )

    def _no_narrative_fallback(self, called_tools: set[str]) -> str:
        """Close ontology/schema-only turns with an explicit user delivery."""
        tools = "、".join(sorted(called_tools)) or "本体/数据工具"
        claim_lines = [render_claim(claim) for claim in self.claims]
        confirmed = "\n".join(f"- {line}" for line in claim_lines if line)
        evidence = f"\n\n当前可确认的证据\n\n{confirmed}" if confirmed else ""
        return (
            "结论\n\n"
            f"本轮已完成 {tools} 的检索，但在最大执行轮次内没有形成可交付的数据结论。"
            f"{evidence}\n\n"
            "下一步需要补齐可执行的数据查询、物理字段映射或明确分析口径；当前不把本体操作"
            "本身当作最终业务答案。"
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Structured 6-step SOP progress (01..06)
    # ------------------------------------------------------------------
    def _sop_event(self, step: int, detail: str, allow_backward: bool = True) -> dict[str, Any]:
        """Structured SOP progress event; ``step`` is 1-based (01..06)."""
        self._sop_last_step = step
        return {
            "type": "sop_progress",
            "step": step,
            "detail": detail,
            "allow_backward": allow_backward,
        }

    def _sop_for_tool(
        self,
        name: str,
        params: Optional[dict[str, Any]] = None,
    ) -> Generator[dict[str, Any], None, None]:
        """Map a real tool execution onto the 6-step SOP state machine."""
        if name in DATA_QUERY_TOOLS:
            if self._sop_query_failed:
                yield self._sop_event(SOP_STEP_PLANNING, "根据查询错误调整方案")
                self._sop_query_failed = False
            elif self._sop_last_step in (SOP_STEP_QUERY, SOP_STEP_ROOTCAUSE, SOP_STEP_DECISION):
                # A later query after data-fetch / root-cause / decision work:
                # visibly rewind to planning (04→03 / 05→03 / 06→03).
                yield self._sop_event(SOP_STEP_PLANNING, "根据分析结果重新规划")
            plan_detail = (
                "生成自主 SQL 方案" if name == "Ontology-FactQuery" else "生成指标配置查询方案"
            )
            if self._sop_last_step != SOP_STEP_PLANNING:
                yield self._sop_event(SOP_STEP_PLANNING, plan_detail)
            execute_detail = (
                "执行自主 SQL 查询" if name == "Ontology-FactQuery" else "执行指标配置查询"
            )
            yield self._sop_event(SOP_STEP_QUERY, execute_detail)
            return
        if name == "AskUser":
            params = params or {}
            question = str(params.get("question") or "")
            if any(key in params for key in ("dimension", "dimensions")) or "维度" in question:
                detail = "维度下钻（等待用户确认）"
            elif any(key in params for key in ("term", "terms")) or "术语" in question:
                detail = "术语消歧（等待用户确认）"
            else:
                detail = "等待用户确认口径或维度"
            step = SOP_STEP_INTENT
            yield self._sop_event(step, detail)
            return
        mapping = _SOP_TOOL_STEP.get(name)
        if mapping is not None:
            yield self._sop_event(*mapping)

    def _execute_tool(
        self,
        tool_use: dict[str, Any],
        turn_ctx: Optional[TurnContext] = None,
    ) -> tuple[str, bool]:
        """Execute a tool, applying the deterministic chart usefulness guard."""

        name = str(tool_use.get("name") or "")
        params = tool_use.get("input")
        if not isinstance(params, dict):
            params = {}
        else:
            params = dict(params)
        # Render tools normalize bare codes to trusted business names BEFORE
        # validation/execution. Unresolvable codes are kept verbatim; SQL
        # snippets, URLs, JSON and source_note are never rewritten.
        if name in {"ChartGenerate", "ChartGenerateMultiDim", "TableGenerate"}:
            params = normalize_display_params(name, params, self._display_resolver())
        if name in {"ChartGenerate", "ChartGenerateMultiDim", "TableGenerate"} and self.query_results:
            latest = self.query_results[-1]
            if name.startswith("Chart"):
                series = params.get("series")
                if isinstance(series, list):
                    for item in series:
                        if not isinstance(item, dict):
                            continue
                        item.setdefault("unit", latest.semantic.get("unit", ""))
                        item.setdefault("semantic_type", latest.semantic.get("semantic_type", "OBSERVED"))
                        item.setdefault("scope", dict(latest.scope))
            else:
                params.setdefault("source_note", latest.provenance.source or "query result")
                params.setdefault("analysis_scope", dict(latest.scope))
                params.setdefault("semantic", dict(latest.semantic))
        reason = chart_skip_reason(self._active_user_text, name, params)
        if reason:
            return skipped_chart_output(reason), True
        try:
            # Gate network-facing tools with the turn's cancel event so a
            # reset/restore/disconnect aborts a Doris/ontology wait promptly.
            ctx = turn_ctx if turn_ctx is not None else getattr(self, "_turn_ctx", None)
            set_current_cancel(ctx.cancel if ctx is not None else None)
            executor = self._tool_executors.get(name)
            if executor is not None:
                return executor(params, self.cwd), False
            return execute_tool(name, params, self.cwd), False
        except ResourceCancelled:
            raise
        except Exception as exc:
            return f"Error executing {name}: {exc}", False

    def _display_resolver(self) -> "Callable[[str], Optional[str]]":
        """Build a code → trusted business-name resolver for this session.

        Name sources, in priority order:

        1. The latest query result's structured metadata (Ontology-MetricQuery
           now carries ``metrics``/``dimensions_meta`` and
           ``metric_names``/``dimension_names``).
        2. Ontology entities already seen this session (``ontology_seen``).
        3. The local ontology store.

        A name is only used when it is a valid, non-code text; anything else
        resolves to ``None`` so the original code is preserved (never guessed).
        """
        mapping: dict[str, str] = {}

        if self.query_results:
            latest = self.query_results[-1]
            scope = latest.scope or {}
            semantic = latest.semantic or {}
            for item in scope.get("metrics") or []:
                if isinstance(item, dict) and item.get("code"):
                    code = str(item["code"])
                    name = str(item.get("display_name") or "").strip()
                    if name and name != code:
                        mapping[code] = name
            for item in scope.get("dimensions_meta") or []:
                if isinstance(item, dict) and item.get("code"):
                    code = str(item["code"])
                    name = str(item.get("display_name") or "").strip()
                    if name and name != code:
                        mapping[code] = name
            for key in ("metric_names", "dimension_names"):
                names = semantic.get(key) or scope.get(key) or {}
                if isinstance(names, dict):
                    for code, name in names.items():
                        text = str(name or "").strip()
                        if text and text != str(code):
                            mapping.setdefault(str(code), text)

        for record in self.ontology_seen.values():
            code = str(record.get("code") or "")
            name = str(record.get("name") or "").strip()
            if code and name and name != code:
                mapping.setdefault(code, name)

        def resolve(code: str) -> Optional[str]:
            if not looks_like_code(code):
                return None
            name = mapping.get(code)
            if is_valid_name(name) and str(name) != str(code):
                return str(name)
            # Local-store fallback only for local ontology sessions; remote
            # codes are never resolved against the unrelated local workbook.
            if self.ontology_backend not in {"remote", "production"}:
                entity, _ = self._lookup(code)
                if entity is not None:
                    candidate = (
                        getattr(entity, "name", None)
                        or getattr(entity, "label", None)
                        or ""
                    )
                    if is_valid_name(candidate) and str(candidate) != code:
                        return str(candidate)
            return None

        return resolve

    def _emit_assistant_iteration(
        self,
        iteration: int,
        stop_reason: str,
        text_buffer: str,
        tool_uses: list[dict[str, Any]],
        thinking_blocks: list[dict[str, Any]],
        usage: dict[str, Any],
        turn_ctx: Optional[TurnContext] = None,
    ) -> Generator[dict[str, Any], None, None]:
        """Emit the ``llm_response`` event and persist this iteration's
        assistant turn to the conversation history.

        Used for tool-bearing iterations and for claim-validated final
        narratives; never called for rejected/discarded candidate drafts so
        those can neither reach the browser nor enter history.
        """
        if self._turn_superseded(turn_ctx):
            return False

        # A no-tool response is this turn's final delivery candidate (the
        # main loop breaks after committing it).  Step 05 (根因分析) is emitted
        # only when the final narrative really contains a root-cause section;
        # plain L1/L2 取数与异常定位 never enter step 05.
        if text_buffer and not tool_uses:
            if has_root_cause_section(text_buffer):
                yield self._sop_event(SOP_STEP_ROOTCAUSE, "根因证据链组装")
            yield self._sop_event(SOP_STEP_DECISION, "组装最终报告")

        yield {
            "type": "llm_response",
            "iteration": iteration,
            "text": text_buffer,
            "tool_uses": [
                {"id": tu["id"], "name": tu["name"], "input": tu["input"]}
                for tu in tool_uses
            ],
            "stop_reason": stop_reason,
            "usage": usage,
        }

        # Persist assistant turn to history. Thinking blocks must come
        # FIRST — Anthropic requires the trace at the head of content
        # blocks when extended thinking is enabled, and DeepSeek's
        # OpenAI-style translator just reads the field regardless of
        # position so the ordering is harmless either way.
        content: list[dict[str, Any]] = []
        content.extend(thinking_blocks)
        if text_buffer:
            content.append({"type": "text", "text": text_buffer})
        content.extend(tool_uses)
        if content:
            return self._commit_messages(content, turn_ctx)
        return True

    def _stream_one_response(
        self,
        iteration: int,
        defer_text: bool = False,
        turn_ctx: Optional[TurnContext] = None,
    ):
        """Consume one LLM stream; yield per-delta events; return summary.

        When ``defer_text`` is True the text deltas are accumulated into the
        returned ``text_buffer`` but are NOT forwarded to the browser. The
        caller decides whether the buffered candidate passes validation and,
        if so, replays it as visible ``text_delta`` events.

        If the gateway rejects the request because the selected model does
        not support the DeepSeek-only ``thinking`` parameter, the current
        LLM request is retried once with thinking disabled.  The retry
        never re-runs tool calls or restarts the turn; any other provider
        error is surfaced unchanged.
        """
        cfg = get_llm_config()
        active_model_key = self._active_model_key()
        current_model_id = get_model_id(active_model_key)
        active_model = get_model(active_model_key) or {}
        active_supports_thinking = bool(active_model.get("supports_thinking", False))

        # Do not start a model call for a turn that was already superseded.
        if self._turn_superseded(turn_ctx):
            return "superseded", "", [], {}, []

        # Only retry when the current request actually carried the
        # DeepSeek-only thinking parameter; a plain [False] attempt list
        # means the active model never sends it, so there is nothing to fix.
        attempts = [True, False] if cfg.effective_thinking else [False]
        for attempt, thinking in enumerate(attempts):
            text_buffer = ""
            tool_uses: list[dict[str, Any]] = []
            thinking_blocks: list[dict[str, Any]] = []
            stop_reason = "end_turn"
            usage: dict[str, Any] = {}
            retry_without_thinking = False
            # Visible-thinking requests carry an explicit Chinese constraint
            # for the user-facing thinking summary; it is injected only when
            # the user enabled thinking AND the active model actually
            # advertises thinking support.
            request_system_prompt = self.system_prompt
            if thinking and active_supports_thinking:
                request_system_prompt = (
                    request_system_prompt.rstrip()
                    + "\n\n"
                    + VISIBLE_THINKING_CN_RULE
                )

            try:
                for event in stream_message(
                    self.messages,
                    request_system_prompt,
                    allowed_tools=self.allowed_tools,
                    model_key=active_model_key,
                    max_tokens=cfg.max_tokens,
                    temperature=cfg.temperature,
                    thinking=thinking,
                    cancel_event=(turn_ctx.cancel if turn_ctx is not None else None),
                ):
                    etype = event["type"]
                    if etype == "text_delta":
                        text_buffer += event["text"]
                        if not defer_text:
                            yield {"type": "text_delta", "text": event["text"]}
                    elif etype == "thinking_delta":
                        # Surface the streaming reasoning trace to the
                        # inspector only when this request actually ran with
                        # visible thinking enabled.  A stray reasoning event
                        # while thinking is disabled is never forwarded.
                        if thinking:
                            yield {"type": "thinking_delta", "text": event.get("text", "")}
                    elif etype == "thinking_block":
                        # End-of-block snapshot — keep it so the assistant message
                        # in self.messages can round-trip the trace on the next
                        # tool turn (DeepSeek API rejects requests otherwise; for
                        # Anthropic the signature is the gating field).
                        blk = {"type": "thinking", "thinking": event.get("text", "")}
                        sig = event.get("signature")
                        if sig:
                            blk["signature"] = sig
                        thinking_blocks.append(blk)
                    elif etype == "tool_use_start":
                        yield {"type": "tool_start", "id": event["id"], "name": event["name"]}
                    elif etype == "tool_use_end":
                        tu = {
                            "type": "tool_use",
                            "id": event["id"],
                            "name": event["name"],
                            "input": event["input"],
                        }
                        tool_uses.append(tu)
                        yield {
                            "type": "tool_input",
                            "id": event["id"],
                            "name": event["name"],
                            "input": event["input"],
                        }
                    elif etype == "message_end":
                        stop_reason = event.get("stop_reason", "end_turn")
                        usage = event.get("usage", {})
                        self.cost_tracker.add_usage(
                            current_model_id,
                            input_tokens=usage.get("input_tokens", 0),
                            output_tokens=usage.get("output_tokens", 0),
                        )
                    elif etype == "model_fallback":
                        # The automatic fallback applies only to the current
                        # turn: later tool iterations in this turn reuse it,
                        # but the saved user model choice is never modified
                        # and the next user turn restarts on the original.
                        fallback_key = event.get("model_key")
                        if fallback_key:
                            self._turn_fallback_model_key = fallback_key
                            yield {
                                "type": "status",
                                "message": (
                                    f"当前模型额度不足，本次请求已临时切换到 "
                                    f"{get_model_id(fallback_key)}"
                                ),
                            }
                    elif etype == "error":
                        if thinking and _is_thinking_param_error(event["error"]):
                            retry_without_thinking = True
                            break
                        yield {"type": "error", "message": event["error"]}
                        return "error", text_buffer, tool_uses, usage, thinking_blocks

            except ResourceCancelled:
                # The turn was cancelled while waiting for the LLM slot:
                # no token was acquired, nothing to commit — surface the
                # superseded event instead of an error.
                return "superseded", text_buffer, tool_uses, usage, thinking_blocks

            if not retry_without_thinking:
                return stop_reason, text_buffer, tool_uses, usage, thinking_blocks
            logger.info(
                "provider retry: model %s rejected unsupported 'thinking' parameter; "
                "retrying the current LLM request once without thinking",
                current_model_id,
            )

        yield {"type": "error", "message": "Team API request failed: unsupported 'thinking' parameter"}
        return "error", text_buffer, tool_uses, usage, thinking_blocks

    def _snapshot_messages(self) -> list[dict[str, Any]]:
        """Return a lightweight JSON-safe view of the current message list."""
        out: list[dict[str, Any]] = []
        for msg in self.messages:
            role = msg.get("role")
            content = msg.get("content")
            if isinstance(content, str):
                out.append({"role": role, "content": content})
                continue
            blocks: list[dict[str, Any]] = []
            for blk in content or []:
                btype = blk.get("type")
                if btype == "text":
                    blocks.append({"type": "text", "text": blk.get("text", "")})
                elif btype == "thinking":
                    raw_t = blk.get("thinking", "") or ""
                    preview_t = raw_t if len(raw_t) <= 2000 else raw_t[:2000] + f"\n... [+{len(raw_t)-2000} chars]"
                    blocks.append({"type": "thinking", "text_preview": preview_t})
                elif btype == "tool_use":
                    blocks.append({
                        "type": "tool_use",
                        "id": blk.get("id"),
                        "name": blk.get("name"),
                        "input": blk.get("input"),
                    })
                elif btype == "tool_result":
                    raw = blk.get("content", "")
                    if isinstance(raw, list):  # Claude API list-of-blocks form
                        raw = "".join(b.get("text", "") for b in raw if isinstance(b, dict))
                    text = str(raw)
                    preview = text if len(text) <= 2000 else text[:2000] + f"\n... [+{len(text)-2000} chars]"
                    blocks.append({
                        "type": "tool_result",
                        "tool_use_id": blk.get("tool_use_id"),
                        "content_preview": preview,
                    })
                else:
                    blocks.append({"type": btype or "unknown"})
            out.append({"role": role, "content": blocks})
        return out

    def _extract_entities(
        self, text: str, tool_name: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Extract entities from ontology tools using the active source.

        The remote and local repositories intentionally keep separate code
        namespaces.  When remote mode is active, a remote ``[CODE] label
        (Type)`` line must win even if the local fallback workbook contains
        the same code.  SQL/chart/table output is excluded from the inspector
        because a source-note reference is not an ontology hit.
        """
        ontology_tools = {
            "Ontology-SemanticQuery", "Ontology-TermDisambiguate", "MetricCalculation", "Ontology-RelationQuery",
            "Ontology-EntityDescribe", "ListBusinessObjects", "Ontology-GraphContext", "Ontology-GraphExpand",
        }
        if tool_name is not None and tool_name not in ontology_tools:
            return []
        raw_text = text or ""
        codes = set(ENTITY_CODE_RE.findall(raw_text))
        remote_lines = {
            match.group("code"): {
                "label": match.group("label").strip(),
                "type": (match.group("type") or "").strip(),
                "display": match.group(0).strip(),
            }
            for match in REMOTE_ENTITY_LINE_RE.finditer(raw_text)
        }
        results: list[dict[str, Any]] = []
        for code in codes:
            remote = remote_lines.get(code)
            source = "remote" if self.ontology_backend in {"remote", "production"} else "local"
            # Remote output is authoritative in production mode.  Do not
            # enrich it with a same-code local fallback object: code values
            # are only unique inside one ontology repository.
            if source == "remote" and remote is not None:
                kind = self._kind_from_code(code, remote["type"])
                record = {
                    "code": code,
                    "kind": kind,
                    "name": remote["label"] or code,
                    "display": remote["display"],
                    "source": source,
                    "repository_id": self.ontology_repository_id,
                }
            elif source == "remote":
                # A remote ontology tool result without a structured entity
                # line is not safe to resolve against the unrelated local
                # workbook, so leave it out rather than displaying a false hit.
                continue
            else:
                entity, kind = self._lookup(code)
                if entity is None:
                    remote = remote_lines.get(code)
                if entity is not None:
                    record = {
                        "code": code,
                        "kind": kind,
                        "name": getattr(entity, "name", None) or code,
                        "display": entity.to_prompt(),
                        "source": source,
                        "repository_id": "",
                    }
                elif remote is not None:
                    record = {
                        "code": code,
                        "kind": self._kind_from_code(code, remote["type"]),
                        "name": remote["label"] or code,
                        "display": remote["display"],
                        "source": source,
                        "repository_id": "",
                    }
                else:
                    continue
            record["entity_key"] = ":".join(
                filter(None, [record["source"], record["repository_id"], record["kind"], code])
            )
            results.append(record)
            if record["entity_key"] not in self.ontology_seen:
                self.ontology_seen[record["entity_key"]] = record
        results.sort(key=lambda r: r["code"])
        return results

    @staticmethod
    def _kind_from_code(code: str, remote_type: str = "") -> str:
        """Normalize remote type names to the frontend's entity categories."""
        type_key = (remote_type or "").lower().replace("_", "")
        type_map = {
            "businessobject": "business_object",
            "logicalentity": "logical_entity",
            "businessattribute": "attribute",
            "entityrelation": "relation",
            "indicator": "metric",
            "metric": "metric",
            "term": "term",
            "dimension": "dimension",
            "activity": "activity",
            "rule": "rule",
            "businessrule": "rule",
            "process": "process",
            "metarelation": "meta_relation",
            "tablenode": "table_node",
            "column": "column",
        }
        if type_key in type_map:
            return type_map[type_key]
        prefix = re.match(r"[A-Z]+", code.upper())
        return {
            "BO": "business_object",
            "LE": "logical_entity",
            "AT": "attribute",
            "ER": "relation",
            "REL": "relation",
            "M": "metric",
            "MET": "metric",
            "T": "term",
            "TERM": "term",
            "D": "dimension",
            "DIM": "dimension",
            "A": "activity",
            "ACT": "activity",
            "R": "rule",
            "RULE": "rule",
            "SSP": "process",
            "MREL": "meta_relation",
        }.get(prefix.group(0) if prefix else "", "ontology")

    def _lookup(self, code: str):
        store = self.ontology_store
        if code in store.metrics:
            return store.metrics[code], "metric"
        if code in store.business_objects:
            return store.business_objects[code], "business_object"
        if code in store.logical_entities:
            return store.logical_entities[code], "logical_entity"
        if code in store.attributes:
            return store.attributes[code], "attribute"
        if code in store.relations:
            return store.relations[code], "relation"
        if code in store.terms:
            return store.terms[code], "term"
        if code in store.activities:
            return store.activities[code], "activity"
        if code in store.rules:
            return store.rules[code], "rule"
        if code in store.dimensions:
            return store.dimensions[code], "dimension"
        if code in store.processes:
            return store.processes[code], "process"
        if code in store.meta_relations:
            return store.meta_relations[code], "meta_relation"
        return None, None
