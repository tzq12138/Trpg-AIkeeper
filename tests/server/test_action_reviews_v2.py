import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

from src.server.db_adapter import PgConnection
from src.server.engine.compensation_service import (
    ActionReviewAlreadyResolved,
    resolve_action_review,
)
from src.server.engine.roll_receipt import create_roll_receipt
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


def _setup_recalculable_review(client, test_db, monkeypatch):
    monkeypatch.setenv("ROLL_RECEIPT_SECRET", "recalculation-test-secret")
    room, joined = _setup_completed_action(client, test_db)
    receipt = create_roll_receipt(
        action_id="review-action",
        rule_set_version="coc7-v1",
        rolled_at="2026-07-19T12:00:00+00:00",
        raw_rolls=[{
            "dice": "d100",
            "values": {
                "ones": 2,
                "tens": [4],
                "candidates": [42],
                "selected_index": 0,
            },
            "result": 42,
        }],
    )
    explanation = {
        "rule_set_version": "coc7-v1",
        "authoritative_inputs": {
            "intent_type": "skill_check",
            "skill_value": 60,
        },
        "verification_receipt": receipt,
    }
    test_db.execute(
        "INSERT INTO resolution_bundles "
        "(action_id, room_id, character_id, canonical_result, rule_explanation, actor_projection, stage_projection, host_console, release_status) "
        "VALUES ('review-action', %s, %s, '{}', %s, '{}', '{}', '{}', 'released')",
        (room["room_id"], joined["character_id"], json.dumps(explanation, ensure_ascii=False)),
    )
    test_db.commit()
    review = client.post(
        "/api/player/actions/review-action/review-requests",
        headers={"X-Room-Token": joined["player_token"]},
        json={"objection": "难度参数录入错误"},
    ).json()
    return room, joined, review, explanation


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


def test_ai_only_player_review_does_not_enqueue_host_review(client, test_db):
    """Test migration (04 §6, R4 spec): ai_only disputes are now ACCEPTED as
    pending automatic cases instead of rejected with 409. The equivalent
    coverage preserved here is exactly what the old test guarded — no Host
    queue entry and no Host event is created — plus the new R4 contract:
    201 + pending with a frozen evidence hash. Host manual endpoints still
    reject ai_only (tested separately below).
    """
    room, joined = _setup_completed_action(client, test_db)
    scenario = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    package_id = f"review-ai-only-{room['room_id']}"
    test_db.execute(
        "INSERT INTO runtime_package_versions "
        "(runtime_package_version_id, scenario_version_id, package_version_number, "
        "gate_status, input_checksum, runtime_package, created_by) "
        "VALUES (%s, %s, 1, 'ready', 'review-ai-only', %s, 'test')",
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
    test_db.commit()

    response = client.post(
        "/api/player/actions/review-action/review-requests",
        headers={"X-Room-Token": joined["player_token"]},
        json={"objection": "请重新检查这次规则解释"},
    )

    assert response.status_code == 201, response.text
    review = response.json()
    assert review["status"] == "pending"
    assert review["ai_suggestion"]["requires_host_review"] is False
    assert review["evidence_hash"]
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM action_review_requests "
        "WHERE action_id = 'review-action'",
    ).fetchone()["count"] == 1
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM events "
        "WHERE room_id = %s AND audience = 'host' "
        "AND event_type = 's2c_action_review_requested'",
        (room["room_id"],),
    ).fetchone()["count"] == 0


