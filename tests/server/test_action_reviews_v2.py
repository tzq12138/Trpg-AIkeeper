import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

from src.server.db_adapter import PgConnection
from src.server.engine.compensation_service import (
    ActionReviewAlreadyResolved,
    resolve_action_review,
)
from tests.server.conftest import create_room, setup_auth_test_data


def _setup_completed_action(client, test_db):
    setup_auth_test_data(test_db)
    room = create_room(client)
    joined = client.post(f"/api/player/rooms/{room['room_id']}/join").json()
    test_db.execute(
        "UPDATE characters SET xlsx_data = %s WHERE character_id = %s",
        (
            json.dumps(
                {"name": "调查员", "luck": 40, "hp": 10, "san": 50, "mp": 10},
                ensure_ascii=False,
            ),
            joined["character_id"],
        ),
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, draft_id, intent_type, "
        "declared_intent, status, result) VALUES ('review-action', %s, %s, 'draft-review', "
        "'skill_check', '我原本想侦查门框', 'completed', %s)",
        (
            room["room_id"],
            joined["character_id"],
            json.dumps({"narrative": "你检查了地板"}, ensure_ascii=False),
        ),
    )
    return room, joined


def test_player_review_request_creates_non_mutating_ai_suggestion(client, test_db):
    room, joined = _setup_completed_action(client, test_db)
    before_version = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"]

    response = client.post(
        "/api/player/actions/review-action/review-requests",
        headers={"X-Room-Token": joined["player_token"]},
        json={
            "original_intent": "我想检查门框，不是地板",
            "objection": "结算对象理解错了",
        },
    )

    assert response.status_code == 201
    review = response.json()
    assert review["status"] == "pending"
    assert review["ai_suggestion"]["requires_host_review"] is True
    assert review["ai_suggestion"]["mutations"] == []
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM compensation_transactions"
    ).fetchone()["count"] == 0
    after_version = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"]
    assert after_version == before_version


def test_player_cannot_review_queued_action_or_another_players_action(client, test_db):
    room, joined = _setup_completed_action(client, test_db)
    other = client.post(f"/api/player/rooms/{room['room_id']}/join").json()
    test_db.execute(
        "UPDATE actions SET status = 'queued' WHERE action_id = 'review-action'"
    )

    queued = client.post(
        "/api/player/actions/review-action/review-requests",
        headers={"X-Room-Token": joined["player_token"]},
        json={"objection": "现在就申诉"},
    )
    hidden = client.post(
        "/api/player/actions/review-action/review-requests",
        headers={"X-Room-Token": other["player_token"]},
        json={"objection": "查看别人的行动"},
    )

    assert queued.status_code == 409
    assert queued.json()["detail"]["code"] == "review_not_available"
    assert hidden.status_code == 404


def test_host_can_list_and_reject_pending_review_without_state_change(client, test_db):
    room, joined = _setup_completed_action(client, test_db)
    created = client.post(
        "/api/player/actions/review-action/review-requests",
        headers={"X-Room-Token": joined["player_token"]},
        json={"objection": "结算对象理解错了"},
    ).json()

    denied = client.get(
        f"/api/host/{room['room_id']}/action-reviews",
        headers={"X-Owner-Token": "wrong"},
    )
    listed = client.get(
        f"/api/host/{room['room_id']}/action-reviews",
        headers={"X-Owner-Token": room["owner_token"]},
    )
    rejected = client.post(
        f"/api/host/{room['room_id']}/action-reviews/{created['review_request_id']}/resolve",
        headers={"X-Owner-Token": room["owner_token"]},
        json={"decision": "rejected", "reason": "原结算正确"},
    )

    assert denied.status_code == 403
    assert listed.status_code == 200
    assert [item["review_request_id"] for item in listed.json()["items"]] == [
        created["review_request_id"]
    ]
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM compensation_transactions"
    ).fetchone()["count"] == 0


def test_host_accepted_compensation_uses_state_service_and_is_audited(client, test_db):
    room, joined = _setup_completed_action(client, test_db)
    created = client.post(
        "/api/player/actions/review-action/review-requests",
        headers={"X-Room-Token": joined["player_token"]},
        json={"objection": "应返还 3 点幸运"},
    ).json()

    response = client.post(
        f"/api/host/{room['room_id']}/action-reviews/{created['review_request_id']}/resolve",
        headers={"X-Owner-Token": room["owner_token"]},
        json={
            "decision": "modified",
            "reason": "返还误扣幸运",
            "mutations": [
                {"op": "replace", "path": "/character/luck", "value": 43}
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "modified"
    transaction = test_db.execute(
        "SELECT status, transaction_type, reason FROM compensation_transactions"
    ).fetchone()
    assert dict(transaction) == {
        "status": "applied",
        "transaction_type": "state_mutation",
        "reason": "返还误扣幸运",
    }
    runtime = test_db.execute(
        "SELECT luck FROM character_runtime_state WHERE character_id = %s AND room_id = %s",
        (joined["character_id"], room["room_id"]),
    ).fetchone()
    assert runtime["luck"] == 43


def test_concurrent_host_compensation_applies_only_once(client, test_db):
    room, joined = _setup_completed_action(client, test_db)
    created = client.post(
        "/api/player/actions/review-action/review-requests",
        headers={"X-Room-Token": joined["player_token"]},
        json={"objection": "应返还 3 点幸运"},
    ).json()
    review = dict(
        test_db.execute(
            "SELECT arr.*, a.room_id FROM action_review_requests arr "
            "JOIN actions a ON a.action_id = arr.action_id "
            "WHERE arr.review_request_id = %s",
            (created["review_request_id"],),
        ).fetchone()
    )
    start = Barrier(2)

    def resolve_once():
        conn = PgConnection(test_db._pool)
        try:
            start.wait(timeout=5)
            return resolve_action_review(
                SimpleNamespace(state_service=None),
                conn,
                review,
                decision="modified",
                reason="返还误扣幸运",
                mutations=[
                    {"op": "replace", "path": "/character/luck", "value": 43}
                ],
            )
        except ActionReviewAlreadyResolved:
            return {"status": "conflict"}
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: resolve_once(), range(2)))

    assert sorted(result["status"] for result in results) == ["conflict", "modified"]
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM compensation_transactions"
    ).fetchone()["count"] == 1
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM events WHERE event_type = 's2c_action_review_resolved'"
    ).fetchone()["count"] == 1


def test_host_compensation_rejects_non_allowlisted_state_path(client, test_db):
    room, joined = _setup_completed_action(client, test_db)
    created = client.post(
        "/api/player/actions/review-action/review-requests",
        headers={"X-Room-Token": joined["player_token"]},
        json={"objection": "尝试越权"},
    ).json()

    response = client.post(
        f"/api/host/{room['room_id']}/action-reviews/{created['review_request_id']}/resolve",
        headers={"X-Owner-Token": room["owner_token"]},
        json={
            "decision": "accepted",
            "reason": "错误字段",
            "mutations": [
                {"op": "replace", "path": "/character/name", "value": "覆盖"}
            ],
        },
    )

    assert response.status_code == 422
    assert test_db.execute(
        "SELECT status FROM action_review_requests WHERE review_request_id = %s",
        (created["review_request_id"],),
    ).fetchone()["status"] == "pending"
