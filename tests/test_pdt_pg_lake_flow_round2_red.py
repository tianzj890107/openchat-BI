"""RED tests: PDT 数据湖切 PG 的第二轮端到端契约（钱江本体库）。

Contract source: ``docs/specs/pdt-pg-lake-end-to-end-flow-round2.md``.

The first round (``docs/specs/pdt-pg-lake-end-to-end-flow.md``) fixed the two
MySQL-only metadata statements, the false absence reports and the discarded
gateway error body.  Re-running the same user-visible flow afterwards surfaced
a second, smaller set of defects, all of which run the **real production** code
against a loopback gateway whose planes can be broken one at a time:

* ``bi_agent.tools.remote_ontology_tools`` - partial degradation must stay a
  business answer, not become a transport incident;
* ``bi_agent.tools.sql_tools`` - model-visible copy must not name the wrong
  engine, must not echo the API URL, and must not forward statements the
  gateway is known to reject.

Offline and deterministic: loopback only, no credentials, no real service, no
LLM, no user data (no session / upload / chart directory is touched).
"""

from __future__ import annotations

import json
import re
import sqlite3
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from bi_agent.ontology.remote import RemoteOntologyClient
from bi_agent.ontology.store import OntologyStore
from bi_agent.tools import build_source_executors
from bi_agent.tools.sql_tools import DorisHttpConn, _validate_sql


SQL_LEGACY = "/agent/doris/query"
SQL_MAL = "/api/v1/analysis/data/query"
META_QUERY = "/api/v1/analysis/meta/query"
RESOLVE_OBJECT = "/api/v1/analysis/context/resolve-ontology-object"
LEGACY_RESOLVE_OBJECT = "/agent/ontology/ensureOntologyObject"
EXPAND_CONTEXT = "/api/v1/analysis/context/expand-ontology-context"
REPO_LIST = "/api/v1/analysis/context/ontology-repository"
REPO_DETAIL = "/api/v1/analysis/context/ontology-repository/12"

GATEWAY_BUSY = "系统繁忙，请稍后再试"

SCHEMA_NAME = "ontology_qianjiang"
TABLE_NAME = "poheader"

BO_ROW = {
    "code": "BO0005",
    "name": "PurchaseOrder",
    "label": "采购订单",
    "description": "采购订单 金额 汇总",
}

#: A name the confirmation layer may confirm verbatim (no query markers) and
#: that no plane will ever match.
ABSENT_NAME = "完全不存在的对象zzz"

#: Statements the local validator accepts but the real gateway answers with
#: ``400 仅允许以 SELECT 或 MATCH 开头``.
GATEWAY_REJECTED_LEAD = re.compile(r"^\s*(with|explain|pragma)\b", re.IGNORECASE)


def mal_ok(payload: Any) -> tuple[int, dict]:
    return 200, {"success": True, "code": 200, "msg": "success", "data": payload}


def mal_error(status: int, msg: str) -> tuple[int, dict]:
    return status, {"success": False, "code": status, "msg": msg}


def mal_table(rows: list[dict[str, Any]]) -> tuple[int, dict]:
    return mal_ok({
        "resultType": "TABLE",
        "result": {
            "columns": [{"identifierCode": name, "label": name, "type": "PROPERTY"}
                        for name in (list(rows[0]) if rows else [])],
            "rows": rows,
        },
    })


#: One plausible row for each metadata listing the tools issue.
_TABLE_VALUES = {"table_name": TABLE_NAME}
_COLUMN_VALUES = {
    "column_name": "ponumber",
    "data_type": "character varying",
    "is_nullable": "YES",
    "ordinal_position": 1,
}


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


