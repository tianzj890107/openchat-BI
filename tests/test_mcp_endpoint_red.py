"""Red tests for the embedded remote MCP endpoint.

These tests do not call demo2.  They assert the transport contract, the
colleague-facing tool surface, the deterministic route/gate tools, and the
HTML artifact hand-off.  A fake executor factory keeps the suite local.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bi_agent.web.mcp_endpoint import (
    DEFAULT_EXPOSED_TOOLS,
    MCP_DENIED_TOOLS,
    _canvas_tools,
    build_mcp_router,
)


def _source() -> SimpleNamespace:
    return SimpleNamespace(
        ontology_store=object(),
        remote_ontology=None,
        ontology_backend="production",
        ontology_namespace="ecore",
        ontology_path="",
        db_path="",
        use_doris=False,
        doris_jdbc_url="",
        doris_driver="",
        doris_username="",
        doris_password="",
        doris_database="ontology_ecore",
        doris_api_url="http://demo2.eimos.com/api/gateway2/ontology/agent/doris/query",
        retrieval_mode="semantic",
        graph_path="",
    )


def _canvas_payload(cwd: str) -> str:
    canvas = _canvas_tools()
    out = Path(cwd) / "dataset" / "canvas" / "test-artifact.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("<html><body>ok</body></html>", encoding="utf-8")
    spec = {"saved_path": "dataset/canvas/test-artifact.html", "title": "t"}
    return (
        "Canvas generated\nSaved: dataset/canvas/test-artifact.html\n\n"
        + canvas.CANVAS_SPEC_OPEN
        + json.dumps(spec, ensure_ascii=False)
        + canvas.CANVAS_SPEC_CLOSE
    )


def _executors(cwd_holder: dict[str, str]):
    def factory(_source):
        return {
            "Ontology-MetricQuery": lambda params, cwd: "metric-ok",
            "MetricFactQuery": lambda params, cwd: json.dumps({"total": 1}),
            "CanvasGenerate": lambda params, cwd: _canvas_payload(cwd),
        }
    return factory


def _client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(build_mcp_router(
        get_source=_source,
        build_doris=lambda *args, **kwargs: None,
        get_cwd=lambda: str(tmp_path),
        executor_factory=_executors({}),
    ))
    return TestClient(app)


def _init(client: TestClient) -> str:
    response = client.post("/api/mcp", json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    })
    assert response.status_code == 200
    return response.headers["mcp-session-id"]


def _call(client: TestClient, sid: str, name: str, arguments: dict):
    return client.post(
        "/api/mcp",
        headers={"mcp-session-id": sid},
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )


def test_initialize_returns_session_and_protocol(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post("/api/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {}},
    })
    assert response.status_code == 200
    assert response.headers["mcp-session-id"]
    result = response.json()["result"]
    assert result["protocolVersion"] == "2025-03-26"
    assert result["serverInfo"]["name"] == "ontology-analytics-mcp"


def test_tools_list_exposes_real_tools_and_hides_wrappers(tmp_path: Path) -> None:
    client = _client(tmp_path)
    sid = _init(client)
    response = client.post(
        "/api/mcp", headers={"mcp-session-id": sid},
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert set(DEFAULT_EXPOSED_TOOLS) <= names
    assert "AnalysisRoute" in names
    assert "MetricFactQuery" in names
    assert "CanvasGenerate" in names
    assert "OutputGateCheck" in names
    assert not (MCP_DENIED_TOOLS & names)
    assert "AnalysisRun" not in names
    assert "Ontology-FactQuery" not in names


def test_missing_session_is_rejected(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    assert response.status_code == 400
    assert "Mcp-Session-Id" in response.text


def test_analysis_route_is_deterministic(tmp_path: Path) -> None:
    client = _client(tmp_path)
    sid = _init(client)
    response = _call(client, sid, "AnalysisRoute", {"question": "2025年采购金额合计是多少"})
    body = response.json()["result"]
    assert body["isError"] is False
    decision = json.loads(body["content"][0]["text"])
    assert decision["mode"] == "FACT_QUERY"
    assert decision["next_step"] in {"QUERY_DORIS", "QUERY_ONTOLOGY"}


def test_output_gate_rejects_write_sql(tmp_path: Path) -> None:
    client = _client(tmp_path)
    sid = _init(client)
    response = _call(client, sid, "OutputGateCheck", {
        "answer": "合计 100 元", "sql": "DELETE FROM t",
    })
    report = json.loads(response.json()["result"]["content"][0]["text"])
    assert report["verdict"] == "reject"
    assert any(item.startswith("sql_rejected") for item in report["hard_issues"])


def test_canvas_returns_download_url_and_serves_it(tmp_path: Path) -> None:
    client = _client(tmp_path)
    sid = _init(client)
    response = _call(client, sid, "CanvasGenerate", {"title": "t", "blocks": []})
    text = response.json()["result"]["content"][0]["text"]
    assert "Artifact URL:" in text
    url = text.split("Artifact URL:", 1)[1].strip()
    artifact = client.get(url)
    assert artifact.status_code == 200
    assert artifact.text == "<html><body>ok</body></html>"


def test_artifact_route_blocks_traversal(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/api/mcp/artifacts/..%2F..%2Fetc%2Fpasswd")
    assert response.status_code == 404


def test_analysis_run_cannot_be_re_enabled(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(build_mcp_router(
        get_source=_source,
        build_doris=lambda *args, **kwargs: None,
        get_cwd=lambda: str(tmp_path),
        executor_factory=_executors({}),
        exposed_tools=("AnalysisRoute", "AnalysisRun", "Ontology-FactQuery"),
    ))
    client = TestClient(app)
    sid = _init(client)
    response = client.post(
        "/api/mcp", headers={"mcp-session-id": sid},
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert names == {"AnalysisRoute"}
