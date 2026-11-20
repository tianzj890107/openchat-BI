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
}


def _band(code, stage, band, count, amount, energy, severe=None):
    detail = {"阶段": stage, "档位": band, "各产品静态基线及有效正周期样本数": [{"产品类型": "全部", "静态基线天": 32.6,
                                                                       "有效正周期样本数": 120}]}
    if severe:
        detail["严重超期汇总_跨阶段去重"] = severe
    return {"指标序号": code, "数量": count, "金额_亿元": amount, "电量_GWh": energy, "计算说明状态": "已有查询结果",
            "分组明细及缺口": detail}


SEVERE_TOTAL = dict(opportunity_count=300, stage_record_count=320, amount_yi=8.5, energy_gwh=4.2, hit_stage_count=1,
                    missing_amount_opportunities=0, missing_energy_opportunities=0)
# 亿纬锂能本体文件_1117 result shapes: R01 (gap by product type), R08 (positive
# customer gaps), R12～R17 (one statement, six band rows).
OPPORTUNITY = {
    "OR01": [{"指标序号": "R01", "金额_亿元": 60.0, "分组明细及缺口": [
        dict(product_type="全部", target_amount=120.0, progress_amount=20.0, forecast_amount=40.0, gap_amount=60.0,
             gap_rate_amount=0.5, target_energy=50.0, progress_energy=10.0, forecast_energy=45.0, gap_energy=-5.0,
             gap_rate_energy=-0.1),
        dict(product_type="电芯", target_amount=80.0, gap_amount=50.0)]}],
    "OR08": [{"指标序号": "R08", "数量": 3, "分组明细及缺口": [
        {"风险专用正缺口汇总": {"任一口径正缺口客户数": 3,
                         "金额口径": {"缺口客户数": 3, "战略客户数": 1, "客户等级未知数": 0, "目标金额_亿元": 30.0,
                                  "进度金额_亿元": 5.0, "剩余预测金额_亿元": 10.0, "缺口金额_亿元": 15.0},
                         "电量口径": {"缺口客户数": 0}}},
        dict(account_id="A1", account_name="客户甲", gap_amount=9.0),
        dict(account_id="A2", account_name="客户乙", gap_amount=-1.0)]}],
    "BANDS": [_band("R12", "商机获取", "超期", 40, 3.0, 1.0, SEVERE_TOTAL), _band("R13", "商机获取", "严重超期", 300, 9.0, 4.5),
              _band("R14", "技术交流", "超期", 5, 0.5, 0.1), _band("R15", "技术交流", "严重超期", 0, 0.0, 0.0),
              _band("R16", "方案推动", "超期", 2, 0.2, 0.1), _band("R17", "方案推动", "严重超期", 0, 0.0, 0.0)],
}


class Result:
    def __init__(self, rows, truncated=False):
        self.rows = rows
        self.truncated = truncated


