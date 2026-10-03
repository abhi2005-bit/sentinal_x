"""
SENTINEL-X — WebSocket Transport.

Streams events from the EventBus to connected frontend clients.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from sentinel_x.services.event_bus import EventBus


logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])

# Global event bus instance for the FastAPI app
_BUS = EventBus()


def get_bus() -> EventBus:
    """Return the global event bus."""
    return _BUS


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for a specific session.
    Subscribes to the EventBus and streams all events.
    """
    await websocket.accept()
    queue = _BUS.subscribe(session_id)
    
    # Push history first so reconnecting clients get up to speed
    history = _BUS.history_dicts(session_id)
    if history:
        try:
            await websocket.send_json({"type": "history", "events": history})
        except Exception:
            _BUS.unsubscribe(session_id, queue)
            return

    try:
        while True:
            # Wait for next event from the bus
            event = await queue.get()
            await websocket.send_json(event.to_dict())
            
    except WebSocketDisconnect:
        logger.info(f"Client disconnected from session {session_id}")
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"WebSocket error for {session_id}: {e}")
    finally:
        _BUS.unsubscribe(session_id, queue)
