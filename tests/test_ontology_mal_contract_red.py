"""RED tests for the MAL (本体 MAL 层) 契约迁移.

Contract source: ``docs/specs/ontology-mal-contract-migration.md``.

Every assertion runs the **real production** code against a loopback HTTP server
that speaks the documented MAL dialect:

* ``bi_agent.ontology.remote.RemoteOntologyClient`` — real transport, real
  normalisation;
* ``bi_agent.tools.sql_tools._doris_query`` — the real business-data path;
* ``bi_agent.web.app._remote_repository_catalog`` — the real data-source
  catalogue used by the source switcher.

Nothing here re-implements parsing: the fake server only *serves* payloads, and
the assertions describe what must come back out of production.

The file is RED before the migration.  The服务 side now documents a
``QueryRequest``/``QueryResponse`` family under ``/api/v1/analysis/...`` while the
client still speaks ``/agent/ontology/*`` + ``/system/manager/ontology-repository``
and parses only ``data.results[].rows`` / ``data.items`` / ``data.objects`` /
``data.rows``.  Both dialects are live, so the client must normalise at the
transport boundary and keep callers unchanged.

Offline and deterministic: loopback only, no credentials, no real service, no
LLM, no user data.
"""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from bi_agent.ontology.remote import OntologyApiError, RemoteOntologyClient
from bi_agent.tools.analysis_policy import build_cognitive_policy_decision
from bi_agent.tools.remote_ontology_tools import _related_objects
from bi_agent.tools.sql_tools import DorisHttpConn, _doris_query
from bi_agent.web.app import _remote_repository_catalog


# ---------------------------------------------------------------------------
# documented paths
# ---------------------------------------------------------------------------

SCRIPT_QUERY_OLD = "/agent/ontology/scriptQuery"
FIND_RELATED_OLD = "/agent/ontology/findRelatedObjects"
ENSURE_OBJECT_OLD = "/agent/ontology/ensureOntologyObject"
REPO_LIST_OLD = "/system/manager/ontology-repository"
DORIS_OLD = "/agent/doris/query"

META_QUERY_NEW = "/api/v1/analysis/meta/query"
DATA_QUERY_NEW = "/api/v1/analysis/data/query"
EXPAND_CONTEXT_NEW = "/api/v1/analysis/context/expand-ontology-context"
RESOLVE_OBJECT_NEW = "/api/v1/analysis/context/resolve-ontology-object"
REPO_LIST_NEW = "/api/v1/analysis/context/ontology-repository"

ALLOWED_TOOLS = [
    "Ontology-MetricQuery",
    "Ontology-FactQuery",
    "Ontology-SemanticQuery",
    "Ontology-TermDisambiguate",
    "Ontology-RelationLookup",
    "Ontology-EntityDescribe",
    "Ontology-ListBusinessObjects",
    "SQL-Execute",
]


# ---------------------------------------------------------------------------
# payload builders
# ---------------------------------------------------------------------------

def new_table(rows: list[dict], columns: list[str] | None = None, **extra: Any) -> dict:
    """``QueryResponse(TABLE)``: rows live under ``data.result``."""
    if columns is None:
        columns = []
        for row in rows:
            for key in row:
                if key not in columns:
                    columns.append(key)
    data: dict[str, Any] = {
        "resultType": "TABLE",
        "result": {
            "columns": [
                {"identifierCode": name, "label": name, "type": "PROPERTY"}
                for name in columns
            ],
            "rows": rows,
        },
    }
    data.update(extra)
    return {"success": True, "code": 200, "msg": "success", "data": data}


def new_graph(vertices: list[dict], links: list[dict], edge_key: str = "links") -> dict:
    return {
        "success": True,
        "code": 200,
        "msg": "success",
        "data": {
            "resultType": "GRAPH",
            "result": {"vertices": vertices, edge_key: links},
        },
    }


def legacy_script(rows: list[dict]) -> dict:
    return {"code": 200, "msg": None, "data": {"results": [{"rows": rows}]}}


def legacy_related(objects: list[dict]) -> dict:
    return {"code": 200, "msg": None, "data": {"objects": objects}}


def legacy_repositories(items: list[dict], total: int) -> dict:
    return {"code": 200, "msg": None, "data": {"items": items, "total": total}}


def legacy_ensure(found: bool) -> dict:
    return {
        "code": 200,
        "msg": None,
        "data": {
            "found": found,
            "objectInfo": {"typeName": "LogicalEntity", "properties": {
                "code": "LE000001", "label": "采购需求头", "name": "prHeader",
            }} if found else None,
        },
    }


def legacy_graph(vertices: list[dict], links: list[dict]) -> dict:
    """``findRelatedObjects``-style OpenCypher reply (``data.results[].rows``)."""
    return {"code": 200, "msg": None, "data": {"results": [{
        "rows": vertices + links,
    }]}}


def legacy_doris(rows: list[dict]) -> dict:
    return {"code": 200, "msg": None, "data": {"rows": rows, "rowCount": len(rows)}}


