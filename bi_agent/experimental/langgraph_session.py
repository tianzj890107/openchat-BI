"""Opt-in LangGraph turn loop for the analysis agent.

This module deliberately subclasses :class:`bi_agent.web.session.WebSession`
instead of modifying it.  The legacy loop remains the default; only
``_run_loop`` is replaced.  Every model call, tool call, recovery transition and
SSE event still goes through the production WebSession helpers, so the
experiment cannot bypass the existing tool boundary or data-source isolation.

The graph is intentionally a *control-plane* graph.  Conversation messages,
Claims, query results, the Tool Runtime ledger and the Recovery state continue
to live in the WebSession, which keeps conversation restore and the existing
tests compatible.
"""

from __future__ import annotations

import logging
from typing import Any, Generator, Optional, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

import bi_agent.web.session as session_module
from bi_agent.llm.provider import get_model_id
from bi_agent.llm.runtime_config import get_config as get_llm_config
from bi_agent.reliability import ValidationStatus, soften_evidence_language
from bi_agent.tools.analysis_policy import (
    extract_action_items,
    has_effective_action,
    has_root_cause_section,
    split_action_item,
)
from bi_agent.tools.ask_user import ASK_USER_TOOL_NAME
from bi_agent.web.session import (
    FORECAST_LIMITATION_NOTE,
    SOP_STEP_DECISION,
    WebSession,
    _RECOVERY_STOP_STATUSES,
    forecast_disclosure_missing,
)

logger = logging.getLogger(__name__)


class LangGraphTurnState(TypedDict, total=False):
    """Serializable control state for one analysis turn.

    Conversation content deliberately stays on the WebSession; this state only
    records loop position and gate decisions.
    """

    iteration: int
    route: str
    stop_reason: str
    text_buffer: str
    tool_uses: list[dict[str, Any]]
    thinking_blocks: list[dict[str, Any]]
    usage: dict[str, Any]
    defer_text: bool
    called_tools: list[str]
    text_concat: str
    enforced_render: bool
    enforced_answer_validation: bool
    root_cause_seen: bool
    delivery_blocked: bool
    action_blocked: bool
    action_repairs: int


def _emit(event: dict[str, Any]) -> None:
    """Emit one custom-stream event from inside a LangGraph node."""
    writer = get_stream_writer()
    writer(event)


def _drain(generator: Generator[dict[str, Any], None, Any], sink) -> Any:
    """Consume a production WebSession generator while forwarding its events.

    Python does not expose a generator's return value through ``for``, so the
    loop uses ``next()`` and returns ``StopIteration.value``.  This is what lets
    the graph reuse ``_stream_one_response`` and ``_run_tool_and_emit`` without
    duplicating their event ordering.
    """

    while True:
        try:
            event = next(generator)
        except StopIteration as stop:
            return stop.value
        sink(event)


