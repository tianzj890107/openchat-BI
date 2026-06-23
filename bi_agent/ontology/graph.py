"""
NetworkX graph builder for the ontology.

Builds a directed multigraph from a loaded OntologyStore and saves it as
GraphML (so it round-trips and shows up in the 图库源 dropdown).

The graph is a **containment hierarchy** matching the ontology's intended
shape (parent --包含--> child):

    业务对象 (business_object)
    ├── 逻辑实体 (logical_entity)
    │   └── 业务属性 (business_attribute)
    ├── 指标 (indicator)               指标绑定在业务对象下
    │   └── 维度 (dimension)            指标下钻的分析轴
    └── 活动 (activity)                活动绑定在业务对象下

    流程 (process, 场景子流程)
    └── 活动 (activity)                流程下层为活动

On top of the tree we keep two cross-cutting relation families:

  - ER edges      : instance 逻辑实体 ↔ 逻辑实体 links from the 实体关系 sheet
                    (concrete entity relations, with their own cardinality/FK).
  - 规则约束 edges : 业务规则 --约束--> 活动 (rules hang off the activities).

Edge labels / cardinalities are taken from the 本体元模型关系 sheet when a
matching element-kind pair exists (so 包含/被下钻/操作… and 1:N/M:N come from
the meta model); otherwise a sensible default is used.
"""

from __future__ import annotations

from typing import Iterator

import networkx as nx

from .store import OntologyStore


def _truncate(s: str, n: int = 200) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "…"


# --- Meta-model label lookup ----------------------------------------------
# The 本体元模型关系 sheet declares, per element-kind pair, the relation
# name (包含 / 被下钻 / 操作 …) and cardinality. We use it to LABEL the
# containment edges; the edge DIRECTION follows the containment tree above
# (which is sometimes the reverse of how the meta row is written, e.g. the
# meta row is indicator->business_object 归属于, but the tree edge is
# business_object->indicator — then we use the reverse_name).

def _flip_card(card: str) -> str:
    return {"1:N": "N:1", "N:1": "1:N"}.get(card or "", card or "")


def _meta_label(store: OntologyStore, src_kind: str, tgt_kind: str,
                default_cn: str = "包含", default_card: str = "1:N") -> dict:
    """Return {rel, rel_en, cardinality, meta_code} for a kind pair, trying
    the reverse direction (with reverse_name) if no forward row exists."""
    for mr in store.meta_relations.values():
        if mr.source_kind == src_kind and mr.target_kind == tgt_kind:
            return {"rel": mr.name or default_cn, "rel_en": mr.english or "",
                    "cardinality": mr.cardinality or default_card, "meta_code": mr.code}
    for mr in store.meta_relations.values():
        if mr.source_kind == tgt_kind and mr.target_kind == src_kind:
            return {"rel": mr.reverse_name or mr.name or default_cn,
                    "rel_en": mr.reverse_english or "",
                    "cardinality": _flip_card(mr.cardinality) or default_card,
                    "meta_code": mr.code}
    return {"rel": default_cn, "rel_en": "", "cardinality": default_card, "meta_code": ""}


# --- Containment-edge resolvers -------------------------------------------
# Each yields (parent_code, child_code) instance pairs for one tree level.

def _pairs_bo_le(store: OntologyStore) -> Iterator[tuple[str, str]]:
    for le in store.logical_entities.values():
        if le.bo_code in store.business_objects:
            yield (le.bo_code, le.code)


def _pairs_le_at(store: OntologyStore) -> Iterator[tuple[str, str]]:
    for at in store.attributes.values():
        if at.le_code in store.logical_entities:
            yield (at.le_code, at.code)


def _resolve_bo(store: OntologyStore, value: str) -> str | None:
    """Resolve a 业务对象 reference (code or name) to a BO code."""
    if not value:
        return None
    if value in store.business_objects:
        return value
    return store._bo_by_name.get(value.lower())


def _pairs_bo_indicator(store: OntologyStore) -> Iterator[tuple[str, str]]:
    for m in store.metrics.values():
        bo = _resolve_bo(store, m.bo_name)
        if bo:
            yield (bo, m.code)


def _pairs_indicator_dimension(store: OntologyStore) -> Iterator[tuple[str, str]]:
    for m in store.metrics.values():
        for dim_short in m.applicable_dimensions:
            dcode = store._dim_by_shortname.get((dim_short or "").lower())
            if dcode:
                yield (m.code, dcode)


def _pairs_bo_activity(store: OntologyStore) -> Iterator[tuple[str, str]]:
    for act in store.activities.values():
        for oc in act.object_codes:
            if oc in store.business_objects:
                yield (oc, act.code)


