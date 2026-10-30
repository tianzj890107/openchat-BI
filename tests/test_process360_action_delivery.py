from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from bi_agent.process360 import audit
from bi_agent.process360.catalog import Process360Catalog
from bi_agent.process360.router import delivery_requirement
from bi_agent.process360.service import Process360Service
from bi_agent.process360.store import Process360Store
from bi_agent.process360.tools import _with_action_block
from bi_agent.web import mcp_endpoint
from tests.test_process360_engine import FakeDB

ROOT = Path(__file__).resolve().parents[1]


def _service(tmp_path: Path) -> Process360Service:
    return Process360Service(
        catalog=Process360Catalog.from_project(ROOT),
        db=FakeDB(),
        store=Process360Store(tmp_path / "runtime.sqlite3"),
        cwd=ROOT,
    )


def _canvas(tmp_path: Path, blocks: list[dict]) -> tuple[str, str, str]:
    output = mcp_endpoint._canvas_tools()._make_canvas_generate()(
        {
            "title": "行动交付验收",
            "conclusion": "结论：先核查超期订单。",
            "blocks": blocks,
        },
        str(tmp_path),
    )
    spec = json.loads(
        output.split(mcp_endpoint._canvas_tools().CANVAS_SPEC_OPEN)[1].split(
            mcp_endpoint._canvas_tools().CANVAS_SPEC_CLOSE
        )[0]
    )
    page = Path(spec["saved_path"])
    if not page.is_absolute():
        page = tmp_path / page
    return spec["canvasId"], hashlib.sha256(page.read_bytes()).hexdigest(), page.read_text()


