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
    has_action_section,
    has_root_cause_section,
)
from open_claude.skills.bundled import init_bundled_skills
from open_claude.skills.registry import load_skills
from open_claude.tokens import CostTracker
from open_claude.tools import execute_tool

from ..llm.provider import get_model_id, stream_message
from ..llm.runtime_config import get_config as get_llm_config
from ..ontology.store import OntologyStore
from ..tools.ask_user import ASK_USER_TOOL_NAME
from ..tools.chart_multidim_tools import extract_multidim_chart_spec
from ..tools.chart_policy import chart_skip_reason, skipped_chart_output
from ..tools.chart_tools import extract_chart_spec
from ..tools.table_tools import extract_table_spec
from ..tools.todo_tools import extract_todo_spec


logger = logging.getLogger(__name__)


def _is_thinking_param_error(message: str) -> bool:
    """True when the gateway rejected the request because the model does
    not support the DeepSeek-only ``thinking`` parameter (LiteLLM's
    UnsupportedParamsError)."""
    lower = str(message or "").lower()
    return "unsupportedparams" in lower and "thinking" in lower
from ..reliability import (
    AnalysisContext, Association, Claim, ClaimLevel, LimitationType, Provenance,
    QueryResult, RelationType, ValidationStatus, association_claim,
    claims_from_query_result, detect_conflicts, enrich_query_result,
    reconcile_query_results, relation_evidence_status, render_narrative, validate_claims,
)