def _pairs_process_activity(store: OntologyStore) -> Iterator[tuple[str, str]]:
    for proc in store.processes.values():
        for ac in proc.activity_codes:
            if ac in store.activities:
                yield (proc.code, ac)


# (parent_kind, child_kind, resolver) — drives the containment tree.
_CONTAINMENT = [
    ("business_object", "logical_entity", _pairs_bo_le),
    ("logical_entity", "business_attribute", _pairs_le_at),
    ("business_object", "indicator", _pairs_bo_indicator),
    ("indicator", "dimension", _pairs_indicator_dimension),
    ("business_object", "activity", _pairs_bo_activity),
    ("process", "activity", _pairs_process_activity),
]


def _add_nodes(G: nx.MultiDiGraph, store: OntologyStore) -> None:
    def add(code: str, kind: str, name: str, english: str = "", definition: str = "") -> None:
        if not code:
            return
        G.add_node(
            code, kind=kind, name=name or code, english=english or "",
            label=(f"{name} ({english})" if english else (name or code)),
            definition=_truncate(definition),
        )
    for t in store.terms.values():
        add(t.code, "term", t.name, t.english, t.definition)
    for b in store.business_objects.values():
        add(b.code, "business_object", b.name, b.english, b.definition)
    for le in store.logical_entities.values():
        add(le.code, "logical_entity", le.name, le.english, le.definition)
    for at in store.attributes.values():
        add(at.code, "business_attribute", at.name, at.english, at.definition)
    for m in store.metrics.values():
        add(m.code, "indicator", m.name, m.english, m.definition)
    for d in store.dimensions.values():
        add(d.code, "dimension", d.name, d.english, d.definition)
    for a in store.activities.values():
        add(a.code, "activity", a.name, "", a.description)
    for p in store.processes.values():
        add(p.code, "process", p.name, "", "")
    for r in store.rules.values():
        add(r.code, "business_rule", r.rule, "", r.rule)


def build_graph(store: OntologyStore) -> tuple[nx.MultiDiGraph, dict]:
    """Return (graph, stats). See module docstring for the edge model."""
    G = nx.MultiDiGraph()
    _add_nodes(G, store)

    # Containment tree edges (parent --包含/…--> child).
    tree_edges = 0
    by_level: dict[str, int] = {}
    for parent_kind, child_kind, resolver in _CONTAINMENT:
        lbl = _meta_label(store, parent_kind, child_kind)
        level_key = f"{parent_kind}->{child_kind}"
        for parent, child in resolver(store):
            if parent in G and child in G:
                G.add_edge(
                    parent, child, key=f"{level_key}:{parent}->{child}",
                    kind="TREE", rel=lbl["rel"], rel_en=lbl["rel_en"],
                    cardinality=lbl["cardinality"], meta_code=lbl["meta_code"],
                )
                tree_edges += 1
                by_level[level_key] = by_level.get(level_key, 0) + 1

    # ER edges — concrete 逻辑实体 ↔ 逻辑实体 links from 实体关系.
    er_edges = 0
    for er in store.relations.values():
        if er.source_code in G and er.target_code in G:
            G.add_edge(
                er.source_code, er.target_code, key=er.code,
                kind="ER", rel=er.name or "", rel_en=er.english or "",
                cardinality=er.cardinality or "", description=_truncate(er.description),
                code=er.code,
            )
            er_edges += 1

    # 业务规则 --约束--> 活动.
    rule_edges = 0
    rlbl = _meta_label(store, "business_rule", "activity", default_cn="约束", default_card="M:N")
    for r in store.rules.values():
        if r.activity_code in store.activities and r.code in G:
            G.add_edge(
                r.code, r.activity_code, key=f"RULE:{r.code}",
                kind="RULE", rel=rlbl["rel"], rel_en=rlbl["rel_en"],
                cardinality=rlbl["cardinality"], meta_code=rlbl["meta_code"],
            )
            rule_edges += 1

    stats = {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "tree_edges": tree_edges,
        "tree_by_level": by_level,
        "er_edges": er_edges,
        "rule_edges": rule_edges,
        "dimensions": len(store.dimensions),
        "processes": len(store.processes),
    }
    return G, stats


def save_graph(G: nx.MultiDiGraph, path: str) -> str:
    nx.write_graphml(G, str(path))
    return str(path)


def build_from_xlsx(xlsx_path: str, out_path: str) -> dict:
    """Load an ontology xlsx, build the graph, write GraphML; return stats."""
    store = OntologyStore.from_xlsx(str(xlsx_path))
    G, stats = build_graph(store)
    save_graph(G, str(out_path))
    stats["path"] = str(out_path)
    return stats
