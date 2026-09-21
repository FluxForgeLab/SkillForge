"""In-process async event bus for trace events."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from skillforge.domain.entities import TraceEvent

Subscriber = Callable[[TraceEvent], Awaitable[None]]


class EventBus:
    """Async pub/sub for TraceEvent within a single process."""

    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []

    def subscribe(self, handler: Subscriber) -> Callable[[], None]:
        self._subscribers.append(handler)

        def unsubscribe() -> None:
            if handler in self._subscribers:
                self._subscribers.remove(handler)

        return unsubscribe

    async def publish(self, event: TraceEvent) -> None:
        if not self._subscribers:
            return
        await asyncio.gather(*(handler(event) for handler in list(self._subscribers)))
