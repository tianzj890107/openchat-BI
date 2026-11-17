"""360 智能分析: global ontology config, registered queries, strategy tools, handoff."""
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bi_agent.analysis360 import handoff, ontology as onto, tools
from bi_agent.analysis360.queries import QueryRejected, render

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def config():
    return onto.load_config()


class FakeDatabase:
    """Records SQL; answers with scripted rows (by substring of the SQL)."""

    def __init__(self, rows=None, truncated=False, error=None):
        self.config = SimpleNamespace(schema="ded_public")
        self.rows = rows if rows is not None else [dict(opportunity_id="opp-1", amount=12.5)]
        self.truncated = truncated
        self.error = error
        self.calls = []

    @contextmanager
    def snapshot(self):
        yield self

    def run(self, sql, params=None, max_rows=None):
        self.calls.append((sql, params))
        if self.error:
            raise self.error
        rows = self.rows(sql) if callable(self.rows) else self.rows
        columns = list(rows[0]) if rows else []
        return SimpleNamespace(columns=columns, rows=rows, truncated=self.truncated, duration_ms=1)


def _run(database=None, handoff_context=None):
    database = database or FakeDatabase()
    return tools.Run(handoff=handoff_context, database_factory=lambda: database), database


def _risk_handoff(code="RK02", title="签单进度滞后", period="2025"):
    return handoff.normalise(dict(
        kind="risk", period=period, measurementDate="2025-11-14",
        clause=dict(code=code, title=title, description="金额口径落后 12.3 个百分点", level="高"),
        card=dict(stage="商机获取", ontology="商机获取节点 V3"),
        siblings=[dict(code="RK01", title="商机预测覆盖不足")]))


# ---- config -----------------------------------------------------------------

def test_config_is_built_from_the_global_ontology_not_a_card_ontology(config):
    assert config["ontology"] == "亿纬锂能_流程360全局本体_无投标_V1.0"
    assert set(config["activities"]) == {f"BA0{i}" for i in range(8)}
    assert config["risks"]["RK02"]["activity"] == "BA02"
    assert config["risks"]["RK-GD01"]["activity"] == "BA05"
    assert config["risks"]["RK-GG01"]["activity"] == "BA00"
    assert config["budget"] == dict(maxEntityHops=3, maxCausesPerRound=5, maxQueries=12, previewRows=100)


def test_registered_sql_matches_its_registered_hash(config):
    for index, query in config["queries"].items():
        assert hashlib.sha256(config["sql"][index].encode("utf-8")).hexdigest() == query["sha256"], index


def test_query_gates_follow_the_access_sheet(config):
    assert config["queries"]["T005"]["gate"] == "enabled"
    assert config["queries"]["Q031"]["gate"] == "enabled"
    assert config["queries"]["Q029"]["gate"] == "mock"      # MOCK 回放
    assert config["queries"]["Q058"]["gate"] == "mock"
    assert config["queries"]["N01"]["gate"] == "pending"    # 诊断，先验收再启用
    assert not any(query["gate"] == "isolated" for query in config["queries"].values())


def test_candidate_relations_are_not_executable(config):
    assert config["relations"]["ER06"]["enabled"] and config["relations"]["ER19"]["enabled"]
    assert not config["relations"]["ER-G032"]["enabled"]
    assert "候选" in config["relations"]["ER-G032"]["disabledReason"]


# ---- query rendering --------------------------------------------------------

def test_template_binds_its_period_and_observation_time(config):
    sql, values, effective, _ = render(config, "T005", dict(
        start_date="2024-01-01", end_exclusive="2025-01-01", observed_date="2024-12-31"))
    assert "DATE '2024-01-01' AS start_date" in sql and "DATE '2025-01-01' AS end_exclusive" in sql
    assert "TIMESTAMP '2024-12-31 23:59:59'" in sql and "CURRENT_TIMESTAMP" not in sql.upper()
    assert values == {} and effective["start_date"] == "2024-01-01"
    assert not sql.lstrip().startswith("--")


def test_template_without_a_period_is_rejected(config):
    with pytest.raises(QueryRejected):
        render(config, "T005", {})
    with pytest.raises(QueryRejected):
        render(config, "T005", dict(start_date="2025-01-01", end_exclusive="2024-01-01"))


