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
    assert config["source"]["path"].endswith("销售额出货量共同问题分析_V3.xlsx")
    kinds = [spec["kind"] for spec in config["issues"].values()]
    assert kinds.count("metric") == 8 and kinds.count("link") == 2 and kinds.count("data") == 6
    # V3: business problems are typed by stage; data checks are not problems.
    assert {code: spec["category"] for code, spec in config["issues"].items() if spec["kind"] != "data"} == {
        "IS01": "订未发问题", "IS02": "商机问题", "IS03": "订单问题", "IS04": "订未发问题",
        "IS05": "订单问题", "IS06": "订未发问题", "IS07": "商机问题", "IS08": "订单问题",
        "IS09": "商机问题", "IS10": "商机问题"}
    # 商机问题 linked to the 商机获取 card: its categories, no metrics of their own.
    assert config["issues"]["IS09"]["params"] == dict(upstreamCategory="商机覆盖风险")
    assert config["issues"]["IS10"]["params"] == dict(upstreamCategory="商机转化风险")
    assert config["issues"]["IS09"]["indicators"] == "" and config["issues"]["IS10"]["indicators"] == ""
    assert all(spec["type"] == "数据校验" and spec["category"] == ""
               for spec in config["issues"].values() if spec["kind"] == "data")
    assert not any(spec["type"] in ("指标异常", "数据问题") for spec in config["issues"].values())
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
    assert findings["IS01"]["riskCategory"] == "订未发问题" and "issueType" not in findings["IS01"]
    assert "落后 26.0 个百分点" in findings["IS01"]["description"]
    # 10 overdue of 25 pending = 40% ≥ 20%.
    assert findings["IS04"]["riskLevel"] == "中"
    # Order fulfilment 70% < 80%; strategic customer energy gap > 0.
    assert {"IS06", "IS07", "IS08"} <= set(findings)
    assert not {"DQ01", "DQ02", "DQ03", "DQ04", "DQ05", "DQ06"} & set(findings)
    judgement = result["ontologyJudgement"]
    # Only business problems are judged; data checks never reach the card.
    assert [i["code"] for i in judgement["risks"]] == [f"IS{n:02d}" for n in range(1, 11)]
    # Parent → child: 商机 / 订单 / 订未发问题, in the helmet's order.
    groups = result["riskGroups"]
    assert [g["category"] for g in groups] == [c for c in ss.ISSUE_GROUPS
                                               if any(f["riskCategory"] == c for f in result["findings"])]
    by_id = {f["id"]: f for f in result["findings"]}
    for group in groups:
        assert {by_id[fid]["riskCategory"] for fid in group["findingIds"]} == {group["category"]}
    assert [fid for g in groups for fid in g["findingIds"]] == [f["id"] for f in result["findings"]]
    # Business wording only: no codes, no 指标异常 / 数据问题, no rule tally.
    assert result["summary"] == ss.business_summary(
        {g["category"]: g["findingIds"] for g in groups})
    assert result["summary"].startswith(f"本期发现 {len(result['findings'])} 项业务问题：")
    assert not any(word in result["summary"] for word in ("IS0", "DQ0", "指标异常", "数据问题", "规则判定"))
    # The delivery is problem-only: do not run or publish causes/advice.
    assert result["causes"] == [] and result["analysisDimensions"] == []
    assert result["recommendations"] == [] and result["primaryLabel"] == "问题"
    assert result["ontologyJudgement"]["causes"] == []
    assert result["ontologyJudgement"]["advice"] == []
    assert "根因" not in result["summary"] and "建议" not in result["summary"]
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


def test_a_failed_query_limits_the_card_without_showing_a_data_problem():
    card = _card(fail={"B01"})
    findings = {f["riskCode"]: f for f in card["result"]["findings"]}
    # Data checks are not business problems: nothing DQ* is shown.
    assert not any(code.startswith("DQ") for code in findings)
    assert any("取数未成功" in note for note in card["result"]["limitations"])
    assert card["result"]["causes"] == [] and card["result"]["recommendations"] == []
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


def test_empty_core_metric_and_inconsistent_rates_are_checked_but_not_shown():
    data = ss.collect("2025", ss.v2._measurement_context("2025", "2025-12-31"),
                      database=fake_database(override={"YWLN_M0002": None, "YWLN_M0008": 0.9}))
    evaluated = ss.evaluate(data, ss.load_config(), None)
    checks = {item["code"]: item for item in evaluated["riskCandidates"]}
    # The data checks still run (they keep the rule trace honest)...
    assert "B01 目标销售额" in checks["DQ02"]["description"]
    # 出货量达成率 0.9 vs 实绩 30 ÷ 目标 50 = 0.6.
    assert "出货量达成率 90.0%，按实绩 ÷ 目标复算为 60.0%" in checks["DQ03"]["description"]
    # ...but the card shows business problems only.
    card = _card(override={"YWLN_M0002": None, "YWLN_M0008": 0.9})
    assert not any(f["riskCode"].startswith("DQ") for f in card["result"]["findings"])
    assert card["result"]["causes"] == [] and card["result"]["recommendations"] == []


