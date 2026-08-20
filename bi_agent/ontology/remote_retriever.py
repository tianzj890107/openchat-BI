"""Structured graph retrieval over the managed remote ontology service.

The local :class:`GraphRetriever` traverses workbook-derived indexes.  This
module provides the remote equivalent using the server's bounded neighborhood
API plus its read-only OpenCypher endpoint.  It keeps edge direction and
relation properties, produces evidence paths, and degrades to the vertex-only
neighborhood when a repository cannot execute the generic edge query.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
import json
from typing import Any, Iterable, Optional

from .remote import RemoteOntologyClient


def _scalar(value: Any) -> Any:
    if isinstance(value, list) and len(value) == 1:
        return _scalar(value[0])
    if isinstance(value, dict) and set(value) == {"value"}:
        return _scalar(value["value"])
    return value


def _text(value: Any) -> str:
    value = _scalar(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value or "").strip()


def _value(props: dict[str, Any], *names: str, default: Any = "") -> Any:
    lowered = {str(key).casefold(): _scalar(value) for key, value in props.items()}
    for name in names:
        value = lowered.get(name.casefold())
        if value not in (None, "", []):
            return value
    return default


def _type_from_code(code: str) -> str:
    upper = str(code or "").upper()
    mappings = (
        ("MREL", "MetaRelation"), ("TERM", "Term"), ("RULE", "Rule"),
        ("PROC", "Process"), ("ACT", "Activity"), ("DIM", "Dimension"),
        ("MET", "Indicator"), ("COL", "Column"), ("PT", "TableNode"),
        ("BO", "BusinessObject"), ("LE", "LogicalEntity"),
        ("ATT", "BusinessAttribute"), ("AT", "BusinessAttribute"),
        ("ER", "EntityRelation"), ("SSP", "Process"), ("A", "Activity"),
        ("D", "Dimension"), ("M", "Indicator"), ("R", "Rule"),
        ("T", "Term"),
    )
    for prefix, type_name in mappings:
        if upper.startswith(prefix):
            return type_name
    return "Unknown"


@dataclass
class RemoteNode:
    code: str
    type_name: str
    properties: dict[str, Any] = field(default_factory=dict)
    anchor: bool = False

    @property
    def label(self) -> str:
        return _text(_value(self.properties, "label", "name", default=self.code)) or self.code

    def one_line(self) -> str:
        return f"[{self.code}] {self.label} ({self.type_name})"


@dataclass
class RemoteEdge:
    source: str
    relation: str
    target: str
    properties: dict[str, Any] = field(default_factory=dict)
    synthetic: bool = False


@dataclass
class RemoteGraph:
    anchor_code: str
    anchor_type: str
    depth: int
    nodes: dict[str, RemoteNode]
    edges: list[RemoteEdge]
    relations_available: bool
    relation_error: str = ""


class RemoteGraphRetriever:
    """Remote graph context and cross-domain diffusion with bounded output."""

    _TYPE_ORDER = (
        "BusinessObject", "LogicalEntity", "BusinessAttribute", "Indicator",
        "Dimension", "Activity", "Process", "Rule", "Term", "TableNode",
        "Column", "EntityRelation", "MetaRelation", "Unknown",
    )
    _DETAIL_FIELDS = (
        ("英文名", ("name",)),
        ("定义", ("description", "definition")),
        ("别名", ("alias", "aliases")),
        ("缩写", ("abbreviation",)),
        ("物理表", ("physicalTable", "tableName", "sourceTable")),
        ("物理列", ("columnName", "aggregateColumn", "aggregateColumns")),
        ("数据类型", ("dataType", "valueType")),
        ("指标类型", ("indicatorType", "metricType")),
        ("业务公式", ("businessFormula", "bizFormula", "formulaBusiness", "formula")),
        ("统计口径", ("statisticalCaliber", "statCaliber", "scope", "statisticalScope")),
        ("计算规则", ("attributeCalculationRule", "calculationRule", "formulaTechnical")),
        ("角色", ("role",)),
    )
    # Context preparation follows ownership/calculation/mapping edges only.
    # Cross-domain LE/activity/process edges are intentionally reserved for
    # GraphExpand so an ordinary lookup does not flood the model context.
    _CONTEXT_RELATIONS = {
        "BOContainLE", "LEContainATT", "IndicatorBelongToBO",
        "IndicatorIsCalculatedFromATT", "IndicatorIsCalculatedFromLE",
        "IndicatorIsDrilledByDimension", "IndicatorCalculateToIndicator",
        "DimensionBoundToATT", "DimensionReferencesATT", "ATTHasHierarchyParent",
        "LEMappingPT", "ATTMappingField", "PTContainField",
        "TermDefiniteBO", "TermDefiniteIndicator", "TermDefiniteDimension",
        "TermDefiniteLE", "TermDefiniteATT",
    }

    def __init__(self, client: RemoteOntologyClient) -> None:
        self.client = client

    def _graph(self, type_name: str, code: str, depth: int) -> RemoteGraph:
        payload = self.client.graph_neighborhood(type_name, code, depth=depth)
        nodes: dict[str, RemoteNode] = {}
        for item in payload.get("objects") or []:
            if not isinstance(item, dict):
                continue
            props = item.get("properties") if isinstance(item.get("properties"), dict) else item
            props = dict(props or {})
            node_code = _text(_value(props, "code", "identifierCode"))
            if not node_code:
                continue
            node_type = str(item.get("typeName") or item.get("type") or _type_from_code(node_code))
            current = nodes.get(node_code)
            # Prefer a concrete server type/property map over a synthesized root.
            if current is None or len(props) > len(current.properties):
                nodes[node_code] = RemoteNode(
                    node_code, node_type, props,
                    bool(item.get("anchor")) or node_code == code,
                )
        if code not in nodes:
            nodes[code] = RemoteNode(code, type_name, {"code": code}, True)

        edges: list[RemoteEdge] = []
        seen_edges: set[tuple[str, str, str, str]] = set()
        for row in payload.get("relations") or []:
            if not isinstance(row, dict):
                continue
            source = _text(_value(row, "sourceCode", "source_code", "source"))
            target = _text(_value(row, "targetCode", "target_code", "target"))
            relation = _text(_value(row, "relationType", "relation", "type", default="RELATED")) or "RELATED"
            props = _scalar(_value(row, "relationProperties", "properties", default={}))
            if not isinstance(props, dict):
                props = {"value": props} if props not in (None, "") else {}
            if not source or not target or source not in nodes or target not in nodes:
                continue
            signature = (source, relation, target, json.dumps(props, ensure_ascii=False, sort_keys=True, default=str))
            if signature in seen_edges:
                continue
            seen_edges.add(signature)
            edges.append(RemoteEdge(source, relation, target, props))

        relations_available = bool(payload.get("relations_available", True))
        if not edges:
            # Keep traversal useful on older repositories. The synthetic edge
            # is explicitly labelled so it can never be mistaken for a modeled
            # direction or join relationship.
            for node_code in sorted(nodes):
                if node_code != code:
                    edges.append(RemoteEdge(code, "RELATED_NEIGHBOR", node_code, synthetic=True))
        return RemoteGraph(
            code, type_name, int(payload.get("depth") or depth), nodes, edges,
            relations_available, str(payload.get("relation_error") or ""),
        )

    @staticmethod
    def _adjacency(graph: RemoteGraph) -> dict[str, list[tuple[str, RemoteEdge, bool]]]:
        adjacency: dict[str, list[tuple[str, RemoteEdge, bool]]] = defaultdict(list)
        for edge in graph.edges:
            adjacency[edge.source].append((edge.target, edge, True))
            adjacency[edge.target].append((edge.source, edge, False))
        return adjacency

    def _path(self, graph: RemoteGraph, start: str, target: str) -> list[tuple[str, Optional[RemoteEdge], bool]]:
        if start == target:
            return [(start, None, True)]
        adjacency = self._adjacency(graph)
        queue: deque[str] = deque([start])
        previous: dict[str, tuple[str, RemoteEdge, bool]] = {}
        visited = {start}
        while queue:
            current = queue.popleft()
            for neighbor, edge, forward in adjacency.get(current, []):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                previous[neighbor] = (current, edge, forward)
                if neighbor == target:
                    queue.clear()
                    break
                queue.append(neighbor)
        if target not in previous:
            return []
        reversed_steps: list[tuple[str, Optional[RemoteEdge], bool]] = []
        cursor = target
        while cursor != start:
            parent, edge, forward = previous[cursor]
            reversed_steps.append((cursor, edge, forward))
            cursor = parent
        reversed_steps.append((start, None, True))
        return list(reversed(reversed_steps))

    def _render_node(self, node: RemoteNode, *, details: bool = True) -> list[str]:
        lines = [node.one_line()]
        if not details:
            return lines
        emitted = {node.code, node.label}
        for label, names in self._DETAIL_FIELDS:
            value = _text(_value(node.properties, *names))
            if value and value not in emitted:
                if len(value) > 600:
                    value = value[:600] + "…"
                lines.append(f"  {label}: {value}")
                emitted.add(value)
        return lines

    @staticmethod
    def _edge_properties(edge: RemoteEdge, *, include_display: bool = True) -> str:
        values = []
        keys = [
            "relationAttributeMapping", "attrMappings", "mapping", "foreignKey",
            "joinCondition", "condition", "cardinality", "expression", "sequence",
            "direction", "weight",
        ]
        if include_display:
            keys.extend(("description", "name", "label"))
        for key in keys:
            value = _text(_value(edge.properties, key))
            if value:
                if len(value) > 180:
                    value = value[:180] + "…"
                values.append(f"{key}={value}")
        return "; ".join(values)

    def _render_edge(
        self, graph: RemoteGraph, edge: RemoteEdge, *, compact: bool = False,
    ) -> str:
        source = graph.nodes[edge.source]
        target = graph.nodes[edge.target]
        suffix = self._edge_properties(edge, include_display=not compact)
        if compact:
            text = f"- [{source.code}] --{edge.relation}--> [{target.code}]"
        else:
            text = f"- {source.one_line()} --{edge.relation}--> {target.one_line()}"
        if suffix:
            text += f"；{suffix}"
        if edge.synthetic:
            text += "；方向/关系类型未由当前仓库返回"
        return text

    def _render_path(self, graph: RemoteGraph, path: list[tuple[str, Optional[RemoteEdge], bool]]) -> str:
        if not path:
            return ""
        parts = [graph.nodes[path[0][0]].one_line()]
        for code, edge, forward in path[1:]:
            assert edge is not None
            arrow = f"--{edge.relation}-->" if forward else f"<--{edge.relation}--"
            parts.extend((arrow, graph.nodes[code].one_line()))
        return " ".join(parts)

    def _context_codes(
        self, graph: RemoteGraph, start: str, *, max_depth: int, max_nodes: int,
    ) -> set[str]:
        """Select the local-parity subtree while excluding cross-domain edges."""

        if not graph.relations_available or all(edge.synthetic for edge in graph.edges):
            fallback = [start]
            fallback.extend(code for code in sorted(graph.nodes) if code != start)
            return set(fallback[:max_nodes])
        adjacency = self._adjacency(graph)
        queue: deque[tuple[str, int]] = deque([(start, 0)])
        selected = {start}
        while queue and len(selected) < max_nodes:
            current, level = queue.popleft()
            if level >= max_depth:
                continue
            for neighbor, edge, _ in adjacency.get(current, []):
                if edge.relation not in self._CONTEXT_RELATIONS or neighbor in selected:
                    continue
                selected.add(neighbor)
                queue.append((neighbor, level + 1))
                if len(selected) >= max_nodes:
                    break
        return selected

    def _merge(self, base: RemoteGraph, extra: RemoteGraph) -> None:
        for code, node in extra.nodes.items():
            current = base.nodes.get(code)
            if current is None or len(node.properties) > len(current.properties):
                base.nodes[code] = node
        signatures = {(edge.source, edge.relation, edge.target) for edge in base.edges}
        for edge in extra.edges:
            signature = (edge.source, edge.relation, edge.target)
            if signature not in signatures:
                base.edges.append(edge)
                signatures.add(signature)
        base.relations_available = base.relations_available and extra.relations_available

    def context_bundle(
        self,
        type_name: str,
        code: str,
        *,
        root_properties: Optional[dict[str, Any]] = None,
        depth: int = 4,
        max_nodes: int = 180,
    ) -> str:
        """Return a grouped, edge-aware subtree for a BO or indicator anchor."""

        graph = self._graph(type_name, code, max(2, min(depth, 5)))
        if root_properties:
            root = graph.nodes.get(code)
            if root is not None and len(root_properties) > len(root.properties):
                root.properties = dict(root_properties)
                root.type_name = type_name
        root = graph.nodes[code]
        selected_codes = self._context_codes(
            graph, code, max_depth=max(2, min(depth, 5)), max_nodes=max_nodes,
        )
        lines = [
            f"# Remote GraphContext · {root.one_line()}",
            f"- 本体库: {self.client.repository_id}",
            f"- 遍历深度: {graph.depth}；邻域顶点: {len(graph.nodes)}；上下文保留: {len(selected_codes)}；关系: {len(graph.edges)}",
        ]
        if not graph.relations_available:
            lines.append("- 降级说明: 当前仓库未返回边明细，已保留完整邻域顶点；方向和关系类型不作为证据。")
        lines.extend(("", "## 锚点", *self._render_node(root)))

        grouped: dict[str, list[RemoteNode]] = defaultdict(list)
        for node in graph.nodes.values():
            if node.code != code and node.code in selected_codes:
                grouped[node.type_name].append(node)
        emitted = 1
        lines.append("\n## 关联子树")
        for type_key in (*self._TYPE_ORDER, *sorted(set(grouped) - set(self._TYPE_ORDER))):
            nodes = sorted(grouped.get(type_key, []), key=lambda item: (item.code, item.label))
            if not nodes or emitted >= max_nodes:
                continue
            remaining = max_nodes - emitted
            selected = nodes[:remaining]
            lines.append(f"\n### {type_key} ({len(nodes)})")
            for node in selected:
                lines.extend(self._render_node(node))
            emitted += len(selected)
            if len(selected) < len(nodes):
                lines.append(f"- 其余 {len(nodes) - len(selected)} 个节点因上下文上限省略")

        evidence_edges = [
            edge for edge in graph.edges
            if not edge.synthetic and edge.source in selected_codes and edge.target in selected_codes
        ]
        fallback_edges = [
            edge for edge in graph.edges
            if edge.source in selected_codes and edge.target in selected_codes
        ]
        lines.append(f"\n## 关系证据 ({len(evidence_edges or fallback_edges)})")
        for edge in (evidence_edges or fallback_edges)[:160]:
            lines.append(self._render_edge(graph, edge, compact=True))
        if len(evidence_edges or fallback_edges) > 160:
            lines.append(f"- 其余 {len(evidence_edges or fallback_edges) - 160} 条关系因上下文上限省略")

        # Remote enhancement: expose shortest evidence paths from the anchor
        # to every directly useful business object/metric/dimension.
        targets = [
            node for node in graph.nodes.values()
            if node.code != code and node.code in selected_codes
            and node.type_name in {"BusinessObject", "Indicator", "Dimension"}
        ]
        if targets:
            lines.append("\n## 关键路径")
            for node in sorted(targets, key=lambda item: item.code)[:24]:
                path = self._path(graph, code, node.code)
                if path:
                    lines.append("- " + self._render_path(graph, path))
        return "\n".join(lines)

    def relation_bundle(self, type_name: str, code: str, *, depth: int = 2) -> str:
        """Return edge-aware relations for semantic ``RelationLookup`` use."""

        graph = self._graph(type_name, code, max(1, min(depth, 5)))
        root = graph.nodes[code]
        lines = [
            f"# Remote relations · {root.one_line()}",
            f"- 本体库: {self.client.repository_id}；遍历深度: {graph.depth}",
        ]
        if not graph.relations_available:
            lines.append("- 降级说明: 当前仓库只返回关联顶点，方向和关系类型不可用。")
        lines.append(f"\n## 关联对象 ({max(0, len(graph.nodes) - 1)})")
        for node in sorted(graph.nodes.values(), key=lambda item: (item.type_name, item.code)):
            if node.code != code:
                lines.append(node.one_line())
        lines.append(f"\n## 关系证据 ({len(graph.edges)})")
        for edge in graph.edges[:300]:
            lines.append(self._render_edge(graph, edge))
        return "\n".join(lines)

    @staticmethod
    def _path_kind(graph: RemoteGraph, path: list[tuple[str, Optional[RemoteEdge], bool]]) -> str:
        node_types = {graph.nodes[code].type_name for code, _, _ in path}
        relations = {step[1].relation for step in path[1:] if step[1] is not None}
        if node_types & {"Activity", "Process"}:
            return "活动/流程链"
        if "LEAssociateLE" in relations or "LogicalEntity" in node_types:
            return "实体关系链"
        if node_types & {"Indicator", "Dimension", "BusinessAttribute"}:
            return "指标/属性链"
        return "本体关系链"

    def expand(
        self,
        type_name: str,
        code: str,
        *,
        root_properties: Optional[dict[str, Any]] = None,
        depth: int = 5,
        max_related: int = 12,
    ) -> str:
        """Diffuse through every modeled path and drill related BO subtrees."""

        graph = self._graph(type_name, code, max(3, min(depth, 5)))
        if root_properties and code in graph.nodes:
            graph.nodes[code].properties.update(root_properties)
        start_code = code
        if type_name == "Indicator":
            business_objects = [node for node in graph.nodes.values() if node.type_name == "BusinessObject"]
            ranked = []
            for node in business_objects:
                path = self._path(graph, code, node.code)
                if path:
                    ranked.append((len(path), node.code))
            if ranked:
                start_code = min(ranked)[1]

        start = graph.nodes.get(start_code)
        if start is None or start.type_name != "BusinessObject":
            return (
                f"GraphExpand: [{code}] 无法通过远程关系图定位所属业务对象。"
                "请先用 GraphContext 或 OntologyQuery 确认业务对象锚点。"
            )

        related: list[tuple[int, RemoteNode, list[tuple[str, Optional[RemoteEdge], bool]]]] = []
        for node in graph.nodes.values():
            if node.type_name != "BusinessObject" or node.code == start.code:
                continue
            path = self._path(graph, start.code, node.code)
            if path:
                related.append((len(path), node, path))
        related.sort(key=lambda item: (item[0], item[1].code))
        selected = related[:max(1, min(max_related, 30))]

        lines = [
            f"# Remote GraphExpand · 锚点 {start.one_line()}",
            f"- 本体库: {self.client.repository_id}；遍历深度: {graph.depth}",
        ]
        if code != start.code:
            anchor_path = self._path(graph, code, start.code)
            lines.append("- 指标回挂业务对象: " + self._render_path(graph, anchor_path))
        if not graph.relations_available:
            lines.append("- 降级说明: 当前仓库未返回边明细，以下对象来自邻域遍历，不能用于证明方向或关联类型。")
        if not selected:
            lines.append("\n未发现可关联的上下游业务对象。")
            return "\n".join(lines)

        lines.append(f"\n## 关联业务对象与路径证据 ({len(related)})")
        for _, node, path in selected:
            lines.append(f"- {self._path_kind(graph, path)}: {self._render_path(graph, path)}")
        if len(selected) < len(related):
            lines.append(f"- 其余 {len(related) - len(selected)} 个业务对象因扩散上限省略")

        # Match and exceed the local implementation: every selected BO becomes
        # a new anchor and contributes its own full remote subtree. Merge the
        # graphs first so shared vertices/edges appear only once.
        subtree_codes = {node.code for _, node, _ in selected}
        for _, node, _ in selected:
            subtree = self._graph("BusinessObject", node.code, 3)
            subtree_codes.update(self._context_codes(subtree, node.code, max_depth=3, max_nodes=120))
            self._merge(graph, subtree)

        subtree_nodes: list[RemoteNode] = []
        for node in graph.nodes.values():
            if node.code != start.code and node.code in subtree_codes:
                subtree_nodes.append(node)
        grouped: dict[str, list[RemoteNode]] = defaultdict(list)
        for node in subtree_nodes:
            grouped[node.type_name].append(node)
        lines.append("\n## 新锚点关联子树（合并去重）")
        emitted = 0
        for type_key in (*self._TYPE_ORDER, *sorted(set(grouped) - set(self._TYPE_ORDER))):
            nodes = sorted(grouped.get(type_key, []), key=lambda item: item.code)
            if not nodes or emitted >= 260:
                continue
            chosen = nodes[:260 - emitted]
            lines.append(f"\n### {type_key} ({len(nodes)})")
            for node in chosen:
                lines.extend(self._render_node(node, details=node.type_name != "BusinessAttribute"))
            emitted += len(chosen)
        relevant_edges = [
            edge for edge in graph.edges
            if edge.source in subtree_codes and edge.target in subtree_codes
        ]
        lines.append(f"\n## 扩散关系证据 ({len(relevant_edges)})")
        for edge in relevant_edges[:300]:
            lines.append(self._render_edge(graph, edge, compact=True))
        return "\n".join(lines)