def test_config_query_keeps_only_the_filter_blocks_it_has_parameters_for(config):
    bare, values, _, notes = render(config, "Q031", {})
    assert values == {} and "FILTER_BEGIN" not in bare and ":team_ids" not in bare
    assert any("当前时点" in note for note in notes)
    sql, values, effective, _ = render(config, "Q031", dict(
        start_date="2025-01-01", end_exclusive="2026-01-01", team_ids=["储能一部", "储能二部"]))
    assert "%(team_ids_0)s, %(team_ids_1)s" in sql
    assert values["team_ids_1"] == "储能二部" and values["start_date"] == "2025-01-01"
    assert effective["team_ids"] == ["储能一部", "储能二部"]
    assert len(sql) > len(bare)


def test_config_query_rejects_parameters_outside_its_contract(config):
    with pytest.raises(QueryRejected, match="不接受"):
        render(config, "Q031", dict(sql="drop table x"))


def test_mock_and_pending_queries_are_never_rendered(config):
    for index in ("Q029", "N01"):
        with pytest.raises(QueryRejected, match="不可执行"):
            render(config, index, dict(start_date="2025-01-01", end_exclusive="2026-01-01"))


def test_every_enabled_query_renders(config):
    period = dict(start_date="2025-01-01", end_exclusive="2026-01-01")
    for index, query in config["queries"].items():
        if query["gate"] != "enabled":
            continue
        sql, _, _, _ = render(config, index, period if query["mode"] == "template" else {})
        assert sql.lstrip()[:6].lower() in {"with _", "select"} or sql.lstrip().lower().startswith("with"), index


# ---- resolve_scope ----------------------------------------------------------

def test_scope_routes_from_the_card_clause_first():
    run, _ = _run(handoff_context=_risk_handoff())
    scope = run.resolve_scope({})
    assert scope["status"] == "ok"
    assert scope["activity"]["code"] == "BA02" and scope["activity"]["process"] == "PR02"
    assert scope["primary"]["code"] == "RK02" and scope["primary"]["source"] == "卡片条款"
    assert [a["code"] for a in scope["anchors"]] == ["RK02", "RK01"]
    assert scope["period"] == dict(start="2025-01-01", endExclusive="2026-01-01", observedDate="2025-11-14",
                                   source="卡片筛选", semantics=scope["period"]["semantics"])
    assert scope["versions"]["ontology"] == "亿纬锂能_流程360全局本体_无投标_V1.0"
    assert scope["budget"]["maxQueries"] == 12


def test_a_card_only_code_is_not_forced_onto_the_global_ontology():
    context = handoff.normalise(dict(kind="issue", period="2025",
                                     clause=dict(code="IS01", title="销售额达成低于目标")))
    run, _ = _run(handoff_context=context)
    scope = run.resolve_scope({})
    # IS01 is the 共同问题 card's own code: only candidates by name are offered.
    assert scope["status"] == "needs_clarification"
    candidates = scope["unresolved"][0]["candidates"]
    assert dict(kind="risks", code="RK-GG01", name="销售额达成低于目标") in candidates
    confirmed = run.resolve_scope(dict(anchor_codes=["RK-GG01"]))
    assert confirmed["status"] == "ok" and confirmed["activity"]["code"] == "BA00"


def test_scope_without_a_period_asks_for_one_and_flags_a_reopened_period():
    run, _ = _run()
    assert run.resolve_scope(dict(anchor_codes=["RK-GD01"]))["status"] == "needs_period"
    run, _ = _run(handoff_context=_risk_handoff(period="2025"))
    reopened = run.resolve_scope(dict(year="2024"))
    assert reopened["period"]["start"] == "2024-01-01"
    assert any("重开分析" in note for note in reopened["notes"])


# ---- get_subgraph -----------------------------------------------------------

