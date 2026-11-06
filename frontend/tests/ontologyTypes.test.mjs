import test from "node:test";
import assert from "node:assert/strict";
import { ONTOLOGY_TYPES, canonicalOntologyType, ontologyTypeKind } from "../src/ontologyTypes.js";
import { buildGraph, buildRadialGraph } from "../src/ontologyGraphModel.js";

test("all demo2 home palette types and legacy process/meta types retain distinct styles and labels", () => {
  const types = ["Action", "BusinessAttribute", "BusinessObject", "BusinessRule", "Dimension", "DimensionDerivedRule", "Event", "Field", "Indicator", "LogicalEntity", "PhysicalTable", "Status", "Term", "Activity", "Process", "EntityRelation", "MetaRelation"];
  const data = { nodes: types.map((type) => ({ id: type, code: type, name: type, type })), links: [] };
  const graph = buildGraph(data);
  const radial = buildRadialGraph(data);
  for (const type of types) {
    const definition = ONTOLOGY_TYPES.find(([name]) => name === type);
    assert.ok(definition, type);
    assert.equal(graph.getNodeAttribute(type, "nodeType"), definition[2]);
    assert.equal(graph.getNodeAttribute(type, "color"), definition[3]);
    assert.equal(radial.nodes.find((node) => node.id === type).itemStyle.color, definition[3]);
  }
});
test("legacy names normalize without conflating activity/action or relation types", () => {
  assert.equal(canonicalOntologyType("Rule"), "BusinessRule");
  assert.equal(canonicalOntologyType("TableNode"), "PhysicalTable");
  assert.equal(canonicalOntologyType("Column"), "Field");
  assert.equal(ontologyTypeKind("dimension_derived_rule"), "dimension_derived_rule");
  assert.notEqual(canonicalOntologyType("Activity"), canonicalOntologyType("Action"));
  assert.notEqual(canonicalOntologyType("EntityRelation"), canonicalOntologyType("MetaRelation"));
});
