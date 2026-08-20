"""Generic reliability primitives for BI analysis.

This module deliberately knows nothing about a particular business domain.  It
is the small deterministic layer between tool output and an LLM narrative:
scope/semantics/provenance are carried forward, claims are typed, and unsafe
comparisons are reported instead of silently normalised.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from enum import Enum
import math
import re
from typing import Any, Iterable, Mapping, Sequence


class SemanticType(str, Enum):
    OBSERVED = "OBSERVED"
    CALCULATED = "CALCULATED"
    DERIVED = "DERIVED"
    ESTIMATED = "ESTIMATED"
    FORECAST = "FORECAST"
    PROXY = "PROXY"


class ClaimLevel(str, Enum):
    FACT = "FACT"
    ASSOCIATION = "ASSOCIATION"
    INFERENCE = "INFERENCE"
    VERIFIED = "VERIFIED"


class LimitationType(str, Enum):
    DATA_MISSING = "DATA_MISSING"
    SEMANTIC_MISSING = "SEMANTIC_MISSING"
    RELATION_MISSING = "RELATION_MISSING"
    CAPABILITY_MISSING = "CAPABILITY_MISSING"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    SCOPE_CONFLICT = "SCOPE_CONFLICT"
    UNIT_CONFLICT = "UNIT_CONFLICT"
    SEMANTIC_CONFLICT = "SEMANTIC_CONFLICT"


class RelationType(str, Enum):
    ONTOLOGY_RELATION = "ONTOLOGY_RELATION"
    PATH_RELATION = "PATH_RELATION"
    SHARED_ATTRIBUTE = "SHARED_ATTRIBUTE"
    TEMPORAL_ASSOCIATION = "TEMPORAL_ASSOCIATION"
    HIERARCHICAL_RELATION = "HIERARCHICAL_RELATION"
    STATISTICAL_ASSOCIATION = "STATISTICAL_ASSOCIATION"


class ValidationStatus(str, Enum):
    ALLOW = "ALLOW"
    ALLOW_WITH_WARNING = "ALLOW_WITH_WARNING"
    REJECT = "REJECT"


@dataclass(frozen=True)
class AnalysisContext:
    subject: Any = None
    goal: Any = None
    metrics: tuple[Any, ...] = ()
    dimensions: tuple[Any, ...] = ()
    filters: tuple[Any, ...] = ()
    time_scope: Any = None
    entity_scope: tuple[Any, ...] = ()
    comparison_scope: Any = None

    def merge(self, changes: Mapping[str, Any]) -> "AnalysisContext":
        """Apply only explicitly supplied fields; omitted scope is inherited."""
        allowed = {f.name for f in self.__dataclass_fields__.values()}
        values: dict[str, Any] = {}
        for key, value in changes.items():
            if key not in allowed:
                continue
            if key in {"metrics", "dimensions", "filters", "entity_scope"}:
                value = tuple(value or ())
            values[key] = value
        return replace(self, **values)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass(frozen=True)
class Provenance:
    source: str = ""
    table: str = ""
    view: str = ""
    api: str = ""
    metric_code: str = ""
    query: str = ""
    query_id: str = ""
    timestamp: str = ""


@dataclass(frozen=True)
class Measure:
    name: str
    value: Any
    unit: str = ""
    semantic_type: SemanticType = SemanticType.OBSERVED
    aggregation: str = ""
    scope: Mapping[str, Any] = field(default_factory=dict)
    source: Provenance | None = None


@dataclass(frozen=True)
class QueryResult:
    data: Any
    scope: Mapping[str, Any] = field(default_factory=dict)
    semantic: Mapping[str, Any] = field(default_factory=dict)
    provenance: Provenance = field(default_factory=Provenance)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["provenance"] = asdict(self.provenance)
        return result


@dataclass(frozen=True)
class ValidationResult:
    status: ValidationStatus
    issues: tuple[str, ...] = ()
    limitations: tuple[LimitationType, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status != ValidationStatus.REJECT


@dataclass(frozen=True)
class ReconciliationResult:
    status: ValidationStatus
    parent_value: float | None
    child_value: float | None
    difference: float | None
    tolerance: float
    issues: tuple[str, ...] = ()
    limitations: tuple[LimitationType, ...] = ()


@dataclass(frozen=True)
class Association:
    from_entity: Any
    to_entity: Any
    relation_type: RelationType
    path: tuple[Any, ...] = ()
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class Claim:
    id: str
    statement: str
    level: ClaimLevel
    scope: Mapping[str, Any] = field(default_factory=dict)
    supports: tuple[str, ...] = ()
    limitations: tuple[LimitationType | str, ...] = ()
    confidence: float | None = None
    semantic: Mapping[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None


@dataclass(frozen=True)
class Observation:
    id: str
    statement: str
    scope: Mapping[str, Any] = field(default_factory=dict)
    semantic: Mapping[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None


def claim_from_observation(observation: Observation) -> Claim:
    return Claim(observation.id, observation.statement, ClaimLevel.FACT,
                 observation.scope, supports=(observation.id,), semantic=observation.semantic,
                 provenance=observation.provenance)


def association_claim(association: Association, *, statement: str, claim_id: str) -> Claim:
    return Claim(claim_id, statement, ClaimLevel.ASSOCIATION,
                 supports=association.evidence,
                 limitations=(LimitationType.INSUFFICIENT_EVIDENCE,))


def relation_evidence_status(output: str) -> tuple[bool, str]:
    """Decide whether a relation-tool output carries usable edge evidence.

    An Association claim is only warranted when the tool actually returned
    explicit relation/edge/path evidence.  Empty, error, validation, degraded
    (direction/type unavailable), zero-edge and no-object outputs must not be
    treated as a valid association.  The status text is used for disclosure
    when no evidence is present.
    """
    text = str(output or "")
    if not text.strip():
        return False, "empty relation output"
    low = text.lower()
    if "error" in low:
        return False, "relation tool error"
    if "降级说明" in text or "不作为证据" in text or "不能用于证明" in text:
        return False, "degraded relation evidence"
    if any(marker in text for marker in (
        "未发现", "无可用上下文", "不是已知的", "未匹配", "请提供",
        "empty entity", "no logical entity", "no recorded relations",
        "no related", "no match",
    )):
        return False, "no related objects found"
    if re.search(r"关系证据\s*\(0\)", text) or re.search(r"关联对象\s*\(0\)", text):
        return False, "zero relation evidence"
    if re.search(r"关系证据\s*\(\d+\)", text):
        return True, ""
    if re.search(r"关键路径|关联业务对象与路径证据|路径证据", text):
        return True, ""
    if re.search(r"# Relations for|关系\s*:", text):
        return True, ""
    return False, "no explicit edge evidence"


def render_claim(claim: Claim) -> str:
    """Render one claim with level-aware wording; never upgrades certainty."""
    prefixes = {
        ClaimLevel.FACT: "数据显示：",
        ClaimLevel.ASSOCIATION: "发现关联：",
        ClaimLevel.INFERENCE: "可能的排查方向：",
        ClaimLevel.VERIFIED: "已验证：",
    }
    text = f"{prefixes[claim.level]}{claim.statement}"
    if claim.limitations:
        text += "（限制：" + "、".join(str(x.value if isinstance(x, Enum) else x) for x in claim.limitations) + "）"
    return text


def render_narrative(claims: Sequence[Claim]) -> str:
    return "\n".join(render_claim(claim) for claim in claims)


def _metadata_from_output(data: Any) -> dict[str, Any] | None:
    """Read the optional metadata envelope emitted by SQL/Metric tools."""
    if isinstance(data, dict):
        if "data" in data and "provenance" in data:
            return data
        if "rows" in data:
            return {"data": data}
        return None
    text = str(data or "")
    marker = "[RESULT_METADATA]"
    if marker in text:
        text = text.split(marker, 1)[1].strip()
    else:
        # MetricDataQuery has a human header followed by a JSON envelope.
        start = text.find("{")
        if start < 0:
            return None
        text = text[start:]
    try:
        parsed = __import__("json").loads(text)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) and "data" in parsed else None


def _numeric_rows(payload: Any) -> list[tuple[str, float]]:
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    columns = payload.get("columns", []) if isinstance(payload, dict) else []
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        return []
    values: list[tuple[str, float]] = []
    for row in rows:
        if isinstance(row, dict):
            for key, value in row.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    values.append((str(key), float(value)))
        elif isinstance(row, (list, tuple)) and isinstance(columns, list):
            for key, value in zip(columns, row):
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    values.append((str(key), float(value)))
    return values


def claims_from_query_result(result: QueryResult, claim_id_prefix: str = "query") -> list[Claim]:
    """Build conservative FACT claims from structured tool metadata.

    No business meaning is inferred: only numeric cells explicitly returned by
    a tool become facts. Unstructured tool output cannot silently create a fact.
    """
    envelope = _metadata_from_output(result.data)
    if not envelope:
        return []
    payload = envelope.get("data") or {}
    if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
        payload = payload["result"]
    semantic = dict(result.semantic or {})
    semantic.update(envelope.get("semantic") or {})
    claims: list[Claim] = []
    for index, (name, value) in enumerate(_numeric_rows(payload)):
        claims.append(claim_from_observation(Observation(
            id=f"{claim_id_prefix}-{index}",
            statement=f"{name}={value:g}", scope=result.scope,
            semantic=semantic, provenance=result.provenance,
        )))
    return claims


def enrich_query_result(result: QueryResult) -> QueryResult:
    """Merge a tool's serialized metadata into the session result envelope."""
    envelope = _metadata_from_output(result.data)
    if not envelope:
        return result
    provenance = envelope.get("provenance") or {}
    return QueryResult(
        data=result.data,
        scope=dict(envelope.get("scope") or result.scope),
        semantic={**result.semantic, **dict(envelope.get("semantic") or {})},
        provenance=Provenance(**{
            key: provenance.get(key, getattr(result.provenance, key))
            for key in Provenance.__dataclass_fields__
        }),
    )


