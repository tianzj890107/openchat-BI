from __future__ import annotations

import json

import pytest

from bi_agent.process360 import tools
from bi_agent.web import mcp_endpoint


def test_process360_data_tools_require_host_principal() -> None:
    with pytest.raises(ValueError, match="required"):
        tools.EXECUTORS["Process360Query"]({"scenario": "SC01"}, ".")
    with pytest.raises(ValueError, match="required"):
        tools.EXECUTORS["Process360Plan"]({"question": "经营情况怎么样"}, ".")


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
