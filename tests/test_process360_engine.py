from __future__ import annotations

import json
from pathlib import Path
from datetime import date
from types import SimpleNamespace

import pytest

from bi_agent.process360.catalog import Process360Catalog
from bi_agent.process360.db import DatabaseQueryError, ensure_read_only
from bi_agent.process360.models import Scope
from bi_agent.process360.router import route
from bi_agent.process360.service import Process360Service
from bi_agent.process360.tools import EXECUTORS

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "dataset" / "process360" / "ywln-v3.1" / "catalog.json"


def _catalog() -> Process360Catalog:
    return Process360Catalog.from_file(CATALOG_PATH)


class FakeDB:
    def __init__(self) -> None:
        self.config = SimpleNamespace(schema="ywln_crm")
        self.available = True
        self.calls: list[tuple[str, dict]] = []

    def run(self, sql: str, params: dict | None = None, **_: object) -> SimpleNamespace:
        params = dict(params or {})
        self.calls.append((sql, params))
        rows: list[dict]
        if "AS overdue_rows" in sql:
            rows = [{
                "overdue_rows": 2, "amount_100m": 12.5, "power_gwh": 3.25,
                "zero_power_rows": 0, "missing_price_rows": 0,
                "first_plan_date": "2026-08-01", "last_plan_date": "2026-10-01",
            }]
        elif "AS missing_delivery_date" in sql:
            rows = [{"missing_delivery_date": 0, "zero_power_rows": 0, "missing_price_rows": 0}]
        elif "AS approved_count" in sql:
            rows = [{"approved_count": 7, "in_progress_count": 2, "rejected_count": 1,
                     "approved_without_time": 0, "submitted_without_time": 0}]
        elif "AS pending_customers" in sql:
            rows = [{"strategic_customers": 2, "pending_customers": 1}]
        elif "AS awarded_unsigned_rows" in sql:
            rows = [{"awarded_unsigned_rows": 1, "amount_100m": 2.25, "power_gwh": 0.4,
                     "avg_wait_days": 90, "max_wait_days": 90,
                     "missing_amount": 0, "missing_energy": 0}]
        elif "AS actual_rows" in sql:
            rows = [{"actual_rows": 10, "actual_qty": 100, "actual_power_gwh": 5.0,
                     "actual_amount_100m": 4.0, "ambiguous_rows": 0, "unmatched_rows": 2,
                     "unmatched_qty": 20, "outside_power_gwh": 0.25, "unknown_rows": 0, "invalid_qty_rows": 0,
                     "outside_amount_100m": 0.2, "missing_amount_rows": 0, "zero_power_rows": 0}]
        elif '"AT9200384" AS customer_id' in sql:
            rows = [
                {"customer_id": "c1", "customer_name": "战略一", "account_level": 1,
                 "created_at": "2025-01-01", "has_valid_opportunity": True, "valid_opportunity_count": 2},
                {"customer_id": "c2", "customer_name": "战略二", "account_level": 1,
                 "created_at": "2025-02-01", "has_valid_opportunity": False, "valid_opportunity_count": 0},
            ]
        elif '"AT9200042" AS bid_id' in sql:
            rows = [{"bid_id": "b1", "project_name": "项目一", "opportunity_id": "o1",
                     "energy_mwh": 400, "amount_rmb": 225000000, "awarded_at": "2026-07-01",
                     "region": "华东", "cell_model": "LF280K", "sales_person": "s1", "wait_days": 90}]
        elif '"order_id" AS order_id' in sql or "match_status" in sql:
            rows = [{"order_id": "o1", "ship_date": "2026-10-10", "line_no": 10,
                     "product_id": "p1", "qty": 20, "amount_tax_free": 2000000,
                     "kwh_per_unit": 0.9, "plan_rows": None, "has_daily_plan": None,
                     "planned_qty": None, "align_status": None, "match_status": "unmatched"}]
        elif '"customer_name"' in sql and "OVER" in sql:
            rows = [{"order_id": "o1", "line_no": 10, "product_id": "p1", "plan_id": "d1",
                     "plan_date": "2026-08-01", "remaining_qty": 100, "delivery_date": "2026-09-01",
                     "owner_id": "u1", "customer_id": "c1", "customer_name": "客户一",
                     "unit_price": 300, "price_unit": 1, "kwh_per_unit": 0.9,
                     "amount_100m": 12.5, "power_gwh": 3.25, "align_status": 4,
                     "modified_on": "2026-09-01"}]
        else:
            rows = []
        return SimpleNamespace(columns=list(rows[0]) if rows else [], rows=rows,
                               duration_ms=1, truncated=False)


def _service(db: FakeDB | None = None) -> Process360Service:
    return Process360Service(catalog=_catalog(), db=db or FakeDB())


def test_router_selects_sop_and_detects_ambiguity() -> None:
    catalog = _catalog()
    assert route("超期未发为什么增加？", catalog).sop_id == "P09"
    assert route("超期未发为什么增加？", catalog).scenario == "SC01"
    assert route("经营情况怎么样，主要风险是什么", catalog).sop_id == "P18"
    ambiguous = route("发货和报价哪个风险大", catalog)
    assert ambiguous.scenario is None
    assert ambiguous.clarification


def test_scope_validates_and_blocks_historical_overdue() -> None:
    scope = Scope.from_payload({"periodStart": "2026-10-01", "periodEnd": "2026-10-27"})
    assert scope.period_start.isoformat() == "2026-10-01"
    with pytest.raises(ValueError):
        Scope.from_payload({"periodStart": "2026-10-27", "periodEnd": "2026-10-01"})
    result = _service().query("SC01", scope={"periodEnd": "2026-09-30"})
    assert result["status"] == "blocked"
    assert "G16" in {gap["code"] for gap in result["gaps"]}


