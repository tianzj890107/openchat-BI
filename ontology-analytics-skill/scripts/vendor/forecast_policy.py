# vendored from bi_agent/web/session.py (c94d430) — 「预测披露闸门」段落原样摘录。
# 只依赖标准库与同目录的 analysis_policy；FORECAST_KIND_* 取自 analysis_policy。
from __future__ import annotations

import re

from analysis_policy import (
    FORECAST_KIND_PREDICTIVE,
    FORECAST_KIND_SCENARIO,
    FORECAST_KIND_STORED,
)

# ---------------------------------------------------------------------------
# Forecast disclosure gate (batch 5)
#
# A forecast / scenario turn may only be delivered when the answer states the
# data window, the method, the explicit assumption (scenario) and the
# uncertainty.  The repository has no statistical model, so a confidently
# written number — or an invented confidence interval — must be downgraded to a
# limitation instead of being presented as a prediction.  See
# ``docs/specs/analysis-forecast-and-scenario-routing.md`` §7.
# ---------------------------------------------------------------------------
FORECAST_WINDOW_RE = re.compile(
    r"(?:数据窗口|时间窗口|窗口|区间|时间段|过去|历史|截至|同比|环比|口径|"
    r"近\s*\d+\s*(?:个)?(?:月|年|周|天|季度)|\d{4}\s*年)"
)
FORECAST_METHOD_TOKENS = (
    "推演", "推算", "外推", "趋势外推", "按假设", "根据假设", "基于假设",
    "计算方式", "计算方法", "方法",
)
FORECAST_UNCERTAINTY_TOKENS = (
    "不确定性", "不确定", "未经验证", "限制", "不足以", "无法确认",
    "无法给出区间", "仅供参考", "不能视为", "无法保证",
)
FORECAST_ASSUMPTION_TOKENS = ("假设", "如果", "前提", "条件下", "情景", "情形")
# Statistical vocabulary this repository cannot legitimately produce.
FORECAST_FABRICATION_RE = re.compile(
    r"(?:置信区间|置信度|置信水平|显著性|季节性|回测|准确率|误差率|拟合优度)"
)
# A stored plan/budget record presented as a model-generated prediction.
FORECAST_MODEL_CLAIM_RE = re.compile(
    r"(?:模型(?:给出|输出|生成|预测|推算)|预测结论|算法预测|机器学习|AI\s*预测)"
)

FORECAST_LIMITATION_NOTE = (
    "说明：当前系统不具备统计预测能力，以上内容不是统计预测结论。"
    "如需继续，可提供明确假设后做情景推演、改为查询系统中已有的计划或预算数据，"
    "或补充数据范围后重试。"
)


def forecast_disclosure_missing(
    forecast_kind: str | None,
    assumption: str | None,
    answer: str | None,
) -> list[str]:
    """Return the disclosure items a forecast answer failed to state."""

    text = str(answer or "")
    if not text.strip() or not forecast_kind:
        return []
    missing: list[str] = []
    if FORECAST_FABRICATION_RE.search(text):
        missing.append("fabricated_statistics")
    if forecast_kind == FORECAST_KIND_STORED:
        if FORECAST_MODEL_CLAIM_RE.search(text):
            missing.append("stored_presented_as_model_output")
        return missing
    if forecast_kind == FORECAST_KIND_SCENARIO:
        disclosed = any(token in text for token in FORECAST_ASSUMPTION_TOKENS)
        if not disclosed and assumption:
            disclosed = str(assumption) in text
        if not disclosed:
            missing.append("assumption")
    has_window = bool(FORECAST_WINDOW_RE.search(text))
    has_method = any(token in text for token in FORECAST_METHOD_TOKENS)
    has_uncertainty = any(token in text for token in FORECAST_UNCERTAINTY_TOKENS)
    if not (has_window or has_method or has_uncertainty):
        missing.append("window_or_method_or_limitation")
    return missing
