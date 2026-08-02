import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from src.server.combat_round_planner import build_combat_round_plan
from src.server.db_adapter import PgConnection
from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.engine.state_service import (
    StateService,
    acquire_action_conflict_locks,
    build_action_conflict_guard,
    validate_action_conflict_guard,
)
from src.server.models import CharacterMutationItem, StateChangeSet
from src.server.player.action_service import confirm_action_draft
from tests.server.conftest import create_room, setup_auth_test_data


def _setup_runtime_room(client, test_db, player_count=3):
    setup_auth_test_data(test_db)
    room = create_room(client)
    players = [
        client.post(f"/api/player/rooms/{room['room_id']}/join").json()
        for _ in range(player_count)
    ]
    for index, player in enumerate(players, start=1):
        test_db.execute(
            "UPDATE characters SET xlsx_data = %s WHERE character_id = %s",
            (
                json.dumps(
                    {
                        "name": f"Player {index}",
                        "hp": 10,
                        "max_hp": 10,
                        "san": 50,
                        "max_san": 50,
                        "mp": 10,
                        "max_mp": 10,
                        "luck": 50,
                    }
                ),
                player["character_id"],
            ),
        )
    test_db.execute(
        "INSERT INTO room_scene_state (room_id, current_scene, version) "
        "VALUES (%s, 'scene-a', 1)",
        (room["room_id"],),
    )
    test_db.commit()
    service = StateService(test_db)
    for player in players:
        service.initialize_character_state(player["character_id"], room["room_id"])
    return room, players, service


def test_same_character_same_idempotency_key_concurrently_creates_one_action(
    client,
    test_db,
    monkeypatch,
):
    room, players, _ = _setup_runtime_room(client, test_db, player_count=1)
    player = players[0]
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers={"X-Room-Token": player["player_token"]},
        json={"declared_intent": "我观察桌上的旧报纸。"},
    ).json()
    character = dict(
        test_db.execute(
            "SELECT * FROM characters WHERE character_id = %s",
            (player["character_id"],),
        ).fetchone()
    )
    initial_reads = Barrier(2)
    original_execute = PgConnection.execute

    def synchronized_execute(conn, sql, params=None):
        result = original_execute(conn, sql, params)
        if (
            "SELECT action_id, draft_id FROM actions WHERE character_id" in sql
            and not getattr(conn, "_task5_idempotency_read", False)
        ):
            conn._task5_idempotency_read = True
            initial_reads.wait(timeout=5)
        return result

    monkeypatch.setattr(PgConnection, "execute", synchronized_execute)

    def confirm_once():
        conn = PgConnection(test_db._pool)
        try:
            return confirm_action_draft(
                conn,
                character,
                draft["draft_id"],
                "task5-same-key",
                draft["confirmation_requirements"],
            )
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(executor.map(lambda _: confirm_once(), range(2)))

    assert receipts[0].action_id == receipts[1].action_id
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM actions WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["count"] == 1


def test_unrelated_same_version_actions_can_both_apply(client, test_db):
    room, players, service = _setup_runtime_room(client, test_db, player_count=2)
    first, second = players
    first_guard = build_action_conflict_guard(
        test_db,
        room_id=room["room_id"],
        actor_character_id=first["character_id"],
        intent_type="skill_check",
        params={"skillName": "侦查"},
        base_state_version=0,
    )
    second_guard = build_action_conflict_guard(
        test_db,
        room_id=room["room_id"],
        actor_character_id=second["character_id"],
        intent_type="skill_check",
        params={"skillName": "图书馆使用"},
        base_state_version=0,
    )

    first_result = service.apply_change(
        room["room_id"],
        {"character_id": first["character_id"], "action_id": "first"},
        StateChangeSet(
            characterMutations=[
                CharacterMutationItem(
                    characterId=first["character_id"],
                    mutations=[{"op": "replace", "path": "/character/hp", "value": 9}],
                )
            ]
        ),
    )
    assert validate_action_conflict_guard(test_db, second_guard) is None
    second_result = service.apply_change(
        room["room_id"],
        {"character_id": second["character_id"], "action_id": "second"},
        StateChangeSet(
            characterMutations=[
                CharacterMutationItem(
                    characterId=second["character_id"],
                    mutations=[{"op": "replace", "path": "/character/hp", "value": 8}],
                )
            ]
        ),
    )

    assert first_result["state_version"] == 1
    assert second_result["state_version"] == 2
    assert validate_action_conflict_guard(test_db, first_guard) == "actor_state_changed"


def test_shared_unique_item_and_shared_target_are_revalidated_after_serialization(
    client,
    test_db,
):
    room, players, _ = _setup_runtime_room(client, test_db, player_count=3)
    first, second, target = players
    test_db.execute(
        "INSERT INTO inventory (id, character_id, room_id, name, quantity, version) "
        "VALUES ('one-only-item', %s, %s, '唯一钥匙', 1, 1)",
        (first["character_id"], room["room_id"]),
    )
    test_db.commit()
    item_guard = build_action_conflict_guard(
        test_db,
        room_id=room["room_id"],
        actor_character_id=first["character_id"],
        intent_type="use_item",
        params={"itemId": "one-only-item", "actionKind": "consume"},
        base_state_version=0,
    )
    target_guard = build_action_conflict_guard(
        test_db,
        room_id=room["room_id"],
        actor_character_id=second["character_id"],
        intent_type="combat_action",
        params={"targetId": target["character_id"]},
        base_state_version=0,
    )

    with test_db.transaction() as tx:
        acquire_action_conflict_locks(tx, item_guard)
        tx.execute("DELETE FROM inventory WHERE id = 'one-only-item'")
    assert validate_action_conflict_guard(test_db, item_guard) == "resource_conflict"

    test_db.execute(
        "UPDATE character_runtime_state SET hp = hp - 1, version = version + 1 "
        "WHERE room_id = %s AND character_id = %s",
        (room["room_id"], target["character_id"]),
    )
    test_db.commit()
    assert validate_action_conflict_guard(test_db, target_guard) == "target_state_changed"

    assert "client:forged" not in build_action_conflict_guard(
        test_db,
        room_id=room["room_id"],
        actor_character_id=second["character_id"],
        intent_type="skill_check",
        params={"_conflictKeys": ["client:forged"]},
        base_state_version=0,
    )["keys"]