# ---------------------------------------------------------------------------
# loopback MAL server
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # keep pytest output clean
        pass

    def _dispatch(self, method: str) -> None:
        fake: "_FakeMal" = self.server.fake  # type: ignore[attr-defined]
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
            status, payload = 404, {
                "success": False, "code": 404, "msg": f"no fake route for {parsed.path}",
            }
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

    def on(self, path: str, payload: Any) -> "_FakeMal":
        def responder(_call: dict) -> tuple[int, dict]:
            return 200, payload
        self.routes[path] = responder
        return self

    def on_many(self, paths: list[str], payload: Any) -> "_FakeMal":
        for path in paths:
            self.on(path, payload)
        return self

    def on_func(self, path: str, responder: Callable[[dict], tuple[int, dict]]) -> "_FakeMal":
        self.routes[path] = responder
        return self

    def client(self, **kwargs: Any) -> RemoteOntologyClient:
        return RemoteOntologyClient(self.base_url, "1", **kwargs)

    # -- recording helpers ----------------------------------------------
    def paths(self) -> list[str]:
        return [call["path"] for call in self.calls]

    def last(self) -> dict[str, Any]:
        if not self.calls:
            raise AssertionError("the production code issued no request at all")
        return self.calls[-1]

    def body(self) -> Any:
        return self.last()["body"]

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _quiet(fn: Callable, *args: Any, **kwargs: Any) -> Any:
    """Call production code that is allowed to fail while still being recorded."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - the assertion after the call is the point
        return exc


class _MalTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = _FakeMal()
        self.addCleanup(self.fake.close)
        self.client = self.fake.client()

    # -- shared fixtures -------------------------------------------------
    def serve_search(self, path: str, rows: list[dict]) -> None:
        def responder(call: dict) -> tuple[int, dict]:
            if call["method"] == "POST":
                analysis = (call["body"] or {}).get("analysisConfig") or {}
                if "UNWIND nodes(p)" in str(analysis.get("sql") or ""):
                    return 200, new_table([
                        {"typeNames": ["LogicalEntity"], "properties": {"code": "LE0001"}},
                    ])
                if "MATCH (s)-[r]->(t)" in str(analysis.get("sql") or ""):
                    return 200, new_table([{
                        "sourceCode": "BO0004", "relationType": "Relation",
                        "relationProperties": {"since": "2024"}, "targetCode": "LE0001",
                    }])
            return 200, new_table(rows)
        self.fake.on_func(path, responder)


# ---------------------------------------------------------------------------
# 1. the client must speak the documented new contract
# ---------------------------------------------------------------------------

class RequestContractTests(_MalTestCase):
    def test_script_query_uses_the_documented_meta_endpoint(self):
        self.fake.on(META_QUERY_NEW, new_table([{"code": "BO0004"}]))
        _quiet(self.client.script_query, "sql", "SELECT FROM BusinessObject LIMIT 5")
        self.assertEqual(self.fake.last()["method"], "POST")
        self.assertEqual(self.fake.last()["path"], META_QUERY_NEW)

    def test_script_query_body_is_a_query_request(self):
        self.fake.on(META_QUERY_NEW, new_table([{"code": "BO0004"}]))
        _quiet(self.client.script_query, "sql", "SELECT FROM BusinessObject LIMIT 5")
        body = self.fake.body()
        self.assertEqual(body, {
            "analysisConfig": {"language": "sql", "sql": "SELECT FROM BusinessObject LIMIT 5"},
            "commonConfig": {},
        })

    def test_script_query_keeps_parameters_in_analysis_config(self):
        self.fake.on(META_QUERY_NEW, new_table([{"code": "BO0004"}]))
        _quiet(self.client.script_query, "opencypher",
               "MATCH (n) WHERE n.code = $code RETURN n", [["code", "BO0004"]])
        body = self.fake.body()
        self.assertEqual(body["analysisConfig"]["language"], "opencypher")
        self.assertEqual(body["analysisConfig"]["paramsList"], [["code", "BO0004"]])
        self.assertEqual(body["commonConfig"], {})

    def test_script_query_never_calls_the_legacy_endpoint(self):
        self.fake.on(META_QUERY_NEW, new_table([{"code": "BO0004"}]))
        _quiet(self.client.script_query, "sql", "SELECT FROM BusinessObject LIMIT 5")
        self.assertNotIn(SCRIPT_QUERY_OLD, self.fake.paths())

    def test_find_related_uses_the_documented_expand_context_endpoint(self):
        self.fake.on(EXPAND_CONTEXT_NEW, new_table([]))
        _quiet(self.client.find_related, "BusinessObject", "BO0004", 2)
        call = self.fake.last()
        self.assertEqual(call["method"], "GET")
        self.assertEqual(call["path"], EXPAND_CONTEXT_NEW)
        self.assertEqual(call["query"], {"type": "BusinessObject", "code": "BO0004", "depth": "2"})
        self.assertNotIn(FIND_RELATED_OLD, self.fake.paths())

    def test_find_related_clamps_depth_on_the_new_endpoint(self):
        self.fake.on(EXPAND_CONTEXT_NEW, new_table([]))
        _quiet(self.client.find_related, "BusinessObject", "BO0004", 9)
        call = self.fake.last()
        self.assertEqual(call["path"], EXPAND_CONTEXT_NEW)
        self.assertEqual(call["query"]["depth"], "5")
        self.assertEqual(call["query"]["code"], "BO0004")

    def test_list_repositories_uses_the_documented_context_endpoint(self):
        self.fake.on(REPO_LIST_NEW, new_table([], pagination={"pageNum": 1, "pageSize": 100, "total": 0}))
        _quiet(self.client.list_repositories, page=1, size=100)
        call = self.fake.last()
        self.assertEqual(call["method"], "GET")
        self.assertEqual(call["path"], REPO_LIST_NEW)
        self.assertEqual(call["query"], {"page": "1", "size": "100"})
        self.assertEqual(call["headers"].get("x-ontology-repository-id"), "1")

    def test_list_repositories_can_omit_the_repository_header(self):
        self.fake.on(REPO_LIST_NEW, new_table([], pagination={"pageNum": 1, "pageSize": 100, "total": 0}))
        _quiet(self.client.list_repositories, page=2, size=50)
        call = self.fake.last()
        self.assertEqual(call["path"], REPO_LIST_NEW)
        self.assertEqual(call["query"], {"page": "2", "size": "50"})
        self.assertNotIn("x-ontology-repository-id", call["headers"])

    def test_repository_info_uses_the_documented_context_endpoint(self):
        self.fake.on(f"{REPO_LIST_NEW}/1", new_table([{"id": 1, "name": "开发本体库-Doris"}]))
        _quiet(self.client.repository_info)
        call = self.fake.last()
        self.assertEqual(call["method"], "GET")
        self.assertEqual(call["path"], f"{REPO_LIST_NEW}/1")

    def test_resolve_object_uses_the_documented_context_endpoint(self):
        self.fake.on(RESOLVE_OBJECT_NEW, new_table([{"typeName": "LogicalEntity", "code": "LE000001"}]))
        _quiet(self.client.ensure_object, "prHeader", ["BusinessObject", "LogicalEntity"])
        call = self.fake.last()
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["path"], RESOLVE_OBJECT_NEW)
        self.assertEqual(self.fake.body(), {
            "analysisConfig": {"name": "prHeader",
                               "candidateTypes": ["BusinessObject", "LogicalEntity"]},
            "commonConfig": {},
        })
        self.assertNotIn(ENSURE_OBJECT_OLD, self.fake.paths())

    def test_metadata_query_keeps_the_documented_contract(self):
        self.fake.on(META_QUERY_NEW, new_table([{"code": "M0001"}]))
        analysis = {"vertex": [{"type": "Indicator", "properties": [{"name": "code"}]}]}
        common = {"pagination": {"pageNum": 1, "pageSize": 10}}
        self.client.metadata_query(analysis, common)
        self.assertEqual(self.fake.last()["path"], META_QUERY_NEW)
        self.assertEqual(self.fake.body(), {"analysisConfig": analysis, "commonConfig": common})

    def test_data_query_keeps_the_documented_contract(self):
        self.fake.on(DATA_QUERY_NEW, new_table([{"value": 1}]))
        analysis = {"metric": "M0001"}
        self.client.data_query(analysis, {})
        self.assertEqual(self.fake.last()["path"], DATA_QUERY_NEW)
        self.assertEqual(self.fake.body(), {"analysisConfig": analysis, "commonConfig": {}})

    def test_no_migrated_flow_touches_an_agent_ontology_path(self):
        self.serve_search(META_QUERY_NEW, [{"code": "BO0004"}])
        self.fake.on(EXPAND_CONTEXT_NEW, new_table([]))
        self.fake.on(REPO_LIST_NEW, new_table([], pagination={"pageNum": 1, "pageSize": 100, "total": 0}))
        self.fake.on(f"{REPO_LIST_NEW}/1", new_table([{"id": 1}]))
        self.fake.on(RESOLVE_OBJECT_NEW, new_table([]))
        _quiet(self.client.script_query, "sql", "SELECT FROM BusinessObject LIMIT 5")
        _quiet(self.client.find_related, "BusinessObject", "BO0004", 2)
        _quiet(self.client.list_repositories)
        _quiet(self.client.repository_info)
        _quiet(self.client.ensure_object, "prHeader", ["LogicalEntity"])
        leaked = [path for path in self.fake.paths()
                  if path.startswith("/agent/") or path.startswith("/system/")]
        self.assertEqual(leaked, [])


# ---------------------------------------------------------------------------
# 2. both live dialects must normalise to the same internal shape
# ---------------------------------------------------------------------------

class DialectEquivalenceTests(unittest.TestCase):
    """Feed legacy and new payloads; the normalised result must be identical."""

    ROWS = [
        {"code": "M0001", "label": "采购金额", "name": "purchaseAmount"},
        {"code": "M0002", "label": "到货周期", "name": "leadTime"},
    ]
    RELATED = [
        {"typeName": "LogicalEntity", "properties": {"code": "LE000001", "name": "prHeader"}},
        {"typeName": "BusinessAttribute", "properties": {"code": "AT0000001"}},
    ]
    REPOS = [
        {"id": 1, "name": "开发本体库-Doris", "description": "本地开发默认库",
         "namespaceCode": "dev", "currentDatabase": "ontology_dev"},
        {"id": 2, "name": "ECore 本体库", "namespaceCode": "ecore",
         "dorisDatabase": "ontology_ecore"},
    ]

    def _legacy(self) -> tuple[_FakeMal, RemoteOntologyClient]:
        fake = _FakeMal()
        fake.on(SCRIPT_QUERY_OLD, legacy_script(self.ROWS))
        fake.on(FIND_RELATED_OLD, legacy_related(self.RELATED))
        fake.on(REPO_LIST_OLD, legacy_repositories(self.REPOS, len(self.REPOS)))
        fake.on(f"{REPO_LIST_OLD}/1", self.REPOS[0])
        fake.on(ENSURE_OBJECT_OLD, legacy_ensure(True))
        return fake, fake.client()

    def _new(self) -> tuple[_FakeMal, RemoteOntologyClient]:
        fake = _FakeMal()
        fake.on(META_QUERY_NEW, new_table(self.ROWS))
        fake.on(EXPAND_CONTEXT_NEW, new_table(self.RELATED))
        fake.on(REPO_LIST_NEW, new_table(self.REPOS, pagination={
            "pageNum": 1, "pageSize": 100, "total": len(self.REPOS)}))
        fake.on(f"{REPO_LIST_NEW}/1", new_table([self.REPOS[0]]))
        fake.on(RESOLVE_OBJECT_NEW, new_table([{
            "typeName": "LogicalEntity", "code": "LE000001",
            "label": "采购需求头", "name": "prHeader",
        }]))
        return fake, fake.client()

    def _both(self) -> list[RemoteOntologyClient]:
        clients = []
        for build in (self._legacy, self._new):
            fake, client = build()
            self.addCleanup(fake.close)
            clients.append(client)
        return clients

    def test_script_query_normalises_to_one_shape(self):
        legacy, new = self._both()
        old = _quiet(legacy.script_query, "sql", "SELECT FROM Indicator LIMIT 5")
        fresh = _quiet(new.script_query, "sql", "SELECT FROM Indicator LIMIT 5")
        self.assertNotIsInstance(fresh, Exception, fresh)
        self.assertEqual(old, fresh, (old, fresh))
        self.assertIn("results", fresh)

    def test_search_objects_rows_are_identical(self):
        legacy, new = self._both()
        old = _quiet(legacy.search_objects, "Indicator", "采购", 5)
        fresh = _quiet(new.search_objects, "Indicator", "采购", 5)
        self.assertNotIsInstance(fresh, Exception, fresh)
        self.assertEqual(old, fresh, (old, fresh))
        self.assertEqual([row.get("code") for row in fresh], ["M0001", "M0002"])

    def test_list_objects_rows_are_identical(self):
        legacy, new = self._both()
        old = _quiet(legacy.list_objects, "Indicator", 10)
        fresh = _quiet(new.list_objects, "Indicator", 10)
        self.assertNotIsInstance(fresh, Exception, fresh)
        self.assertEqual(old, fresh, (old, fresh))
        self.assertEqual(len(fresh), 2)

    def test_find_related_normalises_to_objects(self):
        legacy, new = self._both()
        old = _quiet(legacy.find_related, "BusinessObject", "BO0004", 2)
        fresh = _quiet(new.find_related, "BusinessObject", "BO0004", 2)
        self.assertNotIsInstance(fresh, Exception, fresh)
        self.assertEqual(old, fresh, (old, fresh))
        self.assertEqual(len(_related_objects(fresh)), 2)

    def test_ensure_object_normalises_found_and_object_info(self):
        legacy, new = self._both()
        old = _quiet(legacy.ensure_object, "prHeader", ["LogicalEntity"])
        fresh = _quiet(new.ensure_object, "prHeader", ["LogicalEntity"])
        self.assertNotIsInstance(fresh, Exception, fresh)
        self.assertTrue(fresh["found"])
        self.assertEqual(fresh["objectInfo"]["properties"]["code"], "LE000001")
        self.assertEqual(old["found"], fresh["found"])
        self.assertEqual(old["objectInfo"]["properties"], fresh["objectInfo"]["properties"])

    def test_list_repositories_normalises_items_and_total(self):
        legacy, new = self._both()
        old = _quiet(legacy.list_repositories, page=1, size=100)
        fresh = _quiet(new.list_repositories, page=1, size=100)
        self.assertNotIsInstance(fresh, Exception, fresh)
        self.assertEqual(len(old["items"]), len(fresh["items"]))
        self.assertEqual(old["total"], fresh["total"])
        self.assertEqual(fresh["total"], 2)

    def test_repository_info_normalises_the_single_row(self):
        legacy, new = self._both()
        old = _quiet(legacy.repository_info)
        fresh = _quiet(new.repository_info)
        self.assertNotIsInstance(fresh, Exception, fresh)
        self.assertEqual(old["name"], fresh["name"])
        self.assertEqual(fresh["id"], 1)

    def test_catalog_is_identical_for_both_dialects(self):
        legacy, new = self._both()
        old = _remote_repository_catalog(legacy)
        fresh = _remote_repository_catalog(new)
        self.assertNotIsInstance(fresh, Exception, fresh)
        self.assertEqual([repo["id"] for repo in old], ["1", "2"])
        self.assertEqual([repo["dorisDatabase"] for repo in old],
                         [repo["dorisDatabase"] for repo in fresh])
        self.assertEqual([repo["namespace"] for repo in old], ["dev", "ecore"])

    def test_graph_neighborhood_is_identical_for_both_dialects(self):
        vertices = [{"typeNames": ["LogicalEntity"], "properties": {"code": "LE0001"}}]
        links = [{"sourceCode": "BO0004", "relationType": "R", "relationProperties": {},
                  "targetCode": "LE0001"}]
        legacy_fake, legacy = self._legacy()
        new_fake, new = self._new()
        self.addCleanup(legacy_fake.close)
        self.addCleanup(new_fake.close)
        for fake in (legacy_fake, new_fake):
            fake.on(SCRIPT_QUERY_OLD, legacy_graph(vertices, links))
            fake.on(META_QUERY_NEW, new_graph(vertices, links))
        old = _quiet(legacy.graph_neighborhood, "BusinessObject", "BO0004", depth=2)
        fresh = _quiet(new.graph_neighborhood, "BusinessObject", "BO0004", depth=2)
        self.assertNotIsInstance(fresh, Exception, fresh)
        self.assertEqual(old, fresh, (old, fresh))


# ---------------------------------------------------------------------------
# 3. new-dialect specifics that the legacy parser silently drops
# ---------------------------------------------------------------------------

class NewDialectParsingTests(_MalTestCase):
    def test_list_objects_reads_result_rows(self):
        self.fake.on(META_QUERY_NEW, new_table([{"code": "BO0004"}, {"code": "BO0005"}]))
        rows = self.client.list_objects("BusinessObject", 10)
        self.assertEqual([row["code"] for row in rows], ["BO0004", "BO0005"])

    def test_search_objects_reads_result_rows(self):
        self.fake.on(META_QUERY_NEW, new_table([{"code": "M0001", "label": "采购金额"}]))
        rows = self.client.search_objects("Indicator", "采购", 5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "采购金额")

    def test_list_objects_survives_an_empty_result_set(self):
        self.fake.on(META_QUERY_NEW, new_table([]))
        self.assertEqual(self.client.list_objects("BusinessObject", 10), [])

    def test_find_related_exposes_result_rows_as_objects(self):
        self.fake.on(EXPAND_CONTEXT_NEW, new_table([
            {"typeName": "LogicalEntity", "code": "LE000001", "name": "prHeader"},
        ]))
        related = self.client.find_related("BusinessObject", "BO0004", 2)
        self.assertEqual(len(related["objects"]), 1)
        self.assertEqual(related["objects"][0]["typeName"], "LogicalEntity")
        self.assertEqual(len(_related_objects(related)), 1)

    def test_ensure_object_hit_flattens_properties(self):
        self.fake.on(RESOLVE_OBJECT_NEW, new_table([{
            "typeName": "LogicalEntity", "code": "LE000001",
            "label": "采购需求头", "name": "prHeader",
        }]))
        found = self.client.ensure_object("prHeader", ["LogicalEntity"])
        self.assertTrue(found["found"])
        self.assertEqual(found["objectInfo"]["typeName"], "LogicalEntity")
        self.assertEqual(found["objectInfo"]["properties"]["code"], "LE000001")

    def test_ensure_object_miss_is_empty_not_an_error(self):
        self.fake.on(RESOLVE_OBJECT_NEW, new_table([]))
        found = self.client.ensure_object("nope", ["LogicalEntity"])
        self.assertFalse(found["found"])
        self.assertIsNone(found["objectInfo"])

    def test_list_repositories_reads_rows_and_pagination(self):
        self.fake.on(REPO_LIST_NEW, new_table(
            [{"id": 1, "name": "库一", "currentDatabase": "ontology_one"}],
            pagination={"pageNum": 1, "pageSize": 100, "total": 3}))
        listing = self.client.list_repositories(page=1, size=100)
        self.assertEqual(len(listing["items"]), 1)
        self.assertEqual(listing["total"], 3)

    def test_list_repositories_stops_paginating_on_the_last_page(self):
        self.fake.on(REPO_LIST_NEW, new_table(
            [{"id": 1, "name": "库一"}],
            pagination={"pageNum": 1, "pageSize": 1, "total": 1}))
        catalog = _remote_repository_catalog(self.client)
        self.assertEqual([repo["id"] for repo in catalog], ["1"])
        self.assertEqual(len(self.fake.calls), 1)

    def test_catalog_reads_current_database_from_the_new_field(self):
        self.fake.on(REPO_LIST_NEW, new_table(
            [{"id": 7, "name": "开发本体库-Doris", "namespaceCode": "dev",
              "currentDatabase": "ontology_dev", "metaDatabase": "ontology_dev_all_meta",
              "knowledgeDatabase": "ontology_dev_all_knowledge"}],
            pagination={"pageNum": 1, "pageSize": 100, "total": 1}))
        catalog = _remote_repository_catalog(self.client)
        self.assertEqual(catalog[0]["dorisDatabase"], "ontology_dev")
        self.assertEqual(catalog[0]["namespace"], "dev")
        self.assertTrue(catalog[0]["databaseValue"].endswith(":7"))

    def test_repository_info_reads_the_single_row(self):
        self.fake.on(f"{REPO_LIST_NEW}/1", new_table([{
            "id": 1, "name": "开发本体库-Doris", "currentDatabase": "ontology_dev",
        }]))
        info = self.client.repository_info()
        self.assertEqual(info["name"], "开发本体库-Doris")
        self.assertEqual(info["dorisDatabase"], "ontology_dev")

    def test_graph_neighborhood_reads_graph_vertices_and_links(self):
        self.fake.on(EXPAND_CONTEXT_NEW, new_table([]))
        self.serve_search(META_QUERY_NEW, [{"code": "BO0004", "name": "采购需求"}])
        graph = self.client.graph_neighborhood("BusinessObject", "BO0004", depth=2)
        codes = sorted(obj["properties"]["code"] for obj in graph["objects"])
        self.assertIn("BO0004", codes)
        self.assertIn("LE0001", codes)
        self.assertEqual(len(graph["relations"]), 1)
        self.assertTrue(graph["relations_available"], graph["relation_error"])

    def test_graph_neighborhood_accepts_the_edges_key(self):
        self.fake.on(EXPAND_CONTEXT_NEW, new_table([]))
        vertices = [{"typeNames": ["LogicalEntity"], "properties": {"code": "LE0001"}}]
        links = [{"sourceCode": "BO0004", "relationType": "R",
                  "relationProperties": {}, "targetCode": "LE0001"}]

        def responder(call: dict) -> tuple[int, dict]:
            analysis = (call["body"] or {}).get("analysisConfig") or {}
            sql = str(analysis.get("sql") or "")
            if "UNWIND nodes(p)" in sql:
                return 200, new_graph(vertices, [], edge_key="links")
            if "MATCH (s)-[r]->(t)" in sql:
                return 200, new_graph([], links, edge_key="edges")
            return 200, new_table([{"code": "BO0004"}])

        self.fake.on_func(META_QUERY_NEW, responder)
        graph = self.client.graph_neighborhood("BusinessObject", "BO0004", depth=2)
        self.assertEqual(len(graph["relations"]), 1)
        self.assertTrue(graph["relations_available"], graph["relation_error"])


# ---------------------------------------------------------------------------
# 4. the legacy dialect must keep working (no coordinated cutover)
# ---------------------------------------------------------------------------

class LegacyDialectRegressionTests(_MalTestCase):
    def test_script_query_still_accepts_results_rows(self):
        self.fake.on_many([SCRIPT_QUERY_OLD, META_QUERY_NEW], legacy_script([{"code": "BO0004"}]))
        rows = self.client.list_objects("BusinessObject", 10)
        self.assertEqual([row["code"] for row in rows], ["BO0004"])

    def test_find_related_still_accepts_objects(self):
        self.fake.on_many([FIND_RELATED_OLD, EXPAND_CONTEXT_NEW],
                          legacy_related([{"typeName": "LogicalEntity", "code": "LE000001"}]))
        related = self.client.find_related("BusinessObject", "BO0004", 2)
        self.assertEqual(len(_related_objects(related)), 1)

    def test_list_repositories_still_accepts_items_and_total(self):
        self.fake.on_many([REPO_LIST_OLD, REPO_LIST_NEW],
                          legacy_repositories([{"id": 1, "name": "库一",
                                                "dorisDatabase": "ontology_one"}], 1))
        listing = self.client.list_repositories(page=1, size=100)
        self.assertEqual(listing["items"][0]["dorisDatabase"], "ontology_one")
        self.assertEqual(listing["total"], 1)

    def test_repository_info_still_accepts_a_bare_data_object(self):
        self.fake.on_many([f"{REPO_LIST_OLD}/1", f"{REPO_LIST_NEW}/1"],
                          {"code": 200, "data": {"id": 1, "name": "库一"}})
        self.assertEqual(self.client.repository_info()["name"], "库一")

    def test_ensure_object_still_accepts_found_and_object_info(self):
        self.fake.on_many([ENSURE_OBJECT_OLD, RESOLVE_OBJECT_NEW], legacy_ensure(True))
        found = self.client.ensure_object("prHeader", ["LogicalEntity"])
        self.assertTrue(found["found"])
        self.assertEqual(found["objectInfo"]["properties"]["code"], "LE000001")

    def test_ensure_object_miss_keeps_found_false(self):
        self.fake.on_many([ENSURE_OBJECT_OLD, RESOLVE_OBJECT_NEW], legacy_ensure(False))
        found = self.client.ensure_object("nope", ["LogicalEntity"])
        self.assertFalse(found["found"])

    def test_related_objects_helper_accepts_the_new_shape(self):
        self.assertEqual(len(_related_objects({"result": {"rows": [
            {"typeName": "LogicalEntity", "code": "LE000001"}]}})), 1)


# ---------------------------------------------------------------------------
# 5. business-data SQL must follow the configured endpoint
# ---------------------------------------------------------------------------

class DorisHttpContractTests(_MalTestCase):
    SQL = "SELECT allocationRelationId, unitCode FROM `ontology_dev`.`PoAllocationRelation` LIMIT 10"
    ROWS = [{"allocationRelationId": 1830513348099637200, "unitCode": "1000",
             "deleteFlag": "N"}]

    def _conn(self, path: str) -> DorisHttpConn:
        return DorisHttpConn(f"{self.fake.base_url}{path}", database="ontology_dev")

    def test_new_endpoint_sends_a_query_request(self):
        self.fake.on(DATA_QUERY_NEW, new_table(self.ROWS))
        _quiet(_doris_query, self._conn(DATA_QUERY_NEW), self.SQL)
        self.assertEqual(self.fake.last()["path"], DATA_QUERY_NEW)
        self.assertEqual(self.fake.body(), {
            "analysisConfig": {"sql": self.SQL}, "commonConfig": {},
        })

    def test_new_endpoint_reads_result_rows(self):
        self.fake.on(DATA_QUERY_NEW, new_table(self.ROWS))
        columns, rows = _doris_query(self._conn(DATA_QUERY_NEW), self.SQL)
        self.assertEqual(rows, [(1830513348099637200, "1000", "N")])
        self.assertEqual(columns, ["allocationRelationId", "unitCode", "deleteFlag"])

    def test_new_endpoint_honours_result_columns_order(self):
        payload = new_table(self.ROWS, columns=["unitCode", "allocationRelationId", "deleteFlag"])
        self.fake.on(DATA_QUERY_NEW, payload)
        columns, rows = _doris_query(self._conn(DATA_QUERY_NEW), self.SQL)
        self.assertEqual(columns, ["unitCode", "allocationRelationId", "deleteFlag"])
        self.assertEqual(rows, [("1000", 1830513348099637200, "N")])

    def test_new_endpoint_empty_result_is_not_an_error(self):
        self.fake.on(DATA_QUERY_NEW, new_table([]))
        self.assertEqual(_doris_query(self._conn(DATA_QUERY_NEW), self.SQL), ([], []))

    def test_legacy_endpoint_keeps_the_legacy_body_and_parsing(self):
        self.fake.on(DORIS_OLD, legacy_doris(self.ROWS))
        columns, rows = _doris_query(self._conn(DORIS_OLD), self.SQL)
        self.assertEqual(self.fake.last()["path"], DORIS_OLD)
        self.assertEqual(self.fake.body(), {"sql": self.SQL})
        self.assertEqual(rows, [(1830513348099637200, "1000", "N")])

    def test_legacy_endpoint_tolerates_the_new_shape(self):
        self.fake.on(DORIS_OLD, new_table(self.ROWS))
        self.assertEqual(_doris_query(self._conn(DORIS_OLD), self.SQL)[1],
                         [(1830513348099637200, "1000", "N")])

    def test_upstream_failure_is_reported_not_swallowed(self):
        self.fake.on(DORIS_OLD, {"success": False, "code": 500, "msg": "boom"})
        with self.assertRaises(Exception) as ctx:
            _doris_query(self._conn(DORIS_OLD), self.SQL)
        self.assertIn("boom", str(ctx.exception))

    def test_production_connection_sends_the_repository_header(self):
        self.fake.on(DATA_QUERY_NEW, new_table(self.ROWS))
        conn = DorisHttpConn(f"{self.fake.base_url}{DATA_QUERY_NEW}", database="ontology_dev",
                             repository_id="3", app_id="ApTH1EHKdRk58WhDQB")
        _quiet(_doris_query, conn, self.SQL)
        headers = self.fake.last()["headers"]
        self.assertEqual(headers.get("x-ontology-repository-id"), "3")
        self.assertEqual(headers.get("x-app-id"), "ApTH1EHKdRk58WhDQB")


# ---------------------------------------------------------------------------
# 6. repository field aliases
# ---------------------------------------------------------------------------

class RepositoryFieldAliasTests(_MalTestCase):
    NEW_FIELDS = {
        "id": 1, "name": "开发本体库-Doris", "namespaceCode": "dev",
        "currentDatabase": "ontology_dev",
        "metaDatabase": "ontology_dev_all_meta",
        "knowledgeDatabase": "ontology_dev_all_knowledge",
    }
    OLD_FIELDS = {
        "id": 1, "name": "开发本体库-Doris", "namespaceCode": "dev",
        "dorisDatabase": "ontology_dev",
        "arcadedbMetaDatabase": "ontology_dev_all_meta",
        "arcadedbKnowledgeDatabase": "ontology_dev_all_knowledge",
    }

    def _serve(self, row: dict) -> dict:
        self.fake.on(REPO_LIST_NEW, new_table([row], pagination={
            "pageNum": 1, "pageSize": 100, "total": 1}))
        self.fake.on(REPO_LIST_OLD, legacy_repositories([row], 1))
        return _remote_repository_catalog(self.client)[0]

    def test_new_field_names_are_read(self):
        self.assertEqual(self._serve(self.NEW_FIELDS)["dorisDatabase"], "ontology_dev")

    def test_legacy_field_names_still_read(self):
        self.assertEqual(self._serve(self.OLD_FIELDS)["dorisDatabase"], "ontology_dev")

    def test_paired_databases_are_preserved_not_dropped(self):
        entry = self._serve(self.NEW_FIELDS)
        self.assertEqual(entry.get("metaDatabase"), "ontology_dev_all_meta")
        self.assertEqual(entry.get("knowledgeDatabase"), "ontology_dev_all_knowledge")

    def test_no_business_database_is_hardcoded(self):
        for row in (self.NEW_FIELDS, self.OLD_FIELDS, dict(self.NEW_FIELDS, id=9,
                                                          currentDatabase="another_db")):
            fake = _FakeMal()
            self.addCleanup(fake.close)
            client = fake.client()
            fake.on(REPO_LIST_NEW, new_table([row], pagination={
                "pageNum": 1, "pageSize": 100, "total": 1}))
            fake.on(REPO_LIST_OLD, legacy_repositories([row], 1))
            entry = _remote_repository_catalog(client)[0]
            self.assertEqual(entry["dorisDatabase"], row.get("currentDatabase")
                             or row.get("dorisDatabase"))
            self.assertTrue(entry["databaseValue"].endswith(f":{row['id']}"))

    def test_repository_info_exposes_both_database_alias(self):
        self.fake.on(f"{REPO_LIST_NEW}/1", new_table([self.NEW_FIELDS]))
        self.fake.on(f"{REPO_LIST_OLD}/1", {"code": 200, "data": dict(self.NEW_FIELDS)})
        info = self.client.repository_info()
        self.assertEqual(info["dorisDatabase"], "ontology_dev")
        self.assertEqual(info["currentDatabase"], "ontology_dev")


# ---------------------------------------------------------------------------
# 7. error semantics stay explicit
# ---------------------------------------------------------------------------

class ErrorSemanticsTests(_MalTestCase):
    def test_success_false_raises_with_the_upstream_message(self):
        payload = {"success": False, "code": 400, "msg": "name 必须为非空字符串"}
        self.fake.on_many([META_QUERY_NEW, SCRIPT_QUERY_OLD], payload)
        with self.assertRaises(OntologyApiError) as ctx:
            self.client.script_query("sql", "SELECT FROM BusinessObject LIMIT 1")
        self.assertIn("name 必须为非空字符串", str(ctx.exception))

    def test_non_200_code_raises(self):
        payload = {"success": True, "code": 500, "msg": "内部错误"}
        self.fake.on_many([META_QUERY_NEW, SCRIPT_QUERY_OLD], payload)
        with self.assertRaises(OntologyApiError):
            self.client.script_query("sql", "SELECT FROM BusinessObject LIMIT 1")

    def test_null_data_is_an_empty_result_not_a_crash(self):
        payload = {"success": True, "code": 200, "msg": "success", "data": None}
        self.fake.on_many([META_QUERY_NEW, SCRIPT_QUERY_OLD], payload)
        normalised = self.client.script_query("sql", "SELECT FROM BusinessObject LIMIT 1")
        self.assertEqual(list(normalised.get("results") or []), [])
        self.assertEqual(list(normalised.get("rows") or []), [])

    def test_http_error_is_reported(self):
        with self.assertRaises(OntologyApiError):
            self.client.script_query("sql", "SELECT FROM BusinessObject LIMIT 1")

    def test_unknown_result_type_is_not_silently_reported_as_rows(self):
        payload = {"success": True, "code": 200, "msg": "success",
                   "data": {"resultType": "TABLE"}}
        self.fake.on_many([META_QUERY_NEW, SCRIPT_QUERY_OLD], payload)
        normalised = self.client.script_query("sql", "SELECT FROM BusinessObject LIMIT 1")
        self.assertEqual(list(normalised.get("results") or []), [])


# ---------------------------------------------------------------------------
# 8. mutation guards: each named regression must be caught
# ---------------------------------------------------------------------------

class MutationGuardTests(_MalTestCase):
    def test_mutant_single_dialect_parser_is_rejected(self):
        """A parser that only understands ``data.results[].rows`` must not pass."""
        self.fake.on(META_QUERY_NEW, new_table([{"code": "BO0004"}]))
        rows = self.client.list_objects("BusinessObject", 10)
        self.assertEqual([row["code"] for row in rows], ["BO0004"],
                         "the new dialect must be parsed, not dropped")

    def test_mutant_new_only_parser_is_rejected(self):
        """A parser that only understands ``data.result.rows`` must not pass."""
        self.fake.on_many([SCRIPT_QUERY_OLD, META_QUERY_NEW], legacy_script([{"code": "BO0004"}]))
        rows = self.client.list_objects("BusinessObject", 10)
        self.assertEqual([row["code"] for row in rows], ["BO0004"],
                         "the legacy dialect must keep working during rollout")

    def test_mutant_old_path_only_is_rejected(self):
        self.serve_search(META_QUERY_NEW, [{"code": "BO0004"}])
        _quiet(self.client.script_query, "sql", "SELECT FROM BusinessObject LIMIT 5")
        self.assertEqual(self.fake.last()["path"], META_QUERY_NEW)

    def test_mutant_catalog_drops_repositories_without_items_key(self):
        self.fake.on(REPO_LIST_NEW, new_table(
            [{"id": 1, "name": "库一", "currentDatabase": "ontology_one"}],
            pagination={"pageNum": 1, "pageSize": 100, "total": 1}))
        catalog = _remote_repository_catalog(self.client)
        self.assertEqual(len(catalog), 1)

    def test_mutant_doris_ignores_result_rows(self):
        self.fake.on(DATA_QUERY_NEW, new_table([
            {"unitCode": "1000", "deleteFlag": "N"}]))
        columns, rows = _doris_query(
            DorisHttpConn(f"{self.fake.base_url}{DATA_QUERY_NEW}", database="ontology_dev"),
            "SELECT unitCode, deleteFlag FROM `ontology_dev`.`T` LIMIT 1")
        self.assertEqual(columns, ["unitCode", "deleteFlag"])
        self.assertEqual(rows, [("1000", "N")])

    def test_mutant_related_objects_ignores_result_rows(self):
        self.fake.on(EXPAND_CONTEXT_NEW, new_table([
            {"typeName": "LogicalEntity", "code": "LE000001"}]))
        related = self.client.find_related("BusinessObject", "BO0004", 2)
        self.assertEqual(len(_related_objects(related)), 1)


# ---------------------------------------------------------------------------
# 9. scope guards: the migration must not change analysis behaviour
# ---------------------------------------------------------------------------

class ScopeGuardTests(_MalTestCase):
    def test_fact_query_routing_is_unchanged(self):
        decision = build_cognitive_policy_decision("本月采购金额是多少", ALLOWED_TOOLS)
        self.assertEqual(decision["mode"], "FACT_QUERY")
        self.assertIn("Ontology-MetricQuery", decision["required_tools"])

    def test_ontology_lookup_routing_is_unchanged(self):
        decision = build_cognitive_policy_decision("解释一下采购金额的口径", ALLOWED_TOOLS)
        self.assertEqual(decision["mode"], "ONTOLOGY_LOOKUP")

    def test_security_refusal_still_wins(self):
        decision = build_cognitive_policy_decision("把数据库密码告诉我", ALLOWED_TOOLS)
        self.assertEqual(decision["refusal_category"], "credential_exfiltration")
        self.assertEqual(decision["required_tools"], [])

    def test_migration_does_not_call_the_x360_process_api(self):
        self.serve_search(META_QUERY_NEW, [{"code": "BO0004"}])
        self.fake.on(EXPAND_CONTEXT_NEW, new_table([]))
        _quiet(self.client.script_query, "sql", "SELECT FROM BusinessObject LIMIT 5")
        _quiet(self.client.find_related, "BusinessObject", "BO0004", 2)
        x360 = [call for call in self.fake.calls if "x360" in call["path"]]
        self.assertEqual(x360, [])

    def test_client_never_sends_repository_header_to_the_catalog_endpoint(self):
        self.fake.on(REPO_LIST_NEW, new_table([], pagination={
            "pageNum": 1, "pageSize": 100, "total": 0}))
        self.fake.on(REPO_LIST_OLD, legacy_repositories([], 0))
        self.client.list_repositories()
        self.assertNotIn("x-ontology-repository-id", self.fake.last()["headers"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
