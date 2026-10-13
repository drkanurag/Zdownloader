import asyncio
import time
import unittest

from app.dsa.priority_queue import PriorityQueue
from app.dsa.lru_cache import LRUCacheWithTTL
from app.dsa.sliding_window import SlidingWindowSpeedEstimator
from app.dsa.token_bucket import TokenBucketRateLimiter
from app.dsa.trie import DomainRadixTrie
from app.core.security import validate_url_security
from app.core.circuit_breaker import CircuitBreaker, CircuitState
from app.core.event_bus import EventBus
from app.domain.events import JobCreatedEvent
from app.domain.exceptions import CircuitBreakerOpenException

class TestDataStructuresAndAlgorithms(unittest.IsolatedAsyncioTestCase):

    async def test_priority_queue_ordering_and_fifo(self):
        """Test Min-Heap priority ordering with FIFO tie-breaking."""
        pq = PriorityQueue[str]()
        # Push items with different priorities
        await pq.push("job_low", "Low Priority Job", priority=10)
        await pq.push("job_crit", "Critical Job", priority=1)
        await pq.push("job_normal_1", "Normal Job 1", priority=5)
        await pq.push("job_normal_2", "Normal Job 2", priority=5)

        self.assertEqual(len(pq), 4)

        # First pop must be Critical (priority 1)
        k1, v1 = await pq.pop()
        self.assertEqual(k1, "job_crit")

        # Second pop must be Normal 1 (priority 5, earlier timestamp FIFO)
        k2, v2 = await pq.pop()
        self.assertEqual(k2, "job_normal_1")

        # Third pop must be Normal 2 (priority 5)
        k3, v3 = await pq.pop()
        self.assertEqual(k3, "job_normal_2")

        # Fourth pop must be Low (priority 10)
        k4, v4 = await pq.pop()
        self.assertEqual(k4, "job_low")

    async def test_priority_queue_tombstone_cancellation(self):
        """Test cancellation and removal via tombstoning."""
        pq = PriorityQueue[str]()
        await pq.push("job_1", "Job 1", priority=1)
        await pq.push("job_2", "Job 2", priority=2)

        # Cancel job_1
        cancelled = await pq.remove("job_1")
        self.assertTrue(cancelled)

        # Popping should immediately skip job_1 and return job_2
        k, v = await pq.pop()
        self.assertEqual(k, "job_2")

    async def test_lru_cache_eviction_and_ttl(self):
        """Test O(1) LRU eviction order and TTL expiration."""
        cache = LRUCacheWithTTL[str, str](capacity=2, default_ttl_seconds=0.1)

        await cache.put("a", "Alpha")
        await cache.put("b", "Beta")

        # Access 'a' to make it most recently used
        val_a = await cache.get("a")
        self.assertEqual(val_a, "Alpha")

        # Put 'c', which should evict 'b' (least recently used)
        await cache.put("c", "Gamma")
        self.assertIsNone(await cache.get("b"))
        self.assertEqual(await cache.get("a"), "Alpha")
        self.assertEqual(await cache.get("c"), "Gamma")

        # Test TTL expiration
        await asyncio.sleep(0.15)
        self.assertIsNone(await cache.get("a"))
        self.assertIsNone(await cache.get("c"))

    def test_sliding_window_speed_estimator(self):
        """Test Sliding Window moving average speed and ETA estimation."""
        estimator = SlidingWindowSpeedEstimator(window_seconds=1.0)

        # Simulate 1 MB transferred at t=0
        estimator.record(current_total_bytes=1048576, timestamp=100.0)
        # Simulate 3 MB transferred at t=0.5s (2 MB delta over 0.5s = 4 MB/s)
        estimator.record(current_total_bytes=3145728, timestamp=100.5)

        speed = estimator.get_speed()
        self.assertGreater(speed, 3500000)
        self.assertLess(speed, 4500000)

        # Total expected = 7 MB, remaining = 4 MB, at 4 MB/s ETA should be ~1s
        eta = estimator.estimate_eta(total_expected_bytes=7340032)
        self.assertEqual(eta, 1)

    async def test_token_bucket_rate_limiter(self):
        """Test Token Bucket burst capacity and rate limiting."""
        limiter = TokenBucketRateLimiter(capacity=3.0, refill_rate=2.0)

        # Can burst up to 3 tokens
        self.assertTrue(await limiter.try_acquire(1.0))
        self.assertTrue(await limiter.try_acquire(1.0))
        self.assertTrue(await limiter.try_acquire(1.0))

        # 4th token should fail immediately (bucket empty)
        self.assertFalse(await limiter.try_acquire(1.0))

        # Wait 0.55s for ~1.1 tokens to replenish
        await asyncio.sleep(0.55)
        self.assertTrue(await limiter.try_acquire(1.0))

    def test_domain_radix_trie(self):
        """Test Trie prefix/subdomain matching in O(L) time."""
        trie = DomainRadixTrie()
        trie.insert("youtube.com", "YouTube")
        trie.insert("vimeo.com", "Vimeo")
        trie.insert("*.reddit.com", "Reddit")

        self.assertEqual(trie.match_subdomain("youtube.com"), "YouTube")
        self.assertEqual(trie.match_subdomain("m.youtube.com"), "YouTube")
        self.assertEqual(trie.match_subdomain("music.youtube.com"), "YouTube")
        self.assertEqual(trie.match_subdomain("old.reddit.com"), "Reddit")
        self.assertIsNone(trie.match_subdomain("unknownsite.org"))