def _store(tmp_path: Path, monkeypatch) -> Process360Store:
    monkeypatch.setenv("PROCESS360_STORE_PATH", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(audit, "_STORE", None)
    return audit.store()


def _plan(store: Process360Store, *, required: bool = True) -> str:
    return store.save_plan(
        {
            "question": "储能超期未发订单该怎么办？",
            "scenario": "SC01",
            "actionDeliveryRequired": required,
            "deliveryKind": "action_cards" if required else "analysis_report",
            "steps": [
                {"id": "step-1", "tool": "Process360Solutions", "dependsOn": [], "status": "pending"},
                {"id": "step-2", "tool": "Process360Draft", "dependsOn": ["step-1"], "status": "pending"},
            ],
            "tenant": "t1",
            "principalKey": "ywln:poc",
        },
        status="ok",
    )["id"]


def _draft(store: Process360Store) -> tuple[dict, dict]:
    actions = [
        {
            "id": "a1",
            "title": "锁定排产与产能",
            "content": "由供应链核查瓶颈产能并回填交期。",
            "evidence": "SC01 超期未发明细",
        }
    ]
    payload = {
        "runId": "run-1",
        "queryId": "query-1",
        "scenario": "SC01",
        "tasks": [],
        "canvasActions": actions,
    }
    saved = store.save_draft(
        payload=payload,
        scenario="SC01",
        run_id="run-1",
        tenant="t1",
        principal="poc",
        approval_status="host_click_authorized",
    )
    return saved, actions[0]


def _action_item(saved: dict, action: dict) -> dict:
    return {
        **action,
        "draftId": saved["id"],
        "draftHash": saved["hash"],
        "runId": "run-1",
        "queryId": "query-1",
        "actionId": action["id"],
        "scenario": "SC01",
        "approvalStatus": "host_click_authorized",
        "expiresAt": saved["expiresAt"],
        "dispatchTool": "TaskOrderCreate",
    }


def _gate(tmp_path: Path, body: dict) -> dict:
    return json.loads(mcp_endpoint._gate_executor()(body, str(tmp_path)))


def test_route_marks_action_delivery_for_recommend_and_draft_only() -> None:
    assert delivery_requirement("储能超期未发订单该怎么办？")["required"] is True
    assert delivery_requirement("把整改计划拆成任务令草稿")["required"] is True
    assert delivery_requirement("本月采购金额是多少")["required"] is False


def test_route_plan_contains_executable_draft_step(tmp_path: Path) -> None:
    service = _service(tmp_path)
    routed = service.route("储能超期未发订单该怎么办？")
    assert routed["actionDeliveryRequired"] is True
    tools = [step["tool"] for step in routed["steps"]]
    assert tools[-1] == "Process360Draft"

    dispatched = service.route("把超期订单整改发送任务令")
    tools = [step["tool"] for step in dispatched["steps"]]
    assert "Process360Draft" in tools
    assert all(tool.startswith("Process360") for tool in tools)


def test_multi_goal_plan_marks_action_delivery_and_keeps_fact_plans_light(tmp_path: Path) -> None:
    service = _service(tmp_path)
    action_plan = service.plan(question="储能超期未发订单该怎么办？")
    assert action_plan["actionDeliveryRequired"] is True
    tools = [step["tool"] for step in action_plan["steps"]]
    assert "Process360Analyze" in tools
    assert tools[-1] == "Process360Draft"

    fact_plan = service.plan(question="本月采购金额是多少？")
    assert fact_plan["actionDeliveryRequired"] is False
    assert all(step["tool"] != "Process360Draft" for step in fact_plan["steps"])


def test_canvas_blocked_action_block_is_visible_and_machine_readable(tmp_path: Path) -> None:
    _cid, _digest, page = _canvas(
        tmp_path,
        [
            {
                "kind": "actions",
                "params": {
                    "items": [],
                    "reason": "缺少可信责任人，尚未生成任务草稿",
                    "gaps": ["RESPONSIBLE_PARTY_MISSING"],
                },
            }
        ],
    )
    assert "尚不能生成可下发任务" in page
    assert "缺少可信责任人" in page
    assert "data-fuxi-task-order" not in page
    assert "<button" not in page
    assert 'name="canvas-actions"' in page


def test_canvas_action_meta_carries_draft_references(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path, monkeypatch)
    saved, action = _draft(store)
    item = _action_item(saved, action)
    _cid, _digest, page = _canvas(tmp_path, [{"kind": "actions", "params": {"items": [item]}}])
    assert 'name="canvas-actions"' in page
    assert saved["id"] in page
    assert "发送任务令" in page


def test_gate_keeps_plain_suggestions_for_a_non_action_analysis(
    tmp_path: Path, monkeypatch
) -> None:
    _store(tmp_path, monkeypatch)
    canvas_id, digest, page = _canvas(
        tmp_path,
        [
            {
                "kind": "actions",
                "params": {
                    "items": [
                        {"id": "a1", "title": "核实回款", "content": "由财务复核逾期账户。"}
                    ]
                },
            }
        ],
    )
    assert "分析建议" in page
    assert "临时直发" in page
    assert "点击后将按当前卡片内容生成待办" in page
    assert 'title="缺少草稿字段' not in page
    assert "data-fuxi-task-order" in page
    report = _gate(
        tmp_path,
        {
            "answer": "逾期可能来自回款确认延迟，建议先核实账户账龄。",
            "question": "回款逾期的原因是什么？",
            "canvasId": canvas_id,
            "artifactHash": digest,
        },
    )
    assert report["verdict"] != "reject"
    assert report["actionDelivery"]["status"] == "recommendations"
    assert not any(issue.startswith("action_card_") for issue in report["warnings"])


def test_gate_rejects_missing_action_card_when_plan_requires_it(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path, monkeypatch)
    plan_id = _plan(store, required=True)
    canvas_id, digest, _page = _canvas(
        tmp_path, [{"kind": "text", "markdown": "建议由供应链核查产能。"}]
    )
    report = _gate(
        tmp_path,
        {
            "answer": "建议由供应链核查产能。",
            "question": "储能超期未发订单该怎么办？",
            "planId": plan_id,
            "canvasId": canvas_id,
            "artifactHash": digest,
        },
    )
    assert report["verdict"] == "reject"
    assert "action_card_required" in report["hard_issues"]


def test_gate_rejects_blocked_placeholder_without_a_draft_attempt(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path, monkeypatch)
    plan_id = _plan(store, required=True)
    canvas_id, digest, _page = _canvas(
        tmp_path,
        [{"kind": "actions", "params": {"items": [], "reason": "缺少可信责任人"}}],
    )
    report = _gate(
        tmp_path,
        {
            "answer": "由于缺少责任人，暂不能生成任务令。",
            "question": "储能超期未发订单该怎么办？",
            "planId": plan_id,
            "canvasId": canvas_id,
            "artifactHash": digest,
        },
    )
    assert report["verdict"] == "reject"
    assert "action_draft_not_attempted" in report["hard_issues"]


def test_gate_allows_blocked_placeholder_when_draft_step_was_blocked(
    tmp_path: Path, monkeypatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    plan_id = _plan(store, required=True)
    store.record_plan_step(
        plan_id=plan_id,
        step_id="step-2",
        request_id="req-1",
        tool="Process360Draft",
        status="blocked",
    )
    canvas_id, digest, _page = _canvas(
        tmp_path,
        [{"kind": "actions", "params": {"items": [], "reason": "缺少可信责任人"}}],
    )
    report = _gate(
        tmp_path,
        {
            "answer": "由于缺少责任人，暂不能生成任务令，已明确披露缺口。",
            "question": "储能超期未发订单该怎么办？",
            "planId": plan_id,
            "canvasId": canvas_id,
            "artifactHash": digest,
        },
    )
    assert not any(issue.startswith("action_") for issue in report["hard_issues"])
    assert report["actionDelivery"]["status"] == "blocked"


def test_gate_rejects_action_card_with_unknown_draft(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path, monkeypatch)
    plan_id = _plan(store, required=True)
    item = {
        "id": "a1",
        "title": "锁定排产",
        "content": "核查产能。",
        "draftId": "missing-draft",
        "draftHash": "deadbeef",
        "actionId": "a1",
        "runId": "run-1",
        "approvalStatus": "host_click_authorized",
        "expiresAt": time.time() + 3600,
        "dispatchTool": "TaskOrderCreate",
    }
    canvas_id, digest, _page = _canvas(tmp_path, [{"kind": "actions", "params": {"items": [item]}}])
    report = _gate(
        tmp_path,
        {
            "answer": "建议锁定排产。",
            "question": "储能超期未发订单该怎么办？",
            "planId": plan_id,
            "canvasId": canvas_id,
            "artifactHash": digest,
        },
    )
    assert report["verdict"] == "reject"
    assert any(issue.startswith("action_draft_not_found") for issue in report["hard_issues"])


def test_gate_accepts_action_card_bound_to_stored_draft(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path, monkeypatch)
    plan_id = _plan(store, required=True)
    saved, action = _draft(store)
    store.record_plan_step(
        plan_id=plan_id,
        step_id="step-2",
        request_id="req-1",
        tool="Process360Draft",
        status="completed",
    )
    canvas_id, digest, _page = _canvas(
        tmp_path, [{"kind": "actions", "params": {"items": [_action_item(saved, action)]}}]
    )
    report = _gate(
        tmp_path,
        {
            "answer": "建议锁定排产。",
            "question": "储能超期未发订单该怎么办？",
            "planId": plan_id,
            "canvasId": canvas_id,
            "artifactHash": digest,
        },
    )
    assert report["verdict"] != "reject"
    assert report["actionDelivery"]["status"] == "ready"
    assert report["actionDelivery"]["count"] == 1


def test_gate_rejects_action_card_from_another_run(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path, monkeypatch)
    plan_id = _plan(store, required=True)
    saved, action = _draft(store)
    store.record_plan_step(
        plan_id=plan_id,
        step_id="step-1",
        request_id="req-1",
        tool="Process360Analyze",
        status="completed",
        refs={"runId": "another-run"},
    )
    store.record_plan_step(
        plan_id=plan_id,
        step_id="step-2",
        request_id="req-1",
        tool="Process360Draft",
        status="completed",
    )
    canvas_id, digest, _page = _canvas(
        tmp_path, [{"kind": "actions", "params": {"items": [_action_item(saved, action)]}}]
    )
    report = _gate(
        tmp_path,
        {
            "answer": "建议锁定排产。",
            "question": "储能超期未发订单该怎么办？",
            "planId": plan_id,
            "canvasId": canvas_id,
            "artifactHash": digest,
        },
    )
    assert report["verdict"] == "reject"
    assert any(issue.startswith("action_run_not_in_plan") for issue in report["hard_issues"])


def test_gate_requires_cards_for_action_question_without_a_process360_plan(
    tmp_path: Path, monkeypatch
) -> None:
    _store(tmp_path, monkeypatch)
    canvas_id, digest, _page = _canvas(
        tmp_path, [{"kind": "text", "markdown": "建议由供应链核查产能。"}]
    )
    report = _gate(
        tmp_path,
        {
            "answer": "建议由供应链核查产能。",
            "question": "回款逾期该怎么办？",
            "canvasId": canvas_id,
            "artifactHash": digest,
        },
    )
    assert report["verdict"] == "reject"
    assert "action_card_required" in report["hard_issues"]


def test_gate_allows_plain_cards_without_plan_but_flags_untrusted_draft(
    tmp_path: Path, monkeypatch
) -> None:
    _store(tmp_path, monkeypatch)
    canvas_id, digest, _page = _canvas(
        tmp_path,
        [
            {
                "kind": "actions",
                "params": {
                    "items": [
                        {"id": "a1", "title": "跟进回款", "content": "由财务确认逾期账户。"}
                    ]
                },
            }
        ],
    )
    report = _gate(
        tmp_path,
        {
            "answer": "建议跟进回款。",
            "question": "回款逾期该怎么办？",
            "canvasId": canvas_id,
            "artifactHash": digest,
        },
    )
    assert report["verdict"] != "reject"
    assert report["actionDelivery"]["status"] == "untrusted"
    assert "action_cards_without_trusted_draft" in report["warnings"]


def test_draft_tool_builds_a_ready_or_blocked_canvas_block() -> None:
    blocked = _with_action_block(
        {
            "status": "blocked",
            "gaps": [{"code": "RESPONSIBLE_PARTY_MISSING", "needed": "补充可信责任人"}],
            "canvasActions": [],
        }
    )
    block = blocked["canvasActionBlock"]
    assert block["kind"] == "actions"
    assert block["params"]["items"] == []
    assert "补充可信责任人" in block["params"]["reason"]
    assert blocked["actionDelivery"]["status"] == "blocked"

    ready = _with_action_block(
        {
            "status": "ok",
            "canvasActions": [{"id": "a1", "title": "核查", "content": "核查产能"}],
        }
    )
    assert ready["canvasActionBlock"]["params"]["items"][0]["id"] == "a1"
    assert ready["actionDelivery"]["status"] == "ready"
