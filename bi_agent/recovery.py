"""Lightweight analysis Recovery state machine (phase 2, in-process).

Recovery is the *execution-control* state of one analysis turn, separate from
the six-step SOP display track.  It records where the turn is, which tool
results were confirmed (checkpoints), and whether a failure may be retried
explicitly.  Only small, sanitized references are persisted; full SQL, user
text, credentials, complete result sets, Claim collections and thread/lock
objects are never stored here.

The module deliberately does not import ``bi_agent.web.session``: WebSession
calls into this module and keeps DOM/SSE/state side effects in its own layer.
"""

from __future__ import annotations

import copy
import hashlib
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .tool_runtime import canonical_input

RECOVERY_VERSION = 1
MAX_RECOVERY_ATTEMPTS = 2

# Stable statuses (external contract).
PLANNED = "PLANNED"
RUNNING = "RUNNING"
WAITING_USER = "WAITING_USER"
SUCCEEDED = "SUCCEEDED"
FAILED_RETRYABLE = "FAILED_RETRYABLE"
FAILED_FINAL = "FAILED_FINAL"
CANCELLED = "CANCELLED"
VALID_STATUSES = frozenset({
    PLANNED, RUNNING, WAITING_USER, SUCCEEDED,
    FAILED_RETRYABLE, FAILED_FINAL, CANCELLED,
})

# Stable step codes (never free text / page copy).
INTENT = "INTENT"
ONTOLOGY = "ONTOLOGY"
PLAN = "PLAN"
QUERY = "QUERY"
ANALYZE = "ANALYZE"
DELIVER = "DELIVER"
WAIT_USER = "WAIT_USER"
VALID_STEPS = frozenset({
    INTENT, ONTOLOGY, PLAN, QUERY, ANALYZE, DELIVER, WAIT_USER,
})

# Recovery-level stable error codes.  Tool-level codes (TOOL_TIMEOUT,
# TOOL_EXECUTION_ERROR, TOOL_CANCELLED, STALE_TOOL_RESULT) come from
# bi_agent.tool_runtime and are reused verbatim.
INTERRUPTED_DURING_EXECUTION = "INTERRUPTED_DURING_EXECUTION"
RECOVERY_NOT_RETRYABLE = "RECOVERY_NOT_RETRYABLE"
RECOVERY_INPUT_MISSING = "RECOVERY_INPUT_MISSING"
RETRY_EXHAUSTED = "RETRY_EXHAUSTED"

# Persisted-state limits (bounded, defensive).
_MAX_TURN_REF = 64
_MAX_ERROR_CODE = 64
_MAX_DIGEST = 128
_MAX_REF = 256
_MAX_STEP_TEXT = 512
_MAX_OPTIONS = 50
_MAX_OPTION_TEXT = 300
_MAX_TOOL_USE_ID = 128


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _bounded(value: Any, limit: int) -> str:
    text = str(value or "")
    return text[:limit]


def input_digest(params: Any) -> str:
    """Canonical SHA-256 digest of a tool-call parameter object."""
    return hashlib.sha256(canonical_input(params).encode("utf-8")).hexdigest()


def _sanitize_checkpoint(raw: Any) -> Optional[dict[str, Any]]:
    """Return a bounded, whitelisted checkpoint dict (or None)."""
    if not isinstance(raw, dict):
        return None
    step = str(raw.get("step") or "")
    if step not in VALID_STEPS:
        return None
    return {
        "checkpoint_id": _bounded(raw.get("checkpoint_id"), 64) or uuid.uuid4().hex,
        "turn_ref": _bounded(raw.get("turn_ref"), _MAX_TURN_REF),
        "step": step,
        "input_digest": _bounded(raw.get("input_digest"), _MAX_DIGEST),
        "execution_id": _bounded(raw.get("execution_id"), 64),
        "tool_use_id": _bounded(raw.get("tool_use_id"), _MAX_TOOL_USE_ID),
        "attempt": int(raw.get("attempt") or 1) if isinstance(raw.get("attempt"), int) else 1,
        "result_ref": _bounded(raw.get("result_ref"), _MAX_REF),
        "retryable": bool(raw.get("retryable")),
        "created_at": _bounded(raw.get("created_at"), 64) or _utcnow(),
    }


