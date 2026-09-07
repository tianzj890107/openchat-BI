import test from "node:test";
import assert from "node:assert/strict";
import {
  createOntologyLayoutOptionTooltipState,
  hideOntologyLayoutOptionTooltip,
  showOntologyLayoutOptionTooltip,
} from "../src/ontologyLayoutOptionTooltipState.js";
import {
  ONTOLOGY_LAYOUT_OPTIONS,
  ontologyLayoutOption,
} from "../src/ontologyLayoutOptions.js";

const CLUSTER_HINT = "ForceAtlas2 是一种先进的力导向图布局，适合查看节点之间的关系聚类。";
const RADIAL_HINT = "以当前锚点为中心，按照最短关系距离由内向外分环排列。";

function hintOf(state) {
  if (!state?.value) return null;
  return ontologyLayoutOption(state.value)?.hint || null;
}

test("default state is hidden with no active value or hint", () => {
  const state = createOntologyLayoutOptionTooltipState();
  assert.equal(state.visible, false);
  assert.equal(state.value, null);
  assert.equal(hintOf(state), null);
});

test("hovering cluster shows the full new ForceAtlas2 hint", () => {
  const state = showOntologyLayoutOptionTooltip(
    createOntologyLayoutOptionTooltipState(),
    "cluster",
  );
  assert.equal(state.visible, true);
  assert.equal(state.value, "cluster");
  assert.equal(hintOf(state), CLUSTER_HINT);
});

test("hovering radial shows the unchanged ring hint", () => {
  const state = showOntologyLayoutOptionTooltip(
    createOntologyLayoutOptionTooltipState(),
    "radial",
  );
  assert.equal(state.visible, true);
  assert.equal(state.value, "radial");
  assert.equal(hintOf(state), RADIAL_HINT);
});

test("switching cluster to radial never keeps the old hint", () => {
  let state = showOntologyLayoutOptionTooltip(
    createOntologyLayoutOptionTooltipState(),
    "cluster",
  );
  state = showOntologyLayoutOptionTooltip(state, "radial");
  assert.equal(state.visible, true);
  assert.equal(state.value, "radial");
  assert.equal(hintOf(state), RADIAL_HINT);
  assert.notEqual(hintOf(state), CLUSTER_HINT);
});

test("leave, select, Escape, Tab, outside click, busy and modal close all collapse through hide", () => {
  for (const label of [
    "leave",
    "select",
    "Escape",
    "Tab",
    "outside click",
    "busy",
    "modal close",
  ]) {
    let state = showOntologyLayoutOptionTooltip(
      createOntologyLayoutOptionTooltipState(),
      "cluster",
    );
    assert.equal(state.visible, true, label);
    state = hideOntologyLayoutOptionTooltip(state);
    assert.equal(state.visible, false, label);
    assert.equal(state.value, null, label);
    assert.equal(hintOf(state), null, label);
  }
});

test("unknown values never show the bubble", () => {
  for (const value of ["network", "", undefined, null]) {
    const state = showOntologyLayoutOptionTooltip(
      createOntologyLayoutOptionTooltipState(),
      value,
    );
    assert.equal(state.visible, false, String(value));
    assert.equal(state.value, null, String(value));
  }
});

test("hide is idempotent", () => {
  const hidden = createOntologyLayoutOptionTooltipState();
  let state = hideOntologyLayoutOptionTooltip(hidden);
  assert.deepEqual(state, hidden);
  state = hideOntologyLayoutOptionTooltip(state);
  assert.deepEqual(state, hidden);
  state = showOntologyLayoutOptionTooltip(state, "cluster");
  state = hideOntologyLayoutOptionTooltip(state);
  state = hideOntologyLayoutOptionTooltip(state);
  assert.deepEqual(state, hidden);
});

test("tooltip transitions never mutate the frozen options registry", () => {
  const before = JSON.parse(JSON.stringify(ONTOLOGY_LAYOUT_OPTIONS));
  let state = createOntologyLayoutOptionTooltipState();
  for (const value of ["cluster", "radial", "network"]) {
    state = showOntologyLayoutOptionTooltip(state, value);
    state = hideOntologyLayoutOptionTooltip(state);
  }
  assert.deepEqual(JSON.parse(JSON.stringify(ONTOLOGY_LAYOUT_OPTIONS)), before);
});
