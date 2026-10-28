"""S04 anomaly, impact and candidate-cause analysis.

The layer is deterministic.  It separates:
- what the facts show (metric values and record counts),
- what the scenario rule says is anomalous,
- which causes are candidates that still need the named evidence,
- which display/risk grading is unavailable because a matrix or target is missing.

It never promotes a candidate cause to a root cause, and it never turns a
blocked metric into zero.
"""

from __future__ import annotations

from typing import Any, Mapping

from .catalog import Process360Catalog
from .models import combine_status, dedupe_gaps, envelope, gap


def _metric_map(query: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("code")): dict(item) for item in query.get("metrics", [])}


def _value(metrics: Mapping[str, Mapping[str, Any]], code: str) -> float | None:
    item = metrics.get(code) or {}
    value = item.get("value")
    if value is None or item.get("status") == "blocked":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _level(value: float | None, *, high: float, critical: float) -> str:
    if value is None:
        return "UNVERIFIABLE"
    if value >= critical:
        return "CRITICAL"
    if value >= high:
        return "HIGH"
    if value > 0:
        return "MEDIUM"
    return "LOW"


def _candidate_causes(
    catalog: Process360Catalog, scenario: str, context: Mapping[str, Any]
) -> list[dict[str, Any]]:
    causes = []
    for row in context.get("causes", []):
        evidence_codes = [
            str(item)
            for item in str(row.get("证据模板编码") or "").replace("、", ",").split(",")
            if item.strip()
        ]
        causes.append(
            {
                "code": row.get("code"),
                "name": row.get("name") or row.get("原因名称"),
                "mechanism": row.get("因果机制"),
                "activity": row.get("作用活动编码"),
                "verificationRule": row.get("验证规则编码"),
                "evidenceTemplates": evidence_codes,
                "status": "candidate_unverified",
                "statement": "候选原因，仅用于提出核查任务；未取得证据前不得表述为已确认根因。",
                "requiredEvidence": [
                    {
                        "code": code,
                        "name": (catalog.get("evidence_templates", code) or {}).get("name", code),
                        "required": (catalog.get("evidence_templates", code) or {}).get(
                            "必需内容", ""
                        ),
                    }
                    for code in evidence_codes
                ],
            }
        )
    return causes


def _scenario_observation(
    scenario: str, metrics: Mapping[str, Mapping[str, Any]], query: Mapping[str, Any]
) -> dict[str, Any]:
    if scenario == "SC01":
        amount = _value(metrics, "M0337")
        if amount is None:
            amount = _value(metrics, "M0143")
        power = _value(metrics, "M0336")
        if power is None:
            power = _value(metrics, "M0134")
        return {
            "observed": bool(query.get("overdueRows")),
            "headline": (
                (f"{power:.2f} GWh" if power is not None else "电量不可计算")
                + (f" / {amount:.2f} 亿元" if amount is not None else " / 金额不可计算")
                + "的订单行已过要求交期且仍有待发余额"
            ),
            "objects": int(query.get("overdueRows") or 0),
            "impact": {"amount100m": amount, "powerGwh": power},
            "severity": _level(amount, high=1.0, critical=10.0),
            "severityBasis": "运营分诊阈值（金额），不是客户批准的风险矩阵等级",
        }
    if scenario == "SC02":
        return {
            "observed": False,
            "headline": f"本期已批准报价申请 {int(query.get('approvedCount') or 0)} 单；红区单数/占比因口径缺口不可评估",
            "objects": int(query.get("approvedCount") or 0),
            "impact": {},
            "severity": "UNVERIFIABLE",
            "severityBasis": "M0137/M36002 blocked，不能判定红区风险等级",
        }
    if scenario == "SC03":
        pending = int(query.get("pendingCustomers") or 0)
        return {
            "observed": pending > 0,
            "headline": f"{pending} 户战略客户当前没有有效商机",
            "objects": pending,
            "impact": {},
            "severity": _level(float(pending), high=5, critical=15),
            "severityBasis": "运营分诊阈值（户数），不是批准风险矩阵等级",
        }
    if scenario == "SC04":
        amount = _value(metrics, "M0179")
        power = _value(metrics, "M0142")
        count = int(query.get("awardedUnsigned") or 0)
        return {
            "observed": count > 0,
            "headline": f"{count} 个项目已中标但未签有效正式订单，涉及 "
            + (f"{amount:.2f} 亿元" if amount is not None else "金额不可计算")
            + " / "
            + (f"{power:.2f} GWh" if power is not None else "电量不可计算"),
            "objects": count,
            "impact": {"amount100m": amount, "powerGwh": power},
            "severity": _level(amount, high=1.0, critical=5.0),
            "severityBasis": "运营分诊阈值（金额），不是客户批准的风险矩阵等级",
        }
    if scenario == "SC05":
        unmatched = _value(metrics, "M0334")
        ratio = _value(metrics, "M36006")
        return {
            "observed": unmatched is not None and unmatched > 0,
            "headline": (
                f"本期可分类的超计划发货候选为 {unmatched:.4f} GWh"
                if unmatched is not None
                else "日计划匹配与超计划数量不可评估"
            )
            + (f"，占实际发货电量 {ratio:.2%}" if ratio is not None else "；占比不可计算"),
            "objects": int(query.get("ambiguousRows") or 0),
            "impact": {"powerGwh": unmatched},
            "severity": "UNVERIFIABLE"
            if ratio is None
            else _level(ratio, high=0.05, critical=0.10),
            "severityBasis": "未匹配不是违规；RF09 目标为空，不做业务效果定级",
        }
    return {
        "observed": False,
        "headline": "",
        "objects": 0,
        "impact": {},
        "severity": "UNVERIFIABLE",
    }


