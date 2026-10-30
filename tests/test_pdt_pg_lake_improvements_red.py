"""RED tests: PDT 数据湖切 PG 的改善批次契约（用户圈定 2 / 3 / 4 / 6 / 7 / 8 / 10 条）。

Contract source: ``docs/specs/pdt-pg-lake-improvements-batch.md``.

第 2 / 6 / 7 条的契约已由 ``tests/test_pdt_pg_lake_flow_round2_red.py`` 承载，本文件只补
它们**缺的覆盖面**，以及第 8 / 10 条这两条新增契约：

* 第 3 / 4 条：连接串与 "Doris" 字样在**元数据工具**（``ListTables`` / ``DescribeTable``）
  的错误文案里同样必须消失（轮二只覆盖了 ``Ontology-FactQuery``）；
* 第 8 条：``ListTables`` 恢复规模信息、``DescribeTable`` 恢复主键标注，且都不得重新引入
  MySQL-only 列；
* 第 10 条：本体库编号不在目录中时，报错必须可操作；``DEPLOYMENT.md`` 不得再写旧编号。

假网关是 PG 方言：MySQL-only 构造（``table_rows`` / ``column_key`` / 反引号 / ``LIMIT a,b``）
一律回真实网关的 ``code 500 系统繁忙``；行数与主键相关的列按列名应答，因此不绑定某一种
PG 来源写法（``reltuples`` / ``n_live_tup`` / ``pg_class`` / ``table_constraints`` 都可以）。

Offline and deterministic: loopback only, no credentials, no real service, no LLM,
no user data (no session / upload / chart directory is touched).
"""

from __future__ import annotations

import json
import os
import re
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from unittest import mock

from bi_agent.ontology.remote import RemoteOntologyClient
from bi_agent.ontology.store import OntologyStore
from bi_agent.tools import build_source_executors
from bi_agent.tools.sql_tools import DorisHttpConn
from bi_agent.web.app import STATE, configure


SQL_LEGACY = "/agent/doris/query"
SQL_MAL = "/api/v1/analysis/data/query"
META_QUERY = "/api/v1/analysis/meta/query"
LEGACY_META_QUERY = "/agent/ontology/scriptQuery"
RESOLVE_OBJECT = "/api/v1/analysis/context/resolve-ontology-object"
LEGACY_RESOLVE_OBJECT = "/agent/ontology/ensureOntologyObject"
EXPAND_CONTEXT = "/api/v1/analysis/context/expand-ontology-context"
REPO_LIST = "/api/v1/analysis/context/ontology-repository"
REPO_DETAIL = "/api/v1/analysis/context/ontology-repository/12"

GATEWAY_BUSY = "系统繁忙，请稍后再试"
SCHEMA_NAME = "ontology_qianjiang"

#: MySQL-only constructs the PostgreSQL gateway rejects outright.
MYSQL_ONLY_SQL = re.compile(r"\btable_rows\b|\bcolumn_key\b|`|limit\s+\d+\s*,", re.IGNORECASE)

#: Column names a PG-dialect implementation may use for a row estimate.
ESTIMATE_COLUMNS = (
    "reltuples", "n_live_tup", "n_dead_tup", "row_estimate", "estimated_rows",
    "est_rows", "rows_estimate", "approx_rows", "row_count_estimate",
)

#: Column names / values a PG-dialect implementation may use to mark a primary key.
PK_COLUMNS = ("is_pk", "is_primary_key", "primary_key", "is_pk_column", "pk", "constraint_type")

#: (name, kind, relkind, estimate) — one base table with an estimate and one view without.
LISTING_ROWS = (
    ("poheader", "BASE TABLE", "r", 667),
    ("poview", "VIEW", "v", -1.0),
)

#: (column, data type, nullable, is primary key)
COLUMN_ROWS = (
    ("ponumber", "character varying", "YES", True),
    ("nmaterial", "character varying", "YES", False),
)

#: A PG error the gateway currently hides behind its generic 500 text.
PG_UNDEFINED_TABLE = 'relation "ontology_qianjiang.poheader" does not exist'


def sql_ok(rows: list[dict[str, Any]]) -> tuple[int, dict]:
    columns = list(rows[0]) if rows else []
    return 200, {
        "success": True, "code": 200, "msg": "success",
        "data": {
            "rows": rows,
            "rowCount": len(rows),
            "columns": [{"identifierCode": name, "label": name, "type": "PROPERTY"}
                        for name in columns],
        },
    }


