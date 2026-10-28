from __future__ import annotations

import json
from pathlib import Path

from bi_agent.process360 import audit
from bi_agent.process360.catalog import Process360Catalog
from bi_agent.process360.models import envelope, gap
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
NO_DISPATCH = {
    "tenantId": "t1",
    "userId": "u1",
    "grantKind": "all",
    "authorizationVersion": "auth-v1",
    "canDispatch": False,
}


def _call_tool(runtime: mcp_endpoint.McpRuntime, name: str, params: dict) -> dict:
    return json.loads(
        runtime.call_tool(
            name,
            params,
            conversation_id="conv-1",
            request_id=f"request-{name}",
        )
    )


def test_legacy_task_order_branch_requires_dispatch_permission(monkeypatch) -> None:
    class Client:
        def __init__(self) -> None:
            self.calls = 0

        def create_todo(self, **_kwargs):
            self.calls += 1
            raise AssertionError("dispatch must not reach Fuxi without canDispatch")

    client = Client()
    monkeypatch.setattr(mcp_endpoint, "FuxiTodoClient", lambda: client)
    token = set_request_context(
        resolve_request_context(
            principal=NO_DISPATCH,
            request_id="legacy-dispatch",
            surface="mcp",
        )
    )
    try:
        output = mcp_endpoint._task_order_executor()(
            {
                "action_id": "legacy-1",
                "title": "跟进回款",
                "content": "复核逾期原因",
                "recipients_raw": ["18800000001"],
            },
            str(ROOT),
        )
    finally:
        reset_request_context(token)
    result = json.loads(output)
    assert result["status"] == "blocked"
    assert result["accepted"] is False
    assert "DISPATCH_NOT_AUTHORIZED" in {item["code"] for item in result["gaps"]}
    assert client.calls == 0


def test_not_applicable_step_is_skipped_and_cannot_unlock_a_dependency(
    tmp_path: Path, monkeypatch
) -> None:
    store_path = tmp_path / "runtime.sqlite3"
    monkeypatch.setenv("PROCESS360_STORE_PATH", str(store_path))
    monkeypatch.setattr(audit, "_STORE", None)
    svc = Process360Service(
        catalog=Process360Catalog.from_project(ROOT),
        db=FakeDB(),
        store=Process360Store(store_path),
        cwd=ROOT,
    )
    planned = svc.plan(
        question="本月超期未发多少，为什么增加",
        scenario="SC01",
        scope={"periodEnd": "2026-10-27"},
        principal={**NO_DISPATCH, "canDispatch": True},
    )
    query_step = next(step for step in planned["steps"] if step["sop"] == "P03")
    analyze_step = next(step for step in planned["steps"] if step["sop"] == "P09")
    calls: list[str] = []

    def stub(params, _cwd):
        calls.append(str(params.get("scenario") or ""))
        return json.dumps({"status": "not_applicable", "scenario": params.get("scenario")})

    runtime = mcp_endpoint.McpRuntime(
        get_source=lambda: None,
        build_doris=lambda *args, **kwargs: None,
        get_cwd=lambda: str(ROOT),
        executor_factory=lambda source: {},
        exposed_tools=("Process360Query", "Process360Analyze"),
        principal_provider=lambda: {**NO_DISPATCH, "canDispatch": True},
    )
    runtime._source_free["Process360Query"] = stub
    runtime._source_free["Process360Analyze"] = stub

    skipped = _call_tool(
        runtime,
        "Process360Query",
        {"scenario": "SC01", "planId": planned["planId"], "stepId": query_step["id"]},
    )
    assert skipped["status"] == "not_applicable"
    rows = svc.store.list_plan_steps(planned["planId"])
    assert next(row for row in rows if row["step_id"] == query_step["id"])["status"] == "skipped"

    blocked = _call_tool(
        runtime,
        "Process360Analyze",
        {"scenario": "SC01", "planId": planned["planId"], "stepId": analyze_step["id"]},
    )
    assert blocked["status"] == "needs_clarification"
    assert "PLAN_DEPENDENCY_PENDING" in {item["code"] for item in blocked["gaps"]}
    assert len(calls) == 1


def test_blocked_query_keeps_its_source_connection_and_scope(tmp_path: Path, monkeypatch) -> None:
    svc = Process360Service(
        catalog=Process360Catalog.from_project(ROOT),
        db=object(),
        store=Process360Store(tmp_path / "runtime.sqlite3"),
        cwd=ROOT,
    )
    monkeypatch.setattr(svc, "_db_ready", lambda: (True, ""))

    def blocked(code, scope):
        return envelope(
            "S03",
            "blocked",
            catalog_id=svc.catalog_id,
            catalog_version=svc.catalog_version,
            scenario=code,
            scope=scope,
            gaps=[
                gap(
                    "PLAN_CLASSIFICATION_UNKNOWN",
                    "计划分类不完整",
                    needed="补齐计划分类",
                    impact="不发布正式汇总",
                    severity="blocking",
                    source="runtime",
                )
            ],
        )

    monkeypatch.setattr(svc, "_run_scenario_snapshot", blocked)
    result = svc.query("SC05", scope={"periodEnd": "2026-10-27"}, principal={
        "tenantId": "t1",
        "userId": "u1",
        "grantKind": "all",
        "authorizationVersion": "auth-v1",
    })
    assert result["status"] == "blocked"
    assert result["dataSource"] == "process360-postgres"
    assert result["sourceConnection"] == "database:test"
    assert result["scope"]["periodEnd"] == "2026-10-27"
