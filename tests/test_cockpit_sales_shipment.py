"""销售额／出货量共同问题分析: indicator → problem card on its own ontology."""
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from bi_agent.cockpit import sales_shipment as ss
from bi_agent.cockpit import opportunity_v2 as v2

ROOT = Path(__file__).resolve().parents[1]
MEASURED = date(2025, 12, 31)

# One value per result column; grouped metrics return their own rows.
SCALARS = {
    "YWLN_M0002": 100.0, "YWLN_M0001": 60.0, "YWLN_M0007": 50.0, "YWLN_M0006": 30.0, "YWLN_M0009": 0.86,
    "YWLN_M0003": 0.6, "YWLN_M0008": 0.6, "YWLN_M0004": 92.0, "YWLN_M0005": 0.92, "YWLN_M0011": 46.0,
    "YWLN_M0012": 0.92, "YWLN_M0010": 12.0, "YWLN_M0037": 0.7, "YWLN_M_ORDER_CANCEL_CHANGE": 2.0,
    "YWLN_M0053": 20.0, "YWLN_M0054": 15.0, "YWLN_M0144": 30.0, "YWLN_M0148": 60.0, "YWLN_M0145": 10.0,
    "YWLN_M0149": 25.0, "YWLN_M0143": 10.0, "M0134": 4.0, "YWLN_M0150": 15.0,
    "YWLN_M_OVERDUE_PENDING_AMOUNT_SHARE": 0.4, "YWLN_M0151": 1.5, "YWLN_M0056": 40.0, "YWLN_M0057": 30.0,
    "YWLN_M0023": 120.0, "YWLN_M0022": 55.0, "YWLN_M0140": 8.0, "YWLN_M0198": 70.0, "YWLN_M0194": 33.0,
    "YWLN_M0257": 3.0,
}
GROUPS = {
    "O01": [dict(YWLN_D003="电芯", YWLN_M0032=30.0), dict(YWLN_D003="PACK", YWLN_M0032=10.0)],
    "O02": [dict(YWLN_D016="normal_order", YWLN_M0033=80.0), dict(YWLN_D016="order_cancel", YWLN_M0033=3.0)],
    "S12": [dict(YWLN_D004="电芯产品部", YWLN_D005="战略大客户", YWLN_D006="客户A", YWLN_D049="SO-1",
                 YWLN_D050="2025-10-01", YWLN_M_ORDER_OVERDUE_DAYS=91.0),
            dict(YWLN_D004="电芯产品部", YWLN_D005="一般客户", YWLN_D006="客户B", YWLN_D049="SO-2",
                 YWLN_D050="2025-12-01", YWLN_M_ORDER_OVERDUE_DAYS=30.0)],
    "S13": [dict(YWLN_D024="overdue_uncompleted", YWLN_M0312=3.0), dict(YWLN_D024="normal_completed", YWLN_M0312=20.0)],
    "C07": [dict(YWLN_D005="战略大客户", YWLN_M_CUSTOMER_ACTUAL_ENERGY=9000.0),
            dict(YWLN_D005="一般客户", YWLN_M_CUSTOMER_ACTUAL_ENERGY=4000.0)],
    "C08": [dict(YWLN_D005="战略大客户", YWLN_M_CUSTOMER_ENERGY_GAP=1500.0),
            dict(YWLN_D005="一般客户", YWLN_M_CUSTOMER_ENERGY_GAP=200.0)],
}


class Result:
    def __init__(self, rows, truncated=False):
        self.rows = rows
        self.truncated = truncated


def fake_database(*, fail=(), empty=(), override=None, unavailable=False):
    """A database whose reader answers each bound metric SQL with fixture rows."""
    config = ss.load_config()
    by_sql = {}
    for code, metric in config["metrics"].items():
        if not metric["derived"]:
            by_sql.setdefault(v2._ontology_metric_sql(config, code, 2025, MEASURED, "ded_public"), []).append(code)
    values = dict(SCALARS, **(override or {}))
    seen = []

    class Reader:
        def run(self, sql, params, timeout_ms=0):
            codes = by_sql[sql]
            seen.append(sql)
            if set(codes) & set(fail):
                raise RuntimeError(f"boom {codes[0]}")
            if set(codes) & set(empty):
                return Result([])
            grouped = [code for code in codes if code in GROUPS]
            if grouped:
                return Result([dict(row) for row in GROUPS[grouped[0]]])
            return Result([{config["metrics"][code]["resultColumn"]: values.get(config["metrics"][code]["resultColumn"])
                            for code in codes}])

    class Snapshot:
        def __enter__(self):
            return Reader()

        def __exit__(self, *args):
            return False

    class Database:
        available = not unavailable
        config = SimpleNamespace(schema="ded_public", database="ywln", host="127.0.0.1", port=5432)

        def unavailable_reason(self):
            return "未配置数据库"

        def snapshot(self, **kwargs):
            return Snapshot()

    database = Database()
    database.seen = seen
    return database


