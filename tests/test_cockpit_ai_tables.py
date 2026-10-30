"""The three AI DataTables use AP facts and validated structured card fields."""
import json
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bi_agent.cockpit.cards import CONTRACT
from bi_agent.cockpit.dashboard_source import RELEASE
from bi_agent.cockpit.ai_tables import TABLE_SPECS, preheat_table
from bi_agent.cockpit.page_cache import page_scope
from bi_agent.cockpit.publications import view_scope
from bi_agent.cockpit.router import build_cockpit_router
from bi_agent.cockpit.store import Store


class Config:
    base_url = "http://ap.example/api/gateway2"
    batch_mode = "individual"
    receipt_ttl = 3600

    def identity(self):
        return "source-ai-table"

    def headers(self):
        return {"X-App-Id": "test"}


class Gateway:
    def __init__(self, cfg, data):
        self.config = cfg
        self.data = data
        self.calls = []

    def query(self, kind, payload):
        self.calls.append((kind, payload))
        return self.data


def _save_order_card(tmp_path, cfg, page="analysis", stage="order", scope_notes=None):
    store = Store(tmp_path / "dataset" / "cockpit" / "history.sqlite3")
    context = dict(id=1, page=page, stage=stage, engine="main", sourceMode="service",
                   chartSnapshotId=RELEASE, dataSource="ap", dataIdentity=cfg.identity())
    item = store.create_analysis("table-card-" + stage, context)
    store.update_analysis(item["id"], status="completed", result={
        "summary": "订单原因已交付",
        "causes": [dict(id="c1", title="排产分配不足", description="产能池被调走",
                        status="supported", evidenceIds=["q1"])],
        "recommendations": [dict(id="r1", causeIds=["c1"], action="重排交付计划",
                                 ownerRole="计划经理", deadlineDays=3,
                                 acceptance="订单恢复排产")],
        "limitations": ["测试"],
        "cardContract": CONTRACT,
        **({"scopeNotes": scope_notes} if scope_notes else {}),
    }, evidence={
        "facts": [],
        "records": [dict(id="q1", data={"YWLN_D049": {"value": "SO-1"}})],
        "evidence": [dict(id="q1")],
    })
    store.publish(item["id"])
    item = store.get_analysis(item["id"])
    store.bind_view(view_scope(context), stage, item["scope"])
    return item


def _client(tmp_path, monkeypatch, data, *, raise_server_exceptions=True):
    import bi_agent.cockpit.router as router_module
    cfg = Config()
    gateway = Gateway(cfg, data)
    monkeypatch.setenv("COCKPIT_DATA_MODE", "ap")
    monkeypatch.delenv("COCKPIT_REFRESH_ENABLED", raising=False)
    monkeypatch.setattr(router_module, "get_gateway", lambda: gateway)
    app = FastAPI()
    app.include_router(build_cockpit_router(
        lambda: str(tmp_path),
        main_runner=lambda *_: (_ for _ in ()).throw(AssertionError("table read must not invoke the model")),
        main_context=lambda context: {},
    ))
    return TestClient(app, raise_server_exceptions=raise_server_exceptions), gateway


def _query(fields, *, filters=None, page_size=10):
    return {
        "id": 1,
        "analysisConfig": {
            "dimensions": [dict(identifierCode=code) for code, kind in fields if kind == "Dimension"],
            "indicators": [dict(identifierCode=code) for code, kind in fields if kind == "Indicator"],
        },
        "commonConfig": {
            "pagination": {"pageNum": 1, "pageSize": page_size},
            **({"filters": {"logic": "AND", "children": filters}} if filters else {}),
        },
    }


def _date_scope(value, grain="MONTH"):
    return json.dumps([
        ["setButtonGrainSelection:grain:{}", json.dumps(grain)],
        ["setFilterConditions:filter:{}", json.dumps([{"label": "时间", "value": value}], ensure_ascii=False)],
    ], ensure_ascii=False)


def _filter_children(payload):
    node = payload["commonConfig"].get("filters")
    if not node:
        return []
    return node.get("children") if isinstance(node, dict) and "children" in node else [node]


def _filter_for(payload, code):
    matches = [item for item in _filter_children(payload) if item.get("identifierCode") == code]
    assert len(matches) == 1, f"expected one {code} filter, got {matches}"
    return matches[0]