# Only real data queries may become later data sources, reconciliation
# candidates or claim inputs.  Display/metadata/utility tools are consumed by
# the UI or the LLM but must never feed back into the analysis state.
DATA_QUERY_TOOLS = frozenset({"SQLRun", "MetricDataQuery"})
# Relation/context tools contribute an Association claim only when their
# output carries explicit edge/path evidence.
RELATION_TOOLS = frozenset({"RelationLookup", "GraphContext", "GraphExpand"})


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
DATA_FETCH_TOOLS = {"SQLRun", "MetricDataQuery"}

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
        self._active_user_text = str(user_text or "")
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

    def _run_loop(self) -> Generator[dict[str, Any], None, None]:
        stop_reason = "end_turn"
        # Per-turn render-enforcement bookkeeping
        called_tools_this_turn: set[str] = set()
        text_concat_this_turn: str = ""
        enforced_render: bool = False
        enforced_action: bool = False
        enforced_answer_validation: bool = False
        claim_context_sent: bool = False
        root_cause_seen = False
        action_seen = False

        for iteration in range(self.max_iterations):
            yield {"type": "iteration_start", "iteration": iteration}

            cfg = get_llm_config()
            current_model_id = get_model_id(cfg.model_key)

            yield {
                "type": "llm_request",
                "iteration": iteration,
                "model": current_model_id,
                "model_key": cfg.model_key,
                "max_tokens": cfg.max_tokens,
                "temperature": cfg.temperature,
                "message_count": len(self.messages),
                "messages_snapshot": self._snapshot_messages(),
            }

            stop_reason, text_buffer, tool_uses, usage, thinking_blocks = (
                yield from self._stream_one_response(iteration)
            )

            # A provider error already emitted an SSE error event. Do not
            # append a partial assistant message or emit `done`, otherwise the
            # browser saves an incomplete turn as if it completed normally.
            if stop_reason == "error":
                return

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
                self.messages.append({"role": "assistant", "content": content})

            # Track this iteration's tool calls + text for render enforcement
            for tu in tool_uses:
                called_tools_this_turn.add(tu["name"])
            if text_buffer:
                text_concat_this_turn += "\n" + text_buffer
                root_cause_seen = root_cause_seen or has_root_cause_section(text_buffer)
                action_seen = action_seen or has_action_section(text_buffer)

            if stop_reason != "tool_use" or not tool_uses:
                # ---- Render enforcement ------------------------------------
                # Trigger when the agent fetched data (SQLRun) or wrote a
                # Markdown table into the chat, but never called any of the
                # rendering tools. Inject one corrective user message and
                # re-prompt; only fires once per turn to avoid loops.
                allowed = set(self.allowed_tools or [])
                has_render_tool_available = bool(allowed & RENDER_TOOLS)
                fetched_data = bool(called_tools_this_turn & DATA_FETCH_TOOLS)
                wrote_md_table = _has_markdown_table(text_concat_this_turn)
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
                        reasons.append("已经执行了 `SQLRun` 取数")
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

                # A root-cause answer without an action section is always
                # incomplete. This is an output invariant, not an intent gate:
                # even if the model over-produces root cause for an L1/L2
                # question, the response must not finish with root cause alone.
                if (
                    not enforced_action
                    and root_cause_seen
                    and not action_seen
                ):
                    enforced_action = True
                    reminder = (
                        "本轮回复已经出现根因章节,但还没有行动章节,不能结束本轮。"
                        "请基于本轮已经验证的根因证据,继续补充一个纯文字标题为‘行动建议’或‘建议雏形’的小节。"
                        "至少给出 1–2 条具体动作,每条都要对应具体根因切片和数据证据;"
                        "不要重复根因分析,不要写‘加强管理’等空泛表述,不要声称动作已经执行,不要使用表情符号。"
                    )
                    self.messages.append({"role": "user", "content": reminder, "internal": True})
                    continue

                if self.claims:
                    if not claim_context_sent:
                        claim_context_sent = True
                        claim_lines = "\n".join(
                            f"- [{claim.level.value}] {claim.statement}"
                            + (f"（限制：{'、'.join(str(x.value if hasattr(x, 'value') else x) for x in claim.limitations)}）" if claim.limitations else "")
                            for claim in self.claims
                        )
                        reminder = (
                            "以下是本轮由工具结果生成的 Structured Claims。最终回答必须只基于这些 Claims，"
                            "数字、范围和语义不得超出它们；ASSOCIATION/INFERENCE 不得写成已验证因果；"
                            "存在限制或冲突时必须明确披露。请据此重新生成最终 Narrative。\n"
                            + claim_lines
                            + "\n\n结构化 Claim 渲染参考：\n"
                            + render_narrative(self.claims)
                        )
                        self.messages.append({"role": "user", "content": reminder, "internal": True})
                        yield {"type": "claim_context", "claims": [claim.id for claim in self.claims]}
                        continue
                    validation = validate_claims(self.claims, text_concat_this_turn)
                    if validation.status == ValidationStatus.REJECT:
                        if enforced_answer_validation:
                            yield {
                                "type": "answer_blocked",
                                "status": "blocked",
                                "issues": list(validation.issues),
                                "message": "最终回答被阻止：结构化 Claims 不支持该确定性叙述。",
                            }
                            return
                        enforced_answer_validation = True
                        reminder = (
                            "最终回答未通过结构化 Claim 校验。请重新生成叙述："
                            + "；".join(validation.issues)
                            + "。只能使用已有 Claim，保持其 FACT/ASSOCIATION/INFERENCE/VERIFIED 等级，"
                              "披露冲突和限制，不要添加未经支持的数字或因果结论。"
                        )
                        self.messages.append({"role": "user", "content": reminder, "internal": True})
                        yield {"type": "answer_validation", "status": "rejected", "issues": list(validation.issues)}
                        continue

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
                    t0 = time.time()
                    output, chart_was_suppressed = self._execute_tool(tu)
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
                t0 = time.time()
                output, chart_was_suppressed = self._execute_tool(tu)
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

        yield {"type": "done", "stop_reason": stop_reason}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _execute_tool(self, tool_use: dict[str, Any]) -> tuple[str, bool]:
        """Execute a tool, applying the deterministic chart usefulness guard."""

        name = str(tool_use.get("name") or "")
        params = tool_use.get("input")
        if not isinstance(params, dict):
            params = {}
        else:
            params = dict(params)
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
            executor = self._tool_executors.get(name)
            if executor is not None:
                return executor(params, self.cwd), False
            return execute_tool(name, params, self.cwd), False
        except Exception as exc:
            return f"Error executing {name}: {exc}", False

    def _stream_one_response(self, iteration: int):
        """Consume one LLM stream; yield per-delta events; return summary.

        If the gateway rejects the request because the selected model does
        not support the DeepSeek-only ``thinking`` parameter, the current
        LLM request is retried once with thinking disabled.  The retry
        never re-runs tool calls or restarts the turn; any other provider
        error is surfaced unchanged.
        """
        cfg = get_llm_config()
        current_model_id = get_model_id(cfg.model_key)

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

            for event in stream_message(
                self.messages,
                self.system_prompt,
                allowed_tools=self.allowed_tools,
                model_key=cfg.model_key,
                max_tokens=cfg.max_tokens,
                temperature=cfg.temperature,
                thinking=thinking,
            ):
                etype = event["type"]
                if etype == "text_delta":
                    text_buffer += event["text"]
                    yield {"type": "text_delta", "text": event["text"]}
                elif etype == "thinking_delta":
                    # Surface the streaming reasoning trace to the inspector.
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
                    # Persist the working fallback so subsequent turns start
                    # directly on it instead of retrying an exhausted model.
                    fallback_key = event.get("model_key")
                    if fallback_key:
                        try:
                            get_llm_config().update(model_key=fallback_key)
                        except Exception:
                            pass
                        yield {
                            "type": "status",
                            "message": f"当前模型额度不足，已自动切换到 {get_model_id(fallback_key)}",
                        }
                elif etype == "error":
                    if thinking and _is_thinking_param_error(event["error"]):
                        retry_without_thinking = True
                        break
                    yield {"type": "error", "message": event["error"]}
                    return "error", text_buffer, tool_uses, usage, thinking_blocks

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
            "OntologyQuery", "TermDisambiguate", "MetricLookup", "RelationLookup",
            "EntityDescribe", "ListBusinessObjects", "GraphContext", "GraphExpand",
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
