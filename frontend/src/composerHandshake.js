// Visible-composer handshake: the legacy hidden `#chat-input` and the controlled
// ProUiComposer are different state owners, so a prefill that arrives before the
// composer mounts must be queued, not dropped or blind-written into the DOM.
let ready = false
let pending = null
let generation = 0

export function isComposerReady() { return ready }

export function markComposerReady() {
  ready = true
  generation += 1
  return generation
}

export function markComposerGone() { ready = false }

/** Queue (or replace) the prefill for the visible composer; ids make it idempotent. */
export function queuePrefill(text, id = "") {
  const value = String(text ?? "")
  if (!value) return null
  pending = { text: value, id: String(id || "") }
  return pending
}

/** Consume the queued prefill once the composer is ready. */
export function consumePrefill() {
  const item = pending
  pending = null
  return item
}

export function resetHandshake() { ready = false; pending = null; generation = 0 }
