from __future__ import annotations

from pathlib import Path

from bi_agent.process360.catalog import Process360Catalog
from bi_agent.process360.closure import build_baseline
from bi_agent.process360.identity import PrincipalScope
from bi_agent.process360.models import Scope
from bi_agent.process360.service import QUERY_TEMPLATE_VERSION, Process360Service
from bi_agent.process360.store import Process360Store


ROOT = Path(__file__).resolve().parents[1]
PRINCIPAL = {
    "tenantId": "t1",
    "userId": "u1",
    "grantKind": "all",
    "authorizationVersion": "auth-v1",
}


def service(tmp_path: Path) -> Process360Service:
    return Process360Service(
        catalog=Process360Catalog.from_project(ROOT),
        db=object(),
        store=Process360Store(tmp_path / "runtime.sqlite3"),
        cwd=ROOT,
    )


def stored_query(tmp_path: Path, **overrides):
    svc = service(tmp_path)
    values = {
        "scenario": "SC01",
        "scope": {"limit": 100, "customerIds": ["c1"]},
        "payload": {"status": "ok", "scope": {"limit": 100}, "records": [{"order_id": "o1"}]},
        "tenant": "t1",
        "principal": "u1",
        "catalog_version": svc.catalog_version,
        "catalog_hash": svc._catalog_hash(),
        "authorization_version": "auth-v1",
        "grant_fingerprint": PrincipalScope.from_payload(PRINCIPAL).grant_fingerprint,
        "source_connection": svc._source_connection(),
        "template_version": QUERY_TEMPLATE_VERSION,
        "result_hash": "result-hash-1",
        "complete": True,
        "full_count": 1,
        "expires_at": 9999999999,
    }
    values.update(overrides)
    return svc.store.save_query(**values)["id"]


def test_query_contract_fields_are_persisted_and_reloaded(tmp_path: Path) -> None:
    query_id = stored_query(tmp_path)
    stored = service(tmp_path).store.get_query(query_id)
    assert stored["source_connection"] == "database:test"
    assert stored["authorization_version"] == "auth-v1"
    assert stored["grant_fingerprint"] == PrincipalScope.from_payload(PRINCIPAL).grant_fingerprint
    assert stored["template_version"] == QUERY_TEMPLATE_VERSION
    assert stored["result_hash"] == "result-hash-1"
    assert stored["complete"] is True
    assert stored["contract_version"] == "process360.query.v2"


def test_query_scope_conflict_does_not_silently_rerun(tmp_path: Path) -> None:
    svc = service(tmp_path)
    query_id = stored_query(tmp_path)
    result = svc.query(
        "SC01",
        principal=PRINCIPAL,
        query_id=query_id,
        scope={"customerIds": ["c2"]},
    )
    assert result["status"] in {"blocked", "needs_clarification"}
    assert "QUERY_SCOPE_CONFLICT" in {item["code"] for item in result["gaps"]}
    assert result.get("queryId") in {None, query_id}


def test_expired_query_is_not_reused(tmp_path: Path) -> None:
    svc = service(tmp_path)
    query_id = stored_query(tmp_path, expires_at=1)
    result = svc.query("SC01", principal=PRINCIPAL, query_id=query_id)
    assert result["status"] in {"blocked", "needs_clarification"}
    assert "QUERY_EXPIRED" in {item["code"] for item in result["gaps"]}


def test_authorization_version_change_blocks_reuse(tmp_path: Path) -> None:
    svc = service(tmp_path)
    query_id = stored_query(tmp_path)
    changed = {**PRINCIPAL, "authorizationVersion": "auth-v2"}
    result = svc.query("SC01", principal=changed, query_id=query_id)
    assert result["status"] in {"blocked", "needs_clarification"}
    assert "QUERY_AUTHORIZATION_CHANGED" in {item["code"] for item in result["gaps"]}


def test_inaccessible_and_missing_query_return_the_same_status(tmp_path: Path) -> None:
    svc = service(tmp_path)
    query_id = stored_query(tmp_path)
    other = {**PRINCIPAL, "userId": "u2"}
    inaccessible = svc.query("SC01", principal=other, query_id=query_id)
    missing = svc.query("SC01", principal=other, query_id="not-there")
    assert {item["code"] for item in inaccessible["gaps"]} == {
        "QUERY_NOT_FOUND_OR_INACCESSIBLE"
    }
    assert {item["code"] for item in missing["gaps"]} == {
        "QUERY_NOT_FOUND_OR_INACCESSIBLE"
    }


def test_legacy_query_records_are_not_trusted(tmp_path: Path) -> None:
    svc = service(tmp_path)
    legacy_id = svc.store.save_query(
        scenario="SC01",
        scope={"limit": 100},
        payload={"status": "ok", "records": []},
        tenant="t1",
        principal="u1",
        catalog_version=svc.catalog_version,
    )["id"]
    result = svc.query("SC01", principal=PRINCIPAL, query_id=legacy_id)
    assert result["status"] in {"blocked", "needs_clarification"}
    assert "QUERY_LEGACY_CONTRACT" in {item["code"] for item in result["gaps"]}


def test_baseline_completeness_checks_business_keys_and_accepts_empty_sets() -> None:
    catalog = Process360Catalog.from_project(ROOT)
    scope = Scope.from_payload({})
    empty = build_baseline(
        catalog,
        "SC01",
        scope,
        {"status": "ok", "records": [], "queryInfo": {"totalRows": 0, "truncated": False}},
        full_rows=[],
    )
    assert empty["complete"] is True
    assert empty["objectCount"] == 0

    duplicate = build_baseline(
        catalog,
        "SC01",
        scope,
        {"status": "ok", "records": [{"order_id": "o1", "line_no": 1}, {"order_id": "o1", "line_no": 1}], "queryInfo": {"totalRows": 2}},
        full_rows=[{"order_id": "o1", "line_no": 1}, {"order_id": "o1", "line_no": 1}],
    )
    assert duplicate["complete"] is False
    assert duplicate["duplicateObjectCount"] == 1


def test_structure_uses_stored_full_rows_not_the_display_sample(tmp_path: Path) -> None:
    svc = service(tmp_path)
    full_rows = [
        {"customer_id": f"c{index}", "owner_id": "u1", "amount_100m": 1}
        for index in range(600)
    ]
    query_id = stored_query(
        tmp_path,
        scope={"limit": 100},
        payload={"status": "ok", "scope": {"limit": 100}, "records": full_rows[:5], "queryInfo": {"totalRows": 600, "truncated": True}},
        full_rows=full_rows,
        full_count=600,
    )
    result = svc.structure(
        "SC01",
        principal=PRINCIPAL,
        query_id=query_id,
        dimension="customer_id",
        value_field="amount_100m",
        top_n=5,
    )
    assert result["structure"]["totals"]["records"] == 600
    assert result["structure"]["totals"]["complete"] is True
    assert result["structure"]["totals"]["groups"] == 600