def test_problem_groups_get_model_summaries_with_a_rule_fallback():
    from bi_agent.cockpit.section_summary import summarize_risk_groups
    calls = []

    def model(payload):
        calls.append(payload)
        # 订未发问题 passes; the others invent 9999 and fall back to the rule summary.
        return {"summaries": {category: ("超期订未发占比偏高。" if category == "订未发问题" else "缺口 9999 亿元。")
                              for category in payload["groups"]}}

    card = ss.build_card("2025", database=fake_database(), measurement_date="2025-12-31", judge=_no,
                         summarize_groups=lambda groups: summarize_risk_groups(
                             groups, call_model=model, card="销售额与出货量共同分析", label="问题"))
    groups = {g["category"]: g for g in card["result"]["riskGroups"]}
    assert groups["订未发问题"]["summary"] == "超期订未发占比偏高。"
    assert groups["订未发问题"]["summarySource"] == "model"
    for category, group in groups.items():
        if category != "订未发问题":
            assert group["summarySource"] == "rule"
            assert group["summary"].startswith(f"本类共 {len(group['findingIds'])} 项问题：")
            assert "9999" not in group["summary"]
    assert "validationFeedback" in calls[1]


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


def test_ratio_facts_are_percentages_with_their_ontology_definition():
    card = _card()
    facts = {f["id"]: f for f in card["evidence"]["facts"]}
    r01 = facts["ss:metric:R01"]
    assert r01["value"] == 60.0 and r01["unit"] == "%" and r01["label"] == "销售额达成率"
    assert r01["definition"] == ss.load_config()["metrics"]["R01"]["definition"]


def _opportunity_card(*risks, summaries=None):
    """A published 商机获取 card item: (code, title, level, category) rows."""
    findings = [dict(id=f"opp:{code}", riskCode=code, title=title, riskLevel=level, riskCategory=category)
                for code, title, level, category in risks]
    groups = {}
    for finding in findings:
        groups.setdefault(finding["riskCategory"], []).append(finding["id"])
    return dict(context=dict(period="2025", stage="opportunity"), result=dict(
        findings=findings,
        riskGroups=[dict(category=c, findingIds=ids, summary=(summaries or {}).get(c, ""))
                    for c, ids in groups.items()]))


def test_opportunity_problems_take_over_the_opportunity_card_categories():
    requests = []

    def judge(request):
        requests.append(request)
        return dict(established=False, reason="x")

    upstream = _opportunity_card(
        ("RK01", "商机预测覆盖不足", "高", "商机覆盖风险"),
        ("RK02", "签单进度滞后", "极高", "商机覆盖风险"),
        summaries={"商机覆盖风险": "商机预测与签单进度均存在缺口。"})
    card = ss.build_card("2025", database=fake_database(), measurement_date="2025-12-31", judge=judge,
                         upstream=upstream)
    result = card["result"]
    findings = {f["riskCode"]: f for f in result["findings"]}
    coverage = findings["IS09"]
    assert coverage["riskCategory"] == "商机问题" and coverage["decidedBy"] == "rule"
    # The highest level of the category's established risks.
    assert coverage["riskLevel"] == "极高"
    assert coverage["description"] == ("商机获取环节有 2 项商机覆盖风险成立：商机预测覆盖不足（高）、签单进度滞后（极高）。"
                                       "商机预测与签单进度均存在缺口。")
    assert "RK0" not in coverage["description"]
    # No 商机转化风险 established upstream: the conversion problem does not hold.
    assert "IS10" not in findings
    assert not any(r.get("code") in {"IS09", "IS10"} for r in requests)
    group = next(g for g in result["riskGroups"] if g["category"] == "商机问题")
    assert coverage["id"] in group["findingIds"]
    assert any(r["id"] == "ss:upstream:opportunity-risk:RK02" for r in card["evidence"]["records"])
    assert not any("尚未发布同期间分析结果" in note for note in result["limitations"])


def test_without_an_opportunity_card_the_linked_problems_wait_instead_of_guessing():
    requests = []

    def judge(request):
        requests.append(request)
        return dict(established=False, reason="x")

    card = ss.build_card("2025", database=fake_database(), measurement_date="2025-12-31", judge=judge)
    result = card["result"]
    assert not {"IS09", "IS10"} & {f["riskCode"] for f in result["findings"]}
    # Never handed to the model: there is nothing to judge from.
    assert not any(r.get("code") in {"IS09", "IS10"} for r in requests)
    judged = {r["code"]: r for r in result["ontologyJudgement"]["risks"]}
    assert judged["IS09"]["decidedBy"] == "unevaluated" and judged["IS09"]["reason"] == ss.UPSTREAM_MISSING
    assert any("商机覆盖、商机转化问题暂未纳入" in note for note in result["limitations"])


def test_the_customer_round_reads_the_same_period_and_runs_opportunity_first():
    from bi_agent.cockpit import frozen
    item = _opportunity_card(("RK10", "商机获取阶段超期较多", "高", "商机转化风险"))
    assert frozen._published_for_period(lambda key: item, "opportunity-risk", "2025") is item
    assert frozen._published_for_period(lambda key: item, "opportunity-risk", "2024") is None
    assert frozen._published_for_period(None, "opportunity-risk", "2025") is None

    def broken(key):
        raise RuntimeError("store unavailable")
    assert frozen._published_for_period(broken, "opportunity-risk", "2025") is None
    service = frozen.FrozenAnnualService.__new__(frozen.FrozenAnnualService)
    order = service.priority_order(page="analysis")
    assert order.index("opportunity-risk") < order.index("combined")
