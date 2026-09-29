"""RED tests: PDT 数据湖切 PG 后的端到端流程契约（钱江本体库）。

Contract source: ``docs/specs/pdt-pg-lake-end-to-end-flow.md``.

Every assertion runs the **real production** code against a loopback HTTP server
that behaves like the PG-backed ontology gateway:

* ``bi_agent.tools.sql_tools`` — 真实的 ``ListTables`` / ``DescribeTable`` /
  ``Ontology-FactQuery`` 执行器（经 ``build_source_executors`` 装配）；
* ``bi_agent.tools.remote_ontology_tools`` — 真实的语义检索 / 对象详情 / 图库锚点；
* ``bi_agent.web.app._remote_repository_catalog`` — 真实的数据源目录归一化。

The fake gateway enforces the engine's real dialect: any MySQL-only construct
(``information_schema.tables.table_rows`` / ``information_schema.columns.column_key`` /
反引号 / ``LIMIT a,b``) is answered with the same ``code 500 系统繁忙`` the real
PostgreSQL gateway returns.

Offline and deterministic: loopback only, no credentials, no real service,
no LLM, no user data (no session / upload / chart directory is touched).
"""

from __future__ import annotations

import json
import re
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from bi_agent.ontology.remote import RemoteOntologyClient
from bi_agent.ontology.store import OntologyStore
from bi_agent.tools import build_source_executors
from bi_agent.tools.sql_tools import (
    DESCRIBE_TABLE_SCHEMA,
    LIST_TABLES_SCHEMA,
    SQL_RUN_SCHEMA,
    DorisHttpConn,
)
from bi_agent.web.app import _remote_repository_catalog


# ---------------------------------------------------------------------------
# documented paths
# ---------------------------------------------------------------------------

SQL_LEGACY = "/agent/doris/query"
SQL_MAL = "/api/v1/analysis/data/query"
META_QUERY = "/api/v1/analysis/meta/query"
RESOLVE_OBJECT = "/api/v1/analysis/context/resolve-ontology-object"
EXPAND_CONTEXT = "/api/v1/analysis/context/expand-ontology-context"
REPO_LIST = "/api/v1/analysis/context/ontology-repository"
REPO_DETAIL = "/api/v1/analysis/context/ontology-repository/12"

LEGACY_META_QUERY = "/agent/ontology/scriptQuery"
LEGACY_RESOLVE_OBJECT = "/agent/ontology/ensureOntologyObject"

#: The real gateway's opaque failure text (every engine error collapses into it).
GATEWAY_BUSY = "系统繁忙，请稍后再试"
#: A real PostgreSQL error that the gateway currently hides from the agent.
PG_UNDEFINED_TABLE = 'relation "ontology_qianjiang.poheader" does not exist'
GATEWAY_SELECT_ONLY = "第 1 条语句校验失败：仅允许以 SELECT 或 MATCH 开头的只读查询"

#: MySQL-only constructs the PostgreSQL gateway rejects outright.
MYSQL_ONLY_SQL = re.compile(r"\btable_rows\b|\bcolumn_key\b|`|limit\s+\d+\s*,", re.IGNORECASE)

BO_ROW = {
    "code": "BO0005",
    "name": "PurchaseOrder",
    "label": "采购订单",
    "description": "采购订单 金额 汇总",
}

SCHEMA_NAME = "ontology_qianjiang"


# ---------------------------------------------------------------------------
# payload builders
# ---------------------------------------------------------------------------

def mal_table(rows: list[dict[str, Any]], columns: list[str] | None = None) -> dict[str, Any]:
    if columns is None:
        columns = list(rows[0]) if rows else []
    return {
        "success": True, "code": 200, "msg": "success",
        "data": {
            "resultType": "TABLE",
            "result": {
                "columns": [
                    {"identifierCode": name, "label": name, "type": "PROPERTY"}
                    for name in columns
                ],
                "rows": rows,
            },
        },
    }


def mal_error(status: int, msg: str) -> dict[str, Any]:
    return {"success": False, "code": status, "msg": msg}


