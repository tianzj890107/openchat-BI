"""Deterministic policy for deciding whether a generated chart is useful.

The BI agent is allowed to call ``ChartGenerate`` for any tabular result, but
some requests are enumerations rather than analyses.  A list of ontology
objects (for example, ``列出本体里所有业务对象``) often gets represented as a
count column containing only ``1``.  Rendering that column as a bar chart adds
no information, so the web session can skip the chart and keep the table.

This module intentionally does not call an LLM.  It combines a small,
explainable intent classifier with a data-shape check and is therefore safe to
use both during tool execution and in offline tests.
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable


CHART_TOOL_NAMES = {"ChartGenerate", "ChartGenerateMultiDim"}

# Enumeration/list wording seen in ontology and metadata questions.  Keep the
# patterns narrow enough that an analytical question such as "列出各基地采购
# 金额" is not accidentally treated as a plain list.
_LIST_INTENT_RE = re.compile(
    r"(?:列出|列举|罗列|枚举|有哪些|哪些|所有|全部|清单|列表|名单|可分析|支持分析|可供分析|"
    r"业务对象|业务实体|本体(?:里|中)?(?:的)?(?:业务对象|实体|指标|维度|术语))",
    re.IGNORECASE,
)
_ANALYTIC_RE = re.compile(
    r"(?:金额|数量|总额|余额|收入|支出|库存|采购|应收|应付|趋势|分布|占比|构成|"
    r"变化|波动|增长|下降|同比|环比|排名|排行|TOP|统计|汇总|平均|最大|最小|"
    r"多少|情况|异常|问题|原因|根因|对比|偏差|预测|预警)",
    re.IGNORECASE,
)


def is_list_like_intent(question: str | None) -> bool:
    """Return whether *question* asks for an enumeration rather than analysis.

    A list marker is required, while common measure/analysis words override it.
    This makes ``列出本体里所有业务对象`` list-like but keeps
    ``列出各基地采购金额分布`` analytical.
    """

    text = re.sub(r"\s+", "", str(question or "")).strip()
    if not text or not _LIST_INTENT_RE.search(text):
        return False
    return not bool(_ANALYTIC_RE.search(text))


def _numeric_values(values: Iterable[Any]) -> list[float]:
    out: list[float] = []
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            number = float(value)
        elif isinstance(value, str):
            stripped = value.strip().replace(",", "")
            if not stripped or not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", stripped):
                continue
            number = float(stripped)
        else:
            continue
        if math.isfinite(number):
            out.append(number)
    return out


def _series_values(series: Any) -> list[float]:
    if not isinstance(series, list):
        return []
    values: list[Any] = []
    for entry in series:
        if not isinstance(entry, dict):
            continue
        data = entry.get("data")
        if not isinstance(data, list):
            continue
        for item in data:
            # Pie slices are ``{name, value}``; axis charts usually contain
            # scalar values, but accepting ``{value: ...}`` keeps this guard
            # compatible with ECharts-style input too.
            if isinstance(item, dict):
                values.append(item.get("value"))
            else:
                values.append(item)
    return _numeric_values(values)


def has_constant_chart_values(params: dict[str, Any] | None) -> bool:
    """Return true when a chart has at least two numeric points, all equal."""

    values = _series_values((params or {}).get("series"))
    return len(values) >= 2 and all(value == values[0] for value in values[1:])


def has_constant_multidim_values(params: dict[str, Any] | None) -> bool:
    """Return true when every multi-dimensional chart dimension is constant."""

    dimensions = (params or {}).get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        return False
    values: list[float] = []
    for dimension in dimensions:
        if not isinstance(dimension, dict):
            return False
        dim_values = _series_values(dimension.get("series"))
        # A dimension without at least two numeric points is not enough
        # evidence that its chart is degenerate.
        if len(dim_values) < 2:
            return False
        values.extend(dim_values)
    return bool(values) and all(value == values[0] for value in values[1:])


def chart_skip_reason(
    question: str | None,
    tool_name: str,
    params: dict[str, Any] | None,
) -> str | None:
    """Return a user/LLM-facing reason when a chart should not be generated."""

    if tool_name not in CHART_TOOL_NAMES or not is_list_like_intent(question):
        return None
    constant = (
        has_constant_multidim_values(params)
        if tool_name == "ChartGenerateMultiDim"
        else has_constant_chart_values(params)
    )
    if not constant:
        return None
    return (
        "这是枚举/列表型问题，图表数据的数值全部相同（通常每项均为 1），"
        "柱状图无法提供比较信息；保留 TableGenerate 表格即可，请不要重试图表。"
    )


def skipped_chart_output(reason: str) -> str:
    """Build the deterministic tool result sent back to the model."""

    return f"ChartGenerate skipped — {reason}"
