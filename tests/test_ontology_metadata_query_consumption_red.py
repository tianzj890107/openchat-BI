"""RED tests for 本体元数据查询消费收口（分析 Agent P2 批）.

Contract source: ``docs/specs/ontology-metadata-query-consumption.md``
（依据 ``API/本体元数据查询API-WIP.md`` §获取指标树 / §获取维度树 /
§获取指标关联的维度列表 / §获取逻辑实体关联的业务属性）。

Every assertion drives the **real production** entry points:
``bi_agent.tools.remote_ontology_tools.remote_specs`` → ``MetricCalculation`` /
``Ontology-SemanticQuery`` / ``Ontology-EntityDescribe``。假 MAL 服务只负责按文档方言
返回 payload，测试不复刻任何分类、排序或解析逻辑。

两处已核验的 P2 缺口（P1 批落地后仍然存在）：

1. **元数据检索仍然靠"全量下拉"**：`MetricCalculation` 在权威确认不可用时（以及
   `Ontology-SemanticQuery` 走模糊搜索时）依旧用
   ``SELECT FROM Indicator LIMIT 2000`` / ``SELECT FROM Dimension LIMIT 2000``，
   而文档给的是 ``POST /api/v1/analysis/meta/query`` 的**指标树 / 维度树**查询
   （`analysisConfig.vertex` + `commonConfig.filters` LIKE + `sorts` + `pagination`）。
   后果：单类型超过一次下拉上限（2000/5000 行）时**指标/维度直接查不到**，
   且每次都是最大行数。
2. **逻辑实体关联的业务属性靠图邻域遍历**：`Ontology-EntityDescribe` 用
   ``expand-ontology-context`` + ``depth=1`` 收集属性，而文档给的是
   `BusinessAttribute` 顶点 + `LogicalEntity code EQ` + `LEContainATT` 边的 TABLE
   查询（分页、只返回属性）。后果：属性受图邻域/深度上限约束，且属性与关系混在一起。

离线、确定性：只连 loopback，无凭据、无真实服务、无 LLM、不碰用户数据。
"""

from __future__ import annotations

import json
import os
import re
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Iterable
from unittest import mock

from bi_agent.ontology.remote import RemoteOntologyClient
from bi_agent.tools.remote_ontology_tools import remote_specs


# ---------------------------------------------------------------------------
# documented paths
# ---------------------------------------------------------------------------

META_NEW = "/api/v1/analysis/meta/query"
RESOLVE_NEW = "/api/v1/analysis/context/resolve-ontology-object"
EXPAND_NEW = "/api/v1/analysis/context/expand-ontology-context"

METRIC_CODE = "M0001"
METRIC_NAME = "采购金额"
DIMENSION_CODE = "D0001"
ENTITY_CODE = "LE000001"
ATTRIBUTE_CODE = "ATT0001"
GRAPH_ATTRIBUTE_CODE = "ATT9999"

MAX_PAGE_SIZE = 500  # 文档 pagination 的合理上限；pageSize 必须落在 1..500


# ---------------------------------------------------------------------------
# payload builders
# ---------------------------------------------------------------------------

def table(rows: list[dict], **extra: Any) -> dict:
    """``QueryResponse(TABLE)``: rows live under ``data.result``."""
    data: dict[str, Any] = {"result": {"rows": rows, "columns": []}}
    data.update(extra)
    return {"code": 200, "success": True, "data": data}


def _body_of(call: dict[str, Any]) -> dict[str, Any]:
    body = call.get("body")
    return body if isinstance(body, dict) else {}


def _analysis(body: dict[str, Any]) -> dict[str, Any]:
    analysis = body.get("analysisConfig")
    return analysis if isinstance(analysis, dict) else {}


def _common(body: dict[str, Any]) -> dict[str, Any]:
    common = body.get("commonConfig")
    return common if isinstance(common, dict) else {}


def _sql_of(body: dict[str, Any]) -> str:
    return str(_analysis(body).get("sql") or "")


def _vertex_type(body: dict[str, Any]) -> str:
    vertex = _analysis(body).get("vertex")
    if isinstance(vertex, list) and vertex and isinstance(vertex[0], dict):
        return str(vertex[0].get("type") or "")
    return ""


