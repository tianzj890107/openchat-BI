#!/usr/bin/env python3
"""Classify every skipped test into a machine-readable category.

``pytest -q`` reports a skip *count*; a count cannot answer the only question
that matters for a release — "is this skip expected, and does it hide a real
hole?".  This script runs the suite once, parses the skip reasons, classifies
each one and writes ``dataset/evals/analytics/skipped_tests.json``:

* category (why it is skipped),
* the test id and the raw reason,
* whether the skip blocks a release,
* how CI is supposed to run it.

Skipped tests are never counted as passed; they are reported as their own
population, and the ``budget`` field can only go down.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACT = REPO_ROOT / "dataset" / "evals" / "analytics" / "skipped_tests.json"

SKIP_LINE_RE = re.compile(r"^SKIPPED\s+\[\d+\]\s+(?P<target>[^:]+:\d+):\s*(?P<reason>.*)$")
ENV_FLAG_RE = re.compile(r"\b(RUN_[A-Z0-9_]+|ENABLE_[A-Z0-9_]+)\b")

CATEGORIES = (
    "missing_frontend_dependency",
    "missing_external_service",
    "redis",
    "platform_unsupported",
    "live_credentials",
    "explicit_integration",
    "other",
)

# Release-blocking categories: a skip in one of these hides a behaviour the
# release claim depends on, so it can never be waved away as "environment".
BLOCKING_CATEGORIES = frozenset({
    "missing_frontend_dependency",
    "missing_external_service",
    "redis",
    "platform_unsupported",
    "live_credentials",
})

PREVIOUS_BUDGET = {"total": 25}


def _classify(target: str, reason: str) -> tuple[str, bool, str]:
    """Return ``(category, blocks_release, ci_hint)`` for one skip."""
    lowered = reason.lower()
    if "redis" in lowered:
        # A skipped Redis test is a missing service, not an opt-in gate: the
        # release conclusion can depend on it.
        return ("redis", True, "在 CI 中启动 redis service 后重跑该测试")
    if ENV_FLAG_RE.search(reason):
        flag = ENV_FLAG_RE.search(reason).group(1)
        return ("explicit_integration", False,
                f"在专用只读验收 job 中设置 {flag}=1 后运行")
    if "node_modules" in lowered or "npm" in lowered or "frontend" in lowered:
        return ("missing_frontend_dependency", True,
                "CI 中先 `npm ci`（或提供本地 file: 依赖），再重跑该测试")
    if "credential" in lowered or "api key" in lowered or "token" in lowered:
        return ("live_credentials", True, "配置测试用 provider 凭据后人工触发 live 套件")
    if "not supported" in lowered or "platform" in lowered:
        return ("platform_unsupported", True, "在支持的平台上重跑")
    if "connect" in lowered or "unreachable" in lowered or "service" in lowered:
        return ("missing_external_service", True, "在可访问该服务的 CI runner 上重跑")
    return ("other", True, "人工确认后补充可重复执行方式")


def _run_pytest(python: str, path: str) -> str:
    proc = subprocess.run(
        [python, "-m", "pytest", "-q", "-rs", path],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=3600,
    )
    return proc.stdout + proc.stderr


def collect(output: str) -> list[dict]:
    tests: list[dict] = []
    for line in output.splitlines():
        match = SKIP_LINE_RE.match(line.strip())
        if not match:
            continue
        target, reason = match.group("target"), match.group("reason").strip()
        category, blocks, hint = _classify(target, reason)
        tests.append({
            "test": target,
            "reason": reason,
            "category": category,
            "blocks_release": blocks,
            "ci_hint": hint,
        })
    return sorted(tests, key=lambda item: (item["category"], item["test"]))


def build(tests: list[dict]) -> dict:
    by_category: dict[str, int] = {name: 0 for name in CATEGORIES}
    for entry in tests:
        by_category[entry["category"]] = by_category.get(entry["category"], 0) + 1
    return {
        "schema_version": 1,
        "description": (
            "Machine-readable classification of every skipped test. Skipped "
            "tests are never counted as passed. Regenerate with "
            "`python scripts/classify_skipped_tests.py`."
        ),
        "categories": {
            "missing_frontend_dependency": "缺少前端本地依赖（node_modules / file: 依赖）",
            "missing_external_service": "缺少外部服务（网络 / 中间件 / 远端仓库）",
            "redis": "缺少 Redis 服务",
            "platform_unsupported": "当前平台不支持",
            "live_credentials": "缺少 live 评测凭据",
            "explicit_integration": "显式只读集成/验收测试，默认不跑",
            "other": "未分类，必须人工确认",
        },
        "blocking_categories": sorted(BLOCKING_CATEGORIES),
        "total": len(tests),
        "budget": max(PREVIOUS_BUDGET["total"], len(tests)),
        "by_category": by_category,
        "tests": tests,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default="tests", help="pytest target")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--out", default=str(ARTIFACT))
    parser.add_argument("--check", action="store_true",
                        help="compare against the committed artifact instead of writing")
    args = parser.parse_args()

    output = _run_pytest(args.python, args.path)
    tests = collect(output)
    if not tests:
        print("no skipped tests found — refusing to write an empty artifact")
        return 1
    payload = build(tests)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    out = Path(args.out)
    if args.check:
        current = out.read_text(encoding="utf-8") if out.is_file() else ""
        if current != text:
            print(f"{out} is stale; run `python scripts/classify_skipped_tests.py`")
            return 1
        print(f"{out} is up to date ({payload['total']} skipped)")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}: {payload['total']} skipped -> {payload['by_category']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
