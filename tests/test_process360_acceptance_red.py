"""Acceptance regressions found by auditing the V3.1/V1.2 Process360 feature.

Only fake facts/clients are used. No real database, task dispatch or user data.
"""

from copy import deepcopy
from datetime import date
from types import SimpleNamespace
import json

import pytest

from bi_agent.process360.catalog import Process360Catalog
from bi_agent.process360.models import Scope
from bi_agent.process360.router import route
from bi_agent.process360.service import Process360Service
from bi_agent.process360.analysis import analyze
from tests.test_process360_engine import FakeDB


class FrozenDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 10, 27)


@pytest.fixture(autouse=True)
def fixed_day(monkeypatch):
    monkeypatch.setattr("bi_agent.process360.models.date", FrozenDate)
    monkeypatch.setattr("bi_agent.process360.queries.date", FrozenDate)


def catalog():
    return Process360Catalog.from_project(".")


def service(db=None):
    return Process360Service(catalog=catalog(), db=db or FakeDB())


@pytest.mark.parametrize(
    "scope",
    [
        {"includeCurrentSnapshot": "false"},
        {"limit": 0},
        {"limit": 501},
        {"limit": True},
        {"limit": 1.5},
        {"customerIds": "c1"},
        {"ownerIds": [None]},
        {"asOf": "2026-10-27garbage"},
        {"asOf": "2026-10-20", "periodEnd": "2026-10-27"},
        {"sql": "SELECT 1"},
    ],
)
def test_scope_rejects_invalid_or_undeclared_inputs(scope):
    with pytest.raises(ValueError):
        Scope.from_payload(scope, today=FrozenDate.today())


@pytest.mark.parametrize(
    "scenario,scope",
    [
        ("SC02", {"productIds": ["p1"]}),
        ("SC03", {"ownerIds": ["u1"]}),
        ("SC04", {"productIds": ["p1"]}),
        ("SC05", {"ownerIds": ["u1"]}),
    ],
)
def test_unsupported_filter_never_silently_widens_the_query(scenario, scope):
    db = FakeDB()
    result = service(db).query(scenario, scope=scope)
    assert result["status"] in {"blocked", "needs_clarification"}
    assert not db.calls


@pytest.mark.parametrize("scenario", ["SC03", "SC04"])
def test_current_stock_queries_do_not_claim_historical_observation(scenario):
    db = FakeDB()
    result = service(db).query(scenario, scope={"periodEnd": "2026-09-30"})
    assert result["status"] == "blocked" and not db.calls


def test_explicit_current_snapshot_uses_current_cutoff_and_discloses_requested_history():
    db = FakeDB()
    result = service(db).query(
        "SC01", scope={"periodEnd": "2026-09-30", "includeCurrentSnapshot": True}
    )
    assert result["scope"]["asOf"] == "2026-10-27"
    assert result["requestedScope"]["periodEnd"] == "2026-09-30"
    assert all(p.get("cutoff") != date(2026, 9, 30) for _, p in db.calls)


@pytest.mark.parametrize(
    "question,sop",
    [
        ("订单在哪个节点卡住？", "P07"),
        ("立项不少为什么投标少？", "P07"),
        ("把这些订单安排发货", "P13"),
        ("提交调价申请", "P13"),
        ("任务到哪一步？", "P14"),
        ("催一下负责人", "P14"),
        ("经营情况怎么样，主要风险是什么，下一步怎么办？", "P18"),
    ],
)
def test_all_sop_families_have_real_routes(question, sop):
    assert route(question, catalog()).sop_id == sop


def test_catalog_public_views_cannot_mutate_cached_semantics():
    c = catalog()
    before = deepcopy(c.metric("M0143"))
    returned = c.metric("M0143")
    returned["name"] = "CORRUPTED"
    try:
        assert c.metric("M0143") == before
    finally:
        returned.clear()
        returned.update(before)


def test_catalog_scenario_search_filters_before_limit():
    c = catalog()
    hits = c.search("金额", limit=100)
    own = {r["code"] for r in c.entities_for_scenario("SC04")["metrics"]}
    assert any(h["code"] in own for h in hits)
    result = service().search("金额", scenario="SC04", limit=1)
    assert result["records"] and len(result["records"]) == 1


def test_sc03_counts_the_whole_cohort_not_the_limited_detail():
    class CohortDB(FakeDB):
        def run(self, sql, params=None, **kw):
            if "AS pending_customers" in sql:
                return SimpleNamespace(
                    rows=[{"strategic_customers": 200, "pending_customers": 150}],
                    duration_ms=1,
                    truncated=False,
                )
            return super().run(sql, params, **kw)

    result = service(CohortDB()).query("SC03", scope={"limit": 2})
    assert next(m for m in result["metrics"] if m["code"] == "M0257")["value"] == 150
    assert result["strategicCustomers"] == 200


