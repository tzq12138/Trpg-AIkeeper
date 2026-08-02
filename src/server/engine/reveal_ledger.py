from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime
from typing import Any

from ..events.event_log import EventLog
from ..models import redact_citation
from .runtime_integrity import sanitize_checkpoint_value


_PLAYER_VISIBLE_CONTENT = {"public", "party", "player"}
_REVEAL_EVENT_TYPES = {
    "reveal": "s2c_fact_revealed",
    "correction": "s2c_fact_corrected",
    "safety_event": "s2c_fact_safety_event",
}
_REVEAL_CONDITION_KEYS = {
    "scene_ids",
    "entered_scenes",
    "scenes",
    "required_clue_ids",
    "all_clues",
    "required_event_types",
    "event_types",
}
_SAFE_REASON_CODE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,119}$")


class RevealPolicyError(ValueError):
    """A player-safe reveal rejection that never includes source content."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class RevealLedger:
    """Authoritative, append-only knowledge authorization for a room."""

    def __init__(self, conn):
        self.conn = conn

    def validate_proposals(
        self,
        *,
        room_id: str,
        actor_character_id: str,
        proposals: list[Any],
        executor=None,
    ) -> list[dict[str, Any]]:
        executor = executor or self.conn
        if not isinstance(proposals, list) or len(proposals) > 10:
            raise RevealPolicyError("reveal_proposals_invalid")
        self._require_actor(executor, room_id, actor_character_id)
        room = executor.execute(
            "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        scenario_version_id = str(
            room.get("scenario_version_id") if room else ""
        ).strip()
        if not scenario_version_id and proposals:
            raise RevealPolicyError("reveal_scenario_version_missing")

        validated: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for raw in proposals:
            proposal = self._proposal_dict(raw)
            audience = str(proposal.get("audience") or "party")
            if audience not in {"party", "player"}:
                raise RevealPolicyError("reveal_audience_invalid")
            row = self._load_content_item(
                executor,
                scenario_version_id,
                fact_id=str(proposal.get("fact_id") or "").strip(),
                content_item_id=str(
                    proposal.get("content_item_id") or ""
                ).strip(),
            )
            payload = _json_object(row.get("payload"))
            citation = _json_object(row.get("citation"))
            if not citation:
                raise RevealPolicyError("reveal_citation_missing")
            trigger_snapshot = self._validate_conditions(
                executor,
                room_id=room_id,
                actor_character_id=actor_character_id,
                audience=audience,
                item=row,
                payload=payload,
            )
            fact_id = str(row["content_item_id"])
            key = (fact_id, audience)
            if key in seen:
                continue
            seen.add(key)
            validated.append({
                "fact_id": fact_id,
                "content_item_id": str(row["content_item_id"]),
                "fact_text": self._fact_text(row, payload),
                "citation": citation,
                "audience": audience,
                "target_character_id": (
                    actor_character_id if audience == "player" else ""
                ),
                "trigger_snapshot": trigger_snapshot,
            })
        return validated

    def commit_proposals(
        self,
        *,
        room_id: str,
        source_action_id: str,
        actor_character_id: str,
        proposals: list[Any],
        state_version: int,
    ) -> list[dict[str, Any]]:
        validated = self.validate_proposals(
            room_id=room_id,
            actor_character_id=actor_character_id,
            proposals=proposals,
        )
        with self.conn.transaction() as transaction:
            return self.commit_validated(
                room_id=room_id,
                source_action_id=source_action_id,
                actor_character_id=actor_character_id,
                proposals=validated,
                state_version=state_version,
                executor=transaction,
            )

    def commit_validated(
        self,
        *,
        room_id: str,
        source_action_id: str,
        actor_character_id: str,
        proposals: list[Any],
        state_version: int,
        executor,
    ) -> list[dict[str, Any]]:
        if not source_action_id:
            raise RevealPolicyError("reveal_source_action_missing")
        self._require_actor(executor, room_id, actor_character_id)
        room = executor.execute(
            "SELECT state_version FROM rooms WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        if not room:
            raise RevealPolicyError("reveal_room_not_found")
        if int(room.get("state_version") or 0) != int(state_version):
            raise RevealPolicyError("reveal_state_version_stale")

        # Conditions and source content are checked again inside the write
        # transaction so an earlier validation cannot authorize stale data.
        canonical = self.validate_proposals(
            room_id=room_id,
            actor_character_id=actor_character_id,
            proposals=[
                {
                    "fact_id": self._proposal_dict(item).get("fact_id"),
                    "content_item_id": self._proposal_dict(item).get(
                        "content_item_id"
                    ),
                    "audience": self._proposal_dict(item).get(
                        "audience", "party"
                    ),
                }
                for item in proposals
            ],
            executor=executor,
        )
        records = []
        for proposal in canonical:
            existing = executor.execute(
                "SELECT * FROM fact_reveals WHERE room_id = %s "
                "AND source_action_id = %s AND fact_id = %s AND audience = %s "
                "AND target_character_id = %s AND record_kind = 'reveal'",
                (
                    room_id,
                    source_action_id,
                    proposal["fact_id"],
                    proposal["audience"],
                    proposal["target_character_id"],
                ),
            ).fetchone()
            if existing:
                records.append(_record_dict(existing))
                continue
            reveal_id = str(uuid.uuid4())
            event_payload = self._event_payload(
                reveal_id=reveal_id,
                proposal=proposal,
                status="revealed",
            )
            sequence = EventLog(executor).log_event(
                room_id,
                _REVEAL_EVENT_TYPES["reveal"],
                proposal["audience"],
                event_payload,
                commit=False,
                action_id=source_action_id,
                state_version=state_version,
            )
            executor.execute(
                "INSERT INTO fact_reveals "
                "(reveal_id, room_id, fact_id, content_item_id, fact_text, "
                "citation, audience, target_character_id, source_action_id, "
                "state_version, event_sequence, trigger_snapshot, record_kind, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "'reveal', 'revealed')",
                (
                    reveal_id,
                    room_id,
                    proposal["fact_id"],
                    proposal["content_item_id"],
                    proposal["fact_text"],
                    json.dumps(proposal["citation"], ensure_ascii=False),
                    proposal["audience"],
                    proposal["target_character_id"],
                    source_action_id,
                    int(state_version),
                    sequence,
                    json.dumps(
                        sanitize_checkpoint_value(
                            proposal.get("trigger_snapshot") or {}
                        ),
                        ensure_ascii=False,
                    ),
                ),
            )
            records.append({
                "reveal_id": reveal_id,
                "room_id": room_id,
                **proposal,
                "source_action_id": source_action_id,
                "state_version": int(state_version),
                "event_sequence": sequence,
                "record_kind": "reveal",
                "status": "revealed",
                "corrects_reveal_id": None,
                "reason_code": None,
            })
        return records

    def project_facts(
        self,
        room_id: str,
        *,
        audience: str,
        character_id: str | None = None,
        executor=None,
    ) -> list[dict[str, Any]]:
        history = self.project_history(
            room_id,
            audience=audience,
            character_id=character_id,
            executor=executor,
        )
        effective: dict[tuple[str, str, str], dict[str, Any]] = {}
        for record in history:
            key = (
                str(record.get("fact_id") or ""),
                str(record.get("audience") or ""),
                str(record.get("target_character_id") or ""),
            )
            effective[key] = record
        return sorted(
            effective.values(),
            key=lambda record: (
                int(record.get("event_sequence") or 0),
                str(record.get("reveal_id") or ""),
            ),
        )

    def project_history(
        self,
        room_id: str,
        *,
        audience: str,
        character_id: str | None = None,
        executor=None,
    ) -> list[dict[str, Any]]:
        executor = executor or self.conn
        if audience == "public":
            visibility_clause = "audience = 'party'"
            params: tuple[Any, ...] = (room_id,)
        elif audience in {"player", "director"}:
            if not character_id:
                raise RevealPolicyError("reveal_projection_character_required")
            visibility_clause = (
                "(audience = 'party' OR "
                "(audience = 'player' AND target_character_id = %s))"
            )
            params = (room_id, character_id)
        elif audience == "engine":
            visibility_clause = "TRUE"
            params = (room_id,)
        else:
            raise RevealPolicyError("reveal_projection_audience_invalid")
        rows = executor.execute(
            "SELECT * FROM fact_reveals WHERE room_id = %s AND "
            + visibility_clause
            + " ORDER BY event_sequence, reveal_id",
            params,
        ).fetchall()
        return [_record_dict(row) for row in rows]

    def append_correction(
        self,
        *,
        room_id: str,
        reveal_id: str,
        corrected_text: str,
        citation: dict[str, Any],
        source_action_id: str,
        state_version: int,
    ) -> dict[str, Any]:
        text = str(corrected_text or "").strip()
        if not text or len(text) > 4000 or not isinstance(citation, dict) or not citation:
            raise RevealPolicyError("reveal_correction_invalid")
        with self.conn.transaction() as transaction:
            original = self._load_original(transaction, room_id, reveal_id)
            return self._append_record(
                transaction,
                original=original,
                fact_text=text,
                citation=citation,
                source_action_id=source_action_id,
                state_version=state_version,
                record_kind="correction",
                status="corrected",
                reason_code="fact_corrected",
            )

    def flag_safety_event(
        self,
        *,
        room_id: str,
        reveal_id: str,
        reason_code: str,
        source_action_id: str,
        state_version: int,
    ) -> dict[str, Any]:
        safe_reason = str(reason_code or "").strip()
        if not _SAFE_REASON_CODE.fullmatch(safe_reason):
            raise RevealPolicyError("reveal_safety_reason_invalid")
        with self.conn.transaction() as transaction:
            original = self._load_original(transaction, room_id, reveal_id)
            return self._append_record(
                transaction,
                original=original,
                fact_text="",
                citation=_json_object(original.get("citation")),
                source_action_id=source_action_id,
                state_version=state_version,
                record_kind="safety_event",
                status="safety_flagged",
                reason_code=safe_reason,
            )

    def _append_record(
        self,
        executor,
        *,
        original: dict[str, Any],
        fact_text: str,
        citation: dict[str, Any],
        source_action_id: str,
        state_version: int,
        record_kind: str,
        status: str,
        reason_code: str,
    ) -> dict[str, Any]:
        if not str(source_action_id or "").strip():
            raise RevealPolicyError("reveal_source_action_missing")
        room = executor.execute(
            "SELECT state_version FROM rooms WHERE room_id = %s",
            (original["room_id"],),
        ).fetchone()
        if not room or int(room.get("state_version") or 0) != int(state_version):
            raise RevealPolicyError("reveal_state_version_stale")
        existing = executor.execute(
            "SELECT * FROM fact_reveals WHERE room_id = %s "
            "AND source_action_id = %s AND fact_id = %s AND audience = %s "
            "AND target_character_id = %s AND record_kind = %s",
            (
                original["room_id"],
                source_action_id,
                original["fact_id"],
                original["audience"],
                original.get("target_character_id") or "",
                record_kind,
            ),
        ).fetchone()
        if existing:
            existing_record = _record_dict(existing)
            if (
                existing_record.get("corrects_reveal_id")
                != original["reveal_id"]
                or existing_record.get("fact_text", "") != fact_text
                or existing_record.get("citation", {}) != citation
                or existing_record.get("reason_code") != reason_code
                or int(existing_record.get("state_version") or 0)
                != int(state_version)
            ):
                raise RevealPolicyError("reveal_idempotency_conflict")
            return existing_record
        new_id = str(uuid.uuid4())
        payload = {
            "revealId": new_id,
            "correctsRevealId": original["reveal_id"],
            "factId": original["fact_id"],
            "status": status,
            "reasonCode": reason_code,
        }
        if fact_text:
            payload["factText"] = fact_text
            payload["citation"] = redact_citation(citation)
        if original["audience"] == "player":
            payload["characterId"] = original.get("target_character_id") or ""
        sequence = EventLog(executor).log_event(
            original["room_id"],
            _REVEAL_EVENT_TYPES[record_kind],
            original["audience"],
            payload,
            commit=False,
            action_id=source_action_id,
            state_version=state_version,
        )
        executor.execute(
            "INSERT INTO fact_reveals "
            "(reveal_id, room_id, fact_id, content_item_id, fact_text, citation, "
            "audience, target_character_id, source_action_id, state_version, "
            "event_sequence, trigger_snapshot, record_kind, status, "
            "corrects_reveal_id, reason_code) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '{}', "
            "%s, %s, %s, %s)",
            (
                new_id,
                original["room_id"],
                original["fact_id"],
                original.get("content_item_id"),
                fact_text,
                json.dumps(citation, ensure_ascii=False),
                original["audience"],
                original.get("target_character_id") or "",
                source_action_id,
                int(state_version),
                sequence,
                record_kind,
                status,
                original["reveal_id"],
                reason_code,
            ),
        )
        return {
            "reveal_id": new_id,
            "room_id": original["room_id"],
            "fact_id": original["fact_id"],
            "content_item_id": original.get("content_item_id"),
            "fact_text": fact_text,
            "citation": citation,
            "audience": original["audience"],
            "target_character_id": original.get("target_character_id") or "",
            "source_action_id": source_action_id,
            "state_version": int(state_version),
            "event_sequence": sequence,
            "record_kind": record_kind,
            "status": status,
            "corrects_reveal_id": original["reveal_id"],
            "reason_code": reason_code,
        }

    @staticmethod
    def _proposal_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if hasattr(value, "model_dump"):
            dumped = value.model_dump(mode="json")
            return dumped if isinstance(dumped, dict) else {}
        raise RevealPolicyError("reveal_proposal_invalid")

    @staticmethod
    def _require_actor(executor, room_id: str, actor_character_id: str) -> None:
        actor = executor.execute(
            "SELECT 1 FROM characters WHERE room_id = %s AND character_id = %s "
            "AND status IN ('joined', 'ready', 'active')",
            (room_id, actor_character_id),
        ).fetchone()
        if not actor:
            raise RevealPolicyError("reveal_actor_invalid")

    @staticmethod
    def _load_content_item(
        executor,
        scenario_version_id: str,
        *,
        fact_id: str,
        content_item_id: str,
    ) -> dict[str, Any]:
        if content_item_id:
            row = executor.execute(
                "SELECT * FROM content_items WHERE scenario_version_id = %s "
                "AND content_item_id = %s",
                (scenario_version_id, content_item_id),
            ).fetchone()
            if not row:
                raise RevealPolicyError("reveal_fact_not_found")
            row = dict(row)
            if fact_id and fact_id not in {
                str(row.get("logical_key") or ""),
                str(row.get("content_item_id") or ""),
            }:
                raise RevealPolicyError("reveal_fact_reference_mismatch")
            return row
        if not fact_id:
            raise RevealPolicyError("reveal_fact_reference_missing")
        rows = executor.execute(
            "SELECT * FROM content_items WHERE scenario_version_id = %s "
            "AND (logical_key = %s OR content_item_id = %s) "
            "ORDER BY CASE WHEN content_item_id = %s THEN 0 "
            "WHEN item_type = 'fact' THEN 1 ELSE 2 END LIMIT 2",
            (scenario_version_id, fact_id, fact_id, fact_id),
        ).fetchall()
        if not rows:
            raise RevealPolicyError("reveal_fact_not_found")
        if len(rows) > 1 and str(rows[0].get("content_item_id")) != fact_id:
            raise RevealPolicyError("reveal_fact_ambiguous")
        return dict(rows[0])

    def _validate_conditions(
        self,
        executor,
        *,
        room_id: str,
        actor_character_id: str,
        audience: str,
        item: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        scene_row = executor.execute(
            "SELECT current_scene FROM room_scene_state WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        current_scene = str(
            scene_row.get("current_scene") if scene_row else ""
        ).strip()
        has_reveal_conditions = "reveal_conditions" in payload
        has_unlock_conditions = "unlock_conditions" in payload
        if has_reveal_conditions:
            raw_conditions = payload.get("reveal_conditions")
        elif has_unlock_conditions:
            raw_conditions = payload.get("unlock_conditions")
        else:
            raw_conditions = None
        if has_reveal_conditions or has_unlock_conditions:
            if not isinstance(raw_conditions, dict) or not raw_conditions:
                raise RevealPolicyError("reveal_conditions_invalid")
            if set(raw_conditions) - _REVEAL_CONDITION_KEYS:
                raise RevealPolicyError("reveal_conditions_invalid")
            for value in raw_conditions.values():
                if (
                    not isinstance(value, list)
                    or not value
                    or any(not isinstance(item, str) or not item.strip() for item in value)
                ):
                    raise RevealPolicyError("reveal_conditions_invalid")
            conditions = raw_conditions
        else:
            conditions = {}

        scene_ids = _string_list(
            conditions.get("scene_ids")
            or conditions.get("entered_scenes")
            or conditions.get("scenes")
        )
        if scene_ids and current_scene not in scene_ids:
            raise RevealPolicyError("reveal_condition_unmet")

        required_clues = _string_list(
            conditions.get("required_clue_ids")
            or conditions.get("all_clues")
        )
        if required_clues:
            if audience == "party":
                rows = executor.execute(
                    "SELECT clue_id FROM clue_shares WHERE room_id = %s",
                    (room_id,),
                ).fetchall()
            else:
                rows = executor.execute(
                    "SELECT clue_id FROM clues WHERE room_id = %s "
                    "AND character_id = %s UNION SELECT clue_id FROM clue_shares "
                    "WHERE room_id = %s",
                    (room_id, actor_character_id, room_id),
                ).fetchall()
            known = {str(row["clue_id"]) for row in rows}
            if not set(required_clues).issubset(known):
                raise RevealPolicyError("reveal_condition_unmet")

        required_events = _string_list(
            conditions.get("required_event_types")
            or conditions.get("event_types")
        )
        if required_events:
            rows = executor.execute(
                "SELECT DISTINCT event_type FROM events WHERE room_id = %s "
                "AND event_type = ANY(%s)",
                (room_id, required_events),
            ).fetchall()
            present = {str(row["event_type"]) for row in rows}
            if not set(required_events).issubset(present):
                raise RevealPolicyError("reveal_condition_unmet")

        visibility = str(item.get("visibility") or "host_only")
        if not conditions and visibility not in _PLAYER_VISIBLE_CONTENT:
            item_scene_ids = {
                str(item.get("logical_key") or "").strip(),
                str(payload.get("scene_id") or "").strip(),
                str(payload.get("location_id") or "").strip(),
                str(payload.get("node_id") or "").strip(),
            }
            item_scene_ids.discard("")
            if not current_scene or current_scene not in item_scene_ids:
                raise RevealPolicyError("reveal_condition_unmet")

        return sanitize_checkpoint_value({
            "current_scene": current_scene,
            "scene_ids": scene_ids,
            "required_clue_ids": required_clues,
            "required_event_types": required_events,
            "source_visibility": visibility,
        })

    @staticmethod
    def _fact_text(item: dict[str, Any], payload: dict[str, Any]) -> str:
        for key in (
            "fact_text",
            "text",
            "statement",
            "description",
            "summary",
            "public_description",
        ):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:4000]
        return str(item.get("title") or item.get("logical_key") or "")[:4000]

    @staticmethod
    def _event_payload(
        *, reveal_id: str, proposal: dict[str, Any], status: str
    ) -> dict[str, Any]:
        payload = {
            "revealId": reveal_id,
            "factId": proposal["fact_id"],
            "contentItemId": proposal["content_item_id"],
            "factText": proposal["fact_text"],
            "citation": redact_citation(proposal["citation"]),
            "status": status,
        }
        if proposal["audience"] == "player":
            payload["characterId"] = proposal["target_character_id"]
        return payload

    @staticmethod
    def _load_original(executor, room_id: str, reveal_id: str) -> dict[str, Any]:
        row = executor.execute(
            "SELECT * FROM fact_reveals WHERE room_id = %s AND reveal_id = %s",
            (room_id, reveal_id),
        ).fetchone()
        if not row:
            raise RevealPolicyError("reveal_record_not_found")
        return dict(row)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _record_dict(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["citation"] = _json_object(result.get("citation"))
    result["trigger_snapshot"] = _json_object(result.get("trigger_snapshot"))
    created_at = result.get("created_at")
    if isinstance(created_at, (datetime, date)):
        result["created_at"] = created_at.isoformat()
    return result