def fake_database(*, fail=(), empty=(), override=None, unavailable=False, opportunity=None):
    """A database whose reader answers each bound metric SQL with fixture rows."""
    config = ss.load_config()
    by_sql = {}
    for code, metric in config["metrics"].items():
        if not metric["derived"]:
            by_sql.setdefault(ss.metric_sql(config, code, 2025, MEASURED, "ded_public"), []).append(code)
    values = dict(SCALARS, **(override or {}))
    answers = dict(OPPORTUNITY, **(opportunity or {}))
    seen = []

    class Reader:
        def run(self, sql, params, timeout_ms=0):
            codes = by_sql[sql]
            seen.append((sql, params))
            if set(codes) & set(fail):
                raise RuntimeError(f"boom {codes[0]}")
            if set(codes) & set(empty):
                return Result([])
            if codes[0] in ss.BAND_CODES:
                return Result([dict(row) for row in answers["BANDS"]])
            if codes[0] in ("OR01", "OR08"):
                return Result([dict(row) for row in answers[codes[0]]])
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
    assert config["source"]["path"].endswith("销售额出货量共同问题分析_V4.xlsx")
    kinds = [spec["kind"] for spec in config["issues"].values()]
    assert kinds.count("metric") == 9 and kinds.count("link") == 0 and kinds.count("data") == 5
    # Business problems are typed by stage; data checks are not problems.
    assert {code: spec["category"] for code, spec in config["issues"].items() if spec["kind"] != "data"} == {
        "IS01": "订未发问题", "IS03": "订单问题", "IS04": "订未发问题", "IS05": "订单问题", "IS06": "订未发问题",
        "IS08": "订单问题", "IS11": "商机问题", "IS12": "商机问题", "IS13": "商机问题"}
    # V4: the 商机问题 are 亿纬锂能本体文件_1117's three 商机 risks on its own SQL.
    issues = config["issues"]
    assert [issues[c]["name"] for c in ("IS11", "IS12", "IS13")] == ["商机预测覆盖不足", "客户预测不足", "商机推进超期，影响签单"]
    assert issues["IS11"]["indicators"] == "OR01" and issues["IS12"]["indicators"] == "OR08"
    assert issues["IS11"]["params"] == dict(gapRateHigh=0.1, gapRateMedium=0.05)
    assert issues["IS13"]["params"] == dict(stagesHigh=2, amountHigh=10)
    assert issues["IS13"]["causes"] == ["RC20", "RC18", "RC15", "RC17"]
    assert all(config["causes"][c]["method"] == "AI" for c in ("RC13", "RC14", "RC15", "RC16", "RC17", "RC18", "RC19", "RC20"))
    assert not {"IS02", "IS07", "IS09", "IS10", "DQ06"} & set(issues)
    assert not {"C01", "C03", "C06", "C08", "C10", "R04", "R07"} & set(config["metrics"])
    opp_sql = v2._text(config["metrics"]["OR01"]["sql"])
    assert config["metrics"]["OR13"]["name"] == "商机获取阶段严重超期商机数及预测量" and not config["metrics"]["OR13"]["derived"]
    assert opp_sql.count("%s") == 3 and "CAST(%s AS DATE) AS start_date" in opp_sql
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
    assert len(sql) == 35 and all(m["sql"].strip() and m["resultColumn"] for m in sql)


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
    # Order fulfilment 70% < 80%; orders cancelled; the three 1117 商机 problems.
    assert {"IS06", "IS08", "IS11", "IS12", "IS13"} <= set(findings)
    assert not {"DQ01", "DQ02", "DQ03", "DQ04", "DQ05"} & set(findings)
    assert {findings[c]["riskCategory"] for c in ("IS11", "IS12", "IS13")} == {"商机问题"}
    judgement = result["ontologyJudgement"]
    # Only business problems are judged; data checks never reach the card.
    assert [i["code"] for i in judgement["risks"]] == ["IS01", "IS03", "IS04", "IS05", "IS06", "IS08",
                                                        "IS11", "IS12", "IS13"]
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
    # A dashboard combination query runs once and feeds every metric it
    # carries; the six 1117 stage bands share one statement too.
    config = ss.load_config()
    statements = {ss.metric_sql(config, c, 2025, MEASURED) for c, m in config["metrics"].items() if not m["derived"]}
    assert len(result["queryCatalog"]) == len(statements) < 35
    bands = next(q for q in result["queryCatalog"] if "OR12" in q["metricCodes"])
    assert bands["metricCodes"] == list(ss.BAND_CODES)
    # 1117 SQL binds [期初, 次年初, 观察日]; the dashboard SQL binds nothing.
    assert bands["params"] == ["2025-01-01", "2026-01-01", "2025-12-31"]
    assert next(q for q in result["queryCatalog"] if "B01" in q["metricCodes"])["params"] == []
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


def test_opportunity_problems_are_judged_on_the_1117_sql_like_the_opportunity_card():
    requests = []

    def judge(request):
        requests.append(request)
        return dict(established=False, reason="x")

    # A published 商机获取 card is no longer read: the problems come from 1117 SQL.
    upstream = _opportunity_card(("RK02", "签单进度滞后", "极高", "商机覆盖风险"))
    card = ss.build_card("2025", database=fake_database(), measurement_date="2025-10-31", judge=judge,
                         upstream=upstream)
    result = card["result"]
    findings = {f["riskCode"]: f for f in result["findings"]}
    # IS11 (BR-A01): 120 − (20 + 40) = 60, rate 50% ≥ 10% → 高; energy covered, not listed.
    coverage = findings["IS11"]
    assert coverage["decidedBy"] == "rule" and coverage["riskLevel"] == "高"
    # Same template as the 商机获取 card (1117 1119).
    assert coverage["description"] == ("金额目标 120.00 亿元，1—9月已签单 20.00 亿元，10—12月剩余预测 40.00 亿元，"
                                       "全年缺口 60.00 亿元，缺口率 50.0%。")
    # IS12 (BR-A06): R08's 风险专用正缺口汇总 only; a strategic customer → 高.
    customers = findings["IS12"]
    assert customers["riskLevel"] == "高"
    assert customers["description"] == ("共 3 家客户存在缺口。金额口径 3 家，目标 30.00 亿元，已签单 5.00 亿元，"
                                        "剩余预测 10.00 亿元，缺口合计 15.00 亿元。")
    records = {r["id"]: r for r in card["evidence"]["records"]}
    assert "ss:customer-gap:A1" in records and "ss:customer-gap:A2" not in records
    # IS13 (BR-A11): severe overruns only, the de-duplicated total (BR-V09);
    # one stage and 8.5 亿元 < 10 → 中.
    overrun = findings["IS13"]
    assert overrun["riskLevel"] == "中"
    assert overrun["description"] == "300 条商机在已结束阶段出现严重超期，预测金额 8.50 亿元，预测电量 4.20 GWh。"
    assert records["ss:stage-band:OR13"]["value"] == 300 and "ss:stage-band:OR15" not in records
    # Rule-decided: none of them goes to the model; no upstream gap is noted.
    assert not any(r.get("code") in {"IS11", "IS12", "IS13"} for r in requests)
    assert "RK02" not in str(result["findings"])
    assert not any("尚未发布" in note for note in result["limitations"])
    # The causes behind IS01 / IS05 now read the same 1117 metrics.
    evaluated = ss.evaluate(ss.collect("2025", MEASURED, database=fake_database()), ss.load_config(), MEASURED)
    assert evaluated["causeOutcomes"]["RC01"]["ruleStatus"] == "triggered"
    assert evaluated["causeOutcomes"]["RC02"]["ruleStatus"] == "triggered"
    assert "RC07" not in evaluated["causeOutcomes"]


