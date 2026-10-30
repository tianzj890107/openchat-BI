"""Deterministic evidence validation for candidate causes.

A hash proves that a payload did not change; it does not prove that the source
is trustworthy, the object/period matches the run, or the named rule passed.
This module keeps those checks separate and never promotes a cause to
``verified`` when any of them is missing.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Iterable, Mapping

from .models import as_date
from .store import digest

TRUSTED_SOURCES = {"approved_system", "system", "manual_verified"}
REVIEW_SOURCES = {"manual", "host", "attachment", "upload"}
STATUS_ORDER = {
    "verified": 5,
    "needs_manual_review": 4,
    "unverified": 3,
    "integrity_failed": 2,
    "contradicted": 1,
}


def _codes(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in re.split(r"[、,，;；\s]+", str(value or "")) if item.strip()]


def _required_tokens(template: Mapping[str, Any]) -> list[str]:
    raw = str(template.get("必需内容") or template.get("requiredContent") or "")
    return [item.strip(" 。；;，,") for item in re.split(r"[、，,；;]", raw) if item.strip()]


def _period(value: Any) -> tuple[str | None, str | None]:
    if not isinstance(value, Mapping):
        return None, None
    start = as_date(value.get("start") or value.get("from") or value.get("periodStart"))
    end = as_date(value.get("end") or value.get("to") or value.get("periodEnd"))
    return (start.isoformat() if start else None, end.isoformat() if end else None)


def _overlaps(left: tuple[str | None, str | None], right: tuple[str | None, str | None]) -> bool:
    lstart, lend = left
    rstart, rend = right
    if not lstart or not rstart:
        return False
    return (not lend or lstart <= (rend or "9999-12-31")) and (not rend or rstart <= (lend or "9999-12-31"))


def _object_keys(run: Mapping[str, Any]) -> set[str]:
    payload = run.get("payload") or {}
    keys = payload.get("objectKeys") or payload.get("object_ids") or []
    if isinstance(keys, Mapping):
        keys = list(keys)
    return {str(item) for item in keys if str(item).strip()}


def _window(run: Mapping[str, Any]) -> tuple[str | None, str | None]:
    payload = run.get("payload") or {}
    return _period(payload.get("observationWindow") or payload.get("window") or payload.get("scope"))


def _field_coverage(template: Mapping[str, Any], item: Mapping[str, Any]) -> dict[str, Any]:
    required = _required_tokens(template)
    fields = item.get("fields") if isinstance(item.get("fields"), Mapping) else {}
    records = item.get("records") if isinstance(item.get("records"), list) else []
    keys = {str(key).lower() for key in fields}
    for record in records:
        if isinstance(record, Mapping):
            keys.update(str(key).lower() for key in record)
    missing = []
    for token in required:
        probe = re.sub(r"[（(].*?[）)]", "", token).strip()
        probes = [probe[:max(2, min(6, len(probe)))]]
        if not any(any(p.lower() in key for key in keys) for p in probes if p):
            missing.append(token)
    complete = item.get("contentComplete")
    if complete is None:
        complete = bool(required) and not missing
    return {"required": required, "missing": missing, "complete": bool(complete)}


def _check_item(
    template: Mapping[str, Any],
    item: Mapping[str, Any],
    *,
    run: Mapping[str, Any],
    cause_rule: str,
    observed_objects: set[str],
) -> dict[str, Any]:
    reasons: list[str] = []
    source = str(item.get("source") or "").strip()
    source_key = source.lower().split(":", 1)[0]
    trusted = source_key in TRUSTED_SOURCES
    if not trusted:
        reasons.append("SOURCE_NOT_TRUSTED")
    integrity = "unverified"
    supplied_hash = str(item.get("hash") or "").strip()
    material = {"fields": item.get("fields") or {}, "records": item.get("records") or []}
    if supplied_hash:
        integrity = "verified" if supplied_hash == digest(material) else "failed"
        if integrity == "failed":
            reasons.append("INTEGRITY_HASH_MISMATCH")
    period = _period(item.get("period") or item.get("observationWindow"))
    if not _overlaps(period, _window(run)):
        reasons.append("PERIOD_MISMATCH")
    object_ids = {str(value) for value in (item.get("objectIds") or item.get("object_ids") or []) if str(value).strip()}
    if not object_ids or not (object_ids & observed_objects):
        reasons.append("OBJECT_MISMATCH")
    rule = item.get("rule") if isinstance(item.get("rule"), Mapping) else {}
    rule_code = str(rule.get("code") or item.get("ruleCode") or "").strip()
    passed = rule.get("passed")
    if not rule_code or (cause_rule and rule_code != cause_rule):
        reasons.append("RULE_NOT_PROVIDED")
    if passed is False:
        reasons.append("RULE_FAILED")
    coverage = _field_coverage(template, item)
    if not coverage["complete"]:
        reasons.append("REQUIRED_CONTENT_INCOMPLETE")
    if item.get("contradicts") is True or item.get("contradicting") or item.get("counterEvidence"):
        reasons.append("COUNTER_EVIDENCE")
    if reasons:
        status = "contradicted" if "COUNTER_EVIDENCE" in reasons or "RULE_FAILED" in reasons else (
            "integrity_failed" if "INTEGRITY_HASH_MISMATCH" in reasons else "needs_manual_review"
        )
    else:
        status = "verified"
    return {
        "templateCode": str(item.get("templateCode") or item.get("code") or template.get("code") or ""),
        "source": source,
        "sourceTrusted": trusted,
        "integrity": integrity,
        "period": {"start": period[0], "end": period[1]},
        "objectIds": sorted(object_ids),
        "rule": {"code": rule_code, "passed": passed},
        "fieldCoverage": coverage,
        "status": status,
        "reasons": reasons,
        "note": "哈希只证明内容未变化；来源、对象/期间、规则和反证分别校验。",
    }


def validate_cause_evidence(
    catalog: Any,
    causes: Iterable[Mapping[str, Any]],
    evidence_items: Iterable[Mapping[str, Any]],
    *,
    run: Mapping[str, Any],
) -> dict[str, Any]:
    items = [dict(item) for item in (evidence_items or []) if isinstance(item, Mapping)]
    by_template: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        code = str(item.get("templateCode") or item.get("code") or "").strip()
        if code:
            by_template.setdefault(code, []).append(item)
    observed = _object_keys(run)
    results: list[dict[str, Any]] = []
    for cause in causes:
        cause_code = str(cause.get("code") or "")
        templates = _codes(cause.get("证据模板编码") or cause.get("evidenceTemplates"))
        rule_code = str(cause.get("验证规则编码") or cause.get("verificationRule") or "").strip()
        checks: list[dict[str, Any]] = []
        missing: list[str] = []
        for template_code in templates:
            template = catalog.get("evidence_templates", template_code) or {"code": template_code}
            supplied = by_template.get(template_code) or []
            if not supplied:
                missing.append(template_code)
                continue
            for item in supplied:
                checks.append(_check_item(template, item, run=run, cause_rule=rule_code, observed_objects=observed))
        statuses = [check["status"] for check in checks]
        if missing:
            status = "unverified"
            reasons = ["REQUIRED_EVIDENCE_MISSING"]
        elif any(value == "contradicted" for value in statuses):
            status, reasons = "contradicted", ["COUNTER_EVIDENCE_OR_RULE_FAILED"]
        elif any(value == "integrity_failed" for value in statuses):
            status, reasons = "integrity_failed", ["INTEGRITY_HASH_MISMATCH"]
        elif any(value == "needs_manual_review" for value in statuses):
            status, reasons = "needs_manual_review", ["SOURCE_RULE_OR_CONTENT_REVIEW_REQUIRED"]
        elif statuses and all(value == "verified" for value in statuses):
            status, reasons = "verified", []
        else:
            status, reasons = "unverified", ["NO_VALID_EVIDENCE"]
        results.append(
            {
                "code": cause_code,
                "name": cause.get("name") or cause.get("原因名称") or cause_code,
                "requiredTemplates": templates,
                "missingTemplates": missing,
                "rule": rule_code,
                "status": status,
                "verified": status == "verified",
                "manualReviewRequired": status in {"needs_manual_review", "integrity_failed", "unverified"},
                "reasons": reasons,
                "checks": checks,
                "note": "只有来源可信、对象/期间匹配、验证规则通过且无反证时才标记 verified。",
            }
        )
    return {"items": results, "status": "ok" if results else "not_applicable"}


def apply_evidence(
    catalog: Any,
    analysis: Mapping[str, Any],
    evidence_items: Iterable[Mapping[str, Any]],
    *,
    run: Mapping[str, Any],
) -> dict[str, Any]:
    result = deepcopy(dict(analysis))
    report = validate_cause_evidence(catalog, result.get("candidateCauses") or [], evidence_items, run=run)
    by_code = {item["code"]: item for item in report["items"]}
    for cause in result.get("candidateCauses") or []:
        check = by_code.get(str(cause.get("code") or ""))
        if not check:
            continue
        cause["evidenceStatus"] = check["status"]
        cause["evidenceVerified"] = check["verified"]
        cause["manualReviewRequired"] = check["manualReviewRequired"]
        cause["evidenceChecks"] = check["checks"]
        cause["status"] = "verified" if check["verified"] else "candidate_unverified"
        if check["status"] == "contradicted":
            cause["status"] = "contradicted"
        elif check["status"] == "needs_manual_review":
            cause["status"] = "needs_manual_review"
    result["evidenceValidation"] = report
    verified = [item["code"] for item in report["items"] if item["verified"]]
    result["verifiedCauses"] = verified
    result["rootCauseStatus"] = "verified" if verified else "candidate_or_blocked"
    return result