def sql_error(status: int, msg: str) -> tuple[int, dict]:
    return status, {"success": False, "code": status, "msg": msg}


def mal_table(rows: list[dict[str, Any]]) -> tuple[int, dict]:
    return 200, {
        "success": True, "code": 200, "msg": "success",
        "data": {
            "resultType": "TABLE",
            "result": {
                "columns": [{"identifierCode": name, "label": name, "type": "PROPERTY"}
                            for name in (list(rows[0]) if rows else [])],
                "rows": rows,
            },
        },
    }


def _select_list(sql: str) -> list[str]:
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


def _listing_value(name: str, row: tuple[str, str, str, float], index: int) -> Any:
    table, kind, relkind, estimate = row
    lowered = name.lower()
    if lowered in ("table_name", "relname", "name", "table"):
        return table
    if lowered in ("table_type", "relkind_label"):
        return kind
    if lowered == "relkind":
        return relkind
    if lowered in ESTIMATE_COLUMNS:
        return estimate
    if lowered in ("ordinal_position", "position"):
        return index + 1
    return None


def _column_value(name: str, row: tuple[str, str, str, bool], index: int) -> Any:
    column, data_type, nullable, is_pk = row
    lowered = name.lower()
    if lowered in ("column_name", "attname", "name", "column"):
        return column
    if lowered in ("data_type", "type", "udt_name"):
        return data_type
    if lowered in ("is_nullable", "nullable"):
        return nullable
    if lowered in ("ordinal_position", "position", "attnum"):
        return index + 1
    if lowered in PK_COLUMNS:
        if lowered == "constraint_type":
            return "PRIMARY KEY" if is_pk else None
        if lowered == "pk":
            return column if is_pk else None
        return is_pk
    return None


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
            status, payload = 404, {"success": False, "code": 404, "msg": f"no fake route for {path}"}
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
    """Loopback PG gateway: MySQL-only SQL fails, PG-shaped metadata answers."""

    def __init__(self, *, sql_error: str = "", repository_ids: tuple[int, ...] = (12,)) -> None:
        self.sql_error = sql_error
        self.repository_ids = repository_ids
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
        self.on_func(META_QUERY, lambda _call: mal_table([]))
        self.on_func(LEGACY_META_QUERY, lambda _call: mal_table([]))
        self.on_func(RESOLVE_OBJECT, lambda _call: sql_ok([]))
        self.on_func(LEGACY_RESOLVE_OBJECT, lambda _call: sql_ok([]))
        self.on_func(EXPAND_CONTEXT, lambda _call: mal_table([]))
        self.on(REPO_LIST, {
            "success": True, "code": 200, "msg": "success",
            "data": {"items": [
                {"id": repo_id, "name": f"本体库-{repo_id}", "namespaceCode": "qianjiang",
                 "currentDatabase": SCHEMA_NAME}
                for repo_id in self.repository_ids
            ], "total": len(self.repository_ids)},
        })
        self.on(REPO_DETAIL, {
            "success": True, "code": 200, "msg": "success",
            "data": {"id": 12, "name": "钱江本体库-勿动", "namespaceCode": "qianjiang",
                     "currentDatabase": SCHEMA_NAME},
        })

    def _sql(self, call: dict) -> tuple[int, dict]:
        sql = str((call.get("body") or {}).get("sql") or "")
        if MYSQL_ONLY_SQL.search(sql):
            # The PostgreSQL engine cannot satisfy the MySQL-only construct.
            return sql_error(500, GATEWAY_BUSY)
        if self.sql_error:
            return sql_error(500, self.sql_error)
        if not sql.strip().upper().startswith("SELECT"):
            return sql_error(400, "第 1 条语句校验失败：仅允许以 SELECT 或 MATCH 开头的只读查询")
        names = _select_list(sql)
        lowered = sql.lower()
        if "information_schema.columns" in lowered or "pg_attribute" in lowered:
            rows = [{name: _column_value(name, row, index)
                     for name in names} for index, row in enumerate(COLUMN_ROWS)]
        elif ("information_schema.tables" in lowered or "pg_class" in lowered
              or "pg_stat" in lowered or "pg_catalog" in lowered):
            rows = [{name: _listing_value(name, row, index)
                     for name in names} for index, row in enumerate(LISTING_ROWS)]
        else:
            rows = []
        keep = [row for row in rows if any(value is not None for value in row.values())]
        return sql_ok(keep)

    # -- helpers --------------------------------------------------------

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

    @property
    def authority(self) -> str:
        host, port = self._server.server_address[:2]
        return f"{host}:{port}"

    def sql_calls(self) -> list[str]:
        return [
            str((call.get("body") or {}).get("sql") or "")
            for call in self.calls if call["path"] in (SQL_LEGACY, SQL_MAL)
        ]

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