def reconcile_query_results(results: Sequence[QueryResult], *, tolerance: float = 1e-9) -> ReconciliationResult | None:
    """Reconcile an explicit parent/children pair carried by query metadata.

    Only results that explicitly declare ``parent_value`` / ``child_values``
    are pairing candidates, and they must describe the same metric.  When
    zero, more than one, or a cross-metric candidate pair is found the
    reconciliation is skipped instead of guessed: display or unrelated
    results never become pairing candidates, and interleaved results do not
    hide a real parent/children pair.
    """
    parents = [r for r in results if r.semantic.get("parent_value") is not None]
    children = [r for r in results if isinstance(r.semantic.get("child_values"), (list, tuple))]
    if len(parents) != 1 or len(children) != 1:
        return None
    parent, child = parents[0], children[0]
    parent_metric = _metric_key(parent.semantic)
    child_metric = _metric_key(child.semantic)
    if parent_metric and child_metric and parent_metric != child_metric:
        return None
    return reconcile(parent.semantic["parent_value"], child.semantic["child_values"], tolerance=tolerance)


def _metric_key(semantic: Mapping[str, Any]) -> str:
    """Canonical metric identity used to guard reconciliation pairing."""
    raw = (semantic.get("metric") or semantic.get("metric_code")
           or semantic.get("metric_codes") or "")
    if isinstance(raw, (list, tuple)):
        return ",".join(str(item) for item in raw)
    return str(raw)