def test_affected_orders_merge_only_evidence_linked_cause_and_action(tmp_path, monkeypatch):
    cfg = Config()
    _save_order_card(tmp_path, cfg, page="analysis", stage="order")
    response, gateway = _client(tmp_path, monkeypatch, {
        "result": {"rows": [{
            "YWLN_D049": {"value": "SO-1"},
            "YWLN_D006": {"value": "客户甲"},
            "YWLN_D005": {"value": "A类"},
            "YWLN_D003": {"value": "储能"},
            "YWLN_D004": {"value": "产品一部"},
            "YWLN_D016": {"value": "订单变更"},
            "YWLN_M0032": {"value": 12.5, "render": {"unit": "GWh"}},
            "YWLN_M0033": {"value": 0.18, "render": {"unit": "亿元"}},
        }]},
        "pagination": {"total": 1},
    })
    fields = [("YWLN_D049", "Dimension"), ("YWLN_D006", "Dimension"),
              ("YWLN_D005", "Dimension"), ("YWLN_D003", "Dimension"),
              ("YWLN_D004", "Dimension"), ("YWLN_D016", "Dimension"),
              ("YWLN_M0032", "Indicator"), ("YWLN_M0033", "Indicator")]
    result = response.post("/api/cockpit/ai-tables/affected-order-list/query",
                           json=_query(fields))
    assert result.status_code == 200, result.text
    row = result.json()["rows"][0]
    assert row["YWLN_D049"] == "SO-1"
    assert row["YWLN_D016"] == "订单变更"
    assert row["YWLN_M0032"] == {"unit": "GWh", "value": 12.5}
    assert row["YWLN_M0033"] == {"unit": "亿元", "value": 0.18}
    assert row["原因"] == "证据支持：排产分配不足；产能池被调走"
    assert "重排交付计划" in row["责任动作"] and "计划经理" in row["责任动作"]
    assert gateway.calls[0][0] == "analysis"
    assert gateway.calls[0][1]["commonConfig"]["pagination"]["pageSize"] == 10
    status_filter = _filter_for(gateway.calls[0][1], "YWLN_D016")
    assert status_filter["operator"]["code"] == "IN"
    assert status_filter["value"] == ["order_change", "order_cancel"]


def test_unknown_rows_are_not_given_a_borrowed_cause(tmp_path, monkeypatch):
    cfg = Config()
    _save_order_card(tmp_path, cfg, page="analysis", stage="shipment")
    response, _ = _client(tmp_path, monkeypatch, {
        "result": {"rows": [{"YWLN_D049": {"value": "SO-2"}}]},
        "pagination": {"total": 1},
    })
    fields = [("YWLN_D049", "Dimension"), ("YWLN_D006", "Dimension"),
              ("YWLN_D005", "Dimension"), ("YWLN_D004", "Dimension"),
              ("YWLN_D050", "Dimension"),
              ("M0143", "Indicator"), ("YWLN_M_ORDER_OVERDUE_DAYS", "Indicator")]
    result = response.post("/api/cockpit/ai-tables/overdue-order-list/query",
                           json=_query(fields))
    assert result.status_code == 200, result.text
    assert result.json()["rows"][0]["主因和根因分析"] == "证据不足，未确认根因"


def test_star_product_scope_is_not_the_fixed_prototype_copy(tmp_path, monkeypatch):
    response, _ = _client(tmp_path, monkeypatch, {
        "result": {"rows": [{"YWLN_D046": {"value": "MB31"}}]},
        "pagination": {"total": 1},
    })
    fields = [("YWLN_D046", "Dimension"), ("YWLN_M_STAR_PRODUCT_SHIPMENT_2025", "Indicator"),
              ("YWLN_M0032", "Indicator"), ("YWLN_M_ORDER_RECEIPT_ENERGY_PCT", "Indicator")]
    result = response.post("/api/cockpit/ai-tables/star-product-order-list/query",
                           json=_query(fields))
    assert result.status_code == 200, result.text
    scope = result.json()["rows"][0]["口径"]
    assert "21.126 GWh" not in scope
    assert "2025 全年出货参考" not in scope
    assert scope.startswith("当前筛选范围的业务口径未在已发布分析中提供")


def test_star_product_scope_uses_the_published_versioned_definition(tmp_path, monkeypatch):
    cfg = Config()
    _save_order_card(tmp_path, cfg, page="operations", stage="order",
                     scope_notes={"MB31": "口径版本 v3：包含系统，按当前筛选范围统计"})
    response, _ = _client(tmp_path, monkeypatch, {
        "result": {"rows": [{"YWLN_D046": {"value": "MB31"}}]},
        "pagination": {"total": 1},
    })
    fields = [("YWLN_D046", "Dimension"), ("YWLN_M_STAR_PRODUCT_SHIPMENT_2025", "Indicator"),
              ("YWLN_M0032", "Indicator"), ("YWLN_M_ORDER_RECEIPT_ENERGY_PCT", "Indicator")]
    result = response.post("/api/cockpit/ai-tables/star-product-order-list/query",
                           json=_query(fields))
    assert result.status_code == 200, result.text
    assert result.json()["rows"][0]["口径"] == "口径版本 v3：包含系统，按当前筛选范围统计"


