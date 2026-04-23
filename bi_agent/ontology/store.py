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
        for row in self._rows(ws):
            code = _norm(row[0])
            if not code:
                continue
            er = EntityRelation(
                code=code,
                source_code=_norm(row[1]),
                source_name=_norm(row[2]),
                target_code=_norm(row[3]),
                target_name=_norm(row[4]),
                cardinality=_norm(row[5]),
                description=_norm(row[6]),
                foreign_key=_norm(row[7]) if len(row) > 7 else "",
            )
            self.relations[code] = er
            if er.source_code:
                self._relations_by_le.setdefault(er.source_code, []).append(code)
            if er.target_code and er.target_code != er.source_code:
                self._relations_by_le.setdefault(er.target_code, []).append(code)

    def _load_metrics(self, ws) -> None:
        for row in self._rows(ws):
            code = _norm(row[0])
            if not code:
                continue
            try:
                mtype = int(row[7]) if row[7] is not None else METRIC_TYPE_ATOMIC
            except (TypeError, ValueError):
                mtype = METRIC_TYPE_ATOMIC
            metric = Metric(
                code=code,
                name=_norm(row[1]),
                aliases=_split_list(row[2]),
                english=_norm(row[3]),
                definition=_norm(row[4]),
                formula_business=_norm(row[5]),
                scope=_norm(row[6]),
                metric_type=mtype,
                formula_technical=_norm(row[8]),
                table=_norm(row[9]),
                agg_column=_norm(row[10]),
                agg_type=_norm(row[11]),
                join_condition=_norm(row[12]),
                filter_condition=_norm(row[13]),
                dim_columns=_norm(row[14]) if len(row) > 14 else "",
                version=_norm(row[15]) if len(row) > 15 else "",
                change_note=_norm(row[16]) if len(row) > 16 else "",
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
