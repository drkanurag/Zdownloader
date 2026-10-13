import time
import asyncio
from enum import Enum
from typing import Callable, Any
from app.domain.exceptions import CircuitBreakerOpenException

class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

class CircuitBreaker:
    """
    Circuit Breaker Pattern to prevent cascade failures when querying external platforms.
    
    States:
      - CLOSED: Normal operation. Successes reset failure count.
      - OPEN: Tripped after failure_threshold errors. Rejects calls fast for recovery_timeout seconds.
      - HALF_OPEN: Allows trial request to test if external service has recovered.
    """
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0
        self._lock = asyncio.Lock()

    async def execute(self, func: Callable, *args, **kwargs) -> Any:
        async with self._lock:
            now = time.time()

            if self.state == CircuitState.OPEN:
                if now - self.last_failure_time > self.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                else:
                    raise CircuitBreakerOpenException(
                        f"Circuit breaker is OPEN. Fast-failing external call for {self.recovery_timeout - (now - self.last_failure_time):.1f}s."
                    )

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            async with self._lock:
                if self.state == CircuitState.HALF_OPEN:
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                elif self.state == CircuitState.CLOSED:
                    self.failure_count = max(0, self.failure_count - 1)

            return result

        except Exception as e:
            async with self._lock:
                self.failure_count += 1
                self.last_failure_time = time.time()
                if self.failure_count >= self.failure_threshold:
                    self.state = CircuitState.OPEN
            raise e