def test_table_snapshot_is_saved_and_reused_without_another_ap_query(tmp_path, monkeypatch):
    response, gateway = _client(tmp_path, monkeypatch, {
        "result": {"rows": [{"YWLN_D049": {"value": "SO-1"}}]},
        "pagination": {"total": 1},
    })
    fields = [("YWLN_D049", "Dimension"), ("YWLN_D006", "Dimension"),
              ("YWLN_D005", "Dimension"), ("YWLN_D004", "Dimension"),
              ("YWLN_D050", "Dimension"), ("M0143", "Indicator"),
              ("YWLN_M_ORDER_OVERDUE_DAYS", "Indicator")]
    live = response.post("/api/cockpit/ai-tables/overdue-order-list/query",
                         json=_query(fields))
    assert live.status_code == 200, live.text
    assert live.json()["meta"]["cacheStatus"] == "refreshed"
    assert live.json()["meta"]["mappingVersion"] == "ai-tables-v3"
    assert len(gateway.calls) == 1

    cached = _query(fields)
    cached["cacheOnly"] = True
    hit = response.post("/api/cockpit/ai-tables/overdue-order-list/query", json=cached)
    assert hit.status_code == 200, hit.text
    assert hit.json()["meta"]["cacheStatus"] == "hit"
    assert hit.json()["rows"][0]["YWLN_D049"] == "SO-1"
    assert len(gateway.calls) == 1

    custom = _query(fields)
    custom.update(cacheOnly=True, uiScope=_date_scope('2026-01'))
    miss = response.post("/api/cockpit/ai-tables/overdue-order-list/query", json=custom)
    assert miss.status_code == 200, miss.text
    assert miss.json()["meta"]["cacheStatus"] == "missing"
    assert miss.json()["meta"]["scopeMatch"] is False
    assert len(gateway.calls) == 1


def test_all_three_tables_are_preheated_for_both_roles_and_hit_cache_only(tmp_path, monkeypatch):
    response, gateway = _client(tmp_path, monkeypatch, {
        "result": {"rows": [{"YWLN_D049": {"value": "SO-1"}}]},
        "pagination": {"total": 1},
    })
    calls = []
    def receipt(identity, kind, payload):
        calls.append((identity, kind, payload))
        return dict(response={"result": {"rows": [{"YWLN_D049": {"value": "SO-1"}}]},
                              "pagination": {"total": 1}})
    store = Store(tmp_path / "dataset" / "cockpit" / "history.sqlite3")
    for identity in (1, 2):
        for table_key in TABLE_SPECS:
            assert preheat_table(store, identity, table_key, receipt) == "published"
    assert len(calls) == 6
    for identity in (1, 2):
        for table_key, spec in TABLE_SPECS.items():
            fields = [(item["identifierCode"], item["fieldType"]) for item in spec["fields"]]
            query = _query(fields)
            query.update(id=identity, cacheOnly=True, period='2025-10')
            hit = response.post(f"/api/cockpit/ai-tables/{table_key}/query", json=query)
            assert hit.status_code == 200, hit.text
            assert hit.json()["meta"]["cacheStatus"] == "hit"


def test_failed_table_refresh_never_overwrites_the_saved_snapshot(tmp_path, monkeypatch):
    response, gateway = _client(tmp_path, monkeypatch, {
        "result": {"rows": [{"YWLN_D049": {"value": "SO-1"}}]},
        "pagination": {"total": 1},
    }, raise_server_exceptions=False)
    fields = [("YWLN_D049", "Dimension"), ("YWLN_D006", "Dimension"),
              ("YWLN_D005", "Dimension"), ("YWLN_D004", "Dimension"),
              ("YWLN_D050", "Dimension"), ("M0143", "Indicator"),
              ("YWLN_M_ORDER_OVERDUE_DAYS", "Indicator")]
    first = response.post("/api/cockpit/ai-tables/overdue-order-list/query", json=_query(fields))
    assert first.status_code == 200, first.text

    def fail(kind, payload):
        gateway.calls.append((kind, payload))
        raise RuntimeError("AP unavailable")

    monkeypatch.setattr(gateway, "query", fail)
    failed_query = _query(fields, page_size=20)
    failed = response.post("/api/cockpit/ai-tables/overdue-order-list/query", json=failed_query)
    assert failed.status_code == 500

    cached = _query(fields)
    cached["cacheOnly"] = True
    hit = response.post("/api/cockpit/ai-tables/overdue-order-list/query", json=cached)
    assert hit.status_code == 200, hit.text
    assert hit.json()["meta"]["cacheStatus"] == "hit"
    assert hit.json()["rows"][0]["YWLN_D049"] == "SO-1"


