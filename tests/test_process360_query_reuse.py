from __future__ import annotations

from pathlib import Path
from datetime import date

from bi_agent.process360.catalog import Process360Catalog
from bi_agent.process360.identity import PrincipalScope
from bi_agent.process360.service import QUERY_CONTRACT_VERSION, QUERY_TEMPLATE_VERSION, Process360Service
from bi_agent.process360.store import Process360Store
from tests.test_process360_engine import FakeDB

ROOT = Path(__file__).resolve().parents[1]
PRINCIPAL = {
    "tenantId": "t1",
    "userId": "u1",
    "grantKind": "all",
    "authorizationVersion": "auth-v1",
}


def service(tmp_path: Path) -> Process360Service:
    store = Process360Store(tmp_path / "runtime.sqlite3")
    return Process360Service(cwd=".", store=store, db=object())


def test_compact_query_keeps_summary_and_bounds_rows(tmp_path: Path) -> None:
    rows = [{"order_id": f"o{index}", "line_no": 1} for index in range(2000)]
    payload = {
        "status": "partial",
        "records": rows,
        "queryInfo": {"totalRows": 2000, "truncated": False},
        "evidence": [{"id": "EV01", "records": rows}],
        "queryId": "q1",
    }
    compact = Process360Service.compact_query(payload, sample=5)
    assert "records" not in compact
    assert len(compact["sampleRecords"]) == 5
    assert compact["recordsRef"] == {
        "queryId": "q1",
        "rowCount": 2000,
        "totalRows": 2000,
        "sampleSize": 5,
        "truncated": False,
    }
    assert compact["evidence"][0]["recordCount"] == 2000
    assert len(compact["evidence"][0]["sampleRecords"]) == 2


def test_stored_query_is_reused_only_for_the_same_principal(tmp_path: Path) -> None:
    svc = service(tmp_path)
    query_id = svc.store.save_query(
        scenario="SC01",
        scope={"limit": 100},
        payload={"status": "ok", "records": [{"order_id": "o1"}]},
        tenant="t1",
        principal="u1",
        catalog_version=svc.catalog_version,
        catalog_hash=svc._catalog_hash(),
        authorization_version="test-auth-v1",
        grant_fingerprint=PrincipalScope.from_payload(
            {
                "tenantId": "t1",
                "userId": "u1",
                "grantKind": "all",
                "authorizationVersion": "test-auth-v1",
            }
        ).grant_fingerprint,
        source_connection="database:test",
        template_version=QUERY_TEMPLATE_VERSION,
        complete=True,
        full_count=1,
        expires_at=9999999999,
        full_rows=[{"order_id": "o1"}],
        contract_version=QUERY_CONTRACT_VERSION,
    )["id"]

    owner = PrincipalScope.from_payload(
        {"tenantId": "t1", "userId": "u1", "grantKind": "all", "authorizationVersion": "test-auth-v1"}
    )
    reused, issue = svc._reuse_query(query_id, "SC01", owner)
    assert issue is None
    assert reused is not None
    assert reused["queryReused"] is True
    assert reused["queryId"] == query_id

    other = PrincipalScope.from_payload(
        {"tenantId": "t1", "userId": "u2", "grantKind": "all", "authorizationVersion": "test-auth-v1"}
    )
    assert svc._reuse_query(query_id, "SC01", other)[0] is None
    assert svc._reuse_query(query_id, "SC02", owner)[0] is None


def test_stored_query_is_not_reused_after_the_source_connection_changes(tmp_path: Path) -> None:
    svc = service(tmp_path)
    identity = PrincipalScope.from_payload(
        {
            "tenantId": "t1",
            "userId": "u1",
            "grantKind": "all",
            "authorizationVersion": "test-auth-v1",
        }
    )
    query_id = svc.store.save_query(
        scenario="SC01",
        scope={"limit": 100},
        payload={"status": "ok", "records": [{"order_id": "o1"}]},
        tenant="t1",
        principal="u1",
        catalog_version=svc.catalog_version,
        catalog_hash=svc._catalog_hash(),
        authorization_version="test-auth-v1",
        grant_fingerprint=identity.grant_fingerprint,
        source_connection="pg:old-db:5432/ywln#ywln_crm",
        template_version=QUERY_TEMPLATE_VERSION,
        complete=True,
        full_count=1,
        expires_at=9999999999,
        full_rows=[{"order_id": "o1"}],
        contract_version=QUERY_CONTRACT_VERSION,
    )["id"]
    svc.db = type(
        "ChangedDB",
        (),
        {"config": type("Config", (), {"public_dict": lambda _self: {
            "host": "new-db", "port": 5432, "database": "ywln", "schema": "ywln_crm",
        }})()},
    )()
    reused, issue = svc._reuse_query(query_id, "SC01", identity)
    assert reused is None
    assert issue is not None
    assert issue["code"] == "QUERY_SOURCE_CONNECTION_CHANGED"


def test_draft_reuses_the_query_id_without_a_second_database_read(
    tmp_path: Path, monkeypatch
) -> None:
    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 27)

    monkeypatch.setattr("bi_agent.process360.models.date", FixedDate)
    monkeypatch.setattr("bi_agent.process360.queries.date", FixedDate)
    db = FakeDB()
    svc = Process360Service(
        catalog=Process360Catalog.from_project(ROOT),
        db=db,
        store=Process360Store(tmp_path / "runtime.sqlite3"),
        cwd=ROOT,
    )
    query = svc.query("SC01", scope={"periodEnd": "2026-10-27"}, principal=PRINCIPAL)
    assert query["queryId"]
    calls = len(db.calls)
    draft = svc.draft(
        scenario="SC01",
        scope={"periodEnd": "2026-10-27"},
        query_id=query["queryId"],
        principal={**PRINCIPAL, "canDispatch": True},
    )
    assert draft["status"] == "ok"
    assert draft["queryId"] == query["queryId"]
    assert len(db.calls) == calls