def test_scene_and_risk_context_changes_fail_closed_but_same_turn_scene_drift_is_allowed(
    client,
    test_db,
):
    room, players, _ = _setup_runtime_room(client, test_db, player_count=1)
    player = players[0]
    test_db.execute(
        "UPDATE rooms SET risk_contract_hash = 'risk-v1' WHERE room_id = %s",
        (room["room_id"],),
    )
    test_db.commit()
    guard = build_action_conflict_guard(
        test_db,
        room_id=room["room_id"],
        actor_character_id=player["character_id"],
        intent_type="move",
        params={"fromNodeId": "scene-a", "targetNodeId": "scene-b"},
        base_state_version=0,
    )
    test_db.execute(
        "UPDATE room_scene_state SET current_scene = 'scene-b', version = version + 1 "
        "WHERE room_id = %s",
        (room["room_id"],),
    )
    test_db.commit()

    assert validate_action_conflict_guard(test_db, guard) == "scene_context_changed"
    assert f"scene:{room['room_id']}" in guard["keys"]
    assert validate_action_conflict_guard(
        test_db,
        guard,
        allow_same_turn_scene_drift=True,
    ) is None

    test_db.execute(
        "UPDATE room_scene_state SET current_scene = 'scene-c', version = version + 1 "
        "WHERE room_id = %s",
        (room["room_id"],),
    )
    test_db.commit()
    assert validate_action_conflict_guard(
        test_db,
        guard,
        allow_same_turn_scene_drift=True,
    ) == "scene_context_changed"

    test_db.execute(
        "UPDATE rooms SET risk_contract_hash = 'risk-v2' WHERE room_id = %s",
        (room["room_id"],),
    )
    test_db.commit()
    assert validate_action_conflict_guard(
        test_db,
        guard,
        allow_same_turn_scene_drift=True,
    ) == "risk_context_changed"


def test_pipeline_marks_stale_semantic_context_sync_required_without_running_rules(
    client,
    test_db,
):
    room, players, _ = _setup_runtime_room(client, test_db, player_count=1)
    player = players[0]
    headers = {"X-Room-Token": player["player_token"]}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={
            "declared_intent": "我前往侧厅。",
            "intent_type": "move",
            "params": {"fromNodeId": "scene-a", "targetNodeId": "scene-b"},
        },
    ).json()
    confirmed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "stale-semantic-context"},
        json={"confirmations": draft["confirmation_requirements"]},
    ).json()
    test_db.execute(
        "UPDATE room_scene_state SET current_scene = 'other-scene', version = version + 1 "
        "WHERE room_id = %s",
        (room["room_id"],),
    )
    test_db.commit()
    before_version = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"]

    result = asyncio.run(ResolutionPipeline(test_db).resolve_action(confirmed["action_id"]))

    assert result == {
        "status": "sync_required",
        "action_id": confirmed["action_id"],
        "reason": "scene_context_changed",
    }
    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s",
        (confirmed["action_id"],),
    ).fetchone()["status"] == "sync_required"
    event = test_db.execute(
        "SELECT metadata FROM action_status_events WHERE action_id = %s "
        "AND status = 'sync_required'",
        (confirmed["action_id"],),
    ).fetchone()
    assert event["metadata"] == {
        "conflict_category": "scene",
        "reason_code": "scene_context_changed",
    }
    assert test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"] == before_version


def test_combat_plan_serializes_only_actions_with_overlapping_server_conflict_keys():
    actions = [
        {
            "action_id": "first",
            "character_id": "a",
            "intent_type": "combat_action",
            "declared_intent": "攻击同一目标",
            "dex": 70,
            "params": {"_conflictGuard": {"keys": ["target:room:t"]}},
        },
        {
            "action_id": "second",
            "character_id": "b",
            "intent_type": "combat_action",
            "declared_intent": "也攻击同一目标",
            "dex": 60,
            "params": {"_conflictGuard": {"keys": ["target:room:t"]}},
        },
        {
            "action_id": "unrelated",
            "character_id": "c",
            "intent_type": "combat_action",
            "declared_intent": "攻击另一目标",
            "dex": 50,
            "params": {"_conflictGuard": {"keys": ["target:room:other"]}},
        },
    ]

    plan = build_combat_round_plan(
        turn_id="turn",
        encounter_id="encounter",
        round_number=1,
        actions=actions,
    )
    steps = {step["action_id"]: step for step in plan["steps"]}

    assert steps["first"]["depends_on"] == []
    assert steps["second"]["depends_on"] == ["first"]
    assert steps["unrelated"]["depends_on"] == []
