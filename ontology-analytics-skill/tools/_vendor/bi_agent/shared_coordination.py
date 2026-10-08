"""Multi-instance shared concurrency coordination (phase 3).

Phase 1/2 coordination (session slots, admission, leases) lives in a single
process.  This module adds the *shared* backend semantics that let several
workers/instances coordinate through one external store without changing the
single-instance default:

* ``InMemorySharedCoordination`` — deterministic, thread-safe in-process
  adapter implementing exactly the shared lease/admission semantics.  It is
  shared by *reference*: two registries/controllers that receive the same
  backend object see the same state.  It is NOT a per-instance dictionary.
* ``RedisSharedCoordination`` — production backend.  Every mutation is a
  single atomic ``redis.eval(...)`` (Lua) so cross-instance decisions never
  depend on a local ``threading.Lock``.
* ``build_coordination_backend`` — configuration factory with an explicit,
  observable failure policy (``closed`` vs explicit ``local`` fallback).

Design rules:
* default mode is ``local``; without a shared backend every class keeps its
  historical single-process behaviour bit-for-bit;
* session lease keys never contain credentials or free user text;
* ``fence`` is strictly monotonic per key and never resets on release/expiry;
* renew/release/heartbeat are owner+generation+fence validated;
* health and diagnostics never expose the Redis URL, passwords or session
  content (keys are reported hashed).

The module deliberately does NOT import ``bi_agent.concurrency`` at module
level (that module re-exports this one); admission state is keyed by
principal quota strings and limits are duck-typed (``max_active_turns``,
``max_active_per_principal``, ``max_waiting_turns``).
"""

from __future__ import annotations

import hashlib
import itertools
import os
import threading
import time
import uuid
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# Stable rejection payload (mapped to concurrency.AdmissionRejected by the
# controller layer so HTTP 429 codes stay unchanged).
# ---------------------------------------------------------------------------

GLOBAL_QUEUE_FULL = "GLOBAL_QUEUE_FULL"
PRINCIPAL_CONCURRENCY_LIMIT = "PRINCIPAL_CONCURRENCY_LIMIT"
ADMISSION_TIMEOUT = "ADMISSION_TIMEOUT"
ADMISSION_CANCELLED = "ADMISSION_CANCELLED"