def test_table_query_inherits_the_page_month_or_year_date_scope(tmp_path, monkeypatch):
    response, gateway = _client(tmp_path, monkeypatch, {
        "result": {"rows": [{"YWLN_D049": {"value": "SO-1"}}]},
        "pagination": {"total": 1},
    })
    fields = [("YWLN_D049", "Dimension"), ("YWLN_D006", "Dimension"),
              ("YWLN_D005", "Dimension"), ("YWLN_D004", "Dimension"),
              ("YWLN_D050", "Dimension"), ("M0143", "Indicator"),
              ("YWLN_M_ORDER_OVERDUE_DAYS", "Indicator")]
    month = _query(fields)
    month["uiScope"] = _date_scope("2026-01")
    result = response.post("/api/cockpit/ai-tables/overdue-order-list/query", json=month)
    assert result.status_code == 200, result.text
    payload = gateway.calls[-1][1]
    page_filter = _filter_for(payload, "YWLN_D044")
    assert page_filter["value"] == ["2026-01-01", "2026-01-31"]
    assert page_filter["operator"]["code"] == "BETWEEN"
    overdue_filter = _filter_for(payload, "YWLN_M_ORDER_OVERDUE_DAYS")
    assert overdue_filter["value"] == 0
    assert overdue_filter["operator"] == {"code": "GT", "type": "NUMBER"}

    year = _query(fields)
    year["uiScope"] = _date_scope("2026", grain="YEAR")
    result = response.post("/api/cockpit/ai-tables/overdue-order-list/query", json=year)
    assert result.status_code == 200, result.text
    assert _filter_for(gateway.calls[-1][1], "YWLN_D044")["value"] == [
        "2026-01-01", "2026-12-31"]


def test_table_query_uses_the_visible_page_period_when_scope_is_default(tmp_path, monkeypatch):
    response, gateway = _client(tmp_path, monkeypatch, {
        "result": {"rows": [{"YWLN_D049": {"value": "SO-1"}}]},
        "pagination": {"total": 1},
    })
    fields = [("YWLN_D049", "Dimension"), ("YWLN_D006", "Dimension"),
              ("YWLN_D005", "Dimension"), ("YWLN_D004", "Dimension"),
              ("YWLN_D050", "Dimension"), ("M0143", "Indicator"),
              ("YWLN_M_ORDER_OVERDUE_DAYS", "Indicator")]
    query = _query(fields)
    query["period"] = "2025-10"
    result = response.post("/api/cockpit/ai-tables/overdue-order-list/query", json=query)
    assert result.status_code == 200, result.text
    payload = gateway.calls[-1][1]
    page_filter = _filter_for(payload, "YWLN_D044")
    assert page_filter["value"] == ["2025-10-01", "2025-10-31"]
    assert _filter_for(payload, "YWLN_M_ORDER_OVERDUE_DAYS")["operator"]["code"] == "GT"


def test_table_query_does_not_append_a_duplicate_visible_date_filter(tmp_path, monkeypatch):
    response, gateway = _client(tmp_path, monkeypatch, {
        "result": {"rows": [{"YWLN_D049": {"value": "SO-1"}}]},
        "pagination": {"total": 1},
    })
    fields = [("YWLN_D049", "Dimension"), ("YWLN_D006", "Dimension"),
              ("YWLN_D005", "Dimension"), ("YWLN_D004", "Dimension"),
              ("YWLN_D050", "Dimension"), ("M0143", "Indicator"),
              ("YWLN_M_ORDER_OVERDUE_DAYS", "Indicator")]
    date_filter = {
        "identifierCode": "YWLN_D044",
        "operator": {"code": "BETWEEN", "type": "DATE"},
        "value": ["2025-10-01", "2025-10-31"],
        "valueType": "ABSOLUTE",
    }
    overdue_filter = {
        "alias": "超期天数",
        "identifierCode": "YWLN_M_ORDER_OVERDUE_DAYS",
        "operator": {"code": "GT", "type": "NUMBER"},
        "type": "Indicator",
        "value": 0,
        "valueType": "ABSOLUTE",
    }
    query = _query(fields, filters=[overdue_filter, date_filter])
    query["period"] = "2025-10"
    result = response.post("/api/cockpit/ai-tables/overdue-order-list/query", json=query)
    assert result.status_code == 200, result.text
    payload = gateway.calls[-1][1]
    children = _filter_children(payload)
    assert [item for item in children if item["identifierCode"] == "YWLN_D044"] == [date_filter]
    assert len([item for item in children if item["identifierCode"] == "YWLN_D044"]) == 1
    assert [item for item in children if item["identifierCode"] == "YWLN_M_ORDER_OVERDUE_DAYS"] == [overdue_filter]


