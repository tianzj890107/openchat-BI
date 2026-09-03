import test from "node:test";
import assert from "node:assert/strict";
import {
  ONTOLOGY_LAYOUT_OPTIONS,
  ontologyLayoutOption,
} from "../src/ontologyLayoutOptions.js";

test("layout options are exactly cluster and radial in fixed order", () => {
  assert.equal(ONTOLOGY_LAYOUT_OPTIONS.length, 2);
  assert.deepEqual(
    ONTOLOGY_LAYOUT_OPTIONS.map((option) => option.value),
    ["cluster", "radial"],
  );
});

test("layout option labels match the spec table exactly", () => {
  assert.deepEqual(
    ONTOLOGY_LAYOUT_OPTIONS.map((option) => option.label),
    ["关系聚类可视化", "语义环形可视化"],
  );
});

test("layout option hints match the spec table exactly", () => {
  assert.deepEqual(
    ONTOLOGY_LAYOUT_OPTIONS.map((option) => option.hint),
    [
      "ForceAtlas2 力导向布局，适合查看节点之间的关系聚类。",
      "以当前锚点为中心，按照最短关系距离由内向外分环排列。",
    ],
  );
});

test("ontologyLayoutOption resolves legal values and rejects unknown ones", () => {
  const cluster = ontologyLayoutOption("cluster");
  const radial = ontologyLayoutOption("radial");
  assert.ok(cluster, "cluster must resolve to an option object");
  assert.equal(cluster.value, "cluster");
  assert.equal(cluster.label, "关系聚类可视化");
  assert.ok(radial, "radial must resolve to an option object");
  assert.equal(radial.value, "radial");
  assert.equal(radial.label, "语义环形可视化");
  assert.equal(ontologyLayoutOption("network"), null);
  assert.equal(ontologyLayoutOption(""), null);
  assert.equal(ontologyLayoutOption(undefined), null);
});

test("exported options array and option objects cannot be modified", () => {
  assert.throws(() => {
    ONTOLOGY_LAYOUT_OPTIONS.push({ value: "network" });
  }, TypeError);
  assert.throws(() => {
    ONTOLOGY_LAYOUT_OPTIONS[0].value = "network";
  }, TypeError);
  assert.throws(() => {
    ontologyLayoutOption("cluster").label = "关系模式";
  }, TypeError);
});
