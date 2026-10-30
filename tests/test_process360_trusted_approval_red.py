from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from bi_agent.process360.catalog import Process360Catalog
from bi_agent.process360.identity import PrincipalScope
from bi_agent.process360.service import Process360Service
from bi_agent.process360.store import Process360Store
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


def approval(svc: Process360Service, *, target: float = 0.5) -> dict:
    return svc.store.save_trusted_approval(
        tenant="t1",
        scenario="SC01",
        status="approved",
        target=target,
        direction=">=",
        minimum_denominator=2,
        valid_from=datetime.now(timezone.utc) - timedelta(days=1),
        valid_until=datetime.now(timezone.utc) + timedelta(days=30),
        payload={"approvedBy": "business-owner", "scope": {}},
    )


def test_verify_reads_target_from_server_approval_not_model_arguments(tmp_path: Path) -> None:
    svc = service(tmp_path)
    ref = approval(svc)
    trusted = svc.verify(
        scenario="SC01",
        principal=PRINCIPAL,
        approval_ref=ref["id"],
    )
    assert trusted["approval"]["target"] == 0.5
    assert trusted["closure"]["target"] == 0.5
    assert "VERIFICATION_TARGET_MISSING" not in {item["code"] for item in trusted["gaps"]}

    forged = svc.verify(
        scenario="SC01",
        principal=PRINCIPAL,
        approval_ref=ref["id"],
        approved_target=0.1,
    )
    assert forged["status"] == "blocked"
    assert "APPROVAL_TARGET_MISMATCH" in {item["code"] for item in forged["gaps"]}


def test_unknown_or_expired_approval_cannot_be_replaced_by_a_model_target(tmp_path: Path) -> None:
    svc = service(tmp_path)
    missing = svc.verify(
        scenario="SC01",
        principal=PRINCIPAL,
        approval_ref="missing",
        approved_target=0.5,
    )
    assert "APPROVAL_NOT_FOUND" in {item["code"] for item in missing["gaps"]}

    ref = svc.store.save_trusted_approval(
        tenant="t1",
        scenario="SC01",
        status="approved",
        target=0.5,
        direction=">=",
        minimum_denominator=2,
        valid_from=datetime.now(timezone.utc) - timedelta(days=3),
        valid_until=datetime.now(timezone.utc) - timedelta(days=1),
        payload={},
    )
    expired = svc.verify(
        scenario="SC01",
        principal=PRINCIPAL,
        approval_ref=ref["id"],
        approved_target=0.5,
    )
    assert "APPROVAL_EXPIRED" in {item["code"] for item in expired["gaps"]}
