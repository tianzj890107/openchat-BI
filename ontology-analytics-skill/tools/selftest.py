#!/usr/bin/env python3
"""tools 离线自检：不需要凭据、不连内网。

覆盖：
    1. --list-tools 返回 18 个工具且名字与文档一致；
    2. 用临时 SQLite 库真实调用 Ontology-FactQuery，校验结构化返回与数值；
    3. 只读 SQL 守卫拒绝写操作；
    4. 每个已声明工具都可执行（防止“只声明不注册”）；
    5. CanvasGenerate 产出整页自包含 HTML，且不依赖 Web 端 /static 资源。

任何一项失败即非零退出。
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVE = os.path.join(HERE, "serve.py")

EXPECTED_TOOLS = {
    "Ontology-SemanticQuery", "Ontology-TermDisambiguate", "MetricCalculation",
    "Ontology-RelationQuery", "Ontology-EntityDescribe", "ListBusinessObjects",
    "Ontology-GraphContext", "Ontology-GraphExpand", "Ontology-FactQuery",
    "ListTables", "DescribeTable", "ChartGenerate", "ChartGenerateMultiDim",
    "TableGenerate", "TodoWrite", "AskUser", "Ontology-MetricQuery",
    "CanvasGenerate",
}


def _run(args, env=None):
    return subprocess.run([sys.executable, SERVE, *args], capture_output=True,
                          text=True, env=env, cwd=HERE)


def _isolated(args, env):
    """自检必须与用户凭据隔离：显式指向不存在的配置文件。"""
    return _run(["--config", os.path.join(os.path.dirname(env["OA_SQLITE_DB"]),
                                          "no-credentials.env"), *args], env=env)


def check_list_tools() -> list[str]:
    proc = _run(["--list-tools"])
    if proc.returncode != 0:
        return [f"--list-tools 失败: {proc.stderr.strip()[:200]}"]
    names = {item["name"] for item in json.loads(proc.stdout)["tools"]}
    problems = []
    if names != EXPECTED_TOOLS:
        problems.append(f"工具集合不一致: 缺 {sorted(EXPECTED_TOOLS - names)} 多 {sorted(names - EXPECTED_TOOLS)}")
    return problems


def check_fact_query() -> list[str]:
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "demo.sqlite3")
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE fact_purchase_order "
                     "(order_id INTEGER, order_month TEXT, amount REAL, is_deleted INTEGER DEFAULT 0)")
        conn.executemany("INSERT INTO fact_purchase_order VALUES (?,?,?,0)",
                         [(1, "2025-01", 1200000.0), (2, "2025-02", 980000.0),
                          (3, "2025-03", 1530000.0), (4, "2025-04", 760000.0)])
        conn.commit()
        conn.close()

        env = dict(os.environ)
        env["OA_SQLITE_DB"] = db
        for key in ("ONTOLOGY_BASE_URL", "ONTOLOGY_REPOSITORY_ID", "DORIS_API_URL"):
            env.pop(key, None)

        proc = _isolated(["--call", "Ontology-FactQuery",
                          "--params", '{"sql": "SELECT SUM(amount) AS total FROM fact_purchase_order WHERE is_deleted = 0"}'],
                         env=env)
        if proc.returncode != 0:
            problems.append(f"Ontology-FactQuery 调用失败: {proc.stderr.strip()[:200]}")
            return problems
        payload = json.loads(proc.stdout)
        result = payload.get("result") or ""
        if "[RESULT_METADATA]" not in result:
            problems.append("返回值缺少 [RESULT_METADATA] 结构化块")
        elif '"rows": [[4470000.0]]' not in result:
            problems.append("对账数值不符：期望 4470000.0")

        bad = _isolated(["--call", "Ontology-FactQuery",
                         "--params", '{"sql": "DELETE FROM fact_purchase_order"}'], env=env)
        text = bad.stdout + bad.stderr
        if "only SELECT / WITH / PRAGMA / EXPLAIN are permitted" not in text:
            problems.append(f"写操作未被只读守卫拒绝: {text.strip()[:160]}")
    return problems


def _offline_env(tmp: str) -> dict:
    env = dict(os.environ)
    env["OA_SQLITE_DB"] = os.path.join(tmp, "tools.sqlite3")
    for key in ("ONTOLOGY_BASE_URL", "ONTOLOGY_REPOSITORY_ID", "DORIS_API_URL"):
        env.pop(key, None)
    return env


# 渲染/交互类工具不依赖取数后端，任何环境下都必须可执行。
SOURCE_FREE_TOOLS = (
    "ChartGenerate", "ChartGenerateMultiDim", "TableGenerate",
    "TodoWrite", "AskUser", "CanvasGenerate",
)


def check_source_free_tools_are_executable() -> list[str]:
    """声明与注册必须一致：渲染/交互类工具不得返回 unknown tool。"""
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        env = _offline_env(tmp)
        for name in SOURCE_FREE_TOOLS:
            proc = _isolated(["--call", name, "--params", "{}", "--cwd", tmp], env=env)
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError:
                problems.append(f"{name}: 输出不是 JSON: {(proc.stdout + proc.stderr)[:120]}")
                continue
            if not payload.get("ok") and str(payload.get("error") or "").startswith("unknown tool"):
                problems.append(f"{name}: 已声明但未注册（unknown tool）")
    return problems


def check_canvas_generate() -> list[str]:
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        env = _offline_env(tmp)
        params = {
            "title": "采购金额月度趋势",
            "subtitle": "2025 H1",
            "conclusion": "📌 结论：2025 年 3 月采购金额 153 万元，为上半年最高。",
            "source_note": "M001 · ontology_dev · 2025-01~2025-06",
            "blocks": [
                {"kind": "text", "heading": "说明", "markdown": "本页由 **CanvasGenerate** 产出。"},
                {"kind": "chart", "params": {
                    "chart_type": "bar", "title": "采购金额月度趋势",
                    "x_axis": ["1月", "2月", "3月"],
                    "series": [{"name": "采购金额", "data": [120.0, 98.0, 153.0]}],
                }},
                {"kind": "table", "params": {
                    "title": "明细", "columns": [
                        {"key": "month", "label": "月份"},
                        {"key": "amount", "label": "采购金额", "format": "number", "unit": "万元"},
                    ], "rows": [["1月", 120.0], ["2月", 98.0], ["3月", 1530.0]],
                }},
            ],
        }
        proc = _isolated(["--call", "CanvasGenerate", "--params", json.dumps(params, ensure_ascii=False),
                          "--cwd", tmp], env=env)
        if proc.returncode != 0:
            return [f"CanvasGenerate 调用失败: {(proc.stderr or proc.stdout).strip()[:200]}"]
        payload = json.loads(proc.stdout)
        result = payload.get("result") or ""
        if not payload.get("ok"):
            return [f"CanvasGenerate 返回 error: {payload.get('error')}"]
        if "<CANVAS_SPEC>" not in result:
            problems.append("返回值缺少 <CANVAS_SPEC> 结构化块")

        html_path = os.path.join(tmp, "dataset", "canvas")
        pages = [f for f in os.listdir(html_path)] if os.path.isdir(html_path) else []
        pages = [f for f in pages if f.endswith(".html")]
        if not pages:
            return problems + ["未产出 canvas HTML"]
        html = open(os.path.join(html_path, pages[0]), encoding="utf-8").read()

        if 'src="/static/' in html or "src='/static/" in html:
            problems.append("页面仍引用 Web 端 /static 绝对路径，通用 agent 环境下不可解析")
        if "echarts" not in html:
            problems.append("页面未包含 ECharts 运行时")
        if len(html) < 500_000:
            problems.append("内联 ECharts 后页面异常偏小，可能没真正内联")
        for needle in ("📌 结论", "采购金额月度趋势", "1,530"):
            if needle not in html:
                problems.append(f"页面缺少内容: {needle}")
    return problems


def main() -> int:
    problems = (
        check_list_tools()
        + check_fact_query()
        + check_source_free_tools_are_executable()
        + check_canvas_generate()
    )
    for item in problems:
        print(f"FAIL {item}")
    print(f"tools selftest: {'ok' if not problems else 'failed'} ({len(problems)} problem(s))")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
