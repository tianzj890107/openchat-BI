from __future__ import annotations

import json
from pathlib import Path

from bi_agent.process360 import audit
from bi_agent.process360.catalog import Process360Catalog
from bi_agent.process360.request_context import (
    reset_request_context,
    resolve_request_context,
    set_request_context,
)
from bi_agent.process360.service import Process360Service
from bi_agent.process360.store import Process360Store
from bi_agent.web import mcp_endpoint
from tests.test_process360_engine import FakeDB

ROOT = Path(__file__).resolve().parents[1]
PRINCIPAL = {
    "tenantId": "t1",
    "userId": "u1",
    "grantKind": "all",
    "authorizationVersion": "auth-v1",
    "canDispatch": False,
}


def service(tmp_path: Path) -> Process360Service:
    return Process360Service(
        catalog=Process360Catalog.from_project(ROOT),
        db=FakeDB(),
        store=Process360Store(tmp_path / "runtime.sqlite3"),
        cwd=ROOT,
    )


def runtime(tmp_path: Path, monkeypatch, calls: list[dict]) -> mcp_endpoint.McpRuntime:
    monkeypatch.setenv("PROCESS360_STORE_PATH", str(tmp_path / "runtime.sqlite3"))
    monkeypatch.setattr(audit, "_STORE", None)

    def stub(params, cwd):
        calls.append(dict(params))
        return json.dumps({"status": "ok", "scenario": params.get("scenario") or "SC01"})

    rt = mcp_endpoint.McpRuntime(
        get_source=lambda: None,
        build_doris=lambda *args, **kwargs: None,
        get_cwd=lambda: str(ROOT),
        executor_factory=lambda source: {},
        exposed_tools=("Process360Query", "Process360Analyze"),
        principal_provider=lambda: PRINCIPAL,
    )
    rt._source_free["Process360Query"] = stub
    rt._source_free["Process360Analyze"] = stub
    return rt


def call(rt: mcp_endpoint.McpRuntime, tool: str, params: dict) -> dict:
    return json.loads(rt.call_tool(tool, params, conversation_id="conv-1", request_id="req-1"))


def test_public_mcp_requires_a_stored_plan_and_step(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict] = []
    rt = runtime(tmp_path, monkeypatch, calls)
    missing_plan = call(rt, "Process360Query", {"scenario": "SC01"})
    assert missing_plan["status"] == "needs_clarification"
    assert "PLAN_REQUIRED" in {item["code"] for item in missing_plan["gaps"]}
    assert calls == []

    svc = service(tmp_path)
    planned = svc.plan(
        question="本月超期未发为什么增加",
        scenario="SC01",
        scope={"periodEnd": "2026-10-27"},
        principal=PRINCIPAL,
    )
    query_step = next(step for step in planned["steps"] if step["sop"] == "P03")
    missing_step = call(
        rt,
        "Process360Query",
        {"scenario": "SC01", "planId": planned["planId"]},
    )
    assert "PLAN_STEP_REQUIRED" in {item["code"] for item in missing_step["gaps"]}
    assert calls == []

    allowed = call(
        rt,
        "Process360Query",
        {
            "scenario": "SC01",
            "planId": planned["planId"],
            "stepId": query_step["id"],
        },
    )
    assert allowed["status"] == "ok"
    assert len(calls) == 1
    analyze_step = next(step for step in planned["steps"] if step["sop"] == "P09")
    analyzed = call(
        rt,
        "Process360Analyze",
        {
            "scenario": "SC01",
            "planId": planned["planId"],
            "stepId": analyze_step["id"],
        },
    )
    assert analyzed["status"] == "ok"
    assert any(
        row["step_id"] == query_step["id"] and row["status"] == "completed"
        for row in svc.store.list_plan_steps(planned["planId"])
    )


def test_plan_step_rejects_wrong_tool_pending_dependency_and_scope_change(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[dict] = []
    rt = runtime(tmp_path, monkeypatch, calls)
    svc = service(tmp_path)
    planned = svc.plan(
        question="本月超期未发为什么增加",
        scenario="SC01",
        scope={"periodEnd": "2026-10-27"},
        principal=PRINCIPAL,
    )
    query_step = next(step for step in planned["steps"] if step["sop"] == "P03")
    analyze_step = next(step for step in planned["steps"] if step["sop"] == "P09")

    wrong_tool = call(
        rt,
        "Process360Query",
        {
            "scenario": "SC01",
            "planId": planned["planId"],
            "stepId": analyze_step["id"],
        },
    )
    assert "PLAN_TOOL_MISMATCH" in {item["code"] for item in wrong_tool["gaps"]}

    dependency = call(
        rt,
        "Process360Analyze",
        {
            "scenario": "SC01",
            "planId": planned["planId"],
            "stepId": analyze_step["id"],
        },
    )
    assert "PLAN_DEPENDENCY_PENDING" in {item["code"] for item in dependency["gaps"]}

    changed_scope = call(
        rt,
        "Process360Query",
        {
            "scenario": "SC01",
            "scope": {"periodEnd": "2026-10-26"},
            "planId": planned["planId"],
            "stepId": query_step["id"],
        },
    )
    assert "PLAN_SCOPE_MISMATCH" in {item["code"] for item in changed_scope["gaps"]}
    assert calls == []


def test_pending_clarification_blocks_business_steps(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict] = []
    rt = runtime(tmp_path, monkeypatch, calls)
    planned = service(tmp_path).plan(
        question="当前情况怎么样",
        scope={"periodEnd": "2026-10-27"},
        principal=PRINCIPAL,
    )
    step = planned["steps"][0]
    blocked = call(
        rt,
        "Process360Query",
        {"scenario": "SC01", "planId": planned["planId"], "stepId": step["id"]},
    )
    assert "PLAN_CLARIFICATION_PENDING" in {item["code"] for item in blocked["gaps"]}
    assert calls == []


def test_conversation_keeps_separate_request_trails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROCESS360_STORE_PATH", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(audit, "_STORE", None)
    for index in (1, 2):
        token = set_request_context(
            resolve_request_context(
                principal=PRINCIPAL,
                conversation_id="conv-1",
                request_id=f"req-{index}",
                surface="mcp",
            )
        )
        try:
            audit.ensure_request()
            audit.record_step("Process360Query", {"scenario": "SC01"}, {"status": "blocked"})
        finally:
            reset_request_context(token)
    store = audit.store()
    assert store.get_request("req-1", tenant="t1", principal="u1")
    assert store.get_request("req-2", tenant="t1", principal="u1")
    assert store.get_request("req-1", tenant="t1", principal="u2") is None