def test_risk_subgraph_follows_the_chain_by_codes():
    run, _ = _run(handoff_context=_risk_handoff())
    run.resolve_scope({})
    result = run.get_subgraph({})
    graph = result["subgraph"]
    assert graph["anchor"]["code"] == "RK02" and graph["rule"]["code"] == "BR-A02"
    assert [c["code"] for c in graph["candidateCauses"]] == ["RC01", "RC06", "RC07", "RC08"]
    rc01 = graph["candidateCauses"][0]
    assert rc01["evidence"]["required"] and rc01["recheck"]["metrics"] == ["C01", "R04"]
    assert rc01["advice"][0]["code"] == "AC01" and rc01["advice"][0]["role"]
    indexes = {q["index"] for q in result["queries"]}
    assert {"T005", "T004", "T003"} <= indexes
    assert all("sql" not in q for q in result["queries"])
    assert "ER-G032" in result["candidateRelations"]
    assert all(r["enabled"] for r in result["relations"])


def test_metric_subgraph_looks_up_rules_and_risks():
    run, _ = _run()
    graph = run.get_subgraph(dict(code="R03"))["subgraph"]
    assert graph["anchor"]["kind"] == "metric"
    assert "RK02" in {risk["code"] for risk in graph["risks"]}


# ---- execute_query ----------------------------------------------------------

def test_queries_need_a_scope_and_must_belong_to_its_subgraph():
    run, database = _run(handoff_context=_risk_handoff())
    assert run.execute_query(dict(query_index="T005"))["status"] == "rejected"
    run.resolve_scope({})
    outside = run.execute_query(dict(query_index="Q031"))   # a delivery query
    assert outside["status"] == "rejected" and "子图" in outside["message"]
    assert not database.calls


def test_a_registered_query_returns_evidence_with_its_hash_and_period(config):
    run, database = _run(handoff_context=_risk_handoff())
    run.resolve_scope({})
    result = run.execute_query(dict(query_index="T005", purpose="核对签单进度"))
    assert result["status"] == "ok" and result["evidenceId"] == "E001"
    assert result["sha256"] == config["queries"]["T005"]["sha256"]
    assert result["parameters"] == dict(start_date="2025-01-01", end_exclusive="2026-01-01",
                                        observed_date="2025-11-14")
    assert result["budgetUsed"] == 1 and result["budgetLeft"] == 11
    assert "DATE '2025-01-01' AS start_date" in database.calls[0][0]
    assert run.evidence["E001"]["queryIndex"] == "T005"


def test_mock_pending_and_unknown_queries_are_blocked_without_touching_the_database():
    run, database = _run()
    run.resolve_scope(dict(anchor_codes=["RK-GF02"], year="2025"))
    blocked = run.execute_query(dict(query_index="Q029"))
    assert blocked["status"] == "blocked" and blocked["gate"] == "mock" and "MOCK" in blocked["message"]
    assert run.execute_query(dict(query_index="Q999"))["status"] == "rejected"
    assert not database.calls


def test_result_quality_keeps_empty_zero_and_incomplete_apart():
    for rows, truncated, expected in (([], False, "empty"), ([dict(a=1)], True, "incomplete")):
        run, _ = _run(FakeDatabase(rows=rows, truncated=truncated), _risk_handoff())
        run.resolve_scope({})
        assert run.execute_query(dict(query_index="T005"))["status"] == expected
    run, _ = _run(FakeDatabase(error=RuntimeError("canceling statement due to statement timeout")), _risk_handoff())
    run.resolve_scope({})
    assert run.execute_query(dict(query_index="T005"))["status"] == "timeout"


def test_the_query_budget_stops_the_branch():
    run, database = _run(handoff_context=_risk_handoff())
    run.resolve_scope({})
    for _ in range(12):
        assert run.execute_query(dict(query_index="T005"))["status"] == "ok"
    assert run.execute_query(dict(query_index="T005"))["status"] == "budget_exhausted"
    assert len(database.calls) == 12
    run.resolve_scope({})   # a new scope starts a new budget
    assert run.execute_query(dict(query_index="T005"))["status"] == "ok"


# ---- drill_relation ---------------------------------------------------------

def _delivery_run():
    def rows(sql):
        if "p_fm_edw_v_ods_crm_salesorderdetail" in sql or '"salesorderid"::text = ANY' in sql:
            return [dict(salesorderid="so-1", quantity=5), dict(salesorderid="so-1", quantity=7)]
        return [dict(order_id="so-1", order_number="SO2025001")]
    database = FakeDatabase(rows=rows)
    run, _ = _run(database)
    run.resolve_scope(dict(anchor_codes=["RK-GD01"], year="2025"))
    run.get_subgraph({})
    return run, database