class _GatewayFlowTestCase(unittest.TestCase):
    sql_error = ""

    def setUp(self) -> None:
        self.fake = _FakePgGateway(sql_error=self.sql_error)
        self.addCleanup(self.fake.close)
        self.cwd = str(Path(__file__).resolve().parents[1])
        self.conn = DorisHttpConn(
            self.fake.base_url + SQL_LEGACY, SCHEMA_NAME, repository_id="12", app_id="test-app")
        self.executors = build_source_executors(
            OntologyStore(), str(Path(self.cwd) / "dataset/databases/HyperFusion.db"),
            doris=self.conn,
            remote_ontology=RemoteOntologyClient(
                self.fake.base_url, "12", app_id="test-app", namespace="qianjiang"))

    def run_tool(self, name: str, params: dict[str, Any]) -> str:
        return str(self.executors[name](params, self.cwd))


# ---------------------------------------------------------------------------
# 第 3 / 4 条 - 元数据工具的错误文案（R14 / R15）
# ---------------------------------------------------------------------------

class ErrorCopyTests(_GatewayFlowTestCase):
    sql_error = PG_UNDEFINED_TABLE

    def test_r14a_list_tables_error_does_not_echo_the_api_url(self):
        """R14：ListTables 的错误文案不得带出 API URL / 主机端口。"""
        output = self.run_tool("ListTables", {})
        self.assertIn("does not exist", output, msg="网关正文没有回传：" + output)
        self.assertNotIn(self.fake.authority, output, msg="错误里带出了 API 主机端口：" + output)
        self.assertNotRegex(output, r"https?://", msg="错误里带出了 URL：" + output)

    def test_r14b_describe_table_error_does_not_echo_the_api_url(self):
        """R14 续：DescribeTable 的错误文案同样不得带出连接串。"""
        output = self.run_tool("DescribeTable", {"table": f"{SCHEMA_NAME}.poheader"})
        self.assertNotIn(self.fake.authority, output, msg="错误里带出了 API 主机端口：" + output)
        self.assertNotRegex(output, r"https?://", msg="错误里带出了 URL：" + output)

    def test_r15a_list_tables_error_does_not_call_the_engine_doris(self):
        """R15：ListTables 的错误文案不得把当前引擎称作 Doris。"""
        output = self.run_tool("ListTables", {})
        self.assertIsNone(re.search(r"doris", output, re.IGNORECASE),
                          msg="尚未实现：ListTables 错误文案仍称引擎为 Doris：" + output)

    def test_r15b_describe_table_error_does_not_call_the_engine_doris(self):
        """R15 续：DescribeTable 的错误文案不得把当前引擎称作 Doris。"""
        output = self.run_tool("DescribeTable", {"table": f"{SCHEMA_NAME}.poheader"})
        self.assertIsNone(re.search(r"doris", output, re.IGNORECASE),
                          msg="尚未实现：DescribeTable 错误文案仍称引擎为 Doris：" + output)


# ---------------------------------------------------------------------------
# 第 8 条 - 规模信息与主键标注（R16 / R17 + 守卫 G8 / G9）
# ---------------------------------------------------------------------------

