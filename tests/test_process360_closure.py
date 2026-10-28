from __future__ import annotations

from bi_agent.process360.closure import build_closure
from bi_agent.process360.catalog import Process360Catalog


def catalog() -> Process360Catalog:
    return Process360Catalog.from_project(".")


def baseline(keys=None):
    return {
        "scenario": "SC01",
        "catalogVersion": catalog().version,
        "frozenAt": "2026-10-28T00:00:00Z",
        "observationWindow": {"start": "2026-10-01", "end": "2026-10-27"},
        "objectKeys": keys or ["o1|1|p1|plan1|2026-10-01", "o2|1|p1|plan2|2026-10-02"],
        "objectCount": 2,
        "fullObjectCount": 2,
        "frozenObjectCount": 2,
        "complete": True,
        "objectSetHash": "hash",
        "metrics": {"M36005": 0.0},
    }


def current(*order_ids):
    return {
        "status": "ok",
        "records": [
            {"order_id": order, "line_no": 1, "product_id": "p1", "plan_id": "plan", "plan_date": "2026-10-01"}
            for order in order_ids
        ],
        "metrics": [],
    }


def test_closure_requires_approved_baseline_target_and_delivery_evidence() -> None:
    missing_approval = build_closure(
        catalog(), "SC01", baseline=baseline(), current=current(), approved_target=0.5
    )
    assert missing_approval["status"] == "blocked"
    assert "CLOSURE_APPROVAL_MISSING" in {item["code"] for item in missing_approval["gaps"]}
    missing_target = build_closure(
        catalog(), "SC01", baseline=baseline(), current=current(), approval_ref="AP-1"
    )
    assert "CLOSURE_TARGET_MISSING" in {item["code"] for item in missing_target["gaps"]}


def test_closure_uses_frozen_object_set_and_never_catalog_sample_numerator() -> None:
    result = build_closure(
        catalog(),
        "SC01",
        baseline=baseline(["a", "b"]),
        current={"status": "ok", "records": [{"order_id": "b"}], "metrics": []},
        approval_ref="AP-1",
        approved_target=0.5,
        delivery_evidence={"status": "accepted"},
    )
    assert result["closure"]["numerator"] == 1
    assert result["closure"]["denominator"] == 2
    assert result["closure"]["canClose"] is True
    assert result["closure"]["target"] == 0.5


def test_unverified_exclusion_never_counts_as_improvement() -> None:
    result = build_closure(
        catalog(),
        "SC01",
        baseline=baseline(["a", "b"]),
        current={"status": "ok", "records": [{"order_id": "b"}], "metrics": []},
        approval_ref="AP-1",
        approved_target=0.4,
        excluded_keys=["a"],
        delivery_evidence={"status": "accepted"},
    )
    assert result["closure"]["unverifiedExclusions"] == ["a"]
    assert result["closure"]["canClose"] is False
    verified = build_closure(
        catalog(),
        "SC01",
        baseline=baseline(["a", "b"]),
        current={"status": "ok", "records": [{"order_id": "b"}], "metrics": []},
        approval_ref="AP-1",
        approved_target=0.5,
        excluded_keys=["a"],
        exclusion_evidence={"a": {"status": "approved"}},
        delivery_evidence={"status": "accepted"},
    )
    assert verified["closure"]["canClose"] is True


def test_sc05_without_approved_formula_is_explicitly_blocked() -> None:
    result = build_closure(
        catalog(), "SC05", baseline=baseline(), current=current(), approval_ref="AP-1", approved_target=0.5
    )
    assert result["status"] == "blocked"
    assert "CLOSURE_FORMULA_MISSING" in {item["code"] for item in result["gaps"]}


def test_incomplete_frozen_set_blocks_formal_closure() -> None:
    from bi_agent.process360.closure import build_baseline
    from bi_agent.process360.models import Scope

    query = {
        "status": "partial",
        "records": [{"order_id": "o1", "line_no": 1, "product_id": "p1", "plan_id": "x", "plan_date": "2026-10-01"}],
        "metrics": [],
        "queryInfo": {"totalRows": 2102, "truncated": True},
    }
    frozen = build_baseline(catalog(), "SC01", Scope.from_payload({}), query)
    assert frozen["complete"] is False
    assert frozen["fullObjectCount"] == 2102
    assert frozen["frozenObjectCount"] == 1

    blocked = build_closure(
        catalog(),
        "SC01",
        baseline=frozen,
        current=current("o1"),
        approval_ref="AP-1",
        approved_target=0.5,
    )
    assert blocked["status"] == "blocked"
    assert "VERIFICATION_BASELINE_MISSING" in {item["code"] for item in blocked["gaps"]}
