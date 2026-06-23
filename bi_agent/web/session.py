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
import re
import time
from typing import Any, Generator, Optional

from open_claude.agent_def import AgentDef
from open_claude.prompt import build_system_prompt
from open_claude.skills.bundled import init_bundled_skills
from open_claude.skills.registry import load_skills
from open_claude.tokens import CostTracker
from open_claude.tools import execute_tool

from ..llm.provider import get_model_id, stream_message
from ..llm.runtime_config import get_config as get_llm_config
from ..ontology.store import OntologyStore
from ..tools.ask_user import ASK_USER_TOOL_NAME
from ..tools.chart_multidim_tools import extract_multidim_chart_spec
from ..tools.chart_tools import extract_chart_spec
from ..tools.table_tools import extract_table_spec
from ..tools.todo_tools import extract_todo_spec


# Ontology codes carried in tool output, surfaced to the 本体 inspector panel.
# Digit widths differ across本体源 layouts (ChatBI / 超聚变 / MetaERP),
# e.g. LE000001(6位)/AT0000001(7位)/REL000006(REL前缀)/M0007(4位)。
# 用宽松的位宽区间 + 全部前缀,真实校验交给 _lookup(查不到的候选会被丢弃)。
# 长前缀排在前(REL 先于 R、BO/LE/AT 先于单字母),避免被吃成单字母前缀。
ENTITY_CODE_RE = re.compile(r"\b(?:REL|BO|LE|AT|ER|T|M|A|R)\d{3,7}\b")

# --- Render-tool enforcement ----------------------------------------------
# Tools whose output produces a dashboard card. If a turn contains
# SQL/data fetch but no render tool — or the assistant typed a Markdown
# table into the chat — we re-prompt the model to call TableGenerate.
RENDER_TOOLS = {"TableGenerate", "ChartGenerate", "ChartGenerateMultiDim"}
DATA_FETCH_TOOLS = {"SQLRun"}

# Matches a Markdown table separator row, e.g. "| --- | :---: | ---: |"
_MD_TABLE_SEP_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$",
    re.MULTILINE,
)


def _has_markdown_table(text: str) -> bool:
    return bool(text) and bool(_MD_TABLE_SEP_RE.search(text))


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
    ) -> None:
        self.cwd = cwd
        self.agent_def = agent_def
        self.ontology_store = ontology_store
        self.messages: list[dict[str, Any]] = []
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

        # Skills & system prompt (skills must be loaded before prompt build)
        init_bundled_skills()
        load_skills(cwd)
        self.system_prompt = self._build_system_prompt()

        # Aggregate history of ontology entities seen this session (dedup by code)
        self.ontology_seen: dict[str, dict[str, Any]] = {}

        # Pending AskUser tool_use whose result must be supplied by the user.
        # When non-None, the next call to run_loop() must start by appending a
        # synthetic tool_result for this id, not a fresh user message.
        self.pending_tool_use_id: Optional[str] = None
        self.pending_choice_spec: Optional[dict[str, Any]] = None
        self._pending_sibling_results: list[dict[str, Any]] = []

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
        if self._context_header:
            extras.append(self._context_header.strip())
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

    def set_context_header(self, header: Optional[str]) -> None:
        """
        Update the `# 当前报表 ... # 数据库工具可用性: ...` marker block
        mid-session. Must be called together with `set_tools_override` when
        flipping the db-query toggle, otherwise the agent will see a stale
        availability marker and refuse to use the tools it actually has.
        """
        self._context_header = header
        self.system_prompt = self._build_system_prompt()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_turn(self, user_text: str) -> Generator[dict[str, Any], None, None]:
        """Yield events for one user turn (user message → assistant → tools → ...)."""
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

                if (
                    not enforced_render
                    and has_render_tool_available
                    and (fetched_data or wrote_md_table)
                    and not rendered
                ):
                    enforced_render = True
                    reasons: list[str] = []
                    if fetched_data:
                        reasons.append("已经执行了 `SQLRun` 取数")
                    if wrote_md_table:
                        reasons.append("回复正文里直接写了 Markdown 表格")
                    reason_text = "且".join(reasons)
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
                    self.messages.append({"role": "user", "content": reminder})
                    yield {
                        "type": "render_enforce",
                        "iteration": iteration,
                        "reasons": reasons,
                        "called_tools": sorted(called_tools_this_turn),
                        "message": reminder,
                    }
                    continue  # re-prompt LLM with the reminder appended

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
                    try:
                        output = execute_tool(tu["name"], tu["input"], self.cwd)
                    except Exception as e:
                        output = f"Error executing {tu['name']}: {e}"
                    duration_ms = int((time.time() - t0) * 1000)
                    display_output, chart = extract_chart_spec(output)
                    display_output, table = extract_table_spec(display_output)
                    display_output, multi_chart = extract_multidim_chart_spec(display_output)
                    display_output, todos = extract_todo_spec(display_output)
                    llm_output = display_output if (chart or table or multi_chart or todos) else output
                    entities = self._extract_entities(display_output)
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
                try:
                    output = execute_tool(tu["name"], tu["input"], self.cwd)
                except Exception as e:
                    output = f"Error executing {tu['name']}: {e}"
                duration_ms = int((time.time() - t0) * 1000)

                # Pull out chart/table specs if present; keep the display text
                # for the UI, strip the JSON blocks before sending back to the LLM.
                display_output, chart = extract_chart_spec(output)
                display_output, table = extract_table_spec(display_output)
                display_output, multi_chart = extract_multidim_chart_spec(display_output)
                display_output, todos = extract_todo_spec(display_output)
                llm_output = display_output if (chart or table or multi_chart or todos) else output

                entities = self._extract_entities(display_output)
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

    def _stream_one_response(self, iteration: int):
        """Consume one LLM stream; yield per-delta events; return summary."""
        text_buffer = ""
        tool_uses: list[dict[str, Any]] = []
        thinking_blocks: list[dict[str, Any]] = []
        stop_reason = "end_turn"
        usage: dict[str, Any] = {}

        cfg = get_llm_config()
        current_model_id = get_model_id(cfg.model_key)

        for event in stream_message(
            self.messages,
            self.system_prompt,
            allowed_tools=self.allowed_tools,
            model_key=cfg.model_key,
            max_tokens=cfg.max_tokens,
            temperature=cfg.temperature,
            thinking=cfg.effective_thinking,
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
            elif etype == "error":
                yield {"type": "error", "message": event["error"]}
                return stop_reason, text_buffer, tool_uses, usage, thinking_blocks

        return stop_reason, text_buffer, tool_uses, usage, thinking_blocks

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

    def _extract_entities(self, text: str) -> list[dict[str, Any]]:
        """Find ontology codes in tool output, return enriched entity records."""
        codes = set(ENTITY_CODE_RE.findall(text or ""))
        results: list[dict[str, Any]] = []
        store = self.ontology_store
        for code in codes:
            entity, kind = self._lookup(code)
            if entity is None:
                continue
            record = {
                "code": code,
                "kind": kind,
                "name": getattr(entity, "name", None) or code,
                "display": entity.to_prompt(),
            }
            results.append(record)
            if code not in self.ontology_seen:
                self.ontology_seen[code] = record
        results.sort(key=lambda r: r["code"])
        return results

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
        return None, None
