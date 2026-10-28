from __future__ import annotations

import json
from pathlib import Path

import pytest

from bi_agent.process360 import audit, tools
from bi_agent.process360.identity import reset_active_principal, set_active_principal
from bi_agent.process360.catalog import Process360Catalog
from bi_agent.process360.service import Process360Service
from bi_agent.process360.store import Process360Store
from tests.test_process360_engine import FakeDB

ROOT = Path(__file__).resolve().parents[1]
PRINCIPAL = {"tenantId": "t1", "userId": "u1", "grantKind": "all", "canDispatch": True}


def service(tmp_path: Path) -> Process360Service:
    return Process360Service(
        catalog=Process360Catalog.from_project(ROOT),
        db=FakeDB(),
        store=Process360Store(tmp_path / "runtime.sqlite3"),
        cwd=ROOT,
    )


def test_route_returns_a_stored_plan(tmp_path: Path) -> None:
    svc = service(tmp_path)
    routed = svc.route("超期未发有多少", principal=PRINCIPAL)
    assert routed["planId"]
    assert routed["revision"] == 1
    stored = svc.store.get_plan(routed["planId"])
    assert stored["payload"]["principalKey"] == "t1:u1"


def test_plan_revision_is_recorded_with_its_reason(tmp_path: Path) -> None:
    svc = service(tmp_path)
    first = svc.route("超期未发有多少", principal=PRINCIPAL)
    revised = svc.route(
        "这些订单卡在哪个条款",
        scenario="SC04",
        plan_id=first["planId"],
        revise_reason="问题实际指向中标未签条款，原路由按交付场景判定",
        principal=PRINCIPAL,
    )
    assert revised["revision"] == 2
    assert revised["revisedFrom"] == first["planId"]
    assert revised["scenario"] == "SC04"
    stored = svc.store.get_plan(revised["planId"])
    assert stored["payload"]["reviseReason"].startswith("问题实际指向")
    # the original plan stays untouched for audit
    assert svc.store.get_plan(first["planId"])["payload"]["revision"] == 1


def test_step_outside_its_plan_is_blocked(tmp_path: Path) -> None:
    svc = service(tmp_path)
    plan = svc.route("超期未发有多少", scenario="SC01", principal=PRINCIPAL)
    blocked = svc.query("SC04", plan_id=plan["planId"], principal=PRINCIPAL)
    assert blocked["status"] == "needs_clarification"
    assert "PLAN_SCENARIO_MISMATCH" in {item["code"] for item in blocked["gaps"]}


def test_unknown_plan_is_rejected(tmp_path: Path) -> None:
    svc = service(tmp_path)
    blocked = svc.query("SC01", plan_id="missing", principal=PRINCIPAL)
    assert blocked["status"] == "needs_clarification"
    assert "PLAN_NOT_FOUND" in {item["code"] for item in blocked["gaps"]}


def test_pure_query_still_writes_a_step(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROCESS360_STORE_PATH", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(audit, "_STORE", None)
    token = audit.set_request_id("sess-1")
    identity_token = set_active_principal(PRINCIPAL)
    try:
        audit.ensure_request()
        output = tools.EXECUTORS["Process360Route"]({"question": "超期未发有多少"}, str(ROOT))
    finally:
        reset_active_principal(identity_token)
        audit.reset_request_id(token)
    assert json.loads(output)["planId"]
    trail = audit.store().get_request("sess-1")
    assert trail is not None
    assert [step["tool"] for step in trail["steps"]] == ["Process360Route"]
    assert trail["steps"][0]["status"] == "ok"
    assert trail["steps"][0]["refs"]["planId"]
