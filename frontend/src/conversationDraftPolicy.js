/* Pure helpers for the「新会话」(new conversation) draft policy.
 *
 * Clicking 新会话 may create one empty draft. Until the user actually types
 * anything, clicking it again must reuse that draft instead of piling up empty
 * entries in the sidebar. Keeping the decision in pure functions makes the
 * rule testable and lets the runtime, the history list and the React sidebar
 * share exactly the same result.
 */

/** True when the current bucket is an untouched 新会话 draft. */
export function shouldReuseUnusedDraft(state = {}) {
  const draft = state || {};
  return Boolean(draft.convId)
    && draft.hasContent === false
    && !String(draft.firstUserQuestion ?? "").trim()
    && Number(draft.turnCount || 0) === 0;
}

/** True for a history summary that carries no user content yet. */
export function isUnusedDraftSummary(item) {
  if (!item || !item.id) return false;
  if (Number(item.turn_count || 0) > 0) return false;
  return !String(item.first_user_question ?? "").trim();
}

function summaryMode(item) {
  return item && item.mode === "report" ? "report" : "data";
}

function isNewerSummary(candidate, current) {
  const candidateTime = String(candidate?.updated_at || "");
  const currentTime = String(current?.updated_at || "");
  if (candidateTime !== currentTime) return candidateTime > currentTime;
  return String(candidate?.id || "") > String(current?.id || "");
}

/**
 * Keep every real conversation plus only the newest unused draft per mode.
 *
 * This is a display-layer guard for drafts accumulated before the reuse rule
 * existed: it never deletes a server-side history file, it only removes the
 * duplicate placeholders from the rendered list.
 */
export function collapseUnusedDrafts(items) {
  const list = Array.isArray(items) ? items : [];
  const newestDraft = new Map();
  list.forEach((item) => {
    if (!isUnusedDraftSummary(item)) return;
    const mode = summaryMode(item);
    const current = newestDraft.get(mode);
    if (!current || isNewerSummary(item, current)) newestDraft.set(mode, item);
  });
  const keep = new Set(Array.from(newestDraft.values(), (item) => item?.id));
  return list.filter((item) => !isUnusedDraftSummary(item) || keep.has(item?.id));
}