def row_for(sql: str, *, table_rows: tuple[str, ...], column_rows: tuple[str, ...]) -> dict[str, Any]:
    """Answer one metadata SELECT with the columns the statement asked for."""
    if "information_schema.columns" in sql:
        values: dict[str, Any] = _COLUMN_VALUES if column_rows else {}
    else:
        values = _TABLE_VALUES if table_rows else {}
    return {name: values.get(name) for name in _split_select_list(sql)}


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
    """Loopback gateway with independently switchable planes."""

    def __init__(self, *, list_plane: str = "empty", tree_plane: str = "ok",
                 confirm_plane: str = "ok", tables: tuple[str, ...] = (TABLE_NAME,),
                 columns: tuple[str, ...] = (), sql_error: str = "") -> None:
        #: ``list_plane``: ``hit`` (a BusinessObject matches) or ``empty``.
        self.list_plane = list_plane
        #: ``tree_plane`` / ``confirm_plane``: ``ok`` or ``down``.
        self.tree_plane = tree_plane
        self.confirm_plane = confirm_plane
        #: Metadata the SQL plane reports (empty tuple means "nothing found").
        self.tables = tables
        self.columns = columns
        #: Non-empty means every SQL call fails with the real engine's message.
        self.sql_error = sql_error
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
        self.on_func(META_QUERY, self._meta)
        self.on_func(LEGACY_META_QUERY_ALIAS, self._meta)
        self.on_func(RESOLVE_OBJECT, self._confirm)
        self.on_func(LEGACY_RESOLVE_OBJECT, self._confirm)
        self.on_func(EXPAND_CONTEXT, lambda _call: mal_table([]))
        self.on(REPO_LIST, {
            "success": True, "code": 200, "msg": "success",
            "data": {"items": [{
                "id": 12,
                "name": "钱江本体库-勿动",
                "namespaceCode": "qianjiang",
                "currentDatabase": SCHEMA_NAME,
            }], "total": 1},
        })
        self.on(REPO_DETAIL, {
            "success": True, "code": 200, "msg": "success",
            "data": {"id": 12, "name": "钱江本体库-勿动", "namespaceCode": "qianjiang",
                     "currentDatabase": SCHEMA_NAME},
        })

    # -- planes ---------------------------------------------------------

    def _sql(self, call: dict) -> tuple[int, dict]:
        sql = str((call.get("body") or {}).get("sql") or "")
        if self.sql_error:
            return 500, {"success": False, "code": 500, "msg": self.sql_error}
        if not sql.upper().startswith("SELECT"):
            # The real gateway answers every other lead with its validator text.
            return 400, {"success": False, "code": 400,
                         "msg": "第 1 条语句校验失败：仅允许以 SELECT 或 MATCH 开头的只读查询"}
        row = row_for(sql, table_rows=self.tables, column_rows=self.columns)
        rows = [row] if any(value is not None for value in row.values()) else []
        return 200, {"success": True, "code": 200, "msg": "success",
                     "data": {"rows": rows, "rowCount": len(rows)}}

    def _is_tree_call(self, call: dict) -> bool:
        common = (call.get("body") or {}).get("commonConfig") or {}
        return "pagination" in common or "filters" in common

    def _meta(self, call: dict) -> tuple[int, dict]:
        if self._is_tree_call(call):
            if self.tree_plane == "down":
                return mal_error(500, GATEWAY_BUSY)
            return mal_table([])
        sql = str(((call.get("body") or {}).get("analysisConfig") or {}).get("sql") or "")
        if "BusinessObject" in sql and self.list_plane == "hit":
            return mal_table([dict(BO_ROW)])
        return mal_table([])

    def _confirm(self, call: dict) -> tuple[int, dict]:
        if self.confirm_plane == "down":
            return mal_error(500, GATEWAY_BUSY)
        return mal_ok({"found": False, "objectInfo": None})

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


LEGACY_META_QUERY_ALIAS = "/agent/ontology/scriptQuery"


class _GatewayFlowTestCase(unittest.TestCase):
    list_plane = "empty"
    tree_plane = "ok"
    confirm_plane = "ok"
    tables: tuple[str, ...] = (TABLE_NAME,)
    columns: tuple[str, ...] = ()
    sql_error = ""

    def setUp(self) -> None:
        self.fake = _FakePgGateway(list_plane=self.list_plane, tree_plane=self.tree_plane,
                                   confirm_plane=self.confirm_plane, tables=self.tables,
                                   columns=self.columns, sql_error=self.sql_error)
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
# R8 - 部分降级不得升级成"环境故障"
# ---------------------------------------------------------------------------

