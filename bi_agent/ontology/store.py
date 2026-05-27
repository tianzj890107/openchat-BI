"""
OntologyStore — loads the ChatBI 业务元数据 xlsx into memory and provides
indexed lookup + keyword search for the BI agent.

Design:
- Single entry point: OntologyStore.from_xlsx(path) returns a fully-loaded store.
- In-memory dicts keyed by code, plus secondary indexes by name and alias.
- Lookup APIs are thin; the agent does heavier reasoning via to_prompt() snippets.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

import openpyxl

from .schema import (
    Activity,
    Attribute,
    BusinessObject,
    BusinessRule,
    DimMatrixEntry,
    EntityRelation,
    LogicalEntity,
    METRIC_TYPE_ATOMIC,
    Metric,
    Term,
)


# Sheet name constants (match the real xlsx exactly)
SHEET_TERM = "术语"
SHEET_BO = "业务对象"
SHEET_LE = "逻辑实体"
SHEET_AT = "业务属性"
SHEET_ER = "实体关系"
SHEET_METRIC = "指标"
SHEET_ACTIVITY = "活动"
SHEET_RULE = "业务规则"
SHEET_DIM_MATRIX = "指标维度矩阵"


def _norm(v) -> str:
    """Coerce an xlsx cell to a stripped string (empty string for None)."""
    if v is None:
        return ""
    return str(v).strip()


def _split_list(v) -> list[str]:
    """Split a multi-value cell separated by comma / Chinese comma / semicolon."""
    s = _norm(v)
    if not s:
        return []
    for sep in [",", ",", ";", ";", "、"]:
        s = s.replace(sep, "|")
    return [x.strip() for x in s.split("|") if x.strip()]


def _truthy(v) -> bool:
    s = _norm(v).lower()
    return s in {"y", "yes", "1", "true", "是"}


class OntologyStore:
    """In-memory ontology loaded from the ChatBI xlsx."""

    def __init__(self) -> None:
        self.terms: dict[str, Term] = {}
        self.business_objects: dict[str, BusinessObject] = {}
        self.logical_entities: dict[str, LogicalEntity] = {}
        self.attributes: dict[str, Attribute] = {}
        self.relations: dict[str, EntityRelation] = {}
        self.metrics: dict[str, Metric] = {}
        self.activities: dict[str, Activity] = {}
        self.rules: dict[str, BusinessRule] = {}
        self.dim_matrix: dict[str, DimMatrixEntry] = {}

        # Secondary indexes
        self._term_by_name: dict[str, str] = {}        # name/alias (lower) -> code
        self._bo_by_name: dict[str, str] = {}
        self._le_by_name: dict[str, str] = {}
        self._le_by_table: dict[str, str] = {}         # physical_table -> le_code
        self._metric_by_name: dict[str, str] = {}      # name/alias (lower) -> code
        self._attrs_by_le: dict[str, list[str]] = {}   # le_code -> [at_code, ...]
        self._les_by_bo: dict[str, list[str]] = {}     # bo_code -> [le_code, ...]
        self._relations_by_le: dict[str, list[str]] = {}  # le_code -> [er_code, ...]

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    @classmethod
    def from_xlsx(cls, path: str | Path) -> "OntologyStore":
        store = cls()
        wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
        store._load_terms(wb[SHEET_TERM])
        store._load_business_objects(wb[SHEET_BO])
        store._load_logical_entities(wb[SHEET_LE])
        store._load_attributes(wb[SHEET_AT])
        store._load_relations(wb[SHEET_ER])
        store._load_metrics(wb[SHEET_METRIC])
        store._load_activities(wb[SHEET_ACTIVITY])
        store._load_rules(wb[SHEET_RULE])
        store._load_dim_matrix(wb[SHEET_DIM_MATRIX])
        wb.close()
        store._wire_metric_dimensions()
        return store

    @staticmethod
    def _rows(ws) -> Iterable[tuple]:
        """Yield data rows (skip header), padding short rows with None."""
        it = ws.iter_rows(values_only=True)
        header = next(it, None)
        if header is None:
            return
        width = len(header)
        for row in it:
            if row is None:
                continue
            if all(c is None or _norm(c) == "" for c in row):
                continue
            if len(row) < width:
                row = row + (None,) * (width - len(row))
            yield row

    # --- Header-driven loading -------------------------------------------
    # Some sheets (指标 / 实体关系) differ in column layout between ontology
    # files (e.g. ChatBI 17-col 指标 vs 超聚变 8-col 指标). Loaders for those
    # sheets map by header NAME instead of fixed position.

    @staticmethod
    def _norm_key(s) -> str:
        """Normalize a header / lookup name: drop brackets, commas, spaces."""
        out = _norm(s)
        for ch in "（）()【】[]，,、 　":
            out = out.replace(ch, "")
        return out

    @staticmethod
    def _col_index(header) -> dict:
        """Map normalized header names -> column index (first occurrence wins)."""
        idx: dict[str, int] = {}
        for i, h in enumerate(header or ()):
            key = OntologyStore._norm_key(h)
            if key and key not in idx:
                idx[key] = i
        return idx

    @staticmethod
    def _cell(row, col_idx: dict, *names: str) -> str:
        """Read a row value by any candidate header name (exact, then prefix)."""
        for n in names:
            key = OntologyStore._norm_key(n)
            if not key:
                continue
            pos = col_idx.get(key)
            if pos is None:
                for hk, hp in col_idx.items():
                    if hk.startswith(key):
                        pos = hp
                        break
            if pos is not None and pos < len(row):
                return _norm(row[pos])
        return ""

    @staticmethod
    def _indexed(ws):
        """Return (col_index, data_rows) for a sheet — header mapped by name."""
        it = ws.iter_rows(values_only=True)
        header = next(it, None)
        col = OntologyStore._col_index(header)
        rows = [
            row for row in it
            if row is not None and not all(c is None or _norm(c) == "" for c in row)
        ]
        return col, rows

    def _load_terms(self, ws) -> None:
        for row in self._rows(ws):
            code = _norm(row[0])
            if not code:
                continue
            term = Term(
                code=code,
                name=_norm(row[1]),
                aliases=_split_list(row[2]),
                english=_norm(row[3]),
                definition=_norm(row[4]),
                category=_norm(row[5]),
                department=_norm(row[6]) if len(row) > 6 else "",
            )
            self.terms[code] = term
            if term.name:
                self._term_by_name[term.name.lower()] = code
            for alias in term.aliases:
                self._term_by_name[alias.lower()] = code

    def _load_business_objects(self, ws) -> None:
        for row in self._rows(ws):
            code = _norm(row[0])
            if not code:
                continue
            bo = BusinessObject(
                code=code,
                name=_norm(row[1]),
                english=_norm(row[2]),
                definition=_norm(row[3]),
                type=_norm(row[4]),
                physical_table=_norm(row[5]) if len(row) > 5 else "",
            )
            self.business_objects[code] = bo
            if bo.name:
                self._bo_by_name[bo.name.lower()] = code

    def _load_logical_entities(self, ws) -> None:
        for row in self._rows(ws):
            bo_code = _norm(row[0])
            bo_name = _norm(row[1])
            le_code = _norm(row[2])
            if not le_code:
                continue
            le = LogicalEntity(
                code=le_code,
                name=_norm(row[3]),
                english=_norm(row[4]),
                definition=_norm(row[5]),
                physical_table=_norm(row[6]) if len(row) > 6 else "",
                bo_code=bo_code,
                bo_name=bo_name,
            )
            self.logical_entities[le_code] = le
            if le.name:
                self._le_by_name[le.name.lower()] = le_code
            if le.physical_table:
                self._le_by_table[le.physical_table] = le_code
            if bo_code:
                self._les_by_bo.setdefault(bo_code, []).append(le_code)

    def _load_attributes(self, ws) -> None:
        for row in self._rows(ws):
            le_code = _norm(row[0])
            at_code = _norm(row[3])
            if not at_code:
                continue
            attr = Attribute(
                code=at_code,
                name=_norm(row[4]),
                english=_norm(row[5]),
                definition=_norm(row[6]),
                data_type=_norm(row[7]),
                is_primary_key=_truthy(row[8]) if len(row) > 8 else False,
                le_code=le_code,
                le_name=_norm(row[1]),
                le_english=_norm(row[2]),
            )
            self.attributes[at_code] = attr
            if le_code:
                self._attrs_by_le.setdefault(le_code, []).append(at_code)

    def _load_relations(self, ws) -> None:
        # Header-driven: ChatBI uses 源/目标实体, 超聚变 uses 主/从实体.
        col, rows = self._indexed(ws)
        for row in rows:
            code = self._cell(row, col, "关系编号")
            if not code:
                continue
            er = EntityRelation(
                code=code,
                source_code=self._cell(row, col, "源实体编号", "主实体编号"),
                source_name=self._cell(row, col, "源实体名称", "主实体名称"),
                target_code=self._cell(row, col, "目标实体编号", "从实体编号"),
                target_name=self._cell(row, col, "目标实体名称", "从实体名称"),
                cardinality=self._cell(row, col, "关系类型"),
                description=self._cell(row, col, "关系描述", "关系说明"),
                foreign_key=self._cell(row, col, "外键字段", "关联条件"),
            )
            self.relations[code] = er
            if er.source_code:
                self._relations_by_le.setdefault(er.source_code, []).append(code)
            if er.target_code and er.target_code != er.source_code:
                self._relations_by_le.setdefault(er.target_code, []).append(code)

    def _load_metrics(self, ws) -> None:
        # Header-driven: ChatBI 指标 has 17 rich columns; 超聚变 指标 has 8
        # (编号/名称/英文名/定义/计算口径/数据类型/来源实体/解释部门).
        col, rows = self._indexed(ws)
        for row in rows:
            code = self._cell(row, col, "指标编码", "指标编号")
            if not code:
                continue
            type_raw = self._cell(row, col, "指标类型")
            try:
                mtype = int(type_raw) if type_raw else METRIC_TYPE_ATOMIC
            except (TypeError, ValueError):
                mtype = METRIC_TYPE_ATOMIC
            # 超聚变 carries a single 计算口径 column; reuse it where the
            # richer ChatBI 业务公式 / 统计口径 columns are absent.
            caliber = self._cell(row, col, "计算口径")
            metric = Metric(
                code=code,
                name=self._cell(row, col, "指标名称"),
                aliases=_split_list(self._cell(row, col, "指标别名")),
                english=self._cell(row, col, "指标英文名"),
                definition=self._cell(row, col, "指标定义"),
                formula_business=self._cell(row, col, "计算公式(业务)") or caliber,
                scope=self._cell(row, col, "统计口径") or caliber,
                metric_type=mtype,
                formula_technical=self._cell(row, col, "计算公式(技术)"),
                table=self._cell(row, col, "对应表名", "来源实体"),
                agg_column=self._cell(row, col, "聚合列"),
                agg_type=self._cell(row, col, "聚合类型"),
                join_condition=self._cell(row, col, "连接条件"),
                filter_condition=self._cell(row, col, "筛选条件"),
                dim_columns=self._cell(row, col, "维度列"),
                version=self._cell(row, col, "版本"),
                change_note=self._cell(row, col, "修改说明"),
            )
            self.metrics[code] = metric
            if metric.name:
                self._metric_by_name[metric.name.lower()] = code
            for alias in metric.aliases:
                self._metric_by_name[alias.lower()] = code

    def _load_activities(self, ws) -> None:
        for row in self._rows(ws):
            code = _norm(row[0])
            if not code:
                continue
            act = Activity(
                code=code,
                name=_norm(row[1]),
                description=_norm(row[2]),
                upstream_codes=_split_list(row[3]),
                role=_norm(row[4]),
                object_codes=_split_list(row[5]),
                object_names=_split_list(row[6]) if len(row) > 6 else [],
            )
            self.activities[code] = act

    def _load_rules(self, ws) -> None:
        for row in self._rows(ws):
            code = _norm(row[0])
            if not code:
                continue
            rule = BusinessRule(
                code=code,
                rule=_norm(row[1]),
                activity_code=_norm(row[2]),
                activity_name=_norm(row[3]),
                category=_norm(row[4]),
                department=_norm(row[5]) if len(row) > 5 else "",
            )
            self.rules[code] = rule

    def _load_dim_matrix(self, ws) -> None:
        it = ws.iter_rows(values_only=True)
        header = next(it, None)
        if header is None:
            return
        dim_names = [_norm(h) for h in header[2:]]  # cols 0,1 are metric code/name
        for row in it:
            if row is None or not _norm(row[0]):
                continue
            metric_code = _norm(row[0])
            metric_name = _norm(row[1])
            dims: dict[str, bool] = {}
            for i, dim in enumerate(dim_names):
                if not dim:
                    continue
                cell = row[2 + i] if 2 + i < len(row) else None
                dims[dim] = _truthy(cell)
            self.dim_matrix[metric_code] = DimMatrixEntry(
                metric_code=metric_code,
                metric_name=metric_name,
                dimensions=dims,
            )

    def _wire_metric_dimensions(self) -> None:
        """Copy applicable dimensions from dim_matrix into each Metric."""
        for code, metric in self.metrics.items():
            entry = self.dim_matrix.get(code)
            if entry:
                metric.applicable_dimensions = entry.applicable()

    # ------------------------------------------------------------------
    # Lookup APIs
    # ------------------------------------------------------------------

    def find_term(self, query: str) -> list[Term]:
        """Resolve a term by name or alias; returns all that match (usually 1)."""
        q = query.strip().lower()
        if not q:
            return []
        hits: list[Term] = []
        # Exact match on name/alias index
        code = self._term_by_name.get(q)
        if code:
            hits.append(self.terms[code])
        # Substring fallback over name/alias/definition
        if not hits:
            for t in self.terms.values():
                hay = " ".join([t.name, *t.aliases, t.english, t.definition]).lower()
                if q in hay:
                    hits.append(t)
        return hits

    def find_metric(self, query: str) -> list[Metric]:
        q = query.strip().lower()
        if not q:
            return []
        code = self._metric_by_name.get(q)
        if code:
            return [self.metrics[code]]
        hits: list[Metric] = []
        for m in self.metrics.values():
            hay = " ".join([m.name, *m.aliases, m.english, m.definition]).lower()
            if q in hay:
                hits.append(m)
        return hits

    def get_business_object(self, code_or_name: str) -> Optional[BusinessObject]:
        key = code_or_name.strip()
        if key in self.business_objects:
            return self.business_objects[key]
        code = self._bo_by_name.get(key.lower())
        return self.business_objects.get(code) if code else None

    def get_logical_entity(self, code_or_name: str) -> Optional[LogicalEntity]:
        key = code_or_name.strip()
        if key in self.logical_entities:
            return self.logical_entities[key]
        code = self._le_by_name.get(key.lower())
        if code:
            return self.logical_entities[code]
        code = self._le_by_table.get(key)
        return self.logical_entities.get(code) if code else None

    def attributes_of(self, le_code: str) -> list[Attribute]:
        return [self.attributes[c] for c in self._attrs_by_le.get(le_code, [])]

    def logical_entities_of(self, bo_code: str) -> list[LogicalEntity]:
        return [self.logical_entities[c] for c in self._les_by_bo.get(bo_code, [])]

    def relations_of(self, le_code: str) -> list[EntityRelation]:
        seen: set[str] = set()
        out: list[EntityRelation] = []
        for c in self._relations_by_le.get(le_code, []):
            if c in seen:
                continue
            seen.add(c)
            out.append(self.relations[c])
        return out

    def rules_of(self, activity_code: str) -> list[BusinessRule]:
        return [r for r in self.rules.values() if r.activity_code == activity_code]

    def search(self, query: str, limit: int = 20) -> dict[str, list]:
        """Cross-ontology keyword search. Returns buckets by type."""
        q = query.strip().lower()
        result: dict[str, list] = {
            "terms": [], "business_objects": [], "logical_entities": [],
            "metrics": [], "activities": [], "rules": [],
        }
        if not q:
            return result

        def _match(*texts: str) -> bool:
            return q in " ".join(t for t in texts if t).lower()

        for t in self.terms.values():
            if _match(t.name, *t.aliases, t.english, t.definition):
                result["terms"].append(t)
        for bo in self.business_objects.values():
            if _match(bo.name, bo.english, bo.definition, bo.physical_table):
                result["business_objects"].append(bo)
        for le in self.logical_entities.values():
            if _match(le.name, le.english, le.definition, le.physical_table):
                result["logical_entities"].append(le)
        for m in self.metrics.values():
            if _match(m.name, *m.aliases, m.english, m.definition, m.scope):
                result["metrics"].append(m)
        for a in self.activities.values():
            if _match(a.name, a.description):
                result["activities"].append(a)
        for r in self.rules.values():
            if _match(r.rule, r.activity_name, r.category):
                result["rules"].append(r)

        for k in result:
            result[k] = result[k][:limit]
        return result

    def stats(self) -> dict[str, int]:
        return {
            "terms": len(self.terms),
            "business_objects": len(self.business_objects),
            "logical_entities": len(self.logical_entities),
            "attributes": len(self.attributes),
            "relations": len(self.relations),
            "metrics": len(self.metrics),
            "activities": len(self.activities),
            "rules": len(self.rules),
        }
