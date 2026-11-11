"""Versioned local Process360 catalog.

The catalog is generated from the customer's V3.1 workbook and design document.
It is the runtime semantic source for Process360; the customer database is used
for business facts only.  The database ``meta_*`` tables are not a runtime
replacement for this catalog.
"""

from __future__ import annotations

import json
from copy import deepcopy
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..paths import DATASET_DIR


CATALOG_SCHEMA = "process360.catalog.v1"
DEFAULT_CATALOG_REL = Path("process360") / "ywln-v3.1" / "catalog.json"

_CATALOG_CACHE: dict[tuple[str, int, int], "Process360Catalog"] = {}
_CATALOG_LOCK = threading.RLock()

# Chinese worksheet names -> stable English keys.  Keeping the mapping here
# makes the workbook format explicit and prevents loaders from silently
# depending on one customer's sheet naming.
SHEET_KEYS: dict[str, str] = {
    "业务对象": "business_objects",
    "逻辑实体": "logical_entities",
    "业务属性": "attributes",
    "业务属性映射": "attribute_mappings",
    "业务规则": "business_rules",
    "业务角色": "roles",
    "任务令": "task_templates",
    "使用说明": "usage",
    "元素目录": "element_catalog",
    "动作": "actions",
    "原因因子": "causes",
    "变更清单": "changes",
    "场景": "scenarios",
    "复验": "verifications",
    "实体关系": "entity_relations",
    "对象关系": "object_relations",
    "异常": "anomalies",
    "影响": "impacts",
    "待确认事项": "gaps",
    "指标": "metrics",
    "指标参照配置": "metric_references",
    "指标维度矩阵": "metric_dimension_matrix",
    "方案动作": "solution_actions",
    "本体元素关联": "ontology_links",
    "术语": "terms",
    "校验结果": "source_validation",
    "活动": "activities",
    "流程": "processes",
    "维度": "dimensions",
    "维度层级配置": "dimension_hierarchies",
    "维度派生规则配置": "dimension_rule_configs",
    "维度派生配置": "dimension_join_configs",
    "规则节点绑定": "rule_bindings",
    "解决方案": "solutions",
    "证据": "evidence_templates",
    "运行记录契约": "runtime_records",
    "逻辑实体映射": "entity_mappings",
    "闭环场景总览": "closure_overview",
    "闭环样例": "closure_examples",
    "闭环演算": "closure_calculation",
    "问题": "problems",
    "风险": "risks",
}

CODE_FIELDS: dict[str, tuple[str, ...]] = {
    "business_objects": ("业务对象编码",),
    "logical_entities": ("逻辑实体编码",),
    "attributes": ("业务属性编码",),
    "attribute_mappings": ("业务属性编码",),
    "business_rules": ("规则编码",),
    "roles": ("角色编码",),
    "task_templates": ("任务模板编码",),
    "actions": ("动作编码",),
    "causes": ("原因编码",),
    "changes": ("变更编码",),
    "scenarios": ("场景编码",),
    "verifications": ("复验模板编码",),
    "entity_relations": ("关系编码",),
    "object_relations": ("关系编码",),
    "anomalies": ("异常编码",),
    "impacts": ("影响编码",),
    "gaps": ("缺口编码",),
    "metrics": ("指标编码",),
    "metric_references": ("参照编码",),
    "metric_dimension_matrix": ("指标编码",),
    "solution_actions": ("编排编码",),
    "ontology_links": ("关系编码",),
    "terms": ("术语编码",),
    "activities": ("活动编码",),
    "processes": ("流程编码",),
    "dimensions": ("维度编码",),
    "dimension_hierarchies": ("层级维度编码",),
    "dimension_rule_configs": ("维度派生规则编码",),
    "dimension_join_configs": ("关联编号",),
    "rule_bindings": ("绑定编码",),
    "solutions": ("方案编码",),
    "evidence_templates": ("证据模板编码",),
    "runtime_records": ("记录类型", "字段名"),
    "entity_mappings": ("逻辑实体编码",),
    "closure_overview": ("场景编码",),
    "closure_examples": ("场景编码", "步骤"),
    "closure_calculation": ("场景编码",),
    "problems": ("问题编码",),
    "risks": ("风险编码",),
}