def test_drill_uses_only_accepted_relations_and_keys_from_the_evidence():
    run, database = _delivery_run()
    evidence = run.execute_query(dict(query_index="Q031"))["evidenceId"]
    result = run.drill_relation(dict(relation_code="ER06", direction="forward", from_evidence=evidence,
                                     source_keys=["so-1"], fields=["salesorderid", "quantity"]))
    assert result["status"] == "ok" and result["depth"] == 1 and result["entity"] == "LE08"
    assert result["match"] == dict(sourceKeys=1, matchedKeys=1, unmatchedKeys=0, rows=2, rowsPerMatchedKey=2.0)
    assert any("一对多" in note for note in result["notes"])
    sql, params = database.calls[-1]
    assert params == dict(keys=["so-1"]) and '"salesorderid"::text = ANY(%(keys)s)' in sql
    # A key that is not in the source evidence, a candidate relation, an unknown field.
    assert run.drill_relation(dict(relation_code="ER06", from_evidence=evidence, source_keys=["so-9"],
                                   fields=["quantity"]))["status"] == "rejected"
    assert run.drill_relation(dict(relation_code="ER-G032", from_evidence=evidence, source_keys=["so-1"],
                                   fields=["quantity"]))["status"] == "blocked"
    assert run.drill_relation(dict(relation_code="ER06", from_evidence=evidence, source_keys=["so-1"],
                                   fields=["no_such_field; drop"]))["status"] == "rejected"


def test_drill_stops_at_three_hops():
    run, _ = _delivery_run()
    evidence = run.execute_query(dict(query_index="Q031"))["evidenceId"]
    for depth in (1, 2, 3):
        result = run.drill_relation(dict(relation_code="ER06", from_evidence=evidence, source_keys=["so-1"],
                                         fields=["salesorderid", "quantity"]))
        assert result["depth"] == depth
        evidence = result["evidenceId"]
    assert run.drill_relation(dict(relation_code="ER06", from_evidence=evidence, source_keys=["so-1"],
                                   fields=["quantity"]))["status"] == "budget_exhausted"


# ---- evaluate_and_record ----------------------------------------------------

def test_established_and_not_hit_need_evidence_of_this_run():
    run, _ = _run(handoff_context=_risk_handoff())
    run.resolve_scope({})
    assert run.evaluate_and_record(dict(code="RK02", assessment_status="成立"))["status"] == "rejected"
    assert run.evaluate_and_record(dict(code="RK02", assessment_status="成立",
                                        evidence_ids=["E777"]))["status"] == "rejected"
    evidence = run.execute_query(dict(query_index="T005"))["evidenceId"]
    recorded = run.evaluate_and_record(dict(code="RK02", assessment_status="成立", evidence_ids=[evidence],
                                            basis="金额口径覆盖率低于时间进度"))
    assert recorded["status"] == "recorded" and recorded["record"]["isEstablished"] is True
    assert recorded["record"]["rule"] == "BR-A02" and recorded["record"]["evidenceIds"] == [evidence]


def test_undecided_states_are_recorded_as_unknown_with_their_reason():
    run, _ = _run(handoff_context=_risk_handoff())
    run.resolve_scope({})
    assert run.evaluate_and_record(dict(code="RC01", assessment_status="无法判定", basis="缺数据"))["status"] == "rejected"
    undecided = run.evaluate_and_record(dict(code="RC01", assessment_status="无法判定", basis="缺需求确认记录",
                                             missing_inputs=["需求输入审批时间"]))
    assert undecided["record"]["isEstablished"] is None
    assert undecided["record"]["missingInputs"] == ["需求输入审批时间"]
    pending = run.evaluate_and_record(dict(code="RC06", assessment_status="待核实", basis="C08 低于阈值但分母待核"))
    assert pending["record"]["isEstablished"] is None
    assert run.evaluate_and_record(dict(code="RC07", assessment_status="可能成立"))["status"] == "rejected"
    assert run.evaluate_and_record(dict(code="IS01", assessment_status="未评估"))["status"] == "rejected"


