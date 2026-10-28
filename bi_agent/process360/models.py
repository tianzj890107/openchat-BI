"""Shared, JSON-safe result models for Process360 S00-S07.

Every stage returns the same envelope.  A caller can therefore concatenate
stages without guessing which fields exist, and a blocked stage is explicit
rather than represented by zero/empty data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping

RESULT_SCHEMA = "process360.result.v1"
STATUS_VALUES = ("ok", "partial", "blocked", "needs_clarification", "not_applicable")
GAP_SEVERITIES = ("blocking", "degrading", "informational")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def iso_date(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"invalid date: {value!r}") from exc


def as_date(value: date | datetime | str | None) -> date | None:
    text = iso_date(value)
    return date.fromisoformat(text) if text else None


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, Iterable) and not isinstance(value, (bytes, Mapping)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


@dataclass(frozen=True)
class Scope:
    """Validated query scope supplied by the caller/Fuxi host."""

    as_of: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    customer_ids: tuple[str, ...] = ()
    owner_ids: tuple[str, ...] = ()
    product_ids: tuple[str, ...] = ()
    limit: int = 100
    include_current_snapshot: bool = False

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any] | None, *, today: date | None = None
    ) -> "Scope":
        if payload is not None and not isinstance(payload, Mapping):
            raise ValueError("scope must be an object")
        raw = dict(payload or {})
        aliases = {
            "asOf": "as_of",
            "periodStart": "period_start",
            "periodEnd": "period_end",
            "customerIds": "customer_ids",
            "ownerIds": "owner_ids",
            "productIds": "product_ids",
            "includeCurrentSnapshot": "include_current_snapshot",
        }
        unknown = set(raw) - set(aliases) - set(aliases.values()) - {"limit"}
        if unknown:
            raise ValueError("scope contains unsupported fields")
        for key, alias in aliases.items():
            if key in raw and alias in raw and raw[key] != raw[alias]:
                raise ValueError(f"conflicting scope fields: {key}")
        for key in ["customerIds", "ownerIds", "productIds"]:
            value = raw.get(key, raw.get(aliases[key], []))
            if (
                not isinstance(value, (list, tuple))
                or len(value) > 500
                or any(not isinstance(v, str) or not v.strip() for v in value)
            ):
                raise ValueError(f"{key} must contain non-empty string IDs (maximum 500)")
        today = today or date.today()
        explicit_as_of = as_date(raw.get("asOf") or raw.get("as_of"))
        start = as_date(raw.get("periodStart") or raw.get("period_start"))
        explicit_end = as_date(raw.get("periodEnd") or raw.get("period_end"))
        if explicit_as_of and explicit_end and explicit_as_of != explicit_end:
            raise ValueError("asOf must match periodEnd when both are supplied")
        end = explicit_end or explicit_as_of or today
        if end > today:
            end = today
        as_of = explicit_as_of or end
        if as_of > today:
            as_of = today
        if start is None:
            start = date(end.year, end.month, 1)
        if start > end:
            raise ValueError("periodStart must not be later than periodEnd")
        limit = raw.get("limit", 100)
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("limit must be an integer between 1 and 500")
        include_current = raw.get(
            "includeCurrentSnapshot", raw.get("include_current_snapshot", False)
        )
        if not isinstance(include_current, bool):
            raise ValueError("includeCurrentSnapshot must be a boolean")
        return cls(
            as_of=as_of,
            period_start=start,
            period_end=end,
            customer_ids=tuple(as_list(raw.get("customerIds") or raw.get("customer_ids"))),
            owner_ids=tuple(as_list(raw.get("ownerIds") or raw.get("owner_ids"))),
            product_ids=tuple(as_list(raw.get("productIds") or raw.get("product_ids"))),
            limit=limit,
            include_current_snapshot=include_current,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "asOf": iso_date(self.as_of),
            "periodStart": iso_date(self.period_start),
            "periodEnd": iso_date(self.period_end),
            "customerIds": list(self.customer_ids),
            "ownerIds": list(self.owner_ids),
            "productIds": list(self.product_ids),
            "limit": self.limit,
            "includeCurrentSnapshot": self.include_current_snapshot,
        }

    def observation_cutoff(self, today: date | None = None) -> date:
        today = today or date.today()
        return min(self.as_of or today, today)


def gap(
    code: str,
    title: str,
    *,
    needed: str = "",
    impact: str = "",
    severity: str = "blocking",
    source: str = "catalog",
) -> dict[str, Any]:
    return {
        "code": str(code),
        "title": str(title),
        "needed": str(needed),
        "impact": str(impact),
        "severity": severity if severity in GAP_SEVERITIES else "blocking",
        "source": source,
    }


def evidence(
    code: str,
    name: str,
    *,
    source: str = "",
    observed_at: str | None = None,
    records: Iterable[Mapping[str, Any]] | None = None,
    limitations: Iterable[str] | None = None,
) -> dict[str, Any]:
    return {
        "code": str(code),
        "name": str(name),
        "source": str(source),
        "observedAt": observed_at,
        "records": [dict(row) for row in (records or [])],
        "limitations": [str(item) for item in (limitations or [])],
    }


def metric(
    code: str,
    name: str,
    value: float | int | None,
    unit: str = "",
    *,
    status: str = "ok",
    formula: str = "",
    reference: Any = None,
    note: str = "",
    evidence: str = "",
    caliber: str = "",
) -> dict[str, Any]:
    if status not in STATUS_VALUES:
        raise ValueError(f"invalid metric status: {status}")
    return {
        "code": str(code),
        "name": str(name),
        "value": value,
        "unit": unit,
        "status": status,
        "formula": formula,
        "reference": reference,
        "note": note,
        "evidence": evidence,
        "caliber": caliber,
    }


def envelope(
    stage: str,
    status: str,
    *,
    catalog_id: str = "",
    catalog_version: str = "",
    scenario: str | None = None,
    question: str | None = None,
    scope: Scope | Mapping[str, Any] | None = None,
    metrics: Iterable[Mapping[str, Any]] | None = None,
    records: Iterable[Mapping[str, Any]] | None = None,
    evidence_items: Iterable[Mapping[str, Any]] | None = None,
    gaps: Iterable[Mapping[str, Any]] | None = None,
    limitations: Iterable[str] | None = None,
    next_steps: Iterable[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    if status not in STATUS_VALUES:
        raise ValueError(f"invalid result status: {status}")
    if isinstance(scope, Scope):
        scope_payload = scope.to_dict()
    elif scope is None:
        scope_payload = None
    else:
        scope_payload = dict(scope)
    payload: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "stage": stage,
        "status": status,
        "catalogId": catalog_id,
        "catalogVersion": catalog_version,
        "scenario": scenario,
        "question": question,
        "scope": scope_payload,
        "generatedAt": utc_now(),
        "metrics": [dict(item) for item in (metrics or [])],
        "records": [dict(item) for item in (records or [])],
        "evidence": [dict(item) for item in (evidence_items or [])],
        "gaps": [dict(item) for item in (gaps or [])],
        "limitations": [str(item) for item in (limitations or [])],
        "nextSteps": [str(item) for item in (next_steps or [])],
    }
    payload.update(extra)
    return payload


def combine_status(values: Iterable[str], *, none: str = "blocked") -> str:
    statuses = [value for value in values if value]
    if not statuses:
        return none
    if all(value == "ok" for value in statuses):
        return "ok"
    if "blocked" in statuses and not any(value in {"ok", "partial"} for value in statuses):
        return "blocked"
    if "needs_clarification" in statuses:
        return "needs_clarification"
    if any(value in {"blocked", "partial"} for value in statuses):
        return "partial"
    return statuses[0]


def dedupe_gaps(items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        code = str(item.get("code") or item.get("title") or "")
        key = code or str(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(item))
    return result


def dedupe_evidence(items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        code = str(item.get("code") or item.get("name") or "")
        if code in seen:
            continue
        seen.add(code)
        result.append(dict(item))
    return result


@dataclass(frozen=True)
class RouteDecision:
    sop_id: str
    sop_title: str
    scenario: str | None
    intent: str
    skills: tuple[str, ...]
    required_inputs: tuple[str, ...]
    clarification: tuple[str, ...] = ()
    candidate_scenarios: tuple[str, ...] = ()
    confidence: str = "rule"
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sop": self.sop_id,
            "sopTitle": self.sop_title,
            "scenario": self.scenario,
            "candidateScenarios": list(self.candidate_scenarios),
            "intent": self.intent,
            "skills": list(self.skills),
            "requiredInputs": list(self.required_inputs),
            "clarification": list(self.clarification),
            "confidence": self.confidence,
            "reasons": list(self.reasons),
        }
