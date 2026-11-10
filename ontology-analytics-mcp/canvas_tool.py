#!/usr/bin/env python3
"""Canvas tool — 把一轮分析的最终交付物拼成一份「整页、自包含」的 HTML。

原系统里 `ChartGenerate` / `TableGenerate` 产出的是 `<CHART_SPEC>`/`<TABLE_SPEC>`，
由 Web UI 在对话里内联渲染成卡片；通用 agent（Codex、Claude Code 等）没有宿主页面，
需要的是可以直接打开、可以单独转发出去的完整 HTML。本工具负责这件事：

- 复用 `ChartGenerate` / `ChartGenerateMultiDim` / `TableGenerate` 的参数与配色，
  命名与取数口径与原系统保持一致；
- 把结论、图表、表格、口径说明按顺序拼进同一页；
- 默认内联 ECharts（单文件、离线可开），可选改为同目录相对资源。

本文件属于独立 MCP 包自有模块，不改仓库原实现（`_vendor/` 保持原样副本）。
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
VENDOR = str(HERE / "_vendor")
try:
    # Embedded use (bi_agent.web.mcp_endpoint) already has the project package
    # on sys.path.  Only fall back to the vendored copy for standalone runs.
    import bi_agent  # noqa: F401
except ImportError:
    if VENDOR not in sys.path:
        sys.path.insert(0, VENDOR)

from bi_agent.display_names import (  # noqa: E402
    normalize_chart_multidim_params,
    normalize_chart_params,
    normalize_table_params,
)
from bi_agent.paths import project_path  # noqa: E402
from bi_agent.tools.chart_multidim_tools import (  # noqa: E402
    _build_dim_payload,
    _validate_multidim,
)
from bi_agent.tools.chart_tools import (  # noqa: E402
    CHART_FONT_FAMILY,
    CHART_PALETTE,
    _echarts_option,
    _slug,
)
from bi_agent.tools.chart_tools import _validate as _validate_chart  # noqa: E402
from bi_agent.tools.table_tools import _normalize_rows  # noqa: E402
from bi_agent.tools.table_tools import _validate as _validate_table  # noqa: E402

Executor = Callable[[dict, str], str]
ExecutorFactory = Callable[[], Executor]

CANVAS_DIR = Path("dataset") / "canvas"
CANVAS_SPEC_OPEN = "<CANVAS_SPEC>"
CANVAS_SPEC_CLOSE = "</CANVAS_SPEC>"
ECHARTS_ASSET = HERE / "assets" / "echarts.min.js"
ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"

BLOCK_KINDS = ("text", "chart", "chart_multi", "table", "actions")
MAX_BLOCKS = 20


CANVAS_GENERATE_SCHEMA = {
    "name": "CanvasGenerate",
    "description": (
        "把整轮分析的最终交付物拼成一份「整页、自包含」的 HTML 文件，作为对用户"
        "的最终交付（替代 Web UI 的内联卡片）。当用户要一份可以打开、保存或转发"
        "的完整分析报告时使用：默认内联 ECharts，单文件离线可开。"
        "用法：先照常执行 required_tools 取数，再用本工具把 📌 结论、图表、表格、"
        "口径说明按顺序放进同一个页面。`blocks[].params` 与 "
        "`ChartGenerate` / `ChartGenerateMultiDim` / `TableGenerate` 完全一致，"
        "不要在正文里手写 Markdown 表格，也不要把编码当展示名。"
        "行动建议使用 kind=actions，每条带稳定 id，供 Fuxi 宿主在用户点击后创建任务令；"
        "没有服务端草稿引用的卡片只作为“分析建议”展示，不会出现发送按钮；要求行动交付时"
        "必须使用 Process360Draft 返回的字段。草稿 blocked 时用 items=[] + reason 保留"
        "可见的阻断位置。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "页面标题（业务名称，必填）。",
            },
            "subtitle": {
                "type": "string",
                "description": "可选副标题（业务名称）。",
            },
            "conclusion": {
                "type": "string",
                "description": (
                    "📌 结论：一句话、带数字、带单位。纪律要求每轮交付都必须有结论，"
                    "建议以 `📌 结论` 开头。"
                ),
            },
            "source_note": {
                "type": "string",
                "description": (
                    "口径/溯源说明：指标或对象编码、物理表、时间窗口、过滤条件，"
                    "例如 'M001 · T_FM_MgmtPnL · 2024Q1-Q4'。"
                ),
            },
            "inline_echarts": {
                "type": "boolean",
                "description": (
                    "默认 true：把 ECharts 内联进 HTML，单文件离线可用；"
                    "false 则把 echarts.min.js 写到同目录并相对引用（页面更小）。"
                ),
            },
            "output_dir": {
                "type": "string",
                "description": (
                    "可选输出目录。默认 <cwd>/dataset/canvas；相对路径基于 MCP 服务端 cwd。"
                    "当宿主工作区与 MCP 服务端 cwd 不同时，传入宿主可写目录的绝对路径。"
                    "绝对路径必须位于 cwd 或 ONTOLOGY_CANVAS_ALLOWED_ROOTS 允许的根目录下。"
                ),
            },
            "blocks": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_BLOCKS,
                "description": "按顺序渲染的内容块。",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": list(BLOCK_KINDS),
                            "description": "text / chart / chart_multi / table。",
                        },
                        "heading": {
                            "type": "string",
                            "description": "可选小节标题。",
                        },
                        "markdown": {
                            "type": "string",
                            "description": (
                                "kind=text 时的正文，支持段落、`- ` 列表、**加粗**"
                                "和行内 `代码`。"
                            ),
                        },
                        "params": {
                            "type": "object",
                            "description": (
                                "kind=chart/chart_multi/table 时，与对应工具完全相同的参数；"
                                "kind=actions 时传入 items 数组；草稿 blocked 时可传 items=[]"
                                " 并必须给 reason（可带 gaps），页面展示阻断说明而不是隐藏按钮。"
                            ),
                        },
                    },
                    "required": ["kind"],
                },
            },
        },
        "required": ["title", "blocks"],
    },
}


def _json_for_script(value: Any) -> str:
    """JSON 嵌在 <script> 里，转义 HTML 敏感字符避免提前闭合脚本元素。"""
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")


def _inline_markdown(text: str) -> str:
    out = escape(text, quote=False)
    out = _INLINE_CODE_RE.sub(lambda m: f"<code>{m.group(1)}</code>", out)
    out = _BOLD_RE.sub(lambda m: f"<strong>{m.group(1)}</strong>", out)
    return out


def _render_markdown(markdown: str) -> str:
    parts: list[str] = []
    list_open = False

    def close_list() -> None:
        nonlocal list_open
        if list_open:
            parts.append("</ul>")
            list_open = False

    for raw in (markdown or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            close_list()
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            close_list()
            level = min(len(heading.group(1)) + 2, 5)
            parts.append(f"<h{level}>{_inline_markdown(heading.group(2))}</h{level}>")
            continue
        bullet = _BULLET_RE.match(line)
        if bullet:
            if not list_open:
                parts.append("<ul>")
                list_open = True
            parts.append(f"<li>{_inline_markdown(bullet.group(1))}</li>")
            continue
        close_list()
        parts.append(f"<p>{_inline_markdown(line)}</p>")
    close_list()
    return "\n".join(parts)


def _format_cell(value: Any, column: dict) -> str:
    if value is None:
        return ""
    fmt = str(column.get("format") or "text").lower()
    unit = str(column.get("unit") or "")
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not float(value).is_integer():
            text = f"{value:,.2f}"
        else:
            text = f"{value:,}"
        return f"{text}{unit}"
    return f"{value}{unit}" if fmt in ("percent", "money") else str(value)


def _render_table(params: dict) -> str:
    err = _validate_table(params)
    if err:
        raise ValueError(f"table: {err}")
    cols = params["columns"]
    rows = _normalize_rows(cols, params["rows"])
    highlight = set(params.get("highlight_rows") or [])

    head = "".join(
        f'<th>{(escape(str(c.get("label") or c.get("key") or ""))) }</th>' for c in cols
    )
    body_parts: list[str] = []
    for index, row in enumerate(rows):
        cells = []
        for col, value in zip(cols, row):
            align = col.get("align") or (
                "right" if str(col.get("format") or "") in ("number", "percent", "money") else "left"
            )
            cls = f' class="num" style="text-align:{escape(str(align))}"'
            cells.append(f"<td{cls}>{escape(_format_cell(value, col))}</td>")
        row_cls = ' class="highlight"' if index in highlight else ""
        body_parts.append(f"<tr{row_cls}>{''.join(cells)}</tr>")

    caption = ""
    subtitle = params.get("subtitle")
    if subtitle:
        caption = f'<p class="block-sub">{escape(str(subtitle))}</p>'
    summary = params.get("summary")
    summary_html = f'<p class="block-note">{escape(str(summary))}</p>' if summary else ""
    footnote = params.get("footnote")
    footnote_html = f'<p class="block-note">{escape(str(footnote))}</p>' if footnote else ""

    return (
        f'{caption}<div class="table-wrap"><table><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body_parts)}</tbody></table></div>{summary_html}{footnote_html}'
    )


def _render_chart(params: dict, chart_id: str, charts: list[tuple[str, dict]]) -> str:
    err = _validate_chart(params)
    if err:
        raise ValueError(f"chart: {err}")
    option = _echarts_option(params)
    charts.append((chart_id, option))
    subtitle = params.get("subtitle")
    sub_html = f'<p class="block-sub">{escape(str(subtitle))}</p>' if subtitle else ""
    return f'{sub_html}<div class="chart" id="{chart_id}"></div>'


def _render_chart_multi(params: dict, chart_id: str, multis: list[dict]) -> str:
    err = _validate_multidim(params)
    if err:
        raise ValueError(f"chart_multi: {err}")
    top_source = params.get("source_note") or ""
    dimensions = [_build_dim_payload(d, top_source) for d in params["dimensions"]]
    select_id = f"{chart_id}-select"
    multis.append(
        {
            "select": select_id,
            "chart": chart_id,
            "default": params["default_dim"],
            "dims": [
                {"key": d["key"], "label": d["label"], "option": d["option"]}
                for d in dimensions
            ],
        }
    )
    subtitle = params.get("subtitle")
    sub_html = f'<p class="block-sub">{escape(str(subtitle))}</p>' if subtitle else ""
    return (
        f'{sub_html}<div class="toolbar"><label for="{select_id}">维度</label>'
        f'<select id="{select_id}"></select></div>'
        f'<div class="chart" id="{chart_id}"></div>'
    )


def _validate_canvas(params: dict) -> str | None:
    if not str(params.get("title") or "").strip():
        return "title is required"
    blocks = params.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        return "blocks must be a non-empty list"
    if len(blocks) > MAX_BLOCKS:
        return f"blocks must have ≤ {MAX_BLOCKS} entries (got {len(blocks)})"
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            return f"blocks[{index}] must be an object"
        kind = block.get("kind")
        if kind not in BLOCK_KINDS:
            return f"blocks[{index}].kind must be one of {list(BLOCK_KINDS)}"
        if kind == "text" and not (block.get("markdown") or block.get("heading")):
            return f"blocks[{index}] (text) needs markdown or heading"
        if kind in ("chart", "chart_multi", "table", "actions") and not isinstance(block.get("params"), dict):
            return f"blocks[{index}] ({kind}) needs params"
        if kind == "actions":
            try:
                _validate_action_block(block["params"])
            except ValueError as exc:
                return f"blocks[{index}] (actions): {exc}"
    return None


_ACTION_REF_FIELDS = {
    "draftId": ("draftId", "draft_id"),
    "draftHash": ("draftHash", "draft_hash"),
    "runId": ("runId", "run_id"),
    "approvalStatus": ("approvalStatus", "approval_status"),
    "expiresAt": ("expiresAt", "expires_at"),
    "dispatchTool": ("dispatchTool", "dispatch_tool"),
}
_ACTION_ID_FIELDS = ("actionId", "action_id")
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_NESTED_PHONE_KEYS = {"recipientsraw", "recipients_raw", "phone", "mobile", "recipient", "recipients"}


_ACTION_TEXT_FIELDS = (
    "title", "content", "evidence", "owner_ref", "owner_name", "source",
    "scenario", "task_template", "category", "due_at", "severity",
)


def _reject_private_action(item: dict[str, Any], index: int) -> None:
    for key in item:
        if str(key).lower() in _NESTED_PHONE_KEYS:
            raise ValueError(f"items[{index}].{key} must not contain recipient data")
    for key in _ACTION_TEXT_FIELDS:
        value = item.get(key)
        if isinstance(value, str) and _PHONE_RE.search(value):
            raise ValueError(f"items[{index}].{key} must not contain a phone number")
    stack: list[tuple[str, Any]] = [("metadata.", item.get("metadata"))]
    while stack:
        path, value = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in _NESTED_PHONE_KEYS:
                    raise ValueError(f"items[{index}].{path}{key} must not contain recipient data")
                stack.append((f"{path}{key}.", child))
        elif isinstance(value, (list, tuple)):
            for child in value:
                stack.append((path, child))
        elif isinstance(value, str) and _PHONE_RE.search(value):
            raise ValueError(f"items[{index}].{path.rstrip('.')} must not contain a phone number")


def _first_text(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_actions(params: dict, *, allow_empty: bool = False) -> list[dict[str, Any]]:
    items = params.get("items") if isinstance(params, dict) else None
    if not isinstance(items, list):
        raise ValueError("items must be a non-empty list")
    if not items:
        if allow_empty:
            return []
        raise ValueError("items must be a non-empty list")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"items[{index}] must be an object")
        _reject_private_action(item, index)
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or item.get("markdown") or "").strip()
        if not title:
            raise ValueError(f"items[{index}].title is required")
        if not content:
            raise ValueError(f"items[{index}].content is required")
        action_id = str(
            item.get("id") or item.get("action_id") or f"action-{index + 1}"
        ).strip()
        if not action_id or action_id in seen:
            raise ValueError(f"items[{index}].id must be unique and non-empty")
        seen.add(action_id)
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        refs = {name: _first_text(item, keys) for name, keys in _ACTION_REF_FIELDS.items()}
        refs["actionId"] = _first_text(item, _ACTION_ID_FIELDS) or action_id
        item_type = _first_text(item, ("item_type", "itemType")).upper() or "TODO"
        if item_type not in {"RISK", "TODO"}:
            raise ValueError(f"items[{index}].itemType must be RISK or TODO")
        if not refs["dispatchTool"] and (
            str(item.get("source") or "").strip() == "boulderai-anaylize-todo"
            or str(item.get("scenario") or "").strip()
        ):
            refs["dispatchTool"] = (
                "RiskItemCreate" if item_type == "RISK" else "TaskOrderCreate"
            )
        normalized.append({
            "id": action_id,
            "item_type": item_type,
            "title": title,
            "content": content,
            "evidence": str(item.get("evidence") or "").strip(),
            "severity": str(item.get("severity") or "").strip().upper(),
            "due_at": str(item.get("due_at") or item.get("dueAt") or "").strip(),
            "owner_ref": str(item.get("owner_ref") or item.get("ownerRef") or "").strip(),
            "owner_name": str(item.get("owner_name") or item.get("ownerName") or "").strip(),
            "source": str(item.get("source") or "").strip(),
            "scenario": str(item.get("scenario") or "").strip(),
            "task_template": str(item.get("task_template") or item.get("taskTemplate") or "").strip(),
            "category": str(item.get("category") or "").strip(),
            "metadata": metadata,
            **refs,
        })
    return normalized


def _action_block_reason(params: dict) -> str:
    for key in ("reason", "unavailableReason", "blockedReason", "message"):
        value = str(params.get(key) or "").strip()
        if value:
            return value
    return ""


def _action_block_gaps(params: dict) -> list[str]:
    gaps = params.get("gaps")
    if isinstance(gaps, dict):
        gaps = [gaps]
    if not isinstance(gaps, list):
        return []
    result: list[str] = []
    for gap in gaps:
        if isinstance(gap, dict):
            text = str(
                gap.get("needed")
                or gap.get("title")
                or gap.get("message")
                or gap.get("code")
                or ""
            ).strip()
        else:
            text = str(gap or "").strip()
        if text:
            result.append(text)
    return result


def _validate_action_block(params: dict) -> list[dict[str, Any]]:
    """Validate an actions block, including an explicit blocked placeholder."""

    items = _normalize_actions(params, allow_empty=True)
    if items:
        return items
    reason = _action_block_reason(params)
    if not reason:
        raise ValueError(
            "items is empty; an unavailable action block requires a reason"
        )
    related = " ".join([reason, *_action_block_gaps(params)])
    if _PHONE_RE.search(related):
        raise ValueError("actions block reason or gaps must not contain a phone number")
    return []


REQUIRED_DRAFT_FIELDS = ("draftId", "draftHash", "actionId", "approvalStatus", "expiresAt", "dispatchTool")
DRAFT_REF_FIELDS = ("draftId", "draftHash", "approvalStatus", "expiresAt", "dispatchTool")
_CANVAS_DISPATCH_MODE_ENV = "PROCESS360_CANVAS_DISPATCH_MODE"


def _all_canvas_actions_dispatchable() -> bool:
    raw = (os.environ.get(_CANVAS_DISPATCH_MODE_ENV) or "all").strip().lower()
    return raw not in {"trusted", "draft", "0", "false", "no", "off"}


def _draft_ready(item: dict[str, Any]) -> bool:
    """A card may only be dispatched when the server stored a full draft."""
    return all(str(item.get(field) or "").strip() for field in REQUIRED_DRAFT_FIELDS)


def _draft_issue(item: dict[str, Any]) -> tuple[str, str]:
    """Return a precise, non-legacy reason why a card cannot be sent."""
    if not _draft_ready(item):
        return "missing", "缺少草稿字段，请重新生成任务草稿"
    expires = item.get("expiresAt")
    if isinstance(expires, (int, float)):
        expires_at = datetime.fromtimestamp(float(expires), tz=timezone.utc)
    else:
        text = str(expires or "").strip().replace("Z", "+00:00")
        try:
            expires_at = datetime.fromisoformat(text)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
        except ValueError:
            expires_at = None
    if expires_at is not None and expires_at <= datetime.now(timezone.utc):
        return "expired", "任务草稿已过期，请重新生成建议"
    approval = str(item.get("approvalStatus") or "").strip().lower()
    if approval not in {"approved", "host_click_authorized"}:
        return "pending", "该建议待审批，请先完成审批"
    return "", ""


def _render_actions(
    params: dict,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    items = _validate_action_block(params)
    if not items:
        reason = _action_block_reason(params)
        gaps = _action_block_gaps(params)
        gap_html = (
            "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in gaps) + "</ul>"
            if gaps
            else ""
        )
        return (
            '<div class="action-empty" data-action-state="blocked">'
            "<h4>尚不能生成可下发任务</h4>"
            f"<p>{escape(reason)}</p>{gap_html}</div>",
            [],
            {"status": "blocked", "count": 0, "items": [], "reason": reason, "gaps": gaps},
        )
    for item in items:
        item["draftReady"] = _draft_ready(item)
        item["hasDraftRefs"] = any(
            str(item.get(field) or "").strip() for field in DRAFT_REF_FIELDS
        )
        if item["draftReady"] or item["hasDraftRefs"]:
            issue, message = _draft_issue(item)
        else:
            issue, message = "", ""
        item["draftIssue"] = issue
        item["draftIssueMessage"] = message
    cards: list[str] = []
    for item in items:
        evidence = (
            f'<p class="action-evidence">依据：{_inline_markdown(item["evidence"])}</p>'
            if item["evidence"] else ""
        )
        chips = []
        is_risk = str(item.get("item_type") or "TODO").upper() == "RISK"
        send_label = "推送风险" if is_risk else "发送任务令"
        subject = "风险条目" if is_risk else "待办"
        if item["severity"]:
            chips.append(f'<span class="action-chip severity">{escape(item["severity"])}</span>')
        if is_risk:
            chips.append('<span class="action-chip risk">风险条目</span>')
        if item["due_at"]:
            chips.append(f'<span class="action-chip">截止 {escape(item["due_at"])}</span>')
        if item["owner_name"] or item["owner_ref"]:
            chips.append(
                f'<span class="action-chip">责任人 {escape(item["owner_name"] or item["owner_ref"])}</span>'
            )
        issue = item["draftIssue"]
        recommendation = not item["draftReady"] and not item["hasDraftRefs"]
        temporary_dispatch = _all_canvas_actions_dispatchable() and (
            recommendation or bool(issue)
        )
        item["temporaryDispatch"] = bool(temporary_dispatch)
        if temporary_dispatch:
            if recommendation:
                chips.append('<span class="action-chip">分析建议</span>')
            chips.append('<span class="action-chip temporary">临时直发</span>')
            chips.append('<span class="action-chip unverified">未经验证分析</span>')
            action_control = (
                f'<button type="button" class="action-send" data-fuxi-task-order="{escape(item["id"])}">'
                f"{send_label}</button>"
            )
            issue_note = (
                '<p class="action-recommendation-note">该卡尚未生成可信草稿，点击后将按当前卡片内容生成'
                f"{subject}，并发送给服务端配置的接收人；只表示 Fuxi 已接收，"
                "不代表根因已验证或风险已解除。</p>"
            )
        elif recommendation:
            chips.append('<span class="action-chip">分析建议</span>')
            action_control = ""
            issue_note = (
                '<p class="action-recommendation-note">尚未生成任务草稿，仅供分析参考；'
                "如需下发，请先生成任务草稿。</p>"
            )
        elif issue == "missing":
            label, disabled, title_attr = "缺少草稿字段", " disabled", ' title="缺少草稿字段，请重新生成任务草稿"'
            action_control = (
                f'<button type="button" class="action-send" data-fuxi-task-order="{escape(item["id"])}"'
                f'{disabled}{title_attr}>{label}</button>'
            )
            issue_note = (
                f'<p class="action-feedback" style="color:#B42318">{escape(item["draftIssueMessage"])}</p>'
            )
        elif issue == "expired":
            label, disabled, title_attr = "草稿已过期", " disabled", ' title="任务草稿已过期，请重新生成建议"'
            action_control = (
                f'<button type="button" class="action-send" data-fuxi-task-order="{escape(item["id"])}"'
                f'{disabled}{title_attr}>{label}</button>'
            )
            issue_note = (
                f'<p class="action-feedback" style="color:#B42318">{escape(item["draftIssueMessage"])}</p>'
            )
        elif issue == "pending":
            label, disabled, title_attr = "待审批", " disabled", ' title="该建议待审批，请先完成审批"'
            action_control = (
                f'<button type="button" class="action-send" data-fuxi-task-order="{escape(item["id"])}"'
                f'{disabled}{title_attr}>{label}</button>'
            )
            issue_note = (
                f'<p class="action-feedback" style="color:#B42318">{escape(item["draftIssueMessage"])}</p>'
            )
        else:
            label, disabled, title_attr = send_label, "", ""
            action_control = (
                f'<button type="button" class="action-send" data-fuxi-task-order="{escape(item["id"])}"'
                f'{disabled}{title_attr}>{label}</button>'
            )
            issue_note = ""
        card = (
            '<article class="action-item">'
            f'<div class="action-head"><h4>{_inline_markdown(item["title"])}</h4>'
            f'{action_control}</div>'
            f'<div class="action-content">{_render_markdown(item["content"])}</div>'
            f'{evidence}'
            f'<div class="action-meta">{"".join(chips)}</div>'
            f'{issue_note}'
            '</article>'
        )
        cards.append(card)
    meta_items = [
        {
            "id": item.get("id"),
            "actionId": item.get("actionId"),
            "draftId": item.get("draftId"),
            "draftHash": item.get("draftHash"),
            "dispatchTool": item.get("dispatchTool"),
            "approvalStatus": item.get("approvalStatus"),
            "expiresAt": item.get("expiresAt"),
            "runId": item.get("runId"),
            "scenario": item.get("scenario"),
            "itemType": item.get("item_type"),
            "verificationStatus": "unverified" if item.get("temporaryDispatch") else "draft_backed",
            "sourceKind": "page_direct" if item.get("temporaryDispatch") else "server_draft",
        }
        for item in items
    ]
    ready_count = sum(1 for item in items if item.get("draftReady"))
    legacy_count = sum(
        1 for item in items if item.get("hasDraftRefs") and not item.get("draftReady")
    )
    if ready_count == len(items):
        state = "ready"
    elif ready_count == 0 and legacy_count == 0:
        state = "recommendations"
    else:
        state = "mixed"
    return (
        f'<div class="action-list">{"".join(cards)}</div>',
        items,
        {
            "status": state,
            "count": len(items),
            "items": meta_items,
            "reason": "",
            "gaps": [],
            "temporaryDispatch": _all_canvas_actions_dispatchable(),
        },
    )


ACTION_RUNTIME = r"""
<script>
  const PROCESS360_ACTIONS = __ACTIONS__;
  const PROCESS360_DISPATCH = { url: __DISPATCH_URL__, timeoutMs: 25000 };
  const PROCESS360_HOST_ORIGIN = __HOST_ORIGIN__;
  const PROCESS360_ALLOW_ALL_ACTIONS = __ALLOW_ALL_ACTIONS__;
  const PENDING = new Map();
  const DRAFT_STATE_MESSAGES = {
    missing: '缺少草稿字段，请重新生成任务草稿',
    pending: '该建议待审批，请先完成审批',
    expired: '任务草稿已过期，请重新生成建议',
  };
  const PROCESS360_PENDING_KEY = 'process360.pending.' + PROCESS360_DISPATCH.url;
  const PROCESS360_STATUS_DELAYS = [1200, 2500, 5000];

  function feedbackNode(button) {
    const item = button.closest('.action-item');
    let note = item && item.querySelector(':scope > .action-feedback');
    if (!note) {
      note = document.createElement('p');
      note.className = 'action-feedback';
      if (item) item.appendChild(note);
    }
    return note;
  }

  function setActionState(button, text, tone) {
    const note = feedbackNode(button);
    if (!note) return;
    note.textContent = text;
    note.style.color = tone === 'error' ? '#B42318' : (tone === 'pending' ? '#B54708' : '#087443');
  }

  function draftIssue(action) {
    const required = ['draftId', 'draftHash', 'actionId', 'approvalStatus', 'expiresAt', 'dispatchTool'];
    if (required.some((field) => !String(action[field] == null ? '' : action[field]).trim())) return 'missing';
    const expiry = typeof action.expiresAt === 'number'
      ? action.expiresAt * 1000
      : Date.parse(String(action.expiresAt || ''));
    if (Number.isFinite(expiry) && expiry <= Date.now()) return 'expired';
    const approval = String(action.approvalStatus || '').toLowerCase();
    if (approval !== 'approved' && approval !== 'host_click_authorized') return 'pending';
    return '';
  }

  function pendingKey(action) {
    return [
      action.draftId || '',
      action.actionId || action.id || '',
    ].join('|');
  }

  function isRiskItem(action) {
    return String((action && (action.itemType || action.item_type)) || 'TODO').toUpperCase() === 'RISK';
  }

  function itemLabel(action) {
    return isRiskItem(action) ? '风险条目' : '任务令';
  }

  function sendLabel(action) {
    return isRiskItem(action) ? '推送风险' : '发送任务令';
  }

  function rememberPending(action) {
    try {
      localStorage.setItem(PROCESS360_PENDING_KEY + ':' + pendingKey(action), JSON.stringify({
        draftId: action.draftId || '',
        actionId: action.actionId || action.id || '',
        requestedAt: Date.now(),
      }));
    } catch (error) {}
  }

  function hasPending(action) {
    try {
      return Boolean(localStorage.getItem(PROCESS360_PENDING_KEY + ':' + pendingKey(action)));
    } catch (error) {
      return false;
    }
  }

  function forgetPending(action) {
    try {
      localStorage.removeItem(PROCESS360_PENDING_KEY + ':' + pendingKey(action));
    } catch (error) {}
  }

  // One receipt contract for host and HTTP dispatch.  Acknowledging a request
  // is not success: only a server receipt that proves the todo was applied is.
  function normalizeReceipt(payload) {
    if (!payload || typeof payload !== 'object') {
      return { state: 'unconfirmed', message: '未收到执行回执，请稍后在待办中确认' };
    }
    const status = String(payload.status || payload.state || '').toLowerCase();
    const receipt = payload.receipt || payload.result || null;
    if (status === 'blocked' || status === 'rejected' || payload.ok === false) {
      const gaps = (payload.gaps || []).map((item) => item && item.name).filter(Boolean);
      return { state: 'rejected', message: payload.message || gaps.join('；') || '执行被拒绝', receipt };
    }
    if (status === 'failed') {
      return { state: 'failed', message: payload.message || '执行失败', receipt };
    }
    if (status === 'pending' || status === 'unconfirmed' || status === 'in_progress' || status === 'unknown') {
      return {
        state: 'unconfirmed',
        message: payload.message || '执行结果待确认',
        receipt,
        retryable: payload.retryable === true || status === 'unknown',
      };
    }
    if (payload.accepted !== true) {
      return { state: 'unconfirmed', message: payload.message || '执行结果待确认', receipt };
    }
    const applied = Number((receipt && receipt.applied) || 0);
    const skipped = Number((receipt && receipt.skipped) || 0);
    const receiptOk = Boolean(receipt && receipt.ok === true);
    const appliedCount = Number.isFinite(applied) && Number.isFinite(skipped) ? applied + skipped : 0;
    if ((status === 'ok' || payload.ok === true) && receiptOk && appliedCount > 0) {
      return { state: 'ok', message: payload.message || '任务令已创建', receipt };
    }
    const retryable = payload.retryable === true || status === 'unknown' || status === 'failed';
    return {
      state: 'unconfirmed',
      message: payload.message || '缺少可验证的执行回执，结果待确认',
      receipt,
      retryable,
    };
  }

  function applyReceipt(button, payload, action) {
    const result = normalizeReceipt(payload);
    const label = sendLabel(action);
    const subject = itemLabel(action);
    if (result.state === 'ok') {
      button.disabled = true;
      button.dataset.retry = 'false';
      button.textContent = label;
      if (action) forgetPending(action);
      const verification = payload && payload.verificationStatus === 'unverified' ? '（未经验证分析）' : '';
      setActionState(button, (isRiskItem(action) ? '风险条目已推送' : '任务令已创建') + verification + (result.receipt && result.receipt.sourceTodoId ? '（' + result.receipt.sourceTodoId + '）' : ''), 'ok');
    } else if (result.state === 'unconfirmed') {
      button.disabled = false;
      const retryable = result.retryable === true;
      button.dataset.retry = retryable ? 'true' : 'false';
      button.textContent = retryable ? '安全重试' : label;
      setActionState(button, result.message + (retryable ? '，可使用同一草稿安全重试' : ''), 'pending');
    } else {
      button.disabled = false;
      button.dataset.retry = 'false';
      button.textContent = label;
      if (action) forgetPending(action);
      setActionState(button, result.message || (subject + '未推送'), 'error');
    }
    return result;
  }

  async function fetchPayload(url, options) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), PROCESS360_DISPATCH.timeoutMs);
    try {
      const response = await fetch(url, Object.assign({ credentials: 'same-origin' }, options || {}, { signal: controller.signal }));
      const text = await response.text();
      let payload = null;
      try { payload = text ? JSON.parse(text) : null; } catch (error) { payload = null; }
      return { response, payload };
    } finally {
      clearTimeout(timer);
    }
  }

  function taskAction(action) {
    return {
      id: action.id,
      actionId: action.actionId || action.id,
      title: action.title,
      content: action.content,
      evidence: action.evidence || '',
      severity: action.severity || 'MEDIUM',
      itemType: action.itemType || action.item_type || 'TODO',
      dueAt: action.dueAt || action.due_at || '',
      ownerRef: action.ownerRef || action.owner_ref || '',
      ownerName: action.ownerName || action.owner_name || '',
      scenario: action.scenario || 'CANVAS',
      category: action.category || '智能分析任务令',
      taskTemplate: action.taskTemplate || action.task_template || '',
      dispatchTool: action.dispatchTool || '',
      verificationStatus: action.verificationStatus || 'unverified',
      metadata: action.metadata && typeof action.metadata === 'object' ? action.metadata : {},
    };
  }

  function adoptServerIdentity(action, payload) {
    if (!action || !payload || typeof payload !== 'object') return;
    const draftId = String(payload.draftId || '').trim();
    const actionId = String(payload.actionId || action.actionId || action.id || '').trim();
    const previous = {
      draftId: action.draftId || '',
      actionId: action.actionId || action.id || '',
    };
    if (draftId) action.draftId = draftId;
    if (actionId) action.actionId = actionId;
    if (draftId) {
      forgetPending(previous);
      rememberPending(action);
    }
  }

  async function postDirect(action, button) {
    const { response, payload } = await fetchPayload(PROCESS360_DISPATCH.url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({
        draftId: action.draftId,
        draftHash: action.draftHash,
        actionId: action.actionId || action.id,
        requestId: action.__requestId,
        itemType: taskAction(action).itemType,
        retry: button.dataset.retry === 'true',
        action: taskAction(action),
      }),
    });
    if (!response.ok) {
      return { status: 'unconfirmed', accepted: false, retryable: true, message: '服务端返回 HTTP ' + response.status + '，执行结果待确认' };
    }
    if (!payload) {
      return { status: 'unconfirmed', accepted: false, retryable: true, message: '服务端返回无法解析的回执，执行结果待确认' };
    }
    return payload;
  }

  async function refreshStatus(button, action) {
    try {
      const url = new URL(PROCESS360_DISPATCH.url, window.location.href);
      url.searchParams.set('draftId', action.draftId || '');
      url.searchParams.set('actionId', action.actionId || action.id || '');
      const { response, payload } = await fetchPayload(url.toString(), {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
      });
      if (!response.ok) return null;
      if (!payload) return null;
      return applyReceipt(button, payload, action);
    } catch (error) {
      return null;
    }
  }

  async function monitorStatus(button, action, attempt) {
    const current = Number.isInteger(attempt) ? attempt : 0;
    const result = await refreshStatus(button, action);
    if (!result || result.state !== 'unconfirmed' || !hasPending(action)) return result;
    if (current >= PROCESS360_STATUS_DELAYS.length) return result;
    const delay = PROCESS360_STATUS_DELAYS[current];
    setTimeout(() => monitorStatus(button, action, current + 1), delay);
    return result;
  }

  function restorePendingDispatches() {
    document.querySelectorAll('[data-fuxi-task-order]').forEach((button) => {
      const action = PROCESS360_ACTIONS[button.getAttribute('data-fuxi-task-order')];
      if (!action || !hasPending(action)) return;
      button.disabled = false;
      setActionState(button, '正在恢复任务令状态…', 'pending');
      monitorStatus(button, action, 0);
    });
  }

  function viaHost(action, requestId, taskOrder) {
    const callback = window.fuxiCreateTaskOrder || (window.Fuxi && window.Fuxi.createTaskOrder);
    return new Promise((resolve) => {
      let settled = false;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        PENDING.delete(requestId);
        clearTimeout(timer);
        resolve(value);
      };
      const timer = setTimeout(() => {
        finish({ status: 'unconfirmed', accepted: false, message: '宿主未在 25 秒内返回执行结果，请稍后在待办中确认' });
      }, PROCESS360_DISPATCH.timeoutMs);
      PENDING.set(requestId, { resolve: finish, acknowledged: false });
      try {
        const result = typeof callback === 'function' ? callback(action, taskOrder) : null;
        if (result && typeof result.then === 'function') {
          result.then(finish).catch((error) => finish({ status: 'failed', message: String((error && error.message) || error) }));
        } else if (result && typeof result === 'object') {
          finish(result);
        } else if (typeof callback === 'function') {
          // Synchronous host ack without a receipt is not a success.
          finish({ status: 'unconfirmed', accepted: false, message: '宿主已接收请求，执行结果待确认' });
        } else {
          finish(null);
        }
      } catch (error) {
        finish({ status: 'failed', message: String((error && error.message) || error) });
      }
    });
  }

  window.addEventListener('message', (event) => {
    if (window.parent !== window) {
      if (event.source !== window.parent) return;
      if (PROCESS360_HOST_ORIGIN && event.origin !== PROCESS360_HOST_ORIGIN) return;
      if (!PROCESS360_HOST_ORIGIN && event.origin !== window.location.origin) return;
    }
    const data = event.data;
    if (!data || typeof data !== 'object') return;
    if (data.type !== 'fuxi:task-order-result' && data.type !== 'fuxi:task-order-ack') return;
    const requestId = String(data.requestId || '');
    const pending = PENDING.get(requestId);
    if (!pending) return;
    if (data.type === 'fuxi:task-order-ack') {
      pending.acknowledged = true;
      return;
    }
    pending.resolve(data.payload || data);
  });

  document.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-fuxi-task-order]');
    if (!button || button.disabled) return;
    const action = PROCESS360_ACTIONS[button.getAttribute('data-fuxi-task-order')];
    if (!action) return;
    const issue = PROCESS360_ALLOW_ALL_ACTIONS ? '' : draftIssue(action);
    if (issue) {
      setActionState(button, DRAFT_STATE_MESSAGES[issue], 'error');
      return;
    }
    const requestId = (window.crypto && crypto.randomUUID)
      ? crypto.randomUUID()
      : String(Date.now()) + '-' + Math.random().toString(16).slice(2);
    const taskOrder = {
      action_id: action.actionId || action.id,
      draft_id: action.draftId,
      draft_hash: action.draftHash,
      run_id: action.runId || undefined,
      dispatch_tool: action.dispatchTool,
      item_type: action.itemType || action.item_type || 'TODO',
      action: taskAction(action),
      retry: button.dataset.retry === 'true',
    };
    rememberPending(action);
    button.disabled = true;
    setActionState(button, isRiskItem(action) ? '正在推送风险…' : '正在提交任务令…', 'pending');
    let payload = null;
    const useHostAdapter = window.PROCESS360_TASK_ORDER_TRANSPORT === 'host';
    if (useHostAdapter) {
      payload = await viaHost(action, requestId, taskOrder);
    } else {
      try {
        payload = await postDirect({ ...action, __requestId: requestId }, button);
      } catch (error) {
        payload = { status: 'unconfirmed', accepted: false, retryable: true, message: '请求可能已发出，执行结果待确认' };
      }
    }
    if (!payload) {
      button.disabled = false;
      setActionState(button, '本页未连接任务服务，也未检测到 Fuxi 宿主桥接', 'error');
      return;
    }
    adoptServerIdentity(action, payload);
    const result = applyReceipt(button, payload, action);
    if (result.state === 'unconfirmed') monitorStatus(button, action, 0);
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', restorePendingDispatches);
  } else {
    restorePendingDispatches();
  }