class PartialDegradationTests(_GatewayFlowTestCase):
    """Confirm plane down + tree plane down, but the list plane answers."""

    tree_plane = "down"
    confirm_plane = "down"

    FALSE_INCIDENT = re.compile(r"remote error|unavailable|请求失败|HTTP 500", re.IGNORECASE)

    def test_r8_partial_degradation_keeps_the_empty_result_a_business_answer(self):
        """R8：列表面已正常回答"没有该对象"时，不得升级为传输故障。"""
        output = self.run_tool("Ontology-SemanticQuery", {"query": ABSENT_NAME})
        self.assertIsNone(
            self.FALSE_INCIDENT.search(output),
            msg="尚未实现：只有 tree 面失败、列表面正常返回空，却被报成环境故障。当前输出：" + output,
        )
        self.assertRegex(
            output, r"no remote matches|没有",
            msg="未给出业务否定结论：" + output,
        )
        self.assertRegex(
            output, r"确认接口不可用|回退到本地候选|degraded|降级",
            msg="部分降级没有留下降级说明：" + output,
        )

    def test_r8b_entity_describe_partial_degradation_keeps_the_empty_result(self):
        """R8 续：Ontology-EntityDescribe 走同一候选层，口径必须一致。"""
        output = self.run_tool("Ontology-EntityDescribe", {"entity": ABSENT_NAME})
        self.assertIsNone(
            self.FALSE_INCIDENT.search(output),
            msg="尚未实现：EntityDescribe 在部分降级时被报成环境故障。当前输出：" + output,
        )


# ---------------------------------------------------------------------------
# R9 / R10 - 模型可见的错误与展示文案
# ---------------------------------------------------------------------------

class ErrorCopyTests(_GatewayFlowTestCase):
    sql_error = f'relation "{SCHEMA_NAME}.{TABLE_NAME}" does not exist'

    def test_r9_gateway_error_text_does_not_echo_the_api_url(self):
        """R9：错误里只回网关 msg，不得拼接 API URL / 连接串 / 凭据。"""
        output = self.run_tool("Ontology-FactQuery", {
            "sql": f"SELECT count(*) FROM {SCHEMA_NAME}.{TABLE_NAME}"})
        self.assertIn("does not exist", output, msg="网关正文没有回传：" + output)
        self.assertNotIn(self.fake.authority, output, msg="错误正文里带出了 API 主机端口：" + output)
        self.assertNotIn(self.fake.base_url, output, msg="错误正文里带出了 API URL：" + output)
        self.assertNotRegex(output, r"https?://", msg="错误正文里带出了 URL：" + output)

    def test_r10a_fact_query_error_does_not_call_the_engine_doris(self):
        """R10：网关已改为 PG 引擎，工具文案不得再把它称作 Doris。"""
        output = self.run_tool("Ontology-FactQuery", {"sql": f"SELECT 1 FROM {SCHEMA_NAME}.{TABLE_NAME}"})
        self.assertIsNone(re.search(r"doris", output, re.IGNORECASE),
                          msg="尚未实现：错误文案仍把当前引擎称作 Doris：" + output)

# ---------------------------------------------------------------------------
# R11 - 本地校验不得放行网关已知会拒绝的语句
# ---------------------------------------------------------------------------

class LocalValidationParityTests(_GatewayFlowTestCase):
    REJECTED_SQL = [
        f"WITH t AS (SELECT 1 AS a) SELECT a FROM t",
        "EXPLAIN SELECT 1",
        f"PRAGMA table_info('{TABLE_NAME}')",
    ]

    def test_r11_gateway_backend_never_forwards_statement_forms_it_rejects(self):
        """R11：网关只收 SELECT/MATCH，本地就不该把 WITH/EXPLAIN/PRAGMA 送出去。"""
        for sql in self.REJECTED_SQL:
            with self.subTest(sql=sql):
                self.run_tool("Ontology-FactQuery", {"sql": sql})
        forwarded = [sql for sql in self.fake.sql_calls() if GATEWAY_REJECTED_LEAD.match(sql)]
        self.assertEqual(forwarded, [], msg="仍把网关会拒绝的语句发出去：" + str(forwarded))

    def test_r11b_rejection_explains_the_gateway_rule(self):
        """R11 续：本地拒绝时必须说明原因，不能只说一句 not permitted。"""
        output = self.run_tool("Ontology-FactQuery", {"sql": "EXPLAIN SELECT 1"})
        self.assertRegex(output, r"MATCH|仅允许|只读",
                         msg="本地拒绝没有给出可操作的原因：" + output)