def test_opportunity_problems_levels_and_gaps_follow_1117():
    severe = dict(SEVERE_TOTAL, hit_stage_count=2, amount_yi=3.0)
    bands = [_band("R12", "商机获取", "超期", 1, 0.1, 0.1, severe), _band("R13", "商机获取", "严重超期", 2, 1.0, 1.0),
             _band("R14", "技术交流", "超期", 0, 0, 0), _band("R15", "技术交流", "严重超期", 3, 2.0, 1.0),
             _band("R16", "方案推动", "超期", 0, 0, 0), _band("R17", "方案推动", "严重超期", 0, 0, 0)]
    covered = [{"指标序号": "R01", "分组明细及缺口": [dict(product_type="全部", target_amount=100.0, gap_amount=-5.0,
                                                    target_energy=40.0, gap_energy=0.0)]}]
    no_gap = [{"指标序号": "R08", "数量": 0, "分组明细及缺口": [{"风险专用正缺口汇总": {"任一口径正缺口客户数": 0}}]}]
    card = _card(opportunity=dict(BANDS=bands, OR01=covered, OR08=no_gap))
    findings = {f["riskCode"]: f for f in card["result"]["findings"]}
    # Two stages hit → 高 whatever the amount; covered target and no customer gap → not established.
    assert findings["IS13"]["riskLevel"] == "高"
    assert not {"IS11", "IS12"} & set(findings)
    # Partial amount: the level is left to be verified.
    partial = dict(SEVERE_TOTAL, missing_amount_opportunities=4)
    bands[0] = _band("R12", "商机获取", "超期", 1, 0.1, 0.1, partial)
    bands[3] = _band("R15", "技术交流", "严重超期", 0, 0, 0)
    finding = next(f for f in _card(opportunity=dict(BANDS=bands))["result"]["findings"] if f["riskCode"] == "IS13")
    assert finding["riskLevel"] == "" and "，预测金额 8.50 亿元" in finding["description"]
    # A failed 1117 query leaves the problem undecided (and limits the card).
    failed = _card(fail={"OR01"})
    judged = {r["code"]: r for r in failed["result"]["ontologyJudgement"]["risks"]}
    assert judged["IS11"]["ruleStatus"] == "insufficient" and failed["status"] == "limited"


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


def test_combined_card_reads_as_three_lines_for_opportunity_order_and_shipment():
    # 商机本体 1117 BR-V01: 商机、订单、发货三行，各一句话。
    groups = {"商机问题": [dict(title="IS11 商机预测覆盖不足", riskLevel="高")], "订未发问题": []}
    risk_groups = [dict(category="商机问题", summary="商机预测覆盖不足且客户预测存在缺口。", summarySource="model"),
                   dict(category="订单问题", summary="本类共 1 项问题：x。", summarySource="rule")]
    assessments = [dict(code="IS04", ruleStatus="insufficient", include=False)]
    lines = ss.stage_lines(groups, risk_groups, assessments, {"IS04": "订未发问题"})
    assert [line["label"] for line in lines] == ["商机", "订单", "发货"]
    assert lines[0]["text"] == "商机预测覆盖不足且客户预测存在缺口。"
    assert lines[1]["text"] == "本期未发现订单环节业务问题。"
    assert lines[2]["text"] == "发货环节部分问题数据不足，无法核实。"
    # Without a model summary the line names the stage's own problems.
    fallback = ss.stage_lines(groups, [], [], {})
    assert fallback[0]["text"] == "商机环节存在 1 项问题：商机预测覆盖不足（高）。"
    from bi_agent.cockpit.section_summary import risk_group_prompt
    assert "每个分类只写一句话" in risk_group_prompt("销售额与出货量共同分析", "问题")
