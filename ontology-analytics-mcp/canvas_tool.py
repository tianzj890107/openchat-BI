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
        "行动建议使用 kind=actions，每条带稳定 id，供 Fuxi 宿主在用户点击后创建任务令。"
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
                                "kind=actions 时传入 items 数组。"
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
                _normalize_actions(block["params"])
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


def _normalize_actions(params: dict) -> list[dict[str, Any]]:
    items = params.get("items") if isinstance(params, dict) else None
    if not isinstance(items, list) or not items:
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
        if not refs["dispatchTool"] and (
            str(item.get("source") or "").strip() == "boulderai-anaylize-todo"
            or str(item.get("scenario") or "").strip()
        ):
            refs["dispatchTool"] = "TaskOrderCreate"
        normalized.append({
            "id": action_id,
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


REQUIRED_DRAFT_FIELDS = ("draftId", "draftHash", "actionId", "approvalStatus", "expiresAt", "dispatchTool")


def _draft_ready(item: dict[str, Any]) -> bool:
    """A card may only be dispatched when the server stored a full draft."""
    return all(str(item.get(field) or "").strip() for field in REQUIRED_DRAFT_FIELDS)


def _render_actions(params: dict) -> tuple[str, list[dict[str, Any]]]:
    items = _normalize_actions(params)
    for item in items:
        item["draftReady"] = _draft_ready(item)
    cards: list[str] = []
    for item in items:
        evidence = (
            f'<p class="action-evidence">依据：{_inline_markdown(item["evidence"])}</p>'
            if item["evidence"] else ""
        )
        chips = []
        if item["severity"]:
            chips.append(f'<span class="action-chip severity">{escape(item["severity"])}</span>')
        if item["due_at"]:
            chips.append(f'<span class="action-chip">截止 {escape(item["due_at"])}</span>')
        if item["owner_name"] or item["owner_ref"]:
            chips.append(
                f'<span class="action-chip">责任人 {escape(item["owner_name"] or item["owner_ref"])}</span>'
            )
        approval = str(item.get("approvalStatus") or "").strip().lower()
        if not item["draftReady"]:
            label, disabled, title_attr = "旧版建议", " disabled", ' title="旧版建议，请重新生成任务草稿"'
        elif approval in {"approved", "host_click_authorized"}:
            label, disabled, title_attr = "发送任务令", "", ""
        else:
            label, disabled, title_attr = "待审批", " disabled", ' title="该建议尚未获得下发授权"'
        legacy_note = (
            '<p class="action-feedback" style="color:#B42318">旧版建议，请重新生成任务草稿</p>'
            if not item["draftReady"] else ""
        )
        card = (
            '<article class="action-item">'
            f'<div class="action-head"><h4>{_inline_markdown(item["title"])}</h4>'
            f'<button type="button" class="action-send" data-fuxi-task-order="{escape(item["id"])}"'
            f'{disabled}{title_attr}>{label}</button></div>'
            f'<div class="action-content">{_render_markdown(item["content"])}</div>'
            f'{evidence}'
            f'<div class="action-meta">{"".join(chips)}</div>'
            f'{legacy_note}'
            '</article>'
        )
        cards.append(card)
    return f'<div class="action-list">{"".join(cards)}</div>', items


ACTION_RUNTIME = r"""
<script>
  const PROCESS360_ACTIONS = __ACTIONS__;
  const PROCESS360_DISPATCH = { url: __DISPATCH_URL__, timeoutMs: 25000 };
  const PENDING = new Map();

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

  // One receipt contract for host and HTTP dispatch.
  function normalizeReceipt(payload) {
    if (!payload || typeof payload !== 'object') {
      return { state: 'unconfirmed', message: '未收到执行回执，请稍后在待办中确认' };
    }
    const status = String(payload.status || payload.state || '').toLowerCase();
    const receipt = payload.receipt || payload.result || null;
    if (payload.accepted === false) {
      return { state: 'unconfirmed', message: payload.message || '请求已发出，执行结果待确认', receipt };
    }
    if (status === 'ok' || payload.ok === true) {
      return { state: 'ok', message: payload.message || '任务令已创建', receipt };
    }
    if (status === 'blocked' || status === 'rejected' || payload.ok === false) {
      const gaps = (payload.gaps || []).map((item) => item && item.name).filter(Boolean);
      return { state: 'rejected', message: payload.message || gaps.join('；') || '执行被拒绝', receipt };
    }
    if (status === 'pending' || status === 'unconfirmed' || status === 'in_progress') {
      return { state: 'unconfirmed', message: payload.message || '执行结果待确认', receipt };
    }
    return { state: 'failed', message: payload.message || '执行失败', receipt };
  }

  function applyReceipt(button, payload) {
    const result = normalizeReceipt(payload);
    if (result.state === 'ok') {
      button.disabled = true;
      setActionState(button, '任务令已创建' + (result.receipt && result.receipt.sourceTodoId ? '（' + result.receipt.sourceTodoId + '）' : ''), 'ok');
    } else if (result.state === 'unconfirmed') {
      button.disabled = false;
      setActionState(button, result.message, 'pending');
    } else {
      button.disabled = false;
      setActionState(button, result.message, 'error');
    }
    return result;
  }

  async function postDirect(action) {
    const response = await fetch(PROCESS360_DISPATCH.url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        draftId: action.draftId,
        draftHash: action.draftHash,
        actionId: action.actionId || action.id,
        requestId: action.__requestId,
      }),
    });
    const text = await response.text();
    let payload = null;
    try { payload = text ? JSON.parse(text) : null; } catch (error) { payload = null; }
    if (!payload) {
      return { status: 'unconfirmed', accepted: false, message: '服务端返回无法解析的回执' };
    }
    return payload;
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
      PENDING.set(requestId, finish);
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
    const data = event.data;
    if (!data || typeof data !== 'object') return;
    if (data.type !== 'fuxi:task-order-result' && data.type !== 'fuxi:task-order-ack') return;
    const requestId = String(data.requestId || '');
    const handler = PENDING.get(requestId);
    if (handler) handler(data.payload || data);
  });

  document.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-fuxi-task-order]');
    if (!button || button.disabled) return;
    const action = PROCESS360_ACTIONS[button.getAttribute('data-fuxi-task-order')];
    if (!action) return;
    if (!action.draftReady) {
      setActionState(button, '旧版建议，请重新生成任务草稿', 'error');
      return;
    }
    const approval = String(action.approvalStatus || '').toLowerCase();
    if (approval !== 'approved' && approval !== 'host_click_authorized') {
      setActionState(button, '该建议尚未获得下发授权，请先完成审批', 'error');
      return;
    }
    const expiry = typeof action.expiresAt === 'number'
      ? action.expiresAt * 1000
      : Date.parse(String(action.expiresAt || ''));
    if (Number.isFinite(expiry) && expiry <= Date.now()) {
      setActionState(button, '任务草稿已过期，请重新生成建议', 'error');
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
    };
    button.disabled = true;
    setActionState(button, '正在提交任务令…', 'pending');
    let payload = null;
    let transport = 'http';
    try {
      payload = await postDirect({ ...action, __requestId: requestId });
    } catch (error) {
      transport = 'host';
    }
    if (transport === 'host') {
      payload = await viaHost(action, requestId, taskOrder);
    }
    if (!payload) {
      button.disabled = false;
      setActionState(button, '本页未连接任务服务，也未检测到 Fuxi 宿主桥接', 'error');
      return;
    }
    applyReceipt(button, payload);
  });
</script>
"""


def _actions_runtime(actions: list[dict[str, Any]]) -> str:
    if not actions:
        return ""
    payload = {item["id"]: item for item in actions}
    url = (os.environ.get("PROCESS360_DISPATCH_URL") or "/api/process360/task-orders").strip()
    return (
        ACTION_RUNTIME
        .replace("__ACTIONS__", _json_for_script(payload))
        .replace("__DISPATCH_URL__", json.dumps(url))
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
  .action-send { flex: none; border: 1px solid #1570EF; border-radius: 8px;
    background: #1570EF; color: #FFFFFF; padding: 6px 11px; font-size: 12px;
    font-family: inherit; cursor: pointer; }
  .action-send:disabled { background: #98A2B3; border-color: #98A2B3; cursor: default; }
  .action-feedback { margin: 8px 0 0; font-size: 12px; }
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
  }
"""


def _build_page(
    params: dict,
    body_blocks: list[str],
    charts: list[tuple[str, dict]],
    multis: list[dict],
    echarts_script: str,
    actions_runtime: str = "",
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

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
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
                    inner, block_actions = _render_actions(block["params"])
                    actions.extend(block_actions)
                else:
                    inner = _render_table(block["params"])
                body_blocks.append(f'<section class="card">{heading_html}{inner}</section>')
        except Exception as exc:  # noqa: BLE001
            return f"CanvasGenerate build error: {type(exc).__name__}: {exc}"

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
            params, body_blocks, charts, multis, echarts_script, _actions_runtime(actions)
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
            "inline_echarts": bool(inline),
            "blocks": [block["kind"] for block in params["blocks"]],
            "actions": actions,
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
