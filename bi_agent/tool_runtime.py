"""Tool execution boundary for the analysis agent (phase 1, in-process).

This module owns the per-session tool execution bookkeeping that used to be
scattered through ``WebSession``'s tool loop:

* one ``execution_id`` per logically accepted tool call (UUID, never equal to
  the model's ``tool_use_id``);
* deterministic turn-scoped idempotency keys so duplicated deliveries never
  start a second executor;
* an immutable terminal state machine
  ``PENDING -> RUNNING -> {SUCCEEDED, FAILED, CANCELLED, TIMED_OUT}``;
* bounded, daemon background execution with a per-tool timeout; tasks that
  time out while still queued are discarded before their executor starts;
* a stale-result commit gate re-checked atomically with the terminal CAS;
* sanitized, bounded audit snapshots that never store raw credentials,
  tracebacks or unbounded tool results, while the full successful business
  result is still returned intact to WebSession.

The module deliberately does not import ``bi_agent.web.session`` (the session
layer imports this module): turn ownership is described by the small frozen
``ToolTurnScope`` value object below.
"""

from __future__ import annotations

import hashlib
import json
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

from .concurrency import (
    ResourceCancelled,
    clear_current_cancel,
    set_current_cancel,
)


# ---------------------------------------------------------------------------
# Stable machine codes / states
# ---------------------------------------------------------------------------


class ToolExecutionStatus(str, Enum):
    """States of one tool execution record."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


# Stable error codes (see spec section 10).
TOOL_TIMEOUT = "TOOL_TIMEOUT"
TOOL_CANCELLED = "TOOL_CANCELLED"
STALE_TOOL_RESULT = "STALE_TOOL_RESULT"
TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"

_DEFAULT_TOOL_TIMEOUT_SECONDS = 60.0
_MAX_ERROR_MESSAGE_CHARS = 400
_MAX_CONCURRENT_TOOL_WORKERS = 8


# ---------------------------------------------------------------------------
# Canonical serialization + security helpers
# ---------------------------------------------------------------------------


def _canonical(value: Any) -> Any:
    """Recursively normalize a value for stable serialization.

    Dict keys are sorted (compared as strings); tuples become lists; every
    other scalar is either kept as a JSON primitive or stringified.
    """
    if isinstance(value, dict):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def canonical_input(params: Any) -> str:
    """Return the canonical JSON text of a tool-call parameter object."""
    return json.dumps(
        _canonical(params),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_CREDENTIAL_FIELD_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|authorization|"
    r"access[_-]?key|api[_-]?key|credential|private[_-]?key)\b"
    r"(\s*[=:]\s*)(\S+)"
)
_BEARER_RE = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]+")


def sanitize_error_message(message: Any, limit: int = _MAX_ERROR_MESSAGE_CHARS) -> str:
    """Return a bounded, credential-free human-readable error summary.

    Tracebacks are never captured by the boundary; this function additionally
    strips anything that looks like a credential assignment (``token=...``,
    ``password: ...``, ``Authorization: Bearer ...``) and caps the length.
    """
    text = str(message or "").strip() or "tool execution failed"
    text = _CREDENTIAL_FIELD_RE.sub(r"\1\2[REDACTED]", text)
    text = _BEARER_RE.sub(r"\1[REDACTED]", text)
    # A stray traceback fragment must never leak into the audit.
    text = re.sub(r"(?s)Traceback \(most recent call last\).*", "[traceback omitted]", text)
    if len(text) > limit:
        text = text[:limit].rstrip() + "..."
    return text


def bounded_result_ref(output: Any) -> str:
    """Bound the audit's view of a tool result to a digest + length."""
    text = str(output)
    return f"sha256:{_sha256(text)} chars={len(text)}"


# ---------------------------------------------------------------------------
# Frozen turn identity handed from WebSession to the ledger
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolTurnScope:
    """Ownership identity captured for one turn.

    ``turn_ref`` and ``generation`` identify the idempotency scope; ``cancel``
    and ``is_current`` let the runtime gate stale results after the executor
    returns.  When no web ``TurnContext`` exists (direct local calls) the
    scope is a per-session local counter and no stale gate applies.
    """

    turn_ref: str
    generation: Optional[int] = None
    cancel: Optional[threading.Event] = None
    is_current: Optional[Callable[[], bool]] = None


