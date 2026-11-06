import test from "node:test";
import assert from "node:assert/strict";
import { mergeOntologyHitGraphs, ontologyHitKey } from "../src/ontologyHitsGraphModel.js";
import { buildGraph } from "../src/ontologyGraphModel.js";

const object = { code: "BO1", kind: "business_object", name: "订单", source: "local" };
const attribute = { code: "BA1", kind: "attribute", name: "金额", source: "local" };
const context = {
  nodes: [{ id: "BO1", code: "BO1", type: "business_object", name: "订单" }, { id: "BA1", code: "BA1", type: "attribute", name: "金额" }],
  links: [{ source: "BO1", target: "BA1", relationType: "HAS_ATTRIBUTE" }],
};
test("overlapping contexts merge hits, canonicalize local types and preserve real parent grouping", () => {
  const data = mergeOntologyHitGraphs([object, attribute], new Map([[ontologyHitKey(object), context], [ontologyHitKey(attribute), context]]));
  assert.equal(data.nodes.length, 2);
  assert.equal(data.links.length, 1);
  assert.ok(data.nodes.every((node) => node.focus));
  const graph = buildGraph(data);
  const child = data.nodes.find((node) => node.code === "BA1");
  assert.equal(graph.getNodeAttribute(child.id, "parentId"), data.nodes.find((node) => node.code === "BO1").id);
});
test("same codes in different repositories stay separate", () => {
  const a = { ...object, source: "remote", repository_id: "a" };
  const b = { ...object, source: "remote", repository_id: "b" };
  const attrA = { ...attribute, source: "remote", repository_id: "a" };
  const attrB = { ...attribute, source: "remote", repository_id: "b" };
  const data = mergeOntologyHitGraphs([a, b, attrA, attrB], new Map([[ontologyHitKey(a), context], [ontologyHitKey(b), context]]));
  assert.equal(data.nodes.length, 4);
  assert.equal(data.links.length, 2);
  assert.notEqual(ontologyHitKey(a), ontologyHitKey(b));
});
test("filters remove context nodes and dangling edges, without dropping visible hits", () => {
  const data = mergeOntologyHitGraphs([object, attribute], new Map([[ontologyHitKey(object), context]]), { attribute: false });
  assert.equal(data.nodes.length, 1);
  assert.equal(data.nodes[0].code, "BO1");
  assert.equal(data.links.length, 0);
});
test("missing context keeps isolated hits and never invents relationships", () => {
  const data = mergeOntologyHitGraphs([object, attribute], new Map());
  assert.equal(data.nodes.length, 2);
  assert.equal(data.links.length, 0);
});
test("overview excludes unhit context nodes and edges to them", () => {
  const data = mergeOntologyHitGraphs([object], new Map([[ontologyHitKey(object), context]]));
  assert.deepEqual(data.nodes.map((node) => node.code), ["BO1"]);
  assert.equal(data.links.length, 0);
});
test("unhit intermediates never become an inferred edge between hits", () => {
  const other = { ...object, code: "BO2" };
  const data = mergeOntologyHitGraphs([object, other], new Map([[ontologyHitKey(object), {
    nodes: [...context.nodes, { id: "BO2", code: "BO2", type: "BusinessObject" }],
    links: [...context.links, { source: "BA1", target: "BO2" }],
  }]]));
  assert.equal(data.nodes.length, 2);
  assert.equal(data.links.length, 0);
});
test("synthetic neighbor edges are not presented as ontology relationships", () => {
  const data = mergeOntologyHitGraphs([object], new Map([[ontologyHitKey(object), {
    ...context, links: context.links.map((edge) => ({ ...edge, synthetic: true })),
  }]]));
  assert.equal(data.nodes.length, 1);
  assert.equal(data.links.length, 0);
});
test("distinct relation types and directions are preserved; broken and self edges are omitted", () => {
  const data = mergeOntologyHitGraphs([object, attribute], new Map([[ontologyHitKey(object), { ...context, links: [
    ...context.links, { source: "BO1", target: "BA1", relationType: "USES" },
    { source: "BA1", target: "BO1", relationType: "USES" },
    { source: "BO1", target: "absent" }, { source: "BO1", target: "BO1" },
  ] }]]));
  assert.equal(data.links.length, 3);
});
