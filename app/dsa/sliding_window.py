import time
from collections import deque
from typing import Deque, Tuple, Optional

class SlidingWindowSpeedEstimator:
    """
    Sliding Window algorithm for high-accuracy download speed and ETA estimation.
    
    Instead of noisy instantaneous delta calculations, maintains a time-windowed
    queue of (timestamp, total_bytes) checkpoints.
    
    Time Complexity:
      - record(bytes): O(1) amortized
      - get_speed(): O(1) amortized
    Space Complexity:
      - O(W) where W is sample points within the window (typically < 30 samples).
    """
    def __init__(self, window_seconds: float = 2.0):
        self.window_seconds: float = window_seconds
        self._samples: Deque[Tuple[float, int]] = deque()
        self._total_bytes: int = 0

    def record(self, current_total_bytes: int, timestamp: Optional[float] = None) -> None:
        """Record a byte-count sample at current time."""
        now = timestamp if timestamp is not None else time.time()
        self._total_bytes = current_total_bytes
        self._samples.append((now, current_total_bytes))
        self._evict_old(now)

    def _evict_old(self, now: float) -> None:
        """Evict samples older than the sliding window boundary."""
        cutoff = now - self.window_seconds
        while len(self._samples) > 2 and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def get_speed(self) -> float:
        """
        Calculate smoothed moving average speed (bytes/sec) over the sliding window.
        """
        if len(self._samples) < 2:
            return 0.0

        now = time.time()
        self._evict_old(now)

        earliest_time, earliest_bytes = self._samples[0]
        latest_time, latest_bytes = self._samples[-1]

        duration = latest_time - earliest_time
        if duration <= 0.001:
            return 0.0

        bytes_delta = latest_bytes - earliest_bytes
        if bytes_delta <= 0:
            return 0.0

        return max(0.0, bytes_delta / duration)

    def estimate_eta(self, total_expected_bytes: Optional[int]) -> Optional[int]:
        """
        Estimate remaining seconds based on moving average speed.
        Returns None if total size or speed is unknown.
        """
        if not total_expected_bytes or total_expected_bytes <= self._total_bytes:
            return 0

        speed = self.get_speed()
        if speed <= 0:
            return None

        remaining_bytes = total_expected_bytes - self._total_bytes
        return max(0, int(remaining_bytes / speed))