class ScaleInformationTests(_GatewayFlowTestCase):
    UNKNOWN_MARKER = re.compile(r"unknown|n/a|未知|—|\?", re.IGNORECASE)
    PK_MARKER = re.compile(r"\bPK\b|PRIMARY KEY|主键", re.IGNORECASE)

    def _line_for(self, output: str, needle: str) -> str:
        return next((line for line in output.splitlines() if needle in line), "")

    def test_r16_list_tables_reports_a_scale_estimate_when_the_engine_has_one(self):
        """R16：基表有估算时必须显示出来（当前只剩表名）。"""
        output = self.run_tool("ListTables", {})
        self.assertNotRegex(output, r"error", msg="ListTables 失败：" + output)
        base_line = self._line_for(output, "poheader")
        self.assertTrue(base_line, msg="清单里没有 poheader：" + output)
        self.assertIn("667", base_line, msg="尚未实现：基表没有显示行数估算：" + base_line)

    def test_r16b_view_without_an_estimate_is_marked_unknown_not_a_number(self):
        """R16 续：视图拿不到估算时必须显式标未知，不得把 -1 当行数。"""
        output = self.run_tool("ListTables", {})
        view_line = self._line_for(output, "poview")
        self.assertTrue(view_line, msg="清单里没有 poview：" + output)
        self.assertNotIn("-1", view_line, msg="把引擎的 -1 哨兵当行数展示了：" + view_line)
        self.assertRegex(view_line, self.UNKNOWN_MARKER,
                         msg="尚未实现：无估算时没有给出显式未知标记：" + view_line)

    def test_r17_describe_table_marks_the_primary_key_column(self):
        """R17：表结构必须恢复主键标注，且不得误标非主键列。"""
        output = self.run_tool("DescribeTable", {"table": f"{SCHEMA_NAME}.poheader"})
        pk_line = self._line_for(output, "ponumber")
        other_line = self._line_for(output, "nmaterial")
        self.assertTrue(pk_line, msg="结构里没有 ponumber：" + output)
        self.assertRegex(pk_line, self.PK_MARKER, msg="尚未实现：主键列没有标注：" + pk_line)
        self.assertIsNone(self.PK_MARKER.search(other_line),
                          msg="非主键列被误标成主键：" + other_line)

    def test_g8_restoring_scale_must_not_reintroduce_mysql_only_columns(self):
        """G8（守卫）：恢复行数/主键不得再发 MySQL-only 列。"""
        self.run_tool("ListTables", {})
        self.run_tool("DescribeTable", {"table": f"{SCHEMA_NAME}.poheader"})
        offending = [sql for sql in self.fake.sql_calls() if MYSQL_ONLY_SQL.search(sql)]
        self.assertEqual(offending, [], msg="又发出了 MySQL-only 的元数据 SQL：" + str(offending))

    def test_g9_healthy_listing_and_describe_still_answer(self):
        """G9（守卫）：后端正常时清单与结构仍必须正常出结果。"""
        listing = self.run_tool("ListTables", {})
        self.assertIn("poheader", listing, msg=listing)
        describe = self.run_tool("DescribeTable", {"table": f"{SCHEMA_NAME}.poheader"})
        self.assertIn("ponumber", describe, msg=describe)
        self.assertIn("nmaterial", describe, msg=describe)


# ---------------------------------------------------------------------------
# 第 10 条 - 本体库编号报错与文档（R18 / R19）
# ---------------------------------------------------------------------------

