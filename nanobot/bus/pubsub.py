"""Lightweight asyncio pubsub event bus for nanobot internal events."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Callable

log = logging.getLogger(__name__)

# Built-in event types published by nanobot
EVENT_SESSION_MESSAGE = "session.message"   # new inbound message
EVENT_SESSION_RESPONSE = "session.response"  # agent response complete
EVENT_TOOL_EXECUTED = "tool.executed"        # tool call finished


class EventBus:
    """Global asyncio pubsub.  Callbacks run as fire-and-forget tasks.

    Usage::

        bus = EventBus.instance()

        # Subscribe
        unsub = bus.subscribe("tool.executed", my_callback)

        # Publish  (from async context)
        await bus.publish("tool.executed", {"name": "shell", "status": "ok"})

        # Unsubscribe
        unsub()
    """

    _instance: EventBus | None = None

    def __init__(self) -> None:
        self._typed: dict[str, list[Callable]] = defaultdict(list)
        self._wildcard: list[Callable] = []

    @classmethod
    def instance(cls) -> EventBus:
        """Return the process-wide singleton."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (useful in tests)."""
        cls._instance = None

    # ------------------------------------------------------------------
    # Subscribe
    # ------------------------------------------------------------------

    def subscribe(self, event_type: str, callback: Callable) -> Callable:
        """Subscribe to a specific event type.  Returns an unsubscribe callable."""
        self._typed[event_type].append(callback)

        def _unsub() -> None:
            try:
                self._typed[event_type].remove(callback)
            except ValueError:
                pass

        return _unsub

    def subscribe_all(self, callback: Callable) -> Callable:
        """Subscribe to every event.  Returns an unsubscribe callable."""
        self._wildcard.append(callback)

        def _unsub() -> None:
            try:
                self._wildcard.remove(callback)
            except ValueError:
                pass

        return _unsub

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    async def publish(self, event_type: str, payload: dict) -> None:
        """Fire-and-forget: schedule all matching callbacks as asyncio tasks."""
        callbacks = list(self._typed.get(event_type, [])) + list(self._wildcard)
        for cb in callbacks:
            asyncio.create_task(self._safe_call(cb, event_type, payload))

    async def publish_sync(self, event_type: str, payload: dict) -> None:
        """Await each callback sequentially (for ordered processing)."""
        for cb in list(self._typed.get(event_type, [])) + list(self._wildcard):
            await self._safe_call(cb, event_type, payload)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    async def _safe_call(cb: Callable, event_type: str, payload: dict) -> None:
        try:
            result = cb(event_type, payload)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:  # noqa: BLE001
            log.error("EventBus callback error (%s): %s", event_type, exc)
