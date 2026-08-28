"""First-phase concurrency governance for ChatBI.

Single-process, in-memory coordination only.  Everything here is intentionally
dependency-free (stdlib only) so both the web layer and the tool/provider
layers can import it without cycles.

Lock order (documented contract, must be respected everywhere):

    1. registry lock  (STATE.sessions / report_sessions / source_contexts)
    2. session slot lock  (per session_id + mode: busy / generation / cancel)
    3. WebSession internal state  (messages etc., mutated under the slot lock
       at commit points)
    4. conversation store lock  (never held while calling the network)

Forbidden:
    - holding the registry lock while calling LLM / Doris / ontology network
    - holding the conversation store lock while calling the network
    - waiting on a global downstream semaphore while holding a session-state
      lock (LLM / Doris / ontology semaphores are acquired without any session
      lock held)

Current phase 1 limitation: this is all in-process state, so the server MUST
run a single Uvicorn worker.  Multi-worker scaling needs shared state (Redis /
PostgreSQL), distributed locks and an event stream.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Request identity (phase 1: session_id only; user_id/tenant_id later)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RequestPrincipal:
    """Lightweight, replaceable request identity.

    Phase 1 uses session_id as the quota key.  Once a real user system lands,
    pass user_id (and tenant_id) here without changing callers.
    """

    tenant_id: str = ""
    user_id: str = ""
    session_id: str = ""

    @property
    def quota_key(self) -> str:
        return self.user_id or self.session_id or ""


# ---------------------------------------------------------------------------
# Env-derived limits
# ---------------------------------------------------------------------------


class Limits:
    """Validated, env-driven concurrency limits."""

    def __init__(self, env: Optional[dict[str, str]] = None) -> None:
        env = os.environ if env is None else env

        def positive_int(name: str, default: int) -> int:
            raw = str(env.get(name, "")).strip()
            if not raw:
                return default
            try:
                value = int(raw)
            except (TypeError, ValueError):
                raise ValueError(f"{name} must be a positive integer, got {raw!r}")
            if value <= 0:
                raise ValueError(f"{name} must be a positive integer, got {raw!r}")
            return value

        def non_negative_float(name: str, default: float) -> float:
            raw = str(env.get(name, "")).strip()
            if not raw:
                return default
            try:
                value = float(raw)
            except (TypeError, ValueError):
                raise ValueError(f"{name} must be a number of seconds, got {raw!r}")
            if value < 0:
                raise ValueError(f"{name} must be >= 0 seconds, got {raw!r}")
            return value

        self.max_active_turns = positive_int("CHATBI_MAX_ACTIVE_TURNS", 8)
        self.max_active_per_principal = positive_int("CHATBI_MAX_ACTIVE_PER_PRINCIPAL", 2)
        self.max_waiting_turns = positive_int("CHATBI_MAX_WAITING_TURNS", 32)
        self.admission_wait_seconds = non_negative_float("CHATBI_ADMISSION_WAIT_SECONDS", 2.0)
        self.llm_concurrency = positive_int("CHATBI_LLM_CONCURRENCY", 6)
        self.doris_concurrency = positive_int("CHATBI_DORIS_CONCURRENCY", 12)
        self.ontology_concurrency = positive_int("CHATBI_ONTOLOGY_CONCURRENCY", 12)
        self.session_idle_ttl_seconds = positive_int("CHATBI_SESSION_IDLE_TTL_SECONDS", 7200)
        self.max_in_memory_sessions = positive_int("CHATBI_MAX_IN_MEMORY_SESSIONS", 500)
        # Per-principal must never exceed the global active budget; the global
        # limit is the authoritative cap.
        if self.max_active_per_principal > self.max_active_turns:
            self.max_active_per_principal = self.max_active_turns

    def to_dict(self) -> dict[str, int | float]:
        return {
            "max_active_turns": self.max_active_turns,
            "max_active_per_principal": self.max_active_per_principal,
            "max_waiting_turns": self.max_waiting_turns,
            "admission_wait_seconds": self.admission_wait_seconds,
            "llm_concurrency": self.llm_concurrency,
            "doris_concurrency": self.doris_concurrency,
            "ontology_concurrency": self.ontology_concurrency,
            "session_idle_ttl_seconds": self.session_idle_ttl_seconds,
            "max_in_memory_sessions": self.max_in_memory_sessions,
        }


_limits: Optional[Limits] = None
_limits_lock = threading.Lock()


def get_limits() -> Limits:
    global _limits
    if _limits is None:
        with _limits_lock:
            if _limits is None:
                _limits = Limits()
    return _limits


def reset_limits() -> None:
    """Test hook — recreate Limits from the current environment."""
    global _limits
    with _limits_lock:
        _limits = None


# ---------------------------------------------------------------------------
# Session slot (per session_id + mode) — lease/turn-ownership model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TurnLease:
    """Single-use ownership token for one turn on a ``SessionSlot``.

    ``try_acquire()`` mints a fresh lease (new ``owner`` every time), so a
    stale lease from a superseded turn can never release a newer turn's
    ``busy``/``cancel`` state: every mutating slot API validates ``owner``
    against the slot's current owner and silently ignores mismatches.
    """

    generation: int
    owner: str


class SessionSlot:
    """Per-session turn guard + generation + cancellation + TTL bookkeeping.

    ``busy`` marks an active turn (409 SESSION_BUSY source).  ``generation``
    is bumped whenever the session is rebuilt/reset/restored so a stale turn
    can detect it was superseded.  ``cancel`` is the active turn's
    cancellation Event; reset/restore/activate set it so the old turn stops
    as soon as it checks.

    Ownership rule: a turn holds exactly one ``TurnLease`` for the duration
    of its claim.  ``bump_generation()`` invalidates the current lease AND
    frees the slot immediately, so a reset/restore/activate never blocks a
    new turn behind an in-flight LLM/Doris/ontology call.  The old turn's
    eventual ``release_turn(old_lease)`` is rejected by owner validation and
    therefore cannot clear the new turn's busy/cancel/owner state.
    """

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.busy = False
        self.generation = 0
        self.owner: Optional[str] = None
        self.cancel: Optional[threading.Event] = None
        self.last_access = time.monotonic()

    # --- turn guard ----------------------------------------------------
    def try_acquire(self, cancel_event: Optional[threading.Event] = None) -> Optional[TurnLease]:
        """Claim the slot for one turn.

        Returns a fresh, non-reusable ``TurnLease`` (current generation +
        unique owner), or None when a turn is already running (caller maps
        this to HTTP 409 SESSION_BUSY).

        ``cancel_event`` — when supplied — is bound atomically with the lease
        under ``self.lock`` and becomes the turn's ONE cancel event.  The
        admission wait, downstream resource waits and the SSE stream all
        observe this same event, so a reset/restore/activate/source-switch
        cancels the turn even while it is still queued for admission (no
        "unattached" window between slot acquisition and stream creation).
        """
        with self.lock:
            if self.busy:
                return None
            self.busy = True
            self.owner = uuid.uuid4().hex
            self.cancel = cancel_event if cancel_event is not None else threading.Event()
            self.last_access = time.monotonic()
            return TurnLease(generation=self.generation, owner=self.owner)

    @property
    def current_lease(self) -> Optional[TurnLease]:
        """The active lease, if any (used by tests/diagnostics)."""
        with self.lock:
            if self.owner is None:
                return None
            return TurnLease(generation=self.generation, owner=self.owner)

    def attach_cancel(self, lease: TurnLease, cancel: threading.Event) -> None:
        """Attach the turn's cancellation event — only valid for the owner."""
        with self.lock:
            if self.owner is not None and self.owner == lease.owner:
                self.cancel = cancel

    def release_turn(self, lease: TurnLease) -> None:
        """Release the slot, but ONLY for the current owner.

        A stale lease (from a superseded turn) is a no-op: it can never clear
        the new turn's ``busy``/``cancel``/``owner`` state.
        """
        with self.lock:
            if self.owner is None or self.owner != lease.owner:
                return
            self.busy = False
            self.owner = None
            self.cancel = None
            self.last_access = time.monotonic()

    def touch(self) -> None:
        with self.lock:
            self.last_access = time.monotonic()

    # --- supersession --------------------------------------------------
    def bump_generation(self, *, cancel_active: bool = True) -> int:
        """Invalidate any running turn AND free the slot immediately.

        Used by reset/restore/activate/source switch.  Raises generation
        (so every old lease's ``is_superseded`` becomes True), sets the old
        turn's cancel event, then clears the slot so a new turn can start
        right away — the old lease can never release the new turn thanks to
        owner validation in ``release_turn``.  Returns the new generation.
        """
        with self.lock:
            self.generation += 1
            if cancel_active and self.cancel is not None:
                self.cancel.set()
            self.busy = False
            self.owner = None
            self.cancel = None
            self.last_access = time.monotonic()
            return self.generation

    def is_superseded(self, lease: Optional[TurnLease], cancel: Optional[threading.Event]) -> bool:
        """True when this turn must stop committing.

        A turn is superseded when its cancel event fired, or when the slot
        moved on (generation bumped and/or the owner changed — i.e. a newer
        turn already holds the slot).
        """
        if cancel is not None and cancel.is_set():
            return True
        if lease is None:
            return True
        with self.lock:
            return (
                self.generation != lease.generation
                or self.owner != lease.owner
            )