class LangGraphWebSession(WebSession):
    """WebSession variant whose turn control plane runs on LangGraph.

    Public API is inherited unchanged: ``generate_turn``, ``continue_with_choice``,
    ``retry_from_checkpoint``, recovery snapshots and conversation messages all
    keep their existing contracts.
    """

    def _run_loop(self) -> Generator[dict[str, Any], None, None]:
        turn_ctx = getattr(self, "_turn_ctx", None)
        initial: LangGraphTurnState = {
            "iteration": 0,
            "route": "llm",
            "stop_reason": "end_turn",
            "text_buffer": "",
            "tool_uses": [],
            "thinking_blocks": [],
            "usage": {},
            "defer_text": False,
            "called_tools": [],
            "text_concat": "",
            "enforced_render": False,
            "enforced_answer_validation": False,
            "root_cause_seen": False,
            "delivery_blocked": False,
            "action_blocked": False,
            "action_repairs": 0,
        }
        graph = self._build_graph(turn_ctx)
        # LangGraph counts node visits for recursion protection.  A normal turn
        # uses at most two nodes per model/tool iteration, plus the final gate.
        config = {"recursion_limit": max(30, self.max_iterations * 5 + 20)}
        for event in graph.stream(initial, stream_mode="custom", config=config):
            if isinstance(event, dict):
                yield event

    def _build_graph(self, turn_ctx):
        workflow = StateGraph(LangGraphTurnState)

        def begin_iteration(state: LangGraphTurnState) -> LangGraphTurnState:
            iteration = int(state.get("iteration") or 0)
            if self._turn_superseded(turn_ctx):
                _emit({"type": "session_superseded"})
                return {"route": "stop"}
            if iteration >= self.max_iterations:
                return {"route": "finalize"}
            _emit({"type": "iteration_start", "iteration": iteration})
            cfg = get_llm_config()
            active_model_key = self._active_model_key()
            _emit({
                "type": "llm_request",
                "iteration": iteration,
                "model": get_model_id(active_model_key),
                "model_key": active_model_key,
                "max_tokens": cfg.max_tokens,
                "temperature": cfg.temperature,
                "message_count": len(self.messages),
                "messages_snapshot": self._snapshot_messages(),
            })
            return {"route": "llm", "iteration": iteration}

        def llm_step(state: LangGraphTurnState) -> LangGraphTurnState:
            iteration = int(state.get("iteration") or 0)
            defer_text = bool(self.claims)
            result = _drain(
                self._stream_one_response(
                    iteration,
                    defer_text=defer_text,
                    turn_ctx=turn_ctx,
                ),
                _emit,
            )
            stop_reason, text_buffer, tool_uses, usage, thinking_blocks = result
            return {
                "stop_reason": stop_reason,
                "text_buffer": text_buffer,
                "tool_uses": list(tool_uses or []),
                "usage": usage or {},
                "thinking_blocks": list(thinking_blocks or []),
                "defer_text": defer_text,
            }

        def after_llm(state: LangGraphTurnState) -> LangGraphTurnState:
            iteration = int(state.get("iteration") or 0)
            stop_reason = str(state.get("stop_reason") or "end_turn")
            text_buffer = str(state.get("text_buffer") or "")
            tool_uses = list(state.get("tool_uses") or [])
            thinking_blocks = list(state.get("thinking_blocks") or [])
            usage = dict(state.get("usage") or {})
            called_tools = set(state.get("called_tools") or [])
            text_concat = str(state.get("text_concat") or "")
            root_cause_seen = bool(state.get("root_cause_seen"))
            enforced_render = bool(state.get("enforced_render"))
            enforced_answer_validation = bool(state.get("enforced_answer_validation"))

            if stop_reason == "error":
                return {"route": "stop"}
            if stop_reason == "superseded":
                _emit({"type": "session_superseded"})
                return {"route": "stop"}
            if self._turn_superseded(turn_ctx):
                _emit({"type": "session_superseded"})
                return {"route": "stop"}

            if state.get("defer_text") and tool_uses and text_buffer:
                _emit({"type": "text_delta", "text": text_buffer})

            candidate_pending = bool(self.claims) and not tool_uses
            if not candidate_pending:
                committed = _drain(
                    self._emit_assistant_iteration(
                        iteration,
                        stop_reason,
                        text_buffer,
                        tool_uses,
                        thinking_blocks,
                        usage,
                        turn_ctx,
                    ),
                    _emit,
                )
                if not committed:
                    _emit({"type": "session_superseded"})
                    return {"route": "stop"}
                called_tools.update(str(tu.get("name") or "") for tu in tool_uses)
                if text_buffer:
                    text_concat = f"{text_concat}\n{text_buffer}".strip()
                    root_cause_seen = root_cause_seen or has_root_cause_section(text_buffer)

            if stop_reason != "tool_use" or not tool_uses:
                allowed = set(self.allowed_tools or [])
                has_render_tool_available = bool(allowed & session_module.RENDER_TOOLS)
                fetched_data = bool(called_tools & session_module.DATA_FETCH_TOOLS)
                check_text = text_concat
                if text_buffer:
                    check_text = f"{check_text}\n{text_buffer}".strip()
                wrote_md_table = session_module._has_markdown_table(check_text)
                rendered = bool(called_tools & session_module.RENDER_TOOLS)
                table_rendered = (
                    "TableGenerate" in called_tools
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
                    _emit({
                        "type": "render_enforce",
                        "iteration": iteration,
                        "reasons": reasons,
                        "called_tools": sorted(called_tools),
                        "message": reminder,
                    })
                    return {
                        "route": "next_iteration",
                        "iteration": iteration + 1,
                        "enforced_render": True,
                        "called_tools": sorted(called_tools),
                        "text_concat": text_concat,
                        "root_cause_seen": root_cause_seen,
                    }

                if self.claims:
                    validation = None
                    try:
                        validation = session_module.validate_claims(self.claims, text_buffer or "")
                    except Exception as exc:
                        logger.exception("evidence validator failed")
                        _emit({
                            "type": "answer_validation",
                            "status": "warning",
                            "issues": [f"validator error: {type(exc).__name__}"],
                        })
                    if validation is not None and validation.status == ValidationStatus.ALLOW_WITH_WARNING:
                        original_text = text_buffer
                        text_buffer = soften_evidence_language(text_buffer or "", validation.findings)
                        _emit({
                            "type": "answer_validation",
                            "status": "warning",
                            "issues": list(validation.issues),
                            "adjusted": text_buffer != original_text,
                        })
                    if validation is not None and validation.status == ValidationStatus.REJECT:
                        if enforced_answer_validation:
                            fallback_text = self._blocked_answer_fallback(validation.issues)
                            _emit({
                                "type": "answer_blocked",
                                "status": "blocked",
                                "issues": list(validation.issues),
                                "message": "部分叙述未通过结构化证据校验，已改为展示安全兜底回答。",
                            })
                            _emit({"type": "text_delta", "text": fallback_text})
                            committed = _drain(
                                self._emit_assistant_iteration(
                                    iteration,
                                    "answer_blocked",
                                    fallback_text,
                                    [],
                                    [],
                                    usage,
                                    turn_ctx,
                                ),
                                _emit,
                            )
                            if not committed:
                                _emit({"type": "session_superseded"})
                                return {"route": "stop"}
                            return {
                                "route": "finalize",
                                "delivery_blocked": True,
                                "text_concat": f"{text_concat}\n{fallback_text}".strip(),
                            }
                        claim_lines = "\n".join(
                            f"- [{claim.level.value}] {claim.statement}"
                            + (
                                f"（限制：{'、'.join(str(x.value if hasattr(x, 'value') else x) for x in claim.limitations)}）"
                                if claim.limitations else ""
                            )
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
                        _emit({"type": "claim_context", "claims": [claim.id for claim in self.claims]})
                        _emit({"type": "answer_validation", "status": "rejected", "issues": list(validation.issues)})
                        return {
                            "route": "next_iteration",
                            "iteration": iteration + 1,
                            "enforced_answer_validation": True,
                            "called_tools": sorted(called_tools),
                            "text_concat": text_concat,
                            "root_cause_seen": root_cause_seen,
                        }

                if candidate_pending:
                    if text_buffer:
                        _emit({"type": "text_delta", "text": text_buffer})
                    committed = _drain(
                        self._emit_assistant_iteration(
                            iteration,
                            stop_reason,
                            text_buffer,
                            tool_uses,
                            thinking_blocks,
                            usage,
                            turn_ctx,
                        ),
                        _emit,
                    )
                    if not committed:
                        _emit({"type": "session_superseded"})
                        return {"route": "stop"}
                    called_tools.update(str(tu.get("name") or "") for tu in tool_uses)
                    if text_buffer:
                        text_concat = f"{text_concat}\n{text_buffer}".strip()
                        root_cause_seen = root_cause_seen or has_root_cause_section(text_buffer)

                return {
                    "route": "finalize",
                    "called_tools": sorted(called_tools),
                    "text_concat": text_concat,
                    "root_cause_seen": root_cause_seen,
                }

            ask_user = next(
                (tu for tu in tool_uses if tu.get("name") == ASK_USER_TOOL_NAME),
                None,
            )
            return {
                "route": "ask_user" if ask_user else "tools",
                "called_tools": sorted(called_tools),
                "text_concat": text_concat,
                "root_cause_seen": root_cause_seen,
            }

        def tool_step(state: LangGraphTurnState) -> LangGraphTurnState:
            iteration = int(state.get("iteration") or 0)
            tool_results: list[dict[str, Any]] = []
            for tool_use in list(state.get("tool_uses") or []):
                block = _drain(self._run_tool_and_emit(tool_use, turn_ctx), _emit)
                if block is None:
                    _emit({"type": "session_superseded"})
                    return {"route": "stop"}
                tool_results.append(block)
                if self.recovery.status() in _RECOVERY_STOP_STATUSES:
                    return {"route": "stop"}
            self.messages.append({"role": "user", "content": tool_results})
            return {"route": "next_iteration", "iteration": iteration + 1}

        def ask_user_step(state: LangGraphTurnState) -> LangGraphTurnState:
            tool_uses = list(state.get("tool_uses") or [])
            ask_user = next(
                (tu for tu in tool_uses if tu.get("name") == ASK_USER_TOOL_NAME),
                None,
            )
            if ask_user is None:
                return {"route": "finalize"}
            sibling_results: list[dict[str, Any]] = []
            for tool_use in tool_uses:
                if tool_use.get("id") == ask_user.get("id"):
                    continue
                block = _drain(self._run_tool_and_emit(tool_use, turn_ctx), _emit)
                if block is None:
                    self._pending_sibling_results = []
                    self.pending_tool_use_id = None
                    self.pending_choice_spec = None
                    _emit({"type": "session_superseded"})
                    return {"route": "stop"}
                sibling_results.append(block)
                if self.recovery.status() in _RECOVERY_STOP_STATUSES:
                    self._pending_sibling_results = []
                    self.pending_tool_use_id = None
                    self.pending_choice_spec = None
                    return {"route": "stop"}
            self._pending_sibling_results = sibling_results

            spec = dict(ask_user.get("input") or {})
            self.pending_tool_use_id = str(ask_user.get("id") or "")
            self.pending_choice_spec = spec
            waiting = self.recovery.ask_user(
                self.pending_tool_use_id,
                spec.get("question", ""),
                spec.get("options", []),
            )
            if waiting is not None:
                _emit(self._recovery_event(waiting))
            _drain(self._sop_for_tool(ASK_USER_TOOL_NAME, spec), _emit)
            _emit({
                "type": "user_choice_requested",
                "tool_use_id": self.pending_tool_use_id,
                "question": spec.get("question", "请选择"),
                "options": spec.get("options", []),
                "context": spec.get("context", ""),
            })
            _emit({"type": "awaiting_user_choice"})
            return {"route": "awaiting"}

        def finalize_step(state: LangGraphTurnState) -> LangGraphTurnState:
            text_concat = str(state.get("text_concat") or "")
            called_tools = set(state.get("called_tools") or [])
            root_cause_seen = bool(state.get("root_cause_seen"))
            usage = dict(state.get("usage") or {})

            if not text_concat.strip():
                fallback_text = self._no_narrative_fallback(called_tools)
                _emit({"type": "text_delta", "text": fallback_text})
                committed = _drain(
                    self._emit_assistant_iteration(
                        self.max_iterations,
                        "max_iterations",
                        fallback_text,
                        [],
                        [],
                        {},
                        turn_ctx,
                    ),
                    _emit,
                )
                if not committed:
                    _emit({"type": "session_superseded"})
                    return {"route": "stop"}
                text_concat = fallback_text

            action_repairs = int(state.get("action_repairs") or 0)
            action_blocked = False
            action_needed = bool(self._turn_wants_action or root_cause_seen)
            if action_needed and not has_effective_action(text_concat):
                for _ in range(2):
                    if self._turn_superseded(turn_ctx):
                        _emit({"type": "session_superseded"})
                        return {"route": "stop"}
                    action_repairs += 1
                    if action_repairs == 1:
                        if root_cause_seen:
                            reminder = (
                                "本轮回复已经出现根因章节,但还没有有效行动建议,不能结束本轮。"
                                "请基于本轮已经验证的根因证据,继续补充一个标题为‘行动建议’"
                                "(或‘管理建议’‘决策建议’‘下一步行动’等)的小节,给出 1–2 条具体动作;"
                                "每条都要有明确动作对象和执行方式,不要写‘加强管理’‘持续关注’等空话,"
                                "不要声称动作已经执行,不要重复根因分析,不要使用表情符号。"
                            )
                        else:
                            reminder = (
                                "用户明确要求给出行动建议,但本轮回复还没有有效行动建议,"
                                "不能结束本轮。请基于本轮已经查询到的证据,补充一个标题为"
                                "‘行动建议’(或‘管理建议’‘决策建议’‘下一步行动’等)的小节,"
                                "给出 1–2 条具体动作;每条都要有明确动作对象和执行方式,"
                                "不要写‘加强管理’‘持续关注’等空话,不要声称动作已经执行,"
                                "不要重复已经给出的结论,不要使用表情符号。"
                            )
                    else:
                        reminder = (
                            "上一轮补写仍然没有有效行动建议。请只补充行动建议文本:"
                            "标题为‘行动建议’(或‘管理建议’‘决策建议’‘下一步行动’等),"
                            "给出 1–2 条可执行的具体动作并对应本轮已经验证的证据;"
                            "不要调用任何工具,不要重新执行已经完成的取数、图表或表格。"
                        )
                    self.messages.append({"role": "user", "content": reminder, "internal": True})
                    _emit({
                        "type": "action_repair",
                        "attempt": action_repairs,
                        "message": reminder,
                    })
                    repair_iteration = self.max_iterations + action_repairs
                    cfg = get_llm_config()
                    active_model_key = self._active_model_key()
                    _emit({
                        "type": "llm_request",
                        "iteration": repair_iteration,
                        "model": get_model_id(active_model_key),
                        "model_key": active_model_key,
                        "max_tokens": cfg.max_tokens,
                        "temperature": cfg.temperature,
                        "message_count": len(self.messages),
                        "messages_snapshot": self._snapshot_messages(),
                    })
                    result = _drain(
                        self._stream_one_response(repair_iteration, turn_ctx=turn_ctx),
                        _emit,
                    )
                    repair_stop, repair_text, repair_tools, repair_usage, repair_thinking = result
                    if repair_stop == "error":
                        return {"route": "stop"}
                    if repair_stop == "superseded" or self._turn_superseded(turn_ctx):
                        _emit({"type": "session_superseded"})
                        return {"route": "stop"}
                    if repair_tools:
                        logger.warning(
                            "action_repair tool_uses dropped turn=%s tools=%s",
                            self._user_turn_count,
                            ",".join(sorted({str(tu.get("name", "?")) for tu in repair_tools})),
                        )
                    _emit({
                        "type": "llm_response",
                        "iteration": repair_iteration,
                        "text": repair_text,
                        "tool_uses": [],
                        "stop_reason": repair_stop,
                        "usage": repair_usage,
                    })
                    repair_content: list[dict[str, Any]] = []
                    repair_content.extend(repair_thinking)
                    if repair_text:
                        repair_content.append({"type": "text", "text": repair_text})
                    if repair_content and not self._commit_messages(repair_content, turn_ctx):
                        _emit({"type": "session_superseded"})
                        return {"route": "stop"}
                    if repair_text:
                        text_concat = f"{text_concat}\n{repair_text}".strip()
                    if has_effective_action(text_concat):
                        break
                else:
                    action_blocked = True
                    _emit({
                        "type": "delivery_incomplete",
                        "reason": "action_missing",
                        "attempts": action_repairs,
                        "message": "本轮根因分析后连续补写仍未生成有效行动建议,交付不完整。",
                    })
                    logger.warning(
                        "delivery_incomplete action_missing turn=%s repairs=%s",
                        self._user_turn_count,
                        action_repairs,
                    )

            if self._turn_superseded(turn_ctx):
                _emit({"type": "session_superseded"})
                return {"route": "stop"}

            if action_needed and not action_blocked:
                items: list[dict[str, Any]] = []
                for raw in extract_action_items(text_concat):
                    parsed = split_action_item(raw)
                    items.append({
                        "title": (parsed.get("title") or raw)[:80],
                        "content": parsed.get("content") or raw,
                        "evidence": parsed.get("evidence"),
                    })
                if items:
                    _emit({
                        "type": "action_recommendations",
                        "turn": self._user_turn_count,
                        "items": items,
                    })

            if self._turn_wants_forecast:
                policy_mode = str(
                    (self._cognitive_policy_decision or {}).get("mode") or ""
                )
                if policy_mode == "CAPABILITY_LIMITATION":
                    _emit({
                        "type": "forecast_limitation",
                        "reason": "capability_unavailable",
                        "kind": self._turn_forecast_kind,
                        "message": FORECAST_LIMITATION_NOTE,
                    })
                    _emit({"type": "text_delta", "text": "\n\n" + FORECAST_LIMITATION_NOTE})
                    text_concat = f"{text_concat}\n\n{FORECAST_LIMITATION_NOTE}"
                else:
                    missing = forecast_disclosure_missing(
                        self._turn_forecast_kind,
                        self._turn_forecast_assumption,
                        text_concat,
                    )
                    if missing:
                        _emit({
                            "type": "forecast_disclosure_missing",
                            "reason": "disclosure_missing",
                            "kind": self._turn_forecast_kind,
                            "missing": missing,
                            "message": FORECAST_LIMITATION_NOTE,
                        })
                        _emit({"type": "text_delta", "text": "\n\n" + FORECAST_LIMITATION_NOTE})
                        text_concat = f"{text_concat}\n\n{FORECAST_LIMITATION_NOTE}"
                        logger.warning(
                            "forecast_disclosure_missing turn=%s kind=%s missing=%s",
                            self._user_turn_count,
                            self._turn_forecast_kind,
                            ",".join(missing),
                        )

            if self.recovery.status() == session_module.RUNNING:
                current = self.recovery.snapshot()
                succeeded = self.recovery.mark_succeeded(int(current.get("attempt") or 1))
                if succeeded is not None:
                    _emit(self._recovery_event(succeeded))

            _emit(self._sop_event(SOP_STEP_DECISION, "正在返回用户结果"))
            _emit({
                "type": "done",
                "stop_reason": (
                    "delivery_incomplete" if action_blocked
                    else ("answer_blocked" if state.get("delivery_blocked") else str(state.get("stop_reason") or "end_turn"))
                ),
            })
            return {"route": "stop"}

        workflow.add_node("begin_iteration", begin_iteration)
        workflow.add_node("llm_step", llm_step)
        workflow.add_node("after_llm", after_llm)
        workflow.add_node("tool_step", tool_step)
        workflow.add_node("ask_user_step", ask_user_step)
        workflow.add_node("finalize_step", finalize_step)

        workflow.add_edge(START, "begin_iteration")
        workflow.add_conditional_edges(
            "begin_iteration",
            lambda state: state.get("route", "llm"),
            {"llm": "llm_step", "finalize": "finalize_step", "stop": END},
        )
        workflow.add_edge("llm_step", "after_llm")
        workflow.add_conditional_edges(
            "after_llm",
            lambda state: state.get("route", "finalize"),
            {
                "next_iteration": "begin_iteration",
                "tools": "tool_step",
                "ask_user": "ask_user_step",
                "finalize": "finalize_step",
                "stop": END,
            },
        )
        workflow.add_conditional_edges(
            "tool_step",
            lambda state: state.get("route", "next_iteration"),
            {"next_iteration": "begin_iteration", "stop": END},
        )
        workflow.add_conditional_edges(
            "ask_user_step",
            lambda state: state.get("route", "awaiting"),
            {"finalize": "finalize_step", "stop": END, "awaiting": END},
        )
        workflow.add_edge("finalize_step", END)
        return workflow.compile()
