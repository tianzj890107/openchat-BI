#!/usr/bin/env python3
"""真实工具运行时入口：把仓库里的 BI 工具原样接出来，供任意 agent 调用。

用法：
    python3 tools/serve.py --list-tools
    python3 tools/serve.py --call Ontology-FactQuery --params '{"sql": "SELECT 1"}'
    echo '{"tool": "...", "params": {...}}' | python3 tools/serve.py --serve

配置与凭据（按优先级，后者覆盖前者）：
    1. 进程环境变量；
    2. 本目录下的 credentials.env（已被 .gitignore 忽略，不进仓库）；
    3. ~/.config/ontology-analytics/credentials.env。

工具实现原样取自仓库（见 tools/_vendor/README.md），本文件只做装配：
本体 = 远程本体服务或本地 Excel；SQL = 远程 Doris HTTP 网关 / Doris MySQL / 本地 SQLite。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(HERE, "_vendor")
if VENDOR not in sys.path:
    sys.path.insert(0, VENDOR)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

CONFIG_PATHS = [
    os.path.join(HERE, "credentials.env"),
    os.path.expanduser("~/.config/ontology-analytics/credentials.env"),
]

REQUIRED_CREDENTIAL_KEYS = [
    "ONTOLOGY_BASE_URL", "ONTOLOGY_REPOSITORY_ID", "ONTOLOGY_APP_ID",
    "ONTOLOGY_AUTH_TOKEN", "ONTOLOGY_NAMESPACE",
    "DORIS_API_URL", "DORIS_DATABASE",
    "X360_BASE_URL", "X360_APP_ID", "X360_AUTH_TOKEN",
]


def load_credentials(path: str | None = None) -> list[str]:
    """把凭据文件读进环境变量；已存在的环境变量不被覆盖。返回生效的文件。"""
    used: list[str] = []
    candidates = [path] if path else CONFIG_PATHS
    for candidate in candidates:
        if not candidate or not os.path.isfile(candidate):
            continue
        with open(candidate, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        used.append(candidate)
    return used


def _static_schemas() -> list[dict]:
    from bi_agent.tools import (
        ask_user, chart_multidim_tools, chart_tools, graph_tools,
        ontology_tools, sql_tools, table_tools, todo_tools,
    )
    from bi_agent.tools import remote_ontology_tools as remote
    import canvas_tool

    specs = (
        list(ontology_tools.SPECS) + list(graph_tools.SPECS) + list(sql_tools.SPECS)
        + list(chart_tools.SPECS) + list(chart_multidim_tools.SPECS)
        + list(table_tools.SPECS) + list(todo_tools.SPECS) + list(ask_user.SPECS)
        + list(canvas_tool.SPECS)
    )
    # 同名工具以远程实现为准（与 build_source_executors 的覆盖顺序一致），
    # 因此按 name 去重时把远程 schema 放在后面覆盖。
    by_name: dict[str, dict] = {}
    for schema in [schema for schema, _ in specs]:
        by_name[schema["name"]] = schema
    for schema in (
        remote.ONTOLOGY_QUERY_SCHEMA, remote.TERM_DISAMBIGUATE_SCHEMA,
        remote.METRIC_LOOKUP_SCHEMA, remote.RELATION_LOOKUP_SCHEMA,
        remote.ENTITY_DESCRIBE_SCHEMA, remote.LIST_BUSINESS_OBJECTS_SCHEMA,
        remote.GRAPH_CONTEXT_SCHEMA, remote.GRAPH_EXPAND_SCHEMA,
        remote.METRIC_DATA_QUERY_SCHEMA,
    ):
        by_name[schema["name"]] = schema
    return list(by_name.values())


def build_runtime(allow_local: bool = True):
    """按环境变量装配 store / SQL 后端 / 远程本体客户端，返回可执行工具表。"""
    from bi_agent.ontology.remote import RemoteOntologyClient
    from bi_agent.ontology.store import OntologyStore
    from bi_agent.tools import build_source_executors
    from bi_agent.tools.sql_tools import DorisConn, DorisHttpConn

    backend = (os.environ.get("ONTOLOGY_BACKEND") or "production").strip().lower()
    xlsx = (os.environ.get("OA_LOCAL_ONTOLOGY_XLSX") or "").strip()
    remote = None
    if backend == "local" or xlsx:
        if not xlsx or not os.path.isfile(xlsx):
            raise SystemExit(
                "本地本体模式需要 OA_LOCAL_ONTOLOGY_XLSX 指向本体 xlsx 文件"
            )
        store = OntologyStore.from_xlsx(xlsx)
    else:
        missing = [k for k in ("ONTOLOGY_BASE_URL", "ONTOLOGY_REPOSITORY_ID")
                   if not os.environ.get(k)]
        if missing:
            # 只配了 SQL 后端时允许「SQL-only」模式：本体工具会明确返回未配置，
            # 但取数 / 图表 / 表格工具可用，便于离线自检。
            if (os.environ.get("OA_SQLITE_DB") or "").strip() or (os.environ.get("DORIS_API_URL") or "").strip():
                store = OntologyStore()
            else:
                raise SystemExit(
                    "远程本体模式缺少环境变量: " + ", ".join(missing)
                    + "（见 tools/config.example.env；凭据请放 tools/credentials.env 或 ~/.config/ontology-analytics/credentials.env）"
                )
        else:
            remote = RemoteOntologyClient.from_env()
            store = OntologyStore()

    doris = None
    api_url = (os.environ.get("DORIS_API_URL") or "").strip()
    jdbc = (os.environ.get("DORIS_JDBC_URL") or "").strip()
    if api_url:
        doris = DorisHttpConn(
            api_url,
            (os.environ.get("DORIS_DATABASE") or "").strip(),
            repository_id=(os.environ.get("ONTOLOGY_REPOSITORY_ID") or "").strip(),
            app_id=(os.environ.get("ONTOLOGY_APP_ID") or "").strip(),
            auth_token=(os.environ.get("ONTOLOGY_AUTH_TOKEN") or "").strip(),
        )
    elif jdbc:
        doris = DorisConn(
            jdbc,
            username=(os.environ.get("DORIS_USERNAME") or "").strip(),
            password=(os.environ.get("DORIS_PASSWORD") or "").strip(),
            database=(os.environ.get("DORIS_DATABASE") or "").strip() or None,
        )

    db_path = (os.environ.get("OA_SQLITE_DB") or "").strip()
    if doris is None and not db_path:
        raise SystemExit(
            "缺少取数后端：设置 DORIS_API_URL（推荐）或 DORIS_JDBC_URL，"
            "离线调试可设 OA_SQLITE_DB 指向 SQLite 文件"
        )
    executors = build_source_executors(store, db_path or ":memory:", doris=doris,
                                       remote_ontology=remote)
    # 渲染/交互类工具不依赖数据源，但必须与 schema 声明一致地可执行：
    # 之前只声明不注册，会导致 --call ChartGenerate/TableGenerate 报 unknown tool。
    from bi_agent.tools import (
        ask_user, chart_multidim_tools, chart_tools, table_tools, todo_tools,
    )
    import canvas_tool

    for specs in (
        chart_tools.SPECS, chart_multidim_tools.SPECS, table_tools.SPECS,
        todo_tools.SPECS, ask_user.SPECS, canvas_tool.SPECS,
    ):
        for schema, make_executor in specs:
            executors[schema["name"]] = make_executor()
    return executors


TOOL_INDEX: dict[str, str] = {}


def _resolve(name: str) -> str:
    return TOOL_INDEX.get(name, name)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ontology-analytics 真实工具运行时")
    parser.add_argument("--config", help="凭据 env 文件路径（默认 tools/credentials.env）")
    parser.add_argument("--list-tools", action="store_true", help="列出工具与 schema")
    parser.add_argument("--call", help="工具名，例如 Ontology-FactQuery")
    parser.add_argument("--params", default="{}", help="工具参数 JSON")
    parser.add_argument("--cwd", default=os.getcwd(), help="工具执行的工作目录")
    parser.add_argument("--serve", action="store_true", help="从 stdin 读 JSONL 逐条执行")
    args = parser.parse_args(argv)

    used = load_credentials(args.config)
    for schema in _static_schemas():
        TOOL_INDEX[schema["name"]] = schema["name"]

    if args.list_tools:
        payload = {
            "tools": [
                {"name": s.get("name"), "description": (s.get("description") or "").strip(),
                 "parameters": s.get("parameters") or s.get("input_schema") or {}}
                for s in _static_schemas()
            ],
            "credentials_files": used,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    executors = build_runtime()

    if args.serve:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            name = _resolve(str(row.get("tool") or ""))
            params = row.get("params") or {}
            if name not in executors:
                print(json.dumps({"ok": False, "error": f"unknown tool: {name}"}, ensure_ascii=False))
                continue
            try:
                out = executors[name](params, args.cwd)
                print(json.dumps({"ok": True, "tool": name, "result": out}, ensure_ascii=False))
            except Exception as exc:  # noqa: BLE001
                print(json.dumps({"ok": False, "tool": name, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 0

    if not args.call:
        parser.error("需要 --list-tools / --call / --serve 之一")

    name = _resolve(args.call)
    if name not in executors:
        print(json.dumps({"ok": False, "error": f"unknown tool: {args.call}",
                          "available": sorted(executors)}, ensure_ascii=False))
        return 2
    params = json.loads(args.params or "{}")
    try:
        out = executors[name](params, args.cwd)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "tool": name, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, "tool": name, "result": out}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
