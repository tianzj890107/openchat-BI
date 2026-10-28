"""Frozen baselines and effect closure for Process360.

The catalog's ``closure_calculation`` rows are *examples*: their sample
numerators/denominators must never become live targets.  This module uses only
the row's metric name, direction, target ratio and minimum denominator, and
requires a server-frozen baseline plus an explicit approval reference.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping

from .models import Scope, envelope, gap, metric
from .store import digest

SCENARIO_KEYS: dict[str, tuple[str, ...]] = {
    "SC01": ("order_id", "line_no", "product_id", "plan_id", "plan_date"),
    "SC02": ("quote_id",),
    "SC03": ("customer_id",),
    "SC04": ("bid_id",),
    "SC05": ("order_id", "line_no", "product_id", "ship_date"),
}

CLOSURE_METRIC: dict[str, str] = {
    "SC01": "M36005",
    "SC02": "M36002",
    "SC03": "M36003",
    "SC04": "M36004",
    "SC05": "M36006",
}

RATIO_SCENARIOS = {"SC02", "SC03"}


def object_key(record: Mapping[str, Any], scenario: str) -> str | None:
    fields = SCENARIO_KEYS.get(str(scenario).upper(), ())
    values = [record.get(field) for field in fields if record.get(field) is not None]
    if values:
        return "|".join(str(value) for value in values)
    fallback = sorted(
        (key, value)
        for key, value in record.items()
        if str(key).lower().endswith("_id") and value is not None
    )
    return "|".join(str(value) for _, value in fallback) if fallback else None


def object_keys(records: Iterable[Mapping[str, Any]], scenario: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for record in records or []:
        key = object_key(record, scenario)
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result


def _metric_values(items: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for item in items or []:
        if item.get("value") is None or item.get("status") == "blocked":
            continue
        try:
            result[str(item.get("code"))] = float(item["value"])
        except (TypeError, ValueError, KeyError):
            continue
    return result


def build_baseline(
    catalog: Any,
    scenario: str,
    scope: Scope,
    query: Mapping[str, Any],
    *,
    principal: Mapping[str, Any] | None = None,
    full_rows: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Freeze the object set from the complete server-side result.

    ``full_rows`` must come from a server pass that is not bounded by the
    display ``limit``.  When it is omitted the query's own rows are used and
    completeness is checked against ``queryInfo.totalRows``; an incomplete set
    is recorded as ``complete=false`` and blocks formal effect verification.
    """
    code = str(scenario).upper()
    info = dict(query.get("queryInfo") or {})
    rows = list(full_rows if full_rows is not None else (query.get("records") or []))
    total = int(info.get("totalRows") or 0)
    keys = object_keys(rows, code)
    if full_rows is not None:
        # The server already re-read the full set; only its size matters.
        complete = bool(total) and len(rows) >= total
    else:
        complete = bool(total) and len(rows) >= total and not info.get("truncated")
    metrics = _metric_values(query.get("metrics") or [])
    window = {
        "start": scope.period_start.isoformat() if scope.period_start else None,
        "end": scope.observation_cutoff().isoformat(),
    }
    payload = {
        "scenario": code,
        "catalogId": catalog.catalog_id,
        "catalogVersion": catalog.version,
        "frozenAt": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "scope": scope.to_dict(),
        "observationWindow": window,
        "objectKeys": keys,
        "objectCount": len(keys),
        "fullObjectCount": total or len(rows),
        "frozenObjectCount": len(rows),
        "complete": complete,
        "objectSetHash": digest(sorted(keys)),
        "metrics": metrics,
        "queryStatus": query.get("status"),
        "queryHash": digest({"scenario": code, "scope": scope.to_dict(), "catalog": catalog.version}),
        "principal": dict(principal or {}),
    }
    payload["baselineHash"] = digest(payload)
    return payload


def _compare(value: float, target: float, direction: str) -> bool:
    if direction == "<=":
        return value <= target
    return value >= target


