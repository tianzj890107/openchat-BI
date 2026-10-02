#!/usr/bin/env python3
"""离线自检：回放冻结用例，校验脚本输出与仓库行为一致。

用法：
    python3 scripts/selfcheck.py            # 回放全部用例
    python3 scripts/selfcheck.py --quiet    # 只输出汇总与失败项

覆盖两部分：
    cases/routing_cases.jsonl  路由决策（route.decide）
    cases/gate_cases.jsonl     交付闸门（gates.check / gates.validate_sql）

用例由仓库评测集冻结而来（见 cases/README.md）。脚本只依赖标准库，
任何一条用例不通过即以非零退出码结束。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import gates  # noqa: E402
import route  # noqa: E402


def _check_routing_expect(decision: dict, expect: dict) -> list[str]:
    problems: list[str] = []
    intent = decision.get("intent") or {}
    for key, want in expect.items():
        if key == "intent_level":
            got = intent.get("level")
        elif key == "forecast_kind":
            got = intent.get("forecast_kind")
            if got != want or decision.get("forecast_kind") != want:
                problems.append(f"forecast_kind: want={want!r} got={got!r}/{decision.get('forecast_kind')!r}")
                continue
            continue
        elif key in ("wants_root_cause", "wants_action", "wants_forecast"):
            got = bool(intent.get(key))
            want = bool(want)
        elif key == "mode_not_in":
            if decision.get("mode") in want:
                problems.append(f"mode_not_in: got={decision.get('mode')!r} in {want!r}")
            continue
        elif key == "required_tools":
            want = list(want or [])
            got = list(decision.get("required_tools") or [])
        elif key == "required_tools_empty":
            got = not decision.get("required_tools")
            want = bool(want)
        elif key == "refusal_category_absent":
            got = not decision.get("refusal_category")
            want = bool(want)
        elif key == "refusal_message_required":
            got = bool(str(decision.get("refusal_message") or "").strip())
            want = bool(want)
        elif key in ("evidence_required", "needs_human"):
            got = bool(decision.get(key))
            want = bool(want)
        else:
            got = decision.get(key)
        if got != want:
            problems.append(f"{key}: want={want!r} got={got!r}")
    return problems


def _check_gate_expect(result: dict, expect: dict) -> list[str]:
    problems: list[str] = []
    for key, want in expect.items():
        if key == "hard_contains":
            hard = " | ".join(result.get("hard_issues") or [])
            for item in want:
                if item not in hard:
                    problems.append(f"hard_contains {item!r} not in {hard!r}")
        elif key == "warnings_contains":
            warnings = " | ".join(result.get("warnings") or [])
            for item in want:
                if item not in warnings:
                    problems.append(f"warnings_contains {item!r} not in {warnings!r}")
        elif key == "error_contains":
            error = str(result.get("error") or "")
            if want not in error:
                problems.append(f"error_contains {want!r} not in {error!r}")
        else:
            got = result.get(key)
            if got != want:
                problems.append(f"{key}: want={want!r} got={got!r}")
    return problems


def run_routing(quiet: bool) -> tuple[int, int]:
    path = os.path.join(ROOT, "cases", "routing_cases.jsonl")
    total = failed = 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if "_provenance" in row:
                continue
            total += 1
            tools = list(row["allowed_tools"]) if "allowed_tools" in row else route.DEFAULT_TOOLS
            decision = route.decide(row.get("question") or "", tools)
            problems = _check_routing_expect(decision, row.get("expect") or {})
            if problems:
                failed += 1
                print(f"FAIL routing {row.get('case_id')}: {row.get('question')!r}")
                for item in problems:
                    print(f"      - {item}")
            elif not quiet:
                print(f"ok   routing {row.get('case_id')}")
    return total, failed


def run_gates(quiet: bool) -> tuple[int, int]:
    path = os.path.join(ROOT, "cases", "gate_cases.jsonl")
    total = failed = 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if "_provenance" in row:
                continue
            total += 1
            payload = row.get("input") or {}
            if row.get("kind") == "sql":
                error = gates.validate_sql(str(payload.get("sql") or ""))
                result = {"ok": error is None, "error": error}
            else:
                result = gates.check(payload)
            problems = _check_gate_expect(result, row.get("expect") or {})
            if problems:
                failed += 1
                print(f"FAIL gate {row.get('case_id')}: {payload}")
                for item in problems:
                    print(f"      - {item}")
            elif not quiet:
                print(f"ok   gate {row.get('case_id')}")
    return total, failed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="冻结用例离线自检")
    parser.add_argument("--quiet", action="store_true", help="只输出汇总与失败项")
    args = parser.parse_args(argv)

    r_total, r_failed = run_routing(args.quiet)
    g_total, g_failed = run_gates(args.quiet)
    total, failed = r_total + g_total, r_failed + g_failed
    print(f"\nrouting: {r_total - r_failed}/{r_total} passed")
    print(f"gates:   {g_total - g_failed}/{g_total} passed")
    print(f"selfcheck: {total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
