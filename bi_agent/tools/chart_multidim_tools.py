"""
ChartGenerateMultiDim — multi-dimensional chart with a dimension selector.

Produced by the agent during a "深入洞察" (deep-insight drill-down) task.
Each `dimensions[i]` is a self-contained chart spec for one breakdown of
the same metric (e.g. by 事业部 / by 产品线 / by 区域). The Web UI renders
one chart card with a dropdown; switching dim is a pure ECharts.setOption
swap — zero re-query latency.

Spec extraction tag: <MULTIDIM_CHART_SPEC>...</MULTIDIM_CHART_SPEC>
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable

from .chart_tools import SUPPORTED_TYPES, _echarts_option, _slug, _validate

Executor = Callable[[dict, str], str]
ExecutorFactory = Callable[[], Executor]


MULTIDIM_SPEC_OPEN = "<MULTIDIM_CHART_SPEC>"
MULTIDIM_SPEC_CLOSE = "</MULTIDIM_CHART_SPEC>"
MULTIDIM_SPEC_RE = re.compile(
    re.escape(MULTIDIM_SPEC_OPEN) + r"(.*?)" + re.escape(MULTIDIM_SPEC_CLOSE),
    re.DOTALL,
)

MIN_DIMS = 2
MAX_DIMS = 5


CHART_GENERATE_MULTIDIM_SCHEMA = {
    "name": "ChartGenerateMultiDim",
    "description": (
        "Render a MULTI-DIMENSIONAL chart with a dimension dropdown for "
        "深入洞察 (deep-insight) drill-down tasks. Use this ONLY after the "
        "user clicks the '深入洞察' button on an existing chart, or "
        "explicitly asks for a 维度洞察 / 维度下钻 over a metric. The "
        "workflow is: (1) RelationLookup / EntityDescribe on the source "
        "metric to find its applicable dimensions in the ontology; "
        "(2) pick the 2–5 most business-meaningful ones; (3) for each, "
        "run ONE SQLRun query that GROUPs BY that dimension while keeping "
        "the SAME time/scope filters as the original chart; (4) call this "
        "tool once with all dim breakdowns. The UI renders a single chart "
        "with a dropdown — switching dim is instant. Do NOT use this for a "
        "normal one-shot chart (use ChartGenerate). All dimension data "
        "MUST share consistent caliber (same time window, same filters) "
        "or the comparison is misleading."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Top-level title, e.g., '营业收入 · 维度洞察'.",
            },
            "subtitle": {
                "type": "string",
                "description": "Optional one-line caption.",
            },
            "metric_code": {
                "type": "string",
                "description": (
                    "Ontology code of the metric being drilled down "
                    "(e.g., 'M001'). Required for traceability."
                ),
            },
            "source_note": {
                "type": "string",
                "description": (
                    "Provenance shared by all dim queries, e.g., "
                    "'M001 · T_FM_MgmtPnL · 2024Q1-Q4 · 全部事业部'. "
                    "All dim breakdowns must use this exact filter."
                ),
            },
            "default_dim": {
                "type": "string",
                "description": (
                    "Key of the dimension shown by default (must match "
                    "one of `dimensions[].key`)."
                ),
            },
            "dimensions": {
                "type": "array",
                "minItems": MIN_DIMS,
                "maxItems": MAX_DIMS,
                "description": (
                    "List of dimension breakdowns. Each entry is a "
                    "self-contained chart for one dim of the same metric."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": (
                                "Stable id, e.g., 'by_bu', 'by_product', "
                                "'by_region', 'by_time_quarter'."
                            ),
                        },
                        "label": {
                            "type": "string",
                            "description": (
                                "Human-readable label shown in the dropdown, "
                                "e.g., '按事业部', '按产品线', '按客户'."
                            ),
                        },
                        "chart_type": {
                            "type": "string",
                            "enum": sorted(SUPPORTED_TYPES),
                            "description": (
                                "Chart type for THIS dim. Time-like → line/area; "
                                "category → bar; long labels → horizontal_bar; "
                                "share → pie."
                            ),
                        },
                        "x_axis": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Category labels (required for non-pie types)."
                            ),
                        },
                        "series": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": (
                                "Same shape as ChartGenerate.series. For pie: "
                                "one entry with data=[{name, value}]."
                            ),
                        },
                        "unit": {"type": "string"},
                        "y_axis_name": {"type": "string"},
                        "summary": {
                            "type": "string",
                            "description": (
                                "Optional one-line takeaway for THIS dim "
                                "(e.g., '激光事业部贡献 62% 营收')."
                            ),
                        },
                    },
                    "required": ["key", "label", "chart_type", "series"],
                },
            },
            "summary": {
                "type": "string",
                "description": (
                    "Top-level takeaway across all dims, shown above the "
                    "chart (e.g., '激光事业部 / 整机产品线 / 华东区为主要 "
                    "贡献者,合计占 78% 营收')."
                ),
            },
            "footnote": {"type": "string"},
        },
        "required": ["title", "metric_code", "default_dim", "dimensions"],
    },
}


def _validate_multidim(params: dict) -> str | None:
    dims = params.get("dimensions")
    if not isinstance(dims, list) or len(dims) < MIN_DIMS:
        return f"dimensions must be a list with ≥ {MIN_DIMS} entries"
    if len(dims) > MAX_DIMS:
        return f"dimensions must have ≤ {MAX_DIMS} entries (got {len(dims)})"

    keys: list[str] = []
    for i, d in enumerate(dims):
        if not isinstance(d, dict):
            return f"dimensions[{i}] must be an object"
        for req in ("key", "label", "chart_type", "series"):
            if not d.get(req):
                return f"dimensions[{i}] missing required field '{req}'"
        if d["key"] in keys:
            return f"duplicate dimension key '{d['key']}'"
        keys.append(d["key"])
        # Reuse the single-chart validator for axis/series alignment.
        single_check = _validate({
            "chart_type": d["chart_type"],
            "x_axis": d.get("x_axis"),
            "series": d["series"],
        })
        if single_check:
            return f"dimensions[{i}] ({d['key']}): {single_check}"

    default_dim = params.get("default_dim")
    if default_dim not in keys:
        return (
            f"default_dim '{default_dim}' must match one of dimensions[].key "
            f"(have: {keys})"
        )

    if not params.get("metric_code"):
        return "metric_code is required for traceability (e.g., 'M001')"
    return None


def _build_dim_payload(d: dict, top_source: str) -> dict[str, Any]:
    """Build a per-dim payload with a pre-rendered ECharts option."""
    params_for_option = {
        "chart_type": d["chart_type"],
        "title": d.get("label") or d.get("key") or "",
        "subtitle": d.get("summary") or "",
        "x_axis": d.get("x_axis") or [],
        "series": d["series"],
        "y_axis_name": d.get("y_axis_name") or "",
        "unit": d.get("unit") or "",
        "source_note": top_source,
    }
    option = _echarts_option(params_for_option)
    return {
        "key": d["key"],
        "label": d["label"],
        "chart_type": d["chart_type"],
        "summary": d.get("summary") or "",
        "option": option,
    }


def _write_standalone_html(spec: dict[str, Any], out_path: Path) -> None:
    """Standalone HTML with a working dimension dropdown."""
    spec_json = json.dumps(spec, ensure_ascii=False)
    title = spec.get("title", "维度洞察图表")
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
  html, body {{ margin: 0; height: 100%; background: #121212; color: #FFFFFF;
    font-family: "PingFang SC", "SF Pro Display", -apple-system, sans-serif; }}
  #toolbar {{ display: flex; gap: 12px; align-items: center; padding: 12px 16px;
    border-bottom: 1px solid #424242; }}
  #toolbar label {{ font-size: 12px; color: #9E9E9E; }}
  #dim-select {{ background: #1F1F1F; color: #FFFFFF; border: 1px solid #555555;
    padding: 6px 10px; border-radius: 8px; font-size: 13px;
    font-family: "PingFang SC", "SF Pro Display", -apple-system, sans-serif; }}
  #chart {{ width: 100vw; height: calc(100vh - 49px); }}
</style>
<script src="/static/vendor/echarts.min.js"></script>
</head>
<body>
<div id="toolbar">
  <label for="dim-select">维度</label>
  <select id="dim-select"></select>
</div>
<div id="chart"></div>
<script>
  const SPEC = {spec_json};
  const select = document.getElementById('dim-select');
  for (const d of SPEC.dimensions) {{
    const opt = document.createElement('option');
    opt.value = d.key;
    opt.textContent = d.label;
    if (d.key === SPEC.default_dim) opt.selected = true;
    select.appendChild(opt);
  }}
  const chart = echarts.init(document.getElementById('chart'));
  function show(key) {{
    const d = SPEC.dimensions.find((x) => x.key === key) || SPEC.dimensions[0];
    chart.setOption(d.option, true);
  }}
  show(SPEC.default_dim);
  select.addEventListener('change', (e) => show(e.target.value));
  window.addEventListener('resize', () => chart.resize());
</script>
</body>
</html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")


def _make_chart_generate_multidim() -> Executor:
    def run(params: dict, cwd: str) -> str:
        err = _validate_multidim(params)
        if err:
            return f"ChartGenerateMultiDim rejected: {err}"

        top_source = params.get("source_note") or ""
        try:
            dim_payloads = [
                _build_dim_payload(d, top_source) for d in params["dimensions"]
            ]
        except Exception as e:
            return f"ChartGenerateMultiDim build error: {type(e).__name__}: {e}"

        spec_payload = {
            "title": params.get("title", ""),
            "subtitle": params.get("subtitle") or "",
            "metric_code": params["metric_code"],
            "source_note": top_source,
            "default_dim": params["default_dim"],
            "dimensions": dim_payloads,
            "summary": params.get("summary") or "",
            "footnote": params.get("footnote") or "",
        }

        title = spec_payload["title"] or "multidim-chart"
        ts = time.strftime("%Y%m%d-%H%M%S")
        filename = f"multidim-{ts}-{_slug(title)}.html"
        out_dir = Path(cwd) / "bi_charts"
        out_path = out_dir / filename
        try:
            _write_standalone_html(spec_payload, out_path)
            saved_at = (
                str(out_path.relative_to(cwd))
                if out_path.is_relative_to(cwd)
                else str(out_path)
            )
        except Exception as e:
            saved_at = f"(save failed: {e})"
        spec_payload["saved_path"] = saved_at

        dim_summary = ", ".join(
            f"{d['label']}({len((d.get('x_axis') or [])) or '?'})"
            for d in params["dimensions"]
        )
        header = (
            f"Multi-dim chart generated — {title}\n"
            f"Metric: {params['metric_code']}\n"
            f"Dimensions ({len(params['dimensions'])}): {dim_summary}\n"
            f"Default: {params['default_dim']}\n"
            f"Saved: {saved_at}"
        )
        if top_source:
            header += f"\nSource: {top_source}"
        if params.get("summary"):
            header += f"\nSummary: {params['summary']}"

        return (
            f"{header}\n\n{MULTIDIM_SPEC_OPEN}"
            + json.dumps(spec_payload, ensure_ascii=False)
            + f"{MULTIDIM_SPEC_CLOSE}"
        )

    return run


def extract_multidim_chart_spec(tool_output: str) -> tuple[str, dict | None]:
    """Pull the MULTIDIM_CHART_SPEC block out of a tool output string."""
    m = MULTIDIM_SPEC_RE.search(tool_output or "")
    if not m:
        return tool_output, None
    try:
        spec = json.loads(m.group(1))
    except json.JSONDecodeError:
        return tool_output, None
    cleaned = (tool_output[: m.start()] + tool_output[m.end():]).rstrip()
    return cleaned, spec


SPECS: list[tuple[dict, ExecutorFactory]] = [
    (CHART_GENERATE_MULTIDIM_SCHEMA, lambda: _make_chart_generate_multidim()),
]
