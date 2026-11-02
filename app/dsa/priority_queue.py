import asyncio
import heapq
import time
from typing import Generic, TypeVar, Optional, Tuple, Dict, Any

T = TypeVar("T")

class PriorityQueue(Generic[T]):
    """
    Thread-safe asynchronous Priority Queue implemented using a Binary Min-Heap
    with monotonic per-entry version tokens for O(1) replace and cancellation.
    
    Time Complexity:
      - Enqueue (push): O(log N)
      - Dequeue (pop):  O(log N)
      - Peek:           O(1)
      - Remove/Cancel:  O(1) version invalidation
    
    Tie-breaking ensures FIFO ordering for items with identical priority scores.
    """
    def __init__(self):
        # Heap entries: (priority, timestamp, counter, item_id, item, version)
        self._heap: list[Tuple[int, float, int, str, T, int]] = []
        self._entry_versions: Dict[str, int] = {}
        self._entry_items: Dict[str, T] = {}
        self._counter: int = 0
        self._lock = asyncio.Lock()
        self._has_items = asyncio.Condition(self._lock)

    async def push(self, item_id: str, item: T, priority: int = 5) -> None:
        """
        Push an item into the priority queue.
        Lower priority number = higher execution urgency (e.g., 0 is critical, 10 is low).
        If item_id is already present, its version token is incremented, automatically
        invalidating the previous entry in the heap and preventing duplicate execution.
        """
        async with self._has_items:
            self._counter += 1
            version = self._counter
            self._entry_versions[item_id] = version
            self._entry_items[item_id] = item
            timestamp = time.time()
            entry = (priority, timestamp, self._counter, item_id, item, version)
            heapq.heappush(self._heap, entry)
            self._has_items.notify()

    async def pop(self) -> Tuple[str, T]:
        """
        Pop and return the highest priority item (lowest priority integer).
        Blocks asynchronously if queue has no valid items.
        """
        async with self._has_items:
            while True:
                while not self._heap:
                    await self._has_items.wait()

                priority, ts, count, item_id, item, version = heapq.heappop(self._heap)

                # Check if this heap entry matches the active version for this item_id
                active_version = self._entry_versions.get(item_id)
                if active_version is not None and active_version == version:
                    del self._entry_versions[item_id]
                    self._entry_items.pop(item_id, None)
                    return item_id, item
                # Otherwise, it was replaced or cancelled -> discard and continue

    async def remove(self, item_id: str) -> bool:
        """
        Remove/cancel an item by ID via version invalidation in O(1) time.
        """
        async with self._lock:
            if item_id in self._entry_versions:
                del self._entry_versions[item_id]
                self._entry_items.pop(item_id, None)
                return True
            return False

    async def peek(self) -> Optional[Tuple[str, T]]:
        """Peek at top valid priority item without popping."""
        async with self._lock:
            while self._heap:
                item_id = self._heap[0][3]
                version = self._heap[0][5]
                if self._entry_versions.get(item_id) == version:
                    return self._heap[0][3], self._heap[0][4]
                # Stale entry at head of heap -> prune it
                heapq.heappop(self._heap)
            return None

    def __len__(self) -> int:
        return len(self._entry_versions)