def analyze(
    catalog: Process360Catalog,
    scenario: str,
    context: Mapping[str, Any],
    query: Mapping[str, Any],
    *,
    question: str | None = None,
) -> dict[str, Any]:
    code = str(scenario).upper()
    metrics = _metric_map(query)
    observation = _scenario_observation(code, metrics, query)
    query_status = str(query.get("status") or "blocked")
    if query_status in {"blocked", "needs_clarification", "not_applicable"}:
        observation.update(
            observed=False,
            severity="UNVERIFIABLE",
            impact={},
            headline="事实查询未完成，无法判断异常与风险。",
        )
    anomalies = []
    for row in context.get("anomalies", []):
        anomalies.append(
            {
                "code": row.get("code"),
                "name": row.get("name"),
                "status": "triggered"
                if observation["observed"]
                else (
                    "unverifiable" if observation["severity"] == "UNVERIFIABLE" else "not_triggered"
                ),
                "rule": row.get("识别规则编码"),
                "objectGrain": row.get("对象粒度"),
                "missingDataPolicy": row.get("缺数处理"),
                "observation": observation,
            }
        )
    problems = [dict(row) for row in context.get("problems", [])]
    risks = []
    for row in context.get("risks", []):
        risks.append(
            {
                "code": row.get("code"),
                "name": row.get("name"),
                "problem": row.get("问题编码"),
                "rule": row.get("评估规则编码"),
                "status": "待评估" if observation["severity"] == "UNVERIFIABLE" else "分诊建议",
                "severity": observation["severity"],
                "severityBasis": observation["severityBasis"],
                "dataBoundary": row.get("数据边界"),
                "note": "未接批准风险矩阵时只输出运营分诊建议，不生成主观概率。",
            }
        )
    causes = _candidate_causes(catalog, code, context) if observation["observed"] else []
    cause_gaps = []
    if causes:
        cause_gap = catalog.get("gaps", "G06") or {}
        cause_gaps.append(
            gap(
                "G06",
                str(cause_gap.get("name") or "根因证据与外部系统"),
                needed=str(cause_gap.get("必须补充") or ""),
                impact="候选原因无法升级为已确认根因",
                severity="degrading",
            )
        )
    gaps = dedupe_gaps([*context.get("gaps", []), *query.get("gaps", []), *cause_gaps])
    query_status = str(query.get("status") or "blocked")
    status = combine_status([query_status, "partial" if causes else "ok"], none=query_status)
    if query_status in {"blocked", "needs_clarification", "not_applicable"}:
        status = query_status
    return envelope(
        "S04",
        status,
        catalog_id=catalog.catalog_id,
        catalog_version=catalog.version,
        scenario=code,
        question=question,
        scope=query.get("scope"),
        metrics=query.get("metrics", []),
        records=query.get("records", []),
        evidence_items=query.get("evidence", []),
        gaps=gaps,
        limitations=[
            *query.get("limitations", []),
            "候选原因未经证据验证，不得写成已确认根因。",
            "风险等级仅在批准风险矩阵缺失时输出运营分诊，不代表客户风险分级。",
        ],
        next_steps=[
            "按证据模板收集/上传证据后再判断原因",
            "S05 生成方案与任务令草稿，S06 仅在用户点击时发送 Fuxi 待办",
        ],
        observation=observation,
        anomalies=anomalies,
        problems=problems,
        risks=risks,
        candidateCauses=causes,
        impact={
            **observation.get("impact", {}),
            "impactCode": (context.get("risks") or [{}])[0].get("影响编码")
            if context.get("risks")
            else None,
            "statement": "当前仅量化已观察对象；未接风险矩阵/恢复计划前不估算未来损失。",
        },
        problem=(problems[0] if problems else None),
    )
