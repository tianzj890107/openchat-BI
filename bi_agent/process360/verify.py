"""S07 verification and closure.

Closure has two independent conclusions: delivery evidence completeness and
business effect.  Missing baseline, approved target (RF), or a later observation
window makes the effect conclusion blocked rather than "improved".
"""

from __future__ import annotations

from typing import Any, Mapping

from .catalog import Process360Catalog, _codes
from .models import envelope, gap, metric


def _rf(catalog: Process360Catalog, metric_code: str) -> dict[str, Any]:
    for row in catalog.records("metric_references"):
        if str(row.get("指标编码")) == metric_code and row.get("类型") in {"目标", "阈值"}:
            return dict(row)
    return {}


def build_verification(
    catalog: Process360Catalog,
    scenario: str,
    *,
    baseline: Mapping[str, Any] | None = None,
    current: Mapping[str, Any] | None = None,
    delivery_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    code = str(scenario).upper()
    bundle = catalog.scenario_bundle(code)
    template = (bundle.get("verifications") or [{}])[0]
    if not template:
        return envelope(
            "S07",
            "blocked",
            catalog_id=catalog.catalog_id,
            catalog_version=catalog.version,
            scenario=code,
            gaps=[
                gap(
                    "VERIFICATION_TEMPLATE_MISSING",
                    "缺少复验模板",
                    needed="补充 VF 模板",
                    impact="无法判断交付/效果",
                    severity="blocking",
                    source="catalog",
                )
            ],
        )
    metric_codes = _codes(template.get("指标编码集合"))
    targets = []
    for metric_code in metric_codes:
        reference = _rf(catalog, metric_code)
        targets.append(
            {
                "metric": metric_code,
                "reference": reference.get("code") or reference.get("参照编码"),
                "comparison": reference.get("比较方式"),
                "target": reference.get("数值"),
                "source": reference.get("取值来源"),
                "enabled": False,
                "approvalStatus": "pending_business_approval",
                "note": "本地 RF 为设计参照；尚无批准记录与适用范围，不自动启用。",
            }
        )
    gaps: list[dict[str, Any]] = []
    if any(not item["enabled"] for item in targets):
        gaps.append(
            gap(
                "VERIFICATION_TARGET_MISSING",
                "复验目标尚未批准",
                needed="批准 RF 目标值、复验窗口和样本量",
                impact="只能输出计划和当前口径，不能判定达标",
                severity="blocking",
                source="catalog",
            )
        )
    baseline_valid = bool(
        baseline
        and baseline.get("scenario") == code
        and baseline.get("catalogVersion") == catalog.version
        and baseline.get("objectIds")
        and baseline.get("frozenAt")
        and baseline.get("metrics")
        and baseline.get("observationWindow")
    )
    if not baseline_valid:
        gaps.append(
            gap(
                "VERIFICATION_BASELINE_MISSING",
                "缺少原问题集合的冻结基准",
                needed="原对象集合、基准数量/金额/电量、观察截止日版本",
                impact="无法计算改善幅度或确认原集合已化解",
                severity="blocking",
                source="runtime",
            )
        )
    gaps.append(
        gap(
            "VERIFICATION_DELIVERY_EVIDENCE",
            "交付验收凭据需人工确认",
            needed=str(template.get("交付验收要求") or ""),
            impact="任务状态完成不等于交付合格",
            severity="degrading",
            source="catalog",
        )
    )
    delivery = {
        "requirement": template.get("交付验收要求"),
        "status": "provided" if delivery_evidence else "pending_manual_review",
        "evidence": dict(delivery_evidence or {}),
    }
    effect = {
        "requirement": template.get("效果验收要求"),
        "metrics": metric_codes,
        "targets": targets,
        "baseline": dict(baseline or {}),
        "current": dict(current or {}),
        "status": "blocked"
        if any(item["enabled"] is False for item in targets) or not baseline_valid
        else "partial",
        "note": "没有批准目标/冻结基准时不判定达标；历史已发生事实不可回滚。",
    }
    return envelope(
        "S07",
        "blocked" if effect["status"] == "blocked" else "partial",
        catalog_id=catalog.catalog_id,
        catalog_version=catalog.version,
        scenario=code,
        metrics=[
            metric(
                code,
                str((catalog.metric(code) or {}).get("name") or code),
                (current or {}).get(code),
                str((catalog.metric(code) or {}).get("单位") or ""),
                status="blocked" if effect["status"] == "blocked" else "partial",
                formula=str((catalog.metric(code) or {}).get("计算公式") or ""),
                note="复验指标；目标或基准缺失时不判定达标",
            )
            for code in metric_codes
        ],
        gaps=gaps,
        limitations=[
            "交付验收与效果验收分别判断，不能用任务状态代替效果。",
            "复验不覆盖或撤销历史事实；残余风险需人工复评。",
        ],
        next_steps=[
            "补齐批准 RF 目标、冻结基准和复验窗口证据",
            "由验收人分别确认交付合格与效果达标后关闭问题",
        ],
        verification={
            "template": template.get("code"),
            "name": template.get("name"),
            "rule": template.get("规则编码"),
            "timing": template.get("复验时机"),
            "closeAndReopen": template.get("关闭与重开"),
            "delivery": delivery,
            "effect": effect,
        },
        closure={
            "status": "blocked" if effect["status"] == "blocked" else "pending_manual_review",
            "canClose": False,
        },
    )
