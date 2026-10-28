from __future__ import annotations

import hashlib
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
    "canDispatch": True,
}


def service(tmp_path: Path) -> Process360Service:
    return Process360Service(
        catalog=Process360Catalog.from_project(ROOT),
        db=FakeDB(),
        store=Process360Store(tmp_path / "runtime.sqlite3"),
        cwd=ROOT,
    )


def test_output_gate_registers_an_append_only_artifact_version(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("PROCESS360_STORE_PATH", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(audit, "_STORE", None)
    canvas = mcp_endpoint._canvas_tools()._make_canvas_generate()
    canvas(
        {
            "title": "交付校验",
            "conclusion": "结论：核查超期订单。",
            "blocks": [{"kind": "text", "markdown": "证据见明细。"}],
        },
        str(tmp_path),
    )
    page = next((tmp_path / "dataset" / "canvas").glob("*.html"))
    spec = mcp_endpoint._canvas_tools().extract_canvas_spec(
        f"<CANVAS_SPEC>{json.dumps({'saved_path': str(page)})}</CANVAS_SPEC>"
    )[1]
    digest = hashlib.sha256(page.read_bytes()).hexdigest()
    token = set_request_context(
        resolve_request_context(
            principal=PRINCIPAL,
            conversation_id="conv-1",
            request_id="req-artifact",
            surface="mcp",
        )
    )
    try:
        gate = mcp_endpoint._gate_executor()
        first = json.loads(
            gate(
                {
                    "answer": "结论：核查超期订单。",
                    "canvasId": page.stem,
                    "artifactHash": digest,
                    "planId": "plan-1",
                    "queryId": "query-1",
                },
                str(tmp_path),
            )
        )
    finally:
        reset_request_context(token)
    assert first["artifact"]["artifactId"]
    record = audit.store().get_artifact(first["artifact"]["artifactId"], tenant="t1", principal="u1")
    assert record and record["artifact_hash"] == digest
    assert record["request_id"] == "req-artifact"
    assert record["plan_id"] == "plan-1"
    assert record["query_id"] == "query-1"

    page.write_text(page.read_text(encoding="utf-8") + "\n<!-- changed -->", encoding="utf-8")
    changed = json.loads(
        gate(
            {
                "answer": "结论：核查超期订单。",
                "canvasId": page.stem,
                "artifactHash": digest,
                "planId": "plan-1",
                "queryId": "query-1",
            },
            str(tmp_path),
        )
    )
    assert "artifact_hash_mismatch" in changed["hard_issues"]
    assert changed["artifact"]["artifactId"] != first["artifact"]["artifactId"]
    assert audit.store().get_artifact(changed["artifact"]["artifactId"])["gate_result"]["verdict"] == "reject"


def test_output_gate_refuses_a_final_report_without_an_artifact(tmp_path: Path) -> None:
    report = json.loads(
        mcp_endpoint._gate_executor()(
            {"answer": "结论：核查超期订单。"},
            str(tmp_path),
        )
    )
    assert report["verdict"] == "reject"
    assert "artifact_reference_required" in report["hard_issues"]


def test_output_gate_schema_exposes_trace_references() -> None:
    properties = mcp_endpoint.OUTPUT_GATE_SCHEMA["input_schema"]["properties"]
    assert properties["canvasId"]["type"] == "string"
    assert properties["artifactHash"]["type"] == "string"
    assert properties["planId"]["type"] == "string"
    assert properties["queryId"]["type"] == "string"
    assert properties["deliveryKind"]["enum"] == ["analysis_report", "fact_answer"]


def test_fact_answer_can_be_delivered_without_a_canvas(tmp_path: Path) -> None:
    report = json.loads(
        mcp_endpoint._gate_executor()(
            {
                "answer": "本轮未进入分析报告交付。",
                "deliveryKind": "fact_answer",
            },
            str(tmp_path),
        )
    )
    assert report["verdict"] != "reject"
    assert "artifact_reference_required" not in report.get("hard_issues", [])


def test_execution_registration_failure_never_calls_fuxi(
    tmp_path: Path, monkeypatch
) -> None:
    svc = service(tmp_path)
    bundle = svc.draft(
        scenario="SC01",
        principal=PRINCIPAL,
        owner_ref="u1",
        owner_name="张真",
    )
    action = bundle["canvasActions"][0]

    def fail_claim(**kwargs):
        raise RuntimeError("sqlite disk unavailable")

    monkeypatch.setattr(svc.store, "claim_execution", fail_claim)

    class Client:
        calls = 0

        def create_todo(self, **kwargs):
            self.calls += 1
            raise AssertionError("Fuxi must not be called")

    client = Client()
    result = svc.execute_draft(
        draft_id=bundle["draftId"],
        draft_hash=bundle["draftHash"],
        action_id=action["id"],
        recipients=["18800000001"],
        principal=PRINCIPAL,
        client=client,
    )
    assert result["status"] == "blocked"
    assert "EXECUTION_REGISTRATION_FAILED" in {item["code"] for item in result["gaps"]}
    assert client.calls == 0