class CoordinationRejected(Exception):
    """Shared-admission refusal; carries the stable 429 error code."""

    def __init__(
        self,
        code: str,
        message: str,
        retry_after: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_LEASE_TTL_SECONDS = 60.0
DEFAULT_ADMISSION_TICKET_TTL_SECONDS = 120.0
_ADMISSION_POLL_SECONDS = 0.05
_MAX_NAMESPACE = 64
_MAX_INSTANCE_ID = 128
_MAX_TICKET_OWNER = 64


def _utc_ms() -> int:
    return int(time.time() * 1000)


def _bounded(value: Any, limit: int) -> str:
    return str(value or "")[:limit]


def _key_hash(value: Any) -> str:
    """Short stable digest used in diagnostics (never raw user/session text)."""
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def _clock_or_time(clock: Optional[Callable[[], float]]) -> Callable[[], float]:
    return clock if clock is not None else time.time


class _LeaseState:
    """One active shared lease (internal; not exposed raw)."""

    __slots__ = ("owner", "instance_id", "generation", "fence", "expires_at")

    def __init__(
        self,
        owner: str,
        instance_id: str,
        generation: int,
        fence: int,
        expires_at: float,
    ) -> None:
        self.owner = owner
        self.instance_id = instance_id
        self.generation = generation
        self.fence = fence
        self.expires_at = expires_at

    def to_descriptor(self, key: str) -> dict[str, Any]:
        return {
            "key": key,
            "owner": self.owner,
            "instance_id": self.instance_id,
            "generation": self.generation,
            "fence": self.fence,
            "expires_at": self.expires_at,
        }


# ---------------------------------------------------------------------------
# In-memory shared coordination (deterministic test / local adapter)
# ---------------------------------------------------------------------------


class InMemorySharedCoordination:
    """Thread-safe in-process implementation of the shared semantics.

    A single backend object carries ALL shared state: two registries or two
    admission controllers that receive the same object coordinate through it.
    Supports an injectable ``clock`` for deterministic TTL tests.
    """

    def __init__(
        self,
        clock: Optional[Callable[[], float]] = None,
        *,
        namespace: str = "",
        instance_id: str = "",
        health_status: str = "local",
        lease_ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS,
    ) -> None:
        self._clock = _clock_or_time(clock)
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._namespace = _bounded(namespace, _MAX_NAMESPACE)
        self._instance_id = _bounded(instance_id, _MAX_INSTANCE_ID)
        self._lease_ttl_seconds = max(0.0, float(lease_ttl_seconds))
        # Per-key monotonic counters.  Kept even when the active lease is
        # released/expired so fence/generation never regress.
        self._counters: dict[str, dict[str, int]] = {}
        self._leases: dict[str, _LeaseState] = {}
        # Shared admission state.
        self._active_total = 0
        self._active_by_principal: dict[str, int] = {}
        self._actives: dict[str, dict[str, Any]] = {}
        self._queue: list[dict[str, Any]] = []
        self._seq = itertools.count(1)
        # "local" or "redis_degraded" (set by the failure-policy factory).
        self._health_status = str(health_status or "local")

    # --- clock / diagnostics ------------------------------------------

    def _now(self) -> float:
        return float(self._clock())

    def health(self) -> dict[str, str]:
        with self._lock:
            return {
                "status": self._health_status,
                "effective_mode": (
                    "local" if self._health_status != "redis_degraded"
                    else "local"
                ),
            }

    def snapshot(self) -> dict[str, Any]:
        """Bounded diagnostics.  Keys are hashed; no credentials/user text."""
        with self._lock:
            now = self._now()
            leases: dict[str, dict[str, Any]] = {}
            for key, state in self._leases.items():
                leases[_key_hash(key)] = {
                    "owner_hash": _key_hash(state.owner),
                    "instance_id": state.instance_id,
                    "generation": state.generation,
                    "fence": state.fence,
                    "expires_in": max(0.0, state.expires_at - now),
                }
            return {
                "leases": leases,
                "active": self._active_total,
                "queued": len(self._queue),
            }

    # --- shared session leases -----------------------------------------

    def _lease_is_live(self, state: Optional[_LeaseState], now: float) -> bool:
        return state is not None and state.expires_at > now

    def acquire_lease(
        self,
        key: str,
        owner: str,
        instance_id: str,
        ttl_seconds: Optional[float] = None,
    ) -> Optional[dict[str, Any]]:
        """Atomically acquire the lease for ``key``.

        Returns the lease descriptor or ``None`` while another owner holds a
        live lease.  A live lease owned by the same owner is returned as-is
        (no second ownership, no fence increment).  Each new ownership gets a
        strictly larger fence; counters never reset on release/expiry.
        """
        key = str(key or "")
        owner = str(owner or "")
        if not key or not owner:
            return None
        ttl = (
            max(0.0, float(ttl_seconds))
            if ttl_seconds is not None
            else self._lease_ttl_seconds
        )
        with self._lock:
            now = self._now()
            current = self._leases.get(key)
            if self._lease_is_live(current, now):
                if current.owner == owner:
                    return current.to_descriptor(key)
                return None
            counter = self._counters.get(key, {"generation": 0, "fence": 0})
            counter = {
                "generation": int(counter.get("generation") or 0) + 1,
                "fence": int(counter.get("fence") or 0) + 1,
            }
            self._counters[key] = counter
            state = _LeaseState(
                owner=owner,
                instance_id=str(instance_id or "")[: _MAX_INSTANCE_ID],
                generation=counter["generation"],
                fence=counter["fence"],
                expires_at=now + ttl,
            )
            self._leases[key] = state
            return state.to_descriptor(key)

    def renew_lease(
        self,
        key: str,
        owner: str,
        generation: int = 0,
        fence: int = 1,
        ttl_seconds: Optional[float] = None,
    ) -> bool:
        """Owner-validated renewal.  Returns False when the identity does not
        match the live lease (or the lease is gone/expired)."""
        key = str(key or "")
        owner = str(owner or "")
        if not key or not owner:
            return False
        ttl = (
            max(0.0, float(ttl_seconds))
            if ttl_seconds is not None
            else self._lease_ttl_seconds
        )
        with self._lock:
            now = self._now()
            current = self._leases.get(key)
            if not self._lease_is_live(current, now):
                return False
            if (
                current.owner != owner
                or int(current.generation) != int(generation or 0)
                or int(current.fence) != int(fence or 0)
            ):
                return False
            current.expires_at = now + ttl
            return True

    def release_lease(
        self,
        key: str,
        owner: str,
        generation: int = 0,
        fence: int = 1,
    ) -> bool:
        """Owner-validated release.  A stale owner can never delete a newer
        lease; repeated release is idempotent (False when nothing matched)."""
        key = str(key or "")
        owner = str(owner or "")
        if not key or not owner:
            return False
        with self._lock:
            current = self._leases.get(key)
            if current is None:
                return False
            if (
                current.owner != owner
                or int(current.generation) != int(generation or 0)
                or int(current.fence) != int(fence or 0)
            ):
                return False
            self._leases.pop(key, None)
            return True

    def is_lease_current(
        self,
        key: str,
        owner: str,
        generation: int = 0,
        fence: int = 1,
    ) -> bool:
        """True when ``owner`` still holds the live lease for ``key`` with the
        exact generation/fence (the cross-instance commit-right check)."""
        key = str(key or "")
        owner = str(owner or "")
        if not key or not owner:
            return False
        with self._lock:
            now = self._now()
            current = self._leases.get(key)
            if not self._lease_is_live(current, now):
                return False
            return (
                current.owner == owner
                and int(current.generation) == int(generation or 0)
                and int(current.fence) == int(fence or 0)
            )

    def bump_generation(self, key: str) -> int:
        """Invalidate any live lease for ``key`` and advance the generation
        counter atomically (reset/restore/source-switch path).  Returns the
        new generation.  The fence counter is never regressed: the next legal
        ownership still receives a strictly larger fence."""
        key = str(key or "")
        with self._lock:
            counter = self._counters.get(key, {"generation": 0, "fence": 0})
            counter = {
                "generation": int(counter.get("generation") or 0) + 1,
                "fence": int(counter.get("fence") or 0),
            }
            self._counters[key] = counter
            self._leases.pop(key, None)
            return counter["generation"]

    def current_generation(self, key: str) -> int:
        """Latest generation for ``key`` (live lease wins, else the monotonic
        counter).  Used by conversation-save generation checks so a stale
        save from another instance cannot overwrite a newer session."""
        key = str(key or "")
        with self._lock:
            state = self._leases.get(key)
            if state is not None and self._lease_is_live(state, self._now()):
                return int(state.generation)
            counter = self._counters.get(key)
            if counter:
                return int(counter.get("generation") or 0)
            return 0

    # --- shared admission ----------------------------------------------

    def _reap_expired_actives_locked(self) -> None:
        now = self._now()
        for ticket_id, token in list(self._actives.items()):
            if float(token.get("expires_at") or 0.0) <= now:
                self._release_ticket_locked(token)

    def _grant_locked(
        self,
        token: dict[str, Any],
        limits: Any,
    ) -> dict[str, Any]:
        self._active_total += 1
        qkey = str(token.get("principal_key") or "")
        self._active_by_principal[qkey] = (
            self._active_by_principal.get(qkey, 0) + 1
        )
        self._actives[str(token.get("ticket_id") or "")] = token
        return dict(token)

    def _first_runnable_locked(self, limits: Any) -> Optional[dict[str, Any]]:
        """First queued entry whose principal still has capacity (the head may
        be skipped when its own principal is at the cap so it cannot starve
        runnable principals behind it)."""
        per_principal = int(getattr(limits, "max_active_per_principal", 0))
        for entry in self._queue:
            qkey = str(entry.get("principal_key") or "")
            if self._active_by_principal.get(qkey, 0) < per_principal:
                return entry
        return None

    def _remove_queued_locked(self, entry: dict[str, Any]) -> None:
        try:
            self._queue.remove(entry)
        except ValueError:
            pass  # already granted/removed — idempotent

    def admission_acquire(
        self,
        principal_key: str,
        *,
        limits: Any,
        owner: str,
        instance_id: str,
        cancel_event: Optional[threading.Event] = None,
        timeout_seconds: Optional[float] = None,
        ticket_ttl_seconds: float = DEFAULT_ADMISSION_TICKET_TTL_SECONDS,
    ) -> dict[str, Any]:
        """Shared admission grant/queue (mirrors the local controller's
        fairness rules).  Raises ``CoordinationRejected`` with the stable 429
        codes; returns an opaque validated ticket token on success."""
        qkey = str(principal_key or "")
        owner = str(owner or "")
        if not owner:
            raise CoordinationRejected(
                "ADMISSION_CANCELLED", "invalid owner"
            )
        max_active = int(getattr(limits, "max_active_turns", 0))
        per_principal = int(getattr(limits, "max_active_per_principal", 0))
        max_waiting = int(getattr(limits, "max_waiting_turns", 0))
        wait_seconds = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else float(getattr(limits, "admission_wait_seconds", 2.0))
        )
        token = {
            "ticket_id": f"{uuid.uuid4().hex}{next(self._seq)}",
            "principal_key": qkey,
            "owner": owner[: _MAX_TICKET_OWNER],
            "instance_id": str(instance_id or "")[: _MAX_INSTANCE_ID],
            "expires_at": self._now() + max(0.0, float(ticket_ttl_seconds)),
        }
        deadline = self._now() + max(0.0, wait_seconds)
        with self._cond:
            self._reap_expired_actives_locked()
            # Fast path: capacity free and nobody waiting.
            if self._active_total < max_active and not self._queue:
                if self._active_by_principal.get(qkey, 0) < per_principal:
                    return self._grant_locked(token, limits)
                raise CoordinationRejected(
                    PRINCIPAL_CONCURRENCY_LIMIT,
                    f"该身份并发已达上限（{per_principal}），请稍后再试",
                    retry_after=max(1, int(wait_seconds)),
                )
            if len(self._queue) >= max_waiting:
                raise CoordinationRejected(
                    GLOBAL_QUEUE_FULL,
                    "服务繁忙，排队已满，请稍后重试",
                    retry_after=max(1, int(wait_seconds)),
                )
            entry = dict(token)
            entry["enqueued_at"] = self._now()
            self._queue.append(entry)
            try:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise CoordinationRejected(
                            ADMISSION_CANCELLED, "请求已取消", retry_after=None
                        )
                    self._reap_expired_actives_locked()
                    if self._active_total < max_active:
                        first = self._first_runnable_locked(limits)
                        if first is not None and (
                            first.get("ticket_id") == token["ticket_id"]
                        ):
                            self._remove_queued_locked(entry)
                            return self._grant_locked(token, limits)
                    remaining = deadline - self._now()
                    if remaining <= 0:
                        raise CoordinationRejected(
                            ADMISSION_TIMEOUT,
                            "服务繁忙，等待超时，请稍后重试",
                            retry_after=max(1, int(wait_seconds)),
                        )
                    self._cond.wait(
                        min(max(remaining, 0.0), _ADMISSION_POLL_SECONDS)
                    )
            finally:
                self._remove_queued_locked(entry)

    def _release_ticket_locked(self, token: dict[str, Any]) -> None:
        ticket_id = str(token.get("ticket_id") or "")
        active = self._actives.pop(ticket_id, None)
        if active is None:
            return
        self._active_total = max(0, self._active_total - 1)
        qkey = str(active.get("principal_key") or "")
        count = self._active_by_principal.get(qkey, 0)
        if count <= 1:
            self._active_by_principal.pop(qkey, None)
        else:
            self._active_by_principal[qkey] = count - 1

    def admission_release(self, token: dict[str, Any]) -> bool:
        """Validated release of one active ticket; repeated release and
        unknown/stale tokens are idempotent no-ops."""
        if not isinstance(token, dict) or not token.get("ticket_id"):
            return False
        with self._cond:
            active = self._actives.get(str(token.get("ticket_id") or ""))
            if active is None:
                return False
            if (
                str(active.get("owner") or "") != str(token.get("owner") or "")
                or str(active.get("instance_id") or "")
                != str(token.get("instance_id") or "")
            ):
                return False
            self._release_ticket_locked(active)
            self._cond.notify_all()
            return True

    def wait_until_queued(
        self,
        principal_key: Any,
        timeout: float = 1.0,
    ) -> bool:
        """Test/diagnostic helper: block until a queue entry for the given
        principal (string or ``quota_key``-style identity) exists."""
        target = str(getattr(principal_key, "quota_key", principal_key) or "")
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._cond:
            while True:
                if any(
                    str(e.get("principal_key") or "") == target
                    for e in self._queue
                ):
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(min(remaining, _ADMISSION_POLL_SECONDS))


