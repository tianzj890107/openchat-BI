"""
Table generation tool — emits a structured table spec (columns + rows) that
the Web UI renders as a proper data grid instead of Markdown. Mirrors the
ChartGenerate convention: the payload is wrapped in <TABLE_SPEC>...</TABLE_SPEC>
tags inside the tool output, so WebSession can strip + extract it before
feeding the text back to the LLM.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

Executor = Callable[[dict, str], str]
ExecutorFactory = Callable[[], Executor]


TABLE_SPEC_OPEN = "<TABLE_SPEC>"
TABLE_SPEC_CLOSE = "</TABLE_SPEC>"
TABLE_SPEC_RE = re.compile(
    re.escape(TABLE_SPEC_OPEN) + r"(.*?)" + re.escape(TABLE_SPEC_CLOSE),
    re.DOTALL,
)

ALLOWED_ALIGN = {"left", "right", "center"}
ALLOWED_FORMAT = {"text", "number", "percent", "money"}

MAX_ROWS = 500
MAX_COLS = 30


TABLE_GENERATE_SCHEMA = {
    "name": "TableGenerate",
    "description": (
        "Render a structured data table for the Web UI. Use this instead of "
        "writing Markdown tables whenever you're presenting a result set "
        "(SQL output, drill-down breakdowns, cross-period comparisons, TOPN "
        "rankings, rate tables) — the UI renders it as a clean data grid "
        "with numeric alignment, thousand separators and unit formatting. "
        "Valid data sources: a SQLRun result set, a table extracted from an "
        "uploaded report, or a computation over either. Do NOT fabricate "
        "rows — every value must be traceable to a tool result or a report "
        "reference. Always set `source_note` with provenance (e.g., "
        "'M001 · T_FM_MgmtPnL · 2024Q1-Q4' or '报表 P3/Table 2'). Keep to "
        "≤ 500 rows; if the result set is larger, TOPN it first."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Table title (one line, business-meaningful).",
            },
            "subtitle": {
                "type": "string",
                "description": "Optional one-line subtitle/caption.",
            },
            "columns": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_COLS,
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": (
                                "Column key used to index rows when rows are "
                                "passed as objects. If rows are passed as "
                                "arrays, this is only used as a DOM id."
                            ),
                        },
                        "label": {
                            "type": "string",
                            "description": "Header cell text shown to the user.",
                        },
                        "align": {
                            "type": "string",
                            "enum": sorted(ALLOWED_ALIGN),
                            "description": (
                                "Cell alignment. Default: 'right' for numeric "
                                "format, 'left' otherwise."
                            ),
                        },
                        "format": {
                            "type": "string",
                            "enum": sorted(ALLOWED_FORMAT),
                            "description": (
                                "Value formatting hint. 'number' adds thousand "
                                "separators; 'percent' appends '%'; 'money' "
                                "formats with the `unit` suffix."
                            ),
                        },
                        "unit": {
                            "type": "string",
                            "description": "Unit suffix (e.g., '元', '%').",
                        },
                        "width": {
                            "type": "string",
                            "description": "Optional CSS width (e.g., '120px').",
                        },
                    },
                    "required": ["key", "label"],
                },
            },
            "rows": {
                "type": "array",
                "maxItems": MAX_ROWS,
                "description": (
                    "Either a list of arrays aligned with `columns` (preferred "
                    "for SQL result sets), or a list of objects keyed by "
                    "column `key`."
                ),
            },
            "summary": {
                "type": "string",
                "description": (
                    "Optional one-line takeaway shown under the table "
                    "(e.g., '激光事业部占营收 62%')."
                ),
            },
            "footnote": {
                "type": "string",
                "description": "Optional footnote for口径说明.",
            },
            "source_note": {
                "type": "string",
                "description": (
                    "One-line provenance, e.g., 'M001 · T_FM_MgmtPnL · "
                    "2024Q1-Q4' or '报表 P3/Table 2'."
                ),
            },
            "highlight_rows": {
                "type": "array",
                "items": {"type": "integer"},
                "description": (
                    "Optional row indices (0-based) to highlight — useful "
                    "for top contributors or anomalies."
                ),
            },
        },
        "required": ["title", "columns", "rows"],
    },
}


def _validate(params: dict) -> str | None:
    cols = params.get("columns")
    rows = params.get("rows")
    if not isinstance(cols, list) or not cols:
        return "columns must be a non-empty list"
    if len(cols) > MAX_COLS:
        return f"columns must be ≤ {MAX_COLS}"
    keys = []
    for c in cols:
        if not isinstance(c, dict):
            return "every column must be an object"
        k = c.get("key")
        if not k or not isinstance(k, str):
            return "every column needs a string 'key'"
        if c.get("align") and c["align"] not in ALLOWED_ALIGN:
            return f"column '{k}' align must be one of {sorted(ALLOWED_ALIGN)}"
        if c.get("format") and c["format"] not in ALLOWED_FORMAT:
            return f"column '{k}' format must be one of {sorted(ALLOWED_FORMAT)}"
        keys.append(k)
    if not isinstance(rows, list):
        return "rows must be a list"
    if len(rows) > MAX_ROWS:
        return f"rows must be ≤ {MAX_ROWS}"
    # Rows can be lists or dicts; accept both.
    for i, r in enumerate(rows):
        if isinstance(r, list):
            if len(r) != len(cols):
                return (
                    f"row {i} has {len(r)} values but {len(cols)} columns "
                    f"declared — array rows must align with columns"
                )
        elif isinstance(r, dict):
            missing = [k for k in keys if k not in r]
            if missing:
                return f"row {i} missing keys: {missing[:3]}"
        else:
            return f"row {i} must be an array or object"
    return None


def _normalize_rows(cols: list[dict], rows: list) -> list[list]:
    """Convert dict rows → aligned arrays so the frontend has a stable shape."""
    keys = [c["key"] for c in cols]
    out: list[list] = []
    for r in rows:
        if isinstance(r, list):
            out.append(list(r))
        else:
            out.append([r.get(k) for k in keys])
    return out


def _summary_line(cols: list[dict], rows: list[list]) -> str:
    cols_desc = ", ".join(c.get("label") or c.get("key") for c in cols[:6])
    if len(cols) > 6:
        cols_desc += f", … (+{len(cols) - 6})"
    return f"{len(rows)} row(s) × {len(cols)} col(s)  [{cols_desc}]"


def _make_table_generate() -> Executor:
    def run(params: dict, cwd: str) -> str:
        err = _validate(params)
        if err:
            return f"TableGenerate rejected: {err}"

        cols = params["columns"]
        rows_norm = _normalize_rows(cols, params["rows"])

        spec_payload = {
            "title": params.get("title", ""),
            "subtitle": params.get("subtitle") or "",
            "columns": cols,
            "rows": rows_norm,
            "summary": params.get("summary") or "",
            "footnote": params.get("footnote") or "",
            "source_note": params.get("source_note") or "",
            "highlight_rows": params.get("highlight_rows") or [],
            "analysis_scope": params.get("analysis_scope") or {},
            "semantic": params.get("semantic") or {},
        }

        header = (
            f"Table generated — {params.get('title', '(untitled)')}\n"
            f"Shape: {_summary_line(cols, rows_norm)}"
        )
        if params.get("source_note"):
            header += f"\nSource: {params['source_note']}"
        if params.get("summary"):
            header += f"\nSummary: {params['summary']}"

        return (
            f"{header}\n\n{TABLE_SPEC_OPEN}"
            + json.dumps(spec_payload, ensure_ascii=False)
            + f"{TABLE_SPEC_CLOSE}"
        )

    return run


def extract_table_spec(tool_output: str) -> tuple[str, dict | None]:
    """Pull the TABLE_SPEC block out of a tool output string.

    Returns (cleaned_output, parsed_spec_or_None). The cleaned output has the
    <TABLE_SPEC>...</TABLE_SPEC> block removed so it can be fed back to the
    LLM without the raw JSON payload.
    """
    m = TABLE_SPEC_RE.search(tool_output or "")
    if not m:
        return tool_output, None
    try:
        spec = json.loads(m.group(1))
    except json.JSONDecodeError:
        return tool_output, None
    cleaned = (tool_output[: m.start()] + tool_output[m.end():]).rstrip()
    return cleaned, spec


SPECS: list[tuple[dict, ExecutorFactory]] = [
    (TABLE_GENERATE_SCHEMA, lambda: _make_table_generate()),
]
