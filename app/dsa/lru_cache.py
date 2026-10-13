import time
import asyncio
from typing import Generic, TypeVar, Optional, Dict

K = TypeVar("K")
V = TypeVar("V")

class _Node(Generic[K, V]):
    __slots__ = ("key", "value", "expires_at", "prev", "next")

    def __init__(self, key: K, value: V, expires_at: float):
        self.key: K = key
        self.value: V = value
        self.expires_at: float = expires_at
        self.prev: Optional[_Node[K, V]] = None
        self.next: Optional[_Node[K, V]] = None

class LRUCacheWithTTL(Generic[K, V]):
    """
    Least Recently Used (LRU) Cache with Time-To-Live (TTL) expiration.
    
    Data Structure Architecture:
      - Hash Map: Provides O(1) Key -> Node lookup.
      - Doubly Linked List: Maintains LRU eviction order with O(1) node relocation.
    
    Time Complexity:
      - get: O(1)
      - put: O(1)
      - delete: O(1)
    """
    def __init__(self, capacity: int = 128, default_ttl_seconds: float = 300.0):
        if capacity <= 0:
            raise ValueError("Capacity must be positive")
        self.capacity = capacity
        self.default_ttl = default_ttl_seconds
        self._map: Dict[K, _Node[K, V]] = {}
        self._lock = asyncio.Lock()

        # Dummy sentinel head and tail nodes
        self._head: _Node[K, V] = _Node(None, None, 0.0)  # type: ignore
        self._tail: _Node[K, V] = _Node(None, None, 0.0)  # type: ignore
        self._head.next = self._tail
        self._tail.prev = self._head

    def _remove_node(self, node: _Node[K, V]) -> None:
        """Unlink node from doubly linked list in O(1)."""
        prev_node = node.prev
        next_node = node.next
        if prev_node:
            prev_node.next = next_node
        if next_node:
            next_node.prev = prev_node

    def _add_to_head(self, node: _Node[K, V]) -> None:
        """Insert node right after head sentinel in O(1)."""
        node.next = self._head.next
        node.prev = self._head
        if self._head.next:
            self._head.next.prev = node
        self._head.next = node

    def _move_to_head(self, node: _Node[K, V]) -> None:
        """Move existing node to most recently used position in O(1)."""
        self._remove_node(node)
        self._add_to_head(node)

    def _evict_tail(self) -> Optional[_Node[K, V]]:
        """Remove least recently used node from tail in O(1)."""
        least_recent = self._tail.prev
        if least_recent and least_recent != self._head:
            self._remove_node(least_recent)
            return least_recent
        return None

    async def get(self, key: K) -> Optional[V]:
        """Retrieve value from cache in O(1). Evicts if expired."""
        async with self._lock:
            if key not in self._map:
                return None

            node = self._map[key]
            now = time.time()

            # Check TTL expiration
            if now > node.expires_at:
                self._remove_node(node)
                del self._map[key]
                return None

            # Refresh position in LRU order
            self._move_to_head(node)
            return node.value

    async def put(self, key: K, value: V, ttl: Optional[float] = None) -> None:
        """Insert or update key-value pair in O(1)."""
        async with self._lock:
            ttl_duration = ttl if ttl is not None else self.default_ttl
            expires_at = time.time() + ttl_duration

            if key in self._map:
                node = self._map[key]
                node.value = value
                node.expires_at = expires_at
                self._move_to_head(node)
                return

            if len(self._map) >= self.capacity:
                evicted = self._evict_tail()
                if evicted and evicted.key in self._map:
                    del self._map[evicted.key]

            new_node = _Node(key, value, expires_at)
            self._map[key] = new_node
            self._add_to_head(new_node)

    async def delete(self, key: K) -> bool:
        """Explicitly remove key in O(1)."""
        async with self._lock:
            if key in self._map:
                node = self._map[key]
                self._remove_node(node)
                del self._map[key]
                return True
            return False

    def __len__(self) -> int:
        return len(self._map)