# ---------------------------------------------------------------------------
# Redis shared coordination (atomic Lua entry points)
# ---------------------------------------------------------------------------
#
# Every mutation below is a SINGLE ``redis.eval`` call.  Lua keeps the lease
# value and the per-key monotonic counter in two keys: the counter has no TTL
# so ``fence``/``generation`` never regress when a lease expires or is
# released.  No local Python lock is ever used to "protect" a Redis decision.

# ARGV layout for lease scripts:
#   argv[1]=owner argv[2]=instance_id argv[3]=now(ms) argv[4]=ttl(ms)
# KEYS[1]=lease value key KEYS[2]=fence/generation counter key
_ACQUIRE_LEASE_LUA = r"""
local value = redis.call('GET', KEYS[1])
local now = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
if value then
  local gen, fence, o, inst, exp = value:match('^(%d+) (%d+) ([^ ]+) ([^ ]+) ([^ ]+)$')
  if o == ARGV[1] and tonumber(exp) > now then
    return 'OK ' .. value
  end
  if tonumber(exp) > now then
    return 'BUSY'
  end
end
local counter = redis.call('GET', KEYS[2])
local gen = 0
local fence = 0
if counter then
  local cg, cf = counter:match('^(%d+) (%d+)$')
  gen = tonumber(cg) or 0
  fence = tonumber(cf) or 0
end
gen = gen + 1
fence = fence + 1
redis.call('SET', KEYS[2], gen .. ' ' .. fence)
local expires = now + ttl
redis.call('SET', KEYS[1], gen .. ' ' .. fence .. ' ' .. ARGV[1] .. ' ' .. ARGV[2] .. ' ' .. tostring(expires), 'PX', ttl)
return 'OK ' .. gen .. ' ' .. fence .. ' ' .. ARGV[1] .. ' ' .. ARGV[2] .. ' ' .. tostring(expires)
"""

