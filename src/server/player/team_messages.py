"""Shared delivery for player-authored, out-of-world team messages."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from ..engine.projection import ProjectionDispatcher


ALLOWED_TEAM_MESSAGE_SOURCES = {"text", "voice"}
MAX_TEAM_MESSAGE_LENGTH = 2_000
_team_message_rates: dict[str, list[float]] = {}


class TeamMessageError(ValueError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _check_rate(character_id: str, max_per_second: int = 3) -> bool:
    now = time.monotonic()
    recent = [stamp for stamp in _team_message_rates.get(character_id, []) if now - stamp < 1.0]
    if len(recent) >= max_per_second:
        _team_message_rates[character_id] = recent
        return False
    recent.append(now)
    _team_message_rates[character_id] = recent
    return True


def _investigator_name(character: dict[str, Any]) -> str:
    xlsx_data = character.get("xlsx_data") or {}
    if isinstance(xlsx_data, str):
        try:
            xlsx_data = json.loads(xlsx_data)
        except json.JSONDecodeError:
            xlsx_data = {}
    return str(xlsx_data.get("name") or "") if isinstance(xlsx_data, dict) else ""


async def send_team_message(
    conn,
    *,
    dispatcher: ProjectionDispatcher | None,
    character: dict[str, Any],
    text: str,
    source: str = "text",
    message_id: str | None = None,
    channel: str = "party_chat",
) -> dict[str, Any]:
    message = str(text or "").strip()
    if not message:
        raise TeamMessageError(400, "text is required")
    if len(message) > MAX_TEAM_MESSAGE_LENGTH:
        raise TeamMessageError(400, f"text exceeds {MAX_TEAM_MESSAGE_LENGTH} characters")
    if source not in ALLOWED_TEAM_MESSAGE_SOURCES:
        raise TeamMessageError(
            400,
            f"source must be one of: {', '.join(sorted(ALLOWED_TEAM_MESSAGE_SOURCES))}",
        )
    if not _check_rate(str(character["character_id"])):
        raise TeamMessageError(429, "Too many messages — slow down")

    payload = {
        "messageId": message_id or str(uuid.uuid4()),
        "characterId": character["character_id"],
        "playerName": character.get("player_name", ""),
        "investigatorName": _investigator_name(character),
        "text": message,
        "source": source,
        "channel": channel,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    await (dispatcher or ProjectionDispatcher(conn)).emit(
        character["room_id"],
        "s2c_team_message",
        "party",
        payload,
    )
    return payload
