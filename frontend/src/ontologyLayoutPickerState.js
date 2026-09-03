// Pure state transitions for the ontology layout custom combobox/listbox.
// The module owns no DOM, fetch or graph state: it only tracks whether the
// listbox is open, which option is active and which layout value is selected,
// plus the keyboard/busy rules the DOM handlers delegate to.

import { ONTOLOGY_LAYOUT_OPTIONS, ontologyLayoutOption } from "./ontologyLayoutOptions.js";

export function createOntologyLayoutPickerState() {
  return {
    expanded: false,
    activeIndex: 0,
    selectedValue: ONTOLOGY_LAYOUT_OPTIONS[0].value,
  };
}

function optionIndex(value) {
  return Math.max(0, ONTOLOGY_LAYOUT_OPTIONS.findIndex((option) => option.value === value));
}

// Selected option object ({value,label,hint}) or null for an invalid value.
export function ontologyLayoutPickerSelectedOption(state) {
  const value = state?.selectedValue;
  return ontologyLayoutOption(value) || null;
}

// Value of the currently active option while the menu is open.
export function ontologyLayoutPickerActiveValue(state) {
  if (!state) return null;
  const option = ONTOLOGY_LAYOUT_OPTIONS[state.activeIndex];
  return option ? option.value : null;
}

export function openOntologyLayoutPicker(state, busy = false) {
  if (!state || busy || state.expanded) return state;
  return { ...state, expanded: true, activeIndex: optionIndex(state.selectedValue) };
}

export function closeOntologyLayoutPicker(state) {
  if (!state || !state.expanded) return state;
  return { ...state, expanded: false };
}

export function toggleOntologyLayoutPicker(state, busy = false) {
  if (!state || busy) return state;
  return state.expanded ? closeOntologyLayoutPicker(state) : openOntologyLayoutPicker(state);
}

// ArrowDown (+1) / ArrowUp (-1) wrap around the fixed two-option list.
export function moveOntologyLayoutPickerActive(state, delta) {
  if (!state || !ONTOLOGY_LAYOUT_OPTIONS.length) return state;
  const current = Number.isFinite(state.activeIndex) ? state.activeIndex : 0;
  const next = (current + delta + ONTOLOGY_LAYOUT_OPTIONS.length) % ONTOLOGY_LAYOUT_OPTIONS.length;
  return { ...state, activeIndex: next };
}

export function moveOntologyLayoutPickerHome(state) {
  if (!state) return state;
  return { ...state, activeIndex: 0 };
}

export function moveOntologyLayoutPickerEnd(state) {
  if (!state) return state;
  return { ...state, activeIndex: ONTOLOGY_LAYOUT_OPTIONS.length - 1 };
}

// Enter/Space on an open menu returns the value the DOM should select.
export function commitOntologyLayoutPicker(state) {
  if (!state || !state.expanded) return null;
  const option = ONTOLOGY_LAYOUT_OPTIONS[state.activeIndex];
  return option ? option.value : null;
}

// External sync: reopens, strategy responses and every layout switch funnel
// through here so the picker mirrors ontologyGraphViewState.layout. Unknown
// values are ignored and never enter the picker state.
export function syncOntologyLayoutPicker(state, value) {
  const base = state || createOntologyLayoutPickerState();
  const option = ontologyLayoutOption(value);
  const selectedValue = option ? value : base.selectedValue;
  return { ...base, selectedValue, activeIndex: optionIndex(selectedValue) };
}

// Busy transitions: while a request or render is in flight the menu must be
// collapsed and later busy=false leaves the (already closed) state untouched.
export function setOntologyLayoutPickerBusy(state, busy) {
  if (!state || !busy) return state;
  return closeOntologyLayoutPicker(state);
}