_RENEW_LEASE_LUA = r"""
local value = redis.call('GET', KEYS[1])
if not value then
  return 'NOOP'
end
local gen, fence, o = value:match('^(%d+) (%d+) ([^ ]+)')
if o ~= ARGV[1] or tonumber(gen) ~= tonumber(ARGV[5]) or tonumber(fence) ~= tonumber(ARGV[6]) then
  return 'STALE'
end
local now = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local _, _, _, _, exp = value:match('^(%d+) (%d+) ([^ ]+) ([^ ]+) ([^ ]+)$')
if tonumber(exp) <= now then
  return 'STALE'
end
redis.call('SET', KEYS[1], value, 'PX', ttl, 'XX')
return 'OK'
"""

_RELEASE_LEASE_LUA = r"""
local value = redis.call('GET', KEYS[1])
if not value then
  return 'NOOP'
end
local gen, fence, o = value:match('^(%d+) (%d+) ([^ ]+)')
if o ~= ARGV[1] or tonumber(gen) ~= tonumber(ARGV[5]) or tonumber(fence) ~= tonumber(ARGV[6]) then
  return 'STALE'
end
redis.call('DEL', KEYS[1])
return 'OK'
"""


_BUMP_GENERATION_LUA = r"""
local value = redis.call('GET', KEYS[1])
local counter = redis.call('GET', KEYS[2])
local gen = 0
local fence = 0
if counter then
  local cg, cf = counter:match('^(%d+) (%d+)$')
  gen = tonumber(cg) or 0
  fence = tonumber(cf) or 0
end
gen = gen + 1
redis.call('SET', KEYS[2], gen .. ' ' .. fence)
redis.call('DEL', KEYS[1])
return tostring(gen)
"""

