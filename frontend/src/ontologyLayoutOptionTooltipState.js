// Pure state transitions for the per-option hover tooltip inside the layout
// listbox. The module owns no DOM: it only tracks whether the single tooltip
// is visible and which option value it describes. The runtime DOM layer reads
// the hint text from ONTOLOGY_LAYOUT_OPTIONS by value and never duplicates it.

import { ontologyLayoutOption } from "./ontologyLayoutOptions.js";

export function createOntologyLayoutOptionTooltipState() {
  return { visible: false, value: null };
}

export function showOntologyLayoutOptionTooltip(state, value) {
  const current = state || createOntologyLayoutOptionTooltipState();
  if (!ontologyLayoutOption(value)) return current;
  return { visible: true, value };
}

export function hideOntologyLayoutOptionTooltip(state) {
  const current = state || createOntologyLayoutOptionTooltipState();
  if (!current.visible && current.value === null) return current;
  return { visible: false, value: null };
}