# ---------------------------------------------------------------------------
# R12 / R13 - 空态与名称回显
# ---------------------------------------------------------------------------

class ListingAndDescribeTests(_GatewayFlowTestCase):
    def test_r10b_list_tables_header_states_only_real_facts(self):
        """R10 续：ListTables 表头不得出现占位主机（HTTP API:0）或错误引擎名。"""
        output = self.run_tool("ListTables", {})
        self.assertNotIn("HTTP API:0", output, msg="表头仍是占位主机端口：" + output)
        self.assertIn(SCHEMA_NAME, output, msg="表头没有给出实际库名：" + output)
        self.assertIsNone(re.search(r"doris", output, re.IGNORECASE),
                          msg="ListTables 仍把当前引擎称作 Doris：" + output)

    # The active database holds nothing yet: listing and describing must both
    # answer that emptiness in words instead of implying it.
    tables: tuple[str, ...] = ()

    def test_r12_empty_listing_is_stated_in_words(self):
        """R12：活动库没有表/视图时必须显式说明空态。"""
        output = self.run_tool("ListTables", {})
        self.assertRegex(output, r"0 tables|no tables|没有表|无表|空",
                         msg="尚未实现：0 表时只有表头里一个 0，没有显式空态说明：" + output)

    def test_r13_describe_table_echoes_the_qualified_name(self):
        """R13：未找到时必须回显用户传入的完整限定名（含 schema）。"""
        output = self.run_tool("DescribeTable", {"table": f"{SCHEMA_NAME}.{TABLE_NAME}"})
        self.assertIn(f"{SCHEMA_NAME}.{TABLE_NAME}", output,
                      msg="尚未实现：答复丢掉了 schema 限定名：" + output)


# ---------------------------------------------------------------------------
# G3 - G6 - 守卫：修 R8 / R11 不得误伤正常路径
# ---------------------------------------------------------------------------

class HappyPathGuards(_GatewayFlowTestCase):
    list_plane = "hit"

    def test_g3_healthy_semantic_query_still_returns_the_match(self):
        """G3：后端正常时语义检索必须照常出命中（修 R8 不得把它变成报错）。"""
        output = self.run_tool("Ontology-SemanticQuery", {"query": "采购订单 金额"})
        self.assertIn("BO0005", output, msg=output)
        self.assertIsNone(re.search(r"remote error", output, re.IGNORECASE), msg=output)

    def test_g4_gateway_backend_still_accepts_plain_select(self):
        """G4：收紧本地校验（R11）不得挡住 SELECT。"""
        self.run_tool("Ontology-FactQuery", {"sql": f"SELECT 1 FROM {SCHEMA_NAME}.{TABLE_NAME}"})
        forwarded = self.fake.sql_calls()
        self.assertTrue(any(sql.upper().startswith("SELECT") for sql in forwarded),
                        msg="SELECT 没有送到网关：" + str(forwarded))

    def test_g5_local_sqlite_mode_still_allows_pragma(self):
        """G5：SQLite 本地模式下 PRAGMA 必须照常可用（R11 只针对网关）。"""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "local.db")
            with sqlite3.connect(db_path) as raw:
                raw.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, amount REAL)")
            executors = build_source_executors(OntologyStore(), db_path)
            output = str(executors["Ontology-FactQuery"]({"sql": "PRAGMA table_info('orders')"}, tmp))
        self.assertNotRegex(output, r"error|not permitted", msg="本地 PRAGMA 被误挡：" + output)
        self.assertIn("amount", output, msg="本地 PRAGMA 没有返回列信息：" + output)

    def test_g6_hybrid_validator_defaults_are_unchanged(self):
        """G6：默认（未指定引擎）校验语义不变，避免误伤既有 SQLite 路径。"""
        self.assertIsNone(_validate_sql("SELECT 1"))
        self.assertIsNone(_validate_sql("PRAGMA table_info('orders')"))
        self.assertIsNotNone(_validate_sql("PRAGMA journal_mode=WAL"))
        self.assertIsNotNone(_validate_sql("SELECT 1; DROP TABLE t"))


if __name__ == "__main__":
    unittest.main()