NAME_FIELDS: dict[str, tuple[str, ...]] = {
    "business_objects": ("业务对象名称",),
    "logical_entities": ("逻辑实体名称",),
    "attributes": ("业务属性名称",),
    "business_rules": ("规则名称",),
    "roles": ("角色名称",),
    "task_templates": ("任务名称",),
    "actions": ("动作名称",),
    "causes": ("原因名称",),
    "scenarios": ("场景名称",),
    "verifications": ("名称",),
    "anomalies": ("异常名称",),
    "impacts": ("影响名称",),
    "gaps": ("事项",),
    "metrics": ("指标名称",),
    "metric_references": ("名称",),
    "solution_actions": ("方案编码",),
    "terms": ("术语名称",),
    "activities": ("活动名称",),
    "processes": ("流程名称",),
    "dimensions": ("维度名称",),
    "solutions": ("方案名称",),
    "evidence_templates": ("证据名称",),
    "problems": ("问题名称",),
    "risks": ("风险名称",),
}


@dataclass(frozen=True)
class CatalogValidationIssue:
    severity: str
    code: str
    message: str
    sheet: str = ""
    record_id: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "sheet": self.sheet,
            "recordId": self.record_id,
        }


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _codes(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = _text(value)
    if not text or text in {"无", "N/A", "待配置", "待确认"}:
        return []
    return [item.strip() for item in re.split(r"[、,，;；/\s]+", text) if item.strip()]


def _canonical_code(sheet: str, row: Mapping[str, Any]) -> str:
    fields = CODE_FIELDS.get(sheet, ())
    if sheet == "runtime_records":
        return ":".join(_text(row.get(field, "")) for field in fields)
    if sheet == "closure_examples":
        return f"{_text(row.get('场景编码', ''))}:{_text(row.get('步骤', ''))}"
    for field in fields:
        value = _text(row.get(field, ""))
        if value:
            return value
    return ""


def _canonical_name(sheet: str, row: Mapping[str, Any]) -> str:
    for field in NAME_FIELDS.get(sheet, ()):
        value = _text(row.get(field, ""))
        if value:
            return value
    return ""


class Process360Catalog:
    """Read-only, indexed view over one generated Process360 catalog."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        if payload.get("schema") != CATALOG_SCHEMA:
            raise ValueError(f"unsupported Process360 catalog schema: {payload.get('schema')!r}")
        payload = deepcopy(dict(payload))
        self._payload = payload
        self.catalog_id = (
            _text(payload.get("catalogId")) or _text(payload.get("catalog_id")) or "process360"
        )
        self.version = _text(payload.get("version")) or "unknown"
        self._sops: list[dict[str, Any]] = [
            dict(item) for item in payload.get("sops", []) if isinstance(item, Mapping)
        ]
        raw_sheets = payload.get("sheets")
        if not isinstance(raw_sheets, Mapping):
            raise ValueError("Process360 catalog is missing sheets")
        self._sheets: dict[str, list[dict[str, Any]]] = {
            str(key): [dict(row) for row in rows if isinstance(row, Mapping)]
            for key, rows in raw_sheets.items()
        }
        self._index: dict[str, dict[str, dict[str, Any]]] = {}
        self._sop_index: dict[str, dict[str, Any]] = {str(s.get("id")): s for s in self._sops}
        self._uses_customer_physical_tables = any(
            _text(row.get("客户接入状态")) and _text(row.get("关联物理表"))
            for row in self._sheets.get("entity_mappings", [])
        )
        self._build_index()

    @classmethod
    def from_file(cls, path: str | Path) -> "Process360Catalog":
        target = Path(path)
        stat = target.stat()
        key = (str(target.resolve()), stat.st_mtime_ns, stat.st_size)
        with _CATALOG_LOCK:
            cached = _CATALOG_CACHE.get(key)
            if cached is not None:
                return cached
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("Process360 catalog must be a JSON object")
        catalog = cls(payload)
        errors = [i for i in catalog.validate() if i.severity == "error"]
        if errors:
            raise ValueError(
                "Process360 catalog validation failed: " + ", ".join(i.code for i in errors[:5])
            )
        with _CATALOG_LOCK:
            # Keep only the current version for this path to bound memory.
            for stale in [item for item in _CATALOG_CACHE if item[0] == key[0] and item != key]:
                _CATALOG_CACHE.pop(stale, None)
            _CATALOG_CACHE[key] = catalog
        return catalog

    @classmethod
    def from_project(
        cls, cwd: str | Path = ".", path: str | Path | None = None
    ) -> "Process360Catalog":
        target = Path(path) if path else Path(DATASET_DIR) / DEFAULT_CATALOG_REL
        if not target.is_absolute():
            target = Path(cwd).resolve() / target
        return cls.from_file(target)

    def _build_index(self) -> None:
        for sheet, rows in self._sheets.items():
            index: dict[str, dict[str, Any]] = {}
            for row in rows:
                if not row.get("code"):
                    row["code"] = _canonical_code(sheet, row)
                if not row.get("name"):
                    row["name"] = _canonical_name(sheet, row)
                code = _text(row.get("code"))
                if code:
                    index[code] = row
            self._index[sheet] = index

    @property
    def payload(self):
        return deepcopy(self._payload)

    @property
    def sheets(self):
        return deepcopy(self._sheets)

    @property
    def sops(self):
        return deepcopy(self._sops)

    # -- basic access -----------------------------------------------------

    def records(self, sheet: str) -> list[dict[str, Any]]:
        return deepcopy(self._sheets.get(sheet, []))

    def get(self, sheet: str, code: str) -> dict[str, Any] | None:
        return deepcopy(self._index.get(sheet, {}).get(_text(code)))

    def sop(self, sop_id: str) -> dict[str, Any] | None:
        return deepcopy(self._sop_index.get(_text(sop_id).upper()))

    def find(self, code: str) -> list[dict[str, Any]]:
        wanted = _text(code)
        found: list[dict[str, Any]] = []
        for sheet, index in self._index.items():
            if wanted in index:
                found.append({"sheet": sheet, **index[wanted]})
        return deepcopy(found)

    def metric(self, code: str) -> dict[str, Any] | None:
        return self.get("metrics", code)

    def scenario(self, code: str) -> dict[str, Any] | None:
        return self.get("scenarios", code)

    @property
    def uses_customer_physical_tables(self) -> bool:
        """Whether mappings point at a customer physical schema, not legacy LE views."""
        return self._uses_customer_physical_tables

    def physical_table(self, entity_code: str) -> str:
        """Return the mapped physical table, or empty for a blocked mapping."""
        row = self.get("entity_mappings", entity_code) or {}
        status = _text(row.get("客户接入状态"))
        if status.lower().startswith("blocked"):
            return ""
        return _text(row.get("关联物理表"))

    def physical_field(self, attribute_code: str) -> str:
        """Return the mapped physical column, or empty for a blocked mapping."""
        row = self.get("attribute_mappings", attribute_code) or {}
        status = _text(row.get("客户接入状态"))
        if status.lower().startswith("blocked"):
            return ""
        return _text(row.get("来源字段") or row.get("客户来源字段"))

    def entities_for_scenario(self, code: str) -> dict[str, list[dict[str, Any]]]:
        scenario = self.scenario(code) or {}
        result: dict[str, list[dict[str, Any]]] = {}
        for field, sheet in (
            ("活动编码集合", "activities"),
            ("业务对象编码集合", "business_objects"),
            ("指标编码集合", "metrics"),
            ("使用角色编码集合", "roles"),
        ):
            result[sheet] = [
                self.get(sheet, item) or {"code": item} for item in _codes(scenario.get(field))
            ]
        process = self.get("processes", _text(scenario.get("流程编码")))
        result["processes"] = [process] if process else []
        return result

    def scenario_bundle(self, code: str) -> dict[str, Any]:
        scenario = self.scenario(code)
        if not scenario:
            raise KeyError(f"unknown scenario {code}")
        bundle: dict[str, Any] = {
            "scenario": scenario,
            "entities": self.entities_for_scenario(code),
        }
        for sheet, field in (
            ("anomalies", "场景编码"),
            ("problems", "场景编码"),
        ):
            bundle[sheet] = [
                row for row in self._sheets.get(sheet, []) if _text(row.get(field)) == code
            ]
        overview = next(
            (row for row in self._sheets.get("closure_overview", []) if row.get("code") == code),
            {},
        )
        bundle["gaps"] = [
            self.get("gaps", gap_code) or {"code": gap_code}
            for gap_code in _codes(overview.get("接入缺口"))
        ]
        problem_codes = {row.get("code") for row in bundle["problems"]}
        bundle["risks"] = [
            row for row in self._sheets.get("risks", []) if row.get("问题编码") in problem_codes
        ]
        problem_code_list = [code for code in problem_codes if code]
        # Causes do not carry a problem key in V3.1; expose all causes for the
        # scenario's activities so S04 can still validate candidate paths.
        activity_codes = {row.get("code") for row in bundle["entities"].get("activities", [])}
        bundle["solutions"] = [
            row
            for row in self._sheets.get("solutions", [])
            if row.get("问题编码") in problem_code_list
        ]
        solution_codes = {row.get("code") for row in bundle["solutions"]}
        bundle["causes"] = [
            row
            for row in self._sheets.get("causes", [])
            if _shares(row.get("候选方案编码"), solution_codes)
            or (
                not _codes(row.get("候选方案编码"))
                and _shares(row.get("作用活动编码"), activity_codes)
            )
        ]
        bundle["task_templates"] = [
            row
            for row in self._sheets.get("task_templates", [])
            if row.get("方案编码") in solution_codes or row.get("问题编码") in problem_code_list
        ]
        action_codes: set[str] = set()
        for row in [*bundle["solutions"], *bundle["task_templates"]]:
            for field in ("核心Action编码集合", "下发Action编码"):
                action_codes.update(_codes(row.get(field)))
        bundle["actions"] = [
            row for row in self._sheets.get("actions", []) if row.get("code") in action_codes
        ]
        evidence_codes: set[str] = set(_all_codes(bundle["causes"], "证据模板编码"))
        verification_codes: set[str] = set()
        for row in [*bundle["solutions"], *bundle["task_templates"]]:
            verification_codes.update(_codes(row.get("复验模板编码")))
        for row in self._sheets.get("verifications", []):
            if row.get("code") in verification_codes:
                evidence_codes.update(_codes(row.get("证据模板编码集合")))
        bundle["evidence_templates"] = [
            row
            for row in self._sheets.get("evidence_templates", [])
            if row.get("code") in evidence_codes
        ]
        bundle["verifications"] = [
            row
            for row in self._sheets.get("verifications", [])
            if row.get("code") in verification_codes
        ]
        return deepcopy(bundle)

    # -- search and validation --------------------------------------------

    def search(
        self, query: str, *, limit: int = 20, scenario: str | None = None
    ) -> list[dict[str, Any]]:
        """Dual-entry search: metrics and business objects only."""
        text = _text(query).lower()
        if not text:
            return []
        tokens = [token for token in re.split(r"\s+", text) if token]
        results: list[dict[str, Any]] = []
        allowed = self.entities_for_scenario(str(scenario).upper()) if scenario else None
        for sheet in ("metrics", "business_objects"):
            for row in self._sheets.get(sheet, []):
                if allowed is not None and row.get("code") not in {
                    r.get("code") for r in allowed.get(sheet, [])
                }:
                    continue
                haystack = " ".join(
                    _text(row.get(key)).lower()
                    for key in (
                        "code",
                        "name",
                        "指标名称",
                        "指标别名",
                        "指标英文名",
                        "业务对象名称",
                        "业务对象英文名",
                        "定义",
                        "业务对象定义",
                    )
                )
                score = sum(1 for token in tokens if token in haystack)
                if text in haystack:
                    score += 3
                if row.get("code", "").lower() == text:
                    score += 10
                if score:
                    results.append(
                        {
                            "entryType": "metric" if sheet == "metrics" else "businessObject",
                            "sheet": sheet,
                            "code": row.get("code", ""),
                            "name": row.get("name", ""),
                            "score": score,
                            "record": row,
                        }
                    )
        results.sort(key=lambda item: (-item["score"], item["code"]))
        return deepcopy(results[: max(0, min(limit, 100))])

    def validate(self) -> list[CatalogValidationIssue]:
        issues: list[CatalogValidationIssue] = []
        for sheet, rows in self._sheets.items():
            keyed = bool(CODE_FIELDS.get(sheet))
            if not keyed and sheet not in {"usage", "element_catalog", "source_validation"}:
                continue
            seen: set[str] = set()
            for row in rows:
                code = _text(row.get("code")) or _canonical_code(sheet, row)
                if keyed and not code:
                    issues.append(
                        CatalogValidationIssue(
                            "warning", "MISSING_CODE", "record has no code", sheet
                        )
                    )
                    continue
                if code and code in seen:
                    issues.append(
                        CatalogValidationIssue(
                            "error", "DUPLICATE_CODE", f"duplicate code {code}", sheet, code
                        )
                    )
                seen.add(code)

        def require(sheet: str, code: str, field_label: str, record_id: str) -> None:
            if code and not self.get(sheet, code):
                issues.append(
                    CatalogValidationIssue(
                        "error",
                        "MISSING_REFERENCE",
                        f"{field_label} references missing {sheet} {code}",
                        sheet,
                        record_id,
                    )
                )

        for scenario in self._sheets.get("scenarios", []):
            code = _text(scenario.get("code"))
            require("processes", _text(scenario.get("流程编码")), "流程编码", code)
            for item in _codes(scenario.get("活动编码集合")):
                require("activities", item, "活动编码集合", code)
            for item in _codes(scenario.get("业务对象编码集合")):
                require("business_objects", item, "业务对象编码集合", code)
            for item in _codes(scenario.get("指标编码集合")):
                require("metrics", item, "指标编码集合", code)
            for item in _codes(scenario.get("使用角色编码集合")):
                require("roles", item, "使用角色编码集合", code)
        for anomaly in self._sheets.get("anomalies", []):
            code = _text(anomaly.get("code"))
            for item in _codes(anomaly.get("指标编码集合")):
                require("metrics", item, "指标编码集合", code)
            for item in _codes(anomaly.get("识别规则编码")):
                require("business_rules", item, "识别规则编码", code)
            require("scenarios", _text(anomaly.get("场景编码")), "场景编码", code)
        for problem in self._sheets.get("problems", []):
            code = _text(problem.get("code"))
            for item in _codes(problem.get("异常编码集合")):
                require("anomalies", item, "异常编码集合", code)
        for solution in self._sheets.get("solutions", []):
            code = _text(solution.get("code"))
            require("problems", _text(solution.get("问题编码")), "问题编码", code)
            for item in _codes(solution.get("核心Action编码集合")):
                require("actions", item, "核心Action编码集合", code)
            for item in _codes(solution.get("任务模板编码")):
                require("task_templates", item, "任务模板编码", code)
            for item in _codes(solution.get("复验模板编码")):
                require("verifications", item, "复验模板编码", code)
        for task in self._sheets.get("task_templates", []):
            code = _text(task.get("code"))
            for item in _codes(task.get("下发Action编码")):
                require("actions", item, "下发Action编码", code)
            for item in _codes(task.get("核心Action编码集合")):
                require("actions", item, "核心Action编码集合", code)
            for item in _codes(task.get("复验模板编码")):
                require("verifications", item, "复验模板编码", code)
        for sop in self._sops:
            for skill in _codes(sop.get("skills")):
                if not re.fullmatch(r"S0[0-8]", skill):
                    issues.append(
                        CatalogValidationIssue(
                            "warning",
                            "UNKNOWN_SKILL",
                            f"SOP {sop.get('id')} references unknown skill {skill}",
                            "sops",
                            str(sop.get("id")),
                        )
                    )
        return issues

    def summary(self) -> dict[str, int]:
        return {sheet: len(rows) for sheet, rows in sorted(self._sheets.items())} | {
            "sops": len(self._sops)
        }


def _shares(value: Any, wanted: Iterable[str]) -> bool:
    wanted_set = {item for item in wanted if item}
    return bool(set(_codes(value)) & wanted_set)


def _all_codes(rows: Iterable[Mapping[str, Any]], field: str) -> set[str]:
    result: set[str] = set()
    for row in rows:
        result.update(_codes(row.get(field)))
    return result
