"""Background enforcement for expired combat declaration windows."""
from __future__ import annotations

import asyncio
import logging

from .player.router_player import _settle_turn_background
from .turn_manager import TurnManager

logger = logging.getLogger(__name__)


async def apply_expired_turns_once(app) -> list[dict]:
    pg_db = getattr(app.state, "pg_db", None)
    conn = pg_db.get_connection() if pg_db else app.state.db
    try:
        turn_manager = TurnManager(conn)
        applied = turn_manager.apply_expired_absence_policies()
        for item in applied:
            if turn_manager.all_submitted(item["room_id"]):
                asyncio.create_task(
                    _settle_turn_background(app, item["room_id"], item["turn_id"])
                )
        return applied
    finally:
        if pg_db:
            conn.close()


async def run_turn_timeout_worker(app, stop_event: asyncio.Event, interval_seconds: float = 5.0) -> None:
    while not stop_event.is_set():
        try:
            await apply_expired_turns_once(app)
        except Exception:
            logger.exception("Expired combat turn scan failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue
