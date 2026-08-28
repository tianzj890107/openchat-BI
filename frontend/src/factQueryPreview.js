/* =====================================================================
 * Ontology-FactQuery tool-card first-line summary (pure, deterministic).
 *
 * Only an explicit, human-readable description supplied in the tool input
 * may be rendered beside the tool name. Raw SQL is never shown on the first
 * line and is never parsed to manufacture a summary. When no description is
 * available the preview is intentionally empty. The complete input JSON,
 * including SQL, remains available in the expanded detail panel.
 * ===================================================================== */

const DESCRIPTION_KEYS = [
  "query_description",
  "description",
  "purpose",
  "question",
  "metric_name",
  "metric",
];

export function looksLikeSql(text) {
  return /^\s*(?:SELECT|WITH|EXPLAIN|PRAGMA)\b/i.test(String(text || ""));
}

export function factQueryPreview(input) {
  if (!input || typeof input !== "object") return "";
  for (const key of DESCRIPTION_KEYS) {
    const value = input[key];
    if (typeof value !== "string" || !value.trim()) continue;
    const cleaned = value.trim().replace(/\s+/g, " ");
    if (looksLikeSql(cleaned) || isCodeLike(cleaned) || cleaned.length > 80) continue;
    return shortenText(cleaned, 60);
  }
  return "";
}

function isCodeLike(text) {
  return /^[A-Za-z]{1,6}\d{3,}$/.test(text)
    || /^[A-Z0-9_]{3,}$/.test(text) && !/[\u4e00-\u9fff]/.test(text);
}

function shortenText(text, max) {
  if (text.length <= max) return text;
  return text.slice(0, max - 1) + "…";
}
