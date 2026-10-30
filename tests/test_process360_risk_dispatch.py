from __future__ import annotations

import json
from pathlib import Path

import pytest

from bi_agent.integrations.fuxi_todo import FuxiTodoClient, FuxiTodoConfig
from bi_agent.process360 import audit, dispatch
from bi_agent.process360.catalog import Process360Catalog
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
    "canDispatch": True,
}


class CaptureFuxiClient(FuxiTodoClient):
    def __init__(self) -> None:
        super().__init__(FuxiTodoConfig(base_url="http://fuxi.test"))
        self.calls: list[tuple[str, dict]] = []

    def _post(self, path: str, payload: dict) -> dict:
        self.calls.append((path, payload))
        return {"applied": 1, "skipped": 0, "errors": []}


class ReceiptClient:
    def __init__(self) -> None:
        self.risk_calls: list[dict] = []
        self.todo_calls: list[dict] = []

    def create_risk(self, **kwargs):
        self.risk_calls.append(kwargs)
        return {
            "ok": True,
            "sourceTodoId": kwargs["source_todo_id"],
            "batchRef": "risk-batch-1",
            "applied": 1,
            "skipped": 0,
            "errors": [],
        }

    def create_todo(self, **kwargs):
        self.todo_calls.append(kwargs)
        return {
            "ok": True,
            "sourceTodoId": kwargs["source_todo_id"],
            "batchRef": "todo-batch-1",
            "applied": 1,
            "skipped": 0,
            "errors": [],
        }


def _service(tmp_path: Path) -> Process360Service:
    return Process360Service(
        catalog=Process360Catalog.from_project(ROOT),
        db=FakeDB(),
        store=Process360Store(tmp_path / "runtime.sqlite3"),
        cwd=ROOT,
    )


def test_fuxi_risk_item_uses_risk_type_and_independent_source_id() -> None:
    client = CaptureFuxiClient()
    result = client.create_risk(
        title="超期未发货风险",
        content="已观察事实；候选原因待验证。",
        recipients_raw=["18800000001"],
        action_id="SC01-RISK-RK01",
        canvas_id="draft-1",
        severity="HIGH",
        evidence=[{"type": "metric", "code": "M0337"}],
    )
    assert result["ok"] is True
    item = client.calls[0][1]["items"][0]
    assert item["itemType"] == "RISK"
    assert item["sourceTodoId"].startswith("analytics-risk-")
    assert item["category"] == "智能分析风险"
    assert item["activity"][0]["text"] == "智能分析生成风险条目"


def test_risk_tool_is_exposed_and_requires_a_trusted_draft(tmp_path: Path) -> None:
    assert "RiskItemCreate" in mcp_endpoint.DEFAULT_EXPOSED_TOOLS
    assert "RiskItemCreate" in mcp_endpoint.WRITE_TOOLS
    runtime = mcp_endpoint.McpRuntime(
        get_source=lambda: None,
        build_doris=lambda *_args, **_kwargs: None,
        get_cwd=str(tmp_path),
    )
    assert "RiskItemCreate" in runtime._source_free
    with pytest.raises(ValueError, match="requires draft_id"):
        mcp_endpoint._risk_item_executor()(
            {"action_id": "risk-without-draft", "recipients_raw": ["18800000001"]},
            str(tmp_path),
        )


