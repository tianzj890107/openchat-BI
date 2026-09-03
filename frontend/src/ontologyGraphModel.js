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

// ---------------------------------------------------------------------------
// Semantic radial contract adapter (pure, shared-algorithm input).
// Converts /api/ontology/subgraph JSON into the plain { nodes, links } shape
// consumed by @boulderaitech/ontology-graph/radial.  No layout geometry is
// implemented here; ring placement lives only in the shared package.
// ---------------------------------------------------------------------------

const clampValue = (value, min, max) => Math.min(max, Math.max(min, value));
const RADIAL_SYMBOL_WIDTH_MIN = 44;
const RADIAL_SYMBOL_WIDTH_MAX = 200;
const RADIAL_SYMBOL_HEIGHT_MIN = 26;
const RADIAL_SYMBOL_HEIGHT_MAX = 96;

function radialSymbolSize(label) {
  const length = Array.from(label || "").length;
  const width = clampValue(40 + length * 7, RADIAL_SYMBOL_WIDTH_MIN, RADIAL_SYMBOL_WIDTH_MAX);
  const height = clampValue(22 + length * 3.4, RADIAL_SYMBOL_HEIGHT_MIN, RADIAL_SYMBOL_HEIGHT_MAX);
  return [Math.round(width), Math.round(height)];
}

function radialLayerLabel(key) {
  if (key === "unrelated") return "未关联";
  const match = /^distance:(\d+)$/.exec(key);
  if (!match) return key;
  const distance = Number(match[1]);
  return distance === 0 ? "中心" : `${distance} 跳`;
}

// BFS distances from the chosen anchor over undirected adjacency.
function radialDistances(anchor, adjacency) {
  const distances = new Map([[anchor.id, 0]]);
  const queue = [anchor.id];
  while (queue.length) {
    const current = queue.shift();
    const nextDistance = distances.get(current) + 1;
    for (const neighborId of adjacency.get(current) || []) {
      if (distances.has(neighborId)) continue;
      distances.set(neighborId, nextDistance);
      queue.push(neighborId);
    }
  }
  return distances;
}

export function buildRadialGraph(data) {
  const sourceNodes = Array.isArray(data?.nodes) ? data.nodes : [];
  const sourceLinks = Array.isArray(data?.links) ? data.links : [];
  const nodes = [];
  const byId = new Map();
  const byCode = new Map();

  sourceNodes.forEach((raw) => {
    if (!raw || typeof raw !== "object") return;
    const id = raw.id || raw.code;
    if (!id) return;
    if (byId.has(id) || (raw.code && byCode.has(raw.code))) return;
    const name = raw.name || raw.code || id;
    const type = raw.type || "";
    const color = (NODE_STYLE[type] && NODE_STYLE[type][1]) || "#64748b";
    const node = {
      id,
      name,
      label: name,
      ontologyType: type,
      layer: "unrelated",
      parentId: "",
      symbol: "roundRect",
      symbolSize: radialSymbolSize(name),
      itemStyle: { color },
      focus: Boolean(raw.focus),
      anchor: Boolean(raw.anchor),
    };
    nodes.push(node);
    byId.set(id, node);
    if (raw.code) byCode.set(raw.code, node);
  });

  const resolve = (reference) => (reference && byId.get(reference)) || (reference && byCode.get(reference)) || null;

  // Edges whose endpoints exist in the payload; invalid/self edges are skipped
  // without breaking the whole conversion (existing subgraph tolerance).
  const edges = [];
  sourceLinks.forEach((edge, index) => {
    if (!edge || typeof edge !== "object") return;
    const source = resolve(edge.source);
    const target = resolve(edge.target);
    if (!source || !target || source === target) return;
    edges.push({ id: edge.id || `ontology-edge:${index}`, source, target, edge });
  });

  // Anchor priority: explicit anchor/focus flag -> data.anchor match -> first
  // legal node.  Exactly one center node may occupy distance:0.
  let center = nodes.find((node) => node.anchor || node.focus) || null;
  if (!center && data?.anchor) center = resolve(data.anchor.id) || resolve(data.anchor.code) || null;
  if (!center) center = nodes[0] || null;
  if (!center) return { nodes: [], links: [], layerDefinitions: [], centerLayer: "distance:0" };

  const adjacency = new Map(nodes.map((node) => [node.id, new Set()]));
  for (const { source, target } of edges) {
    adjacency.get(source.id).add(target.id);
    adjacency.get(target.id).add(source.id);
  }
  const distances = radialDistances(center, adjacency);
  let maxDistance = 0;
  nodes.forEach((node) => {
    node.anchor = node === center;
    node.focus = Boolean(node.focus) && node !== center;
    const distance = distances.get(node.id);
    if (distance === undefined) {
      node.layer = "unrelated";
      return;
    }
    node.layer = distance === 0 ? "distance:0" : `distance:${distance}`;
    if (distance > maxDistance) maxDistance = distance;
    if (distance > 0) {
      const parents = [...(adjacency.get(node.id) || [])]
        .filter((neighborId) => distances.get(neighborId) === distance - 1)
        .sort();
      node.parentId = parents[0] || "";
    }
  });

  const layerKeys = [];
  for (let distance = 0; distance <= maxDistance; distance += 1) layerKeys.push(`distance:${distance}`);
  if (nodes.some((node) => node.layer === "unrelated")) layerKeys.push("unrelated");
  const layerDefinitions = layerKeys.map((key) => ({ key, label: radialLayerLabel(key) }));

  const links = edges.map(({ id, source, target, edge }) => ({
    id,
    source: source.id,
    target: target.id,
    relation: edge.relation ?? edge.relationType ?? edge.label ?? "",
    lineStyle: { color: "#94a3b8", width: 1.2 },
  }));

  return { nodes, links, layerDefinitions, centerLayer: "distance:0" };
}