def _no(request):
    return dict(established=False, reason="测试：不成立")


def _card(**kwargs):
    judge = kwargs.pop("judge", _no)
    return ss.build_card("2025", database=fake_database(**kwargs), measurement_date="2025-12-31", judge=judge)


def test_config_is_problem_driven_and_read_from_the_ontology():
    config = ss.load_config()
    assert config["version"] == ss.RULES_VERSION
    assert config["source"]["path"].endswith("销售额出货量共同问题分析_V2.xlsx")
    kinds = [spec["kind"] for spec in config["issues"].values()]
    assert kinds.count("metric") == 8 and kinds.count("data") == 6
    assert "risks" not in config  # problems replace the risk layer
    assert config["issues"]["IS01"]["params"] == dict(lagExtremePoints=15, lagHighPoints=10)
    assert config["issues"]["IS04"]["params"] == dict(share=0.2, highShare=0.5)
    assert config["causes"]["RC06"]["params"] == dict(deviation=0.1)
    for code, spec in config["issues"].items():
        assert spec["causes"] and set(spec["causes"]) == set(config["links"][code]["causes"])
    sql = [m for m in config["metrics"].values() if not m["derived"]]
    assert len(sql) == 39 and all(m["sql"].lstrip().startswith("--") and m["resultColumn"] for m in sql)


def test_card_settles_problems_by_rule_and_ships_as_a_card():
    from bi_agent.cockpit.cards import card_delivery_state, valid_card
    from bi_agent.cockpit.delivery import project_card, publication_payload
    card = _card()
    assert card["context"]["stage"] == "combined" and card["context"]["slotId"] == "sales-shipment-issues"
    assert card["status"] == "completed" and valid_card(card)
    result = card["result"]
    findings = {f["riskCode"]: f for f in result["findings"]}
    # 0.6 / 0.6 against 0.86 time progress: both behind by 26 points.
    assert findings["IS01"]["riskLevel"] == "极高" and findings["IS01"]["decidedBy"] == "rule"
    assert findings["IS01"]["issueType"] == "指标异常"
    assert "落后 26.0 个百分点" in findings["IS01"]["description"]
    # 10 overdue of 25 pending = 40% ≥ 20%.
    assert findings["IS04"]["riskLevel"] == "中"
    # Order fulfilment 70% < 80%; strategic customer energy gap > 0.
    assert {"IS06", "IS07", "IS08"} <= set(findings)
    assert not {"DQ01", "DQ02", "DQ03", "DQ04", "DQ05", "DQ06"} & set(findings)
    judgement = result["ontologyJudgement"]
    assert [i["code"] for i in judgement["risks"]] == list(ss.load_config()["issues"])
    assert result["summary"].startswith("本轮 14 项本体问题中")
    causes = {c["causeCode"]: c for c in result["causes"]}
    assert {"RC01", "RC03", "RC04", "RC05", "RC08", "RC09"} <= set(causes)
    assert causes["RC03"]["stage"] == "shipment" and causes["RC01"]["stage"] == "opportunity"
    assert result["recommendations"] and result["primaryLabel"] == "问题"
    # 39 SQL metrics share 33 statements: a dashboard combination query runs
    # once and feeds every metric it carries.
    assert len(result["queryCatalog"]) == 33
    covered = [code for q in result["queryCatalog"] for code in q["metricCodes"]]
    assert sorted(covered) == sorted(c for c, m in ss.load_config()["metrics"].items() if not m["derived"])
    assert all(q["status"] == "ok" for q in result["queryCatalog"])
    assert result["ontologyTrace"]["risks"][0]["code"] == "IS01"
    assert any(r["id"].startswith("ss:order:SO-1") for r in card["evidence"]["records"])
    delivered = publication_payload(project_card(card, "sales-shipment-issues"))
    assert card_delivery_state(delivered, "sales-shipment-issues")["renderable"]
    assert [f["riskCode"] for f in delivered["result"]["findings"]] == [f["riskCode"] for f in result["findings"]]


def test_a_failed_query_is_a_data_problem_not_a_failed_card():
    card = _card(fail={"B01"})
    findings = {f["riskCode"]: f for f in card["result"]["findings"]}
    assert findings["DQ01"]["issueType"] == "数据问题" and findings["DQ01"]["riskLevel"] == "高"
    assert "B01 目标销售额（failed·RuntimeError）" in findings["DQ01"]["description"]
    assert {c["causeCode"] for c in card["result"]["causes"]} >= {"RC10"}
    assert card["status"] == "limited"
    failed = [q for q in card["result"]["queryCatalog"] if q["status"] == "failed"]
    assert [q["metricCodes"] for q in failed] == [["B01"]] and failed[0]["error"]["code"] == "RuntimeError"


def test_no_usable_query_fails_the_card():
    config = ss.load_config()
    every = {code for code, m in config["metrics"].items() if not m["derived"]}
    with pytest.raises(ss.SalesShipmentUnavailable, match="全部调用SQL取数失败"):
        _card(fail=every)
    with pytest.raises(ss.SalesShipmentUnavailable, match="未配置数据库"):
        ss.build_card("2025", database=fake_database(unavailable=True), measurement_date="2025-12-31")


def test_empty_core_metric_and_inconsistent_rates_are_data_problems():
    card = _card(override={"YWLN_M0002": None, "YWLN_M0008": 0.9})
    findings = {f["riskCode"]: f for f in card["result"]["findings"]}
    assert "B01 目标销售额" in findings["DQ02"]["description"]
    # 出货量达成率 0.9 vs 实绩 30 ÷ 目标 50 = 0.6.
    assert "出货量达成率 90.0%，按实绩 ÷ 目标复算为 60.0%" in findings["DQ03"]["description"]
    assert {"RC11", "RC12"} <= {c["causeCode"] for c in card["result"]["causes"]}


def test_rule_gaps_go_to_the_model_one_problem_at_a_time():
    requests = []

    def judge(request):
        requests.append(request)
        if request["kind"] == "inference":
            return dict(causes=[])
        return dict(established=request["code"] == "IS06", level="中", reason="模型依据取数判定")
    card = _card(override={"YWLN_M0037": None}, judge=judge)
    issue_requests = [r for r in requests if r["kind"] == "issue"]
    assert [r["code"] for r in issue_requests] == ["IS06"]
    finding = next(f for f in card["result"]["findings"] if f["riskCode"] == "IS06")
    assert finding["decidedBy"] == "model" and finding["description"] == "模型依据取数判定"


def test_item_judge_uses_the_cards_own_role(monkeypatch):
    import bi_agent.llm.provider as provider
    seen = []

    def fake_stream(messages, system_prompt, allowed_tools, *args, **kwargs):
        seen.append((allowed_tools, system_prompt))
        return iter([dict(type="text_delta", text='{"established": true, "level": "中", "reason": "x"}'),
                     dict(type="message_end", stop_reason="end_turn", finish_reason="stop", usage={})])
    monkeypatch.setattr(provider, "stream_message", fake_stream)
    monkeypatch.setattr(v2, "_model_candidate_keys", lambda: ["route-a"])
    ss.item_judge(dict(kind="issue", code="IS06"))
    assert seen[0][0] == []
    assert seen[0][1].startswith(ss.ROLE_PROMPT) and "这一条问题" in seen[0][1]
    assert seen[0][1].count("你是") == 1
    assert "称“问题”" in ss.summary_role()


def test_fixed_annual_mode_runs_the_card_on_its_ontology():
    from bi_agent.cockpit import frozen
    assert "combined" in frozen.SECTION_SUMMARY_STAGES
    source = (ROOT / "bi_agent/cockpit/frozen.py").read_text(encoding="utf-8")
    assert "if stage == 'combined' and _sales_shipment_ontology_enabled():" in source
    assert frozen._diagnostic_fields(dict(query="B01", code="TIMEOUT", upstreamCode="57014",
                                          durationSeconds=1.5, message="m")) == dict(
        phase="database_query", query="B01", code="TIMEOUT", message="m", upstream_code="57014",
        duration_seconds=1.5)
