from __future__ import annotations

from pathlib import Path

from bi_agent.process360.identity import PrincipalScope
from bi_agent.process360.service import Process360Service
from bi_agent.process360.store import Process360Store


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
    )["id"]

    owner = PrincipalScope.from_payload({"tenantId": "t1", "userId": "u1", "grantKind": "all"})
    reused = svc._reuse_query(query_id, "SC01", owner)
    assert reused is not None
    assert reused["queryReused"] is True
    assert reused["queryId"] == query_id

    other = PrincipalScope.from_payload({"tenantId": "t1", "userId": "u2", "grantKind": "all"})
    assert svc._reuse_query(query_id, "SC01", other) is None
    assert svc._reuse_query(query_id, "SC02", owner) is None
