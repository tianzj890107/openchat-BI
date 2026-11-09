# DeepSeek assistant-message compatibility

2026-11-09. Customer diagnostics identified DeepSeek 400 errors: `Invalid assistant message: content or tool_calls must be set`. The shared Team provider uses the DeepSeek message converter. Empty or reasoning-only persisted assistant blocks were previously emitted as `content:null` without tool calls.

The outgoing converter now omits assistant turns with no nonblank text and no tool calls, including empty string turns. It preserves tool-only messages, tool-call IDs, tool results and reasoning for valid assistant turns when thinking is enabled. Stored conversation history is never rewritten. Both direct DeepSeek and Team/LiteLLM use this projection.

When the selected Team model is DeepSeek, automatic quota/rate-limit fallbacks remain within DeepSeek-named routes. This prevents silently selecting MiMo/GLM/etc from a stale gateway catalogue. It does not verify advertised gateway routes or change their configuration; ordinary 400 errors are not retried as quota failures. Existing TEAM_BASE_URL and TEAM_MODEL remain authoritative.

Validation: 230 tests passed, plus 42 subtests (message conversion, tool pairing, thinking modes, fallback catalogue and existing regression suite). No live model calls, gateway writes, customer configuration edits, tar changes or deployment. AP query-combination gaps and missing quotation metrics are separate issues and are not addressed by this patch.
