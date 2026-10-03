"""
SENTINEL-X — Real-time Event Bus.

A lightweight in-process pub/sub bus that streams state-transition
events to WebSocket clients and any other subscriber.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional


class SystemEventType(str, Enum):
    """All event types that flow through the bus (doc §10.3)."""
    SESSION_STARTED = "SESSION_STARTED"
    TASK_STARTED = "TASK_STARTED"
    TASK_COMPLETED = "TASK_COMPLETED"
    INTERRUPT_RECEIVED = "INTERRUPT_RECEIVED"
    IMPACT_ANALYZED = "IMPACT_ANALYZED"
    INTERVENTION_CANDIDATES_GENERATED = "INTERVENTION_CANDIDATES_GENERATED"
    INTERVENTION_SELECTED = "INTERVENTION_SELECTED"
    TASK_PRESERVED = "TASK_PRESERVED"
    TASK_INVALIDATED = "TASK_INVALIDATED"
    TASK_PREEMPTED = "TASK_PREEMPTED"
    EFFECT_UPDATED = "EFFECT_UPDATED"
    EXTERNAL_STATE_VERIFIED = "EXTERNAL_STATE_VERIFIED"
    REPLAN_STARTED = "REPLAN_STARTED"
    REPLAN_COMPLETED = "REPLAN_COMPLETED"
    SESSION_RESUMED = "SESSION_RESUMED"
    # Extra utility events
    SESSION_ERROR = "SESSION_ERROR"
    TASK_CANCELLED = "TASK_CANCELLED"


class SystemEvent:
    """A single event published on the bus."""

    def __init__(
        self,
        event_type: SystemEventType,
        session_id: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.event_type = event_type
        self.session_id = session_id
        self.data = data or {}
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type.value,
            "session_id": self.session_id,
            "data": self.data,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


class EventBus:
    """
    Async event bus for broadcasting system events.

    Subscribers are per-session async queues.  The bus also
    keeps a full history so reconnecting clients can replay.
    """

    def __init__(self) -> None:
        # session_id → list of subscriber queues
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        # session_id → event history
        self._history: dict[str, list[SystemEvent]] = {}

    async def publish(self, event: SystemEvent) -> None:
        """Publish an event to all subscribers of the session."""
        sid = event.session_id

        # Record in history
        if sid not in self._history:
            self._history[sid] = []
        self._history[sid].append(event)

        # Deliver to subscribers
        for queue in self._subscribers.get(sid, []):
            await queue.put(event)

    def subscribe(self, session_id: str) -> asyncio.Queue:
        """
        Create a new subscription for a session.
        Returns an asyncio.Queue that will receive events.
        """
        if session_id not in self._subscribers:
            self._subscribers[session_id] = []
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[session_id].append(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        """Remove a subscriber queue."""
        subs = self._subscribers.get(session_id, [])
        if queue in subs:
            subs.remove(queue)

    def history(self, session_id: str) -> list[SystemEvent]:
        """Return the full event history for a session."""
        return self._history.get(session_id, [])

    def history_dicts(self, session_id: str) -> list[dict]:
        """Return history as JSON-serializable dicts."""
        return [e.to_dict() for e in self.history(session_id)]

    def clear_session(self, session_id: str) -> None:
        """Remove all state for a session."""
        self._subscribers.pop(session_id, None)
        self._history.pop(session_id, None)
