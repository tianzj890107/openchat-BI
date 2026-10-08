#!/usr/bin/env python3
"""交付前闸门 CLI：证据 / 预测披露 / 图表抑制 / 只读 SQL。

用法：
    python scripts/gates.py sql --sql "SELECT 1"
    python scripts/gates.py check --input turn.json
    cat turn.json | python scripts/gates.py check

turn.json 字段（除 answer 外都可选）：
    {
      "answer": "…最终回答…",
      "question": "用户原话（图表抑制判定用）",
      "forecast_kind": "predictive|scenario|stored",
      "forecast_assumption": "用户给出的情景假设",
      "sql": "SELECT …",
      "chart": {"tool": "ChartGenerate", "params": {…}},
      "reconcile": {"parent": 25030, "children": [12000, 13030]},
      "claims": [{"id": "c1", "statement": "…", "level": "INFERENCE",
                  "semantic": {"semantic_type": "PROXY"}, "limitations": ["CONFLICTING_EVIDENCE"]}]
    }

判定规则见 references/07-output-gates.md；实现来自 scripts/vendor/ 下与仓库同源的模块。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

from analysis_policy import (  # noqa: E402
    FORECAST_KIND_PREDICTIVE,
    FORECAST_KIND_SCENARIO,
    FORECAST_KIND_STORED,
)
from chart_policy import chart_skip_reason  # noqa: E402
from forecast_policy import FORECAST_LIMITATION_NOTE, forecast_disclosure_missing  # noqa: E402
from reliability import (  # noqa: E402
    Claim,
    ClaimLevel,
    LimitationType,
    SemanticType,
    ValidationStatus,
    reconcile,
    validate_claims,
)
from sql_guard import _validate_sql as validate_sql  # noqa: E402

FORECAST_KINDS = {
    "predictive": FORECAST_KIND_PREDICTIVE,
    "scenario": FORECAST_KIND_SCENARIO,
    "stored": FORECAST_KIND_STORED,
}

BLOCKED_ANSWER_FALLBACK = """结论

本轮工具检索已完成，但自动证据校验发现最终叙述包含无法由结构化结果确认的数字或确定性判断，因此未展示原候选回答。

当前可确认的证据

- {claims}

后续处理

需要重新执行或补全数据查询的结构化结果后，才能给出包含相关数字的业务结论。"""

NO_NARRATIVE_FALLBACK = """结论

本轮已完成 {tools} 的检索，但在最大执行轮次内没有形成可交付的数据结论。

下一步需要补齐可执行的数据查询、物理字段映射或明确分析口径；当前不把本体操作本身当作最终业务答案。"""


def _claim(raw: dict) -> Claim:
    level = str(raw.get("level") or "FACT").upper()
    try:
        level_value = ClaimLevel(level)
    except ValueError:
        level_value = ClaimLevel.FACT
    limitations = []
    for item in raw.get("limitations") or []:
        try:
            limitations.append(LimitationType(str(item).upper()))
        except ValueError:
            limitations.append(str(item))
    return Claim(
        id=str(raw.get("id") or "claim"),
        statement=str(raw.get("statement") or ""),
        level=level_value,
        scope=raw.get("scope") or {},
        supports=tuple(raw.get("supports") or ()),
        limitations=tuple(limitations),
        confidence=raw.get("confidence"),
        semantic=raw.get("semantic") or {},
    )


def check(payload: dict) -> dict:
    answer = str(payload.get("answer") or "")
    question = payload.get("question")
    hard: list[str] = []
    warnings: list[str] = []

    # 1. 证据闸门：claims 与叙述的一致性
    claims = [_claim(item) for item in (payload.get("claims") or [])]
    if claims:
        result = validate_claims(claims, answer)
        if result.status == ValidationStatus.REJECT:
            hard.extend(result.issues)
        elif result.status == ValidationStatus.ALLOW_WITH_WARNING:
            warnings.extend(result.issues)

    pair = payload.get("reconcile") or None
    if pair and pair.get("parent") is not None:
        outcome = reconcile(pair["parent"], pair.get("children") or [])
        if outcome.status == ValidationStatus.REJECT:
            hard.extend(outcome.issues)

    # 2. 预测披露闸门
    forecast_kind = FORECAST_KINDS.get(str(payload.get("forecast_kind") or "").lower())
    if payload.get("forecast_kind") and not forecast_kind:
        warnings.append("unknown_forecast_kind")
    if forecast_kind:
        missing = forecast_disclosure_missing(forecast_kind, payload.get("forecast_assumption"), answer)
        hard.extend(f"forecast_disclosure:{item}" for item in missing)

    # 3. 图表闸门
    chart = payload.get("chart") or None
    if chart:
        reason = chart_skip_reason(question, str(chart.get("tool") or ""), chart.get("params") or {})
        if reason:
            hard.append(f"chart_suppressed:{reason}")

    # 4. 只读 SQL 闸门
    if payload.get("sql"):
        error = validate_sql(str(payload["sql"]))
        if error:
            hard.append(f"sql_rejected:{error}")

    verdict = "reject" if hard else ("warn" if warnings else "pass")
    return {
        "verdict": verdict,
        "hard_issues": hard,
        "warnings": warnings,
        "fallback": {
            "evidence": BLOCKED_ANSWER_FALLBACK,
            "no_narrative": NO_NARRATIVE_FALLBACK,
            "forecast": FORECAST_LIMITATION_NOTE,
        } if verdict == "reject" else {},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="交付前闸门")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sql = sub.add_parser("sql", help="只读 SQL 守卫")
    p_sql.add_argument("--sql", required=True)

    p_check = sub.add_parser("check", help="跑全部闸门")
    p_check.add_argument("--input", help="turn.json 路径；缺省读 stdin")
    p_check.add_argument("--pretty", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "sql":
        error = validate_sql(args.sql)
        if error:
            print(json.dumps({"ok": False, "error": error}, ensure_ascii=False))
            return 2
        print(json.dumps({"ok": True}, ensure_ascii=False))
        return 0

    raw = (open(args.input, encoding="utf-8").read() if args.input else sys.stdin.read())
    payload = json.loads(raw or "{}")
    report = check(payload)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True,
                     indent=2 if args.pretty else None))
    return 2 if report["verdict"] == "reject" else 0


if __name__ == "__main__":
    raise SystemExit(main())
