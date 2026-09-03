import test from "node:test";
import assert from "node:assert/strict";
import {
  closeOntologyLayoutPicker,
  commitOntologyLayoutPicker,
  createOntologyLayoutPickerState,
  moveOntologyLayoutPickerActive,
  moveOntologyLayoutPickerEnd,
  moveOntologyLayoutPickerHome,
  ontologyLayoutPickerActiveValue,
  ontologyLayoutPickerSelectedOption,
  openOntologyLayoutPicker,
  setOntologyLayoutPickerBusy,
  syncOntologyLayoutPicker,
  toggleOntologyLayoutPicker,
} from "../src/ontologyLayoutPickerState.js";

test("picker defaults to closed with cluster selected", () => {
  const state = createOntologyLayoutPickerState();
  assert.equal(state.expanded, false);
  assert.equal(state.selectedValue, "cluster");
  assert.equal(state.activeIndex, 0);
  const selected = ontologyLayoutPickerSelectedOption(state);
  assert.ok(selected, "default selection must resolve");
  assert.equal(selected.value, "cluster");
  assert.equal(selected.label, "关系聚类可视化");
});

test("toggle opens and closes the listbox", () => {
  let state = createOntologyLayoutPickerState();
  state = toggleOntologyLayoutPicker(state);
  assert.equal(state.expanded, true);
  state = toggleOntologyLayoutPicker(state);
  assert.equal(state.expanded, false);
});

test("open and close only flip the expanded flag", () => {
  let state = createOntologyLayoutPickerState();
  state = openOntologyLayoutPicker(state);
  assert.equal(state.expanded, true);
  assert.equal(state.selectedValue, "cluster");
  state = closeOntologyLayoutPicker(state);
  assert.equal(state.expanded, false);
  assert.equal(state.selectedValue, "cluster", "close must keep the layout value");
});

test("ArrowDown and ArrowUp cycle the active option", () => {
  let state = openOntologyLayoutPicker(createOntologyLayoutPickerState());
  assert.equal(state.activeIndex, 0);
  state = moveOntologyLayoutPickerActive(state, 1);
  assert.equal(state.activeIndex, 1);
  state = moveOntologyLayoutPickerActive(state, 1);
  assert.equal(state.activeIndex, 0, "ArrowDown past the last option wraps to the first");
  state = moveOntologyLayoutPickerActive(state, -1);
  assert.equal(state.activeIndex, 1, "ArrowUp from the first option wraps to the last");
});

test("Home and End move to the first and last option", () => {
  let state = openOntologyLayoutPicker(createOntologyLayoutPickerState());
  state = moveOntologyLayoutPickerActive(state, 1);
  assert.equal(state.activeIndex, 1);
  state = moveOntologyLayoutPickerHome(state);
  assert.equal(state.activeIndex, 0);
  state = moveOntologyLayoutPickerEnd(state);
  assert.equal(state.activeIndex, 1);
});

test("Enter/Space commit returns the active option value", () => {
  let state = openOntologyLayoutPicker(createOntologyLayoutPickerState());
  assert.equal(ontologyLayoutPickerActiveValue(state), "cluster");
  state = moveOntologyLayoutPickerActive(state, 1);
  assert.equal(ontologyLayoutPickerActiveValue(state), "radial");
  assert.equal(commitOntologyLayoutPicker(state), "radial");
  assert.equal(
    commitOntologyLayoutPicker(closeOntologyLayoutPicker(state)),
    null,
    "a closed picker commits nothing",
  );
});

test("Escape/close cancels without changing the selected layout", () => {
  let state = createOntologyLayoutPickerState();
  state = syncOntologyLayoutPicker(state, "radial");
  state = openOntologyLayoutPicker(state);
  const closed = closeOntologyLayoutPicker(state);
  assert.equal(closed.expanded, false);
  assert.equal(closed.selectedValue, "radial", "cancel must not change the layout");
});

test("external state sync updates value, active option, label and hint", () => {
  let state = createOntologyLayoutPickerState();
  state = syncOntologyLayoutPicker(state, "radial");
  assert.equal(state.selectedValue, "radial");
  assert.equal(state.activeIndex, 1);
  const selected = ontologyLayoutPickerSelectedOption(state);
  assert.equal(selected.value, "radial");
  assert.equal(selected.label, "语义环形可视化");
  assert.equal(selected.hint, "以当前锚点为中心，按照最短关系距离由内向外分环排列。");
  state = openOntologyLayoutPicker(state);
  assert.equal(state.activeIndex, 1, "opening highlights the current selection");
});

test("busy closes an open menu and prevents reopening", () => {
  let state = openOntologyLayoutPicker(createOntologyLayoutPickerState());
  assert.equal(state.expanded, true);
  state = setOntologyLayoutPickerBusy(state, true);
  assert.equal(state.expanded, false, "busy must close an open menu");
  const opening = openOntologyLayoutPicker(createOntologyLayoutPickerState(), true);
  assert.equal(opening.expanded, false, "busy must prevent opening");
  const toggling = toggleOntologyLayoutPicker(createOntologyLayoutPickerState(), true);
  assert.equal(toggling.expanded, false, "busy must prevent toggling open");
});

test("unknown values never become the picker value", () => {
  const state = createOntologyLayoutPickerState();
  const next = syncOntologyLayoutPicker(state, "network");
  assert.equal(next.selectedValue, "cluster", "unknown value is ignored");
  const selected = ontologyLayoutPickerSelectedOption(next);
  assert.equal(selected.value, "cluster");
  assert.equal(selected.label, "关系聚类可视化");
});
