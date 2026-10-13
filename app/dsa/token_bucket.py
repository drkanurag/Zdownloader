import time
import asyncio
from typing import Optional

class TokenBucketRateLimiter:
    """
    Token Bucket Algorithm for rate limiting and bandwidth traffic shaping.
    
    Tokens regenerate at a constant refill rate (tokens_per_second) up to bucket capacity.
    Allows bursts up to capacity while enforcing long-term average throughput.
    
    Time Complexity:
      - acquire / try_acquire: O(1)
    """
    def __init__(self, capacity: float, refill_rate: float):
        if capacity <= 0 or refill_rate <= 0:
            raise ValueError("Capacity and refill rate must be positive numbers")
        self.capacity: float = capacity
        self.refill_rate: float = refill_rate
        self.tokens: float = capacity
        self.last_refill_time: float = time.time()
        self._lock = asyncio.Lock()

    def _refill(self, now: float) -> None:
        """Add tokens proportional to elapsed time since last refill."""
        elapsed = now - self.last_refill_time
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + (elapsed * self.refill_rate))
            self.last_refill_time = now

    async def try_acquire(self, tokens_needed: float = 1.0) -> bool:
        """Non-blocking attempt to acquire tokens. Returns True if granted."""
        async with self._lock:
            now = time.time()
            self._refill(now)
            if self.tokens >= tokens_needed:
                self.tokens -= tokens_needed
                return True
            return False

    async def acquire(self, tokens_needed: float = 1.0) -> None:
        """
        Asynchronously blocks until required tokens are available in the bucket.
        Useful for bandwidth throttling chunked downloads.
        """
        while True:
            async with self._lock:
                now = time.time()
                self._refill(now)
                if self.tokens >= tokens_needed:
                    self.tokens -= tokens_needed
                    return

                # Calculate sleep duration needed to replenish missing tokens
                missing_tokens = tokens_needed - self.tokens
                sleep_duration = missing_tokens / self.refill_rate

            await asyncio.sleep(min(sleep_duration, 0.5))

    def update_rate(self, new_refill_rate: float, new_capacity: Optional[float] = None) -> None:
        """Dynamically adjust bandwidth cap or request quota."""
        if new_refill_rate <= 0:
            return
        self.refill_rate = new_refill_rate
        if new_capacity:
            self.capacity = new_capacity
        self.tokens = min(self.tokens, self.capacity)

