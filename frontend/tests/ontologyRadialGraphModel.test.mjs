import test from "node:test";
import assert from "node:assert/strict";
import { buildRadialGraph, NODE_STYLE } from "../src/ontologyGraphModel.js";

const node = (id, extra = {}) => ({ id, ...extra });
const link = (source, target, extra = {}) => ({ source, target, ...extra });

test("explicit anchor node enters distance:0 as the only center node", () => {
  const data = {
    nodes: [node("a", { name: "锚点", type: "BusinessObject", anchor: true }), node("b", { name: "B", type: "Indicator" }), node("c", { name: "C", type: "Term" })],
    links: [link("a", "b"), link("b", "c")],
  };
  const radial = buildRadialGraph(data);
  const center = radial.nodes.filter((n) => n.layer === "distance:0");
  assert.equal(center.length, 1);
  assert.equal(center[0].id, "a");
  assert.equal(center[0].anchor, true);
  assert.equal(radial.centerLayer, "distance:0");
  assert.equal(radial.layerDefinitions[0].key, "distance:0");
  assert.equal(radial.layerDefinitions[0].label, "中心");
});

test("one-hop and two-hop nodes enter correct layers via undirected BFS", () => {
  const data = {
    nodes: [
      node("a", { name: "锚点", type: "BusinessObject", anchor: true }),
      node("b", { name: "B", type: "Indicator" }),
      node("c", { name: "C", type: "Indicator" }),
      node("e", { name: "孤点", type: "LogicalEntity" }),
    ],
    links: [link("a", "b"), link("b", "c")],
  };
  const radial = buildRadialGraph(data);
  const byId = new Map(radial.nodes.map((n) => [n.id, n]));
  assert.equal(byId.get("b").layer, "distance:1");
  assert.equal(byId.get("c").layer, "distance:2");
  assert.equal(byId.get("e").layer, "unrelated");
  assert.deepEqual(
    radial.layerDefinitions.map((d) => d.key),
    ["distance:0", "distance:1", "distance:2", "unrelated"],
  );
  assert.deepEqual(
    radial.layerDefinitions.map((d) => d.label),
    ["中心", "1 跳", "2 跳", "未关联"],
  );
});

test("multiple shortest paths pick a deterministic parentId by stable id", () => {
  const data = {
    nodes: [
      node("a", { name: "锚点", type: "BusinessObject", anchor: true }),
      node("x", { name: "X", type: "Indicator" }),
      node("y", { name: "Y", type: "Indicator" }),
      node("z", { name: "Z", type: "Term" }),
    ],
    links: [link("a", "x"), link("a", "y"), link("x", "z"), link("y", "z")],
  };
  const radial = buildRadialGraph(data);
  const z = radial.nodes.find((n) => n.id === "z");
  assert.equal(z.layer, "distance:2");
  assert.equal(z.parentId, "x");
});

test("isolated nodes enter unrelated with empty parentId", () => {
  const data = {
    nodes: [
      node("a", { name: "锚点", type: "BusinessObject", anchor: true }),
      node("b", { name: "B", type: "Indicator" }),
      node("iso", { name: "孤立", type: "Term" }),
    ],
    links: [link("a", "b")],
  };
  const radial = buildRadialGraph(data);
  const iso = radial.nodes.find((n) => n.id === "iso");
  assert.equal(iso.layer, "unrelated");
  assert.equal(iso.parentId, "");
});

test("without explicit anchor, deterministic first legal node or data.anchor match becomes center", () => {
  const firstLegal = buildRadialGraph({
    nodes: [node("c", { name: "C", type: "Term" }), node("b", { name: "B", type: "Indicator" })],
    links: [],
  });
  assert.equal(firstLegal.nodes.filter((n) => n.layer === "distance:0").length, 1);
  assert.equal(firstLegal.nodes.find((n) => n.layer === "distance:0").id, "c");

  const byAnchorCode = buildRadialGraph({
    anchor: { code: "b" },
    nodes: [node("c", { name: "C", type: "Term" }), node("b", { name: "B", type: "Indicator" })],
    links: [],
  });
  assert.equal(byAnchorCode.nodes.find((n) => n.layer === "distance:0").id, "b");
});

