import {withBasePath} from "./api.js";

const fields = ["ontology", "database", "retrieval_mode", "graph", "doris_database"];

export function sourceSelection(value) {
  return Object.fromEntries(fields
    .filter((field) => typeof value?.[field] === "string" && value[field].trim())
    .map((field) => [field, value[field].trim()]));
}

function storageKey() {
  return `agentkit.source.${withBasePath("workbench-agentkit")}`;
}

export function readSourcePreference() {
  try {
    const selection = sourceSelection(JSON.parse(window.localStorage.getItem(storageKey())));
    return Object.keys(selection).length ? selection : null;
  } catch {
    return null;
  }
}

export function writeSourcePreference(selection) {
  try {
    window.localStorage.setItem(storageKey(), JSON.stringify(sourceSelection(selection)));
  } catch {
    // The current tab can still use the selection when storage is unavailable.
  }
}
