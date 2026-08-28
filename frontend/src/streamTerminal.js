/* =====================================================================
 * Pure classification of an SSE stream's EOF for the workbench runtime.
 *
 * A plain EOF on the fetch stream does NOT prove the turn succeeded: the
 * connection can be cut by a proxy/gateway, the browser, a crashed backend
 * process, or a truncated JSON frame.  Only an explicitly parsed backend
 * terminal frame (`done` / `error` / `session_superseded`) may classify the
 * stream as terminal; anything else is `interrupted` — never a synthetic
 * `done`.  A stale stream (superseded by a newer request or turn) must stay
 * silent so an old request can never touch the new request's UI.
 *
 * No DOM, no side effects, no imports — also used by the Python regression
 * tests via `node --input-type=module`.
 * ===================================================================== */

export function classifyStreamEof({ stale = false, sawTerminal = false } = {}) {
  if (stale) return "stale";
  if (sawTerminal) return "terminal";
  return "interrupted";
}