def _scope_superseded(scope: ToolTurnScope) -> bool:
    """True when the owning turn must no longer accept this execution."""
    if scope is None:
        return False
    if scope.cancel is not None and scope.cancel.is_set():
        return True
    if scope.is_current is not None:
        try:
            if not scope.is_current():
                return True
        except Exception:
            return True
    return False


# ---------------------------------------------------------------------------
# Bounded daemon worker pool
# ---------------------------------------------------------------------------


class _DaemonToolPool:
    """Process-wide pool of daemon worker threads for tool executors.

    Daemon threads never block interpreter shutdown (spec 7.1), and the worker
    count is bounded so hung third-party calls cannot create unbounded
    threads.  The pool intentionally does not pretend to force-kill a blocked
    executor — a late return simply loses its commit rights.
    """

    def __init__(self, max_workers: int = _MAX_CONCURRENT_TOOL_WORKERS) -> None:
        self._max_workers = max(1, int(max_workers))
        self._queue: "queue.Queue[Optional[Callable[[], None]]]" = queue.Queue()
        self._workers: list[threading.Thread] = []
        self._lock = threading.Lock()

    def _ensure_started(self) -> None:
        with self._lock:
            while len(self._workers) < self._max_workers:
                thread = threading.Thread(
                    target=self._worker_loop,
                    name=f"tool-runtime-{len(self._workers) + 1}",
                    daemon=True,
                )
                thread.start()
                self._workers.append(thread)

    def _worker_loop(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                return
            try:
                task()
            except BaseException:  # pragma: no cover - defensive only
                # A task must never kill the shared worker; executor failures
                # are captured by the task closure itself.
                pass

    def submit(self, task: Callable[[], None]) -> None:
        """Run ``task`` on a bounded daemon worker as soon as one is free."""
        self._ensure_started()
        self._queue.put(task)


_pool: Optional[_DaemonToolPool] = None
_pool_lock = threading.Lock()


def _get_pool() -> _DaemonToolPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = _DaemonToolPool()
    return _pool


# ---------------------------------------------------------------------------
# Execution record + outcome
# ---------------------------------------------------------------------------


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ToolExecutionRecord:
    """Mutable in-memory bookkeeping row (protected by the ledger lock)."""

    execution_id: str
    idempotency_key: str
    session_scope: str
    turn_scope: str
    generation: Optional[int]
    tool_use_id: str
    tool_name: str
    input_digest: str
    status: str = ToolExecutionStatus.PENDING.value
    attempt: int = 0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_ms: int = -1
    error_code: str = ""
    error_message: str = ""
    retryable: bool = False
    result_ref: str = ""
    # Transient internals — never serialized into the audit snapshot.  The
    # full successful business result is held in memory so WebSession receives
    # exactly what the executor returned and duplicate deliveries can reuse it;
    # the audit only ever sees ``result_ref`` (digest + length).
    _started_mono: Optional[float] = field(default=None, repr=False)
    _done: threading.Event = field(default_factory=threading.Event, repr=False)
    _business_output: Optional[str] = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """Public defensive copy of one audit record."""
        return {
            "execution_id": self.execution_id,
            "idempotency_key": self.idempotency_key,
            "session_scope": self.session_scope,
            "turn_scope": self.turn_scope,
            "generation": self.generation,
            "tool_use_id": self.tool_use_id,
            "tool_name": self.tool_name,
            "input_digest": self.input_digest,
            "status": str(self.status),
            "attempt": self.attempt,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "retryable": self.retryable,
            "result_ref": self.result_ref,
        }


@dataclass
class ToolExecutionOutcome:
    """What the boundary tells the session layer about one tool call."""

    status: str
    execution_id: Optional[str] = None
    attempt: int = 0
    output: Optional[str] = None
    suppressed: bool = False
    error_code: str = ""
    error_message: str = ""
    retryable: bool = False
    reused: bool = False
    tool_name: str = ""
    tool_use_id: str = ""


# ---------------------------------------------------------------------------
# Session ledger
# ---------------------------------------------------------------------------


class ToolExecutionLedger:
    """Session-scoped execution ledger.

    ``execute()`` is the single entry point used by both WebSession tool paths
    (pre-AskUser siblings and the normal tool loop).  All state transitions
    are serialized under ``self._lock``; terminal states are immutable.
    """

    def __init__(
        self,
        session_scope: str,
        *,
        default_timeout: float = _DEFAULT_TOOL_TIMEOUT_SECONDS,
        tool_timeouts: Optional[dict[str, float]] = None,
        pool: Optional[_DaemonToolPool] = None,
    ) -> None:
        self.session_scope = str(session_scope)
        self.default_timeout = max(0.0, float(default_timeout))
        self._tool_timeouts = {
            str(name): max(0.0, float(seconds))
            for name, seconds in (tool_timeouts or {}).items()
        }
        self._pool = pool if pool is not None else _get_pool()
        self._lock = threading.RLock()
        self._records: list[ToolExecutionRecord] = []
        self._by_key: dict[str, ToolExecutionRecord] = {}

    # --- public ---------------------------------------------------------

    def timeout_for(self, tool_name: str) -> float:
        return self._tool_timeouts.get(str(tool_name), self.default_timeout)

    def snapshot(self) -> list[dict[str, Any]]:
        """Read-only audit snapshot in creation order (fresh defensive copy)."""
        with self._lock:
            return [record.to_dict() for record in self._records]

    def execute(
        self,
        *,
        scope: ToolTurnScope,
        tool_use_id: str,
        tool_name: str,
        params: Any,
        invoke: Callable[[], str],
    ) -> ToolExecutionOutcome:
        """Accept one logical tool call and run it exactly once per key.

        ``invoke`` is executed on a bounded daemon worker; the caller waits at
        most ``timeout_for(tool_name)`` seconds and receives a structured
        outcome.  Duplicate deliveries reuse the first result; failed /
        timed-out / cancelled terminals never implicitly retry.
        """
        timeout = self.timeout_for(tool_name)
        key = idempotency_key(
            session_scope=self.session_scope,
            scope=scope,
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            params=params,
        )
        with self._lock:
            record = self._by_key.get(key)
            fresh = record is None
            if fresh:
                record = ToolExecutionRecord(
                    execution_id=str(uuid.uuid4()),
                    idempotency_key=key,
                    session_scope=self.session_scope,
                    turn_scope=scope.turn_ref if scope is not None else "",
                    generation=scope.generation if scope is not None else None,
                    tool_use_id=str(tool_use_id or ""),
                    tool_name=str(tool_name or ""),
                    input_digest=_sha256(canonical_input(params)),
                )
                self._records.append(record)
                self._by_key[key] = record

        if not fresh:
            duplicate = self._snapshot_outcome(record)
            if duplicate is not None:
                return duplicate

        # First real acceptance: PENDING -> RUNNING (or pre-start cancel).
        with self._lock:
            if record.status != ToolExecutionStatus.PENDING.value:
                return self._outcome_locked(record)
            record.status = ToolExecutionStatus.RUNNING.value
            record.attempt = 1
            record.started_at = _utcnow()
            record._started_mono = time.monotonic()
            if _scope_superseded(scope):
                self._finalize_locked(
                    record,
                    ToolExecutionStatus.CANCELLED,
                    error_code=TOOL_CANCELLED,
                    error_message="tool call was cancelled before it started",
                    retryable=True,
                )
                return self._outcome_locked(record)

        self._pool.submit(
            lambda: self._run_on_worker(record, scope, invoke)
        )
        self._wait_for_completion(record, scope, timeout)
        with self._lock:
            return self._outcome_locked(record)

    # --- internals ------------------------------------------------------

    def _snapshot_outcome(self, record: ToolExecutionRecord) -> Optional[ToolExecutionOutcome]:
        """Duplicate-delivery handling for an existing record."""
        with self._lock:
            status = record.status
        if status in (
            ToolExecutionStatus.PENDING.value,
            ToolExecutionStatus.RUNNING.value,
        ):
            # A concurrent duplicate: never start a second executor.  The
            # sequential session loop cannot normally reach this branch;
            # wait for the in-flight run (outside the lock) and reuse
            # whatever it produced.
            record._done.wait(self.timeout_for(record.tool_name))
            with self._lock:
                if record.status == ToolExecutionStatus.RUNNING.value:
                    # The other execution is still in flight past our own
                    # budget: report a timeout for THIS caller without
                    # touching the shared terminal state.
                    return ToolExecutionOutcome(
                        status=ToolExecutionStatus.TIMED_OUT.value,
                        execution_id=record.execution_id,
                        attempt=record.attempt,
                        error_code=TOOL_TIMEOUT,
                        retryable=True,
                        tool_name=record.tool_name,
                        tool_use_id=record.tool_use_id,
                    )
                return self._outcome_locked(record)
        if status == ToolExecutionStatus.SUCCEEDED.value:
            return ToolExecutionOutcome(
                status=status,
                execution_id=record.execution_id,
                attempt=record.attempt,
                output=record._business_output,
                error_code=record.error_code,
                error_message=record.error_message,
                retryable=record.retryable,
                reused=True,
                tool_name=record.tool_name,
                tool_use_id=record.tool_use_id,
            )
        # FAILED / TIMED_OUT / CANCELLED: ordinary re-delivery must not
        # implicitly retry (spec 5).
        return ToolExecutionOutcome(
            status=status,
            execution_id=record.execution_id,
            attempt=record.attempt,
            output=self._legacy_failure_text(record),
            error_code=record.error_code,
            error_message=record.error_message,
            retryable=record.retryable,
            reused=True,
            tool_name=record.tool_name,
            tool_use_id=record.tool_use_id,
        )

    def _run_on_worker(
        self,
        record: ToolExecutionRecord,
        scope: ToolTurnScope,
        invoke: Callable[[], str],
    ) -> None:
        """Run the executor on a bounded daemon worker and settle the record."""
        # Pre-flight check under the ledger lock: a task that waited in the pool
        # queue while the caller already timed out or cancelled the turn (or the
        # turn was superseded) is discarded BEFORE invoking the executor, so an
        # invalid Doris/ontology/other call never starts.  The caller
        # finalizes timeouts/cancellation under the same lock, so this check is
        # atomic with respect to that transition: whichever side acquires the
        # lock first decides whether the executor may legally start.
        with self._lock:
            if record.status != ToolExecutionStatus.RUNNING.value:
                return
            if _scope_superseded(scope):
                self._finalize_locked(
                    record,
                    ToolExecutionStatus.CANCELLED,
                    error_code=TOOL_CANCELLED,
                    error_message=(
                        "tool call was cancelled before the worker started it"
                    ),
                    retryable=True,
                )
                return
        set_current_cancel(scope.cancel if scope is not None else None)
        try:
            try:
                output = invoke()
            except ResourceCancelled:
                output = None
                error: Optional[BaseException] = ResourceCancelled()
            except BaseException as exc:
                output = None
                error = exc
            else:
                error = None
            self._settle_from_worker(record, scope, output, error)
        finally:
            clear_current_cancel()
            record._done.set()

    def _settle_from_worker(
        self,
        record: ToolExecutionRecord,
        scope: ToolTurnScope,
        output: Optional[str],
        error: Optional[BaseException],
    ) -> None:
        with self._lock:
            if record.status != ToolExecutionStatus.RUNNING.value:
                # Already terminal (e.g. TIMED_OUT / CANCELLED by the caller):
                # a late success/failure must never rewrite it.
                return
            if _scope_superseded(scope):
                self._finalize_locked(
                    record,
                    ToolExecutionStatus.CANCELLED,
                    error_code=STALE_TOOL_RESULT,
                    error_message="tool returned after its turn was superseded",
                    retryable=True,
                )
                return
            if error is not None:
                if isinstance(error, ResourceCancelled):
                    self._finalize_locked(
                        record,
                        ToolExecutionStatus.CANCELLED,
                        error_code=TOOL_CANCELLED,
                        error_message="tool execution was cancelled while waiting",
                        retryable=True,
                    )
                else:
                    self._finalize_locked(
                        record,
                        ToolExecutionStatus.FAILED,
                        error_code=TOOL_EXECUTION_ERROR,
                        error_message=sanitize_error_message(str(error)),
                        retryable=False,
                    )
                return
            self._finalize_locked(
                record,
                ToolExecutionStatus.SUCCEEDED,
                output=output,
            )

    def _wait_for_completion(
        self,
        record: ToolExecutionRecord,
        scope: ToolTurnScope,
        timeout: float,
    ) -> None:
        """Wait for the worker, honoring the per-tool timeout and the turn's
        cancellation so a superseded turn never blocks until the timeout."""
        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                with self._lock:
                    if record.status == ToolExecutionStatus.RUNNING.value:
                        self._finalize_locked(
                            record,
                            ToolExecutionStatus.TIMED_OUT,
                            error_code=TOOL_TIMEOUT,
                            error_message=(
                                f"{record.tool_name} did not finish within "
                                f"{timeout:g}s"
                            ),
                            retryable=True,
                        )
                return
            if record._done.wait(min(remaining, 0.05)):
                return
            if _scope_superseded(scope):
                with self._lock:
                    if record.status == ToolExecutionStatus.RUNNING.value:
                        self._finalize_locked(
                            record,
                            ToolExecutionStatus.CANCELLED,
                            error_code=STALE_TOOL_RESULT,
                            error_message=(
                                "turn superseded while the tool was running"
                            ),
                            retryable=True,
                        )
                return

    def _finalize_locked(
        self,
        record: ToolExecutionRecord,
        status: ToolExecutionStatus,
        *,
        error_code: str = "",
        error_message: str = "",
        retryable: bool = False,
        output: Optional[str] = None,
    ) -> None:
        """Write a terminal state.  Only call while holding ``self._lock``."""
        if record.status not in (
            ToolExecutionStatus.PENDING.value,
            ToolExecutionStatus.RUNNING.value,
        ):
            return
        record.status = status.value
        record.finished_at = _utcnow()
        if record._started_mono is not None:
            record.duration_ms = max(
                0, int((time.monotonic() - record._started_mono) * 1000)
            )
        else:
            record.duration_ms = 0
        record.error_code = error_code
        record.error_message = sanitize_error_message(error_message)
        record.retryable = bool(retryable)
        if output is not None:
            text = str(output)
            record._business_output = text
            record.result_ref = bounded_result_ref(text)
        record._done.set()

    def _outcome_locked(self, record: ToolExecutionRecord) -> ToolExecutionOutcome:
        """Build the outcome from a settled record (caller holds the lock)."""
        status = record.status
        if status == ToolExecutionStatus.SUCCEEDED.value:
            output: Optional[str] = record._business_output
        else:
            output = self._legacy_failure_text(record)
        return ToolExecutionOutcome(
            status=status,
            execution_id=record.execution_id,
            attempt=record.attempt,
            output=output,
            error_code=record.error_code,
            error_message=record.error_message,
            retryable=record.retryable,
            tool_name=record.tool_name,
            tool_use_id=record.tool_use_id,
        )

    @staticmethod
    def _legacy_failure_text(record: ToolExecutionRecord) -> str:
        """LLM/UI compatible error string for non-successful outcomes."""
        code = record.error_code or str(record.status)
        message = sanitize_error_message(record.error_message)
        return f"Error executing {record.tool_name}: {message} ({code})"


def idempotency_key(
    *,
    session_scope: str,
    scope: ToolTurnScope,
    tool_use_id: str,
    tool_name: str,
    params: Any,
) -> str:
    """Deterministic identity of one logical tool call.

    Exact composition: SHA-256 over the canonical JSON of
    ``{session scope, turn scope, generation, tool_use_id, tool_name,
    canonical input}``.  Parameter key order does not matter; a different
    turn/generation never reuses an old result.
    """
    payload = json.dumps(
        {
            "session_scope": str(session_scope),
            "turn_scope": str(scope.turn_ref if scope is not None else ""),
            "generation": scope.generation if scope is not None else None,
            "tool_use_id": str(tool_use_id or ""),
            "tool_name": str(tool_name or ""),
            "input": _canonical(params),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return _sha256(payload)