def test_missing_amounts_are_not_zero_filled_in_fact_or_analysis():
    class MissingDB(FakeDB):
        def run(self, sql, params=None, **kw):
            r = super().run(sql, params, **kw)
            if "AS awarded_unsigned_rows" in sql:
                r.rows[0].update(
                    amount_100m=None, power_gwh=None, missing_amount=1, missing_energy=1
                )
            return r

    result = service(MissingDB()).analyze(scenario="SC04")
    assert all(m["value"] is None for m in result["metrics"] if m["code"] in {"M0179", "M0142"})
    assert result["observation"]["impact"]["amount100m"] is None
    assert "0.00 亿元" not in result["observation"]["headline"]


def test_blocked_sc05_metrics_cannot_trigger_anomalies_or_risk_grading():
    s = service()
    ctx = s.context("SC05")
    result = analyze(
        catalog(),
        "SC05",
        ctx,
        {
            "status": "blocked",
            "metrics": [
                {"code": "M0334", "value": 100, "status": "blocked"},
                {"code": "M36006", "value": 0.9, "status": "blocked"},
            ],
        },
    )
    assert not result["observation"]["observed"]
    assert all(a["status"] == "unverifiable" for a in result["anomalies"])


def test_invalid_scope_survives_analysis_as_needs_clarification():
    result = service().analyze(
        scenario="SC01", scope={"periodStart": "2026-10-28", "periodEnd": "2026-10-01"}
    )
    assert result["status"] == "needs_clarification"


def test_blocked_analysis_cannot_become_an_ok_draft():
    result = service().draft(scenario="SC01", scope={"periodEnd": "2026-09-30"})
    assert result["stage"] == "S05" and result["status"] == "blocked"
    assert result["canvasActions"] == []


def test_phone_in_draft_owner_is_not_returned_to_html_or_model():
    result = service().draft(scenario="SC01", owner_name="13800000000")
    assert "13800000000" not in json.dumps(result, ensure_ascii=False)
    assert result["status"] in {"blocked", "needs_clarification"}


def test_cross_scenario_analysis_is_rejected_instead_of_drafting_the_wrong_task():
    result = service().draft(
        scenario="SC01",
        analysis={"scenario": "SC05", "status": "ok", "observation": {"headline": "wrong"}},
    )
    assert result["status"] in {"blocked", "needs_clarification"} and not result.get(
        "canvasActions"
    )


def test_unknown_solution_selection_is_explicit_not_an_empty_unexplained_draft():
    result = service().draft(scenario="SC01", solutions=["SL08"])
    assert result["status"] == "needs_clarification"
    assert result["gaps"]


def test_sample_rf_is_not_a_business_approved_target():
    result = service().verify(scenario="SC03", baseline={"anything": 1})
    assert result["status"] == "blocked"
    assert all(t["enabled"] is False for t in result["verification"]["effect"]["targets"])


def test_database_blockage_is_visible_in_verification_envelope():
    db = FakeDB()
    db.available = False
    result = service(db).verify(scenario="SC03", baseline={"anything": 1})
    assert result["status"] == "blocked"
    assert any(g["code"] == "DATABASE_UNAVAILABLE" for g in result["gaps"])


def test_task_dispatch_requires_a_page_or_explicit_idempotency_scope():
    class Client:
        def create_todo(self, **kwargs):
            raise AssertionError("must not dispatch")

    task = service().draft(scenario="SC01")["tasks"][0]
    with pytest.raises(ValueError):
        service().execute(task=task, recipients=["13800000000"], client=Client())


@pytest.mark.parametrize(
    "question,sop",
    [
        ("销售额怎么算？", "P01"),
        ("发货前要满足什么条件？", "P02"),
        ("本月超期未发多少？", "P03"),
        ("本月为什么比上月少？", "P04"),
        ("按客户、产品和团队拆开看。", "P05"),
        ("哪些订单已经超期？", "P06"),
        ("哪些客户承诺受影响？", "P08"),
        ("超期未发为什么增加？", "P09"),
        ("优先补料还是调整排产？", "P10"),
        ("把整改建议拆成任务，先给我审核。", "P11"),
        ("把这份已批准任务下发给责任人。", "P12"),
        ("谁超期？催一下负责人。", "P14"),
        ("这个问题能否关闭？", "P15"),
        ("两个看板销售额不一致？", "P16"),
        ("产能增加10%会怎样？", "P17"),
    ],
)
def test_design_document_sop_examples_route_to_their_own_family(question, sop):
    assert route(question, catalog()).sop_id == sop


@pytest.mark.parametrize("question", ["把这些订单安排发货", "超期未发任务进度"])
def test_write_or_empty_progress_sop_cannot_be_presented_as_completed_analysis(question):
    db = FakeDB()
    result = service(db).closed_loop(question=question, scenario="SC01")
    assert result["status"] == "not_applicable"
    assert not db.calls


