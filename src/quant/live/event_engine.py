from typing import Any, Callable, Dict, List

from ..enums import EventType


class EventEngine:
    def __init__(self) -> None:
        self._handlers: Dict[EventType, List[Callable[[Any], None]]] = {}

    def register(self, event_type: EventType, handler: Callable[[Any], None]) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def trigger(self, event_type: EventType, data: Any) -> None:
        for handler in self._handlers.get(event_type, []):
            handler(data)