def test_truncated_evidence_cannot_establish_a_conclusion():
    run, _ = _run(FakeDatabase(truncated=True), _risk_handoff())
    run.resolve_scope({})
    evidence = run.execute_query(dict(query_index="T005"))["evidenceId"]
    assert run.evaluate_and_record(dict(code="RK02", assessment_status="未命中",
                                        evidence_ids=[evidence]))["status"] == "rejected"


# ---- draft_and_recheck ------------------------------------------------------

def test_advice_is_a_measure_only_for_an_established_cause():
    run, _ = _run(handoff_context=_risk_handoff())
    run.resolve_scope({})
    evidence = run.execute_query(dict(query_index="T005"))["evidenceId"]
    run.evaluate_and_record(dict(code="RC01", assessment_status="成立", evidence_ids=[evidence], basis="C01 > 0"))
    run.evaluate_and_record(dict(code="RC06", assessment_status="待核实", basis="分母待核"))
    run.evaluate_and_record(dict(code="RC07", assessment_status="未命中", evidence_ids=[evidence]))
    result = run.draft_and_recheck(dict(cause_codes=["RC01", "RC06", "RC07", "RC08"]))
    by_cause = {draft["causeCode"]: draft for draft in result["drafts"]}
    assert by_cause["RC01"]["type"] == "改进措施" and by_cause["RC01"]["role"]
    assert by_cause["RC01"]["recheck"]["metrics"] == ["C01", "R04"] and by_cause["RC01"]["evidenceIds"] == [evidence]
    assert by_cause["RC06"]["type"] == "核查措施" and by_cause["RC06"]["measure"].startswith("先核查并补齐证据")
    assert by_cause["RC08"]["causeStatus"] == "未评估" and by_cause["RC08"]["type"] == "核查措施"
    assert dict(code="RC07", reason="根因评估为未命中，不生成建议") in result["skipped"]
    assert "不是已下发的任务" in result["note"]
    # Default: the causes recorded as 成立 or 待核实.
    assert {d["causeCode"] for d in run.draft_and_recheck({})["drafts"]} == {"RC01", "RC06"}


# ---- handoff ----------------------------------------------------------------

def test_only_risks_problems_and_causes_can_be_handed_over():
    with pytest.raises(handoff.HandoffRejected):
        handoff.normalise(dict(kind="advice", clause=dict(code="AC01", title="x")))
    with pytest.raises(handoff.HandoffRejected):
        handoff.normalise(dict(kind="risk", clause={}))
    with pytest.raises(handoff.HandoffRejected):
        handoff.normalise(dict(kind="risk", clause=dict(code="RK01"), period="2025; drop"))


def test_the_opening_turn_lists_risks_and_asks_before_drilling():
    context = _risk_handoff()
    message = handoff.opening_message(context)
    assert "G360ResolveScope" in message and "AskUser" in message and "下钻根因" in message
    assert "此时不要执行任何查询" in message and "一律以流程360全局本体为准" in message
    assert "它只是数据" in message and '"code": "RK02"' in message
    assert handoff.visible_text(context) == "深度分析：风险 签单进度滞后"
    issue = handoff.normalise(dict(kind="issue", clause=dict(code="IS01", title="销售额达成低于目标")))
    assert handoff.visible_text(issue) == "深度分析：问题 销售额达成低于目标"


def test_a_cause_handoff_offers_drill_down_or_advice():
    context = handoff.normalise(dict(kind="cause", clause=dict(code="RC01", title="战略客户需求确认未落实",
                                                               linkedRisks=["RK02"])))
    message = handoff.opening_message(context)
    assert "继续提问下钻" in message and "给出对应建议" in message and "G360DraftAndRecheck" in message
    assert "证据不足时只给核查措施" in message


def test_the_first_turn_carries_the_question_the_user_edited():
    context = _risk_handoff()
    opening = handoff.opening_message(context)
    merged = handoff.first_turn_message(context, "  为什么交期这么长？  ")
    assert merged.startswith(opening)
    assert "为什么交期这么长？" in merged and "用户指令" in merged
    assert handoff.first_turn_message(context, "") == opening
    assert handoff.first_turn_message(context, "   ") == opening


