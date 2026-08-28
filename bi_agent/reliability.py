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


class EvidenceClass(str, Enum):
    SUPPORTED = "SUPPORTED"
    DERIVED = "DERIVED"
    REASONABLE_INFERENCE = "REASONABLE_INFERENCE"
    UNSUPPORTED_FACT = "UNSUPPORTED_FACT"
    CONTRADICTED = "CONTRADICTED"
    CAUSAL_OVERCLAIM = "CAUSAL_OVERCLAIM"
    PROXY_MISREPRESENTATION = "PROXY_MISREPRESENTATION"
    CONFLICT_NOT_DISCLOSED = "CONFLICT_NOT_DISCLOSED"
    VALIDATOR_ERROR = "VALIDATOR_ERROR"


class EvidenceSeverity(str, Enum):
    INFO = "INFO"
    SOFT = "SOFT"
    HARD = "HARD"


@dataclass(frozen=True)
class EvidenceFinding:
    code: EvidenceClass
    severity: EvidenceSeverity
    message: str


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
    findings: tuple[EvidenceFinding, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status != ValidationStatus.REJECT

    @property
    def hard_findings(self) -> tuple[EvidenceFinding, ...]:
        return tuple(item for item in self.findings if item.severity == EvidenceSeverity.HARD)

    @property
    def soft_findings(self) -> tuple[EvidenceFinding, ...]:
        return tuple(item for item in self.findings if item.severity == EvidenceSeverity.SOFT)


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
        # Ontology-MetricQuery has a human header followed by a JSON envelope.
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
    """Return numeric cells from a normalized query payload.

    Doris/ontology gateways do not agree on whether decimal values are JSON
    numbers or strings, and some wrap the actual table below ``result`` or
    ``data``.  Claims must follow those harmless transport differences or a
    real value such as ``"500"`` disappears from the evidence allow-list and
    the final narrative is incorrectly blocked.

    Parsing stays deliberately conservative: only a whole-cell numeric string
    is accepted.  Codes, dates, labels and mixed text are never coerced.
    """
    while isinstance(payload, dict) and not isinstance(payload.get("rows"), (list, dict)):
        nested = next(
            (payload.get(key) for key in ("result", "data") if isinstance(payload.get(key), dict)),
            None,
        )
        if nested is None or nested is payload:
            break
        payload = nested
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
                parsed = _query_number(value)
                if parsed is not None:
                    values.append((str(key), parsed))
        elif isinstance(row, (list, tuple)) and isinstance(columns, list):
            for key, value in zip(columns, row):
                parsed = _query_number(value)
                if parsed is not None:
                    values.append((str(key), parsed))
    return values


def _query_number(value: Any) -> float | None:
    """Parse one trusted query-result cell without guessing business text."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not re.fullmatch(r"[-+]?(?:\d+(?:,\d{3})*|\d*)(?:\.\d+)?", text) or not re.search(r"\d", text):
        return None
    try:
        number = float(text.replace(",", ""))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


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
    """Evidence consistency guard for user-facing BI narratives.

    Claims constrain evidence semantics, not numeric presentation or the
    entire language model output. Numeric tokens are deliberately not gated:
    formatting, unit conversion, rounding and arbitrary derived figures must
    never suppress a user-facing answer. Proxy/conflict misrepresentation
    remains a hard failure; causal or certainty overstatement is a soft issue
    that callers can locally weaken without discarding the answer.
    """
    text = str(narrative or "")
    findings: list[EvidenceFinding] = []
    if any(c.level == ClaimLevel.INFERENCE for c in claims) and re.search(r"已确认|已验证|确定原因|必然导致", text):
        findings.append(EvidenceFinding(
            EvidenceClass.CAUSAL_OVERCLAIM, EvidenceSeverity.SOFT,
            "claim escalation: inference rendered as verified",
        ))
    if any(LimitationType.CONFLICTING_EVIDENCE in c.limitations for c in claims) and not re.search(r"冲突|不一致|无法|待核查", text):
        findings.append(EvidenceFinding(
            EvidenceClass.CONFLICT_NOT_DISCLOSED, EvidenceSeverity.HARD,
            "known numerical conflict is not disclosed",
        ))
    if claims and any(c.level == ClaimLevel.ASSOCIATION for c in claims) and re.search(r"导致|造成|根因是", text):
        findings.append(EvidenceFinding(
            EvidenceClass.CAUSAL_OVERCLAIM, EvidenceSeverity.SOFT,
            "association rendered as causation",
        ))
    proxy_claims = [c for c in claims if str(c.semantic.get("semantic_type", "")).upper() == SemanticType.PROXY.value]
    if proxy_claims and not re.search(r"代理|Proxy|不等价|无法直接计算|不能直接计算", text, re.IGNORECASE):
        findings.append(EvidenceFinding(
            EvidenceClass.PROXY_MISREPRESENTATION, EvidenceSeverity.HARD,
            "proxy measure is not distinguished from requested measure",
        ))
    hard = tuple(item for item in findings if item.severity == EvidenceSeverity.HARD)
    soft = tuple(item for item in findings if item.severity == EvidenceSeverity.SOFT)
    issues = tuple(item.message for item in findings if item.severity != EvidenceSeverity.INFO)
    if hard:
        return ValidationResult(
            ValidationStatus.REJECT, issues,
            (LimitationType.INSUFFICIENT_EVIDENCE,), tuple(findings),
        )
    if soft:
        return ValidationResult(ValidationStatus.ALLOW_WITH_WARNING, issues, (), tuple(findings))
    return ValidationResult(ValidationStatus.ALLOW, (), (), tuple(findings))


def soften_evidence_language(narrative: str, findings: Sequence[EvidenceFinding]) -> str:
    """Locally weaken soft overclaims while preserving the useful answer."""
    text = str(narrative or "")
    codes = {finding.code for finding in findings if finding.severity == EvidenceSeverity.SOFT}
    if EvidenceClass.CAUSAL_OVERCLAIM in codes:
        text = text.replace("必然导致", "可能与")
        text = text.replace("根因是", "当前关联现象是")
        text = text.replace("导致了", "与")
        text = text.replace("导致", "与")
        text = text.replace("造成了", "与")
        text = text.replace("造成", "与")
        text = text.replace("已确认", "当前迹象表明")
        text = text.replace("已验证", "初步观察到")
        if "不足以确认因果" not in text:
            text = text.rstrip() + "\n\n证据说明：当前结果支持关联性分析，但不足以确认因果关系。"
    return text


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
