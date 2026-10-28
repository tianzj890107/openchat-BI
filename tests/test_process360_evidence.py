from __future__ import annotations

from bi_agent.process360.evidence import validate_cause_evidence
from bi_agent.process360.store import digest


class Catalog:
    def get(self, sheet: str, code: str):
        assert sheet == "evidence_templates"
        return {"code": code, "必需内容": "订单号、原因"}


RUN = {
    "id": "run-1",
    "payload": {
        "objectKeys": ["o1"],
        "observationWindow": {"start": "2026-10-01", "end": "2026-10-27"},
    },
}
CAUSE = {"code": "C1", "name": "排产", "证据模板编码": "EV01", "验证规则编码": "R1"}


def _item(**overrides):
    fields = {"订单号": "o1", "原因": "排产冲突"}
    item = {
        "templateCode": "EV01",
        "source": "system",
        "objectIds": ["o1"],
        "period": {"start": "2026-10-01", "end": "2026-10-27"},
        "fields": fields,
        "hash": digest({"fields": fields, "records": []}),
        "rule": {"code": "R1", "passed": True},
    }
    item.update(overrides)
    return item


def test_hash_alone_does_not_make_untrusted_evidence_verified() -> None:
    report = validate_cause_evidence(Catalog(), [CAUSE], [_item(source="upload")], run=RUN)
    assert report["items"][0]["status"] == "needs_manual_review"
    assert report["items"][0]["verified"] is False


def test_object_period_rule_and_counter_evidence_are_checked_separately() -> None:
    object_mismatch = validate_cause_evidence(
        Catalog(), [CAUSE], [_item(objectIds=["other"])], run=RUN
    )["items"][0]
    assert object_mismatch["status"] != "verified"
    period_mismatch = validate_cause_evidence(
        Catalog(), [CAUSE], [_item(period={"start": "2025-01-01", "end": "2025-01-31"})], run=RUN
    )["items"][0]
    assert period_mismatch["status"] != "verified"
    rule_failed = validate_cause_evidence(
        Catalog(), [CAUSE], [_item(rule={"code": "R1", "passed": False})], run=RUN
    )["items"][0]
    assert rule_failed["status"] == "contradicted"
    counter = validate_cause_evidence(
        Catalog(), [CAUSE], [_item(contradicts=True)], run=RUN
    )["items"][0]
    assert counter["status"] == "contradicted"


def test_complete_trusted_evidence_can_be_verified() -> None:
    report = validate_cause_evidence(Catalog(), [CAUSE], [_item()], run=RUN)
    assert report["items"][0]["verified"] is True
    assert report["items"][0]["status"] == "verified"