test("graph without relation edges still renders center and unrelated layers", () => {
  const radial = buildRadialGraph({
    nodes: [node("a", { name: "锚点", type: "BusinessObject", anchor: true }), node("b", { name: "B", type: "Indicator" }), node("c", { name: "C", type: "Term" })],
    links: [],
  });
  assert.equal(radial.nodes.length, 3);
  assert.deepEqual(
    radial.layerDefinitions.map((d) => d.key),
    ["distance:0", "unrelated"],
  );
  assert.equal(radial.nodes.find((n) => n.id === "b").layer, "unrelated");
});

test("radial nodes carry id/name/label/layer/parentId/symbolSize/itemStyle/ontologyType", () => {
  const radial = buildRadialGraph({
    nodes: [node("a", { name: "锚点", type: "BusinessObject", anchor: true }), node("code-only", { code: "b", name: "", type: "Indicator" })],
    links: [link("a", "b")],
  });
  const radialNode = radial.nodes.find((n) => n.id === "code-only");
  for (const key of ["id", "name", "label", "layer", "parentId", "symbol", "symbolSize", "itemStyle", "ontologyType", "focus", "anchor"]) {
    assert.ok(Object.prototype.hasOwnProperty.call(radialNode, key), `missing ${key}`);
  }
  assert.equal(radialNode.name, "b");
  assert.equal(radialNode.label, "b");
  assert.equal(radialNode.ontologyType, "Indicator");
  assert.equal(radialNode.symbol, "roundRect");
  assert.ok(Array.isArray(radialNode.symbolSize));
  assert.ok(radialNode.symbolSize.every((v) => Number.isFinite(v) && v > 0));
  assert.ok(Number.isFinite(radialNode.symbolSize[0]));
});

test("radial styling reuses NODE_STYLE colors and clamps symbol size", () => {
  const radial = buildRadialGraph({
    nodes: [
      node("m", { name: "采购金额", type: "Indicator", anchor: true }),
      node("u", { name: "未知类型".repeat(30), type: "WeirdType" }),
    ],
    links: [],
  });
  const byId = new Map(radial.nodes.map((n) => [n.id, n]));
  assert.equal(byId.get("m").itemStyle.color, NODE_STYLE.Indicator[1]);
  assert.equal(byId.get("u").itemStyle.color, "#64748b");
  assert.ok(byId.get("u").symbolSize[0] <= 200, "symbol width must be capped");
  assert.ok(byId.get("u").symbolSize[1] <= 120, "symbol height must be capped");
});

test("input objects are never mutated", () => {
  const data = {
    nodes: [
      { id: "a", name: "锚点", type: "BusinessObject", anchor: true, nested: { keep: true } },
      { id: "b", name: "B", type: "Indicator" },
    ],
    links: [{ source: "a", target: "b", relation: "R1", extra: { keep: true } }],
  };
  const before = JSON.stringify(data);
  deepFreeze(data);
  buildRadialGraph(data);
  assert.equal(JSON.stringify(data), before);
});

test("edges with unknown endpoints or self loops are tolerated and skipped", () => {
  const radial = buildRadialGraph({
    nodes: [node("a", { name: "锚点", type: "BusinessObject", anchor: true }), node("b", { name: "B", type: "Indicator" })],
    links: [
      link("a", "b", { relation: "keep" }),
      link("a", "missing", { relation: "drop" }),
      link("a", "a", { relation: "self" }),
      { source: null, target: "b", relation: "null" },
      link("", "b", { relation: "empty" }),
    ],
  });
  assert.equal(radial.links.length, 1);
  const kept = radial.links[0];
  assert.equal(kept.source, "a");
  assert.equal(kept.target, "b");
  assert.equal(kept.relation, "keep");
  assert.ok(kept.lineStyle && kept.lineStyle.color);
});

test("identical input twice produces deeply equal output", () => {
  const data = {
    nodes: [
      node("a", { name: "锚点", type: "BusinessObject", anchor: true }),
      node("x", { name: "X", type: "Indicator" }),
      node("y", { name: "Y", type: "Term" }),
      node("z", { name: "Z", type: "LogicalEntity" }),
    ],
    links: [link("a", "x"), link("x", "y"), link("a", "y"), link("y", "z")],
  };
  const one = buildRadialGraph(data);
  const two = buildRadialGraph(data);
  assert.equal(JSON.stringify(one), JSON.stringify(two));
});

function deepFreeze(value) {
  if (!value || typeof value !== "object") return value;
  for (const child of Object.values(value)) deepFreeze(child);
  return Object.freeze(value);
}