def _split_select_list(sql: str) -> list[str]:
    """Bare column identifiers of a SELECT list, order preserved, paren-aware."""
    match = re.search(r"\bselect\b(.*?)\bfrom\b", sql, re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    parts: list[str] = []
    depth = 0
    current = ""
    for char in match.group(1):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
            continue
        current += char
    parts.append(current)
    names: list[str] = []
    for part in parts:
        item = re.split(r"\s+as\s+", part.strip(), flags=re.IGNORECASE)[0].strip()
        item = item.split(".")[-1].strip().strip('"').strip("'")
        names.append(item or "expr")
    return names


_TABLE_VALUES = {
    "table_name": "poheader",
    "relname": "poheader",
    "name": "poheader",
    "table_type": "VIEW",
    "relkind": "v",
    "reltuples": 667,
    "n_live_tup": 667,
    "row_estimate": 667,
}

_COLUMN_VALUES = {
    "column_name": "ponumber",
    "attname": "ponumber",
    "name": "ponumber",
    "data_type": "character varying",
    "is_nullable": "YES",
    "ordinal_position": 1,
    "column_default": None,
    "is_primary_key": False,
    "is_pk": False,
    "primary_key": False,
    "constraint_type": "PRIMARY KEY",
}


def _row_for(sql: str) -> dict[str, Any]:
    values = _COLUMN_VALUES if "information_schema.columns" in sql else _TABLE_VALUES
    return {name: values.get(name) for name in _split_select_list(sql)}


# ---------------------------------------------------------------------------
# loopback PG gateway
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # keep pytest output clean
        pass

    def _dispatch(self, method: str) -> None:
        fake: "_FakePgGateway" = self.server.fake  # type: ignore[attr-defined]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            body: Any = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = raw
        path = self.path.split("?", 1)[0]
        call = {"method": method, "path": path, "body": body}
        fake.calls.append(call)
        responder = fake.routes.get(path)
        if responder is None:
            status, payload = 404, mal_error(404, f"no fake route for {path}")
        else:
            status, payload = responder(call)
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802 - http.server hook
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802 - http.server hook
        self._dispatch("POST")


class _FakePgGateway:
    """Loopback gateway: PG dialect on the SQL plane, switchable metadata plane."""

    def __init__(self, *, metadata_available: bool = True) -> None:
        self.metadata_available = metadata_available
        self.routes: dict[str, Callable[[dict], tuple[int, dict]]] = {}
        self.calls: list[dict[str, Any]] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.fake = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(
            target=lambda: self._server.serve_forever(poll_interval=0.02), daemon=True)
        self._thread.start()
        self._install()

    def _install(self) -> None:
        self.on_func(SQL_LEGACY, self._sql)
        self.on_func(SQL_MAL, self._sql)
        for path in (META_QUERY, LEGACY_META_QUERY):
            self.on_func(path, self._meta)
        for path in (RESOLVE_OBJECT, LEGACY_RESOLVE_OBJECT):
            self.on_func(path, self._resolve)
        self.on_func(EXPAND_CONTEXT, self._expand)
        self.on(REPO_LIST, {
            "success": True, "code": 200, "msg": "success",
            "data": {"items": [{
                "id": 12,
                "name": "钱江本体库-勿动",
                "description": "钱江本体库",
                "namespaceCode": "qianjiang",
                "cdcTopicPrefix": "ontology_qianjiang",
                "metaDatabase": "ontology_qianjiang_all_meta",
                "knowledgeDatabase": "ontology_qianjiang_all_knowledge",
                # PG deployments expose `currentDatabase` only.
                "currentDatabase": SCHEMA_NAME,
            }], "total": 1},
        })
        self.on(REPO_DETAIL, {
            "success": True, "code": 200, "msg": "success",
            "data": {
                "id": 12, "name": "钱江本体库-勿动", "namespaceCode": "qianjiang",
                "currentDatabase": SCHEMA_NAME,
            },
        })

    def _sql(self, call: dict) -> tuple[int, dict]:
        sql = str((call.get("body") or {}).get("sql") or "")
        if MYSQL_ONLY_SQL.search(sql):
            # The PostgreSQL engine cannot satisfy the MySQL-only construct.
            return 500, mal_error(500, GATEWAY_BUSY)
        return 200, {
            "success": True, "code": 200, "msg": "success",
            "data": {"rows": [_row_for(sql)], "rowCount": 1},
        }

    def _meta(self, call: dict) -> tuple[int, dict]:
        if not self.metadata_available:
            return 500, mal_error(500, GATEWAY_BUSY)
        analysis = (call.get("body") or {}).get("analysisConfig") or {}
        sql = str(analysis.get("sql") or "")
        if "FROM BusinessObject" in sql:
            return 200, mal_table([dict(BO_ROW)])
        return 200, mal_table([])

    def _resolve(self, call: dict) -> tuple[int, dict]:
        if not self.metadata_available:
            return 500, mal_error(500, GATEWAY_BUSY)
        return 200, {
            "success": True, "code": 200, "msg": "success",
            "data": {"found": False, "objectInfo": None},
        }

    def _expand(self, call: dict) -> tuple[int, dict]:
        if not self.metadata_available:
            return 500, mal_error(500, GATEWAY_BUSY)
        return 200, mal_table([])

    def on(self, path: str, payload: Any) -> "_FakePgGateway":
        def responder(_call: dict) -> tuple[int, dict]:
            return 200, payload
        self.routes[path] = responder
        return self

    def on_func(self, path: str, responder: Callable[[dict], tuple[int, dict]]) -> "_FakePgGateway":
        self.routes[path] = responder
        return self

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def sql_calls(self) -> list[str]:
        return [
            str((call.get("body") or {}).get("sql") or "")
            for call in self.calls if call["path"] in (SQL_LEGACY, SQL_MAL)
        ]

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


class _PgFlowTestCase(unittest.TestCase):
    metadata_available = True

    def setUp(self) -> None:
        self.fake = _FakePgGateway(metadata_available=self.metadata_available)
        self.addCleanup(self.fake.close)
        self.cwd = str(Path(__file__).resolve().parents[1])
        self.client = RemoteOntologyClient(
            self.fake.base_url, "12", app_id="test-app", namespace="qianjiang")
        conn = DorisHttpConn(
            self.fake.base_url + SQL_LEGACY, SCHEMA_NAME, repository_id="12", app_id="test-app")
        self.executors = build_source_executors(
            OntologyStore(), str(Path(self.cwd) / "dataset/databases/HyperFusion.db"),
            doris=conn, remote_ontology=self.client)

    def run_tool(self, name: str, params: dict[str, Any]) -> str:
        return str(self.executors[name](params, self.cwd))


# ---------------------------------------------------------------------------
# R1 / R2 - 元数据查询必须说 PG 方言
# ---------------------------------------------------------------------------

class SqlDialectTests(_PgFlowTestCase):
    def test_r1_list_tables_survives_a_postgres_gateway(self):
        """R1：ListTables 不得再向 PG 网关发送 `information_schema.tables.table_rows`。"""
        output = self.run_tool("ListTables", {})
        self.assertNotIn("error", output.lower(), msg=(
            "尚未实现：ListTables 在 PG 网关上失败。当前输出：" + output))
        self.assertIn("poheader", output, msg="ListTables 未列出表名：" + output)
        offending = [sql for sql in self.fake.sql_calls() if MYSQL_ONLY_SQL.search(sql)]
        self.assertEqual(offending, [], msg="仍在发送 MySQL-only 的元数据 SQL：" + str(offending))

    def test_r2_describe_table_survives_a_postgres_gateway(self):
        """R2：DescribeTable 不得再发送 `information_schema.columns.column_key`。"""
        output = self.run_tool("DescribeTable", {"table": SCHEMA_NAME + ".poheader"})
        self.assertNotIn("error", output.lower(), msg=(
            "尚未实现：DescribeTable 在 PG 网关上失败。当前输出：" + output))
        self.assertIn("ponumber", output, msg="DescribeTable 未列出列名：" + output)
        offending = [sql for sql in self.fake.sql_calls() if MYSQL_ONLY_SQL.search(sql)]
        self.assertEqual(offending, [], msg="仍在发送 MySQL-only 的元数据 SQL：" + str(offending))


# ---------------------------------------------------------------------------
# R3 / R4 / R5 - 传输故障不得被写成业务否定
# ---------------------------------------------------------------------------

class NoFalseNegativeTests(_PgFlowTestCase):
    metadata_available = False

    FALSE_NEGATIVES = re.compile(r"no remote (?:match|matches|anchor)", re.IGNORECASE)
    UNAVAILABLE = re.compile(r"remote error|unavailable|不可用|失败", re.IGNORECASE)

    def _assert_honest(self, tool: str, output: str) -> None:
        self.assertIsNone(self.FALSE_NEGATIVES.search(output), msg=(
            "尚未实现：" + tool + " 把后端不可用写成了业务否定。当前输出：" + output))
        self.assertRegex(output, self.UNAVAILABLE, msg=tool + " 未说明后端不可用：" + output)

    def test_r3_semantic_query_never_reports_a_false_absence(self):
        """R3：元数据后端 500 时，Ontology-SemanticQuery 不得回 “no remote matches”。"""
        self._assert_honest("Ontology-SemanticQuery",
                            self.run_tool("Ontology-SemanticQuery", {"query": "采购订单"}))

    def test_r4_entity_describe_never_reports_a_false_absence(self):
        """R4：同一故障下 Ontology-EntityDescribe 不得回 “no remote match”。"""
        self._assert_honest("Ontology-EntityDescribe",
                            self.run_tool("Ontology-EntityDescribe", {"entity": "BO0005"}))

    def test_r5_graph_context_never_reports_a_false_absence(self):
        """R5：同一故障下 Ontology-GraphContext 不得回 “no remote anchor”。"""
        self._assert_honest("Ontology-GraphContext",
                            self.run_tool("Ontology-GraphContext", {"query": "采购订单"}))


# ---------------------------------------------------------------------------
# R6 - 网关的错误正文必须可诊断
# ---------------------------------------------------------------------------

class GatewayErrorSurfaceTests(_PgFlowTestCase):
    def _break_sql_plane(self) -> None:
        def broken(call: dict) -> tuple[int, dict]:
            sql = str((call.get("body") or {}).get("sql") or "")
            if sql.upper().startswith("WITH"):
                return 400, mal_error(400, GATEWAY_SELECT_ONLY)
            return 500, mal_error(500, PG_UNDEFINED_TABLE)

        self.fake.on_func(SQL_LEGACY, broken)
        self.fake.on_func(SQL_MAL, broken)

    def test_r6a_fact_query_surfaces_the_gateway_error_body(self):
        """R6a：网关 5xx 的正文（真实 PG 报错）必须进入工具输出。"""
        self._break_sql_plane()
        output = self.run_tool("Ontology-FactQuery", {
            "sql": "SELECT count(*) AS n FROM " + SCHEMA_NAME + ".poheader"})
        self.assertIn("does not exist", output, msg=(
            "尚未实现：FactQuery 丢弃了网关 500 的正文。当前输出：" + output))

    def test_r6b_fact_query_surfaces_the_gateway_validation_message(self):
        """R6b：网关 4xx 的校验文案也要回传，不能让用户只看到 Bad Request。"""
        self._break_sql_plane()
        output = self.run_tool("Ontology-FactQuery", {
            "sql": "WITH t AS (SELECT 1 AS a) SELECT a FROM t"})
        self.assertIn("仅允许以 SELECT", output, msg=(
            "FactQuery 未回传网关 400 的正文。当前输出：" + output))


# ---------------------------------------------------------------------------
# R7 - 模型可见的 SQL 方言提示必须与引擎一致
# ---------------------------------------------------------------------------

class SqlGuidanceTests(unittest.TestCase):
    def test_r7_fact_query_description_describes_the_postgres_engine(self):
        """R7：工具描述不得再向模型声明 MySQL 方言。"""
        description = str(SQL_RUN_SCHEMA["description"])
        self.assertIsNone(re.search(r"mysql", description, re.IGNORECASE), msg=(
            "尚未实现：Ontology-FactQuery 仍在向模型声明 MySQL 方言：" + description))
        self.assertRegex(description, r"postgres|postgresql|\bPG\b", msg=(
            "工具描述未说明实际引擎方言（PostgreSQL）：" + description))

    def test_r7_metadata_tool_descriptions_do_not_promise_mysql_dialect(self):
        """R7 续：元数据工具的说明也不得再声明 MySQL 方言。"""
        for schema in (LIST_TABLES_SCHEMA, DESCRIBE_TABLE_SCHEMA):
            description = str(schema["description"])
            self.assertIsNone(
                re.search(r"mysql", description, re.IGNORECASE),
                msg=schema["name"] + " 的工具说明仍在声明 MySQL：" + description,
            )


# ---------------------------------------------------------------------------
# G1 / G2 - 守卫：正常路径不得被"更严格的报错"破坏
# ---------------------------------------------------------------------------

class CatalogAndHealthyPathGuards(_PgFlowTestCase):
    def test_g1_pg_only_catalog_still_exposes_the_paired_source(self):
        """G1：目录只给 currentDatabase 时，钱江仍必须成对可选。"""
        catalog = _remote_repository_catalog(self.client)
        entry = next((item for item in catalog if item["id"] == "12"), None)
        self.assertIsNotNone(entry, msg=f"目录里没有钱江本体库：{catalog}")
        self.assertEqual(entry["dorisDatabase"], SCHEMA_NAME)
        self.assertEqual(entry["namespace"], "qianjiang")
        self.assertEqual(entry["databaseValue"], "__doris_repository__:12")

    def test_g2_healthy_metadata_backend_still_returns_matches(self):
        """G2：后端正常时，语义检索的检索层必须照常出结果。"""
        output = self.run_tool("Ontology-SemanticQuery", {"query": "采购订单 金额"})
        self.assertIn("BO0005", output, msg=output)
        self.assertIsNone(re.search(r"no remote match", output, re.IGNORECASE),
                          msg="正常后端被判成没有命中：" + output)

    def test_g2b_confirm_layer_still_hits_on_a_healthy_backend(self):
        """G2 续：确认层命中时仍必须给出权威结果，不得被新的降级逻辑吞掉。"""
        self.fake.on_func(RESOLVE_OBJECT, lambda _call: (200, {
            "success": True, "code": 200, "msg": "success",
            "data": {"found": True, "objectInfo": {
                "typeName": "BusinessObject", "properties": dict(BO_ROW)}},
        }))
        output = self.run_tool("Ontology-SemanticQuery", {"query": "采购订单"})
        self.assertIn("BO0005", output, msg=output)


if __name__ == "__main__":
    unittest.main()
