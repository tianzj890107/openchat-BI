"""RED tests for 本体对象消歧 + 本体库详情收口（分析 Agent P1 批）.

Contract source: ``docs/specs/ontology-object-resolution-and-repository-detail.md``
（依据 ``API/本体MAL层API.md`` §意图确认(新) 与 §获取本体库信息(新)）。

Every assertion drives the **real production** entry points:

* ``bi_agent.tools.remote_ontology_tools.remote_specs`` → ``Ontology-TermDisambiguate`` /
  ``Ontology-EntityDescribe`` / ``Ontology-SemanticQuery`` / ``MetricCalculation``；
* ``bi_agent.web.app._remote_repository_catalog`` → 数据源目录；
* ``GET /api/sources`` → 目录的两个出口。

The loopback fake only *serves* the documented MAL payloads; nothing here
re-implements classification, ranking or parsing.

Two audited defects make this file RED today:

1. 对象消歧走的是"全量下拉 + 本地排序猜"：``Ontology-TermDisambiguate`` 只查 ``Term``、
   ``Ontology-EntityDescribe`` 对 13 个候选类型各发一条 ``SELECT FROM <Type> LIMIT 2000``，
   最终 ``typeName`` 由本地 ``_rank_row`` 决定；权威接口
   ``POST /api/v1/analysis/context/resolve-ontology-object``（客户端已有
   ``RemoteOntologyClient.ensure_object``）**没有任何生产调用方**。
2. 本体库详情接口 ``GET /api/v1/analysis/context/ontology-repository/{id}``
   （``RemoteOntologyClient.repository_info``）同样没有调用方，因此
   ``_remote_repository_catalog`` 只翻列表分页，``cdcTopicPrefix`` 没有任何出口。

Offline and deterministic: loopback only, no credentials, no real service, no LLM,
no user data.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from unittest import mock

from fastapi.testclient import TestClient

from bi_agent.ontology.remote import RemoteOntologyClient
from bi_agent.tools.remote_ontology_tools import remote_specs
from bi_agent.web.app import STATE, _remote_repository_catalog, app


# ---------------------------------------------------------------------------
# documented paths
# ---------------------------------------------------------------------------

META_NEW = "/api/v1/analysis/meta/query"
RESOLVE_NEW = "/api/v1/analysis/context/resolve-ontology-object"
EXPAND_NEW = "/api/v1/analysis/context/expand-ontology-context"
REPO_LIST_NEW = "/api/v1/analysis/context/ontology-repository"
REPO_DETAIL_NEW = "/api/v1/analysis/context/ontology-repository/1"

RESOLVE_LEGACY = "/agent/ontology/ensureOntologyObject"
REPO_LIST_LEGACY = "/system/manager/ontology-repository"
REPO_DETAIL_LEGACY = "/system/manager/ontology-repository/1"

#: 文档 §意图确认(新) 给出的候选类型枚举（顺序即文档顺序）。
DOC_CANDIDATE_TYPES = [
    "BusinessObject", "LogicalEntity", "BusinessAttribute", "Term", "Dimension",
    "Indicator", "Rule", "Activity", "Process", "EntityRelation", "MetaRelation",
    "TableNode", "Column",
]

#: 每个工具的权威类型（Spec §4.2 第 3 条）。
AUTHORITATIVE_TYPE = {
    "Ontology-TermDisambiguate": "Term",
    "MetricCalculation": "Indicator",
    "Ontology-EntityDescribe": "BusinessObject",
    "Ontology-SemanticQuery": "BusinessObject",
}

#: 权威接口给出的命中行（`properties` 在 row 根级展开）。
AUTHORITATIVE_ROW = {
    "typeName": "LogicalEntity",
    "code": "LE000009",
    "name": "prHeader",
    "physicalTable": "dwd_pr_header",
}
AUTHORITATIVE_CODE = "LE000009"
AUTHORITATIVE_TYPE_NAME = "LogicalEntity"

#: 本地候选池里唯一能命中 `prHeader` 的行 —— 今天生产答案就来自这里。
LOCAL_TERM_ROW = {"code": "T0001", "name": "prHeader", "label": "采购申请头"}
LOCAL_CODES = {"T0001"}

METRIC_ROW = {"code": "M0001", "name": "采购金额", "label": "采购金额"}

CATALOG_ROWS = [
    {"id": 1, "name": "开发本体库", "description": "dev", "currentDatabase": "ontology_dev",
     "metaDatabase": "arcade_meta"},
    {"id": 2, "name": "测试本体库", "description": "test", "currentDatabase": "ontology_test",
     "metaDatabase": "arcade_meta_test"},
]
DETAIL_PREFIX = "eimosp.cdc.dev"
CDCP = "cdcTopicPrefix"


# ---------------------------------------------------------------------------
# payload builders (documented MAL dialect)
# ---------------------------------------------------------------------------

def table(rows: list[dict], **extra: Any) -> dict:
    """``QueryResponse(TABLE)``: rows live under ``data.result``."""
    data: dict[str, Any] = {"result": {"rows": rows, "columns": []}}
    data.update(extra)
    return {"code": 200, "success": True, "data": data}


def legacy_rows(rows: list[dict]) -> dict:
    return {"code": 200, "success": True, "data": {"results": [{"rows": rows}]}}


def legacy_repositories(items: list[dict], total: int) -> dict:
    return {"code": 200, "success": True,
            "data": {"items": items, "pagination": {"total": total}}}


def _type_of_script(body: Any) -> str:
    sql = str(((body or {}).get("analysisConfig") or {}).get("sql") or "")
    match = re.search(r"SELECT FROM (\w+)", sql)
    return match.group(1) if match else ""


# ---------------------------------------------------------------------------
# loopback fake MAL service
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # keep pytest output clean
        pass

    def _dispatch(self, method: str) -> None:
        fake: "_FakeMal" = self.server.fake  # type: ignore[attr-defined]
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            body: Any = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = raw
        fake.calls.append({
            "method": method,
            "path": parsed.path,
            "query": {key: values[0] for key, values in parse_qs(parsed.query).items()},
            "body": body,
            "headers": {key.lower(): value for key, value in self.headers.items()},
        })
        responder = fake.routes.get(parsed.path)
        if responder is None:
            status, payload = 404, {"success": False, "code": 404,
                                    "msg": f"no fake route for {parsed.path}"}
        else:
            status, payload = responder(fake.calls[-1])
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


class _FakeMal:
    """Loopback server that records every request the production client makes."""

    def __init__(self) -> None:
        self.routes: dict[str, Callable[[dict], tuple[int, dict]]] = {}
        self.calls: list[dict[str, Any]] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.fake = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(
            target=lambda: self._server.serve_forever(poll_interval=0.02), daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def on(self, path: str, payload: Any, status: int = 200) -> "_FakeMal":
        self.routes[path] = lambda _call: (status, payload)
        return self

    def on_func(self, path: str, responder: Callable[[dict], tuple[int, dict]]) -> "_FakeMal":
        self.routes[path] = responder
        return self

    def client(self, **kwargs: Any) -> RemoteOntologyClient:
        # cache_ttl=0 keeps every call observable: the object cache would
        # otherwise hide the second lookup inside one test method.
        with mock.patch.dict(os.environ, {"ONTOLOGY_CACHE_TTL_SECONDS": "0"}):
            return RemoteOntologyClient(self.base_url, "1", **kwargs)

    # -- recording helpers ----------------------------------------------
    def paths(self) -> list[str]:
        return [call["path"] for call in self.calls]

    def calls_to(self, path: str) -> list[dict[str, Any]]:
        return [call for call in self.calls if call["path"] == path]

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


# ---------------------------------------------------------------------------
# contract checkers (shared by the red assertions *and* the mutation guards)
# ---------------------------------------------------------------------------

def candidate_type_violations(candidate_types: Any, authoritative: str) -> list[str]:
    """Spec §4.2 第 3 条：非空、首项为权威类型、全部来自文档枚举、无重复。"""
    violations: list[str] = []
    if not isinstance(candidate_types, list) or not candidate_types:
        return ["candidateTypes_empty"]
    if candidate_types[0] != authoritative:
        violations.append("authoritative_type_not_first")
    undocumented = [item for item in candidate_types if item not in DOC_CANDIDATE_TYPES]
    if undocumented:
        violations.append("undocumented_types:" + ",".join(str(item) for item in undocumented))
    if len(set(candidate_types)) != len(candidate_types):
        violations.append("duplicated_types")
    return violations


def confirmation_hit_violations(
    output: str, authoritative: dict[str, Any], local_codes: set[str]
) -> list[str]:
    """Spec §4.2 第 4 条：命中必须使用接口给出的 `typeName` 与展开属性。

    ``local_codes`` are codes that only the *local* candidate pool can produce:
    seeing one in the answer means local ranking overrode the authority.
    """
    violations: list[str] = []
    if str(authoritative["code"]) not in output:
        violations.append("authoritative_code_missing")
    if str(authoritative["typeName"]) not in output:
        violations.append("authoritative_type_missing")
    for key in ("physicalTable",):
        value = authoritative.get(key)
        if value and str(value) not in output:
            violations.append(f"expanded_property_missing:{key}")
    for code in sorted(local_codes):
        if code in output:
            violations.append(f"local_candidate_leaked:{code}")
    return violations


def detail_scope_violations(
    entries: list[dict[str, Any]], expected_prefixes: dict[str, str]
) -> list[str]:
    """Spec §4.3：每条目的 `cdcTopicPrefix` 只能来自它自己的来源，无值必须是空串。"""
    violations: list[str] = []
    for entry in entries:
        repository_id = str(entry.get("id"))
        expected = expected_prefixes.get(repository_id, "")
        if CDCP not in entry:
            violations.append(f"cdcTopicPrefix_missing:{repository_id}")
        elif entry[CDCP] != expected:
            violations.append(f"cdcTopicPrefix_wrong:{repository_id}")
    return violations


_OBJECT_BADGE_RE = re.compile(r"\[[^\]]+\][^\n]*\((?:[A-Za-z]+)\)")


@contextmanager
def isolated_state(**overrides: Any):
    """Patch the module-level source state and always restore it."""
    names = ("cwd", "remote_ontology", "ontology_backend", "ontology_namespace",
             "doris_database", "remote_catalog_error", "remote_catalog_last_attempt")
    previous = {name: getattr(STATE, name) for name in names}
    try:
        for name, value in overrides.items():
            setattr(STATE, name, value)
        yield STATE
    finally:
        for name, value in previous.items():
            setattr(STATE, name, value)


class _MalTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = _FakeMal()
        self.addCleanup(self.fake.close)
        self.client = self.fake.client()
        self.tools = {schema["name"]: executor for schema, executor in remote_specs(self.client)}

    # -- fixtures --------------------------------------------------------
    def serve_local_types(self, rows: dict[str, list[dict]] | None = None) -> None:
        """Serve the local full-pull metadata queries (`SELECT FROM <Type> LIMIT n`)."""
        pool = {"Term": [dict(LOCAL_TERM_ROW)], "Indicator": [dict(METRIC_ROW)]}
        pool.update(rows or {})

        def responder(call: dict) -> tuple[int, dict]:
            return 200, table(list(pool.get(_type_of_script(call["body"]), [])))

        self.fake.on_func(META_NEW, responder)

    def serve_authority(self, row: dict[str, Any] | None = None, *, status: int = 200) -> None:
        payload = table([] if row is None else [dict(row)])
        self.fake.on(RESOLVE_NEW, payload, status=status)

    def serve_graph(self) -> None:
        self.fake.on(EXPAND_NEW, table([
            {"typeName": "BusinessAttribute", "code": "ATT01", "name": "prHeaderNo"},
        ]))

    def serve_catalog(self, detail: dict[str, Any] | None = None, *, detail_status: int = 200) -> None:
        self.fake.on(REPO_LIST_NEW, table(
            [dict(row) for row in CATALOG_ROWS],
            pagination={"pageNum": 1, "pageSize": 100, "total": len(CATALOG_ROWS)},
        ))
        payload = table([] if detail is None else [dict(detail)])
        self.fake.on(REPO_DETAIL_NEW, payload, status=detail_status)

    # -- assertions ------------------------------------------------------
    def assert_confirmation_requested(self, name: str, tool: str) -> dict[str, Any]:
        calls = self.fake.calls_to(RESOLVE_NEW)
        self.assertTrue(calls, msg=(
            f"尚未实现：{tool} 没有请求权威确认接口 POST {RESOLVE_NEW}；"
            "今天它只做本地全量下拉（SELECT FROM <Type> LIMIT …）+ 本地排序。"
        ))
        body = calls[-1]["body"] or {}
        self.assertEqual((body.get("analysisConfig") or {}).get("name"), name)
        return calls[-1]

    def candidates_of(self, call: dict[str, Any]) -> Any:
        return ((call.get("body") or {}).get("analysisConfig") or {}).get("candidateTypes")

    def full_pull_calls(self) -> list[dict[str, Any]]:
        return [
            call for call in self.fake.calls_to(META_NEW)
            if "SELECT FROM " in str(((call.get("body") or {}).get("analysisConfig") or {}).get("sql") or "")
        ]


# ---------------------------------------------------------------------------
# R1-R4 / R10 权威确认：请求形状与命中
# ---------------------------------------------------------------------------

class ConfirmationRequestTests(_MalTestCase):
    def test_r1_term_disambiguate_asks_the_authority_to_confirm_the_object(self):
        """R1：单个术语必须走 ``resolve-ontology-object``。"""
        self.serve_local_types()
        self.serve_authority(AUTHORITATIVE_ROW)
        output = self.tools["Ontology-TermDisambiguate"]({"term": "prHeader"}, ".")
        self.assert_confirmation_requested("prHeader", "Ontology-TermDisambiguate")
        self.assertNotIn("remote error", output)

    def test_r2_confirmation_body_is_the_documented_request(self):
        """R2：``analysisConfig.name`` + 非空 ``candidateTypes`` + ``commonConfig == {}``。"""
        self.serve_local_types()
        self.serve_authority(AUTHORITATIVE_ROW)
        self.tools["Ontology-TermDisambiguate"]({"term": "prHeader"}, ".")
        call = self.assert_confirmation_requested("prHeader", "Ontology-TermDisambiguate")
        body = call["body"]
        self.assertEqual(sorted(body), ["analysisConfig", "commonConfig"])
        self.assertEqual(body["commonConfig"], {})
        self.assertEqual(candidate_type_violations(self.candidates_of(call), "Term"), [])
        self.assertEqual(call["method"], "POST")

    def test_r3_candidate_types_are_the_authoritative_type_first_and_stable(self):
        """R3：每个工具首项是自己 的权威类型，两次调用逐字一致。"""
        self.serve_local_types()
        self.serve_authority(AUTHORITATIVE_ROW)
        self.serve_graph()
        observed: dict[str, list[Any]] = {}
        for tool, params in (
            ("Ontology-TermDisambiguate", {"term": "prHeader"}),
            ("Ontology-TermDisambiguate", {"term": "prHeader"}),
            ("MetricCalculation", {"metric": "采购金额"}),
            ("Ontology-EntityDescribe", {"entity": "prHeader"}),
            ("Ontology-SemanticQuery", {"query": "prHeader"}),
        ):
            self.fake.calls.clear()
            self.tools[tool](params, ".")
            calls = self.fake.calls_to(RESOLVE_NEW)
            self.assertTrue(calls, msg=(
                f"尚未实现：{tool} 未调用 {RESOLVE_NEW}，"
                "因此 candidateTypes 契约（权威类型优先、顺序稳定）无法成立。"
            ))
            observed.setdefault(tool, []).append(self.candidates_of(calls[-1]))
            self.assertEqual(
                candidate_type_violations(self.candidates_of(calls[-1]), AUTHORITATIVE_TYPE[tool]),
                [], msg=f"{tool} 的 candidateTypes 不符合 Spec §4.2 第 3 条",
            )
        self.assertEqual(observed["Ontology-TermDisambiguate"][0],
                         observed["Ontology-TermDisambiguate"][1],
                         "同一工具两次调用的 candidateTypes 必须逐字一致")

    def test_r4_hit_uses_the_authoritative_type_name_and_expanded_properties(self):
        """R4：命中的答案必须来自接口，而不是本地候选。"""
        self.serve_local_types()
        self.serve_authority(AUTHORITATIVE_ROW)
        output = self.tools["Ontology-TermDisambiguate"]({"term": "prHeader"}, ".")
        self.assertEqual(
            confirmation_hit_violations(output, AUTHORITATIVE_ROW, LOCAL_CODES), [],
            msg=("命中时必须以接口返回的 typeName/展开属性作答；"
                 f"今天输出为 {output!r}（本地候选池）"),
        )

    def test_r10_metric_calculation_confirms_as_indicator_first(self):
        """R10：``MetricCalculation`` 的确认首项是 ``Indicator``。"""
        self.serve_local_types()
        self.serve_authority({"typeName": "Indicator", "code": "M0001", "name": "采购金额"})
        output = self.tools["MetricCalculation"]({"metric": "采购金额"}, ".")
        call = self.assert_confirmation_requested("采购金额", "MetricCalculation")
        self.assertEqual(candidate_type_violations(self.candidates_of(call), "Indicator"), [])
        self.assertIn("M0001", output)


# ---------------------------------------------------------------------------
# R5-R9 命中后的下游行为：图谱锚点、无全量下拉、未命中、降级、不放大
# ---------------------------------------------------------------------------

class ConfirmationDownstreamTests(_MalTestCase):
    def test_r5_entity_describe_expands_with_the_confirmed_identity(self):
        """R5：``Ontology-EntityDescribe`` 用接口给出的 type+code 去展开上下文。"""
        self.serve_local_types()
        self.serve_authority(AUTHORITATIVE_ROW)
        self.serve_graph()
        output = self.tools["Ontology-EntityDescribe"]({"entity": "prHeader"}, ".")
        expand = self.fake.calls_to(EXPAND_NEW)
        self.assertTrue(expand, msg="Ontology-EntityDescribe 未调用 expand-ontology-context")
        self.assertEqual(expand[-1]["query"].get("type"), AUTHORITATIVE_TYPE_NAME,
                         msg="展开上下文必须使用权威接口给出的 typeName")
        self.assertEqual(expand[-1]["query"].get("code"), AUTHORITATIVE_CODE,
                         msg="展开上下文必须使用权威接口给出的 code")
        self.assertEqual(
            confirmation_hit_violations(output, AUTHORITATIVE_ROW, LOCAL_CODES), [],
        )

    def test_r6_confirmed_lookup_does_not_full_pull_every_candidate_type(self):
        """R6：命中路径不得再出现 ``SELECT FROM <Type> LIMIT …`` 全量下拉。"""
        self.serve_local_types()
        self.serve_authority(AUTHORITATIVE_ROW)
        self.serve_graph()
        for tool, params in (
            ("Ontology-TermDisambiguate", {"term": "prHeader"}),
            ("Ontology-EntityDescribe", {"entity": "prHeader"}),
        ):
            self.fake.calls.clear()
            output = self.tools[tool](params, ".")
            pulls = self.full_pull_calls()
            self.assertEqual(pulls, [], msg=(
                f"尚未实现：{tool} 命中后仍然做了 {len(pulls)} 次全量下拉"
                "（今天 EntityDescribe 会对 13 个候选类型各拉一次）。"
            ))
            self.assertNotIn("remote error", output)

    def test_r7_miss_reports_no_such_object_instead_of_a_lookalike(self):
        """R7：未命中必须明确"本体库没有该对象"，不得用近似候选冒名。"""
        self.serve_local_types()
        self.serve_authority(None)  # data.result.rows = [] → found=False
        output = self.tools["Ontology-TermDisambiguate"]({"term": "prHeader"}, ".")
        self.assert_confirmation_requested("prHeader", "Ontology-TermDisambiguate")
        self.assertIn("prHeader", output)
        badge = _OBJECT_BADGE_RE.search(output)
        self.assertIsNone(badge, msg=(
            "未命中时不得输出任何对象徽标/属性；今天输出为本地近似候选："
            f"{output!r}"
        ))

    def test_r8_authority_failure_degrades_with_a_note_instead_of_erroring(self):
        """R8：确认接口失败 → 降级到本地候选 + 降级说明，不抛错、不谎称不存在。"""
        self.serve_local_types()
        self.serve_authority(None, status=500)
        output = self.tools["Ontology-TermDisambiguate"]({"term": "prHeader"}, ".")
        self.assert_confirmation_requested("prHeader", "Ontology-TermDisambiguate")
        self.assertIn(LOCAL_TERM_ROW["code"], output,
                      msg="确认失败必须降级到本地候选，而不是返回空结果")
        self.assertNotIn("remote error", output,
                         msg="降级路径不得把传输错误直接抛给模型")
        self.assertTrue(
            any(marker in output for marker in ("回退", "降级", "不可用")),
            msg=("确认失败必须在答案里带降级说明（例如"
                 "「（本体确认接口不可用，已回退到本地候选）」）；"
                 f"今天输出为 {output!r}"),
        )

    def test_r9_free_text_queries_never_hit_the_confirmation_endpoint(self):
        """R9（护栏）：模糊/多词输入不得发确认请求 —— 搜索不能被换成精确确认。"""
        self.serve_local_types()
        self.serve_authority(AUTHORITATIVE_ROW)
        for query in ("采购金额下降的原因", "华东 逾期 订单"):
            self.fake.calls.clear()
            output = self.tools["Ontology-SemanticQuery"]({"query": query}, ".")
            self.assertEqual(self.fake.calls_to(RESOLVE_NEW), [],
                             msg=f"模糊输入 {query!r} 不应走精确确认接口")
            self.assertTrue(output.strip(),
                            msg=f"模糊输入 {query!r} 仍必须走既有搜索路径并给出答案")
            self.assertNotIn("remote error", output)


# ---------------------------------------------------------------------------
# R11-R16 本体库详情
# ---------------------------------------------------------------------------

class RepositoryDetailTests(_MalTestCase):
    def test_r11_catalog_requests_the_detail_of_the_active_repository(self):
        """R11：目录必须对当前激活库调用详情接口。"""
        self.serve_catalog({**CATALOG_ROWS[0], CDCP: DETAIL_PREFIX})
        entries = _remote_repository_catalog(self.client)
        detail_calls = self.fake.calls_to(REPO_DETAIL_NEW)
        self.assertTrue(detail_calls, msg=(
            f"尚未实现：目录没有调用 GET {REPO_DETAIL_NEW}"
            "（今天只翻列表分页，repository_info 无调用方）。"
        ))
        self.assertEqual(len(detail_calls), 1, "只应对当前激活库请求一次详情")
        self.assertEqual(len(entries), 2)

    def test_r12_catalog_exposes_cdc_topic_prefix_from_its_own_source(self):
        """R12：``cdcTopicPrefix`` 来自各自来源；不得把激活库详情复用到别的库。"""
        self.serve_catalog({**CATALOG_ROWS[0], CDCP: DETAIL_PREFIX})
        entries = _remote_repository_catalog(self.client)
        self.assertEqual(
            detail_scope_violations(entries, {"1": DETAIL_PREFIX}), [],
            msg="详情字段缺失或串库",
        )

    def test_r14_detail_failure_keeps_the_catalog_usable(self):
        """R14：详情失败不得影响目录可用性与既有字段。"""
        self.serve_catalog(None, detail_status=500)
        entries = _remote_repository_catalog(self.client)
        self.assertTrue(self.fake.calls_to(REPO_DETAIL_NEW),
                        msg="尚未实现：详情失败路径根本不会被触发，因为今天不调详情")
        self.assertEqual([entry["id"] for entry in entries], ["1", "2"])
        self.assertEqual(entries[0]["name"], CATALOG_ROWS[0]["name"])
        self.assertEqual(entries[0]["dorisDatabase"], CATALOG_ROWS[0]["currentDatabase"])
        with tempfile.TemporaryDirectory() as temp_dir:
            with isolated_state(cwd=temp_dir, remote_ontology=self.client,
                                ontology_backend="production", remote_catalog_error="",
                                remote_catalog_last_attempt=0.0):
                payload = json.loads(TestClient(app).get("/api/sources").content)
        self.assertIs(payload["ontology"]["remote_status"]["available"], True)
        self.assertEqual(payload["ontology"]["remote_status"]["message"], "")

    def test_r16_unset_cdc_topic_prefix_is_an_empty_string(self):
        """R16：未配置该字段时必须是空串，不是缺键、null 或报错。"""
        self.serve_catalog({**CATALOG_ROWS[0]})
        entries = _remote_repository_catalog(self.client)
        self.assertEqual(
            detail_scope_violations(entries, {}), [],
            msg="未配置时 cdcTopicPrefix 必须为空串",
        )

    def test_r13_sources_api_exposes_the_same_prefix_on_both_exits(self):
        """R13：``/api/sources`` 的 ontology 与 database 两个出口都要带该字段。"""
        self.serve_catalog({**CATALOG_ROWS[0], CDCP: DETAIL_PREFIX})
        with tempfile.TemporaryDirectory() as temp_dir:
            with isolated_state(cwd=temp_dir, remote_ontology=self.client,
                                ontology_backend="production", remote_catalog_error="",
                                remote_catalog_last_attempt=0.0):
                payload = json.loads(TestClient(app).get("/api/sources").content)
        ontology_repos = payload["ontology"]["remote_repositories"]
        database_repos = payload["database"]["remote_databases"]
        self.assertEqual(
            detail_scope_violations(ontology_repos, {"1": DETAIL_PREFIX}), [],
            msg="尚未实现：ontology.remote_repositories 未透出 cdcTopicPrefix",
        )
        self.assertEqual([repo.get(CDCP) for repo in ontology_repos],
                         [repo.get(CDCP) for repo in database_repos],
                         "两个出口的 cdcTopicPrefix 必须一致")
        self.assertNotIn("password", json.dumps(ontology_repos))


# ---------------------------------------------------------------------------
# R15 旧方言回归（护栏）+ R17 鉴权与不回显
# ---------------------------------------------------------------------------

class LegacyDialectAndAuthTests(_MalTestCase):
    def test_r15_legacy_only_payloads_keep_confirmation_and_catalog_working(self):
        """R15（护栏）：只有旧契约时，确认与目录仍必须可用。"""
        self.fake.on_func(META_NEW, lambda call: (200, table([dict(LOCAL_TERM_ROW)])))
        self.fake.on(RESOLVE_LEGACY, legacy_rows([{**AUTHORITATIVE_ROW}]))
        self.fake.on(REPO_LIST_LEGACY, legacy_repositories(CATALOG_ROWS, len(CATALOG_ROWS)))
        self.fake.on(REPO_DETAIL_LEGACY, legacy_rows([{**CATALOG_ROWS[0], CDCP: DETAIL_PREFIX}]))
        output = self.tools["Ontology-TermDisambiguate"]({"term": "prHeader"}, ".")
        self.assertNotIn("remote error", output)
        self.assertTrue(output.strip(), "旧方言下工具仍必须给出答案")
        entries = _remote_repository_catalog(self.client)
        self.assertEqual([entry["id"] for entry in entries], ["1", "2"])
        self.assertEqual(entries[0]["name"], CATALOG_ROWS[0]["name"])

    def test_r17_authority_and_detail_requests_use_existing_auth_and_leak_nothing(self):
        """R17：沿用既有鉴权头；响应/错误不得回显 token 或 base URL。"""
        token = "test-token-not-a-real-credential"
        client = self.fake.client(app_id="app-x", auth_token=token)
        tools = {schema["name"]: executor for schema, executor in remote_specs(client)}
        self.serve_local_types()
        self.serve_authority(AUTHORITATIVE_ROW)
        self.serve_catalog({**CATALOG_ROWS[0], CDCP: DETAIL_PREFIX})
        output = tools["Ontology-TermDisambiguate"]({"term": "prHeader"}, ".")
        confirm = self.fake.calls_to(RESOLVE_NEW)
        self.assertTrue(confirm, msg="尚未实现：确认请求未发起，无法携带既有鉴权头")
        headers = confirm[-1]["headers"]
        self.assertEqual(headers.get("x-ontology-repository-id"), "1")
        self.assertEqual(headers.get("x-app-id"), "app-x")
        self.assertNotIn(token, output)
        self.assertNotIn(self.fake.base_url, output)

        entries = _remote_repository_catalog(client)
        detail = self.fake.calls_to(REPO_DETAIL_NEW)
        self.assertTrue(detail, msg="尚未实现：详情请求未发起，无法携带既有鉴权头")
        self.assertEqual(detail[-1]["headers"].get("x-ontology-repository-id"), "1")
        blob = json.dumps(entries, ensure_ascii=False)
        self.assertNotIn(token, blob)
        self.assertNotIn(self.fake.base_url, blob)


# ---------------------------------------------------------------------------
# Mutation guards：这些检查器必须能杀死对应变异
# ---------------------------------------------------------------------------

class MutationGuardTests(unittest.TestCase):
    def test_mutation_empty_candidate_types_is_killed(self):
        self.assertIn("candidateTypes_empty", candidate_type_violations([], "Term"))
        self.assertIn("candidateTypes_empty", candidate_type_violations(None, "Term"))

    def test_mutation_authoritative_type_not_first_is_killed(self):
        self.assertIn("authoritative_type_not_first",
                      candidate_type_violations(["BusinessObject", "Term"], "Term"))

    def test_mutation_undocumented_or_duplicated_candidate_type_is_killed(self):
        self.assertIn("undocumented_types:Widget",
                      candidate_type_violations(["Term", "Widget"], "Term"))
        self.assertIn("duplicated_types",
                      candidate_type_violations(["Term", "Term"], "Term"))

    def test_mutation_local_ranking_override_is_killed(self):
        """本地排序覆盖权威 typeName/属性时必须被发现。"""
        local_only = "[T0001] 采购申请头 (Term)\n  name: prHeader"
        violations = confirmation_hit_violations(local_only, AUTHORITATIVE_ROW, LOCAL_CODES)
        self.assertIn("authoritative_code_missing", violations)
        self.assertIn("authoritative_type_missing", violations)
        self.assertIn("expanded_property_missing:physicalTable", violations)
        self.assertIn("local_candidate_leaked:T0001", violations)

    def test_mutation_fabricated_authority_hit_is_killed(self):
        """只把本地候选改个类型名、仍不带接口属性，也必须被发现。"""
        renamed = "[T0001] 采购申请头 (LogicalEntity)"
        violations = confirmation_hit_violations(renamed, AUTHORITATIVE_ROW, LOCAL_CODES)
        self.assertIn("authoritative_code_missing", violations)
        self.assertIn("expanded_property_missing:physicalTable", violations)
        self.assertIn("local_candidate_leaked:T0001", violations)

    def test_mutation_detail_value_reused_for_every_repository_is_killed(self):
        entries = [{"id": "1", CDCP: DETAIL_PREFIX}, {"id": "2", CDCP: DETAIL_PREFIX}]
        self.assertIn("cdcTopicPrefix_wrong:2",
                      detail_scope_violations(entries, {"1": DETAIL_PREFIX}))

    def test_mutation_missing_or_null_cdc_topic_prefix_is_killed(self):
        self.assertIn("cdcTopicPrefix_missing:1", detail_scope_violations([{"id": "1"}], {}))
        self.assertIn("cdcTopicPrefix_wrong:1",
                      detail_scope_violations([{"id": "1", CDCP: None}], {}))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
