import test from "node:test";
import assert from "node:assert/strict";
import {
  closeOntologyLayoutPicker,
  commitOntologyLayoutPicker,
  createOntologyLayoutPickerState,
  handleOntologyLayoutPickerKey,
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


test("closed Enter/Space opens the listbox on the current selection without committing", () => {
  let state = createOntologyLayoutPickerState();
  const enter = handleOntologyLayoutPickerKey(state, "Enter");
  assert.equal(enter.handled, true);
  assert.equal(enter.commitValue, null);
  assert.equal(enter.state.expanded, true);
  assert.equal(enter.state.activeIndex, 0, "opening highlights the current selection");
  assert.equal(enter.state.selectedValue, "cluster");
  const space = handleOntologyLayoutPickerKey(createOntologyLayoutPickerState(), " ");
  assert.equal(space.handled, true);
  assert.equal(space.state.expanded, true);
  assert.equal(space.commitValue, null);
});

test("open Enter/Space commits the active option and closes without self-selecting", () => {
  let state = openOntologyLayoutPicker(createOntologyLayoutPickerState());
  state = moveOntologyLayoutPickerActive(state, 1);
  const enter = handleOntologyLayoutPickerKey(state, "Enter");
  assert.equal(enter.handled, true);
  assert.equal(enter.commitValue, "radial");
  assert.equal(enter.state.expanded, false);
  assert.equal(enter.state.selectedValue, "cluster", "the key transition never selects by itself");
  const space = handleOntologyLayoutPickerKey(state, " ");
  assert.equal(space.handled, true);
  assert.equal(space.commitValue, "radial");
  assert.equal(space.state.expanded, false);
});

test("ArrowDown/ArrowUp from closed open and step relative to the current selection", () => {
  const down = handleOntologyLayoutPickerKey(createOntologyLayoutPickerState(), "ArrowDown");
  assert.equal(down.handled, true);
  assert.equal(down.state.expanded, true);
  assert.equal(down.state.activeIndex, 1, "closed ArrowDown opens on the next option");
  assert.equal(down.commitValue, null);
  const up = handleOntologyLayoutPickerKey(createOntologyLayoutPickerState(), "ArrowUp");
  assert.equal(up.state.expanded, true);
  assert.equal(up.state.activeIndex, 1, "closed ArrowUp from cluster wraps to radial");
  const radial = syncOntologyLayoutPicker(createOntologyLayoutPickerState(), "radial");
  const upFromRadial = handleOntologyLayoutPickerKey(radial, "ArrowUp");
  assert.equal(upFromRadial.state.activeIndex, 0, "closed ArrowUp from radial wraps to cluster");
});

test("ArrowDown/ArrowUp keep cycling while the listbox is open", () => {
  let state = openOntologyLayoutPicker(createOntologyLayoutPickerState());
  let result = handleOntologyLayoutPickerKey(state, "ArrowDown");
  assert.equal(result.handled, true);
  assert.equal(result.state.expanded, true);
  assert.equal(result.state.activeIndex, 1);
  result = handleOntologyLayoutPickerKey(result.state, "ArrowDown");
  assert.equal(result.state.activeIndex, 0, "ArrowDown past the last option wraps");
  result = handleOntologyLayoutPickerKey(result.state, "ArrowUp");
  assert.equal(result.state.activeIndex, 1, "ArrowUp past the first option wraps");
});

test("Home/End open when closed and jump when open", () => {
  const radial = syncOntologyLayoutPicker(createOntologyLayoutPickerState(), "radial");
  const homeClosed = handleOntologyLayoutPickerKey(radial, "Home");
  assert.equal(homeClosed.state.expanded, true);
  assert.equal(homeClosed.state.activeIndex, 0);
  const endClosed = handleOntologyLayoutPickerKey(radial, "End");
  assert.equal(endClosed.state.expanded, true);
  assert.equal(endClosed.state.activeIndex, 1);
  let open = openOntologyLayoutPicker(createOntologyLayoutPickerState());
  open = moveOntologyLayoutPickerActive(open, 1);
  const home = handleOntologyLayoutPickerKey(open, "Home");
  assert.equal(home.state.activeIndex, 0);
  const end = handleOntologyLayoutPickerKey(open, "End");
  assert.equal(end.state.activeIndex, 1);
});

test("Escape closes without commit or layout change", () => {
  let state = syncOntologyLayoutPicker(createOntologyLayoutPickerState(), "radial");
  state = openOntologyLayoutPicker(state);
  const result = handleOntologyLayoutPickerKey(state, "Escape");
  assert.equal(result.handled, true);
  assert.equal(result.state.expanded, false);
  assert.equal(result.commitValue, null);
  assert.equal(result.state.selectedValue, "radial", "Escape never changes the layout");
  const closed = handleOntologyLayoutPickerKey(createOntologyLayoutPickerState(), "Escape");
  assert.equal(closed.handled, false, "Escape on a closed listbox is unhandled");
  assert.equal(closed.state.expanded, false);
});

test("Tab closes the listbox, stays unhandled and never commits", () => {
  const open = openOntologyLayoutPicker(createOntologyLayoutPickerState());
  const result = handleOntologyLayoutPickerKey(open, "Tab");
  assert.equal(result.handled, false, "Tab must not preventDefault");
  assert.equal(result.state.expanded, false);
  assert.equal(result.commitValue, null);
  const closed = handleOntologyLayoutPickerKey(createOntologyLayoutPickerState(), "Tab");
  assert.equal(closed.handled, false);
  assert.equal(closed.state.expanded, false);
});

test("unsupported keys are unhandled and leave the state object untouched", () => {
  const state = openOntologyLayoutPicker(createOntologyLayoutPickerState());
  const result = handleOntologyLayoutPickerKey(state, "F6");
  assert.equal(result.handled, false);
  assert.equal(result.commitValue, null);
  assert.equal(result.state, state, "unsupported keys return the same state object");
  assert.equal(result.state.expanded, true);
});

test("busy blocks opening, navigation and commit and closes an open listbox", () => {
  for (const key of ["Enter", " ", "ArrowDown", "ArrowUp", "Home", "End", "Escape"]) {
    const open = openOntologyLayoutPicker(createOntologyLayoutPickerState());
    const result = handleOntologyLayoutPickerKey(open, key, { busy: true });
    assert.equal(result.state.expanded, false, `${key} while busy must close the menu`);
    assert.equal(result.commitValue, null, `${key} while busy must not commit`);
  }
  for (const key of ["Enter", " ", "ArrowDown", "ArrowUp", "Home", "End"]) {
    const closed = createOntologyLayoutPickerState();
    const result = handleOntologyLayoutPickerKey(closed, key, { busy: true });
    assert.equal(result.state.expanded, false, `${key} while busy must not open the menu`);
    assert.equal(result.commitValue, null);
  }
  const tab = handleOntologyLayoutPickerKey(openOntologyLayoutPicker(createOntologyLayoutPickerState()), "Tab", { busy: true });
  assert.equal(tab.handled, false, "Tab stays unhandled even while busy");
  assert.equal(tab.state.expanded, false);
});

test("keyboard commit stays separate from syncOntologyLayoutPicker", () => {
  let state = openOntologyLayoutPicker(createOntologyLayoutPickerState());
  state = moveOntologyLayoutPickerActive(state, 1);
  const result = handleOntologyLayoutPickerKey(state, "Enter");
  assert.equal(result.commitValue, "radial");
  assert.equal(result.state.selectedValue, "cluster", "the pure key transition never selects");
  const synced = syncOntologyLayoutPicker(result.state, result.commitValue);
  assert.equal(synced.selectedValue, "radial");
  assert.equal(synced.activeIndex, 1);
});
