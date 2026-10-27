"""S01/S02 catalog retrieval and context assembly.

The catalog is the only semantic source.  This module expands a scenario into a
bounded, auditable working set and exposes the links the analysis/action layers
are allowed to use.  It does not call the database or a model.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from .catalog import Process360Catalog, _codes
from .models import envelope, gap


def _scenarios_for(catalog: Process360Catalog, sheet: str, code: str) -> list[str]:
    field = {"metrics": "指标编码集合", "business_objects": "业务对象编码集合"}.get(sheet, "")
    if not field:
        return []
    result: list[str] = []
    for scenario in catalog.records("scenarios"):
        if code in _codes(scenario.get(field)):
            result.append(str(scenario.get("code") or ""))
    return [item for item in result if item]


def search(catalog: Process360Catalog, query: str, *, limit: int = 20,
           scenario: str | None = None) -> dict[str, Any]:
    """Dual-entry lookup: metric and business-object names/codes only."""
    items = catalog.search(query, limit=limit)
    explicit = str(scenario or "").strip().upper() or None
    results: list[dict[str, Any]] = []
    for item in items:
        sheet = str(item.get("sheet") or "")
        code = str(item.get("code") or "")
        scenarios = _scenarios_for(catalog, sheet, code)
        if explicit:
            scenarios = [code for code in scenarios if code == explicit]
            if not scenarios:
                continue
        record = dict(item.get("record") or {})
        results.append({
            "entryType": item.get("entryType"),
            "sheet": sheet,
            "code": code,
            "name": item.get("name"),
            "score": item.get("score"),
            "scenarios": scenarios,
            "record": record,
        })
    return envelope(
        "S01",
        "ok" if results else "partial",
        catalog_id=catalog.catalog_id,
        catalog_version=catalog.version,
        scenario=explicit,
        question=query,
        records=results,
        next_steps=(
            ["S02 装配场景上下文并确认版本/口径"]
            if results else ["未命中指标或业务对象；请改用指标编码/业务对象名称，或先澄清问题范围"]
        ),
        query=query,
        entryTypes=["metric", "businessObject"],
    )


def _rows(catalog: Process360Catalog, sheet: str, codes: Iterable[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for code in codes:
        row = catalog.get(sheet, code)
        if row:
            result.append(dict(row))
    return result


def _linked(catalog: Process360Catalog, sheet: str, field: str, values: set[str]) -> list[dict[str, Any]]:
    return [dict(row) for row in catalog.records(sheet) if set(_codes(row.get(field))) & values]


def _compact(row: Mapping[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    return {key: row.get(key) for key in keys if row.get(key) not in (None, "", [], {})}


def build_context(catalog: Process360Catalog, scenario: str, *, question: str | None = None) -> dict[str, Any]:
    code = str(scenario or "").strip().upper()
    bundle = catalog.scenario_bundle(code)
    record = bundle["scenario"]
    entities = bundle["entities"]
    activity_codes = {str(row.get("code")) for row in entities.get("activities", [])}
    object_codes = {str(row.get("code")) for row in entities.get("business_objects", [])}
    metric_codes = {str(row.get("code")) for row in entities.get("metrics", [])}
    role_codes = {str(row.get("code")) for row in entities.get("roles", [])}

    rule_codes: set[str] = set()
    for row in bundle.get("anomalies", []):
        rule_codes.update(_codes(row.get("识别规则编码")))
    for row in bundle.get("verifications", []):
        rule_codes.update(_codes(row.get("规则编码")))
    for row in [*bundle.get("evidence_templates", []), *bundle.get("task_templates", []),
                *bundle.get("actions", [])]:
        rule_codes.update(_codes(row.get("使用规则编码集合")))
        rule_codes.update(_codes(row.get("校验规则编码集合")))
    rules = _rows(catalog, "business_rules", rule_codes)

    gaps = [
        gap(
            str(row.get("code")),
            str(row.get("name") or row.get("事项") or ""),
            needed=str(row.get("必须补充") or ""),
            impact=str(row.get("影响范围") or ""),
            severity="blocking" if row.get("code") in {"G02", "G03", "G12", "G13", "G16"} else "degrading",
        )
        for row in bundle.get("gaps", [])
    ]

    process = (entities.get("processes") or [{}])[0]
    payload = envelope(
        "S02",
        "partial" if gaps else "ok",
        catalog_id=catalog.catalog_id,
        catalog_version=catalog.version,
        scenario=code,
        question=question,
        gaps=gaps,
        scenarioRecord=dict(record),
        process=dict(process),
        activities=[dict(row) for row in entities.get("activities", [])],
        businessObjects=[dict(row) for row in entities.get("business_objects", [])],
        metrics=[dict(row) for row in entities.get("metrics", [])],
        roles=[dict(row) for row in entities.get("roles", [])],
        rules=rules,
        anomalies=[dict(row) for row in bundle.get("anomalies", [])],
        problems=[dict(row) for row in bundle.get("problems", [])],
        risks=[dict(row) for row in bundle.get("risks", [])],
        causes=[dict(row) for row in bundle.get("causes", [])],
        solutions=[dict(row) for row in bundle.get("solutions", [])],
        taskTemplates=[dict(row) for row in bundle.get("task_templates", [])],
        actions=[dict(row) for row in bundle.get("actions", [])],
        evidenceTemplates=[dict(row) for row in bundle.get("evidence_templates", [])],
        verifications=[dict(row) for row in bundle.get("verifications", [])],
        counts={
            "activities": len(entities.get("activities", [])),
            "businessObjects": len(entities.get("business_objects", [])),
            "metrics": len(entities.get("metrics", [])),
            "roles": len(entities.get("roles", [])),
            "rules": len(rules),
            "causes": len(bundle.get("causes", [])),
            "solutions": len(bundle.get("solutions", [])),
            "taskTemplates": len(bundle.get("task_templates", [])),
            "actions": len(bundle.get("actions", [])),
        },
        next_steps=["S03 按冻结范围只读取数", "任何缺失字段返回 blocked/partial，不补 0"],
        execution={
            "channel": "fuxi-todo",
            "source": "boulderai-anaylize-todo",
            "tool": "TaskOrderCreate",
            "businessWrite": False,
            "note": "点击任务令只创建 Fuxi 待办；发运/签单/排产等业务动作由 Fuxi 待办侧承接。",
        },
    )
    return payload


def _dedupe_by_code(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        code = str(row.get("code") or row.get("规则编码") or "")
        if code and code in seen:
            continue
        seen.add(code)
        result.append(dict(row))
    return result


def requirements(catalog: Process360Catalog, scenario: str) -> dict[str, Any]:
    """Return the minimum inputs and the blocking gaps for a scenario."""
    bundle = catalog.scenario_bundle(str(scenario).upper())
    blocking = [
        gap(
            str(row.get("code")),
            str(row.get("name") or row.get("事项") or ""),
            needed=str(row.get("必须补充") or ""),
            impact=str(row.get("影响范围") or ""),
        )
        for row in bundle.get("gaps", [])
    ]
    evidence_codes: list[str] = []
    for row in bundle.get("evidence_templates", []):
        evidence_codes.append(str(row.get("code")))
    return {
        "scenario": str(scenario).upper(),
        "requiredInputs": [
            str(row.get("使用规则编码集合") or "")
            for row in bundle.get("evidence_templates", [])
        ],
        "evidenceTemplates": evidence_codes,
        "blockingGaps": blocking,
    }