def test_sc01_analysis_and_draft_are_closed_loop_but_not_executed(monkeypatch) -> None:
    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 27)
    monkeypatch.setattr("bi_agent.process360.models.date", FixedDate)
    monkeypatch.setattr("bi_agent.process360.queries.date", FixedDate)
    service = _service()
    analysis = service.analyze(question="超期未发为什么增加？", scope={"periodEnd": "2026-10-27"})
    assert analysis["status"] == "partial"
    assert analysis["observation"]["severity"] == "CRITICAL"
    assert analysis["candidateCauses"]
    assert all(row["status"] == "candidate_unverified" for row in analysis["candidateCauses"])
    draft = service.draft(question="超期未发为什么增加？", scope={"periodEnd": "2026-10-27"},
                          owner_ref="u1", owner_name="owner-a")
    assert draft["status"] == "ok"
    assert {task["taskTemplate"] for task in draft["tasks"]} == {"TK01", "TK02", "TK03", "TK04"}
    for task in draft["tasks"]:
        assert task["dispatch"]["source"] == "boulderai-anaylize-todo"
        assert not any(ch.isdigit() and len(ch) == 11 for ch in task["content"].split())
    assert len(draft["canvasActions"]) == len(draft["tasks"])
    assert draft["canvasActions"][0]["source"] == "boulderai-anaylize-todo"
    assert draft["canvasActions"][0]["scenario"] == "SC01"
    assert draft["canvasActions"][0]["task_template"].startswith("TK")


def test_sc02_and_sc03_keep_missing_mappings_blocked() -> None:
    service = _service()
    sc02 = service.query("SC02")
    metrics = {item["code"]: item for item in sc02["metrics"]}
    assert metrics["M36001"]["value"] == 7
    assert metrics["M0137"]["status"] == "blocked"
    assert metrics["M36002"]["status"] == "blocked"
    sc03 = service.query("SC03")
    metrics = {item["code"]: item for item in sc03["metrics"]}
    assert metrics["M0257"]["value"] == 1
    assert metrics["M36003"]["status"] == "blocked"


def test_sc04_and_sc05_do_not_zero_fill_or_assert_violation() -> None:
    service = _service()
    sc04 = service.query("SC04")
    assert {item["code"] for item in sc04["metrics"]} == {"M0179", "M0142", "M36004"}
    assert sc04["awardedUnsigned"] == 1
    sc05 = service.query("SC05")
    assert sc05["status"] == "partial"
    assert all(item["status"] == "partial" for item in sc05["metrics"])
    assert "计划外违规" in " ".join(sc05["limitations"])


def test_sc05_ambiguous_plan_blocks_metrics() -> None:
    db = FakeDB()
    original = db.run

    def run(sql: str, params: dict | None = None, **kwargs: object) -> SimpleNamespace:
        result = original(sql, params, **kwargs)
        if "AS actual_rows" in sql:
            result.rows[0]["ambiguous_rows"] = 3
        return result

    db.run = run  # type: ignore[method-assign]
    sc05 = _service(db).query("SC05")
    assert sc05["status"] == "blocked"
    assert all(item["status"] == "blocked" for item in sc05["metrics"])


def test_verify_requires_baseline_and_approved_target() -> None:
    result = _service().verify(scenario="SC01", scope={"periodEnd": "2026-10-27"})
    assert result["status"] == "blocked"
    assert result["closure"]["canClose"] is False
    assert "VERIFICATION_BASELINE_MISSING" in {gap["code"] for gap in result["gaps"]}
    assert "VERIFICATION_TARGET_MISSING" in {gap["code"] for gap in result["gaps"]}


def test_task_order_execution_is_fuxi_only_and_supplied_by_host() -> None:
    class Client:
        def __init__(self) -> None:
            self.calls = []

        def create_todo(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "sourceTodoId": kwargs["source_todo_id"], "applied": 1}

    service = _service()
    draft = service.draft(scenario="SC01", owner_ref="u1", owner_name="owner-a")
    client = Client()
    receipt = service.execute(task=draft["tasks"][0], recipients=["18837823993"],
                              action_id="a1", canvas_id="canvas-1", client=client)
    assert receipt["status"] == "ok"
    assert client.calls[0]["recipients_raw"] == ["18837823993"]
    assert client.calls[0]["content"].startswith("**场景**")
    with pytest.raises(ValueError):
        service.execute(task={**draft["tasks"][0], "content": "拨打 18837823993"},
                        recipients=["18837823993"], action_id="a2", client=client)


def test_mcp_process360_tools_are_routable() -> None:
    from bi_agent.web.mcp_endpoint import DEFAULT_EXPOSED_TOOLS
    for name in EXECUTORS:
        assert name in DEFAULT_EXPOSED_TOOLS
    payload = json.loads(EXECUTORS["Process360Route"]({"question": "超期未发为什么增加"}, str(ROOT)))
    assert payload["route"]["scenario"] == "SC01"


def test_database_adapter_rejects_writes() -> None:
    ensure_read_only("select 1")
    with pytest.raises(DatabaseQueryError):
        ensure_read_only("update ywln_crm.\"LE000011\" set x = 1")
    with pytest.raises(DatabaseQueryError):
        ensure_read_only("select 1; delete from t")
