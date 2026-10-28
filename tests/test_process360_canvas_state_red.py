from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from bi_agent.web import mcp_endpoint


def _generated_page(tmp_path: Path, items: list[dict]) -> str:
    execute = mcp_endpoint._canvas_tools()._make_canvas_generate()
    execute(
        {
            "title": "状态机测试",
            "conclusion": "结论：先核查。",
            "blocks": [{"kind": "actions", "params": {"items": items}}],
        },
        str(tmp_path),
    )
    return next((tmp_path / "dataset" / "canvas").glob("*.html")).read_text(encoding="utf-8")


def _run_normalize(payload: dict) -> dict:
    runtime = mcp_endpoint._canvas_tools().ACTION_RUNTIME
    match = re.search(r"function normalizeReceipt\(payload\) \{.*?\n  \}", runtime, re.S)
    assert match, "normalizeReceipt must remain an independently testable function"
    script = match.group(0) + "\nconsole.log(JSON.stringify(normalizeReceipt(" + json.dumps(payload) + ")));"
    output = subprocess.check_output(["node", "-e", script], text=True)
    return json.loads(output)


def test_blocked_and_rejected_are_classified_before_unconfirmed() -> None:
    blocked = _run_normalize({"status": "blocked", "accepted": False, "message": "无权限"})
    assert blocked["state"] == "rejected"
    rejected = _run_normalize({"status": "rejected", "accepted": False, "message": "Fuxi拒绝"})
    assert rejected["state"] == "rejected"


def test_ok_without_a_verifiable_receipt_is_not_success() -> None:
    assert _run_normalize({"status": "ok", "accepted": False})["state"] == "unconfirmed"
    assert _run_normalize({"status": "ok", "accepted": True, "receipt": {}})["state"] == "unconfirmed"
    verified = _run_normalize(
        {"status": "ok", "accepted": True, "receipt": {"sourceTodoId": "analytics-1"}}
    )
    assert verified["state"] == "ok"
    assert _run_normalize({"status": "unknown", "accepted": False})["state"] == "unconfirmed"


def test_canvas_distinguishes_missing_fields_pending_approval_and_expiry(tmp_path: Path) -> None:
    base = {
        "id": "a1",
        "title": "核查",
        "content": "核查证据。",
        "evidence": "证据",
        "approvalStatus": "approved",
        "expiresAt": "2099-01-01T00:00:00Z",
        "dispatchTool": "TaskOrderCreate",
        "draftId": "draft-1",
        "draftHash": "hash-1",
        "actionId": "a1",
    }
    missing = {**base, "id": "missing", "actionId": "missing"}
    missing.pop("draftHash")
    pending = {**base, "id": "pending", "actionId": "pending", "approvalStatus": "pending"}
    expired = {**base, "id": "expired", "actionId": "expired", "expiresAt": "2000-01-01T00:00:00Z"}
    page = _generated_page(tmp_path, [missing, pending, expired])
    assert "缺少草稿字段" in page
    assert "待审批" in page
    assert "草稿已过期" in page


def test_canvas_never_falls_back_to_host_after_http_error() -> None:
    runtime = mcp_endpoint._canvas_tools().ACTION_RUNTIME
    assert "transport = 'host'" not in runtime
    assert "AbortController" in runtime
    assert "refreshStatus" in runtime