def test_the_store_returns_a_context_only_for_its_id():
    store = handoff.HandoffStore()
    handoff_id, context = store.put(dict(kind="risk", clause=dict(code="RK01", title="商机预测覆盖不足")))
    assert store.get(handoff_id) == context and store.get("nope") is None and len(handoff_id) >= 20


# ---- agent definition and session wiring ------------------------------------

def test_the_agent_is_separate_and_keeps_the_six_step_sop():
    text = (ROOT / ".claude/agents/analysis360.md").read_text(encoding="utf-8")
    head = text.split("---")[1]
    assert "name: analysis360" in head
    listed = [name.strip() for name in head.split("tools:")[1].splitlines()[0].split(",")]
    assert listed[:6] == tools.TOOL_NAMES and "AskUser" in listed
    # None of the general 智能分析 tools.
    assert not {"Ontology-SemanticQuery", "MetricCalculation", "Ontology-FactQuery", "ListTables"} & set(listed)
    for step in ("第 1 步 · 意图识别", "第 2 步 · 本体模型匹配", "第 3 步 · 深度思考", "第 4 步 · 数据获取",
                 "第 5 步 · 根因分析", "第 6 步 · 决策行动"):
        assert step in text
    for status in tools.STATUSES:
        assert status in text
    assert "你是储能业务销售运营分析师" in text and "不是你的分析本体" in text


def test_the_strategy_tools_drive_the_sop_steps():
    from bi_agent.runtime import session
    steps = {name: session._SOP_TOOL_STEP[name][0] for name in tools.TOOL_NAMES}
    assert steps == dict(G360ResolveScope=1, G360GetSubgraph=2, G360ExecuteQuery=4, G360DrillRelation=4,
                         G360EvaluateAndRecord=5, G360DraftAndRecheck=6)


def test_tool_schemas_never_accept_sql():
    for schema in tools.schemas():
        properties = schema["input_schema"]["properties"]
        assert "sql" not in properties and "table" not in properties
    assert json.loads(tools.unbound_executor({}))["status"] == "unavailable"