_CURRENT_GENERATION_LUA = r"""
local value = redis.call('GET', KEYS[1])
if value then
  local gen = value:match('^(%d+)')
  if gen then
    return gen
  end
end
local counter = redis.call('GET', KEYS[2])
if counter then
  local gen = counter:match('^(%d+)')
  if gen then
    return gen
  end
end
return '0'
"""


class RedisSharedCoordination:
    """Redis-backed shared coordination.

    ``client`` is any redis-py-style client exposing ``eval``.  Every lease
    mutation runs as one atomic Lua script; admission mutations likewise use
    single-script entry points (grant / enqueue / validated release).  Keys
    are namespaced so environments never collide.  ``clock`` may be injected
    for deterministic tests; real usage relies on the Redis server clock via
    ``time.time()`` sent as an argument to the script.
    """

    def __init__(
        self,
        client: Any,
        namespace: str = "chatbi",
        *,
        clock: Optional[Callable[[], float]] = None,
        instance_id: str = "",
        lease_ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS,
        admission_ticket_ttl_seconds: float = DEFAULT_ADMISSION_TICKET_TTL_SECONDS,
    ) -> None:
        self._client = client
        self._namespace = _bounded(namespace, _MAX_NAMESPACE)
        self._clock = _clock_or_time(clock)
        self._instance_id = _bounded(instance_id, _MAX_INSTANCE_ID)
        self._lease_ttl_seconds = max(0.0, float(lease_ttl_seconds))
        self._admission_ticket_ttl_seconds = max(
            0.0, float(admission_ticket_ttl_seconds)
        )

    # --- keys ----------------------------------------------------------

    def _key(self, kind: str, key: Any) -> str:
        raw = str(key or "")
        if self._namespace:
            return f"{self._namespace}:{kind}:{raw}"
        return f"{kind}:{raw}"

    def _now_ms(self) -> int:
        return int(float(self._clock()) * 1000)

    # --- lease ops (single eval each) ----------------------------------

    def acquire_lease(
        self,
        key: str,
        owner: str,
        instance_id: str,
        ttl_seconds: Optional[float] = None,
    ) -> Optional[dict[str, Any]]:
        ttl = (
            max(0.0, float(ttl_seconds))
            if ttl_seconds is not None
            else self._lease_ttl_seconds
        )
        reply = self._client.eval(
            _ACQUIRE_LEASE_LUA,
            2,
            self._key("lease", key),
            self._key("lease-counter", key),
            str(owner or ""),
            str(instance_id or ""),
            self._now_ms(),
            int(ttl * 1000),
        )
        if not isinstance(reply, str) or not reply.startswith("OK "):
            return None
        _, gen, fence, o, inst, exp = reply.split(" ", 5)
        return {
            "key": str(key),
            "owner": o,
            "instance_id": inst,
            "generation": int(gen),
            "fence": int(fence),
            "expires_at": int(exp) / 1000.0,
        }

    def renew_lease(
        self,
        key: str,
        owner: str,
        generation: int = 0,
        fence: int = 1,
        ttl_seconds: Optional[float] = None,
        instance_id: Optional[str] = None,
    ) -> bool:
        ttl = (
            max(0.0, float(ttl_seconds))
            if ttl_seconds is not None
            else self._lease_ttl_seconds
        )
        inst = str(instance_id if instance_id is not None else self._instance_id)
        reply = self._client.eval(
            _RENEW_LEASE_LUA,
            2,
            self._key("lease", key),
            self._key("lease-counter", key),
            str(owner or ""),
            inst,
            self._now_ms(),
            int(ttl * 1000),
            int(generation or 0),
            int(fence or 1),
        )
        return reply == "OK"

    def release_lease(
        self,
        key: str,
        owner: str,
        generation: int = 0,
        fence: int = 1,
        instance_id: Optional[str] = None,
    ) -> bool:
        inst = str(instance_id if instance_id is not None else self._instance_id)
        reply = self._client.eval(
            _RELEASE_LEASE_LUA,
            2,
            self._key("lease", key),
            self._key("lease-counter", key),
            str(owner or ""),
            inst,
            self._now_ms(),
            0,
            int(generation or 0),
            int(fence or 1),
        )
        return reply == "OK"

    def is_lease_current(
        self,
        key: str,
        owner: str,
        generation: int = 0,
        fence: int = 1,
    ) -> bool:
        """Read-side commit-right check (single atomic script, no TTL write)."""
        reply = self._client.eval(
            "local v=redis.call('GET',KEYS[1]);"
            " if not v then return 'NO' end;"
            " local g,f,o= v:match('^(%d+) (%d+) ([^ ]+)');"
            " if o==ARGV[1] and tonumber(g)==tonumber(ARGV[2])"
            " and tonumber(f)==tonumber(ARGV[3]) then return 'YES' end;"
            " return 'NO'",
            1,
            self._key("lease", key),
            str(owner or ""),
            int(generation or 0),
            int(fence or 1),
        )
        return reply == "YES"

    def bump_generation(self, key: str) -> int:
        """Atomically invalidate the live lease for ``key`` and advance the
        generation counter (single Lua script; fence never regresses)."""
        key = str(key or "")
        reply = self._client.eval(
            _BUMP_GENERATION_LUA,
            2,
            self._key("lease", key),
            self._key("lease-counter", key),
        )
        try:
            return int(str(reply or "0"))
        except (TypeError, ValueError):
            return 0

    def current_generation(self, key: str) -> int:
        """Latest generation for ``key`` (live lease, else monotonic
        counter).  Single atomic read; no TTL write."""
        key = str(key or "")
        reply = self._client.eval(
            _CURRENT_GENERATION_LUA,
            2,
            self._key("lease", key),
            self._key("lease-counter", key),
        )
        try:
            return int(str(reply or "0"))
        except (TypeError, ValueError):
            return 0

    # --- admission ops (single eval each; validated tickets) -----------

    def admission_acquire(
        self,
        principal_key: str,
        *,
        limits: Any,
        owner: str,
        instance_id: str,
        cancel_event: Optional[threading.Event] = None,
        timeout_seconds: Optional[float] = None,
        ticket_ttl_seconds: float = DEFAULT_ADMISSION_TICKET_TTL_SECONDS,
    ) -> dict[str, Any]:
        """Shared admission entry.  The Redis path grants immediately or
        enqueues; the bounded Python wait loop below only waits for capacity
        that another instance's validated release frees atomically."""
        qkey = str(principal_key or "")
        owner = str(owner or "")
        ticket_id = f"{uuid.uuid4().hex}{_utc_ms()}"
        max_active = int(getattr(limits, "max_active_turns", 0))
        per_principal = int(getattr(limits, "max_active_per_principal", 0))
        wait_seconds = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else float(getattr(limits, "admission_wait_seconds", 2.0))
        )
        token = {
            "ticket_id": ticket_id,
            "principal_key": qkey,
            "owner": owner[: _MAX_TICKET_OWNER],
            "instance_id": str(instance_id or "")[: _MAX_INSTANCE_ID],
        }
        deadline = time.monotonic() + max(0.0, wait_seconds)
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise CoordinationRejected(
                    ADMISSION_CANCELLED, "请求已取消", retry_after=None
                )
            reply = self._client.eval(
                _ADMISSION_TRY_GRANT_LUA,
                4,
                self._key("adm-active-count", qkey),
                self._key("adm-active", ""),
                self._key("adm-principal", qkey),
                self._key("adm-queue", ""),
                str(qkey),
                owner[: _MAX_TICKET_OWNER],
                str(instance_id or ""),
                int(max_active),
                int(per_principal),
                int(self._admission_ticket_ttl_seconds * 1000),
                self._now_ms(),
                ticket_id,
            )
            if isinstance(reply, str) and reply.startswith("GRANT "):
                token["ticket_id"] = reply.split(" ", 1)[1]
                return token
            if isinstance(reply, str) and reply.startswith("QUEUE "):
                token["ticket_id"] = reply.split(" ", 1)[1]
                break
            if isinstance(reply, str) and reply.startswith("REJECT "):
                code, _ = reply.split(" ", 1)
                raise CoordinationRejected(code, "admission rejected")
            # Fake/unavailable client: fail closed with an explicit code.
            raise CoordinationRejected(
                GLOBAL_QUEUE_FULL, "shared admission unavailable"
            )
        # Queued: wait for a validated release to wake capacity; the Lua
        # grant below is the single atomic grant decision.
        while True:
            if cancel_event is not None and cancel_event.is_set():
                try:
                    self._client.eval(
                        _ADMISSION_CANCEL_LUA,
                        4,
                        self._key("adm-active-count", qkey),
                        self._key("adm-active", ""),
                        self._key("adm-principal", qkey),
                        self._key("adm-queue", ""),
                        token["ticket_id"],
                        owner[: _MAX_TICKET_OWNER],
                    )
                except Exception:
                    pass
                raise CoordinationRejected(
                    ADMISSION_CANCELLED, "请求已取消", retry_after=None
                )
            reply = self._client.eval(
                _ADMISSION_POLL_GRANT_LUA,
                4,
                self._key("adm-active-count", qkey),
                self._key("adm-active", ""),
                self._key("adm-principal", qkey),
                self._key("adm-queue", ""),
                token["ticket_id"],
                owner[: _MAX_TICKET_OWNER],
                str(instance_id or ""),
                int(max_active),
                int(per_principal),
                int(self._admission_ticket_ttl_seconds * 1000),
                self._now_ms(),
            )
            if isinstance(reply, str) and reply.startswith("GRANT "):
                return token
            if time.monotonic() >= deadline:
                try:
                    self._client.eval(
                        _ADMISSION_CANCEL_LUA,
                        4,
                        self._key("adm-active-count", qkey),
                        self._key("adm-active", ""),
                        self._key("adm-principal", qkey),
                        self._key("adm-queue", ""),
                        token["ticket_id"],
                        owner[: _MAX_TICKET_OWNER],
                    )
                except Exception:
                    pass
                raise CoordinationRejected(
                    ADMISSION_TIMEOUT,
                    "服务繁忙，等待超时，请稍后重试",
                    retry_after=max(1, int(wait_seconds)),
                )
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    def admission_release(self, token: dict[str, Any]) -> bool:
        if not isinstance(token, dict) or not token.get("ticket_id"):
            return False
        try:
            reply = self._client.eval(
                _ADMISSION_RELEASE_LUA,
                4,
                self._key("adm-active-count", ""),
                self._key("adm-active", ""),
                self._key("adm-principal", ""),
                self._key("adm-queue", ""),
                str(token.get("ticket_id") or ""),
                str(token.get("owner") or ""),
            )
        except Exception:
            return False
        return reply == "OK"

    def wait_until_queued(self, principal_key: Any, timeout: float = 1.0) -> bool:
        """Diagnostic helper for the Redis backend.  Unsupported remotely:
        returns False without blocking (tests use the in-memory backend)."""
        return False

    def health(self) -> dict[str, str]:
        """Redis health probe.  Never includes the URL or credentials."""
        try:
            ping = getattr(self._client, "ping", None)
            if ping is not None and callable(ping):
                ping()
            return {"status": "redis_ok", "effective_mode": "redis"}
        except Exception:
            return {"status": "redis_unavailable", "effective_mode": "redis"}

    def snapshot(self) -> dict[str, Any]:
        return {"leases": {}, "active": 0, "queued": 0}


