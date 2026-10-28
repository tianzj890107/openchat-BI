from __future__ import annotations

from bi_agent.process360.advanced import (
    compare_metrics,
    process_conversion,
    rule_forecast,
    structure_from_records,
    validate_solution_structure,
)


def test_multi_period_comparison_never_divides_by_zero() -> None:
    result = compare_metrics(
        {"metrics": [{"code": "M1", "value": 10, "status": "ok"}]},
        {"metrics": [{"code": "M1", "value": 0, "status": "ok"}]},
    )
    assert result["rows"][0]["change"] == 10
    assert result["rows"][0]["changeRate"] is None
    assert result["rows"][0]["zeroBase"] is True


def test_structure_marks_truncated_and_unknown_dimensions() -> None:
    result = structure_from_records(
        [
            {"customer_name": "客户一", "amount_100m": 2},
            {"customer_name": "", "amount_100m": 1},
        ],
        truncated=True,
    )
    assert result["status"] == "partial"
    assert result["totals"]["truncated"] is True
    assert result["totals"]["unknown"] == 1
    assert result["groups"][0]["share"] == 2 / 3


def test_process_conversion_needs_object_batches() -> None:
    blocked = process_conversion([])
    assert blocked["status"] == "blocked"
    ok = process_conversion(
        [
            {"objectId": "o1", "batchId": "b1", "stage": "立项", "completedAt": "2026-10-01"},
            {"objectId": "o1", "batchId": "b1", "stage": "投标"},
        ]
    )
    assert ok["objects"] == 1 and ok["batches"] == 1


def test_forecast_is_explicitly_a_rule_estimate() -> None:
    blocked = rule_forecast(actual_to_date=10, target=30, elapsed_days=10, total_days=30)
    assert blocked["status"] == "blocked"
    result = rule_forecast(
        actual_to_date=10,
        target=30,
        elapsed_days=10,
        total_days=30,
        assumption="按当前日均线性推进",
    )
    assert result["projected"] == 30
    assert result["confidenceInterval"] is None
    assert result["kind"] == "rule_estimate"


def test_solution_validation_is_structural_not_a_fake_score() -> None:
    result = validate_solution_structure(
        [{"id": "t1", "ownerRole": "RO01", "acceptance": "完成", "requires": {"approval": "审批"}}]
    )
    assert result["status"] in {"ok", "partial"}
    assert result["scored"] is False