def test_ai_only_host_review_endpoint_rejects_legacy_review(client, test_db):
    room, joined = _setup_completed_action(client, test_db)
    scenario = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    package_id = f"review-host-guard-{room['room_id']}"
    test_db.execute(
        "INSERT INTO runtime_package_versions "
        "(runtime_package_version_id, scenario_version_id, package_version_number, "
        "gate_status, input_checksum, runtime_package, created_by) "
        "VALUES (%s, %s, 1, 'ready', 'review-host-guard', %s, 'test')",
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
        "INSERT INTO action_review_requests "
        "(review_request_id, action_id, character_id, objection) "
        "VALUES ('legacy-ai-only-review', 'review-action', %s, 'legacy review')",
        (joined["character_id"],),
    )
    test_db.commit()

    response = client.get(
        f"/api/host/{room['room_id']}/action-reviews",
        headers={"X-Owner-Token": room["owner_token"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "AI_ONLY_HOST_ADJUDICATION_DISABLED"


def test_ai_only_host_skip_character_is_not_a_manual_adjudication_path(client, test_db):
    room, _joined = _setup_completed_action(client, test_db)
    scenario = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    package_id = f"skip-host-guard-{room['room_id']}"
    test_db.execute(
        "INSERT INTO runtime_package_versions "
        "(runtime_package_version_id, scenario_version_id, package_version_number, "
        "gate_status, input_checksum, runtime_package, created_by) "
        "VALUES (%s, %s, 1, 'ready', 'skip-host-guard', %s, 'test')",
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
    test_db.commit()

    response = client.post(
        f"/api/rooms/{room['room_id']}/turns/legacy-turn/skip-character",
        headers={"X-Owner-Token": room["owner_token"]},
        json={"character_id": "any", "policy": "idle"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "AI_ONLY_HOST_ADJUDICATION_DISABLED"


def test_ai_only_owner_cannot_restore_arbitrary_checkpoint(client, test_db):
    """Frozen D11: in ai_only the Owner must not select a checkpoint; the
    legacy restore endpoint must fail closed until system-generated recovery
    proposals exist."""
    room, _joined = _setup_completed_action(client, test_db)
    scenario = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    package_id = f"restore-guard-{room['room_id']}"
    test_db.execute(
        "INSERT INTO runtime_package_versions "
        "(runtime_package_version_id, scenario_version_id, package_version_number, "
        "gate_status, input_checksum, runtime_package, created_by) "
        "VALUES (%s, %s, 1, 'ready', 'restore-guard', %s, 'test')",
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
    test_db.commit()

    response = client.post(
        f"/api/rooms/{room['room_id']}/restore/legacy-checkpoint",
        headers={"X-Owner-Token": room["owner_token"]},
        json={
            "proposal": {
                "mode": "checkpoint_restore",
                "checkpointId": "legacy-checkpoint",
            },
            "dryRunToken": "not-needed",
            "confirm": True,
            "reason": "test",
            "confirmations": {"proposalHash": "x", "stateVersion": 1},
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "AI_ONLY_HOST_ADJUDICATION_DISABLED"


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


def test_host_review_list_contains_auditable_intent_rule_state_and_citation_packet(client, test_db, monkeypatch):
    room, _joined, review, explanation = _setup_recalculable_review(client, test_db, monkeypatch)
    explanation.update({
        "authoritative_inputs": {
            "intent_type": "skill_check",
            "skill_name": "侦查",
            "skill_value": 60,
            "raw_rolls": [{"dice": "d100", "result": 42}],
        },
        "modifiers": {"difficulty": "regular", "bonus_dice": 0},
        "formula": "d100 <= 60",
        "state_before": {"hp": 10, "san": 50},
        "state_after": {"hp": 10, "san": 48},
        "citations": [{"source": "CoC7 基础规则", "page": 55, "location": "技能检定"}],
    })
    test_db.execute(
        "UPDATE actions SET params = %s WHERE action_id = 'review-action'",
        (json.dumps({
            "analysis": {
                "understanding_summary": "你想仔细检查门框。",
                "risk": "high",
                "visibility": "party",
                "confirmation_requirements": ["dice_roll"],
                "intent_contract": {
                    "target": "门框",
                    "method": "侦查",
                    "object": None,
                    "constraints": ["不惊动守卫"],
                    "resources": [],
                    "conditions": ["如果守卫未靠近"],
                    "visibility": "party",
                    "ambiguities": [],
                },
            },
            "director_plan": {
                "context_version": 7,
                "interpreted_intent": "检查门框上的痕迹",
                "mechanic_plan": {"mechanic": "skill_check", "skillName": "侦查", "difficulty": "regular"},
                "preconditions": [{"kind": "state_version", "expected": 7}],
                "permissions": [{"scope": "scene", "allowed": True}],
                "citations": [{"source": "剧本", "page_number": 3, "location": "门框"}],
            },
        }, ensure_ascii=False),),
    )
    test_db.execute(
        "UPDATE resolution_bundles SET rule_explanation = %s WHERE action_id = 'review-action'",
        (json.dumps(explanation, ensure_ascii=False),),
    )
    test_db.commit()

    response = client.get(
        f"/api/host/{room['room_id']}/action-reviews",
        headers={"X-Owner-Token": room["owner_token"]},
    )

    assert response.status_code == 200
    packet = response.json()["items"][0]
    assert packet["original_action_text"] == "我原本想侦查门框"
    assert packet["intent_contract"] == {
        "intentType": "skill_check",
        "understandingSummary": "你想仔细检查门框。",
        "risk": "high",
        "visibility": "party",
        "confirmationRequirements": ["dice_roll"],
        "target": "门框",
        "method": "侦查",
        "object": None,
        "constraints": ["不惊动守卫"],
        "resources": [],
        "conditions": ["如果守卫未靠近"],
        "ambiguities": [],
    }
    assert packet["rule_plan"] == {
        "ruleSetVersion": "coc7-v1",
        "authoritativeInputs": {
            "intentType": "skill_check",
            "skillName": "侦查",
            "skillValue": 60,
            "rawRolls": [{"dice": "d100", "result": 42}],
        },
        "modifiers": {"difficulty": "regular", "bonus_dice": 0},
        "formula": "d100 <= 60",
    }
    assert packet["state_diff"] == {
        "before": {"hp": 10, "san": 50},
        "after": {"hp": 10, "san": 48},
    }
    assert packet["citations"] == [
        {"source": "CoC7 基础规则", "page": 55, "location": "技能检定"},
        {"source": "剧本", "pageNumber": 3, "location": "门框"},
    ]
    assert "signature" not in response.text


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


def test_host_recalculation_reuses_verified_original_roll_without_world_mutation(client, test_db, monkeypatch):
    room, _joined, review, _explanation = _setup_recalculable_review(client, test_db, monkeypatch)
    before_state_version = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s", (room["room_id"],)
    ).fetchone()["state_version"]
    original = test_db.execute(
        "SELECT result FROM actions WHERE action_id = 'review-action'"
    ).fetchone()["result"]

    response = client.post(
        f"/api/host/{room['room_id']}/action-reviews/{review['review_request_id']}/recalculate",
        headers={"X-Owner-Token": room["owner_token"]},
        json={"difficulty": "hard", "reason": "难度参数录入错误"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "modified"
    assert payload["recalculation"] == {
        "roll": 42,
        "skillValue": 60,
        "difficulty": "hard",
        "target": 30,
        "successLevel": "regular",
        "isSuccess": False,
    }
    transaction = test_db.execute(
        "SELECT transaction_type, payload, status FROM compensation_transactions "
        "WHERE transaction_id = %s",
        (payload["compensation_transaction_id"],),
    ).fetchone()
    assert transaction["transaction_type"] == "roll_recalculation"
    assert transaction["status"] == "applied"
    assert transaction["payload"]["original_rolls"][0]["result"] == 42
    assert transaction["payload"]["original_rolls"][0]["values"]["candidates"] == [42]
    assert transaction["payload"]["state_version_before"] == before_state_version
    assert transaction["payload"]["state_version_after"] == before_state_version
    assert test_db.execute(
        "SELECT result FROM actions WHERE action_id = 'review-action'"
    ).fetchone()["result"] == original
    assert test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s", (room["room_id"],)
    ).fetchone()["state_version"] == before_state_version


def test_recalculation_rejects_tampered_receipt_and_client_roll_fields(client, test_db, monkeypatch):
    room, _joined, review, explanation = _setup_recalculable_review(client, test_db, monkeypatch)
    explanation["verification_receipt"]["signature"] = "tampered"
    test_db.execute(
        "UPDATE resolution_bundles SET rule_explanation = %s WHERE action_id = 'review-action'",
        (json.dumps(explanation, ensure_ascii=False),),
    )
    test_db.commit()
    headers = {"X-Owner-Token": room["owner_token"]}

    tampered = client.post(
        f"/api/host/{room['room_id']}/action-reviews/{review['review_request_id']}/recalculate",
        headers=headers,
        json={"difficulty": "hard", "reason": "难度参数录入错误"},
    )
    forged_roll = client.post(
        f"/api/host/{room['room_id']}/action-reviews/{review['review_request_id']}/recalculate",
        headers=headers,
        json={"difficulty": "hard", "reason": "难度参数录入错误", "roll": 1},
    )

    assert tampered.status_code == 422
    assert tampered.json()["detail"]["code"] == "roll_receipt_invalid"
    assert forged_roll.status_code == 422
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM compensation_transactions"
    ).fetchone()["count"] == 0
    assert test_db.execute(
        "SELECT status FROM action_review_requests WHERE review_request_id = %s",
        (review["review_request_id"],),
    ).fetchone()["status"] == "pending"
