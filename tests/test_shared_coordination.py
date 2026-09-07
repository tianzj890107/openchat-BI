"""RED contract tests for multi-instance shared concurrency coordination."""

from __future__ import annotations

import threading
import unittest

from bi_agent import concurrency


class FakeClock:
    def __init__(self):
        self.value = 1000.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class FakeRedis:
    """Small spy; production code owns script semantics, this records eval use."""

    def __init__(self):
        self.eval_calls = []

    def eval(self, script, numkeys, *args):
        self.eval_calls.append((script, numkeys, args))
        return None


class SharedCoordinationRedTests(unittest.TestCase):
    def _backend(self, clock=None):
        self.assertTrue(
            hasattr(concurrency, "InMemorySharedCoordination"),
            "RED: 尚无共享协调语义适配器",
        )
        return concurrency.InMemorySharedCoordination(clock=clock)

    def _registry(self, backend, instance_id):
        try:
            return concurrency.SessionSlotRegistry(
                shared_backend=backend,
                instance_id=instance_id,
            )
        except TypeError as exc:
            self.fail(f"RED: SessionSlotRegistry 尚未接入共享 backend: {exc}")

    def test_local_registry_default_remains_backward_compatible(self):
        registry = concurrency.SessionSlotRegistry()
        first = registry.ensure("data:local-session")
        lease = first.try_acquire()
        self.assertIsNotNone(lease)
        self.assertIsNone(first.try_acquire())
        first.release_turn(lease)
        self.assertIsNotNone(first.try_acquire())

    def test_two_instances_cannot_acquire_same_shared_session(self):
        backend = self._backend()
        registry_a = self._registry(backend, "instance-a")
        registry_b = self._registry(backend, "instance-b")
        slot_a = registry_a.ensure("data:shared-session")
        slot_b = registry_b.ensure("data:shared-session")
        lease_a = slot_a.try_acquire()
        self.assertIsNotNone(lease_a)
        self.assertIsNone(slot_b.try_acquire())
        self.assertGreater(lease_a.fence, 0)

    def test_expired_lease_can_be_taken_over_with_strictly_larger_fence(self):
        clock = FakeClock()
        backend = self._backend(clock)
        registry_a = self._registry(backend, "instance-a")
        registry_b = self._registry(backend, "instance-b")
        slot_a = registry_a.ensure("data:ttl-session")
        slot_b = registry_b.ensure("data:ttl-session")
        lease_a = slot_a.try_acquire(lease_ttl_seconds=10)
        self.assertIsNotNone(lease_a)
        clock.advance(11)
        lease_b = slot_b.try_acquire(lease_ttl_seconds=10)
        self.assertIsNotNone(lease_b)
        self.assertGreater(lease_b.fence, lease_a.fence)
        self.assertTrue(slot_a.is_superseded(lease_a, None))

    def test_stale_owner_release_and_renew_cannot_touch_new_lease(self):
        clock = FakeClock()
        backend = self._backend(clock)
        slot_a = self._registry(backend, "instance-a").ensure("data:fenced")
        slot_b = self._registry(backend, "instance-b").ensure("data:fenced")
        lease_a = slot_a.try_acquire(lease_ttl_seconds=5)
        clock.advance(6)
        lease_b = slot_b.try_acquire(lease_ttl_seconds=20)
        self.assertIsNotNone(lease_b)
        slot_a.release_turn(lease_a)
        self.assertFalse(slot_a.renew_turn(lease_a, lease_ttl_seconds=20))
        self.assertFalse(slot_b.is_superseded(lease_b, None))
        self.assertIsNone(slot_a.try_acquire())

    def test_heartbeat_owner_mismatch_cancels_old_turn(self):
        clock = FakeClock()
        backend = self._backend(clock)
        slot_a = self._registry(backend, "instance-a").ensure("data:heartbeat")
        slot_b = self._registry(backend, "instance-b").ensure("data:heartbeat")
        cancel = threading.Event()
        lease_a = slot_a.try_acquire(cancel_event=cancel, lease_ttl_seconds=5)
        clock.advance(6)
        self.assertIsNotNone(slot_b.try_acquire(lease_ttl_seconds=10))
        self.assertFalse(slot_a.heartbeat(lease_a, cancel, lease_ttl_seconds=5))
        self.assertTrue(cancel.is_set())
        self.assertTrue(slot_a.is_superseded(lease_a, cancel))

    def test_shared_admission_caps_global_and_principal_across_instances(self):
        backend = self._backend()
        limits = concurrency.Limits({
            "CHATBI_MAX_ACTIVE_REQUESTS": "2",
            "CHATBI_MAX_ACTIVE_PER_PRINCIPAL": "1",
            "CHATBI_MAX_QUEUED_REQUESTS": "0",
        })
        try:
            first = concurrency.AdmissionController(limits, shared_backend=backend, instance_id="a")
            second = concurrency.AdmissionController(limits, shared_backend=backend, instance_id="b")
        except TypeError as exc:
            self.fail(f"RED: AdmissionController 尚未接入共享 backend: {exc}")
        p1 = concurrency.RequestPrincipal(session_id="principal-1")
        p2 = concurrency.RequestPrincipal(session_id="principal-2")
        ticket_1 = first.acquire(p1)
        with self.assertRaises(concurrency.AdmissionRejected) as duplicate:
            second.acquire(p1)
        self.assertEqual(duplicate.exception.code, "PRINCIPAL_CONCURRENCY_LIMIT")
        ticket_2 = second.acquire(p2)
        with self.assertRaises(concurrency.AdmissionRejected):
            first.acquire(concurrency.RequestPrincipal(session_id="principal-3"))
        first.release(ticket_1)
        second.release(ticket_2)

    def test_cancelled_shared_queue_ticket_never_consumes_later_capacity(self):
        backend = self._backend()
        limits = concurrency.Limits({
            "CHATBI_MAX_ACTIVE_REQUESTS": "1",
            "CHATBI_MAX_ACTIVE_PER_PRINCIPAL": "1",
            "CHATBI_MAX_QUEUED_REQUESTS": "2",
            "CHATBI_ADMISSION_WAIT_SECONDS": "1",
        })
        first = concurrency.AdmissionController(limits, shared_backend=backend, instance_id="a")
        second = concurrency.AdmissionController(limits, shared_backend=backend, instance_id="b")
        active = first.acquire(concurrency.RequestPrincipal(session_id="active"))
        cancel = threading.Event()
        result = []

        def wait_then_cancel():
            try:
                second.acquire(
                    concurrency.RequestPrincipal(session_id="queued"),
                    cancel_event=cancel,
                )
            except Exception as exc:
                result.append(exc)

        worker = threading.Thread(target=wait_then_cancel)
        worker.start()
        self.assertTrue(backend.wait_until_queued("queued", timeout=1))
        cancel.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(getattr(result[0], "code", ""), "ADMISSION_CANCELLED")
        first.release(active)
        self.assertEqual(backend.snapshot()["queued"], 0)

    def test_redis_backend_uses_atomic_script_entrypoints(self):
        self.assertTrue(
            hasattr(concurrency, "RedisSharedCoordination"),
            "RED: 尚无 Redis 共享协调实现",
        )
        client = FakeRedis()
        backend = concurrency.RedisSharedCoordination(client, namespace="chatbi-test")
        backend.acquire_lease("data:s1", "owner-a", "instance-a", ttl_seconds=10)
        backend.renew_lease("data:s1", "owner-a", generation=0, fence=1, ttl_seconds=10)
        backend.release_lease("data:s1", "owner-a", generation=0, fence=1)
        self.assertEqual(len(client.eval_calls), 3)
        self.assertTrue(all(call[1] >= 1 for call in client.eval_calls))

    def test_coordination_failure_policy_is_explicit_and_observable(self):
        self.assertTrue(hasattr(concurrency, "build_coordination_backend"))
        with self.assertRaises(ValueError):
            concurrency.build_coordination_backend({
                "CHATBI_COORDINATION_MODE": "redis",
                "CHATBI_COORDINATION_FAILURE_MODE": "closed",
            })
        backend = concurrency.build_coordination_backend({
            "CHATBI_COORDINATION_MODE": "redis",
            "CHATBI_REDIS_URL": "redis://invalid.example/0",
            "CHATBI_COORDINATION_FAILURE_MODE": "local",
        }, redis_factory=lambda _url: (_ for _ in ()).throw(ConnectionError("down")))
        self.assertEqual(backend.health()["status"], "redis_degraded")
        self.assertEqual(backend.health()["effective_mode"], "local")

    def test_shared_keys_and_health_never_expose_credentials_or_user_text(self):
        backend = self._backend()
        registry = self._registry(backend, "instance-safe")
        slot = registry.ensure("data:safe-session")
        self.assertIsNotNone(slot.try_acquire())
        serialized = repr(backend.snapshot()) + repr(backend.health())
        self.assertNotIn("redis://", serialized)
        self.assertNotIn("password", serialized.lower())
        self.assertNotIn("用户的完整问题", serialized)


if __name__ == "__main__":
    unittest.main()
