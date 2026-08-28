/* =====================================================================
 * Pure turn-terminal lifecycle state for the workbench runtime.
 *
 * Only an explicitly accepted backend `done` marks a turn as completed;
 * a turn that ended in `error` / `session_superseded` /
 * `stream_interrupted` is recorded as failed and a late `done` must never
 * flip it back into success.  Repeated or delayed `done` frames for the
 * same turn are idempotent: the completed set is bounded (small FIFO) so
 * a long session cannot grow it without limit.
 *
 * No DOM, no side effects, no imports — used by runtime.js and by the
 * Python regression tests via `node --input-type=module`.
 * ===================================================================== */

export const DEFAULT_COMPLETED_TURN_CAPACITY = 64;

export function createTurnLifecycle({ capacity = DEFAULT_COMPLETED_TURN_CAPACITY } = {}) {
  return { completed: [], failed: new Set(), capacity };
}

export function isTurnCompleted(state, turnId) {
  return state.completed.includes(turnId);
}

export function isTurnFailed(state, turnId) {
  return state.failed.has(turnId);
}

// Accept a `done` only for a turn that is neither already completed nor
// failed.  Returns { state, accepted } so callers can skip all success side
// effects when the frame is a duplicate or a late echo of a dead turn.
export function recordDone(state, turnId) {
  if (isTurnCompleted(state, turnId) || isTurnFailed(state, turnId)) {
    return { state, accepted: false };
  }
  const completed = state.completed.concat(turnId);
  if (completed.length > state.capacity) {
    completed.splice(0, completed.length - state.capacity);
  }
  return { state: { ...state, completed }, accepted: true };
}

export function recordFailure(state, turnId) {
  if (!turnId) return state;
  const failed = new Set(state.failed);
  failed.add(turnId);
  return { ...state, failed };
}

export function resetTurnLifecycle(state) {
  return { completed: [], failed: new Set(), capacity: state.capacity };
}