# Admission Lua helpers (single-script grant / enqueue / poll / release).
# Queue order is kept in a Redis LIST of JSON-ish ticket tokens.
_ADMISSION_TRY_GRANT_LUA = r"""
local qkey = ARGV[1]
local owner = ARGV[2]
local inst = ARGV[3]
local max_active = tonumber(ARGV[4])
local per_principal = tonumber(ARGV[5])
local ttl_ms = tonumber(ARGV[6])
local now = tonumber(ARGV[7])
local ticket = ARGV[8]
local active = tonumber(redis.call('GET', KEYS[1]) or '0')
local principal = tonumber(redis.call('GET', KEYS[3]) or '0')
if active < max_active and principal < per_principal then
  redis.call('INCR', KEYS[1])
  redis.call('INCR', KEYS[3])
  redis.call('SET', KEYS[2] .. ticket, owner .. '|' .. inst, 'PX', ttl_ms)
  redis.call('PEXPIRE', KEYS[1], ttl_ms)
  return 'GRANT ' .. ticket
end
if principal >= per_principal then
  return 'REJECT PRINCIPAL_CONCURRENCY_LIMIT'
end
redis.call('RPUSH', KEYS[4], ticket .. '|' .. qkey)
redis.call('PEXPIRE', KEYS[4], ttl_ms)
return 'QUEUE ' .. ticket
"""

