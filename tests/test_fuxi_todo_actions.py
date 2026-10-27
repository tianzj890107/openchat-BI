from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from bi_agent.integrations.fuxi_todo import (
    FuxiTodoClient,
    FuxiTodoConfig,
    make_source_todo_id,
    normalize_recipient,
    normalize_recipients,
)
from bi_agent.web import mcp_endpoint


class _CaptureClient(FuxiTodoClient):
    def __init__(self) -> None:
        super().__init__(FuxiTodoConfig(
            base_url="http://fuxi.test",
            source_code="boulderai-anaylize-todo",
            category="智能分析任务令",
        ))
        self.calls: list[tuple[str, dict]] = []

    def _post(self, path: str, payload: dict) -> dict:
        self.calls.append((path, payload))
        return {"applied": 1, "skipped": 0, "errors": []}


class _TodoHandler(BaseHTTPRequestHandler):
    request_body: dict = {}
    source_header = ""
    request_path = ""

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        type(self).request_path = self.path
        type(self).source_header = self.headers.get("x-fuxi-source", "")
        length = int(self.headers.get("content-length") or 0)
        type(self).request_body = json.loads(self.rfile.read(length) or b"{}")
        body = json.dumps({"applied": 1, "skipped": 0, "errors": []}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def test_recipient_normalization_matches_fuxi_contract() -> None:
    assert normalize_recipient("+86 139-0000-0002") == "13900000002"
    assert normalize_recipients(["13800000001", "13900000002"]) == [
        "13800000001", "13900000002",
    ]
    with pytest.raises(ValueError):
        normalize_recipients([])


def test_source_todo_id_is_stable_and_safe() -> None:
    first = make_source_todo_id("action 1", "canvas/2026-10-27")
    second = make_source_todo_id("action 1", "canvas/2026-10-27")
    assert first == second
    assert first.startswith("analytics-canvas-2026-10-27-action-1")


def test_create_todo_maps_action_to_fuxi_batch() -> None:
    client = _CaptureClient()
    result = client.create_todo(
        title="跟进重点客户回款",
        content="根据分析结果跟进逾期回款。",
        recipients_raw=["+86 138-0000-0001"],
        action_id="action-1",
        canvas_id="canvas-1",
        severity="WARNING",
        evidence="应收账龄表",
        caliber_meta={"artifactId": "canvas-1"},
    )
    assert result["ok"] is True
    path, payload = client.calls[0]
    assert path == "/source/todo-batches"
    item = payload["items"][0]
    assert item["sourceTodoId"] == "analytics-canvas-1-action-1"
    assert item["severity"] == "MEDIUM"
    assert item["itemType"] == "TODO"
    assert item["sourceStatus"] == "OPEN"
    assert item["recipientsRaw"] == ["13800000001"]
    assert item["caliberMeta"]["artifactId"] == "canvas-1"


def test_create_todo_uses_documented_http_contract() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TodoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = FuxiTodoClient(FuxiTodoConfig(
            base_url=f"http://127.0.0.1:{server.server_port}",
            source_code="boulderai-anaylize-todo",
            category="智能分析任务令",
        ))
        result = client.create_todo(
            title="跟进重点客户回款",
            content="根据分析结果跟进逾期回款。",
            recipients_raw="+86 138-0000-0001",
            action_id="action-1",
            severity="HIGH",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result["ok"] is True
    assert _TodoHandler.request_path == "/source/todo-batches"
    assert _TodoHandler.source_header == "boulderai-anaylize-todo"
    assert _TodoHandler.request_body["batchRef"].startswith("analytics-analytics-analysis-action-1-")
    item = _TodoHandler.request_body["items"][0]
    assert item["recipientsRaw"] == ["13800000001"]
    assert item["severity"] == "HIGH"
    assert item["sourceUpdatedAt"].endswith("Z")


def test_task_order_executor_uses_fuxi_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _CaptureClient()
    monkeypatch.setattr(mcp_endpoint, "FuxiTodoClient", lambda: client)
    executor = mcp_endpoint._task_order_executor()
    output = executor({
        "action_id": "a1",
        "title": "跟进回款",
        "content": "复核逾期客户",
        "recipients_raw": ["13800000001"],
        "severity": "HIGH",
    }, "/tmp")
    assert json.loads(output)["sourceTodoId"] == "analytics-analysis-a1"
    assert client.calls[0][0] == "/source/todo-batches"


def test_canvas_actions_block_renders_task_order_control(tmp_path: Path) -> None:
    canvas = mcp_endpoint._canvas_tools()
    execute = canvas._make_canvas_generate()
    output = execute({
        "title": "分析行动",
        "conclusion": "结论：优先处理高风险行动。",
        "blocks": [{
            "kind": "actions",
            "heading": "行动建议",
            "params": {"items": [{
                "id": "action-1",
                "title": "跟进重点客户回款",
                "content": "由责任人逐户复核逾期原因。",
                "evidence": "应收账龄表",
                "severity": "HIGH",
            }]},
        }],
    }, str(tmp_path))
    assert "Canvas generated" in output
    html = (tmp_path / "dataset" / "canvas").glob("*.html")
    page = next(html).read_text(encoding="utf-8")
    assert "发送任务令" in page
    assert 'data-fuxi-task-order="action-1"' in page
    assert "fuxi:task-order-create" in page
    assert '"actions"' in output