</script>
"""


def _actions_runtime(actions: list[dict[str, Any]]) -> str:
    if not actions:
        return ""
    payload = {item["id"]: item for item in actions}
    url = (os.environ.get("PROCESS360_DISPATCH_URL") or "/api/process360/task-orders").strip()
    host_origin = (os.environ.get("PROCESS360_HOST_ORIGIN") or "").strip()
    return (
        ACTION_RUNTIME
        .replace("__ACTIONS__", _json_for_script(payload))
        .replace("__DISPATCH_URL__", json.dumps(url))
        .replace("__HOST_ORIGIN__", json.dumps(host_origin))
        .replace(
            "__ALLOW_ALL_ACTIONS__",
            "true" if _all_canvas_actions_dispatchable() else "false",
        )
    )


PAGE_STYLE = """
  :root { color-scheme: light; }
  html, body { margin: 0; background: #F2F3F5; color: #1F2023;
    font-family: "PingFang SC", "SF Pro Display", -apple-system, sans-serif; }
  .page { max-width: 1080px; margin: 0 auto; padding: 32px 24px 56px; }
  header.page-head { margin-bottom: 20px; }
  h1 { font-size: 24px; line-height: 1.35; margin: 0 0 6px; }
  .page-sub { margin: 0; color: #6B7280; font-size: 14px; }
  .page-meta { margin: 8px 0 0; color: #9AA0A6; font-size: 12px; }
  .conclusion { background: #EAF3FF; border: 1px solid #C9E0FF; border-radius: 12px;
    padding: 14px 18px; font-size: 16px; font-weight: 600; color: #0B4FA8;
    margin: 0 0 20px; }
  .card { background: #FFFFFF; border: 1px solid #E7E7EA; border-radius: 14px;
    padding: 18px 20px; margin: 0 0 18px; box-shadow: 0 1px 2px rgba(16,24,40,.04); }
  .card h3, .card h4 { margin: 0 0 10px; }
  .block-sub { margin: -4px 0 10px; color: #6B7280; font-size: 13px; }
  .block-note { margin: 10px 0 0; color: #6B7280; font-size: 12px; }
  .chart { width: 100%; height: 360px; }
  .toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 8px; }
  .toolbar label { font-size: 12px; color: #6B7280; }
  select { background: #FFFFFF; color: #1F2023; border: 1px solid #D9D9E3;
    padding: 6px 10px; border-radius: 8px; font-size: 13px;
    font-family: "PingFang SC", "SF Pro Display", -apple-system, sans-serif; }
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { border-bottom: 1px solid #EDEDF0; padding: 8px 10px; white-space: nowrap; }
  th { background: #FAFAFB; color: #4B5563; font-weight: 600; text-align: left; }
  td.num { font-variant-numeric: tabular-nums; }
  tr.highlight td { background: #FFF7E6; }
  code { background: #F3F4F6; border-radius: 4px; padding: 1px 5px; font-size: 12px; }
  .action-list { display: grid; gap: 10px; }
  .action-empty { border: 1px dashed #D0D5DD; border-radius: 10px; padding: 12px 14px;
    background: #FFFAEB; color: #7A2E0E; }
  .action-empty h4 { margin: 0 0 6px; font-size: 14px; }
  .action-empty p { margin: 4px 0; font-size: 13px; }
  .action-empty ul { margin: 6px 0 0 18px; padding: 0; font-size: 12px; }
  .action-item { border: 1px solid #E4E7EC; border-radius: 10px; padding: 12px 14px;
    background: #FCFCFD; }
  .action-head { display: flex; align-items: flex-start; justify-content: space-between;
    gap: 12px; }
  .action-head h4 { margin: 0; font-size: 14px; line-height: 1.5; }
  .action-content { margin-top: 6px; color: #344054; font-size: 13px; }
  .action-content p { margin: 4px 0; }
  .action-evidence { margin: 6px 0 0; color: #667085; font-size: 12px; }
  .action-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
  .action-chip { border-radius: 999px; padding: 2px 8px; background: #F2F4F7;
    color: #475467; font-size: 11px; }
  .action-chip.severity { background: #FEF3F2; color: #B42318; }
  .action-chip.temporary { background: #EAF3FF; color: #0B4FA8; }
  .action-chip.unverified { background: #FFFAEB; color: #B54708; }
  .action-send { flex: none; border: 1px solid #1570EF; border-radius: 8px;
    background: #1570EF; color: #FFFFFF; padding: 6px 11px; font-size: 12px;
    font-family: inherit; cursor: pointer; }
  .action-send:disabled { background: #98A2B3; border-color: #98A2B3; cursor: default; }
  .action-feedback { margin: 8px 0 0; font-size: 12px; }
  .action-recommendation-note { margin: 8px 0 0; color: #667085;
    font-size: 12px; line-height: 18px; }
  .page-foot { margin-top: 8px; color: #9AA0A6; font-size: 12px; }
  @media (prefers-color-scheme: dark) {
    html, body { background: #14161A; color: #E8EAED; }
    .card { background: #1B1E23; border-color: #2A2E35; }
    .conclusion { background: #14243C; border-color: #234067; color: #BBD8FF; }
    th { background: #20242B; color: #C6CBD1; }
    th, td { border-bottom-color: #2A2E35; }
    code { background: #242830; }
    .action-item { background: #171A1F; border-color: #2A2E35; }
    .action-content { color: #D0D5DD; }
    .action-chip { background: #242830; color: #C6CBD1; }
    .action-recommendation-note { color: #98A2B3; }
  }
"""


def _build_page(
    params: dict,
    body_blocks: list[str],
    charts: list[tuple[str, dict]],
    multis: list[dict],
    echarts_script: str,
    actions_runtime: str = "",
    actions_meta: dict[str, Any] | None = None,
) -> str:
    title = escape(str(params.get("title") or "分析交付"), quote=False)
    subtitle = str(params.get("subtitle") or "").strip()
    sub_html = f'<p class="page-sub">{escape(subtitle)}</p>' if subtitle else ""
    source_note = str(params.get("source_note") or "").strip()
    generated = time.strftime("%Y-%m-%d %H:%M")
    meta = f"生成时间 {generated}" + (f" · 口径 {escape(source_note)}" if source_note else "")
    conclusion = str(params.get("conclusion") or "").strip()
    conclusion_html = (
        f'<div class="conclusion">{_inline_markdown(conclusion)}</div>' if conclusion else ""
    )
    foot = (
        f'<p class="page-foot">口径与溯源：{escape(source_note)}</p>' if source_note else ""
    )

    runtime = ""
    if charts or multis:
        runtime = f"""
<script>
  const CHARTS = {_json_for_script(charts)};
  const MULTI = {_json_for_script(multis)};
  for (const [id, option] of CHARTS) {{
    const el = document.getElementById(id);
    if (!el) continue;
    const chart = echarts.init(el);
    chart.setOption(option);
    window.addEventListener('resize', () => chart.resize());
  }}
  for (const spec of MULTI) {{
    const select = document.getElementById(spec.select);
    const chart = echarts.init(document.getElementById(spec.chart));
    const show = (key) => {{
      const dim = spec.dims.find((d) => d.key === key) || spec.dims[0];
      chart.setOption(dim.option, true);
    }};
    for (const dim of spec.dims) {{
      const option = document.createElement('option');
      option.value = dim.key;
      option.textContent = dim.label;
      if (dim.key === spec.default) option.selected = true;
      select.appendChild(option);
    }}
    select.addEventListener('change', (event) => show(event.target.value));
    show(spec.default);
    window.addEventListener('resize', () => chart.resize());
  }}
</script>"""

    actions_meta_html = ""
    if actions_meta and actions_meta.get("status") in {
        "ready", "recommendations", "mixed", "blocked"
    }:
        payload = json.dumps(actions_meta, ensure_ascii=False, separators=(",", ":"))
        actions_meta_html = (
            '<meta name="canvas-actions" content="' + escape(payload, quote=True) + '">'
        )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{actions_meta_html}
<title>{title}</title>
<style>{PAGE_STYLE}</style>
{echarts_script}
</head>
<body>
<main class="page">
<header class="page-head">
  <h1>{title}</h1>
  {sub_html}
  <p class="page-meta">{meta}</p>
</header>
{conclusion_html}
{chr(10).join(body_blocks)}
{foot}
</main>{runtime}{actions_runtime}
</body>
</html>"""


def render_canvas_html(params: dict, *, allow_external_assets: bool = True) -> str:
    """Render one Canvas page in memory without writing a file.

    Embedded hosts (Cockpit's "full evidence" view) need the same page style
    and table/richtext rendering as ``CanvasGenerate`` but must not create a
    timestamped artifact or call any tool.  Charts and tables are rendered
    from the inline ``params`` exactly like the file-producing path, so this
    adds no AP or model round-trip.

    ``kind=actions`` is rejected here: the action cards carry a dispatch
    runtime owned by the MCP host, which the read-only evidence page must not
    embed.
    """
    err = _validate_canvas(params)
    if err:
        raise ValueError(err)
    charts: list[tuple[str, dict]] = []
    multis: list[dict] = []
    body_blocks: list[str] = []
    for index, block in enumerate(params["blocks"]):
        kind = block["kind"]
        if kind == "actions":
            raise ValueError("actions blocks are not supported in embedded HTML")
        heading = str(block.get("heading") or "").strip()
        heading_html = f"<h3>{escape(heading)}</h3>" if heading else ""
        if kind == "text":
            inner = _render_markdown(str(block.get("markdown") or ""))
        elif kind == "chart":
            inner = _render_chart(block["params"], f"chart-{index}", charts)
        elif kind == "chart_multi":
            inner = _render_chart_multi(block["params"], f"chart-{index}", multis)
        else:
            inner = _render_table(block["params"])
        body_blocks.append(f'<section class="card">{heading_html}{inner}</section>')
    echarts_script = ""
    if charts or multis:
        try:
            echarts_script = f'<script>{ECHARTS_ASSET.read_text(encoding="utf-8")}</script>'
        except OSError:
            if not allow_external_assets:
                raise
            echarts_script = f'<script src="{ECHARTS_CDN}"></script>'
    return _build_page(params, body_blocks, charts, multis, echarts_script)


def _make_canvas_generate(
    display_resolver: "Callable[[str], str | None] | None" = None,
) -> Executor:
    def run(params: dict, cwd: str) -> str:
        if display_resolver is not None:
            params = _normalize_blocks(params, display_resolver)
        err = _validate_canvas(params)
        if err:
            return f"CanvasGenerate rejected: {err}"

        charts: list[tuple[str, dict]] = []
        multis: list[dict] = []
        body_blocks: list[str] = []
        counts = {"text": 0, "chart": 0, "chart_multi": 0, "table": 0, "actions": 0}
        actions: list[dict[str, Any]] = []
        blocked_action_state: dict[str, Any] | None = None

        try:
            for index, block in enumerate(params["blocks"]):
                kind = block["kind"]
                counts[kind] += 1
                heading = str(block.get("heading") or "").strip()
                heading_html = f"<h3>{escape(heading)}</h3>" if heading else ""
                if kind == "text":
                    inner = _render_markdown(str(block.get("markdown") or ""))
                elif kind == "chart":
                    inner = _render_chart(block["params"], f"chart-{index}", charts)
                elif kind == "chart_multi":
                    inner = _render_chart_multi(block["params"], f"chart-{index}", multis)
                elif kind == "actions":
                    inner, block_actions, block_state = _render_actions(block["params"])
                    actions.extend(block_actions)
                    if block_state.get("status") == "blocked" and blocked_action_state is None:
                        blocked_action_state = block_state
                else:
                    inner = _render_table(block["params"])
                body_blocks.append(f'<section class="card">{heading_html}{inner}</section>')
        except Exception as exc:  # noqa: BLE001
            return f"CanvasGenerate build error: {type(exc).__name__}: {exc}"

        if actions:
            has_draft_refs = any(item.get("hasDraftRefs") for item in actions)
            all_drafts_ready = all(item.get("draftReady") for item in actions)
            if all_drafts_ready:
                action_status = "ready"
            elif not has_draft_refs:
                action_status = "recommendations"
            else:
                action_status = "mixed"
            action_meta = {
                "status": action_status,
                "count": len(actions),
                "items": [
                    {
                        "id": item.get("id"),
                        "actionId": item.get("actionId"),
                        "draftId": item.get("draftId"),
                        "draftHash": item.get("draftHash"),
                        "dispatchTool": item.get("dispatchTool"),
                        "approvalStatus": item.get("approvalStatus"),
                        "expiresAt": item.get("expiresAt"),
                        "runId": item.get("runId"),
                        "scenario": item.get("scenario"),
                        "itemType": item.get("item_type") or item.get("itemType"),
                        "temporaryDispatch": bool(item.get("temporaryDispatch")),
                        "verificationStatus": "unverified" if item.get("temporaryDispatch") else "draft_backed",
                        "sourceKind": "page_direct" if item.get("temporaryDispatch") else "server_draft",
                        "draftReady": bool(item.get("draftReady")),
                        "hasDraftRefs": bool(item.get("hasDraftRefs")),
                    }
                    for item in actions
                ],
                "reason": "",
                "gaps": [],
                "temporaryDispatch": _all_canvas_actions_dispatchable(),
            }
        elif blocked_action_state is not None:
            action_meta = blocked_action_state
        else:
            action_meta = {"status": "none", "count": 0, "items": [], "reason": "", "gaps": []}

        inline = params.get("inline_echarts", True)
        assets_note = ""
        if charts or multis:
            if inline:
                try:
                    echarts_script = (
                        f'<script>{ECHARTS_ASSET.read_text(encoding="utf-8")}</script>'
                    )
                except OSError:
                    echarts_script = f'<script src="{ECHARTS_CDN}"></script>'
                    assets_note = " (echarts 资源缺失，已回退 CDN，离线可能打不开)"
            else:
                echarts_script = '<script src="./echarts.min.js"></script>'
        else:
            echarts_script = ""

        title = str(params.get("title"))
        ts = time.strftime("%Y%m%d-%H%M%S")
        try:
            out_dir = _resolve_output_dir(cwd, params.get("output_dir"))
            out_dir.mkdir(parents=True, exist_ok=True)
        except (OSError, ValueError) as exc:
            return f"CanvasGenerate rejected: {exc}"
        if charts or multis:
            if not inline:
                try:
                    (out_dir / "echarts.min.js").write_text(
                        ECHARTS_ASSET.read_text(encoding="utf-8"), encoding="utf-8"
                    )
                except OSError as exc:  # noqa: BLE001
                    assets_note += f" (同目录 echarts.min.js 写入失败: {exc})"

        stem = f"canvas-{ts}-{_slug(title)}"
        out_path = out_dir / f"{stem}.html"
        suffix = 2
        while out_path.exists():
            out_path = out_dir / f"{stem}-{suffix}.html"
            suffix += 1

        page = _build_page(
            params,
            body_blocks,
            charts,
            multis,
            echarts_script,
            _actions_runtime(actions),
            action_meta,
        )
        try:
            out_path.write_text(page, encoding="utf-8")
            saved_at = (
                str(out_path.relative_to(cwd)) if out_path.is_relative_to(cwd) else str(out_path)
            )
            size_kb = out_path.stat().st_size / 1024
        except OSError as exc:  # noqa: BLE001
            return f"CanvasGenerate save error: {type(exc).__name__}: {exc}"

        parts = [f"{kind}×{count}" for kind, count in counts.items() if count]
        header = (
            f"Canvas generated — {title}\n"
            f"Blocks: {', '.join(parts) or 'none'}\n"
            f"Saved: {saved_at} ({size_kb:.0f} KB){assets_note}"
        )
        if not str(params.get("conclusion") or "").strip():
            header += "\nWarning: 缺少 📌 结论，交付前请补上（纪律硬要求）。"

        spec_payload = {
            "title": title,
            "subtitle": params.get("subtitle") or "",
            "conclusion": params.get("conclusion") or "",
            "source_note": params.get("source_note") or "",
            "saved_path": saved_at,
            "canvasId": out_path.stem,
            "artifactHash": _sha256_text(page),
            "inline_echarts": bool(inline),
            "blocks": [block["kind"] for block in params["blocks"]],
            "actions": actions,
            "actionState": action_meta,
        }
        return (
            f"{header}\n\n{CANVAS_SPEC_OPEN}"
            + json.dumps(spec_payload, ensure_ascii=False)
            + f"{CANVAS_SPEC_CLOSE}"
        )

    return run


def _resolve_output_dir(cwd: str, requested: object) -> Path:
    """Resolve the canvas directory without allowing unapproved absolute writes."""
    base = Path(cwd).resolve()
    text = str(requested or "").strip()
    if not text:
        return project_path(cwd, CANVAS_DIR)
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    candidate = candidate.resolve()
    roots = [base]
    raw_roots = os.environ.get("ONTOLOGY_CANVAS_ALLOWED_ROOTS", "")
    for raw in raw_roots.split(os.pathsep):
        if raw.strip():
            roots.append(Path(raw.strip()).expanduser().resolve())
    if not any(candidate == root or candidate.is_relative_to(root) for root in roots):
        raise ValueError(
            "output_dir is outside the allowed roots; set ONTOLOGY_CANVAS_ALLOWED_ROOTS "
            "to an explicit host workspace directory when needed"
        )
    return candidate


def _normalize_blocks(params: dict, resolver: "Callable[[str], str | None]") -> dict:
    """对每个块的 params 套用与对应工具相同的业务名归一化。"""
    if not isinstance(params.get("blocks"), list):
        return params
    blocks = []
    for block in params["blocks"]:
        if not isinstance(block, dict):
            blocks.append(block)
            continue
        kind = block.get("kind")
        inner = block.get("params")
        if isinstance(inner, dict):
            if kind == "chart":
                inner = normalize_chart_params(inner, resolver)
            elif kind == "chart_multi":
                inner = normalize_chart_multidim_params(inner, resolver)
            elif kind == "table":
                inner = normalize_table_params(inner, resolver)
            block = {**block, "params": inner}
        blocks.append(block)
    return {**params, "blocks": blocks}


def extract_canvas_spec(tool_output: str) -> tuple[str, dict | None]:
    """Pull the CANVAS_SPEC block out of a tool output string."""
    pattern = re.compile(
        re.escape(CANVAS_SPEC_OPEN) + r"(.*?)" + re.escape(CANVAS_SPEC_CLOSE), re.DOTALL
    )
    match = pattern.search(tool_output or "")
    if not match:
        return tool_output, None
    try:
        spec = json.loads(match.group(1))
    except json.JSONDecodeError:
        return tool_output, None
    cleaned = (tool_output[: match.start()] + tool_output[match.end():]).rstrip()
    return cleaned, spec


SPECS: list[tuple[dict, ExecutorFactory]] = [
    (CANVAS_GENERATE_SCHEMA, lambda: _make_canvas_generate()),
]


if __name__ == "__main__":  # 允许单独调试：python3 ontology-analytics-mcp/canvas_tool.py '<json>'
    payload = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {"title": "demo", "blocks": []}
    workdir = os.getcwd()
    print(_make_canvas_generate()(payload, workdir))
