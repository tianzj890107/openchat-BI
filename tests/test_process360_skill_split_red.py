"""Two-skill separation: 智能分析 (general) vs 360智能分析 (Process360 / ywln).

MCP cannot carry a skill id on ``tools/call``, so the separation is enforced by
connection: each connector gets its own tool whitelist, and ``AnalysisRoute``
hands every SC01-SC05 question over instead of querying procurement Doris.
"""

from __future__ import annotations

import json

import pytest

from bi_agent.process360.router import delivery_requirement, strong_scenario
from bi_agent.web import mcp_endpoint


SC05_QUESTION = (
    "计划外发货偏差分析，哪些发货偏离日计划、如何核查、后续是否改善？发风险和待办"
)


def _route(question: str, tools):
    executor = mcp_endpoint._route_executor(tuple(tools))
    return json.loads(executor({"question": question}, "."))


def test_analysis_route_refuses_sc05_with_procurement_doris() -> None:
    decision = _route(SC05_QUESTION, mcp_endpoint.DEFAULT_EXPOSED_TOOLS)
    assert decision["mode"] == "PROCESS360_REQUIRED"
    assert decision["next_step"] == "PROCESS360_ROUTE"
    assert decision["required_tools"] == ["Process360Route"]
    assert decision["skill"] == "process360-analytics"
    assert decision["scenario"] == "SC05"
    assert decision["dataSource"] == "process360-postgres"
    assert decision["dataChain"] == "ywln"
    assert "MetricQuery" not in json.dumps(decision["required_tools"])


def test_analysis_route_marks_risk_and_todo_as_action_delivery() -> None:
    decision = _route(SC05_QUESTION, mcp_endpoint.DEFAULT_EXPOSED_TOOLS)
    assert decision["delivery"] == {
        "kind": "action_cards",
        "actionRequired": True,
        "sopId": "P11",
    }


def test_analysis_route_keeps_general_questions_on_doris() -> None:
    for question in ("2025年采购金额合计是多少", "本月发货金额是多少"):
        decision = _route(question, mcp_endpoint.DEFAULT_EXPOSED_TOOLS)
        assert decision["mode"] == "FACT_QUERY", question
        assert decision["next_step"] == "QUERY_DORIS", question
        assert "Process360Route" not in decision["required_tools"], question


def test_analysis_route_asks_to_switch_connector_without_process360() -> None:
    decision = _route(SC05_QUESTION, mcp_endpoint.GENERAL_TOOL_PROFILE)
    assert decision["mode"] == "PROCESS360_REQUIRED"
    assert decision["next_step"] == "SWITCH_CONNECTOR"
    assert decision["required_tools"] == []
    assert "360智能分析连接器" in decision["instruction"]


def test_strong_scenario_threshold_keeps_weak_keywords_general() -> None:
    assert strong_scenario("哪些订单超期未发") == ("SC01", 12)
    assert strong_scenario("红区报价有多少") == ("SC02", 15)
    assert strong_scenario("本月发货金额是多少") is None
    assert strong_scenario("2025年采购金额合计是多少") is None


def test_risk_and_todo_wording_requires_a_server_draft() -> None:
    assert delivery_requirement(SC05_QUESTION)["required"] is True
    assert delivery_requirement(SC05_QUESTION)["sopId"] == "P11"
    assert delivery_requirement("哪些订单超期未发")["required"] is False


def test_skill_tool_profiles_are_isolated() -> None:
    general = set(mcp_endpoint.GENERAL_TOOL_PROFILE)
    process360 = set(mcp_endpoint.PROCESS360_TOOL_PROFILE)
    # Only the delivery tools are shared; the analysis entry points are not.

    assert not any(name.startswith("Process360") for name in general)
    assert not any(
        name in process360
        for name in ("AnalysisRoute", "MetricFactQuery", "ListBusinessObjects",
                     "Ontology-MetricQuery", "ChartGenerate", "TableGenerate")
    )
    assert "AnalysisRoute" in general and "AnalysisRoute" not in process360
    assert "Process360Route" in process360 and "Process360Route" not in general
    for tool in ("MetricFactQuery", "ListBusinessObjects", "Ontology-MetricQuery"):
        assert tool in general and tool not in process360
    for tool in ("CanvasGenerate", "RiskItemCreate", "TaskOrderCreate", "OutputGateCheck"):
        assert tool in general and tool in process360
    assert mcp_endpoint._configured_tools("general") == mcp_endpoint.GENERAL_TOOL_PROFILE
    assert mcp_endpoint._configured_tools("process360") == mcp_endpoint.PROCESS360_TOOL_PROFILE


def test_general_runtime_rejects_process360_tool() -> None:
    runtime = mcp_endpoint.McpRuntime(
        get_source=lambda: None,
        build_doris=lambda *args, **kwargs: None,
        get_cwd=lambda: ".",
        executor_factory=lambda source: {},
        exposed_tools=mcp_endpoint.GENERAL_TOOL_PROFILE,
    )
    with pytest.raises(PermissionError, match="tool_not_allowed"):
        runtime.call_tool("Process360Route", {"question": "哪些订单超期未发"})


def test_process360_runtime_rejects_general_analysis_tool() -> None:
    runtime = mcp_endpoint.McpRuntime(
        get_source=lambda: None,
        build_doris=lambda *args, **kwargs: None,
        get_cwd=lambda: ".",
        executor_factory=lambda source: {},
        exposed_tools=mcp_endpoint.PROCESS360_TOOL_PROFILE,
    )
    for name in ("AnalysisRoute", "MetricFactQuery", "ListBusinessObjects"):
        with pytest.raises(PermissionError, match="tool_not_allowed"):
            runtime.call_tool(name, {"question": "哪些订单超期未发"})


def test_process360_profile_lists_only_process360_tools() -> None:
    runtime = mcp_endpoint.McpRuntime(
        get_source=lambda: None,
        build_doris=lambda *args, **kwargs: None,
        get_cwd=lambda: ".",
        executor_factory=lambda source: {},
        exposed_tools=mcp_endpoint.PROCESS360_TOOL_PROFILE,
    )
    assert runtime.exposed == mcp_endpoint.PROCESS360_TOOL_PROFILE