def build_closure(
    catalog: Any,
    scenario: str,
    *,
    baseline: Mapping[str, Any] | None,
    current: Mapping[str, Any],
    approval_ref: str = "",
    approved_target: float | None = None,
    approved_direction: str = "",
    approved_minimum_denominator: int | None = None,
    excluded_keys: Iterable[str] = (),
    exclusion_evidence: Mapping[str, Any] | None = None,
    delivery_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    code = str(scenario).upper()
    row = catalog.get("closure_calculation", code) or {}
    metric_code = CLOSURE_METRIC.get(code, "")
    gaps: list[dict[str, Any]] = []
    if not row:
        return envelope(
            "S07",
            "blocked",
            catalog_id=catalog.catalog_id,
            catalog_version=catalog.version,
            scenario=code,
            gaps=[
                gap(
                    "CLOSURE_FORMULA_MISSING",
                    "该场景没有已批准的关闭演算口径",
                    needed="业务批准该场景的基准/复验公式、方向和最低样本量",
                    impact="不能判定整改是否达标；样例数字不作为生产目标",
                    severity="blocking",
                    source="catalog",
                )
            ],
            closure={"status": "blocked", "canClose": False},
        )
    if not approval_ref.strip():
        gaps.append(
            gap(
                "CLOSURE_APPROVAL_MISSING",
                "缺少批准目标/口径引用",
                needed="提供业务批准记录编号和批准目标",
                impact="不启用本地样例目标，不能判定达标",
                severity="blocking",
                source="runtime",
            )
        )
    baseline_valid = bool(
        baseline
        and str(baseline.get("scenario") or "").upper() == code
        and baseline.get("catalogVersion") == catalog.version
        and (baseline.get("objectKeys") or baseline.get("objectCount") is not None)
        and baseline.get("frozenAt")
        and baseline.get("observationWindow")
        and baseline.get("complete", False)
    )
    if not baseline_valid:
        gaps.append(
            gap(
                "VERIFICATION_BASELINE_MISSING",
                "缺少服务端冻结的完整原始对象集合",
                needed="先用本次分析创建 runId 并冻结全量基准；展示分页不能作为基准",
                impact="无法计算原集合化解比例",
                severity="blocking",
                source="runtime",
            )
        )
    if gaps:
        return envelope(
            "S07",
            "blocked",
            catalog_id=catalog.catalog_id,
            catalog_version=catalog.version,
            scenario=code,
            gaps=gaps,
            closure={"status": "blocked", "canClose": False, "metric": metric_code},
            baseline=dict(baseline or {}),
        )
    baseline = dict(baseline or {})
    target = approved_target
    direction = str(approved_direction or "").strip() or ">="
    minimum = int(approved_minimum_denominator or 1)
    if target is None:
        gaps.append(
            gap(
                "CLOSURE_TARGET_MISSING",
                "缺少业务批准的复验目标",
                needed="提供批准记录中的目标比例、方向和最低样本量",
                impact="catalog 样例数字不作为生产目标",
                severity="blocking",
                source="runtime",
            )
        )
    baseline_keys = [str(item) for item in (baseline.get("objectKeys") or [])]
    current_keys = set(object_keys(current.get("records") or [], code))
    baseline_metrics = {str(key): value for key, value in (baseline.get("metrics") or {}).items()}
    current_metrics = _metric_values(current.get("metrics") or [])
    excluded = {str(item) for item in excluded_keys or []}
    verified_exclusions: set[str] = set()
    if exclusion_evidence:
        for key, evidence in (exclusion_evidence or {}).items():
            if evidence:
                verified_exclusions.add(str(key))
    unverified_exclusion_set = excluded - verified_exclusions
    unverified_exclusions = sorted(unverified_exclusion_set)
    if code in RATIO_SCENARIOS:
        baseline_value = baseline_metrics.get(metric_code)
        current_value = current_metrics.get(metric_code)
        basis = "ratio_metric"
        denominator = int(baseline.get("objectCount") or 0)
        numerator = None
        sample_size = denominator
    elif code == "SC01":
        remaining = {key for key in baseline_keys if key in current_keys}
        resolved = set(baseline_keys) - remaining
        net_resolved = resolved - unverified_exclusion_set
        numerator = len(net_resolved)
        denominator = len(baseline_keys)
        baseline_value = 0.0 if denominator else None
        current_value = (numerator / denominator) if denominator else None
        basis = "object_set"
        sample_size = denominator
    elif code == "SC04":
        remaining = {key for key in baseline_keys if key in current_keys}
        resolved = set(baseline_keys) - remaining
        net_resolved = resolved - unverified_exclusion_set
        numerator = len(net_resolved)
        denominator = len(baseline_keys)
        baseline_value = 0.0 if denominator else None
        current_value = (numerator / denominator) if denominator else None
        basis = "object_set"
        sample_size = denominator
    else:
        baseline_value = None
        current_value = None
        basis = "unsupported"
        numerator = None
        denominator = int(baseline.get("objectCount") or 0)
        sample_size = denominator
    if target is None or current_value is None or basis == "unsupported":
        gaps.append(
            gap(
                "CLOSURE_EVIDENCE_MISSING",
                "关闭演算所需指标不可用",
                needed="补齐批准目标口径和复验期同口径指标",
                impact="不判定达标",
                severity="blocking",
                source="runtime",
            )
        )
    sample_ok = sample_size >= minimum
    met = bool(sample_ok and current_value is not None and target is not None and _compare(float(current_value), float(target), direction))
    if not sample_ok:
        status = "insufficient_sample"
    elif met:
        status = "met"
    else:
        status = "not_met"
    if unverified_exclusions:
        gaps.append(
            gap(
                "EXCLUSION_EVIDENCE_MISSING",
                "部分移出/取消对象没有批准证据",
                needed="逐项提供取消、移出或范围变更的批准回执",
                impact="这些对象不计入净化解，避免伪改善",
                severity="blocking",
                source="runtime",
            )
        )
    delivery_ok = bool(delivery_evidence and delivery_evidence.get("status") in {"accepted", "complete", "provided"})
    can_close = status == "met" and delivery_ok and not unverified_exclusions and not gaps
    closure = {
        "metric": metric_code,
        "name": row.get("演算指标"),
        "basis": basis,
        "baselineRate": baseline_value,
        "currentRate": current_value,
        "target": target,
        "direction": direction,
        "minimumDenominator": minimum,
        "sampleSize": sample_size,
        "numerator": numerator,
        "denominator": denominator,
        "excludedObjects": sorted(excluded),
        "unverifiedExclusions": unverified_exclusions,
        "netResolved": numerator if code in {"SC01", "SC04"} else None,
        "status": status,
        "canClose": can_close,
        "approvalRef": approval_ref,
        "deliveryEvidence": dict(delivery_evidence or {}),
        "note": "只使用冻结基准和批准目标；不读取样例分子/分母。",
    }
    return envelope(
        "S07",
        "ok" if status == "met" else "blocked",
        catalog_id=catalog.catalog_id,
        catalog_version=catalog.version,
        scenario=code,
        metrics=[
            metric(
                metric_code,
                str(catalog.metric(metric_code).get("name") if catalog.metric(metric_code) else metric_code),
                current_value,
                str((catalog.metric(metric_code) or {}).get("单位") or ""),
                status="ok" if status == "met" else "blocked",
                formula=str((catalog.metric(metric_code) or {}).get("计算公式") or ""),
                note="复验指标；目标与基准由服务端冻结记录提供",
            )
        ] if metric_code else [],
        gaps=gaps,
        closure=closure,
        baseline=baseline,
        current={"status": current.get("status"), "metrics": current_metrics},
    )
