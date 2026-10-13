import asyncio
import heapq
import time
from typing import Generic, TypeVar, Optional, Tuple, Dict, Any

T = TypeVar("T")

class PriorityQueue(Generic[T]):
    """
    Thread-safe asynchronous Priority Queue implemented using a Binary Min-Heap.
    Time Complexity:
      - Enqueue (push): O(log N)
      - Dequeue (pop):  O(log N)
      - Peek:           O(1)
      - Remove/Cancel:  O(log N) with lazy tombstoning
    
    Tie-breaking ensures FIFO ordering for items with identical priority scores.
    """
    def __init__(self):
        self._heap: list[Tuple[int, float, int, str, T]] = []
        self._entry_map: Dict[str, Tuple[int, float, int, str, T]] = {}
        self._counter: int = 0  # Monotonic counter for FIFO tie-breaking
        self._lock = asyncio.Lock()
        self._has_items = asyncio.Condition(self._lock)
        self._tombstones: set[str] = set()

    async def push(self, item_id: str, item: T, priority: int = 5) -> None:
        """
        Push an item into the priority queue.
        Lower priority number = higher execution urgency (e.g., 0 is critical, 10 is low).
        """
        async with self._has_items:
            # If already present, mark previous as tombstone
            if item_id in self._entry_map:
                self._tombstones.add(item_id)

            self._counter += 1
            timestamp = time.time()
            entry = (priority, timestamp, self._counter, item_id, item)
            self._entry_map[item_id] = entry
            self._tombstones.discard(item_id)
            heapq.heappush(self._heap, entry)
            self._has_items.notify()

    async def pop(self) -> Tuple[str, T]:
        """
        Pop and return the highest priority item (lowest priority integer).
        Blocks asynchronously if queue is empty.
        """
        async with self._has_items:
            while True:
                while not self._heap:
                    await self._has_items.wait()

                priority, ts, count, item_id, item = heapq.heappop(self._heap)

                # Skip tombstoned (cancelled / updated) entries
                if item_id in self._tombstones:
                    self._tombstones.remove(item_id)
                    continue

                if item_id in self._entry_map:
                    del self._entry_map[item_id]

                return item_id, item

    async def remove(self, item_id: str) -> bool:
        """
        Remove an item by ID via tombstoning in O(1) amortized time.
        """
        async with self._lock:
            if item_id in self._entry_map:
                del self._entry_map[item_id]
                self._tombstones.add(item_id)
                return True
            return False

    async def peek(self) -> Optional[Tuple[str, T]]:
        """Peek at top priority item without popping."""
        async with self._lock:
            while self._heap and self._heap[0][3] in self._tombstones:
                tombstone = heapq.heappop(self._heap)
                self._tombstones.discard(tombstone[3])

            if self._heap:
                return self._heap[0][3], self._heap[0][4]
            return None

    def __len__(self) -> int:
        return len(self._entry_map)