@pytest.mark.parametrize(
    "question,key",
    [
        ("超期未发近六个月趋势", "comparison"),
        ("订单在哪个节点卡住？", "processConversion"),
        ("预计超期未发能完成多少", "forecast"),
        ("经营情况怎么样", "subgoals"),
    ],
)
def test_implemented_special_sops_return_structured_results_or_explicit_gaps(question, key):
    db = FakeDB()
    result = service(db).closed_loop(question=question, scenario="SC01")
    assert result["status"] in {"ok", "partial", "blocked"}
    analysis = result["analysis"]
    assert key in analysis
    assert "S05" not in result["stages"]


def test_mcp_rejects_unknown_arguments_before_service_or_database(monkeypatch):
    from bi_agent.process360 import tools

    monkeypatch.setattr(tools, "_service", lambda *_: pytest.fail("service must not run"))
    with pytest.raises(ValueError):
        tools.EXECUTORS["Process360Query"]({"scenario": "SC01", "sql": "SELECT 1"}, ".")


def test_recipients_iterator_consumed_once_before_dispatch():
    class Client:
        def create_todo(self, **kw):
            assert kw["recipients_raw"] == ["13800000000"]
            return {"ok": True, "applied": 1}

    task = service().draft(scenario="SC01")["tasks"][0]
    result = service().execute(
        task=task, recipients=iter(["13800000000"]), canvas_id="run-1", client=Client()
    )
    assert result["recipientsProvidedByHost"] == 1


def test_lossy_id_normalization_cannot_collapse_different_objects():
    from bi_agent.integrations.fuxi_todo import make_source_todo_id

    assert make_source_todo_id("任务一", "画布") != make_source_todo_id("任务二", "画布")
    assert make_source_todo_id("a" * 250 + "1", "canvas") != make_source_todo_id(
        "a" * 250 + "2", "canvas"
    )


def test_invalid_phone_error_does_not_echo_raw_recipient():
    from bi_agent.integrations.fuxi_todo import normalize_recipient

    with pytest.raises(ValueError) as error:
        normalize_recipient("private-person-123")
    assert "private-person" not in str(error.value)


def test_empty_fuxi_receipt_is_not_success():
    from bi_agent.integrations.fuxi_todo import FuxiTodoClient

    class Client(FuxiTodoClient):
        def _post(self, *_):
            return {}

    result = Client().create_todo(
        title="核查", content="核查", action_id="a1", recipients_raw=["13800000000"]
    )
    assert not result["ok"]


@pytest.mark.parametrize("unknown,energy,missing_amount", [(1, 0, 0), (0, 2, 0), (0, 0, 1)])
def test_incomplete_sc05_cohorts_do_not_publish_complete_metrics(unknown, energy, missing_amount):
    class DB(FakeDB):
        def run(self, sql, params=None, **kwargs):
            result = super().run(sql, params, **kwargs)
            if "AS actual_rows" in sql:
                result.rows[0].update(
                    unknown_rows=unknown, zero_power_rows=energy, missing_amount_rows=missing_amount
                )
            return result

    result = service(DB()).query("SC05")
    targets = (
        {"M0334", "M0335", "M36006"} if unknown else ({"M0334", "M36006"} if energy else {"M0335"})
    )
    for m in result["metrics"]:
        if m["code"] in targets:
            assert m["status"] == "blocked" and m["value"] is None


def test_fact_only_closed_loop_stops_before_analysis_and_task_drafting():
    result = service().closed_loop(question="本月超期未发多少？", scenario="SC01")
    assert "S03" in result["stages"]
    assert "S04" not in result["stages"] and "S05" not in result["stages"]


def test_root_cause_request_does_not_implicitly_generate_task_orders():
    result = service().closed_loop(question="超期未发为什么增加？", scenario="SC01")
    assert "S04" in result["stages"] and "S05" not in result["stages"]


def test_historical_shipment_comparison_requires_plan_history_not_current_plan():
    db = FakeDB()
    result = service(db).query("SC05", scope={"periodEnd": "2026-09-30"})
    assert result["status"] == "blocked" and not db.calls


def test_fuxi_rejection_receipt_does_not_return_recipient_phones():
    from bi_agent.integrations.fuxi_todo import FuxiTodoClient

    class Client(FuxiTodoClient):
        def _post(self, *_):
            return {
                "applied": 0,
                "errors": [{"message": "invalid 13800000000", "recipientsRaw": ["13800000000"]}],
            }

    result = Client().create_todo(
        title="核查", content="核查", action_id="a1", recipients_raw=["13800000000"]
    )
    assert not result["ok"]
    assert "13800000000" not in json.dumps(result)


def test_public_mcp_dispatch_blocks_phone_in_task_metadata(monkeypatch):
    from bi_agent.web import mcp_endpoint

    class Client:
        def create_todo(self, **kwargs):
            pytest.fail("private data must be rejected before dispatch")

    monkeypatch.setattr(mcp_endpoint, "FuxiTodoClient", Client)
    with pytest.raises(ValueError):
        mcp_endpoint._task_order_executor()(
            {
                "action_id": "SC01-TK01",
                "title": "核查",
                "content": "核查",
                "canvas_id": "canvas-1",
                "recipients_raw": ["13800000000"],
                "owner_name": "13800000000",
            },
            ".",
        )
