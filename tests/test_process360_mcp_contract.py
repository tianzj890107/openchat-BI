from __future__ import annotations

import json

import pytest

from bi_agent.process360 import tools
from bi_agent.web import mcp_endpoint


def test_process360_schemas_never_expose_principal() -> None:
    for spec in tools.SPECS:
        properties = spec["input_schema"].get("properties", {})
        assert "principal" not in properties, spec["name"]
        assert "principal" not in spec["input_schema"].get("required", [])


def test_process360_tools_reject_model_supplied_principal() -> None:
    runtime = mcp_endpoint.McpRuntime(
        get_source=lambda: None,
        build_doris=lambda *args, **kwargs: None,
        get_cwd=lambda: ".",
        executor_factory=lambda source: {},
    )
    with pytest.raises(ValueError, match="resolved by the server"):
        runtime.call_tool("Process360Route", {"question": "经营情况怎么样", "principal": {"tenantId": "t", "userId": "u"}})


def test_process360_runtime_injects_server_principal(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def executor(params, cwd):
        from bi_agent.process360.identity import active_principal_payload
        seen.update(active_principal_payload() or {})
        return "{}"

    runtime = mcp_endpoint.McpRuntime(
        get_source=lambda: None,
        build_doris=lambda *args, **kwargs: None,
        get_cwd=lambda: ".",
        executor_factory=lambda source: {},
        exposed_tools=("Process360Query",),
        principal_provider=lambda: {"tenantId": "poc", "userId": "readonly", "grantKind": "all"},
    )
    runtime._source_free["Process360Query"] = executor
    runtime.call_tool("Process360Query", {"scenario": "SC01"})
    assert seen["tenantId"] == "poc"
    assert seen["userId"] == "readonly"
    assert seen["grantKind"] == "all"


def test_task_order_create_uses_trusted_draft_and_ignores_caller_content(monkeypatch) -> None:
    calls = {}

    class Service:
        def __init__(self, *, cwd):
            calls["cwd"] = cwd

        def execute_draft(self, **kwargs):
            calls.update(kwargs)
            return {"status": "ok", "draftId": kwargs["draft_id"], "actionId": kwargs["action_id"]}

    monkeypatch.setattr(mcp_endpoint.process360_tools, "Process360Service", Service)
    monkeypatch.setattr(mcp_endpoint, "FuxiTodoClient", lambda: object())
    output = mcp_endpoint._task_order_executor()(
        {
            "draft_id": "draft-1",
            "draft_hash": "hash-1",
            "action_id": "SC01-TK01",
            "title": "调用方篡改标题",
            "content": "调用方篡改正文",
            "recipients_raw": ["13800000001"],
            "principal": {"tenantId": "t1", "userId": "u1", "canDispatch": True},
        },
        "/tmp/project",
    )
    assert json.loads(output)["status"] == "ok"
    assert calls["draft_id"] == "draft-1"
    assert calls["draft_hash"] == "hash-1"
    assert calls["principal"]["userId"] == "u1"
    assert "title" not in calls
    assert "content" not in calls


def test_process360_metadata_cannot_use_legacy_dispatch_without_draft() -> None:
    with pytest.raises(ValueError, match="draft_id"):
        mcp_endpoint._task_order_executor()(
            {
                "action_id": "SC01-TK01",
                "title": "核查",
                "content": "核查",
                "recipients_raw": ["13800000001"],
                "caliber_meta": {"scenario": "SC01", "dispatchTool": "TaskOrderCreate"},
            },
            ".",
        )


def test_all_process360_mcp_tools_are_exposed() -> None:
    for name in tools.EXECUTORS:
        assert name in mcp_endpoint.DEFAULT_EXPOSED_TOOLS


def test_render_tools_are_registered_and_invocable() -> None:
    runtime = mcp_endpoint.McpRuntime(
        get_source=lambda: None,
        build_doris=lambda *args, **kwargs: None,
        get_cwd=lambda: ".",
        executor_factory=lambda source: {},
        exposed_tools=("TableGenerate", "ChartGenerate", "ChartGenerateMultiDim"),
    )
    assert runtime.missing_executors() == ()

    table = runtime.call_tool(
        "TableGenerate",
        {
            "title": "测试表",
            "columns": [{"key": "a", "label": "A"}],
            "rows": [{"a": 1}],
        },
    )
    assert "<TABLE_SPEC>" in table or "TABLE_SPEC" in table

    chart = runtime.call_tool(
        "ChartGenerate",
        {
            "chart_type": "bar",
            "title": "测试图",
            "series": [{"name": "S", "data": [1, 2]}],
            "x_axis": ["a", "b"],
        },
    )
    assert "CHART_SPEC" in chart
