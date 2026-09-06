"""Best-effort live WebSocket dispatch for events that were persisted through
EventLog without a ProjectionDispatcher (R7 notification contract).

The pipeline's `ProjectionDispatcher.emit` both persists a row AND pushes it
live in one call. Events persisted outside the pipeline (system integrity
pauses, system recovery milestones, automatic review terminals) used to stop
at the EventLog row: reconnect/catch-up saw them, live sockets did not.

This module closes that gap with a fire-and-forget helper with explicit,
audience-scoped delivery (never a room-wide fan-out for host events):

  - audience="party"            -> every connection of the room (host + players)
  - audience="host"             -> ONLY the Owner console connection
                                   (manager.send_event to "host", never a
                                   broadcast that player sockets could see)
  - audience="player"           -> ONLY the owning player's connection; a
                                   player event without character_id stays
                                   catch-up-only (fail-closed, no fan-out)
  - audience="system"           -> audit/catch-up row only, nothing live

The row (EventLog) remains the source of truth: the WebSocket event only
triggers a refresh, and GET-based catch-up is the durable path. Dispatch is
skipped entirely when no event loop is running (sync/test contexts), and a
stale or closed socket never raises.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..host.ws_manager import manager
from ..models import EngineEvent

logger = logging.getLogger(__name__)


def push_live_event(
    room_id: str,
    event_type: str,
    audience: str,
    payload: dict[str, Any],
    *,
    character_id: str | None = None,
    sequence: int = 0,
) -> bool:
    """Queue one live EngineEvent to the room's connected sockets.

    Args:
        room_id: room scope.
        event_type: an EngineEventType literal (validated at build time).
        audience: host / player / party / system.
        payload: SANITIZED payload — never include internal prompt text,
            evidence content or private objection text (the row is the truth
            and the socket is only a refresh trigger).
        character_id: required for audience="player".
        sequence: EventLog row sequence when already known (else 0).
    Returns:
        True when a live dispatch was queued; False when the context has no
        event loop (test/sync) or the event failed validation.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    try:
        event = EngineEvent(
            roomId=room_id,
            type=event_type,
            roomSequence=sequence,
            audience=audience,
            payload=payload,
        )
    except Exception as build_err:
        logger.error(
            "push_live_event: invalid EngineEvent type=%s audience=%s room=%s: %s",
            event_type,
            audience,
            room_id,
            build_err,
        )
        return False
    try:
        asyncio.get_running_loop().create_task(
            _deliver(room_id, audience, character_id, event)
        )
    except RuntimeError:
        return False
    return True


async def _deliver(
    room_id: str,
    audience: str,
    character_id: str | None,
    event: EngineEvent,
) -> None:
    try:
        if audience == "player":
            # Owner-scoped notice: only the named character's socket receives
            # it. A player event WITHOUT a character id is ambiguous and is
            # NEVER widened to the whole room — it stays catch-up-only
            # (fail-closed: the EventLog row remains the durable contract).
            if character_id:
                await manager.send_event(room_id, f"player:{character_id}", event)
                return
            logger.warning(
                "push_live_event: player event without character_id is "
                "catch-up-only room=%s type=%s",
                room_id,
                event.type,
            )
            return
        if audience == "host":
            # Explicit owner-console delivery; never broadcast host events to
            # player sockets (the ws_manager filters on audience today, but
            # the delivery path should not depend on that filter).
            await manager.send_event(room_id, "host", event)
            return
        if audience == "party":
            await manager.broadcast_to_room(room_id, event)
        # audience="system" is catch-up/audit only: nothing is pushed live.
    except Exception as exc:
        logger.debug(
            "push_live_event: deliver failed room=%s type=%s: %s",
            room_id,
            event.type,
            type(exc).__name__,
        )
