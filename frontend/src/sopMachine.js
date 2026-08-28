/* =====================================================================
 * Pure 6-step analysis SOP state machine.
 *
 * No DOM, no side effects, no imports — used by the runtime (runtime.js)
 * and by the Python regression tests via `node --input-type=module`.
 *
 * The machine tracks the real trajectory: every step that is actually
 * entered is recorded in `visited`.  Statuses are derived from the
 * trajectory instead of a linear "everything before the cursor is done"
 * rule, so:
 *  - a step that was never executed is `skipped` (never green);
 *  - a backward move (05→03 / 04→03 / 06→05) drops the superseded steps
 *    from the trajectory so they become `pending` again (never stale green);
 *  - exactly one step is `in_progress` at any time;
 *  - only a terminal backend `done` event converts the final state:
 *    visited → completed, unvisited → skipped.
 * ===================================================================== */

export const SOP_STEPS = Object.freeze([
  "意图识别",
  "本体模型匹配",
  "深度思考&分析规划",
  "数据获取和可视化",
  "根因分析",
  "决策行动",
]);

export const SOP_STATUS_COMPLETED = "completed";
export const SOP_STATUS_IN_PROGRESS = "in_progress";
export const SOP_STATUS_PENDING = "pending";
export const SOP_STATUS_SKIPPED = "skipped";

export function clampStep(stepIndex) {
  const n = Number(stepIndex);
  if (!Number.isInteger(n)) return 0;
  return Math.max(0, Math.min(SOP_STEPS.length - 1, n));
}

function normalizeVisited(visited) {
  if (!Array.isArray(visited)) return [];
  const seen = new Set();
  const out = [];
  for (const item of visited) {
    const step = clampStep(item);
    if (!seen.has(step)) { seen.add(step); out.push(step); }
  }
  out.sort((a, b) => a - b);
  return out;
}

/**
 * Mid-run statuses given the visited trajectory and the current step.
 * The current step is `in_progress`; visited steps are `completed`; a step
 * that was bypassed (never visited) is `skipped` when it lies behind the
 * cursor and `pending` when it is still ahead.
 */
export function sopStatusesFor(visited, current) {
  const cur = clampStep(current);
  const seen = new Set(normalizeVisited(visited));
  return SOP_STEPS.map((_, i) => {
    if (i === cur) return SOP_STATUS_IN_PROGRESS;
    if (seen.has(i)) return SOP_STATUS_COMPLETED;
    return i < cur ? SOP_STATUS_SKIPPED : SOP_STATUS_PENDING;
  });
}

/**
 * Terminal statuses after the backend `done` event: every visited step is
 * `completed`, every step that was never executed is `skipped` (non-green).
 * `done` only means the turn finished successfully — it never paints steps
 * that were not actually executed as green.
 */
export function sopStatusesForDone(visited) {
  const seen = new Set(normalizeVisited(visited));
  return SOP_STEPS.map((_, i) => seen.has(i) ? SOP_STATUS_COMPLETED : SOP_STATUS_SKIPPED);
}

/**
 * Pure transition.  Returns `null` when nothing changes (or a backward move
 * was rejected), otherwise `{ step, visited, todos }` where todos is a fresh
 * array of six `{ content, detail, status }` items.  Detail is attached only
 * to the current (in-progress) step.
 */
export function applySopStep(visited, current, stepIndex, detail, options = {}) {
  const allowBackward = !!(options && options.allowBackward);
  const cur = clampStep(current);
  const target = clampStep(stepIndex);
  if (target < cur && !allowBackward) return null;
  if (target === cur && !detail) return null;
  const seen = normalizeVisited(visited);
  let nextSeen;
  if (target < cur) {
    // Backward move: superseded later steps leave the trajectory so they
    // become pending again instead of staying green.
    nextSeen = seen.filter((i) => i <= target);
    if (!nextSeen.includes(target)) nextSeen.push(target);
  } else {
    nextSeen = seen.includes(target) ? seen.slice() : seen.concat(target);
  }
  nextSeen.sort((a, b) => a - b);
  const statuses = sopStatusesFor(nextSeen, target);
  const todos = SOP_STEPS.map((content, i) => ({
    content,
    detail: i === target && detail ? String(detail) : "",
    status: statuses[i],
  }));
  return { step: target, visited: nextSeen, todos };
}

/** Index of the in-progress step, or SOP_STEPS.length when none. */
export function currentStepOf(todos) {
  if (!Array.isArray(todos)) return 0;
  const cur = todos.findIndex((item) => item && item.status === SOP_STATUS_IN_PROGRESS);
  return cur < 0 ? SOP_STEPS.length : cur;
}

/** Derive the visited trajectory from a restored todos array. */
export function visitedFromTodos(todos) {
  if (!Array.isArray(todos)) return [];
  return todos
    .map((item, i) => (item && item.status === SOP_STATUS_COMPLETED ? i : -1))
    .filter((i) => i >= 0);
}

// Legacy snapshot mappings (old index -> closest new 0-based step).
// Old 5-step (superseded today): semantics/context -> ontology matching,
// planning stays, data fetch stays, final delivery -> decision actions.
export const LEGACY_5_TO_6 = Object.freeze([1, 1, 2, 3, 5]);
// Old 6-step histories: intent -> intent; caliber/context -> ontology
// matching; planning -> planning; fetch -> data fetch; analysis -> root
// cause; delivery -> decision actions.
export const LEGACY_6_TO_6 = Object.freeze([0, 1, 2, 3, 4, 5]);
// Old 9-step histories: intent -> intent; caliber/context -> ontology
// matching; planning -> planning; query loops -> data fetch; deeper
// analysis/verification -> root cause; final delivery -> decision actions.
export const LEGACY_9_TO_6 = Object.freeze([0, 1, 2, 3, 4, 3, 4, 4, 5]);

/**
 * Convert a restored snapshot into the 6-step shape.  Completed legacy
 * histories map to all-six-completed; an in-progress legacy cursor maps to
 * the closest new step (later steps become pending again).  The conversion
 * happens only in memory — stored history JSON is never rewritten.
 */
export function migrateLegacySop(snapshot, hasContent) {
  const source = Array.isArray(snapshot) ? snapshot : [];
  if (!source.length) {
    return hasContent
      ? SOP_STEPS.map((content) => ({ content, detail: "", status: SOP_STATUS_COMPLETED }))
      : [];
  }
  const allCompleted = SOP_STEPS.map((content) => ({
    content, detail: "", status: SOP_STATUS_COMPLETED,
  }));
  const migrateWith = (mapping) => {
    const oldCursor = source.findIndex((item) => item && item.status !== SOP_STATUS_COMPLETED);
    if (oldCursor < 0) return null;
    const target = mapping[oldCursor];
    const detail = String((source[oldCursor] && source[oldCursor].detail) || "");
    const visited = Array.from({ length: target + 1 }, (_, i) => i);
    return SOP_STEPS.map((content, index) => ({
      content,
      detail: index === target ? detail : "",
      status: sopStatusesFor(visited, target)[index],
    }));
  };
  if (source.length === 5) {
    const migrated = migrateWith(LEGACY_5_TO_6);
    return migrated == null ? allCompleted : migrated;
  }
  if (source.length === 6) {
    const migrated = migrateWith(LEGACY_6_TO_6);
    return migrated == null ? allCompleted : migrated;
  }
  if (source.length === 9) {
    const migrated = migrateWith(LEGACY_9_TO_6);
    return migrated == null ? allCompleted : migrated;
  }
  return SOP_STEPS.map((content, index) => {
    const item = source[index] || {};
    const status = [SOP_STATUS_COMPLETED, SOP_STATUS_IN_PROGRESS, SOP_STATUS_PENDING, SOP_STATUS_SKIPPED]
      .includes(item.status)
      ? item.status
      : SOP_STATUS_PENDING;
    return {
      content: String(item.content || content),
      detail: String(item.detail || ""),
      status,
    };
  });
}
