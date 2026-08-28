// Shared Sigma + Graphology + ForceAtlas2 renderer adapted from
// ontology-agent/frontend/src/{OntologySigmaPreview,ontologyGraphModel,
// ontologyForceLayout}.js. Keep its interaction and layout settings aligned
// with that source when ontology-agent updates.
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import Sigma from "sigma";

export const FORCE_ATLAS_CONFIG = Object.freeze({
  scalingRatio: 4.5,
  gravity: 0.25,
  strongGravityMode: false,
  barnesHutOptimize: true,
  barnesHutTheta: 0.65,
  slowDown: 4,
  edgeWeightInfluence: 1,
  linLogMode: true,
  outboundAttractionDistribution: false,
  adjustSizes: false,
});

const ATTRIBUTE_LABEL_RATIO = 0.58;
const TAU = Math.PI * 2;
const NODE_STYLE = {
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

function hashUnit(value) {
  let hash = 2166136261;
  for (const char of String(value || "")) {
    hash ^= char.codePointAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return ((hash >>> 0) % 100000) / 100000;
}

function semanticSeed(graph) {
  const businessObjects = graph.filterNodes((node, attrs) => attrs.nodeType === "businessObject");
  const clusterRadius = Math.max(8, Math.sqrt(Math.max(1, businessObjects.length)) * 7);
  const centers = new Map();
  businessObjects.forEach((node, index) => {
    const angle = TAU * index / Math.max(1, businessObjects.length) - Math.PI / 2;
    centers.set(node, { x: Math.cos(angle) * clusterRadius, y: Math.sin(angle) * clusterRadius });
  });
  graph.forEachNode((node, attrs) => {
    const parent = attrs.parentId && graph.hasNode(attrs.parentId) ? attrs.parentId : null;
    const parentCenter = parent ? centers.get(parent) || {
      x: Number(graph.getNodeAttribute(parent, "x")) || 0,
      y: Number(graph.getNodeAttribute(parent, "y")) || 0,
    } : null;
    const ownCenter = centers.get(node);
    const layerDistance = { businessObject: 0, logicalEntity: 3.5, businessAttribute: 5.5, metric: 4.5, businessRule: 8 }[attrs.nodeType] || 6;
    const angle = hashUnit(node) * TAU;
    const center = ownCenter || parentCenter || { x: 0, y: 0 };
    const distance = graph.degree(node) === 0 ? clusterRadius + 8 : layerDistance;
    graph.mergeNodeAttributes(node, {
      x: center.x + Math.cos(angle) * distance,
      y: center.y + Math.sin(angle) * distance,
    });
  });
}

function reduceOverlap(graph, iterations = 18) {
  const nodes = graph.nodes().filter((node) => graph.degree(node) > 0);
  for (let iteration = 0; iteration < iterations; iteration += 1) {
    let moved = false;
    for (let left = 0; left < nodes.length; left += 1) {
      const a = nodes[left];
      const ax = graph.getNodeAttribute(a, "x");
      const ay = graph.getNodeAttribute(a, "y");
      for (let right = left + 1; right < nodes.length; right += 1) {
        const b = nodes[right];
        let dx = graph.getNodeAttribute(b, "x") - ax;
        let dy = graph.getNodeAttribute(b, "y") - ay;
        let distance = Math.hypot(dx, dy);
        const minimum = (graph.getNodeAttribute(a, "size") + graph.getNodeAttribute(b, "size")) * 0.13 + 0.8;
        if (distance >= minimum) continue;
        if (distance < 0.0001) {
          const angle = hashUnit(`${a}:${b}`) * TAU;
          dx = Math.cos(angle); dy = Math.sin(angle); distance = 1;
        }
        const push = (minimum - distance) * 0.34;
        const ux = dx / distance; const uy = dy / distance;
        graph.setNodeAttribute(a, "x", graph.getNodeAttribute(a, "x") - ux * push);
        graph.setNodeAttribute(a, "y", graph.getNodeAttribute(a, "y") - uy * push);
        graph.setNodeAttribute(b, "x", graph.getNodeAttribute(b, "x") + ux * push);
        graph.setNodeAttribute(b, "y", graph.getNodeAttribute(b, "y") + uy * push);
        moved = true;
      }
    }
    if (!moved) break;
  }
}

function packIsolatedNodes(graph) {
  const connected = graph.filterNodes((node) => graph.degree(node) > 0);
  const isolated = graph.filterNodes((node) => graph.degree(node) === 0);
  if (!isolated.length) return;
  const xs = connected.map((node) => graph.getNodeAttribute(node, "x"));
  const ys = connected.map((node) => graph.getNodeAttribute(node, "y"));
  const minX = xs.length ? Math.min(...xs) : -5;
  const maxX = xs.length ? Math.max(...xs) : 5;
  const maxY = ys.length ? Math.max(...ys) : 5;
  const columns = Math.max(1, Math.ceil(Math.sqrt(isolated.length)));
  const spacing = 4.5;
  const startX = (minX + maxX) / 2 - (Math.min(columns, isolated.length) - 1) * spacing / 2;
  isolated.forEach((node, index) => {
    graph.setNodeAttribute(node, "x", startX + (index % columns) * spacing);
    graph.setNodeAttribute(node, "y", maxY + 7 + Math.floor(index / columns) * spacing);
  });
}

function normalizeCoordinates(graph, stretchAxes = false, targetAspect = 1) {
  if (!graph.order) return;
  const xs = graph.mapNodes((node, attrs) => Number(attrs.x) || 0);
  const ys = graph.mapNodes((node, attrs) => Number(attrs.y) || 0);
  const minX = Math.min(...xs); const maxX = Math.max(...xs);
  const minY = Math.min(...ys); const maxY = Math.max(...ys);
  const spanX = Math.max(1, maxX - minX); const spanY = Math.max(1, maxY - minY);
  const span = Math.max(spanX, spanY);
  graph.updateEachNodeAttributes((node, attrs) => ({
    ...attrs,
    x: ((Number(attrs.x) || 0) - (minX + maxX) / 2) / (stretchAxes ? spanX : span) * 100 * (stretchAxes ? targetAspect : 1),
    y: ((Number(attrs.y) || 0) - (minY + maxY) / 2) / (stretchAxes ? spanY : span) * 100,
  }));
}

function layoutOntologyForceAtlas(graph, container) {
  semanticSeed(graph);
  if (graph.size) {
    forceAtlas2.assign(graph, {
      iterations: graph.order <= 80 ? 180 : (graph.order <= 1200 ? 160 : 100),
      settings: FORCE_ATLAS_CONFIG,
      getEdgeWeight: "weight",
    });
  }
  reduceOverlap(graph, graph.order > 500 ? 8 : 18);
  // Match ontology-agent's relationship-cluster layout: disconnected nodes
  // are packed below the connected graph instead of remaining scattered.
  packIsolatedNodes(graph);
  normalizeCoordinates(
    graph,
    graph.order <= 40,
    Math.max(1, Math.min(3.2, container.clientWidth / Math.max(1, container.clientHeight))),
  );
}

function buildGraph(data) {
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

export function createOntologySigmaRenderer(container, data) {
  const graph = buildGraph(data);
  layoutOntologyForceAtlas(graph, container);
  let hoveredNode = null;
  let selectedNode = null;
  let selectedNeighbors = new Set();
  let cameraRatio = 1;
  const renderer = new Sigma(graph, container, {
    allowInvalidContainer: false,
    defaultNodeColor: "#64748b", defaultEdgeColor: "#cbd5e1",
    labelColor: { color: "#334155" }, labelFont: '"PingFang SC", -apple-system, sans-serif',
    labelSize: 12, labelWeight: "500", labelRenderedSizeThreshold: 5,
    renderEdgeLabels: false, hideEdgesOnMove: graph.order > 700,
    stagePadding: 24, zIndex: true, minCameraRatio: 0.08, maxCameraRatio: 8,
    nodeReducer: (node, attrs) => {
      const highlighted = node === hoveredNode || node === selectedNode || selectedNeighbors.has(node) || attrs.highlighted;
      const dimmed = selectedNode && !highlighted;
      const alwaysLabel = ["businessObject", "logicalEntity", "metric", "businessRule"].includes(attrs.nodeType);
      const attributeLabel = attrs.nodeType === "businessAttribute" && (highlighted || cameraRatio < ATTRIBUTE_LABEL_RATIO);
      return { ...attrs, label: alwaysLabel || attributeLabel || highlighted ? attrs.label : "",
        color: dimmed ? "#cbd5e1" : attrs.color,
        size: attrs.size * (node === hoveredNode || node === selectedNode ? 1.28 : 1),
        zIndex: highlighted ? 2 : 1, forceLabel: Boolean(highlighted || attrs.nodeType === "businessObject") };
    },
    edgeReducer: (edge, attrs) => {
      const [source, target] = graph.extremities(edge);
      const highlighted = selectedNode && (source === selectedNode || target === selectedNode);
      return { ...attrs, color: selectedNode ? (highlighted ? "#475569" : "#e2e8f0") : attrs.color,
        size: attrs.size * (highlighted ? 1.7 : 1), zIndex: highlighted ? 2 : 0 };
    },
  });
  const refresh = () => renderer.refresh();
  renderer.on("enterNode", ({ node }) => { hoveredNode = node; refresh(); });
  renderer.on("leaveNode", () => { hoveredNode = null; refresh(); });
  renderer.on("clickNode", ({ node, event }) => {
    event.preventSigmaDefault?.(); selectedNode = node;
    selectedNeighbors = new Set(graph.neighbors(node)); refresh();
  });
  renderer.on("clickStage", () => { selectedNode = null; selectedNeighbors = new Set(); refresh(); });
  renderer.getCamera().on("updated", (state) => {
    const nextRatio = Number(state.ratio) || 1;
    const thresholdChanged = (cameraRatio < ATTRIBUTE_LABEL_RATIO) !== (nextRatio < ATTRIBUTE_LABEL_RATIO);
    cameraRatio = nextRatio; if (thresholdChanged) refresh();
  });
  renderer.getCamera().animatedReset({ duration: 300 });
  const preventDoubleClick = (event) => { event.preventDefault(); event.stopPropagation(); };
  container.addEventListener("dblclick", preventDoubleClick, { capture: true });
  const observer = new ResizeObserver(() => renderer.resize());
  observer.observe(container);
  return {
    kill() { observer.disconnect(); container.removeEventListener("dblclick", preventDoubleClick, { capture: true }); renderer.kill(); },
    relayout() { layoutOntologyForceAtlas(graph, container); renderer.refresh(); renderer.getCamera().animatedReset({ duration: 300 }); },
  };
}