def _sanitize_pending_user(raw: Any) -> Optional[dict[str, Any]]:
    """Return a bounded pending-user payload or None."""
    if not isinstance(raw, dict):
        return None
    tool_use_id = str(raw.get("tool_use_id") or "").strip()
    if not tool_use_id:
        return None
    question = _bounded(raw.get("question"), _MAX_STEP_TEXT)
    options = []
    raw_options = raw.get("options")
    if isinstance(raw_options, list):
        for item in raw_options[: _MAX_OPTIONS]:
            if isinstance(item, dict):
                options.append({
                    "id": _bounded(item.get("id"), 128),
                    "label": _bounded(item.get("label"), _MAX_OPTION_TEXT),
                })
            elif item is not None:
                text = str(item)[: _MAX_OPTION_TEXT]
                options.append({"id": text, "label": text})
    return {
        "tool_use_id": _bounded(tool_use_id, 128),
        "question": question,
        "options": options,
    }


def _base_state(status: str, *, turn_ref: str = "") -> dict[str, Any]:
    return {
        "recovery_version": RECOVERY_VERSION,
        "turn_ref": turn_ref,
        "status": status,
        "current_step": INTENT if status == PLANNED else INTENT,
        "attempt": 0 if status == PLANNED else 1,
        "retryable": False,
        "error_code": "",
        "last_checkpoint": None,
        "pending_user": None,
        "updated_at": _utcnow(),
    }


def initial_recovery_state() -> dict[str, Any]:
    """Fresh-session recovery state: PLANNED, no turn, no checkpoint."""
    return _base_state(PLANNED)


def normalize_recovery_state(raw: Any) -> dict[str, Any]:
    """Normalize an arbitrary (possibly legacy/malformed) recovery payload.

    * missing/invalid input  -> safe PLANNED state;
    * ``RUNNING`` snapshots  -> the process lost that execution, so the state
      is downgraded to ``FAILED_RETRYABLE/INTERRUPTED_DURING_EXECUTION``;
    * unknown status/step/fields are dropped or reset to safe defaults;
    * every persisted string is bounded; no object injection survives.
    """
    if not isinstance(raw, dict):
        return _base_state(PLANNED)
    status = str(raw.get("status") or "")
    if status not in VALID_STATUSES:
        status = PLANNED
    state = _base_state(status)
    state["recovery_version"] = RECOVERY_VERSION
    state["turn_ref"] = _bounded(raw.get("turn_ref"), _MAX_TURN_REF)
    step = str(raw.get("current_step") or "")
    if step in VALID_STEPS:
        state["current_step"] = step
    attempt = raw.get("attempt")
    state["attempt"] = int(attempt) if isinstance(attempt, int) and attempt >= 0 else state["attempt"]
    state["retryable"] = bool(raw.get("retryable")) if status == FAILED_RETRYABLE else False
    if status != FAILED_RETRYABLE:
        state["retryable"] = False
    state["error_code"] = _bounded(raw.get("error_code"), _MAX_ERROR_CODE)
    state["last_checkpoint"] = _sanitize_checkpoint(raw.get("last_checkpoint"))
    state["pending_user"] = _sanitize_pending_user(raw.get("pending_user"))
    # A snapshot whose process is gone must never restore as "still running".
    if status == RUNNING:
        state["status"] = FAILED_RETRYABLE
        state["retryable"] = True
        state["error_code"] = (
            state["error_code"] or INTERRUPTED_DURING_EXECUTION
        )
        if state["error_code"] in {"", "TOOL_TIMEOUT"}:
            state["error_code"] = INTERRUPTED_DURING_EXECUTION
        state["pending_user"] = None
    # Terminal / waiting states never keep a stale retryable flag.
    if status in (SUCCEEDED, FAILED_FINAL, CANCELLED):
        state["retryable"] = False
    if status == WAITING_USER and state["pending_user"] is None:
        # WAITING_USER without a valid pending payload is not resumable.
        state["status"] = PLANNED
        state["current_step"] = INTENT
        state["attempt"] = 0
    state["updated_at"] = _bounded(raw.get("updated_at"), 64) or _utcnow()
    return state


