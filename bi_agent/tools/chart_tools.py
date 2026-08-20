"""
Chart generation tool — emits an ECharts option spec and saves a standalone
HTML so charts are viewable both in the Web UI (inline) and the CLI (open
the HTML file). The spec is embedded in the tool output between
<CHART_SPEC>...</CHART_SPEC> tags so the WebSession can strip + extract it.
"""

from __future__ import annotations

import json
import re
import time
from html import escape
from pathlib import Path
from typing import Any, Callable

from ..paths import CHARTS_DIR, project_path
from ..reliability import Measure, SemanticType, validate_chart_measures

Executor = Callable[[dict, str], str]
ExecutorFactory = Callable[[], Executor]


CHART_SPEC_OPEN = "<CHART_SPEC>"
CHART_SPEC_CLOSE = "</CHART_SPEC>"
CHART_SPEC_RE = re.compile(
    re.escape(CHART_SPEC_OPEN) + r"(.*?)" + re.escape(CHART_SPEC_CLOSE),
    re.DOTALL,
)

SUPPORTED_TYPES = {"bar", "line", "pie", "scatter", "area", "horizontal_bar"}

# Shared with the CPQ-style light result surface. Keeping the palette here
# makes charts rendered in the conversation, history and standalone HTML use
# the same restrained colors instead of black canvases and fluorescent text.
# CEO 驾驶舱使用的克制语义色：蓝、黄、绿、红。图表与驾驶舱共用这组
# 颜色，避免生成 HTML 时出现高饱和荧光色或每张图使用不同的主题。
CHART_PALETTE = [
    "#0B7FF3",  # CEO blue
    "#E8B339",  # CEO yellow
    "#28C79D",  # CEO green
    "#F05A5A",  # CEO red
    "#64B5FF",  # light blue
    "#FF9F43",  # warm orange
    "#8B5CF6",  # muted violet
]
CHART_FONT_FAMILY = '"PingFang SC", "SF Pro Display", -apple-system, sans-serif'


CHART_GENERATE_SCHEMA = {
    "name": "ChartGenerate",
    "description": (
        "Render a chart for tabular data you already have in hand. Valid "
        "sources: a SQLRun result set, a table extracted from an uploaded "
        "report (PDF/DOCX Markdown tables), or a computation you performed "
        "over either. Use it when the data has more than one row/column "
        "worth visualizing — time series, dimension breakdowns, "
        "distributions, shares. For enumeration/list questions (for example "
        "listing ontology business objects), if the plotted measure is the "
        "same for every row (often all 1), use TableGenerate only because a "
        "chart adds no comparison value. Do NOT call it for a single scalar, for "
        "raw SQL not yet executed, or with fabricated numbers — every data "
        "point must be traceable to a report table or a tool result. The "
        "chart renders inline in the Web UI and is also saved as a "
        "standalone HTML under `dataset/charts/`. Always set `source_note` with "
        "provenance (e.g., '报表 P3/Table 2' or 'M001 · T_FM_MgmtPnL · "
        "2024Q1-Q4')."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "chart_type": {
                "type": "string",
                "enum": sorted(SUPPORTED_TYPES),
                "description": (
                    "bar: vertical bars by category. "
                    "horizontal_bar: bars laid horizontally (good for long labels). "
                    "line: time series or ordered x-axis. "
                    "area: line with filled area (trends). "
                    "scatter: x/y points (correlation). "
                    "pie: share of a whole (one series only; data must be "
                    "list of {name, value})."
                ),
            },
            "title": {"type": "string", "description": "Chart title."},
            "subtitle": {"type": "string", "description": "Optional subtitle/caption."},
            "x_axis": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Category labels on the x-axis (required for bar/line/"
                    "area/horizontal_bar). Ignored for pie."
                ),
            },
            "series": {
                "type": "array",
                "description": (
                    "Data series. For bar/line/area/scatter/horizontal_bar: "
                    "[{name: str, data: [number, ...]}, ...] where each "
                    "series' data aligns with x_axis. For pie: exactly one "
                    "entry with data = [{name: str, value: number}, ...]."
                ),
                "items": {"type": "object"},
            },
            "y_axis_name": {"type": "string", "description": "Y-axis label (e.g., '金额(元)')."},
            "unit": {"type": "string", "description": "Unit suffix for values (e.g., '元')."},
            "source_note": {
                "type": "string",
                "description": "One-line provenance, e.g., 'M001 · T_FM_MgmtPnL · 2024Q1-Q4'.",
            },
        },
        "required": ["chart_type", "title", "series"],
    },
}


