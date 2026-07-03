import json
import uuid
import logging
from typing import Any

from .engine.engine import Engine
from .engine.resolution_pipeline import ResolutionPipeline
from .models import PlayerIntent

logger = logging.getLogger(__name__)


class GameLoop:
    """Optional turn-processing orchestrator.

    When agent_enabled, this provides an alternative resolution path that uses
    the GameAgent for narrative generation. It does NOT replace the existing
    ResolutionPipeline — it wraps it with agent-enhanced narrative output.
    """

    def __init__(
        self,
        conn,
        engine: Engine,
        pipeline: ResolutionPipeline,
    ):
        self.conn = conn
        self.engine = engine
        self.pipeline = pipeline

    async def process_turn(self, room_id: str) -> dict[str, Any]:
        """Process all queued actions for a room sequentially."""
        queued = self.conn.execute(
            "SELECT * FROM actions WHERE room_id = %s AND status = 'queued' ORDER BY created_at",
            (room_id,),
        ).fetchall()

        if not queued:
            return {"status": "no_actions", "room_id": room_id}

        room = self.conn.execute(
            "SELECT * FROM rooms WHERE room_id = %s", (room_id,)
        ).fetchone()
        if not room:
            return {"status": "room_not_found", "room_id": room_id}

        # Mark all queued actions as resolving
        for action in queued:
            self.conn.execute(
                "UPDATE actions SET status = 'resolving' WHERE action_id = %s",
                (action["action_id"],),
            )
        self.conn.commit()

        results = []
        for action in queued:
            resolution_result = await self.pipeline.resolve_action(action["action_id"])
            results.append({
                "action_id": action["action_id"],
                "status": "resolved",
                "result": resolution_result,
            })

        return {
            "status": "resolved",
            "room_id": room_id,
            "actions_processed": len(queued),
            "results": results,
        }

    def submit_player_action(
        self,
        room_id: str,
        character_id: str,
        declared_intent: str,
        intent_type: str = "dialogue",
        params: dict[str, Any] | None = None,
    ) -> dict:
        """Submit a player action through the engine (same as current flow)."""
        intent = PlayerIntent(
            action_id=str(uuid.uuid4()),
            intent_type=intent_type,
            declared_intent=declared_intent,
            params=params or {},
        )
        return self.engine.submit_intent(room_id, character_id, intent)
