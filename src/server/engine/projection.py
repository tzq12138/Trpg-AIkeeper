import json
import logging
from typing import Any

from ..models import EngineEvent
from ..events.event_log import EventLog, FACT_REVEAL_EVENT_KINDS
from ..host.ws_manager import manager as default_ws_manager
from ..redis_cache import RedisCache

logger = logging.getLogger(__name__)


class ProjectionBuilder:
    def build(self, event: EngineEvent) -> list[EngineEvent]:
        projections = []
        if event.audience == "host":
            projections.append(event)
        elif event.audience == "player":
            projections.append(event)
        elif event.audience == "party":
            projections.append(event.model_copy(update={"audience": "host"}))
            projections.append(event.model_copy(update={"audience": "player"}))
        elif event.audience == "system":
            projections.append(event)
        return projections


class ProjectionDispatcher:
    def __init__(self, conn, ws_manager=default_ws_manager, cache: RedisCache | None = None,
                 spoiler_guard=None):
        self.conn = conn
        self.ws_manager = ws_manager
        self.cache = cache or RedisCache("")
        self.spoiler_guard = spoiler_guard

    async def emit(
        self,
        room_id: str,
        event_type: str,
        audience: str,
        payload: dict[str, Any],
        character_id: str | None = None,
        _skip_spoiler_check: bool = False,
    ):
        if event_type.startswith("s2c_fact_"):
            raise ValueError("fact_event_requires_reveal_ledger")

        if audience == "player" and character_id:
            payload = {**payload, "characterId": character_id}

        # ── SpoilerGuard safety-net scan ──
        if not _skip_spoiler_check and audience in ("player", "party") and self.spoiler_guard:
            payload = await self._scan_payload_for_spoilers(
                room_id, event_type, audience, payload, character_id,
            )

        sequence = EventLog(self.conn).log_event(
            room_id,
            event_type,
            audience,
            payload,
        )

        logger.debug("emit: seq=%s type=%s audience=%s room=%s char=%s",
                     sequence, event_type, audience, room_id, character_id or "-")

        try:
            event = EngineEvent(
                roomId=room_id,
                type=event_type,
                roomSequence=sequence,
                audience=audience,
                payload=payload,
            )
        except Exception as build_err:
            logger.error("emit: invalid EngineEvent type=%s audience=%s room=%s: %s",
                         event_type, audience, room_id, build_err)
            return

        if audience == "player" and character_id:
            await self.ws_manager.send_event(room_id, f"player:{character_id}", event)
            return
        await self.ws_manager.broadcast_to_room(room_id, event)

    async def publish_committed_fact_event(
        self,
        room_id: str,
        sequence: int,
    ) -> bool:
        """Publish an already committed fact event after exact ledger validation."""
        row = self.conn.execute(
            "SELECT sequence, room_id, event_type, audience, payload, action_id, "
            "state_version FROM events WHERE room_id = %s AND sequence = %s",
            (room_id, sequence),
        ).fetchone()
        if not row or row.get("event_type") not in FACT_REVEAL_EVENT_KINDS:
            return False
        payload = row.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                return False
        if not isinstance(payload, dict):
            return False
        character_id = str(
            payload.get("characterId") or payload.get("character_id") or ""
        )
        if not EventLog(self.conn)._ledger_authorizes_event(
            row["sequence"],
            row["event_type"],
            row["audience"],
            character_id or None,
            payload,
            row.get("action_id"),
            row.get("state_version"),
            row.get("room_id"),
        ):
            return False
        try:
            event = EngineEvent(
                roomId=room_id,
                type=row["event_type"],
                roomSequence=row["sequence"],
                audience=row["audience"],
                payload=payload,
            )
        except Exception:
            logger.exception(
                "publish_committed_fact_event: invalid event room=%s sequence=%s",
                room_id,
                sequence,
            )
            return False
        if row["audience"] == "player":
            if not character_id:
                return False
            await self.ws_manager.send_event(
                room_id,
                f"player:{character_id}",
                event,
            )
        elif row["audience"] == "party":
            await self.ws_manager.broadcast_to_room(room_id, event)
        else:
            return False
        return True

    async def publish_committed_event(
        self,
        room_id: str,
        sequence: int,
    ) -> bool:
        """Publish one already committed non-fact event without logging it twice."""
        row = self.conn.execute(
            "SELECT sequence, room_id, event_type, audience, payload "
            "FROM events WHERE room_id = %s AND sequence = %s",
            (room_id, sequence),
        ).fetchone()
        if not row:
            return False
        if row.get("event_type") in FACT_REVEAL_EVENT_KINDS:
            return await self.publish_committed_fact_event(room_id, sequence)
        payload = row.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                return False
        if not isinstance(payload, dict):
            return False
        try:
            event = EngineEvent(
                roomId=room_id,
                type=row["event_type"],
                roomSequence=row["sequence"],
                audience=row["audience"],
                payload=payload,
            )
        except Exception:
            logger.exception(
                "publish_committed_event: invalid event room=%s sequence=%s",
                room_id,
                sequence,
            )
            return False
        if row["audience"] == "player":
            character_id = str(
                payload.get("characterId") or payload.get("character_id") or ""
            )
            if not character_id:
                return False
            await self.ws_manager.send_event(
                room_id,
                f"player:{character_id}",
                event,
            )
        else:
            await self.ws_manager.broadcast_to_room(room_id, event)
        return True

    async def _scan_payload_for_spoilers(
        self,
        room_id: str,
        event_type: str,
        audience: str,
        payload: dict[str, Any],
        character_id: str | None,
    ) -> dict[str, Any]:
        """Safety-net: scan payload string fields for spoiler content.

        Unlike the pipeline-level check, this does NOT retry — it only redacts.
        """
        try:
            # Build a lightweight index from the room's scenario
            room = self.conn.execute(
                "SELECT scenario_id FROM rooms WHERE room_id = %s", (room_id,),
            ).fetchone()
            if not room or not room.get("scenario_id"):
                return payload

            scenario_id = room["scenario_id"]
            index = self.spoiler_guard.load_index(scenario_id)
            if not index:
                return payload

            unlock = self.spoiler_guard.compute_unlock_state(room_id)

            # Scan all string values in payload
            modified = False
            scanned = self._scan_dict(payload, audience, character_id, unlock, index)
            if scanned != payload:
                modified = True
                payload = scanned

            if modified:
                # Log as safety-net redaction
                try:
                    self.spoiler_guard.log_audit(
                        room_id, "", json.dumps(payload, ensure_ascii=False),
                        [], 1, "redacted_safety_net",
                        json.dumps(payload, ensure_ascii=False), unlock,
                    )
                except Exception:
                    pass
        except Exception:
            pass  # Safety net must never break delivery

        return payload

    def _scan_dict(
        self,
        obj: Any,
        audience: str,
        character_id: str | None,
        unlock,
        index: list,
    ) -> Any:
        """Recursively scan a dict/list/str for spoiler content."""
        REDACTED = "[内容已由剧透保护系统过滤]"

        if isinstance(obj, dict):
            result = {}
            for key, value in obj.items():
                if isinstance(value, str) and len(value) > 10:
                    review = self.spoiler_guard.review(
                        value, audience, character_id, unlock, index,
                    )
                    if not review.allowed:
                        result[key] = REDACTED
                    else:
                        result[key] = value
                elif isinstance(value, (dict, list)):
                    result[key] = self._scan_dict(value, audience, character_id, unlock, index)
                else:
                    result[key] = value
            return result

        if isinstance(obj, list):
            return [self._scan_dict(item, audience, character_id, unlock, index) for item in obj]

        return obj
