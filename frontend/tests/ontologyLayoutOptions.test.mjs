import test from "node:test";
import assert from "node:assert/strict";
import {
  ONTOLOGY_LAYOUT_OPTIONS,
  ontologyLayoutOption,
} from "../src/ontologyLayoutOptions.js";

const OLD_CLUSTER_HINT = "ForceAtlas2 力导向布局，适合查看节点之间的关系聚类。";

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

test("cluster hint uses the full advanced ForceAtlas2 sentence", () => {
  assert.equal(
    ontologyLayoutOption("cluster").hint,
    "ForceAtlas2 是一种先进的力导向图布局，适合查看节点之间的关系聚类。",
  );
});

test("radial hint keeps the unchanged ring description", () => {
  assert.equal(
    ontologyLayoutOption("radial").hint,
    "以当前锚点为中心，按照最短关系距离由内向外分环排列。",
  );
});

test("the old ForceAtlas2 hint copy no longer exists anywhere in the registry", () => {
  const serialized = JSON.stringify(ONTOLOGY_LAYOUT_OPTIONS);
  assert.ok(!serialized.includes(OLD_CLUSTER_HINT), "old cluster hint must be gone");
  assert.ok(!serialized.includes("ForceAtlas2 力导向布局"), "short old copy must be gone");
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
