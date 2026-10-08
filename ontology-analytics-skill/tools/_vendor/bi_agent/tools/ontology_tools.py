"""
Ontology tools — expose OntologyStore as tool-use endpoints for the BI agent.

Each tool is a pair (schema, factory) where the factory binds a store instance
to the executor closure. register_all() in the tools package wires them up.
"""

from __future__ import annotations

from typing import Callable

from ..ontology.store import OntologyStore


Executor = Callable[[dict, str], str]
ExecutorFactory = Callable[[OntologyStore], Executor]


# ---------------------------------------------------------------------------
# Ontology-SemanticQuery — cross-ontology keyword search
# ---------------------------------------------------------------------------

ONTOLOGY_QUERY_SCHEMA = {
    "name": "Ontology-SemanticQuery",
    "description": (
        "Cross-ontology keyword search. Searches terms, business objects, "
        "logical entities, metrics, activities, and rules by substring. "
        "Use this at the start of intent recognition to discover what the "
        "user's words map to in the knowledge base."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keyword or phrase."},
            "limit": {"type": "integer", "description": "Per-bucket cap (default 10)."},
        },
        "required": ["query"],
    },
}


def _make_ontology_query(store: OntologyStore) -> Executor:
    def run(params: dict, cwd: str) -> str:
        query = (params.get("query") or "").strip()
        limit = int(params.get("limit") or 10)
        if not query:
            return "Ontology-SemanticQuery: empty query."
        buckets = store.search(query, limit=limit)
        sections: list[str] = [f"# Ontology-SemanticQuery: {query!r}"]
        labels = {
            "terms": "术语 (Terms)",
            "business_objects": "业务对象 (Business Objects)",
            "logical_entities": "逻辑实体 (Logical Entities)",
            "metrics": "指标 (Metrics)",
            "activities": "活动 (Activities)",
            "rules": "规则 (Rules)",
        }
        total = 0
        for key, label in labels.items():
            items = buckets[key]
            if not items:
                continue
            total += len(items)
            sections.append(f"\n## {label} ({len(items)})")
            for it in items:
                sections.append(it.to_prompt())
        if total == 0:
            return f"Ontology-SemanticQuery: no matches for {query!r}."
        return "\n".join(sections)
    return run


# ---------------------------------------------------------------------------
# Ontology-TermDisambiguate — resolve a single term to its canonical entry
# ---------------------------------------------------------------------------

TERM_DISAMBIGUATE_SCHEMA = {
    "name": "Ontology-TermDisambiguate",
    "description": (
        "Resolve a user-facing word or phrase to its canonical term entry "
        "(definition, category, aliases). Call this whenever a user uses "
        "business vocabulary and you're not certain of the exact meaning."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "term": {"type": "string", "description": "Term name or alias."},
        },
        "required": ["term"],
    },
}


def _make_term_disambiguate(store: OntologyStore) -> Executor:
    def run(params: dict, cwd: str) -> str:
        term = (params.get("term") or "").strip()
        if not term:
            return "Ontology-TermDisambiguate: empty term."
        hits = store.find_term(term)
        if not hits:
            return f"Ontology-TermDisambiguate: no term matches {term!r}."
        if len(hits) == 1:
            return hits[0].to_prompt()
        lines = [f"Ontology-TermDisambiguate: {len(hits)} candidates for {term!r}:"]
        for t in hits:
            lines.append(t.to_prompt())
        return "\n\n".join(lines)
    return run


# ---------------------------------------------------------------------------
# MetricCalculation — full metric spec including SQL hints + dims
# ---------------------------------------------------------------------------

METRIC_LOOKUP_SCHEMA = {
    "name": "MetricCalculation",
    "description": (
        "Return the full spec of a metric: business formula, scope, SQL "
        "components (table/agg_column/agg_type/filter/join), and the list "
        "of applicable dimensions from the dim matrix. Call this before "
        "drafting SQL to make sure you use the authoritative definition."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "metric": {"type": "string", "description": "Metric code, name, or alias."},
        },
        "required": ["metric"],
    },
}


def _make_metric_lookup(store: OntologyStore) -> Executor:
    def run(params: dict, cwd: str) -> str:
        metric = (params.get("metric") or "").strip()
        if not metric:
            return "MetricCalculation: empty metric."
        if metric in store.metrics:
            return store.metrics[metric].to_prompt()
        hits = store.find_metric(metric)
        if not hits:
            return f"MetricCalculation: no metric matches {metric!r}."
        if len(hits) == 1:
            return hits[0].to_prompt()
        lines = [f"MetricCalculation: {len(hits)} candidates for {metric!r}:"]
        for m in hits:
            lines.append(m.to_prompt())
        return "\n\n".join(lines)
    return run