class RepositoryIdErrorTests(unittest.TestCase):
    STATE_FIELDS = (
        "cwd", "db_path", "ontology_path", "use_doris", "ontology_backend",
        "remote_ontology", "ontology_namespace", "doris_api_url", "doris_database",
        "doris_jdbc_url", "doris_driver", "doris_username", "doris_password",
        "remote_catalog_error", "remote_catalog_last_attempt",
    )

    def _run_configure(self, fake: _FakePgGateway, repository_id: str = "3") -> None:
        saved = {field: getattr(STATE, field, None) for field in self.STATE_FIELDS}
        self.addCleanup(lambda: [setattr(STATE, field, value) for field, value in saved.items()])
        env = {
            "ONTOLOGY_BACKEND": "production",
            "ONTOLOGY_BASE_URL": fake.base_url,
            "DORIS_API_URL": fake.base_url + SQL_LEGACY,
            "ONTOLOGY_REPOSITORY_ID": repository_id,
            "ONTOLOGY_APP_ID": "test-app",
            "ONTOLOGY_TIMEOUT_SECONDS": "5",
        }
        cwd = str(Path(__file__).resolve().parents[1])
        with mock.patch.dict(os.environ, env, clear=False), mock.patch(
            "bi_agent.web.app.register_all", return_value=None,
        ):
            STATE.ontology_backend = "production"
            STATE.doris_api_url = fake.base_url + SQL_LEGACY
            configure(
                cwd=cwd,
                ontology_path=str(Path(cwd) / "dataset/spreadsheets/本体元素_MetaERP（采购领域）-建模.xlsx"),
                db_path=str(Path(cwd) / "dataset/databases/HyperFusion.db"),
                use_doris=True,
            )

    def test_r18b_pdt_legacy_id_3_uses_verified_ywln_repository_14(self):
        """旧 PDT 注入 3 时，只回退到已验证的 14 / ywln / ontology_ywln。"""
        fake = _FakePgGateway(repository_ids=(16, 14, 13, 12))
        self.addCleanup(fake.close)
        fake.on(REPO_LIST, {
            "success": True, "code": 200, "msg": "success",
            "data": {"items": [{
                "id": 14, "name": "亿纬锂能开发本体库", "namespaceCode": "ywln",
                "currentDatabase": "ontology_ywln",
            }], "total": 1},
        })

        self._run_configure(fake)

        self.assertEqual(STATE.remote_ontology.repository_id, "14")
        self.assertEqual(STATE.ontology_namespace, "ywln")
        self.assertEqual(STATE.doris_database, "ontology_ywln")

    def test_r18c_legacy_id_3_does_not_fallback_when_14_database_mismatches(self):
        """编号 14 存在但数据库不是 ywln 时，必须继续 fail-fast。"""
        fake = _FakePgGateway(repository_ids=(14,))
        self.addCleanup(fake.close)
        fake.on(REPO_LIST, {
            "success": True, "code": 200, "msg": "success",
            "data": {"items": [{
                "id": 14, "name": "亿纬锂能开发本体库", "namespaceCode": "ywln",
                "currentDatabase": "ontology_qianjiang",
            }], "total": 1},
        })

        with self.assertRaises(RuntimeError) as ctx:
            self._run_configure(fake)
        self.assertIn("不在可用目录中", str(ctx.exception))

    def test_r18_unknown_repository_id_error_lists_the_available_ids(self):
        """R18：编号不在目录中时，报错要给出可用编号与配置键名，且不含内网地址。"""
        fake = _FakePgGateway(repository_ids=(12, 8, 6, 5))
        self.addCleanup(fake.close)
        saved = {field: getattr(STATE, field, None) for field in self.STATE_FIELDS}
        self.addCleanup(lambda: [setattr(STATE, field, value) for field, value in saved.items()])

        env = {
            "ONTOLOGY_BACKEND": "production",
            "ONTOLOGY_BASE_URL": fake.base_url,
            "DORIS_API_URL": fake.base_url + SQL_LEGACY,
            "ONTOLOGY_REPOSITORY_ID": "3",
            "ONTOLOGY_APP_ID": "test-app",
            "ONTOLOGY_NAMESPACE": "qianjiang",
            "ONTOLOGY_TIMEOUT_SECONDS": "5",
        }
        cwd = str(Path(__file__).resolve().parents[1])
        with mock.patch.dict(os.environ, env, clear=False):
            STATE.ontology_backend = "production"
            with self.assertRaises(RuntimeError) as ctx:
                configure(
                    cwd=cwd,
                    ontology_path=str(Path(cwd) / "dataset/spreadsheets/本体元素_MetaERP（采购领域）-建模.xlsx"),
                    db_path=str(Path(cwd) / "dataset/databases/HyperFusion.db"),
                    use_doris=True,
                )
        message = str(ctx.exception)
        self.assertIn("3", message, msg="报错没有提到配置的编号：" + message)
        self.assertIn("12", message, msg="尚未实现：报错没有列出可用编号：" + message)
        self.assertIn("ONTOLOGY_REPOSITORY_ID", message,
                      msg="尚未实现：报错没有指出该改哪个配置项：" + message)
        self.assertNotRegex(message, r"https?://", msg="报错里带出了内网地址：" + message)


class DocumentationTests(unittest.TestCase):
    def test_r19_deployment_doc_no_longer_pins_the_stale_repository_id(self):
        """R19：DEPLOYMENT.md 不得再把目录里已不存在的编号写成 PDT 当前值。"""
        doc = (Path(__file__).resolve().parents[1] / "DEPLOYMENT.md").read_text(encoding="utf-8")
        self.assertNotIn("ONTOLOGY_REPOSITORY_ID=3", doc,
                         msg="尚未实现：DEPLOYMENT.md 仍把 3 写成 PDT 的本体库编号。")
        self.assertIn("按环境", doc,
                      msg="文档丢了「按环境查目录」的取值口径，不能只删编号。")


if __name__ == "__main__":
    unittest.main()
