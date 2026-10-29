"""The three AI DataTables use AP facts and validated structured card fields."""
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bi_agent.cockpit.cards import CONTRACT
from bi_agent.cockpit.dashboard_source import RELEASE
from bi_agent.cockpit.publications import view_scope
from bi_agent.cockpit.router import build_cockpit_router
from bi_agent.cockpit.store import Store


class Config:
    base_url = "http://ap.example/api/gateway2"
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


def _save_order_card(tmp_path, cfg, page="analysis", stage="order"):
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
    }, evidence={
        "facts": [],
        "records": [dict(id="q1", data={"YWLN_D049": {"value": "SO-1"}})],
        "evidence": [dict(id="q1")],
    })
    store.publish(item["id"])
    store.bind_view(view_scope(context), stage, item["scope"])


def _client(tmp_path, monkeypatch, data):
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
    return TestClient(app), gateway


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
            "YWLN_M_ORDER_CANCEL_CHANGE": {"value": 12.5, "render": {"unit": "GWh"}},
        }]},
        "pagination": {"total": 1},
    })
    fields = [("YWLN_D049", "Dimension"), ("YWLN_D006", "Dimension"),
              ("YWLN_D005", "Dimension"), ("YWLN_D003", "Dimension"),
              ("YWLN_D004", "Dimension"), ("YWLN_M_ORDER_CANCEL_CHANGE", "Indicator")]
    result = response.post("/api/cockpit/ai-tables/affected-order-list/query",
                           json=_query(fields))
    assert result.status_code == 200, result.text
    row = result.json()["rows"][0]
    assert row["YWLN_D049"] == "SO-1"
    assert row["原因"] == "证据支持：排产分配不足；产能池被调走"
    assert "重排交付计划" in row["责任动作"] and "计划经理" in row["责任动作"]
    assert gateway.calls[0][0] == "analysis"
    assert gateway.calls[0][1]["commonConfig"]["pagination"]["pageSize"] == 10


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


def test_star_product_scope_is_derived_from_registered_series(tmp_path, monkeypatch):
    response, _ = _client(tmp_path, monkeypatch, {
        "result": {"rows": [{"YWLN_D046": {"value": "MB31"}}]},
        "pagination": {"total": 1},
    })
    fields = [("YWLN_D046", "Dimension"), ("YWLN_M_STAR_PRODUCT_SHIPMENT_2025", "Indicator"),
              ("YWLN_M0032", "Indicator"), ("YWLN_M_STAR_PRODUCT_ORDER_SHARE", "Indicator")]
    result = response.post("/api/cockpit/ai-tables/star-product-order-list/query",
                           json=_query(fields))
    assert result.status_code == 200, result.text
    assert result.json()["rows"][0]["口径"].startswith("含系统")


def test_table_query_rejects_unreviewed_fields_and_or_filters(tmp_path, monkeypatch):
    response, _ = _client(tmp_path, monkeypatch, {"result": {"rows": []}})
    bad_fields = _query([("YWLN_D049", "Dimension"), ("YWLN_M0001", "Indicator")])
    assert response.post("/api/cockpit/ai-tables/affected-order-list/query",
                         json=bad_fields).status_code == 422
    good_fields = _query([
        ("YWLN_D049", "Dimension"), ("YWLN_D006", "Dimension"),
        ("YWLN_D005", "Dimension"), ("YWLN_D003", "Dimension"),
        ("YWLN_D004", "Dimension"), ("YWLN_M_ORDER_CANCEL_CHANGE", "Indicator"),
    ], filters=[{"identifierCode": "YWLN_D049", "operator": {"code": "EQ"}, "value": "SO-1"}])
    good_fields["commonConfig"]["filters"]["logic"] = "OR"
    assert response.post("/api/cockpit/ai-tables/affected-order-list/query",
                         json=good_fields).status_code == 422
