// ChatBI-specific ontology graph model: /api/ontology/subgraph JSON -> graphology graph.
// Node/edge attributes follow the shared contract in @boulderaitech/ontology-graph
// (nodeType/label/color/size/parentId/highlighted, edge weight/size/color).
import Graph from "graphology";

export const NODE_STYLE = {
  BusinessObject: ["businessObject", "#2563eb", 15],
  LogicalEntity: ["logicalEntity", "#0f766e", 10],
  BusinessAttribute: ["businessAttribute", "#64748b", 4],
  Indicator: ["metric", "#7c3aed", 7],
  Rule: ["businessRule", "#c2410c", 7],
  Term: ["term", "#0891b2", 7],
  Dimension: ["dimension", "#db2777", 7],
  Activity: ["activity", "#16a34a", 7],
  Process: ["process", "#ca8a04", 7],
  TableNode: ["tableNode", "#475569", 5],
  Column: ["column", "#94a3b8", 4],
};

export function buildGraph(data) {
  const graph = new Graph({ type: "undirected", multi: true, allowSelfLoops: false });
  (data.nodes || []).forEach((node) => {
    const [nodeType, color, size] = NODE_STYLE[node.type] || [String(node.type || "ontology"), "#64748b", 5];
    graph.addNode(node.id || node.code, {
      ...node, ontologyType: node.type, type: "circle", nodeType, color, size: node.focus ? size * 1.35 : size,
      label: node.name || node.code, x: 0, y: 0,
      highlighted: Boolean(node.focus || node.anchor),
    });
  });
  (data.links || []).forEach((edge, index) => {
    if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target) || edge.source === edge.target) return;
    graph.addUndirectedEdgeWithKey(edge.id || `ontology-edge:${index}`, edge.source, edge.target, {
      ...edge,
      size: Math.max(0.7, Math.min(2.4, Number(edge.weight) || 1)),
      weight: Math.max(0.7, Number(edge.weight) || 1),
      color: "#cbd5e1",
    });
    const sourceType = graph.getNodeAttribute(edge.source, "nodeType");
    const targetType = graph.getNodeAttribute(edge.target, "nodeType");
    if (sourceType === "businessObject" && targetType !== "businessObject") graph.setNodeAttribute(edge.target, "parentId", edge.source);
    else if (targetType === "businessObject" && sourceType !== "businessObject") graph.setNodeAttribute(edge.source, "parentId", edge.target);
  });
  return graph;
}