def _slug(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", (text or "chart")).strip("-")
    return (s[:limit] or "chart").lower()


def _validate(params: dict) -> str | None:
    ct = params.get("chart_type")
    if ct not in SUPPORTED_TYPES:
        return f"chart_type must be one of {sorted(SUPPORTED_TYPES)}"
    series = params.get("series")
    if not isinstance(series, list) or not series:
        return "series must be a non-empty list"
    # Optional semantic metadata is accepted for newer callers while old chart
    # payloads remain valid. A warning is surfaced as a rejection only when a
    # direct comparison is unsafe; display-only charts may omit the metadata.
    metadata = []
    for item in series:
        if isinstance(item, dict) and any(k in item for k in ("unit", "semantic_type", "scope")):
            try:
                metadata.append(Measure(
                    name=str(item.get("name") or "series"), value=0,
                    unit=str(item.get("unit") or params.get("unit") or ""),
                    semantic_type=SemanticType(str(item.get("semantic_type") or "OBSERVED").upper()),
                    scope=item.get("scope") or {},
                ))
            except (ValueError, TypeError):
                return "series semantic_type must be a supported semantic type"
    if len(metadata) >= 2:
        comparison = validate_chart_measures(metadata)
        if not comparison.ok:
            return "chart comparison rejected: " + "; ".join(comparison.issues)
    if ct == "pie":
        if len(series) != 1:
            return "pie charts need exactly one series entry"
        data = series[0].get("data")
        if not isinstance(data, list) or not data:
            return "pie series.data must be a non-empty list of {name, value}"
        for d in data:
            if not isinstance(d, dict) or "name" not in d or "value" not in d:
                return "pie slices must be objects with 'name' and 'value'"
    else:
        x_axis = params.get("x_axis")
        if not isinstance(x_axis, list) or not x_axis:
            return f"{ct} charts require a non-empty x_axis"
        for s in series:
            data = s.get("data")
            if not isinstance(data, list):
                return "every series.data must be a list"
            if len(data) != len(x_axis):
                return (
                    f"series '{s.get('name', '?')}' has {len(data)} points but "
                    f"x_axis has {len(x_axis)} labels — they must match"
                )
    return None


def _echarts_option(params: dict) -> dict[str, Any]:
    """Build a sane ECharts option from the simplified params."""
    ct = params["chart_type"]
    title = params["title"]
    subtitle = params.get("subtitle") or ""
    series = params["series"]
    unit = params.get("unit") or ""
    y_name = params.get("y_axis_name") or ""

    base: dict[str, Any] = {
        "backgroundColor": "transparent",
        "title": {
            "text": title,
            "subtext": subtitle,
            "left": 14,
            "top": 10,
            "textStyle": {
                "color": "#1F2023", "fontSize": 14, "fontWeight": "600",
                "fontFamily": CHART_FONT_FAMILY,
            },
            "subtextStyle": {
                "color": "#6B7280", "fontSize": 11,
                "fontFamily": CHART_FONT_FAMILY,
            },
        },
        "color": CHART_PALETTE,
        "textStyle": {"color": "#374151", "fontFamily": CHART_FONT_FAMILY},
        "tooltip": {
            "trigger": "item" if ct == "pie" else "axis",
            "backgroundColor": "#FFFFFF",
            "borderColor": "#E7E7EA",
            "borderWidth": 1,
            "textStyle": {"color": "#1F2023", "fontFamily": CHART_FONT_FAMILY},
            "axisPointer": {"type": "shadow"},
        },
        "legend": {
            "top": 36,
            "right": 14,
            "textStyle": {"color": "#374151", "fontFamily": CHART_FONT_FAMILY},
            "icon": "roundRect",
            "itemWidth": 10,
            "itemHeight": 10,
        },
        "grid": {"left": 18, "right": 16, "top": 80, "bottom": 40, "containLabel": True},
    }

    if ct == "pie":
        pie_series = {
            "type": "pie",
            "radius": ["40%", "70%"],
            "center": ["50%", "56%"],
            "avoidLabelOverlap": True,
            "itemStyle": {"borderColor": "#F7F7F8", "borderWidth": 2},
            "label": {
                "color": "#374151", "formatter": "{b}: {d}%",
                "fontFamily": CHART_FONT_FAMILY,
            },
            "data": series[0]["data"],
        }
        base["series"] = [pie_series]
        base["legend"]["show"] = False
        return base

    # Axis-based charts
    x_axis = params.get("x_axis", [])
    axis_fg = {"color": "#374151", "fontFamily": CHART_FONT_FAMILY}
    grid_line = {"show": True, "lineStyle": {"color": "#E7E7EA"}}

    if ct == "horizontal_bar":
        base["xAxis"] = {
            "type": "value",
            "name": y_name,
            "nameTextStyle": {"color": "#6B7280", "fontFamily": CHART_FONT_FAMILY},
            "axisLabel": axis_fg,
            "splitLine": grid_line,
            "axisLine": {"lineStyle": {"color": "#D9D9E3"}},
        }
        base["yAxis"] = {
            "type": "category",
            "data": x_axis,
            "axisLabel": axis_fg,
            "axisLine": {"lineStyle": {"color": "#D9D9E3"}},
        }
    else:
        base["xAxis"] = {
            "type": "category",
            "data": x_axis,
            "axisLabel": axis_fg,
            "axisLine": {"lineStyle": {"color": "#D9D9E3"}},
        }
        base["yAxis"] = {
            "type": "value",
            "name": y_name,
            "nameTextStyle": {"color": "#6B7280", "fontFamily": CHART_FONT_FAMILY},
            "axisLabel": {**axis_fg, "formatter": ("{value}" + unit) if unit else "{value}"},
            "splitLine": grid_line,
            "axisLine": {"lineStyle": {"color": "#D9D9E3"}},
        }

    echarts_series: list[dict[str, Any]] = []
    for s in series:
        entry: dict[str, Any] = {"name": s.get("name", ""), "data": s.get("data", [])}
        if ct == "bar":
            entry["type"] = "bar"
            entry["barMaxWidth"] = 28
            entry["itemStyle"] = {"borderRadius": [2, 2, 0, 0]}
        elif ct == "horizontal_bar":
            entry["type"] = "bar"
            entry["barMaxWidth"] = 20
            entry["itemStyle"] = {"borderRadius": [0, 2, 2, 0]}
        elif ct == "line":
            entry["type"] = "line"
            entry["smooth"] = True
            entry["symbol"] = "circle"
            entry["symbolSize"] = 6
        elif ct == "area":
            entry["type"] = "line"
            entry["smooth"] = True
            entry["areaStyle"] = {"opacity": 0.15}
        elif ct == "scatter":
            entry["type"] = "scatter"
            entry["symbolSize"] = 10
        echarts_series.append(entry)
    base["series"] = echarts_series
    return base


def _write_standalone_html(option: dict[str, Any], out_path: Path, title: str) -> None:
    # JSON is embedded inside a <script>; escape HTML-significant characters
    # so a title/source supplied by a model or report cannot terminate the
    # script element. The browser receives the same JSON values after parse.
    option_json = (
        json.dumps(option, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    safe_title = escape(str(title or "chart"), quote=False)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{safe_title}</title>
<style>
  html, body {{ margin: 0; height: 100%; background: #F7F7F8; color: #1F2023;
    font-family: "PingFang SC", "SF Pro Display", -apple-system, sans-serif; }}
  #chart {{ width: 100vw; height: 100vh; }}
</style>
<script src="/static/vendor/echarts.min.js"></script>
</head>
<body>
<div id="chart"></div>
<script>
  const chart = echarts.init(document.getElementById('chart'));
  chart.setOption({option_json});
  window.addEventListener('resize', () => chart.resize());
</script>
</body>
</html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")


def _make_chart_generate() -> Executor:
    def run(params: dict, cwd: str) -> str:
        err = _validate(params)
        if err:
            return f"ChartGenerate rejected: {err}"

        try:
            option = _echarts_option(params)
        except Exception as e:
            return f"ChartGenerate build error: {type(e).__name__}: {e}"

        title = params.get("title", "chart")
        ts = time.strftime("%Y%m%d-%H%M%S")
        out_dir = project_path(cwd, CHARTS_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = f"chart-{ts}-{_slug(title)}"
        out_path = out_dir / f"{stem}.html"
        suffix = 2
        while out_path.exists():
            out_path = out_dir / f"{stem}-{suffix}.html"
            suffix += 1
        try:
            _write_standalone_html(option, out_path, title)
            saved_at = str(out_path.relative_to(cwd)) if out_path.is_relative_to(cwd) else str(out_path)
        except Exception as e:
            saved_at = f"(save failed: {e})"

        series_info = []
        ct = params["chart_type"]
        if ct == "pie":
            pts = params["series"][0].get("data", [])
            series_info.append(f"1 series, {len(pts)} slice(s)")
        else:
            for s in params["series"]:
                series_info.append(f"{s.get('name', '?')}: {len(s.get('data', []))} pts")

        header = (
            f"Chart generated — {ct} · {title}\n"
            f"Saved: {saved_at}\n"
            f"Series: {'; '.join(series_info)}"
        )
        if params.get("source_note"):
            header += f"\nSource: {params['source_note']}"

        # Embed the full option spec for the Web UI to extract. The
        # WebSession strips this block before feeding the tool result
        # back to the LLM so it doesn't pollute the conversation.
        spec_payload = {
            "option": option,
            "title": title,
            "chart_type": ct,
            "saved_path": saved_at,
        }
        return (
            f"{header}\n\n{CHART_SPEC_OPEN}"
            + json.dumps(spec_payload, ensure_ascii=False)
            + f"{CHART_SPEC_CLOSE}"
        )
    return run


def extract_chart_spec(tool_output: str) -> tuple[str, dict | None]:
    """Pull the CHART_SPEC block out of a tool output string.

    Returns (cleaned_output, parsed_spec_or_None). The cleaned output has the
    <CHART_SPEC>...</CHART_SPEC> block removed so it can be fed back to the
    LLM without the raw JSON payload.
    """
    m = CHART_SPEC_RE.search(tool_output or "")
    if not m:
        return tool_output, None
    try:
        spec = json.loads(m.group(1))
    except json.JSONDecodeError:
        return tool_output, None
    cleaned = (tool_output[: m.start()] + tool_output[m.end():]).rstrip()
    return cleaned, spec


SPECS: list[tuple[dict, ExecutorFactory]] = [
    (CHART_GENERATE_SCHEMA, lambda: _make_chart_generate()),
]
