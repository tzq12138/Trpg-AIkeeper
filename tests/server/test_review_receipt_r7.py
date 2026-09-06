"""R7 — player action receipt exposes room runtime context and recovery state.

The receipt GET (/api/player/actions/{action_id}) must tell a waiting client
why its action is stuck without guessing from the action status alone:
room_runtime_status (room runtime), resolution_outcome (D04 vocabulary from
the durable resolution trace) and recovery={reason_code, retryable,
original_roll_preserved} whenever the room is paused_system/recovering.
The receipt stays player-scoped: another identity gets a 404 and a missing
token gets 401 — the public stage never reads a private receipt.

These are VIEW-contract tests over engine-shaped rows (the same fixtures the
review suite uses); the real fault→pause→receipt chain is covered in
test_system_failure_recovery.py.
"""

import json

from tests.server.conftest import create_room, setup_auth_test_data


def _paused_room_action(
    client,
    test_db,
    *,
    integrity_reason,
    action_status="resolving",
    receipt=None,
    outcome=None,
):
    setup_auth_test_data(test_db)
    room = create_room(client)
    joined = client.post(f"/api/player/rooms/{room['room_id']}/join").json()
    test_db.execute(
        "UPDATE rooms SET status = 'paused', runtime_status = 'paused_system', "
        "integrity_status = 'read_only_recovery', integrity_reason = %s, "
        "integrity_source = 'resolution_pipeline', "
        "integrity_state_version = state_version, integrity_updated_at = NOW() "
        "WHERE room_id = %s",
        (integrity_reason, room["room_id"]),
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, draft_id, intent_type, "
        "declared_intent, params, status, result, receipt, idempotency_key) "
        "VALUES ('review-action', %s, %s, 'draft-review', 'skill_check', "
        "'我原本想侦查门框', '{}', %s, %s, %s, 'action-idem-1')",
        (
            room["room_id"],
            joined["character_id"],
            action_status,
            json.dumps({"narrative": "你检查了地板"}, ensure_ascii=False),
            json.dumps(receipt, ensure_ascii=False) if receipt else None,
        ),
    )
    if outcome:
        test_db.execute(
            "INSERT INTO resolution_traces "
            "(resolution_trace_id, action_id, room_id, state_version, status, "
            "resolution_outcome, trace) "
            "VALUES ('trace-r7-1', 'review-action', %s, 0, 'completed', %s, '{}')",
            (room["room_id"], outcome),
        )
    test_db.commit()
    return room, joined


def _get_receipt(client, token):
    return client.get(
        "/api/player/actions/review-action",
        headers={"X-Room-Token": token},
    )


def test_running_room_receipt_carries_outcome_without_recovery(client, test_db):
    room, joined = _paused_room_action(
        client, test_db, integrity_reason=None, outcome="success",
        action_status="completed",
    )
    # A running room: the same engine columns with runtime running.
    test_db.execute(
        "UPDATE rooms SET status = 'active', runtime_status = 'running', "
        "integrity_status = 'healthy', integrity_reason = NULL "
        "WHERE room_id = %s",
        (room["room_id"],),
    )
    test_db.commit()

    response = _get_receipt(client, joined["player_token"])

    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["room_runtime_status"] == "running"
    assert receipt["resolution_outcome"] == "success"
    assert receipt["recovery"] is None
    assert receipt["status"] == "completed"


def test_paused_receipt_exposes_recovery_with_preserved_roll(client, test_db):
    # Engine-shaped frozen dice receipt (the receipt VIEW checks presence, not
    # signature — verification happens in the review engines).
    receipt = {
        "verification_receipt": {
            "purpose": "skill_check.initial",
            "dice": "d100",
            "signature": "frozen",
        }
    }
    room, joined = _paused_room_action(
        client,
        test_db,
        integrity_reason="narrator_timeout",
        action_status="resolving",
        receipt=receipt,
        outcome=None,
    )
    del room

    response = _get_receipt(client, joined["player_token"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["room_runtime_status"] == "paused_system"
    assert body["status"] == "resolving"  # action state stays an action state
    recovery = body["recovery"]
    assert recovery["reason_code"] == "narrator_timeout"
    assert recovery["retryable"] is True
    assert recovery["original_roll_preserved"] is True


def test_paused_receipt_without_dice_and_conclusive_reason_not_retryable(
    client, test_db,
):
    room, joined = _paused_room_action(
        client,
        test_db,
        integrity_reason="review_outcome_flip",
        action_status="resolving",
        receipt=None,
        outcome=None,
    )
    del room

    response = _get_receipt(client, joined["player_token"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["room_runtime_status"] == "paused_system"
    recovery = body["recovery"]
    assert recovery["reason_code"] == "review_outcome_flip"
    assert recovery["retryable"] is False
    assert recovery["original_roll_preserved"] is False


def test_room_get_exposes_runtime_status_and_integrity_reason(client, test_db):
    """Owner console reads recovery state from the public room GET."""
    room, joined = _paused_room_action(
        client, test_db, integrity_reason="review_outcome_flip"
    )
    del joined

    public = client.get(f"/api/rooms/{room['room_id']}")

    assert public.status_code == 200, public.text
    body = public.json()
    assert body["runtime_status"] == "paused_system"
    assert body["integrity_reason"] == "review_outcome_flip"
    # Still never leaks owner credentials or internal proposal content.
    assert "owner_token" not in public.text
    assert "review-action" not in public.text


def test_receipt_is_player_scoped_never_stage_visible(client, test_db):
    room, joined = _paused_room_action(
        client, test_db, integrity_reason="provider_failure"
    )
    other = client.post(f"/api/player/rooms/{room['room_id']}/join").json()

    own = _get_receipt(client, joined["player_token"])
    assert own.status_code == 200, own.text
    # A second identity (or the stage pretending to be one) never reads the
    # private receipt: same 404 contract as the review endpoints.
    other_view = _get_receipt(client, other["player_token"])
    assert other_view.status_code == 404, other_view.text
    anon = _get_receipt(client, "")
    assert anon.status_code in (401, 403), anon.text
    # No receipt content is reachable through the public room snapshot either.
    public = client.get(f"/api/rooms/{room['room_id']}")
    assert "review-action" not in public.text
