from dataclasses import dataclass

from ..models import ActionIntakeReceiptDTO, PlayerActionEnvelopeDTO


NON_STATE_INPUT_MODES = {"party_chat", "ooc", "rule_question", "private_note", "safety"}


@dataclass
class ActionProtocolError(Exception):
    status_code: int
    detail: dict[str, object]


def intake_player_action(
    conn,
    character: dict,
    envelope: PlayerActionEnvelopeDTO,
) -> ActionIntakeReceiptDTO:
    room_id = str(character["room_id"])
    character_id = str(character["character_id"])
    existing = conn.execute(
        "SELECT room_id, character_id, base_state_version, execution_mode "
        "FROM player_action_envelopes WHERE action_id = %s",
        (envelope.action_id,),
    ).fetchone()
    if existing:
        if existing["room_id"] != room_id or existing["character_id"] != character_id:
            raise ActionProtocolError(409, {"code": "action_id_conflict"})
        return ActionIntakeReceiptDTO(
            actionId=envelope.action_id,
            baseStateVersion=int(existing["base_state_version"]),
            executionMode=str(existing["execution_mode"]),
        )

    room = conn.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()
    if not room:
        raise ActionProtocolError(404, {"code": "room_not_found"})
    current_state_version = int(room["state_version"])
    if envelope.base_state_version != current_state_version:
        raise ActionProtocolError(
            409,
            {
                "code": "sync_required",
                "base_state_version": envelope.base_state_version,
                "current_state_version": current_state_version,
            },
        )

    execution_mode = (
        "non_state_event"
        if envelope.input_mode in NON_STATE_INPUT_MODES
        else "intent_draft_required"
    )
    raw_text = (
        "[private_note_body_stored_encrypted]"
        if envelope.input_mode == "private_note"
        else envelope.raw_text
    )
    conn.execute(
        "INSERT INTO player_action_envelopes ("
        "action_id, room_id, character_id, input_mode, source, raw_text, "
        "base_state_version, requested_visibility, client_sequence, attachments, execution_mode"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            envelope.action_id,
            room_id,
            character_id,
            envelope.input_mode,
            envelope.source,
            raw_text,
            envelope.base_state_version,
            envelope.requested_visibility,
            envelope.client_sequence,
            envelope.attachments,
            execution_mode,
        ),
    )
    conn.commit()
    return ActionIntakeReceiptDTO(
        actionId=envelope.action_id,
        baseStateVersion=envelope.base_state_version,
        executionMode=execution_mode,
    )


def validate_envelope_for_draft(conn, character: dict, action_id: str) -> None:
    envelope = conn.execute(
        "SELECT room_id, character_id, execution_mode FROM player_action_envelopes "
        "WHERE action_id = %s",
        (action_id,),
    ).fetchone()
    if not envelope:
        raise ActionProtocolError(404, {"code": "action_envelope_not_found"})
    if (
        envelope["room_id"] != character["room_id"]
        or envelope["character_id"] != character["character_id"]
    ):
        raise ActionProtocolError(403, {"code": "action_envelope_forbidden"})
    if envelope["execution_mode"] != "intent_draft_required":
        raise ActionProtocolError(409, {"code": "input_mode_not_action"})


def validate_envelope_for_input_mode(
    conn,
    character: dict,
    action_id: str,
    expected_input_mode: str,
) -> None:
    envelope = conn.execute(
        "SELECT room_id, character_id, input_mode FROM player_action_envelopes "
        "WHERE action_id = %s",
        (action_id,),
    ).fetchone()
    if not envelope:
        raise ActionProtocolError(404, {"code": "action_envelope_not_found"})
    if (
        envelope["room_id"] != character["room_id"]
        or envelope["character_id"] != character["character_id"]
    ):
        raise ActionProtocolError(403, {"code": "action_envelope_forbidden"})
    if envelope["input_mode"] != expected_input_mode:
        raise ActionProtocolError(409, {"code": "input_mode_mismatch"})
