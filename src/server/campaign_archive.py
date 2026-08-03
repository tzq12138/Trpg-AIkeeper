import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from .engine.action_lifecycle import complete_action
from .events.event_log import EventLog
from .models import CampaignEnding, CampaignSummary, CampaignArchiveQuery, EventLogEntry
from .events.events_registry import event_type


NONTERMINAL_CAMPAIGN_ACTION_STATUSES = (
    "analyzing",
    "awaiting_confirmation",
    "awaiting_player_consent",
    "armed",
    "queued",
    "batched",
    "resolving",
    "awaiting_player_choice",
    "awaiting_host_exception",
    "sync_required",
)


class CampaignReadOnlyError(RuntimeError):
    pass


@dataclass(frozen=True)
class CampaignFinalization:
    archive_id: str
    canceled_action_ids: tuple[str, ...]
    state_version: int
    ending_event_sequence: int | None = None
    resolution_bundle: dict[str, Any] | None = None


class CampaignArchive:
    def __init__(self, conn):
        self.conn = conn

    def generate_ending(
        self,
        room_id: str,
        *,
        ending_event_payload: dict[str, Any] | None = None,
    ) -> CampaignEnding:
        with self.conn.transaction() as tx:
            room = tx.execute(
                "SELECT room_id, status FROM rooms WHERE room_id = %s FOR UPDATE",
                (room_id,),
            ).fetchone()
            if not room:
                raise CampaignReadOnlyError("campaign_room_missing")
            if str(room.get("status") or "") == "completed":
                raise CampaignReadOnlyError("campaign_already_completed")

            events = self._get_all_events(room_id, executor=tx)
            public_events = [
                event
                for event in events
                if str(event.get("audience") or "") in {"party", "system"}
            ]
            characters = tx.execute(
                "SELECT * FROM characters WHERE room_id = %s ORDER BY character_id",
                (room_id,),
            ).fetchall()
            ending_type = str(
                (ending_event_payload or {}).get("ending_type")
                or self._determine_ending_type(public_events)
            )
            ending = CampaignEnding(
                ending_type=ending_type,
                summary=self._build_summary(room_id, public_events, characters),
                highlights=self._extract_highlights(public_events),
                character_arcs=self._build_character_arcs(
                    room_id,
                    characters,
                    executor=tx,
                ),
            )

            finalized = finalize_campaign(
                self.conn,
                room_id,
                ending_type=ending.ending_type,
                summary=ending.summary,
                highlights=ending.highlights,
                character_arcs=ending.character_arcs,
                expected_room_statuses=("lobby", "suggested", "active", "paused"),
                ending_event_payload=ending_event_payload,
                transaction=tx,
            )
            if finalized is None:
                raise CampaignReadOnlyError("campaign_already_completed")

        return ending

    def get_campaign_summary(
        self,
        room_id: str,
        *,
        character_id: str | None = None,
    ) -> CampaignSummary:
        room = self.conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
        if not room:
            raise ValueError(f"Room {room_id} not found")

        actions = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM actions WHERE room_id = %s", (room_id,)
        ).fetchone()
        events = self._get_all_events(room_id)
        if character_id:
            event_log = EventLog(self.conn)
            events = [
                event
                for event in events
                if event_log._can_player_see_event(
                    str(event.get("event_type") or ""),
                    str(event.get("audience") or ""),
                    _json_value(event.get("payload")),
                    character_id,
                    event.get("sequence"),
                    event.get("action_id"),
                    event.get("state_version"),
                    event.get("room_id"),
                )
            ]

        duration = 0
        if room["started_at"]:
            start = _datetime_value(room["started_at"])
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            duration = int((now - start).total_seconds())

        key_events = [
            {"sequence": e["sequence"], "type": e["event_type"], "timestamp": e["issued_at"]}
            for e in events
            if e["event_type"] in (event_type("s2c_campaign_ended"), event_type("s2c_reveal_transaction"), event_type("s2c_scene_sync"))
        ]

        ending = None
        archive_row = self.conn.execute(
            "SELECT * FROM campaign_archives WHERE room_id = %s ORDER BY created_at DESC LIMIT 1",
            (room_id,),
        ).fetchone()
        if archive_row:
            projection = project_campaign_archive(
                archive_row,
                scope="player" if character_id else "full",
                character_id=character_id,
            )
            if character_id:
                own_arc = projection.get("character_arc")
                character_arcs = [own_arc] if own_arc else []
            else:
                character_arcs = projection["character_arcs"]
            ending = CampaignEnding(
                ending_type=projection["ending_type"],
                summary=projection["summary"],
                highlights=projection["highlights"],
                character_arcs=character_arcs,
            )

        return CampaignSummary(
            room_id=room_id,
            duration_seconds=duration,
            total_actions=actions["cnt"],
            clues_found=0,
            key_events=key_events,
            ending=ending,
        )

    def query_archive(self, room_id: str, filters: CampaignArchiveQuery) -> list[EventLogEntry]:
        query = "SELECT sequence, room_id, event_type, audience, payload, issued_at FROM events WHERE room_id = %s"
        params: list = [room_id]

        if filters.action_type:
            query += " AND event_type = %s"
            params.append(filters.action_type)

        if filters.since:
            query += " AND issued_at >= %s"
            params.append(filters.since)

        if filters.until:
            query += " AND issued_at <= %s"
            params.append(filters.until)

        if filters.character_id:
            query += " AND payload::text LIKE %s"
            params.append(f"%{filters.character_id}%")

        query += " ORDER BY sequence LIMIT %s"
        params.append(filters.limit)

        rows = self.conn.execute(query, params).fetchall()
        return [
            EventLogEntry(
                sequence=r["sequence"],
                room_id=r["room_id"],
                event_type=r["event_type"],
                audience=r["audience"],
                payload=_json_value(r["payload"]),
                issued_at=_iso_value(r["issued_at"]),
            )
            for r in rows
        ]

    def _get_all_events(self, room_id: str, *, executor=None) -> list[dict]:
        rows = (executor or self.conn).execute(
            "SELECT * FROM events WHERE room_id = %s ORDER BY sequence", (room_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def _determine_ending_type(self, events: list[dict]) -> str:
        for e in events:
            if e["event_type"] == event_type("s2c_campaign_ended"):
                payload = _json_value(e["payload"])
                return payload.get("ending_type", "mixed")
        return "mixed"

    def _build_summary(self, room_id: str, events: list[dict], characters: list) -> str:
        char_names = [c["player_name"] for c in characters]
        event_count = len(events)
        names_str = "、".join(char_names)
        return f"战役结束。角色 {names_str} 参与，共经历 {event_count} 个事件。"

    def _extract_highlights(self, events: list[dict]) -> list[str]:
        highlights = []
        for e in events:
            if str(e.get("audience") or "") not in {"party", "system"}:
                continue
            if e["event_type"] in (event_type("s2c_reveal_transaction"), event_type("s2c_scene_sync")):
                payload = _json_value(e["payload"])
                if "text" in payload:
                    highlights.append(payload["text"])
                elif "summary" in payload:
                    highlights.append(payload["summary"])
        return highlights[:10]

    def _build_character_arcs(
        self,
        room_id: str,
        characters: list,
        *,
        executor=None,
    ) -> list[dict]:
        return build_character_arcs(executor or self.conn, room_id, characters)

    def _save_archive(self, room_id: str, ending: CampaignEnding):
        with self.conn.transaction() as tx:
            _insert_minimal_archive(
                tx,
                room_id,
                ending_type=ending.ending_type,
                summary=ending.summary,
                highlights=ending.highlights,
                character_arcs=ending.character_arcs,
            )


def ensure_campaign_writable(executor, room_id: str) -> dict:
    room = executor.execute(
        "SELECT room_id, status, state_version FROM rooms "
        "WHERE room_id = %s FOR UPDATE",
        (room_id,),
    ).fetchone()
    if not room:
        raise CampaignReadOnlyError("campaign_room_missing")
    if str(room.get("status") or "") in {"completed", "archived"}:
        raise CampaignReadOnlyError("campaign_completed_read_only")
    return dict(room)


def finalize_campaign(
    conn,
    room_id: str,
    *,
    ending_type: str,
    summary: str,
    highlights: list[str],
    character_arcs: list[dict[str, Any]] | None = None,
    current_action: dict[str, Any] | None = None,
    expected_room_statuses: tuple[str, ...] = ("suggested", "active"),
    ending_event_payload: dict[str, Any] | None = None,
    transaction=None,
) -> CampaignFinalization | None:
    from .ai.decision_audit import (
        DecisionAuditRecorder,
        finalize_terminal_decision_audit,
    )

    def execute(tx) -> CampaignFinalization | None:
        room = tx.execute(
            "SELECT room_id, status, state_version FROM rooms "
            "WHERE room_id = %s FOR UPDATE",
            (room_id,),
        ).fetchone()
        if not room:
            raise CampaignReadOnlyError("campaign_room_missing")
        room_status = str(room.get("status") or "")
        if room_status == "completed":
            return None
        if expected_room_statuses and room_status not in expected_room_statuses:
            raise CampaignReadOnlyError("campaign_not_ending_eligible")

        current_action_id = ""
        if current_action:
            current_action_id = str(current_action.get("action_id") or "")
            if not current_action_id or not complete_action(
                conn,
                current_action_id,
                from_statuses=tuple(current_action.get("from_statuses") or ()),
                to_status=str(current_action.get("to_status") or "completed"),
                result=dict(current_action.get("result") or {}),
                receipt=(
                    dict(current_action["receipt"])
                    if isinstance(current_action.get("receipt"), dict)
                    else None
                ),
                metadata=dict(current_action.get("metadata") or {}),
                transaction=tx,
            ):
                raise RuntimeError("campaign_ending_action_completion_conflict")

        room_row = tx.execute(
            "UPDATE rooms SET status = 'completed', state_version = state_version + 1 "
            "WHERE room_id = %s AND status = %s RETURNING state_version",
            (room_id, room_status),
        ).fetchone()
        if not room_row:
            raise RuntimeError("campaign_ending_room_conflict")

        ending_event_sequence = None
        if ending_event_payload is not None:
            ending_event_sequence = EventLog(tx).log_event(
                room_id,
                "s2c_campaign_ended",
                "party",
                dict(ending_event_payload),
                commit=False,
                state_version=int(room_row.get("state_version") or 0),
            )

        canceled_rows = tx.execute(
            "UPDATE actions SET status = 'canceled', canceled_at = NOW(), "
            "completed_at = COALESCE(completed_at, NOW()) "
            "WHERE room_id = %s AND status = ANY(%s) "
            "AND (%s = '' OR action_id <> %s) RETURNING action_id",
            (
                room_id,
                list(NONTERMINAL_CAMPAIGN_ACTION_STATUSES),
                current_action_id,
                current_action_id,
            ),
        ).fetchall()
        canceled_action_ids = tuple(sorted(
            str(row["action_id"]) for row in canceled_rows
        ))
        tx.execute(
            "UPDATE prepared_rule_actions SET status = 'canceled', "
            "completed_at = COALESCE(completed_at, NOW()) "
            "WHERE room_id = %s AND status IN ('armed', 'triggered')",
            (room_id,),
        )
        for action_id in canceled_action_ids:
            tx.execute(
                "INSERT INTO action_status_events (action_id, status, metadata) "
                "VALUES (%s, 'canceled', %s)",
                (
                    action_id,
                    json.dumps(
                        {"reason_code": "campaign_ended"},
                        ensure_ascii=False,
                    ),
                ),
            )
            finalize_terminal_decision_audit(
                tx,
                action_id,
                action_status="canceled",
                reason_code="campaign_ended",
                state_version=int(room_row.get("state_version") or 0),
            )

        canceled_drafts = tx.execute(
            "UPDATE action_drafts SET status = 'canceled', updated_at = NOW() "
            "WHERE room_id = %s "
            "AND status IN ('analyzing', 'awaiting_confirmation') "
            "RETURNING draft_id, current_revision",
            (room_id,),
        ).fetchall()
        draft_audits = DecisionAuditRecorder(tx)
        for draft in canceled_drafts:
            revision = int(draft.get("current_revision") or 1)
            draft_audits.finalize_draft_revision(
                str(draft["draft_id"]),
                revision,
                audit_state="canceled",
                final_delta={
                    "draft_status": "canceled",
                    "reason_code": "campaign_ended",
                    "draft_revision": revision,
                },
            )

        archive_id = _insert_minimal_archive(
            tx,
            room_id,
            ending_type=ending_type,
            summary=summary,
            highlights=highlights,
            character_arcs=(
                character_arcs
                if character_arcs is not None
                else build_character_arcs(tx, room_id)
            ),
        )
        return CampaignFinalization(
            archive_id=archive_id,
            canceled_action_ids=canceled_action_ids,
            state_version=int(room_row.get("state_version") or 0),
            ending_event_sequence=ending_event_sequence,
        )

    if transaction is not None:
        return execute(transaction)
    with conn.transaction() as tx:
        return execute(tx)


def _insert_minimal_archive(
    executor,
    room_id: str,
    *,
    ending_type: str,
    summary: str,
    highlights: list[str],
    character_arcs: list[dict[str, Any]],
) -> str:
    archive_id = uuid.uuid4().hex
    executor.execute(
        "INSERT INTO campaign_archives "
        "(archive_id, room_id, ending_type, summary, highlights, character_arcs) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (
            archive_id,
            room_id,
            str(ending_type or "mixed"),
            str(summary or ""),
            json.dumps(list(highlights or []), ensure_ascii=False),
            json.dumps(list(character_arcs or []), ensure_ascii=False),
        ),
    )
    return archive_id


def _json_value(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def project_campaign_archive(
    archive_row,
    *,
    scope: Literal["full", "player", "admin_ops"],
    character_id: str | None = None,
) -> dict[str, Any]:
    """Return only the campaign archive fields allowed for the requested scope."""
    row = dict(archive_row)
    metadata = {
        key: row.get(key)
        for key in ("archive_id", "room_id", "ending_type", "created_at")
        if key in row
    }
    if scope == "admin_ops":
        return metadata

    projection = {
        **metadata,
        "ending_type": row["ending_type"],
        "summary": row["summary"],
        "highlights": list(_json_value(row.get("highlights")) or []),
    }
    arcs = list(_json_value(row.get("character_arcs")) or [])
    if scope == "full":
        return {**projection, "character_arcs": arcs}
    if not character_id:
        raise ValueError("player archive projection requires character_id")
    own_arc = next(
        (
            arc
            for arc in arcs
            if str(arc.get("character_id") or "") == character_id
        ),
        None,
    )
    return {**projection, "character_arc": own_arc}


def build_character_arcs(conn, room_id: str, characters: list | None = None) -> list[dict]:
    if characters is None:
        characters = conn.execute(
            "SELECT character_id, player_name, xlsx_data FROM characters "
            "WHERE room_id = %s ORDER BY character_id",
            (room_id,),
        ).fetchall()
    arcs = []
    for character in characters:
        character_id = str(character["character_id"])
        runtime = conn.execute(
            "SELECT san, temp_modifiers FROM character_runtime_state "
            "WHERE room_id = %s AND character_id = %s",
            (room_id, character_id),
        ).fetchone()
        sheet = _json_value(character.get("xlsx_data")) or {}
        temp_modifiers = (
            _json_value(runtime.get("temp_modifiers")) or {}
            if runtime
            else _json_value(sheet.get("temp_modifiers")) or {}
        )
        sanity_state = _json_value(temp_modifiers.get("coc7_sanity")) or {}
        actions = conn.execute(
            "SELECT COUNT(*) AS count FROM actions "
            "WHERE room_id = %s AND character_id = %s",
            (room_id, character_id),
        ).fetchone()
        final_san_value = runtime["san"] if runtime else sheet.get("san", 0)
        arcs.append({
            "character_id": character_id,
            "player_name": str(character.get("player_name") or ""),
            "total_actions": int(actions["count"] or 0),
            "final_san": max(0, int(final_san_value or 0)),
            "sanity_outcome": {
                "insanity_type": str(
                    sanity_state.get("insanity_type") or "none"
                ),
                "phase": str(sanity_state.get("phase") or "stable"),
                "control": str(sanity_state.get("control") or "player"),
                "archive_required": bool(
                    sanity_state.get("archive_required", False)
                ),
            },
        })
    return arcs


def _datetime_value(value):
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _iso_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value
