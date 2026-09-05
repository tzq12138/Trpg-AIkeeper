"""R4 slice A — automatic review acceptance with frozen evidence.

In ai_only rooms a player dispute over their OWN settled action is accepted
as a pending automatic case (201) without creating any Host queue entry or
Host event; the same idempotency key replays the same review id, different
payloads under one key conflict, someone else's action stays a 404, a still-
running action is refused with an explicit not-sealed reason, and the public
GET returns the redacted summary only.
"""

import json

from tests.server.conftest import create_room, setup_auth_test_data


def _setup_ai_only_completed_action(client, test_db):
    """Completed own action inside an ai_only room (frozen runtime policy)."""
    setup_auth_test_data(test_db)
    room = create_room(client)
    joined = client.post(f"/api/player/rooms/{room['room_id']}/join").json()
    scenario = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    package_id = f"auto-review-pkg-{room['room_id']}"
    test_db.execute(
        "INSERT INTO runtime_package_versions "
        "(runtime_package_version_id, scenario_version_id, package_version_number, "
        "gate_status, input_checksum, runtime_package, created_by) "
        "VALUES (%s, %s, 1, 'ready', 'auto-review', %s, 'test')",
        (
            package_id,
            scenario["scenario_version_id"],
            json.dumps({"runtime_policy": {"session_mode": "ai_only"}}),
        ),
    )
    test_db.execute(
        "UPDATE rooms SET runtime_package_version_id = %s WHERE room_id = %s",
        (package_id, room["room_id"]),
    )
    test_db.execute(
        "UPDATE characters SET xlsx_data = %s WHERE character_id = %s",
        (
            json.dumps({"name": "调查员", "luck": 40, "hp": 10, "san": 50, "mp": 10}),
            joined["character_id"],
        ),
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, draft_id, intent_type, "
        "declared_intent, params, status, result, idempotency_key) "
        "VALUES ('review-action', %s, %s, 'draft-review', "
        "'skill_check', '我原本想侦查门框', %s, 'completed', %s, 'action-idem-1')",
        (
            room["room_id"],
            joined["character_id"],
            json.dumps({"skillName": "侦查"}, ensure_ascii=False),
            json.dumps({"narrative": "你检查了地板"}, ensure_ascii=False),
        ),
    )
    test_db.commit()
    return room, joined


def _post_review(client, joined, objection="请重新检查这次规则解释", original_intent="", key=""):
    headers = {"X-Room-Token": joined["player_token"]}
    if key:
        headers["Idempotency-Key"] = key
    return client.post(
        "/api/player/actions/review-action/review-requests",
        headers=headers,
        json={"objection": objection, "original_intent": original_intent},
    )


def test_ai_only_review_is_accepted_pending_with_frozen_evidence(client, test_db):
    room, joined = _setup_ai_only_completed_action(client, test_db)
    before_version = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"]

    response = _post_review(client, joined, objection="结算对象理解错了", key="idem-a-1")

    assert response.status_code == 201, response.text
    review = response.json()
    assert review["status"] == "pending"
    assert review["review_request_id"]
    assert review["ai_suggestion"]["requires_host_review"] is False
    assert review["evidence_hash"]
    # The frozen original intent (server-side) is the default review statement.
    assert review["original_intent"] == "我原本想侦查门框"

    row = test_db.execute(
        "SELECT evidence_snapshot, evidence_hash, automatic_resolution, host_resolution "
        "FROM action_review_requests WHERE review_request_id = %s",
        (review["review_request_id"],),
    ).fetchone()
    assert row["evidence_hash"] == review["evidence_hash"]
    snapshot = row["evidence_snapshot"]
    assert snapshot["action"]["declared_intent"] == "我原本想侦查门框"
    assert snapshot["room"]["room_id"] == room["room_id"]
    assert snapshot["action"]["params_hash"]
    assert snapshot["evidence_hash"] == row["evidence_hash"]
    # host_resolution stays empty: this is not a disguised manual approval.
    assert row["host_resolution"] == {}
    # No Host queue entry / Host event was created.
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM events "
        "WHERE room_id = %s AND audience = 'host' "
        "AND event_type = 's2c_action_review_requested'",
        (room["room_id"],),
    ).fetchone()["count"] == 0
    # The review itself never mutates world state.
    after_version = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"]
    assert after_version == before_version


def test_same_idempotency_key_replays_same_review_id(client, test_db):
    room, joined = _setup_ai_only_completed_action(client, test_db)
    del room
    first = _post_review(client, joined, key="idem-same-1")
    assert first.status_code == 201, first.text
    replay = _post_review(client, joined, key="idem-same-1")
    assert replay.status_code == 201, replay.text
    assert replay.json()["review_request_id"] == first.json()["review_request_id"]
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM action_review_requests "
        "WHERE action_id = 'review-action'",
    ).fetchone()["count"] == 1


def test_different_payload_under_one_key_conflicts(client, test_db):
    room, joined = _setup_ai_only_completed_action(client, test_db)
    del room
    first = _post_review(client, joined, objection="第一次异议", key="idem-conflict-1")
    assert first.status_code == 201, first.text
    second = _post_review(client, joined, objection="不同的异议载荷", key="idem-conflict-1")
    assert second.status_code == 409, second.text
    assert second.json()["detail"]["code"] == "idempotency_key_conflict"


def test_other_players_action_is_404_without_existence_leak(client, test_db):
    room, joined_a = _setup_ai_only_completed_action(client, test_db)
    joined_b = client.post(f"/api/player/rooms/{room['room_id']}/join").json()
    # Only the second player may not see the first player's action.
    headers = {"X-Room-Token": joined_b["player_token"]}
    response = client.post(
        "/api/player/actions/review-action/review-requests",
        headers=headers,
        json={"objection": "我想看别人的行动"},
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "action_not_found"
    assert joined_a["character_id"] != joined_b["character_id"]


def test_get_review_returns_redacted_summary_only(client, test_db):
    room, joined = _setup_ai_only_completed_action(client, test_db)
    created = _post_review(client, joined, key="idem-get-1").json()

    response = client.get(
        f"/api/player/actions/review-action/review-requests/{created['review_request_id']}",
        headers={"X-Room-Token": joined["player_token"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["review_request_id"] == created["review_request_id"]
    assert body["status"] == "pending"
    assert body["evidence_hash"] == created["evidence_hash"]
    # Full snapshot and secrets are not exposed by the public GET.
    assert "evidence_snapshot" not in body
    assert "host_resolution" not in body


def test_still_running_action_is_refused_with_not_sealed_reason(client, test_db):
    room, joined = _setup_ai_only_completed_action(client, test_db)
    del room
    test_db.execute(
        "UPDATE actions SET status = 'resolving' WHERE action_id = 'review-action'"
    )
    test_db.commit()
    response = _post_review(client, joined)
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "review_not_available"
    assert "evidence_not_sealed" in detail["reason"]