class TestSystemDesignSecurityAndResilience(unittest.IsolatedAsyncioTestCase):

    def test_ssrf_protection(self):
        """Test SSRF protection against private IP addresses and metadata endpoints."""
        # Loopback
        safe, _ = validate_url_security("http://127.0.0.1:8080/admin")
        self.assertFalse(safe)

        safe, _ = validate_url_security("http://localhost:3000/secret")
        self.assertFalse(safe)

        # RFC 1918 Private networks
        safe, _ = validate_url_security("http://192.168.1.1/router")
        self.assertFalse(safe)

        safe, _ = validate_url_security("http://10.0.0.5:5000/api")
        self.assertFalse(safe)

        # Cloud metadata service (AWS/GCP/Azure)
        safe, _ = validate_url_security("http://169.254.169.254/latest/meta-data/")
        self.assertFalse(safe)

        # Invalid schemes (e.g., file://, ftp://, gopher://)
        safe, _ = validate_url_security("file:///etc/passwd")
        self.assertFalse(safe)

        safe, _ = validate_url_security("gopher://evil.com")
        self.assertFalse(safe)

        # Valid public internet URLs
        safe, _ = validate_url_security("https://www.google.com")
        self.assertTrue(safe)

    async def test_circuit_breaker_state_transitions(self):
        """Test Circuit Breaker CLOSED -> OPEN -> HALF_OPEN state transitions."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        self.assertEqual(cb.state, CircuitState.CLOSED)

        def failing_call():
            raise RuntimeError("Downstream service timeout")

        # Failure 1
        with self.assertRaises(RuntimeError):
            await cb.execute(failing_call)
        self.assertEqual(cb.state, CircuitState.CLOSED)

        # Failure 2 (trips circuit breaker)
        with self.assertRaises(RuntimeError):
            await cb.execute(failing_call)
        self.assertEqual(cb.state, CircuitState.OPEN)

        # Fast-fail while OPEN
        with self.assertRaises(CircuitBreakerOpenException):
            await cb.execute(failing_call)

        # Wait for recovery timeout
        await asyncio.sleep(0.12)

        # Next call tests HALF_OPEN
        def successful_call():
            return "recovered"

        res = await cb.execute(successful_call)
        self.assertEqual(res, "recovered")
        self.assertEqual(cb.state, CircuitState.CLOSED)

    async def test_event_bus_pub_sub(self):
        """Test decoupled publish/subscribe domain events."""
        eb = EventBus()
        received_events = []

        async def handler(event: JobCreatedEvent):
            received_events.append(event)

        eb.subscribe(JobCreatedEvent, handler)

        test_event = JobCreatedEvent(
            event_id="e-1",
            event_type="job_created",
            job_id="j-100",
            url="https://example.com/video.mp4",
            title="Test Video"
        )
        await eb.publish(test_event)

        # Allow microtask execution
        await asyncio.sleep(0.01)

        self.assertEqual(len(received_events), 1)
        self.assertEqual(received_events[0].job_id, "j-100")
        self.assertEqual(received_events[0].title, "Test Video")

if __name__ == "__main__":
    unittest.main()