def _type_of_full_pull(body: dict[str, Any]) -> str:
    match = re.search(r"SELECT FROM (\w+)", _sql_of(body))
    return match.group(1) if match else ""


def _page_of(body: dict[str, Any]) -> tuple[int, int]:
    page = _common(body).get("pagination")
    if not isinstance(page, dict):
        return 0, 0
    try:
        return int(page.get("pageNum") or 0), int(page.get("pageSize") or 0)
    except (TypeError, ValueError):
        return 0, 0


def _walk_filters(value: Any) -> Iterable[dict[str, Any]]:
    """Yield every filter node of a (possibly nested) documented filter tree."""
    if isinstance(value, dict):
        if any(key in value for key in ("type", "property", "logic", "children")):
            yield value
        for child in value.values():
            yield from _walk_filters(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_filters(child)


def _filter_nodes(body: dict[str, Any]) -> list[dict[str, Any]]:
    return list(_walk_filters(_common(body).get("filters")))


def _has_edge_node(body: dict[str, Any], edge_type: str) -> bool:
    return any(str(node.get("type") or "") == edge_type for node in _filter_nodes(body))


def _has_equality_node(body: dict[str, Any], node_type: str, prop: str, value: str) -> bool:
    for node in _filter_nodes(body):
        if str(node.get("type") or "") != node_type or str(node.get("property") or "") != prop:
            continue
        operator = node.get("operator") if isinstance(node.get("operator"), dict) else {}
        if str(operator.get("code") or "").upper() != "EQ":
            continue
        if str(node.get("value") or "") == value:
            return True
    return False


def _like_values(body: dict[str, Any], props: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for node in _filter_nodes(body):
        if str(node.get("property") or "") not in props:
            continue
        operator = node.get("operator") if isinstance(node.get("operator"), dict) else {}
        if str(operator.get("code") or "").upper() != "LIKE":
            continue
        values.append(str(node.get("value") or ""))
    return values


def _vertex_property_names(body: dict[str, Any]) -> set[str]:
    vertex = _analysis(body).get("vertex")
    if not isinstance(vertex, list) or not vertex or not isinstance(vertex[0], dict):
        return set()
    props = vertex[0].get("properties")
    if not isinstance(props, list):
        return set()
    return {str(item.get("name")) for item in props if isinstance(item, dict) and item.get("name")}


# ---------------------------------------------------------------------------
# contract checkers (shared by the red assertions *and* the mutation guards)
# ---------------------------------------------------------------------------

def _pagination_violations(body: dict[str, Any]) -> list[str]:
    page = _common(body).get("pagination")
    if not isinstance(page, dict):
        return ["pagination_missing"]
    page_num, page_size = _page_of(body)
    violations: list[str] = []
    if page_num < 1:
        violations.append("page_num_invalid")
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        violations.append("page_size_out_of_range")
    return violations


def indicator_tree_violations(body: dict[str, Any], needle: str) -> list[str]:
    """文档 §获取指标树：Indicator 顶点 + label LIKE + sorts + pagination。"""
    violations: list[str] = []
    if _vertex_type(body) != "Indicator":
        violations.append("indicator_vertex_missing")
    names = _vertex_property_names(body)
    if not ({"code", "label"} <= names or {"code", "name"} <= names):
        violations.append("indicator_properties_missing")
    if not any(needle in value for value in _like_values(body, ("label", "name"))):
        violations.append("label_like_filter_missing")
    sorts = _common(body).get("sorts")
    if not isinstance(sorts, list) or not sorts:
        violations.append("sorts_missing")
    violations.extend(_pagination_violations(body))
    return violations


def attribute_tree_violations(body: dict[str, Any], entity_code: str) -> list[str]:
    """文档 §获取逻辑实体关联的业务属性：属性顶点 + 实体过滤 + LEContainATT 边。"""
    violations: list[str] = []
    if _vertex_type(body) != "BusinessAttribute":
        violations.append("business_attribute_vertex_missing")
    if not _has_equality_node(body, "LogicalEntity", "code", entity_code):
        violations.append("logical_entity_filter_missing")
    if not _has_edge_node(body, "LEContainATT"):
        violations.append("le_contain_att_edge_missing")
    violations.extend(_pagination_violations(body))
    return violations


def dimension_tree_violations(body: dict[str, Any], needle: str) -> list[str]:
    """文档 §获取维度树：Dimension 顶点 + label LIKE + sorts + pagination。"""
    violations: list[str] = []
    if _vertex_type(body) != "Dimension":
        violations.append("dimension_vertex_missing")
    names = _vertex_property_names(body)
    if not ({"code", "label"} <= names or {"code", "name"} <= names):
        violations.append("dimension_properties_missing")
    if not any(needle in value for value in _like_values(body, ("label", "name"))):
        violations.append("dimension_label_like_filter_missing")
    violations.extend(_pagination_violations(body))
    return violations


def drill_relationship_violations(body: dict[str, Any], metric_code: str) -> list[str]:
    """文档 §获取指标关联的维度列表：Indicator code EQ + 钻取边。"""
    violations: list[str] = []
    if not _has_equality_node(body, "Indicator", "code", metric_code):
        violations.append("indicator_code_filter_missing")
    if not _has_edge_node(body, "IndicatorIsDrilledByDimension"):
        violations.append("drill_edge_missing")
    return violations


DEGRADE_MARKERS = ("回退", "降级", "不可用")


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
        with mock.patch.dict(os.environ, {"ONTOLOGY_CACHE_TTL_SECONDS": "0"}):
            return RemoteOntologyClient(self.base_url, "1", **kwargs)

    def calls_to(self, path: str) -> list[dict[str, Any]]:
        return [call for call in self.calls if call["path"] == path]

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


class _MetaRouter:
    """文档化 meta/query 分发器：按 `analysisConfig` 推断返回哪张表。"""

    def __init__(self) -> None:
        self.type_rows: dict[str, list[dict]] = {}
        self.indicator_pages: dict[int, list[dict]] = {}
        self.dimension_pages: dict[int, list[dict]] = {}
        self.attribute_pages: dict[int, list[dict]] = {}
        self.drill_rows: list[dict] = []
        self.indicator_status = 200
        self.attribute_status = 200
        self.dimension_status = 200

    def __call__(self, call: dict[str, Any]) -> tuple[int, dict]:
        body = _body_of(call)
        if _sql_of(body):
            return 200, table(list(self.type_rows.get(_type_of_full_pull(body), [])))
        if _has_edge_node(body, "IndicatorIsDrilledByDimension"):
            return 200, table(list(self.drill_rows))
        vertex = _vertex_type(body)
        page, _size = _page_of(body)
        if vertex == "Indicator":
            return self.indicator_status, table(list(self.indicator_pages.get(page, [])))
        if vertex == "Dimension":
            return self.dimension_status, table(list(self.dimension_pages.get(page, [])))
        if vertex == "BusinessAttribute":
            return self.attribute_status, table(list(self.attribute_pages.get(page, [])))
        return 200, table([])


class _MalTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = _FakeMal()
        self.addCleanup(self.fake.close)
        self.client = self.fake.client()
        self.tools = {schema["name"]: executor for schema, executor in remote_specs(self.client)}
        self.meta = _MetaRouter()
        self.fake.on_func(META_NEW, self.meta)
        self.resolve_status = 200
        self.resolve_row: dict[str, Any] | None = None
        self.fake.on_func(RESOLVE_NEW, self._resolve)
        self.expand_rows: list[dict[str, Any]] = []
        self.fake.on(EXPAND_NEW, table([]))
        self.patch_expand()

    # -- fixtures --------------------------------------------------------
    def _resolve(self, _call: dict) -> tuple[int, dict]:
        if self.resolve_status != 200:
            return self.resolve_status, {"success": False, "code": self.resolve_status, "msg": "boom"}
        rows = [] if self.resolve_row is None else [dict(self.resolve_row)]
        return 200, table(rows)

    def patch_expand(self) -> None:
        def responder(_call: dict) -> tuple[int, dict]:
            return 200, table(list(self.expand_rows))

        self.fake.on_func(EXPAND_NEW, responder)

    def serve_entity_hit(self) -> None:
        self.resolve_row = {"typeName": "LogicalEntity", "code": ENTITY_CODE,
                            "name": ENTITY_CODE, "label": "采购申请头"}
        self.meta.type_rows["LogicalEntity"] = [
            {"code": ENTITY_CODE, "name": ENTITY_CODE, "label": "采购申请头"},
        ]

    def serve_metric_hit(self) -> None:
        self.resolve_row = {"typeName": "Indicator", "code": METRIC_CODE,
                            "name": METRIC_NAME, "label": METRIC_NAME}
        self.meta.drill_rows = [{"code": DIMENSION_CODE, "label": "采购组织"}]

    def filler_page(self, page_size: int, prefix: str) -> list[dict]:
        return [{"code": f"{prefix}{index:04d}", "label": f"填充{index}"} for index in range(page_size)]

    # -- call selectors --------------------------------------------------
    def meta_calls(self) -> list[dict[str, Any]]:
        return self.fake.calls_to(META_NEW)

    def indicator_tree_calls(self) -> list[dict[str, Any]]:
        return [call for call in self.meta_calls() if _vertex_type(_body_of(call)) == "Indicator"]

    def dimension_tree_calls(self) -> list[dict[str, Any]]:
        return [call for call in self.meta_calls() if _vertex_type(_body_of(call)) == "Dimension"]

    def attribute_tree_calls(self) -> list[dict[str, Any]]:
        return [call for call in self.meta_calls()
                if _vertex_type(_body_of(call)) == "BusinessAttribute"]

    def full_pull_calls(self, type_name: str) -> list[dict[str, Any]]:
        return [call for call in self.meta_calls()
                if _type_of_full_pull(_body_of(call)) == type_name]

    # -- assertions ------------------------------------------------------
    def assert_indicator_tree_used(self, needle: str) -> dict[str, Any]:
        calls = self.indicator_tree_calls()
        self.assertTrue(calls, msg=(
            f"尚未实现：指标检索没有使用文档的指标树查询（POST {META_NEW}，"
            "analysisConfig.vertex[Indicator] + commonConfig.filters[label LIKE] + "
            "sorts + pagination）；今天用的是 `SELECT FROM Indicator LIMIT …` 全量下拉。"
        ))
        violations = indicator_tree_violations(_body_of(calls[-1]), needle)
        self.assertEqual(violations, [], msg=f"指标树请求体不符合文档契约：{violations}")
        return calls[-1]

    def assert_attribute_tree_used(self, entity_code: str) -> dict[str, Any]:
        calls = self.attribute_tree_calls()
        self.assertTrue(calls, msg=(
            f"尚未实现：属性没有使用文档的「逻辑实体关联的业务属性」查询"
            f"（POST {META_NEW}，BusinessAttribute 顶点 + LogicalEntity.code EQ + "
            "LEContainATT 边）；今天用 expand-ontology-context 图邻域 depth=1 代替。"
        ))
        violations = attribute_tree_violations(_body_of(calls[-1]), entity_code)
        self.assertEqual(violations, [], msg=f"属性查询请求体不符合文档契约：{violations}")
        return calls[-1]


# ---------------------------------------------------------------------------
# A. 指标/维度检索必须走文档的树查询（而不是全量下拉）
# ---------------------------------------------------------------------------

class IndicatorTreeQueryTests(_MalTestCase):
    def test_r1_metric_search_uses_the_documented_indicator_tree(self):
        """R1：权威确认不可用时，指标检索必须走文档指标树查询。"""
        self.resolve_status = 500
        self.meta.indicator_pages[1] = [{"code": METRIC_CODE, "name": METRIC_NAME, "label": METRIC_NAME}]
        self.tools["MetricCalculation"]({"metric": METRIC_NAME}, ".")
        self.assert_indicator_tree_used(METRIC_NAME)

    def test_r2_indicator_tree_body_matches_the_documented_shape(self):
        """R2：指标树请求体形状（顶点、属性、LIKE 过滤、排序、分页）。"""
        self.resolve_status = 500
        self.meta.indicator_pages[1] = [{"code": METRIC_CODE, "name": METRIC_NAME, "label": METRIC_NAME}]
        self.tools["MetricCalculation"]({"metric": METRIC_NAME}, ".")
        call = self.assert_indicator_tree_used(METRIC_NAME)
        self.assertEqual(indicator_tree_violations(_body_of(call), METRIC_NAME), [])

    def test_r3_indicator_tree_pagination_stays_within_documented_bounds(self):
        """R3：分页必须存在且 pageSize 落在 1..500。"""
        self.resolve_status = 500
        self.meta.indicator_pages[1] = [{"code": METRIC_CODE, "name": METRIC_NAME, "label": METRIC_NAME}]
        self.tools["MetricCalculation"]({"metric": METRIC_NAME}, ".")
        call = self.assert_indicator_tree_used(METRIC_NAME)
        page_num, page_size = _page_of(_body_of(call))
        self.assertGreaterEqual(page_num, 1)
        self.assertGreaterEqual(page_size, 1)
        self.assertLessEqual(page_size, MAX_PAGE_SIZE)

    def test_r4_metrics_beyond_the_first_page_are_still_found(self):
        """R4：第 1 页满且未命中时必须继续翻页，不能把截断当成"没有该指标"。"""
        self.resolve_status = 500
        page_size_holder: dict[str, int] = {}

        def router(call: dict[str, Any]) -> tuple[int, dict]:
            body = _body_of(call)
            if _vertex_type(body) == "Indicator":
                page_num, page_size = _page_of(body)
                page_size_holder["pageSize"] = page_size
                if page_num == 1:
                    return 200, table(self.filler_page(page_size, "M9"))
                return 200, table([{"code": METRIC_CODE, "name": METRIC_NAME, "label": METRIC_NAME}])
            return self.meta(call)

        self.fake.on_func(META_NEW, router)
        output = self.tools["MetricCalculation"]({"metric": METRIC_NAME}, ".")
        self.assertIn(METRIC_CODE, output, msg=(
            "目标指标在第 2 页时被静默丢弃：单页截断不得等价于「没有该指标」（当前输出："
            f"{output!r}）"
        ))
        self.assertGreater(page_size_holder.get("pageSize", 0), 0)

    def test_r5_semantic_search_never_full_pulls_indicators(self):
        """R5：模糊搜索路径不得对 Indicator 做全量下拉。"""
        output = self.tools["Ontology-SemanticQuery"]({"query": "采购金额下降的原因"}, ".")
        self.assertEqual(self.full_pull_calls("Indicator"), [], msg=(
            "尚未实现：模糊搜索仍然 `SELECT FROM Indicator LIMIT 2000`；"
            "指标必须走文档指标树分页查询（2000 行截断会让超出上限的指标查不到）。"
        ))
        self.assertTrue(self.indicator_tree_calls(),
                        msg="模糊搜索必须通过文档指标树查询检索指标")
        self.assertTrue(output.strip())

    def test_r6_semantic_search_never_full_pulls_dimensions(self):
        """R6：模糊搜索路径不得对 Dimension 做全量下拉。"""
        self.tools["Ontology-SemanticQuery"]({"query": "采购金额下降的原因"}, ".")
        self.assertEqual(self.full_pull_calls("Dimension"), [], msg=(
            "尚未实现：模糊搜索仍然 `SELECT FROM Dimension LIMIT 2000`；"
            "维度必须走文档维度树分页查询。"
        ))
        self.assertTrue(self.dimension_tree_calls(),
                        msg="模糊搜索必须通过文档维度树查询检索维度")

    def test_g1_confirmed_metric_hit_does_not_full_pull_or_search(self):
        """G1（护栏）：权威命中时不应再发全量下拉或树查询。"""
        self.serve_metric_hit()
        output = self.tools["MetricCalculation"]({"metric": METRIC_NAME}, ".")
        self.assertIn(METRIC_CODE, output)
        self.assertEqual(self.full_pull_calls("Indicator"), [])

    def test_g2_metric_dimensions_keep_the_documented_drill_relationship(self):
        """G2（护栏）：指标关联维度仍须用文档的钻取关系查询。"""
        self.serve_metric_hit()
        self.tools["MetricCalculation"]({"metric": METRIC_NAME}, ".")
        drill = [call for call in self.meta_calls()
                 if _has_edge_node(_body_of(call), "IndicatorIsDrilledByDimension")]
        self.assertTrue(drill, msg="指标关联维度查询丢失（IndicatorIsDrilledByDimension）")
        self.assertEqual(drill_relationship_violations(_body_of(drill[-1]), METRIC_CODE), [])

    def test_g4_unavailable_repository_never_fabricates_metrics(self):
        """G4（护栏）：全部不可用时不得伪造指标。"""
        self.resolve_status = 500
        self.meta.indicator_status = 500
        output = self.tools["MetricCalculation"]({"metric": METRIC_NAME}, ".")
        self.assertNotIn(METRIC_CODE, output)
        self.assertTrue(output.strip())


# ---------------------------------------------------------------------------
# B. 逻辑实体关联的业务属性必须走文档查询（而不是图邻域）
# ---------------------------------------------------------------------------

class EntityAttributeQueryTests(_MalTestCase):
    def test_r7_attributes_use_the_documented_business_attribute_query(self):
        """R7：`Ontology-EntityDescribe` 必须发文档的业务属性查询。"""
        self.serve_entity_hit()
        self.meta.attribute_pages[1] = [{"code": ATTRIBUTE_CODE, "name": "单据号"}]
        self.expand_rows = [{"typeName": "BusinessAttribute", "code": GRAPH_ATTRIBUTE_CODE}]
        self.patch_expand()
        self.tools["Ontology-EntityDescribe"]({"entity": ENTITY_CODE}, ".")
        self.assert_attribute_tree_used(ENTITY_CODE)

    def test_r8_attribute_query_body_matches_the_documented_shape(self):
        """R8：属性查询请求体形状（顶点、实体过滤、LEContainATT 边、分页）。"""
        self.serve_entity_hit()
        self.meta.attribute_pages[1] = [{"code": ATTRIBUTE_CODE, "name": "单据号"}]
        self.tools["Ontology-EntityDescribe"]({"entity": ENTITY_CODE}, ".")
        call = self.assert_attribute_tree_used(ENTITY_CODE)
        self.assertEqual(attribute_tree_violations(_body_of(call), ENTITY_CODE), [])

    def test_r9_attribute_query_pagination_stays_within_documented_bounds(self):
        """R9：属性查询分页必须存在且 pageSize 落在 1..500。"""
        self.serve_entity_hit()
        self.meta.attribute_pages[1] = [{"code": ATTRIBUTE_CODE, "name": "单据号"}]
        self.tools["Ontology-EntityDescribe"]({"entity": ENTITY_CODE}, ".")
        call = self.assert_attribute_tree_used(ENTITY_CODE)
        page_num, page_size = _page_of(_body_of(call))
        self.assertGreaterEqual(page_num, 1)
        self.assertGreaterEqual(page_size, 1)
        self.assertLessEqual(page_size, MAX_PAGE_SIZE)

    def test_r10_attributes_beyond_the_first_page_are_still_returned(self):
        """R10：第 1 页满时必须继续翻页，属性不能被单页截断。"""
        self.serve_entity_hit()

        def router(call: dict[str, Any]) -> tuple[int, dict]:
            body = _body_of(call)
            if _vertex_type(body) == "BusinessAttribute":
                page_num, page_size = _page_of(body)
                if page_num == 1:
                    return 200, table(self.filler_page(page_size, "ATT8"))
                return 200, table([{"code": ATTRIBUTE_CODE, "name": "单据号"}])
            return self.meta(call)

        self.fake.on_func(META_NEW, router)
        output = self.tools["Ontology-EntityDescribe"]({"entity": ENTITY_CODE}, ".")
        self.assertIn(ATTRIBUTE_CODE, output, msg=(
            "第 2 页的业务属性被丢弃：单页截断不得静默丢属性"
            f"（当前输出：{output!r}）"
        ))

    def test_r11_attributes_come_from_the_documented_query(self):
        """R11：属性只能来自文档查询 —— 图邻域为空时属性仍必须出现。"""
        self.serve_entity_hit()
        self.meta.attribute_pages[1] = [{"code": ATTRIBUTE_CODE, "name": "单据号"}]
        self.expand_rows = []
        self.patch_expand()
        output = self.tools["Ontology-EntityDescribe"]({"entity": ENTITY_CODE}, ".")
        self.assertIn(ATTRIBUTE_CODE, output, msg=(
            "图邻域没有属性时业务属性全部丢失；属性应以文档查询为准"
            f"（当前输出：{output!r}）"
        ))

    def test_r12_attribute_query_failure_degrades_to_the_graph_with_a_note(self):
        """R12：属性查询失败 → 降级到图邻域 + 如实说明，不得报错或静默。"""
        self.serve_entity_hit()
        self.meta.attribute_status = 500
        self.expand_rows = [{"typeName": "BusinessAttribute", "code": GRAPH_ATTRIBUTE_CODE}]
        self.patch_expand()
        output = self.tools["Ontology-EntityDescribe"]({"entity": ENTITY_CODE}, ".")
        self.assert_attribute_tree_used(ENTITY_CODE)
        self.assertIn(GRAPH_ATTRIBUTE_CODE, output,
                      msg="属性查询失败必须降级到既有图邻域，而不是返回空属性")
        self.assertTrue(
            any(marker in output for marker in DEGRADE_MARKERS),
            msg=f"降级路径必须带一句说明；当前输出：{output!r}",
        )
        self.assertNotIn("remote error", output,
                         msg="降级路径不得把传输错误直接抛给模型")

    def test_g3_entity_describe_keeps_its_object_badge(self):
        """G3（护栏）：对象徽标仍来自权威行，输出形状不变。"""
        self.serve_entity_hit()
        self.meta.attribute_pages[1] = [{"code": ATTRIBUTE_CODE, "name": "单据号"}]
        output = self.tools["Ontology-EntityDescribe"]({"entity": ENTITY_CODE}, ".")
        self.assertIn(f"[{ENTITY_CODE}]", output)
        self.assertIn("LogicalEntity", output)


# ---------------------------------------------------------------------------
# C. Mutation guards：这些检查器必须能杀死对应变异
# ---------------------------------------------------------------------------

def _indicator_body(page_size: int = 50) -> dict[str, Any]:
    return {
        "analysisConfig": {
            "vertex": [{"type": "Indicator", "label": "指标", "properties": [
                {"name": "code", "label": "指标编码"}, {"name": "label", "label": "指标名称"},
            ]}],
        },
        "commonConfig": {
            "filters": {"type": "Indicator", "property": "label",
                        "operator": {"code": "LIKE", "type": "STRING"}, "value": "%采购金额%"},
            "sorts": [{"type": "Indicator", "property": "code", "order": "ASC"}],
            "pagination": {"pageNum": 1, "pageSize": page_size},
        },
    }


def _attribute_body(entity_code: str = ENTITY_CODE, page_size: int = 50) -> dict[str, Any]:
    return {
        "analysisConfig": {
            "vertex": [{"type": "BusinessAttribute", "label": "业务属性", "properties": [
                {"name": "code", "label": "属性编码"}, {"name": "name", "label": "属性名称"},
            ]}],
        },
        "commonConfig": {
            "filters": {"logic": "AND", "children": [
                {"type": "LogicalEntity", "property": "code",
                 "operator": {"code": "EQ", "type": "STRING"}, "value": entity_code},
                {"type": "LEContainATT", "sourceType": "LogicalEntity",
                 "targetType": "BusinessAttribute"},
            ]},
            "sorts": [{"type": "BusinessAttribute", "property": "code", "order": "ASC"}],
            "pagination": {"pageNum": 1, "pageSize": page_size},
        },
    }


class MutationGuardTests(unittest.TestCase):
    def test_documented_bodies_are_accepted(self):
        self.assertEqual(indicator_tree_violations(_indicator_body(), METRIC_NAME), [])
        self.assertEqual(attribute_tree_violations(_attribute_body(), ENTITY_CODE), [])
        self.assertEqual(dimension_tree_violations(
            {"analysisConfig": {"vertex": [{"type": "Dimension", "properties": [
                {"name": "code"}, {"name": "label"}]}]},
             "commonConfig": {"filters": {"property": "label",
                                          "operator": {"code": "LIKE"}, "value": "%采购组织%"},
                              "pagination": {"pageNum": 1, "pageSize": 10}}},
            "采购组织"), [])

    def test_mutation_full_pull_instead_of_tree_is_killed(self):
        body = {"analysisConfig": {"language": "sql", "sql": "SELECT FROM Indicator LIMIT 2000"},
                "commonConfig": {}}
        self.assertIn("indicator_vertex_missing", indicator_tree_violations(body, METRIC_NAME))

    def test_mutation_missing_like_filter_is_killed(self):
        body = _indicator_body()
        body["commonConfig"].pop("filters")
        self.assertIn("label_like_filter_missing", indicator_tree_violations(body, METRIC_NAME))

    def test_mutation_exact_match_instead_of_like_is_killed(self):
        body = _indicator_body()
        body["commonConfig"]["filters"]["operator"] = {"code": "EQ", "type": "STRING"}
        body["commonConfig"]["filters"]["value"] = METRIC_NAME
        self.assertIn("label_like_filter_missing", indicator_tree_violations(body, METRIC_NAME))

    def test_mutation_like_on_the_wrong_property_is_killed(self):
        body = _indicator_body()
        body["commonConfig"]["filters"]["property"] = "description"
        self.assertIn("label_like_filter_missing", indicator_tree_violations(body, METRIC_NAME))

    def test_mutation_missing_sorts_or_pagination_is_killed(self):
        body = _indicator_body()
        body["commonConfig"].pop("sorts")
        self.assertIn("sorts_missing", indicator_tree_violations(body, METRIC_NAME))
        body = _indicator_body()
        body["commonConfig"].pop("pagination")
        self.assertIn("pagination_missing", indicator_tree_violations(body, METRIC_NAME))

    def test_mutation_over_large_page_size_is_killed(self):
        self.assertIn("page_size_out_of_range",
                      indicator_tree_violations(_indicator_body(page_size=2000), METRIC_NAME))
        self.assertIn("page_size_out_of_range",
                      attribute_tree_violations(_attribute_body(page_size=0), ENTITY_CODE))

    def test_mutation_attribute_vertex_swapped_for_entity_vertex_is_killed(self):
        body = _attribute_body()
        body["analysisConfig"]["vertex"][0]["type"] = "LogicalEntity"
        self.assertIn("business_attribute_vertex_missing",
                      attribute_tree_violations(body, ENTITY_CODE))

    def test_mutation_missing_entity_filter_or_edge_is_killed(self):
        body = _attribute_body()
        body["commonConfig"]["filters"]["children"] = [
            node for node in body["commonConfig"]["filters"]["children"]
            if node["type"] != "LogicalEntity"
        ]
        self.assertIn("logical_entity_filter_missing",
                      attribute_tree_violations(body, ENTITY_CODE))
        body = _attribute_body()
        body["commonConfig"]["filters"]["children"] = [
            node for node in body["commonConfig"]["filters"]["children"]
            if node["type"] != "LEContainATT"
        ]
        self.assertIn("le_contain_att_edge_missing",
                      attribute_tree_violations(body, ENTITY_CODE))

    def test_mutation_entity_filter_with_wrong_operator_is_killed(self):
        body = _attribute_body()
        body["commonConfig"]["filters"]["children"][0]["operator"] = {"code": "LIKE"}
        self.assertIn("logical_entity_filter_missing",
                      attribute_tree_violations(body, ENTITY_CODE))

    def test_mutation_drill_relationship_loss_is_killed(self):
        body = {"commonConfig": {"filters": {"logic": "AND", "children": [
            {"type": "Indicator", "property": "code",
             "operator": {"code": "EQ", "type": "STRING"}, "value": METRIC_CODE},
        ]}}}
        self.assertIn("drill_edge_missing", drill_relationship_violations(body, METRIC_CODE))
        self.assertIn("indicator_code_filter_missing",
                      drill_relationship_violations({"commonConfig": {}}, METRIC_CODE))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
