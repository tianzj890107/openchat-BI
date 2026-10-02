#!/usr/bin/env python3
"""确定性路由 CLI（Cognitive Policy 决策快照）。

用法：
    python scripts/route.py --question "2025年采购金额合计是多少" --allowed-tools "Ontology-MetricQuery,Ontology-FactQuery,AskUser"
    python scripts/route.py --batch cases/routing_cases.jsonl > decisions.jsonl
    python scripts/route.py --question "帮我看看" --pretty

输出字段、枚举与优先级见 references/06-routing-rules.md；规则正文在 scripts/vendor/analysis_policy.py。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

from analysis_policy import (  # noqa: E402
    build_cognitive_policy_decision,
    classify_intent,
)

#: 默认工具集 = 数据分析模式的 14 个工具（见 references/08-tools-and-sources.md）。
DEFAULT_TOOLS = [
    "Ontology-SemanticQuery",
    "Ontology-TermDisambiguate",
    "MetricCalculation",
    "Ontology-RelationQuery",
    "Ontology-EntityDescribe",
    "ListBusinessObjects",
    "Ontology-MetricQuery",
    "Ontology-FactQuery",
    "ListTables",
    "DescribeTable",
    "ChartGenerate",
    "ChartGenerateMultiDim",
    "TableGenerate",
    "AskUser",
]


def decide(question: str, allowed_tools) -> dict:
    """返回路由决策：认知策略字段 + 意图分类字段。

    ``intent`` 子对象与仓库评测器 ``eval_policy`` 使用同一个
    ``classify_intent``，因此脚本输出可与其 ``intent_level`` /
    ``wants_root_cause`` / ``wants_action`` / ``wants_forecast`` 断言对齐。
    """

    decision = dict(build_cognitive_policy_decision(question, allowed_tools))
    intent = classify_intent(question)
    decision["intent"] = {
        "level": intent.level,
        "wants_root_cause": bool(intent.wants_root_cause),
        "wants_action": bool(intent.wants_action),
        "wants_forecast": bool(intent.wants_forecast),
        "forecast_kind": intent.forecast_kind,
    }
    return decision


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="确定性路由决策（Cognitive Policy）")
    parser.add_argument("--question", help="用户原话")
    parser.add_argument("--allowed-tools", default=None,
                        help="逗号分隔的工具白名单；缺省＝默认 14 个工具")
    parser.add_argument("--batch", help="JSONL 文件，每行 {question, allowed_tools}")
    parser.add_argument("--pretty", action="store_true", help="缩进输出")
    args = parser.parse_args(argv)

    if args.batch:
        with open(args.batch, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if "_provenance" in row:
                    continue
                # 显式给出的 allowed_tools 一律采用（包括空列表＝无可用工具，
                # 用于复现 CAPABILITY_LIMITATION）；缺省才回落到默认 14 个工具。
                tools = list(row["allowed_tools"]) if "allowed_tools" in row else DEFAULT_TOOLS
                decision = decide(row.get("question") or "", tools)
                print(json.dumps({"question": row.get("question"), **decision},
                                 ensure_ascii=False, sort_keys=True))
        return 0

    if not args.question:
        parser.error("需要 --question 或 --batch")

    tools = (DEFAULT_TOOLS if args.allowed_tools is None
             else [item.strip() for item in args.allowed_tools.split(",") if item.strip()])
    decision = decide(args.question, tools)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True,
                     indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