class SessionSlotRegistry:
    """Map of session_key -> SessionSlot, protected by one RLock."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self._slots: dict[str, SessionSlot] = {}

    def ensure(self, key: str) -> SessionSlot:
        with self.lock:
            slot = self._slots.get(key)
            if slot is None:
                slot = SessionSlot()
                self._slots[key] = slot
            return slot

    def get(self, key: str) -> Optional[SessionSlot]:
        with self.lock:
            return self._slots.get(key)

    def snapshot(self) -> dict[str, SessionSlot]:
        with self.lock:
            return dict(self._slots)

    def remove(self, key: str) -> Optional[SessionSlot]:
        with self.lock:
            return self._slots.pop(key, None)

    def reap_idle(self, limits: Limits, now: Optional[float] = None) -> list[str]:
        """Lazily drop slots (and only memory objects — never history files).

        Returns the keys that were removed so callers can also evict the
        matching WebSession / source context from their registries."""
        now = time.monotonic() if now is None else now
        removed: list[str] = []
        with self.lock:
            for key, slot in list(self._slots.items()):
                with slot.lock:
                    if slot.busy:
                        continue
                    idle = now - slot.last_access
                    over_capacity = len(self._slots) > limits.max_in_memory_sessions
                    if idle >= limits.session_idle_ttl_seconds or over_capacity:
                        self._slots.pop(key, None)
                        removed.append(key)
        return removed


# ---------------------------------------------------------------------------
# Global admission controller
# ---------------------------------------------------------------------------


class AdmissionRejected(Exception):
    """Raised when admission is refused (maps to HTTP 429)."""

    def __init__(self, code: str, message: str, retry_after: Optional[int] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after


class AdmissionTicket:
    __slots__ = ("controller", "principal", "code")

    def __init__(self, controller: "AdmissionController", principal: RequestPrincipal, code: str) -> None:
        self.controller = controller
        self.principal = principal
        self.code = code


class _QueueEntry:
    """One waiting request in the admission FIFO.

    Object identity is the ticket: ``_remove`` removes exactly this entry,
    so a timeout/cancellation can never eject someone else's wait.
    """

    __slots__ = ("principal",)

    def __init__(self, principal: RequestPrincipal) -> None:
        self.principal = principal


class AdmissionController:
    """Bounded active/queued admission for the whole process.

    Contract:
      - active slots free AND queue empty -> immediate grant
      - active full -> bounded in-process FIFO wait (queue tickets)
      - waiting queue full -> GLOBAL_QUEUE_FULL (429)
      - per-principal active at its cap with no queue -> PRINCIPAL_CONCURRENCY_LIMIT (429)
      - wait timed out -> ADMISSION_TIMEOUT (429)
      - wait cancelled -> ADMISSION_CANCELLED
      - release must always happen in a finally block

    Fairness rules:
      - admission is FIFO: a new request can never jump an already-queued
        request that is runnable;
      - a queued head whose principal is at its per-principal cap is skipped
        so it cannot starve runnable principals behind it (it stays queued
        and re-runs as soon as its principal frees capacity).
    """

    def __init__(self, limits: Optional[Limits] = None) -> None:
        self.limits = limits or get_limits()
        self._cond = threading.Condition(threading.RLock())
        self._active_total = 0
        self._active_by_principal: dict[str, int] = {}
        self._queue: list[_QueueEntry] = []
        # Short poll so a cancelled wait is removed from the queue promptly.
        self._poll_interval = 0.1

    # --- internals -----------------------------------------------------
    def _grant(self, principal: RequestPrincipal) -> AdmissionTicket:
        self._active_total += 1
        qkey = principal.quota_key
        self._active_by_principal[qkey] = self._active_by_principal.get(qkey, 0) + 1
        return AdmissionTicket(self, principal, qkey)

    def _first_runnable(self) -> Optional[_QueueEntry]:
        """First queued entry whose principal still has capacity.

        Entries whose principal is at its cap are skipped (they stay queued)
        so a blocked head can never starve runnable principals behind it.
        """
        for entry in self._queue:
            qkey = entry.principal.quota_key
            if self._active_by_principal.get(qkey, 0) < self.limits.max_active_per_principal:
                return entry
        return None

    def _remove(self, entry: _QueueEntry) -> None:
        try:
            self._queue.remove(entry)
        except ValueError:
            pass  # already granted/removed — idempotent

    # --- public API ----------------------------------------------------
    def acquire(
        self,
        principal: RequestPrincipal,
        cancel_event: Optional[threading.Event] = None,
    ) -> AdmissionTicket:
        limits = self.limits
        qkey = principal.quota_key
        deadline = time.monotonic() + limits.admission_wait_seconds
        with self._cond:
            # Fast path: capacity free and nobody waiting. A non-empty queue
            # always keeps priority (strict FIFO), even if this principal
            # could run right now.
            if self._active_total < limits.max_active_turns and not self._queue:
                if self._active_by_principal.get(qkey, 0) < limits.max_active_per_principal:
                    return self._grant(principal)
                raise AdmissionRejected(
                    "PRINCIPAL_CONCURRENCY_LIMIT",
                    f"该身份并发已达上限（{limits.max_active_per_principal}），请稍后再试",
                    retry_after=max(1, int(limits.admission_wait_seconds)),
                )
            if len(self._queue) >= limits.max_waiting_turns:
                raise AdmissionRejected(
                    "GLOBAL_QUEUE_FULL",
                    "服务繁忙，排队已满，请稍后重试",
                    retry_after=max(1, int(limits.admission_wait_seconds)),
                )
            entry = _QueueEntry(principal)
            self._queue.append(entry)
            try:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise AdmissionRejected(
                            "ADMISSION_CANCELLED",
                            "请求已取消",
                            retry_after=None,
                        )
                    if self._active_total < limits.max_active_turns:
                        first = self._first_runnable()
                        if first is entry:
                            self._queue.remove(entry)
                            return self._grant(principal)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise AdmissionRejected(
                            "ADMISSION_TIMEOUT",
                            "服务繁忙，等待超时，请稍后重试",
                            retry_after=max(1, int(limits.admission_wait_seconds)),
                        )
                    self._cond.wait(min(remaining, self._poll_interval))
            finally:
                self._remove(entry)

    def release(self, ticket: AdmissionTicket) -> None:
        with self._cond:
            self._active_total = max(0, self._active_total - 1)
            qkey = ticket.code
            count = self._active_by_principal.get(qkey, 0)
            if count <= 1:
                self._active_by_principal.pop(qkey, None)
            else:
                self._active_by_principal[qkey] = count - 1
            self._cond.notify_all()

    def snapshot(self) -> dict[str, int]:
        with self._cond:
            return {
                "active": self._active_total,
                "waiting": len(self._queue),
            }


# ---------------------------------------------------------------------------
# Downstream resource limiters (LLM / Doris / ontology)
# ---------------------------------------------------------------------------


class ResourceCancelled(Exception):
    """Raised when a resource wait is aborted by the turn's cancel event."""


