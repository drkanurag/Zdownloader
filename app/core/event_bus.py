import asyncio
import threading
from typing import Callable, Dict, List, Type, Any
from app.domain.events import BaseEvent

EventHandler = Callable[[Any], Any]

class EventBus:
    """
    Publish/Subscribe Event Bus.
    Decouples bounded contexts, microservices, and presentation layers.
    """
    def __init__(self):
        self._subscribers: Dict[Type[BaseEvent], List[EventHandler]] = {}
        self._lock = threading.Lock()

    def subscribe(self, event_type: Type[BaseEvent], handler: EventHandler) -> None:
        """Register a handler for a specific event type."""
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(handler)

    async def publish(self, event: BaseEvent) -> None:
        """Publish an event to all registered listeners asynchronously."""
        event_cls = type(event)
        with self._lock:
            handlers = list(self._subscribers.get(event_cls, []))

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    asyncio.create_task(handler(event))
                else:
                    handler(event)
            except Exception as e:
                print(f"[EventBus Error] Handler {handler} failed on {event_cls.__name__}: {e}")

event_bus = EventBus()