def test_custom_table_scope_uses_its_exact_published_card(tmp_path, monkeypatch):
    cfg = Config()
    item = _save_order_card(tmp_path, cfg, page="analysis", stage="shipment")
    scope = _date_scope("2026-01")
    store = Store(tmp_path / "dataset" / "cockpit" / "history.sqlite3")
    store.publish_page(page_scope(cfg, 1, "analysis", scope), dict(
        id=1, page="analysis", uiScope=scope, dataAsOf=time.time(), items={"shipment": item}))
    response, _ = _client(tmp_path, monkeypatch, {
        "result": {"rows": [{"YWLN_D049": {"value": "SO-1"}}]},
        "pagination": {"total": 1},
    })
    fields = [("YWLN_D049", "Dimension"), ("YWLN_D006", "Dimension"),
              ("YWLN_D005", "Dimension"), ("YWLN_D004", "Dimension"),
              ("YWLN_D050", "Dimension"), ("M0143", "Indicator"),
              ("YWLN_M_ORDER_OVERDUE_DAYS", "Indicator")]
    query = _query(fields)
    query["uiScope"] = scope
    result = response.post("/api/cockpit/ai-tables/overdue-order-list/query", json=query)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["meta"]["analysisScopeMatch"] is True
    assert body["meta"]["analysisScope"] == scope
    assert body["rows"][0]["主因和根因分析"].startswith("证据支持：排产分配不足")


def test_unmapped_page_filter_is_rejected_before_ap_is_called(tmp_path, monkeypatch):
    response, gateway = _client(tmp_path, monkeypatch, {"result": {"rows": []}})
    fields = [("YWLN_D049", "Dimension"), ("YWLN_D006", "Dimension"),
              ("YWLN_D005", "Dimension"), ("YWLN_D004", "Dimension"),
              ("YWLN_D050", "Dimension"), ("M0143", "Indicator"),
              ("YWLN_M_ORDER_OVERDUE_DAYS", "Indicator")]
    query = _query(fields)
    query["uiScope"] = json.dumps([
        ["setFilterConditions:filter:{}", json.dumps([{"label": "客户等级", "value": "A"}], ensure_ascii=False)],
    ], ensure_ascii=False)
    result = response.post("/api/cockpit/ai-tables/overdue-order-list/query", json=query)
    assert result.status_code == 422
    assert "尚未映射" in result.text
    assert gateway.calls == []

    mixed = _query(fields)
    mixed["uiScope"] = json.dumps([
        ["setFilterConditions:filter:{}", json.dumps([
            {"label": "时间", "value": "2026-01"},
            {"label": "客户等级", "value": "A"},
        ], ensure_ascii=False)],
    ], ensure_ascii=False)
    rejected = response.post("/api/cockpit/ai-tables/overdue-order-list/query", json=mixed)
    assert rejected.status_code == 422
    assert "客户等级" in rejected.text
    assert gateway.calls == []


def test_table_query_rejects_unreviewed_fields_and_or_filters(tmp_path, monkeypatch):
    response, _ = _client(tmp_path, monkeypatch, {"result": {"rows": []}})
    bad_fields = _query([("YWLN_D049", "Dimension"), ("YWLN_M0001", "Indicator")])
    assert response.post("/api/cockpit/ai-tables/affected-order-list/query",
                         json=bad_fields).status_code == 422
    good_fields = _query([
        ("YWLN_D049", "Dimension"), ("YWLN_D006", "Dimension"),
        ("YWLN_D005", "Dimension"), ("YWLN_D003", "Dimension"),
        ("YWLN_D004", "Dimension"), ("YWLN_D016", "Dimension"),
        ("YWLN_M0032", "Indicator"), ("YWLN_M0033", "Indicator"),
    ], filters=[{"identifierCode": "YWLN_D049", "operator": {"code": "EQ"}, "value": "SO-1"}])
    good_fields["commonConfig"]["filters"]["logic"] = "OR"
    assert response.post("/api/cockpit/ai-tables/affected-order-list/query",
                         json=good_fields).status_code == 422