class ResourceTimeout(TimeoutError):
    """Raised when a resource wait exceeds its deadline."""


class ResourceLimiter:
    """BoundedSemaphore wrapper with cooperative cancellation + timeout.

    ``acquire`` polls the semaphore every ~100 ms, so a set ``cancel_event``
    is observed quickly even while the semaphore stays busy.  The caller must
    release the returned token in a finally block (or use it as a context
    manager).
    """

    def __init__(
        self,
        max_concurrency: int,
        name: str,
        timeout: float = 30.0,
        poll_interval: float = 0.1,
    ) -> None:
        if max_concurrency <= 0:
            raise ValueError(f"{name} concurrency must be positive")
        self.name = name
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._sem = threading.BoundedSemaphore(max_concurrency)

    def acquire(
        self,
        timeout: Optional[float] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> "_ResourceToken":
        """Acquire one slot, polling so cancellation is promptly observed.

        Raises ``ResourceCancelled`` as soon as ``cancel_event`` fires and
        ``ResourceTimeout`` once the total wait exceeds the deadline.  The
        returned token must be released in a finally block.
        """
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise ResourceCancelled(f"{self.name} 资源等待已被取消")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ResourceTimeout(f"{self.name} 资源繁忙，等待超时")
            if self._sem.acquire(timeout=min(self.poll_interval, remaining)):
                # The turn may have been cancelled in the instant between the
                # semaphore grant and this return: hand the slot back
                # immediately so a cancelled request never reaches the
                # provider/executor and capacity never leaks.
                if cancel_event is not None and cancel_event.is_set():
                    self._sem.release()
                    raise ResourceCancelled(f"{self.name} 资源等待已被取消")
                return _ResourceToken(self)

    def release(self) -> None:
        self._sem.release()

    @property
    def available(self) -> int:
        # BoundedSemaphore exposes _value; acceptable for diagnostics/tests.
        return max(0, getattr(self._sem, "_value", 0))


class _ResourceToken:
    __slots__ = ("limiter",)

    def __init__(self, limiter: ResourceLimiter) -> None:
        self.limiter = limiter

    def release(self) -> None:
        self.limiter.release()

    def __enter__(self) -> "_ResourceToken":
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


# Per-thread "current turn cancel event".  The SSE generator for a turn runs
# on a worker thread; tool executors are built once per session but the
# cancel event changes per turn, so the session layer stamps the thread-local
# right before invoking a gated executor (see WebSession._execute_tool).
_current_cancel = threading.local()


def set_current_cancel(cancel_event: Optional[threading.Event]) -> None:
    _current_cancel.event = cancel_event


def get_current_cancel() -> Optional[threading.Event]:
    return getattr(_current_cancel, "event", None)


def clear_current_cancel() -> None:
    try:
        del _current_cancel.event
    except AttributeError:
        pass


# Process-wide downstream limiters (created lazily so tests can reset them).
_llm_limiter: Optional[ResourceLimiter] = None
_doris_limiter: Optional[ResourceLimiter] = None
_ontology_limiter: Optional[ResourceLimiter] = None
_resources_lock = threading.Lock()


def _build_limiters(limits: Limits) -> None:
    global _llm_limiter, _doris_limiter, _ontology_limiter
    _llm_limiter = ResourceLimiter(limits.llm_concurrency, "llm")
    _doris_limiter = ResourceLimiter(limits.doris_concurrency, "doris")
    _ontology_limiter = ResourceLimiter(limits.ontology_concurrency, "ontology")


def get_llm_limiter() -> ResourceLimiter:
    global _llm_limiter
    if _llm_limiter is None:
        with _resources_lock:
            if _llm_limiter is None:
                _build_limiters(get_limits())
    return _llm_limiter


def get_doris_limiter() -> ResourceLimiter:
    global _doris_limiter
    if _doris_limiter is None:
        with _resources_lock:
            if _doris_limiter is None:
                _build_limiters(get_limits())
    return _doris_limiter


def get_ontology_limiter() -> ResourceLimiter:
    global _ontology_limiter
    if _ontology_limiter is None:
        with _resources_lock:
            if _ontology_limiter is None:
                _build_limiters(get_limits())
    return _ontology_limiter


def reset_resources() -> None:
    """Test hook — rebuild downstream limiters from the current environment."""
    global _llm_limiter, _doris_limiter, _ontology_limiter
    with _resources_lock:
        _llm_limiter = None
        _doris_limiter = None
        _ontology_limiter = None