class RecoveryState:
    """Session-scoped, lock-protected recovery bookkeeping.

    Every public transition mutates internal state under ``self._lock`` and
    returns the *new* defensive snapshot (or ``None`` when the transition is
    not legal).  Terminal states are immutable: late results cannot rewrite a
    ``SUCCEEDED``/``FAILED_FINAL``/``CANCELLED`` state.
    """

    def __init__(self, initial: Any = None) -> None:
        self._lock = threading.RLock()
        self._state = normalize_recovery_state(initial)

    # --- read ----------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._state)

    def status(self) -> str:
        with self._lock:
            return str(self._state["status"])

    def _commit(self, state: dict[str, Any]) -> dict[str, Any]:
        state["updated_at"] = _utcnow()
        self._state = state
        return copy.deepcopy(state)

    # --- transitions ---------------------------------------------------

    def start_turn(self, turn_ref: str) -> dict[str, Any]:
        """Begin a fresh recovery turn from PLANNED or any terminal state."""
        with self._lock:
            state = _base_state(RUNNING, turn_ref=_bounded(turn_ref, _MAX_TURN_REF))
            state["attempt"] = 1
            state["current_step"] = INTENT
            return self._commit(state)

    def resume_after_user_choice(self) -> Optional[dict[str, Any]]:
        """WAITING_USER -> RUNNING after a valid user choice."""
        with self._lock:
            if self._state["status"] != WAITING_USER:
                return None
            state = copy.deepcopy(self._state)
            state["status"] = RUNNING
            state["current_step"] = INTENT
            state["retryable"] = False
            state["error_code"] = ""
            state["pending_user"] = None
            return self._commit(state)

    def ask_user(
        self,
        tool_use_id: str,
        question: Any,
        options: Any,
    ) -> Optional[dict[str, Any]]:
        """RUNNING -> WAITING_USER; stores bounded pending-user info."""
        with self._lock:
            if self._state["status"] != RUNNING:
                return None
            state = copy.deepcopy(self._state)
            state["status"] = WAITING_USER
            state["current_step"] = WAIT_USER
            state["retryable"] = False
            state["error_code"] = ""
            state["pending_user"] = _sanitize_pending_user({
                "tool_use_id": tool_use_id,
                "question": question,
                "options": options,
            })
            return self._commit(state)

    def tool_success(
        self,
        step: str,
        *,
        execution_id: Optional[str],
        attempt: int,
        input_digest_value: str,
        result_ref: str,
        tool_use_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Confirm one tool result: keep RUNNING and rotate the checkpoint."""
        with self._lock:
            if self._state["status"] != RUNNING:
                return None
            state = copy.deepcopy(self._state)
            state["current_step"] = step if step in VALID_STEPS else state["current_step"]
            state["attempt"] = max(1, int(attempt or 0))
            state["retryable"] = False
            state["error_code"] = ""
            state["last_checkpoint"] = _make_checkpoint(
                step,
                turn_ref=state["turn_ref"],
                execution_id=execution_id,
                attempt=state["attempt"],
                input_digest_value=input_digest_value,
                result_ref=result_ref,
                retryable=True,
                tool_use_id=tool_use_id,
            )
            return self._commit(state)

    def tool_terminal(
        self,
        status: str,
        *,
        step: str,
        error_code: str,
        retryable: bool,
        execution_id: Optional[str],
        attempt: int,
        input_digest_value: str,
        tool_use_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Map a structured tool outcome to a terminal recovery state.

        A retryable failure whose attempt already reached the explicit-retry
        ceiling escalates to ``FAILED_FINAL/RETRY_EXHAUSTED``.
        """
        with self._lock:
            if self._state["status"] != RUNNING:
                return None
            state = copy.deepcopy(self._state)
            effective_status = status
            effective_code = error_code or ""
            effective_retryable = bool(retryable)
            if (
                status == FAILED_RETRYABLE
                and int(attempt or 0) >= MAX_RECOVERY_ATTEMPTS
            ):
                effective_status = FAILED_FINAL
                effective_code = RETRY_EXHAUSTED
                effective_retryable = False
            state["status"] = effective_status
            state["current_step"] = step if step in VALID_STEPS else state["current_step"]
            state["attempt"] = max(1, int(attempt or state["attempt"]))
            state["retryable"] = effective_retryable
            state["error_code"] = _bounded(effective_code, _MAX_ERROR_CODE)
            if effective_status == CANCELLED:
                state["pending_user"] = None
                state["last_checkpoint"] = None
            else:
                state["last_checkpoint"] = _make_checkpoint(
                    state["current_step"],
                    turn_ref=state["turn_ref"],
                    execution_id=execution_id,
                    attempt=state["attempt"],
                    input_digest_value=input_digest_value,
                    result_ref="",
                    retryable=effective_retryable,
                    tool_use_id=tool_use_id,
                )
            return self._commit(state)

    def mark_unrecoverable(
        self,
        *,
        error_code: str = RECOVERY_INPUT_MISSING,
    ) -> Optional[dict[str, Any]]:
        """Terminalize a FAILED_RETRYABLE state whose replay input cannot be
        rebuilt (restore-time degradation).  The turn is closed as
        ``FAILED_FINAL`` so it can never linger as a fake-retryable state.
        """
        with self._lock:
            if self._state["status"] != FAILED_RETRYABLE:
                return None
            state = copy.deepcopy(self._state)
            state["status"] = FAILED_FINAL
            state["retryable"] = False
            state["error_code"] = _bounded(error_code, _MAX_ERROR_CODE)
            state["pending_user"] = None
            return self._commit(state)

    def begin_retry(
        self,
        expected_tool_use_id: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[dict[str, Any]]]:
        """Explicit retry gate: FAILED_RETRYABLE -> RUNNING (or exhausted).

        The retry is only legal when the checkpoint carries a ``tool_use_id``
        and (when supplied) that id matches the replay descriptor WebSession
        rebuilt.  A retryable state without a locatable replay input is
        degraded to ``FAILED_FINAL/RECOVERY_INPUT_MISSING`` *before* any
        ``RUNNING`` transition, so the caller can never be stuck in RUNNING
        with nothing to execute.

        Returns ``(error_code, new_snapshot)``.  ``error_code`` is empty when
        the retry may proceed; otherwise the state moved to
        a terminal state and the caller must not re-execute.
        """
        with self._lock:
            if self._state["status"] != FAILED_RETRYABLE:
                return RECOVERY_NOT_RETRYABLE, None
            checkpoint = self._state.get("last_checkpoint")
            checkpoint_id = (
                str(checkpoint.get("tool_use_id") or "")
                if isinstance(checkpoint, dict) else ""
            )
            if not checkpoint_id or (
                expected_tool_use_id is not None
                and checkpoint_id != str(expected_tool_use_id)
            ):
                # The persisted checkpoint cannot be replayed from the current
                # conversation messages: close the turn instead of pretending
                # it is retryable.
                state = copy.deepcopy(self._state)
                state["status"] = FAILED_FINAL
                state["retryable"] = False
                state["error_code"] = _bounded(
                    RECOVERY_INPUT_MISSING, _MAX_ERROR_CODE
                )
                state["pending_user"] = None
                return RECOVERY_NOT_RETRYABLE, self._commit(state)
            if int(self._state["attempt"] or 0) >= MAX_RECOVERY_ATTEMPTS:
                state = copy.deepcopy(self._state)
                state["status"] = FAILED_FINAL
                state["retryable"] = False
                state["error_code"] = RETRY_EXHAUSTED
                return RETRY_EXHAUSTED, self._commit(state)
            state = copy.deepcopy(self._state)
            state["status"] = RUNNING
            state["retryable"] = False
            state["error_code"] = ""
            step = state["current_step"]
            state["current_step"] = step if step in VALID_STEPS else INTENT
            return "", self._commit(state)

    def mark_succeeded(self, attempt: int) -> Optional[dict[str, Any]]:
        """RUNNING -> SUCCEEDED with a DELIVER checkpoint."""
        with self._lock:
            if self._state["status"] != RUNNING:
                return None
            state = copy.deepcopy(self._state)
            state["status"] = SUCCEEDED
            state["current_step"] = DELIVER
            state["attempt"] = max(1, int(attempt or state["attempt"]))
            state["retryable"] = False
            state["error_code"] = ""
            state["pending_user"] = None
            state["last_checkpoint"] = _make_checkpoint(
                DELIVER,
                turn_ref=state["turn_ref"],
                execution_id="",
                attempt=state["attempt"],
                input_digest_value="",
                result_ref="",
                retryable=True,
                tool_use_id="",
            )
            return self._commit(state)


def _make_checkpoint(
    step: str,
    *,
    turn_ref: str,
    execution_id: Optional[str],
    attempt: int,
    input_digest_value: str,
    result_ref: str,
    retryable: bool,
    tool_use_id: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "checkpoint_id": uuid.uuid4().hex,
        "turn_ref": _bounded(turn_ref, _MAX_TURN_REF),
        "step": step,
        "input_digest": _bounded(input_digest_value, _MAX_DIGEST),
        "execution_id": _bounded(execution_id or "", 64),
        "tool_use_id": _bounded(tool_use_id or "", _MAX_TOOL_USE_ID),
        "attempt": max(1, int(attempt or 0)),
        "result_ref": _bounded(result_ref, _MAX_REF),
        "retryable": bool(retryable),
        "created_at": _utcnow(),
    }