class TestHandoffEndpoints:
    def setup_method(self):
        from fastapi.testclient import TestClient
        from open_claude.agent_def import AgentDef, get_agent_def_registry
        from bi_agent.concurrency import reset_limits, reset_resources
        from bi_agent.ontology.store import OntologyStore
        from bi_agent.web import app as web
        reset_limits()
        reset_resources()
        self.web = web
        self.tmp = tempfile.mkdtemp()
        registry = get_agent_def_registry()
        registry._defs["bi-analyst"] = AgentDef("bi-analyst", tools=[])
        with patch("bi_agent.web.app.OntologyStore.from_xlsx", return_value=OntologyStore()):
            web.configure(self.tmp, self.tmp, self.tmp, agent_name="bi-analyst")
        registry._defs["analysis360"] = AgentDef("analysis360", tools=tools.TOOL_NAMES + ["AskUser"])
        self.client = TestClient(web.app)

    def teardown_method(self):
        from bi_agent.concurrency import AdmissionController, SessionSlotRegistry, get_limits, reset_limits, reset_resources
        for key in list(os.environ):
            if key.startswith("CHATBI_"):
                os.environ.pop(key, None)
        reset_limits()
        reset_resources()
        self.web.STATE.admission = AdmissionController(get_limits())
        self.web.STATE.session_slots = SessionSlotRegistry()

    def _chat(self, body, path="/api/chat"):
        def script(messages, system_prompt, allowed_tools=None, **kwargs):
            self.seen = dict(messages=messages, system=system_prompt, tools=allowed_tools)
            yield {"type": "text", "text": "好的"}
            yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}
        with patch("bi_agent.web.session.stream_message", side_effect=script):
            return self.client.post(path, json=body)

    def _handoff(self):
        response = self.client.post("/api/analysis360/handoff", json=dict(
            kind="risk", period="2025", clause=dict(code="RK02", title="签单进度滞后", description="落后 12.3 个百分点")))
        assert response.status_code == 200
        return response.json()

    def test_a_card_clause_is_stored_and_read_back(self):
        created = self._handoff()
        assert created["prompt"] == "深度分析：风险 签单进度滞后"
        read = self.client.get(f"/api/analysis360/handoff/{created['id']}").json()
        assert read["kind"] == "risk" and read["clause"]["code"] == "RK02" and read["period"] == "2025"
        assert self.client.get("/api/analysis360/handoff/unknown").status_code == 404
        rejected = self.client.post("/api/analysis360/handoff", json=dict(kind="advice", clause=dict(code="AC01")))
        assert rejected.status_code == 400

    def test_the_first_turn_makes_the_session_a_360_session(self):
        created = self._handoff()
        response = self._chat(dict(message="深度分析", session_id="tab-360", analysis360_handoff=created["id"]))
        assert response.status_code == 200
        session = self.web.STATE.sessions["tab-360"]
        assert session.agent_def.name == "analysis360"
        assert session.analysis360_run.handoff["clause"]["code"] == "RK02"
        first = session.messages[0]["content"]
        first = first if isinstance(first, str) else json.dumps(first, ensure_ascii=False)
        assert "360 深度分析交接" in first and "下钻根因" in first
        assert "360 智能分析" in self.seen["system"]
        # Later turns of the tab stay on the 360 session; other tabs do not.
        self._chat(dict(message="下钻根因", session_id="tab-360"))
        assert self.web.STATE.sessions["tab-360"] is session
        self._chat(dict(message="你好", session_id="tab-general"))
        assert self.web.STATE.sessions["tab-general"].agent_def.name == "bi-analyst"

    def test_the_edited_dialog_question_reaches_the_agent(self):
        created = self._handoff()
        question = "深度分析「签单进度滞后」根因，先看华东区域"
        response = self._chat(dict(message=question, visible_user_text=question,
                                   session_id="tab-dialog", analysis360_handoff=created["id"]))
        assert response.status_code == 200
        session = self.web.STATE.sessions["tab-dialog"]
        first = session.messages[0]["content"]
        first = first if isinstance(first, str) else json.dumps(first, ensure_ascii=False)
        assert "360 深度分析交接" in first and question in first
        prompt = json.dumps(self.seen["messages"], ensure_ascii=False)
        assert question in prompt, "the edited question must be in the model prompt too"

    def test_customer_entry_has_a_360_only_chat_route(self):
        refused = self._chat(dict(message="通用问题", session_id="general-only"), path="/api/analysis360/chat")
        assert refused.status_code == 403
        created = self._handoff()
        first = self._chat(dict(message="深度分析", session_id="customer-360",
                                analysis360_handoff=created["id"]), path="/api/analysis360/chat")
        assert first.status_code == 200
        assert self.web.STATE.sessions["customer-360"].agent_def.name == "analysis360"
        later = self._chat(dict(message="下钻根因", session_id="customer-360"), path="/api/analysis360/chat")
        assert later.status_code == 200
        assert self.web.STATE.sessions["customer-360"].agent_def.name == "analysis360"

    def test_a_reaped_or_new_conversation_stays_360_and_an_expired_handoff_is_refused(self):
        created = self._handoff()
        self._chat(dict(message="深度分析", session_id="tab-360", analysis360_handoff=created["id"]))
        self.web.STATE.sessions.pop("tab-360")           # idle reaping
        self._chat(dict(message="继续", session_id="tab-360"))
        rebuilt = self.web.STATE.sessions["tab-360"]
        assert rebuilt.agent_def.name == "analysis360" and rebuilt.analysis360_run.handoff["clause"]["code"] == "RK02"
        with self.web.STATE.registry_lock:
            self.web.STATE.sessions.pop("tab-360")
            self.web._ANALYSIS360_SESSIONS["tab-360"] = {}   # what a new conversation leaves behind
        self._chat(dict(message="新问题", session_id="tab-360"))
        fresh = self.web.STATE.sessions["tab-360"]
        assert fresh.agent_def.name == "analysis360" and fresh.analysis360_run.handoff is None
        refused = self._chat(dict(message="深度分析", session_id="tab-x", analysis360_handoff="expired"))
        assert refused.status_code == 400