# ---------------------------------------------------------------------------
# Ontology-RelationQuery — relations touching a given LE (for join planning)
# ---------------------------------------------------------------------------

RELATION_LOOKUP_SCHEMA = {
    "name": "Ontology-RelationQuery",
    "description": (
        "List all entity relations (ER) that touch a given logical entity. "
        "Use this to plan joins or trace upstream/downstream dependencies."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "entity": {
                "type": "string",
                "description": "LE code, name, or physical table.",
            },
        },
        "required": ["entity"],
    },
}


def _make_relation_lookup(store: OntologyStore) -> Executor:
    def run(params: dict, cwd: str) -> str:
        entity = (params.get("entity") or "").strip()
        if not entity:
            return "Ontology-RelationQuery: empty entity."
        le = store.get_logical_entity(entity)
        if not le:
            return f"Ontology-RelationQuery: no logical entity matches {entity!r}."
        relations = store.relations_of(le.code)
        if not relations:
            return f"Ontology-RelationQuery: {le.name} ({le.code}) has no recorded relations."
        lines = [f"# Relations for {le.name} [{le.code}] — table {le.physical_table}"]
        for r in relations:
            lines.append(r.to_prompt())
        return "\n\n".join(lines)
    return run


# ---------------------------------------------------------------------------
# Ontology-EntityDescribe — full LE context: definition, attributes, relations
# ---------------------------------------------------------------------------

ENTITY_DESCRIBE_SCHEMA = {
    "name": "Ontology-EntityDescribe",
    "description": (
        "Return a full description of a logical entity: definition, physical "
        "table, all attributes with data types, and all relations. Use this "
        "as the primary tool for preparing context before writing SQL."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "entity": {
                "type": "string",
                "description": "LE code, name, or physical table name.",
            },
        },
        "required": ["entity"],
    },
}


def _make_entity_describe(store: OntologyStore) -> Executor:
    def run(params: dict, cwd: str) -> str:
        entity = (params.get("entity") or "").strip()
        if not entity:
            return "Ontology-EntityDescribe: empty entity."
        le = store.get_logical_entity(entity)
        if not le:
            return f"Ontology-EntityDescribe: no logical entity matches {entity!r}."
        lines = [le.to_prompt()]
        attrs = store.attributes_of(le.code)
        if attrs:
            lines.append(f"\n## 属性 ({len(attrs)})")
            for a in attrs:
                lines.append(a.to_prompt())
        rels = store.relations_of(le.code)
        if rels:
            lines.append(f"\n## 关系 ({len(rels)})")
            for r in rels:
                lines.append(r.to_prompt())
        return "\n".join(lines)
    return run


# ---------------------------------------------------------------------------
# ListBusinessObjects — bird's-eye view of the domain
# ---------------------------------------------------------------------------

LIST_BUSINESS_OBJECTS_SCHEMA = {
    "name": "ListBusinessObjects",
    "description": (
        "List all business objects in the ontology (code, name, physical table). "
        "Use this when the user's question is open-ended and you need a map "
        "of what domains exist."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}


def _make_list_business_objects(store: OntologyStore) -> Executor:
    def run(params: dict, cwd: str) -> str:
        bos = list(store.business_objects.values())
        if not bos:
            return "ListBusinessObjects: ontology is empty."
        lines = [f"# 业务对象 ({len(bos)})"]
        for bo in bos:
            les = store.logical_entities_of(bo.code)
            le_summary = ", ".join(f"{le.name}({le.physical_table})" for le in les) or "—"
            lines.append(f"[{bo.code}] {bo.name} / {bo.english or '-'} — LEs: {le_summary}")
        return "\n".join(lines)
    return run


# ---------------------------------------------------------------------------
# Registry — (schema, factory) pairs
# ---------------------------------------------------------------------------

SPECS: list[tuple[dict, ExecutorFactory]] = [
    (ONTOLOGY_QUERY_SCHEMA, _make_ontology_query),
    (TERM_DISAMBIGUATE_SCHEMA, _make_term_disambiguate),
    (METRIC_LOOKUP_SCHEMA, _make_metric_lookup),
    (RELATION_LOOKUP_SCHEMA, _make_relation_lookup),
    (ENTITY_DESCRIBE_SCHEMA, _make_entity_describe),
    (LIST_BUSINESS_OBJECTS_SCHEMA, _make_list_business_objects),
]