def test_draft_exposes_independent_risk_and_todo_cards(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    bundle = svc.draft(scenario="SC01", principal=PRINCIPAL, owner_ref="u1", owner_name="owner-a")
    assert bundle["status"] == "ok"
    assert bundle["riskActions"] and bundle["canvasActions"]
    risk = bundle["riskActions"][0]
    todo = bundle["canvasActions"][0]
    assert risk["item_type"] == "RISK"
    assert risk["dispatchTool"] == "RiskItemCreate"
    assert risk["draftId"] == bundle["draftId"]
    assert "候选原因（待验证，不是已确认根因）" in risk["content"]
    assert "推送成功只表示 Fuxi 已接收" in risk["content"]
    assert todo["item_type"] == "TODO"
    assert todo["dispatchTool"] == "TaskOrderCreate"
    assert risk["id"] != todo["id"]
    assert set(bundle["dispatchTools"]) == {"RiskItemCreate", "TaskOrderCreate"}


def test_risk_and_todo_use_separate_idempotency_identities() -> None:
    risk_key = dispatch.execution_key("t1", "draft-1", "action-1", "RISK")
    todo_key = dispatch.execution_key("t1", "draft-1", "action-1", "TODO")
    assert risk_key != todo_key
    assert risk_key.endswith(":risk")


def test_risk_click_dispatches_risk_and_rejects_wrong_tool(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    bundle = svc.draft(scenario="SC01", principal=PRINCIPAL, owner_ref="u1", owner_name="owner-a")
    risk = bundle["riskActions"][0]
    client = ReceiptClient()
    wrong = dispatch.dispatch_action(
        svc,
        draft_id=bundle["draftId"],
        draft_hash=bundle["draftHash"],
        action_id=risk["id"],
        request_id="todo-tool",
        recipients=["18800000001"],
        principal=PRINCIPAL,
        client=client,
        item_type="TODO",
    )
    assert wrong["status"] == "blocked"
    assert wrong["gaps"][0]["code"] == "DISPATCH_ITEM_TYPE_MISMATCH"
    assert client.risk_calls == [] and client.todo_calls == []

    first = dispatch.dispatch_action(
        svc,
        draft_id=bundle["draftId"],
        draft_hash=bundle["draftHash"],
        action_id=risk["id"],
        request_id="risk-click",
        recipients=["18800000001"],
        principal=PRINCIPAL,
        client=client,
        item_type="RISK",
    )
    replay = dispatch.dispatch_action(
        svc,
        draft_id=bundle["draftId"],
        draft_hash=bundle["draftHash"],
        action_id=risk["id"],
        request_id="risk-replay",
        recipients=["18800000001"],
        principal=PRINCIPAL,
        client=client,
        item_type="RISK",
    )
    assert first["status"] == "ok" and first["itemType"] == "RISK"
    assert first["sourceTodoId"].startswith("analytics-risk-")
    assert replay["idempotentReplay"] is True
    assert len(client.risk_calls) == 1 and client.todo_calls == []


def test_canvas_renders_risk_and_todo_cards_with_distinct_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROCESS360_CANVAS_DISPATCH_MODE", "trusted")
    canvas = mcp_endpoint._canvas_tools()
    execute = canvas._make_canvas_generate()
    refs = {
        "draftId": "draft-1",
        "draftHash": "hash-1",
        "actionId": "",
        "approvalStatus": "host_click_authorized",
        "expiresAt": "2099-01-01T00:00:00Z",
    }
    output = execute({
        "title": "风险与待办",
        "conclusion": "结论：先推送风险，再发送处置任务。",
        "blocks": [{"kind": "actions", "params": {"items": [
            {
                **refs,
                "id": "SC01-RISK-RK01",
                "actionId": "SC01-RISK-RK01",
                "item_type": "RISK",
                "dispatchTool": "RiskItemCreate",
                "title": "超期未发货风险",
                "content": "**已观察事实**：超期订单仍有待发余额。",
                "evidence": "订单证据",
                "severity": "HIGH",
            },
            {
                **refs,
                "id": "SC01-TK01",
                "actionId": "SC01-TK01",
                "item_type": "TODO",
                "dispatchTool": "TaskOrderCreate",
                "title": "核查超期订单",
                "content": "核查并反馈处置计划。",
                "evidence": "候选原因，待验证",
                "severity": "HIGH",
            },
        ]}}],
    }, str(tmp_path))
    assert "Canvas generated" in output
    spec = json.loads(
        output.split(canvas.CANVAS_SPEC_OPEN)[1].split(canvas.CANVAS_SPEC_CLOSE)[0]
    )
    page = Path(spec["saved_path"])
    if not page.is_absolute():
        page = tmp_path / page
    html = page.read_text(encoding="utf-8")
    assert "推送风险" in html
    assert "发送任务令" in html
    assert '&quot;itemType&quot;:&quot;RISK&quot;' in html
    assert '&quot;itemType&quot;:&quot;TODO&quot;' in html
    assert "action-chip risk" in html
    assert "正在推送风险" in html


def test_canvas_risk_direct_card_is_marked_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROCESS360_CANVAS_DISPATCH_MODE", "all")
    canvas = mcp_endpoint._canvas_tools()
    execute = canvas._make_canvas_generate()
    output = execute({
        "title": "风险直发",
        "blocks": [{"kind": "actions", "params": {"items": [{
            "id": "risk-direct-1",
            "itemType": "RISK",
            "dispatchTool": "RiskItemCreate",
            "title": "超期未发货风险",
            "content": "已观察事实。",
            "severity": "HIGH",
        }]}}],
    }, str(tmp_path))
    assert "Canvas generated" in output
    spec = json.loads(
        output.split(canvas.CANVAS_SPEC_OPEN)[1].split(canvas.CANVAS_SPEC_CLOSE)[0]
    )
    page = Path(spec["saved_path"])
    if not page.is_absolute():
        page = tmp_path / page
    html = page.read_text(encoding="utf-8")
    assert "推送风险" in html
    assert "临时直发" in html
    assert "未经验证分析" in html
    item = spec["actionState"]["items"][0]
    assert item["itemType"] == "RISK"
    assert item["temporaryDispatch"] is True
    assert item["verificationStatus"] == "unverified"
    assert item["sourceKind"] == "page_direct"


def test_gate_accepts_risk_tool_only_for_risk_draft_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROCESS360_STORE_PATH", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(audit, "_STORE", None)
    store = audit.store()
    action = {
        "id": "SC01-RISK-RK01",
        "item_type": "RISK",
        "title": "超期未发货风险",
        "content": "已观察事实。",
        "dispatchTool": "RiskItemCreate",
    }
    saved = store.save_draft(
        payload={"scenario": "SC01", "canvasActions": [action]},
        scenario="SC01",
        tenant="t1",
        principal="u1",
        approval_status="host_click_authorized",
    )
    item = {
        **action,
        "draftId": saved["id"],
        "draftHash": saved["hash"],
        "actionId": action["id"],
        "itemType": "RISK",
    }
    plan = {
        "actionDeliveryRequired": True,
        "steps": [{"id": "draft-step", "tool": "Process360Draft"}],
    }
    report, hard, _warnings = mcp_endpoint._check_action_delivery(
        plan_id="",
        question="",
        plan=plan,
        action_meta={"status": "ready", "items": [item]},
    )
    assert report["status"] == "ready"
    assert hard == []

    _report, hard_wrong, _warnings = mcp_endpoint._check_action_delivery(
        plan_id="",
        question="",
        plan=plan,
        action_meta={
            "status": "ready",
            "items": [{**item, "dispatchTool": "TaskOrderCreate"}],
        },
    )
    assert any(
        issue.startswith("action_dispatch_tool_type_mismatch:")
        for issue in hard_wrong
    )