def _equal_scope(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return dict(left or {}) == dict(right or {})


def reconcile(parent: Any, children: Iterable[Any], *, tolerance: float = 1e-9) -> ReconciliationResult:
    """Compare an aggregate with a re-aggregation of its children."""
    try:
        p, c = float(parent), sum(float(x) for x in children)
    except (TypeError, ValueError):
        return ReconciliationResult(ValidationStatus.REJECT, None, None, None, tolerance,
                                    ("values must be numeric",), (LimitationType.DATA_MISSING,))
    difference = abs(p - c)
    allowed = max(tolerance, abs(p) * tolerance)
    if difference <= allowed:
        return ReconciliationResult(ValidationStatus.ALLOW, p, c, difference, tolerance)
    return ReconciliationResult(
        ValidationStatus.REJECT, p, c, difference, tolerance,
        (f"aggregate mismatch: parent={p:g}, children={c:g}",),
        (LimitationType.CONFLICTING_EVIDENCE,),
    )


def compare_measures(left: Measure, right: Measure) -> ValidationResult:
    issues: list[str] = []
    limits: list[LimitationType] = []
    if left.unit and right.unit and left.unit != right.unit:
        issues.append(f"unit mismatch: {left.unit} vs {right.unit}")
        limits.append(LimitationType.UNIT_CONFLICT)
    if not _equal_scope(left.scope, right.scope):
        issues.append("scope mismatch")
        limits.append(LimitationType.SCOPE_CONFLICT)
    if left.semantic_type != right.semantic_type:
        issues.append(f"semantic mismatch: {left.semantic_type.value} vs {right.semantic_type.value}")
        limits.append(LimitationType.SEMANTIC_CONFLICT)
    if issues:
        return ValidationResult(ValidationStatus.REJECT, tuple(issues), tuple(limits))
    return ValidationResult(ValidationStatus.ALLOW)


def detect_conflicts(results: Sequence[QueryResult]) -> ValidationResult:
    """Detect contradictory observations sharing metric and scope.

    Results with no structured numeric observation are left untouched; this is
    intentionally a validator, not an attempt to infer values from prose.
    """
    seen: dict[tuple[str, str], Any] = {}
    for result in results:
        semantic = result.semantic or {}
        metric = str(semantic.get("metric") or semantic.get("metric_code") or
                     ",".join(semantic.get("metrics") or ()))
        value = semantic.get("value")
        if not metric or not isinstance(value, (int, float)):
            continue
        key = (metric, repr(sorted(result.scope.items())))
        if key in seen and not math.isclose(float(seen[key]), float(value), rel_tol=1e-9, abs_tol=1e-9):
            return ValidationResult(ValidationStatus.REJECT,
                                    (f"conflicting observations for {metric}",),
                                    (LimitationType.CONFLICTING_EVIDENCE,))
        seen[key] = value
    return ValidationResult(ValidationStatus.ALLOW)


def validate_chart_measures(measures: Sequence[Measure], *, display_only: bool = False) -> ValidationResult:
    if len(measures) < 2:
        return ValidationResult(ValidationStatus.ALLOW)
    checks = [compare_measures(measures[0], measure) for measure in measures[1:]]
    issues = tuple(issue for result in checks for issue in result.issues)
    limits = tuple(limit for result in checks for limit in result.limitations)
    if not issues:
        return ValidationResult(ValidationStatus.ALLOW)
    if display_only:
        return ValidationResult(ValidationStatus.ALLOW_WITH_WARNING, issues, limits)
    return ValidationResult(ValidationStatus.REJECT, issues, limits)


def validate_claims(claims: Sequence[Claim], narrative: str) -> ValidationResult:
    """Conservative structural check; it never attempts business reasoning."""
    text = str(narrative or "")
    # Thousands separators are display formatting, not extra numeric facts.
    normalized_text = re.sub(r"(?<=\d),(?=\d{3})", "", text)
    issues: list[str] = []
    claim_text = " ".join(c.statement for c in claims)
    if any(c.level == ClaimLevel.INFERENCE for c in claims) and re.search(r"已确认|已验证|确定原因|必然导致", text):
        issues.append("claim escalation: inference rendered as verified")
    if any(LimitationType.CONFLICTING_EVIDENCE in c.limitations for c in claims) and not re.search(r"冲突|不一致|无法|待核查", text):
        issues.append("known numerical conflict is not disclosed")
    if claims and any(c.level == ClaimLevel.ASSOCIATION for c in claims) and re.search(r"导致|造成|根因是", text):
        issues.append("association rendered as causation")
    proxy_claims = [c for c in claims if str(c.semantic.get("semantic_type", "")).upper() == SemanticType.PROXY.value]
    if proxy_claims and not re.search(r"代理|Proxy|不等价|无法直接计算|不能直接计算", text, re.IGNORECASE):
        issues.append("proxy measure is not distinguished from requested measure")
    # Numeric tokens are a cheap high-signal guard against invented figures.
    # Exact string equality is deliberately not required: display formatting
    # (100 vs 100.0), percentages (0.25 vs 25%), ordinals, list markers,
    # ranges and time expressions are all legitimate narrative numbers.
    claim_text = re.sub(r"(?<=\d),(?=\d{3})", "", claim_text)
    known_numbers = set(re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?", claim_text))
    known_values = {float(number) for number in known_numbers}
    expressive = _expressive_numbers(normalized_text)
    for number in re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?", normalized_text):
        if number in known_numbers or number in expressive:
            continue
        if re.search(r"\b(?:19|20)\d{2}\b", number):
            continue
        try:
            value = float(number)
        except ValueError:
            continue
        if any(math.isclose(value, known, rel_tol=1e-9, abs_tol=1e-9) for known in known_values):
            continue  # 100 vs 100.0 / 100.00
        if any(
            0 < abs(known) <= 1 and math.isclose(value, known * 100, rel_tol=1e-9, abs_tol=1e-6)
            for known in known_values
        ):
            continue  # 0.25 vs 25%
        if any(
            0 < abs(value) <= 1 and math.isclose(known, value * 100, rel_tol=1e-9, abs_tol=1e-6)
            for known in known_values
        ):
            continue  # 25% in claims, 0.25 in narrative
        issues.append(f"unsupported numeric fact: {number}")
        break
    if issues:
        return ValidationResult(ValidationStatus.REJECT, tuple(issues), (LimitationType.INSUFFICIENT_EVIDENCE,))
    return ValidationResult(ValidationStatus.ALLOW)


def _expressive_numbers(text: str) -> set[str]:
    """Collect narrative numbers that are ordinals, ranges, list markers or
    time expressions rather than data facts."""
    expressive: set[str] = set()

    def _add(pattern: str) -> None:
        for match in re.finditer(pattern, text):
            expressive.update(re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?", match.group(0)))

    # Ordinals: 第 2 步 / 第3季度.
    _add(r"第\s*[-+]?\d+(?:\.\d+)?")
    # Ranges: 1–2 / 1-2 / 1~2 / 1 至 2.
    _add(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?\s*(?:[-–—~]|至)\s*[-+]?\d+(?:\.\d+)?")
    # Enumerations: 1、2、3 / 1，2 / （1）（2）/ line-leading "1. ".
    _add(r"(?:^|\n)\s*[-+]?\d+\.(?=\s)")
    _add(r"[-+]?\d+[、．，](?![0-9])")
    _add(r"[（(]\s*[-+]?\d+(?:\.\d+)?\s*[)）]")
    _add(r"[-+]?\d+[)）](?![0-9])")
    # Time/period expressions: 12 月 / 第 3 季度 / 2 周 / 4 分钟.
    _add(r"[-+]?\d+(?:\.\d+)?\s*(?:月份?|季度|旬|周|日|天|时|分钟|小时|秒|期|号|年)(?![A-Za-z])")
    return expressive


def normalize_query_result(data: Any, *, scope: Mapping[str, Any] | None = None,
                           semantic: Mapping[str, Any] | None = None,
                           provenance: Provenance | Mapping[str, Any] | None = None) -> QueryResult:
    if provenance is None:
        prov = Provenance()
    elif isinstance(provenance, Provenance):
        prov = provenance
    else:
        prov = Provenance(**{k: v for k, v in provenance.items() if k in Provenance.__dataclass_fields__})
    return QueryResult(data, dict(scope or {}), dict(semantic or {}), prov)