_ADMISSION_POLL_GRANT_LUA = r"""
local ticket = ARGV[1]
local owner = ARGV[2]
local inst = ARGV[3]
local max_active = tonumber(ARGV[4])
local per_principal = tonumber(ARGV[5])
local ttl_ms = tonumber(ARGV[6])
local now = tonumber(ARGV[7])
local entries = redis.call('LRANGE', KEYS[4], 0, -1)
for i, entry in ipairs(entries) do
  local tid, qkey = entry:match('^([^|]+)|(.*)$')
  if tid == ticket then
    local active = tonumber(redis.call('GET', KEYS[1]) or '0')
    local principal = tonumber(redis.call('GET', KEYS[3]) or '0')
    if active < max_active and principal < per_principal then
      redis.call('LREM', KEYS[4], 1, entry)
      redis.call('INCR', KEYS[1])
      redis.call('INCR', KEYS[3])
      redis.call('SET', KEYS[2] .. ticket, owner .. '|' .. inst, 'PX', ttl_ms)
      return 'GRANT ' .. ticket
    end
    return 'WAIT'
  end
end
return 'LOST'
"""

_ADMISSION_CANCEL_LUA = r"""
local ticket = ARGV[1]
local owner = ARGV[2]
local entries = redis.call('LRANGE', KEYS[4], 0, -1)
for i, entry in ipairs(entries) do
  local tid = entry:match('^([^|]+)|')
  if tid == ticket then
    redis.call('LREM', KEYS[4], 1, entry)
    return 'OK'
  end
end
return 'NOOP'
"""

_ADMISSION_RELEASE_LUA = r"""
local ticket = ARGV[1]
local owner = ARGV[2]
local active = redis.call('GET', KEYS[2] .. ticket)
if not active then
  return 'NOOP'
end
local o = active:match('^([^|]+)|')
if o ~= owner then
  return 'STALE'
end
redis.call('DEL', KEYS[2] .. ticket)
local total = tonumber(redis.call('GET', KEYS[1]) or '0')
if total > 0 then
  redis.call('SET', KEYS[1], total - 1)
end
return 'OK'
"""


# ---------------------------------------------------------------------------
# Configuration factory
# ---------------------------------------------------------------------------

_LOCAL_HEALTH = "local"
_REDIS_DEGRADED = "redis_degraded"
_CLOSED = "closed"
_LOCAL_FALLBACK = "local"


def _env_bounded(env: dict[str, str], name: str, default: str, limit: int) -> str:
    raw = str(env.get(name, "")).strip()
    if not raw:
        return default
    return raw[:limit]


def build_coordination_backend(
    env: Optional[dict[str, str]] = None,
    redis_factory: Optional[Callable[[str], Any]] = None,
) -> Any:
    """Build the coordination backend from configuration.

    * ``local`` (default) → ``InMemorySharedCoordination``; no Redis package,
      URL or daemon required and nothing degrades silently.
    * ``redis`` without ``CHATBI_REDIS_URL`` → ``ValueError`` (startup fails).
    * Redis client creation failure:
        - ``CHATBI_COORDINATION_FAILURE_MODE=closed`` (default) → raise; no
          new work may be accepted;
        - explicit ``CHATBI_COORDINATION_FAILURE_MODE=local`` → returns an
          ``InMemorySharedCoordination`` whose health reports
          ``redis_degraded`` with ``effective_mode=local``.
    """
    env = os.environ if env is None else env
    mode = str(env.get("CHATBI_COORDINATION_MODE", "")).strip().lower()
    failure_mode = (
        str(env.get("CHATBI_COORDINATION_FAILURE_MODE", "")).strip().lower()
        or _CLOSED
    )
    if failure_mode not in (_CLOSED, _LOCAL_FALLBACK):
        raise ValueError(
            "CHATBI_COORDINATION_FAILURE_MODE must be 'closed' or 'local'"
        )
    namespace = _env_bounded(
        env, "CHATBI_COORDINATION_NAMESPACE", "chatbi", _MAX_NAMESPACE
    )
    instance_id = _env_bounded(
        env, "CHATBI_INSTANCE_ID", "", _MAX_INSTANCE_ID
    )
    # TTL/heartbeat validation (positive, heartbeat < TTL/2).
    ttl_raw = str(env.get("CHATBI_LEASE_TTL_SECONDS", "")).strip()
    heartbeat_raw = str(env.get("CHATBI_LEASE_HEARTBEAT_SECONDS", "")).strip()
    ttl = DEFAULT_LEASE_TTL_SECONDS
    heartbeat = ttl / 3.0
    if ttl_raw:
        ttl = float(ttl_raw)
        if ttl <= 0:
            raise ValueError("CHATBI_LEASE_TTL_SECONDS must be > 0")
    if heartbeat_raw:
        heartbeat = float(heartbeat_raw)
        if heartbeat <= 0:
            raise ValueError("CHATBI_LEASE_HEARTBEAT_SECONDS must be > 0")
    if heartbeat >= ttl / 2.0:
        raise ValueError(
            "CHATBI_LEASE_HEARTBEAT_SECONDS must be < TTL / 2"
        )
    if not mode or mode == _LOCAL_HEALTH:
        return InMemorySharedCoordination(
            namespace=namespace,
            instance_id=instance_id,
            lease_ttl_seconds=ttl,
        )
    if mode != "redis":
        raise ValueError(
            f"CHATBI_COORDINATION_MODE must be 'local' or 'redis', got {mode!r}"
        )
    url = str(env.get("CHATBI_REDIS_URL", "")).strip()
    if not url:
        raise ValueError("CHATBI_COORDINATION_MODE=redis requires CHATBI_REDIS_URL")
    try:
        if redis_factory is not None:
            client = redis_factory(url)
        else:
            # Lazy import: the local default must not depend on redis-py.
            import redis  # type: ignore

            client = redis.Redis.from_url(url)
    except Exception as exc:
        if failure_mode == _LOCAL_FALLBACK:
            # Explicit, observable local fallback.  Never silent.
            backend = InMemorySharedCoordination(
                namespace=namespace,
                instance_id=instance_id,
                lease_ttl_seconds=ttl,
                health_status=_REDIS_DEGRADED,
            )
            return backend
        raise RuntimeError(
            "shared coordination unavailable (redis mode, closed policy)"
        ) from exc
    return RedisSharedCoordination(
        client,
        namespace=namespace,
        instance_id=instance_id,
        lease_ttl_seconds=ttl,
    )
