import json

import pytest

from src.server.models import ActionDraftAnalyzeRequest
from src.server.player.action_service import analyze_action_draft
from tests.server.conftest import create_room, setup_auth_test_data


def _setup_player(client, test_db):
    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    joined = client.post(f"/api/player/rooms/{room_id}/join").json()
    return room_id, joined["character_id"], joined["player_token"]


def test_prepared_action_requires_whitelisted_trigger_and_safe_reaction():
    draft = analyze_action_draft(
        ActionDraftAnalyzeRequest(
            declared_intent="敌人公开攻击时我躲到柱子后",
            intent_type="prepared_action",
            params={
                "triggerKind": "enemy_public_attack_declared",
                "reactionKind": "take_cover",
            },
        )
    )

    assert draft.intent_type == "prepared_action"
    assert draft.risk == "high"
    assert draft.requires_confirmation is True
    assert set(draft.confirmation_requirements) >= {"prepared_action", "state_change"}
    assert draft.params == {
        "triggerKind": "enemy_public_attack_declared",
        "reactionKind": "take_cover",
    }


def test_natural_language_preparation_is_classified_without_a_hidden_command():
    draft = analyze_action_draft(
        ActionDraftAnalyzeRequest(
            declared_intent="如果敌人公开开枪攻击，我就躲到柱子后。",
        )
    )

    assert draft.intent_type == "prepared_action"
    assert draft.params == {
        "triggerKind": "enemy_public_attack_declared",
        "reactionKind": "take_cover",
    }
    assert set(draft.confirmation_requirements) >= {"prepared_action", "state_change"}


def test_confirmed_prepared_action_arms_without_queuing_a_reaction(client, test_db):
    room_id, character_id, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    before = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={
            "declared_intent": "敌人公开攻击时我躲到柱子后",
            "intent_type": "prepared_action",
            "params": {
                "triggerKind": "enemy_public_attack_declared",
                "reactionKind": "take_cover",
            },
        },
    ).json()

    response = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "arm-cover-1"},
        json={"confirmations": draft["confirmation_requirements"]},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "armed"
    armed = test_db.execute(
        "SELECT action_id, room_id, character_id, trigger_kind, reaction_kind, status "
        "FROM prepared_rule_actions WHERE action_id = %s",
        (response.json()["action_id"],),
    ).fetchone()
    assert dict(armed) == {
        "action_id": response.json()["action_id"],
        "room_id": room_id,
        "character_id": character_id,
        "trigger_kind": "enemy_public_attack_declared",
        "reaction_kind": "take_cover",
        "status": "armed",
    }
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM actions WHERE room_id = %s AND status = 'queued'",
        (room_id,),
    ).fetchone()["count"] == 0
    after = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()
    assert after["state_version"] == before["state_version"]


def test_authoritative_rule_event_consumes_an_armed_reaction_only_once(client, test_db):
    from src.server.engine.prepared_rule_actions import (
        PreparedRuleEvent,
        complete_triggered_prepared_reaction,
        consume_prepared_actions_for_rule_event,
    )

    room_id, character_id, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={
            "declared_intent": "敌人公开攻击时我躲到柱子后",
            "intent_type": "prepared_action",
            "params": {
                "triggerKind": "enemy_public_attack_declared",
                "reactionKind": "take_cover",
            },
        },
    ).json()
    armed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "arm-cover-trigger"},
        json={"confirmations": draft["confirmation_requirements"]},
    ).json()
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, status) "
        "VALUES (%s, %s, %s, 'combat_action', 'completed')",
        ("enemy-action-1", room_id, character_id),
    )
    test_db.commit()

    event = PreparedRuleEvent.enemy_public_attack_declared()
    first = consume_prepared_actions_for_rule_event(
        test_db,
        room_id=room_id,
        source_action_id="enemy-action-1",
        rule_event=event,
    )
    second = consume_prepared_actions_for_rule_event(
        test_db,
        room_id=room_id,
        source_action_id="enemy-action-1",
        rule_event=event,
    )

    assert len(first) == 1
    assert first[0]["prepared_action_id"] == armed["action_id"]
    assert first[0]["reaction_kind"] == "take_cover"
    assert second == []
    prepared = test_db.execute(
        "SELECT status, source_action_id FROM prepared_rule_actions WHERE action_id = %s",
        (armed["action_id"],),
    ).fetchone()
    assert dict(prepared) == {"status": "triggered", "source_action_id": "enemy-action-1"}
    queued = test_db.execute(
        "SELECT intent_type, params FROM actions WHERE action_id = %s",
        (first[0]["reaction_action_id"],),
    ).fetchone()
    assert queued["intent_type"] == "combat_action"
    assert queued["params"]["preparedActionId"] == armed["action_id"]
    assert queued["params"]["actionKind"] == "defend"
    assert complete_triggered_prepared_reaction(
        test_db,
        reaction_action_id=first[0]["reaction_action_id"],
        terminal_status="completed",
    ) is True
    completed = test_db.execute(
        "SELECT status FROM prepared_rule_actions WHERE action_id = %s",
        (armed["action_id"],),
    ).fetchone()
    assert completed["status"] == "completed"


def test_client_like_event_payload_cannot_consume_an_armed_reaction(client, test_db):
    from src.server.engine.prepared_rule_actions import consume_prepared_actions_for_rule_event

    room_id, character_id, _ = _setup_player(client, test_db)
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, status) "
        "VALUES (%s, %s, %s, 'combat_action', 'completed')",
        ("enemy-action-2", room_id, character_id),
    )
    test_db.commit()

    assert consume_prepared_actions_for_rule_event(
        test_db,
        room_id=room_id,
        source_action_id="enemy-action-2",
        rule_event={"kind": "enemy_public_attack_declared", "visibility": "public"},
    ) == []


def test_player_can_cancel_an_armed_prepared_action_before_it_triggers(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={
            "declared_intent": "敌人公开攻击时我躲到柱子后",
            "intent_type": "prepared_action",
            "params": {
                "triggerKind": "enemy_public_attack_declared",
                "reactionKind": "take_cover",
            },
        },
    ).json()
    armed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "arm-cancel-1"},
        json={"confirmations": draft["confirmation_requirements"]},
    ).json()

    response = client.post(
        f"/api/player/actions/{armed['action_id']}/cancel",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "canceled"
    status = test_db.execute(
        "SELECT status FROM prepared_rule_actions WHERE action_id = %s",
        (armed["action_id"],),
    ).fetchone()
    assert status["status"] == "canceled"


def test_black_bear_attack_declaration_consumes_matching_armed_action(client, test_db):
    from src.server.encounter_persistence import add_participant, create_encounter
    from src.server.engine.solo_combat_reactions import queue_black_bear_reaction

    room_id, character_id, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={
            "declared_intent": "敌人公开攻击时我躲到柱子后",
            "intent_type": "prepared_action",
            "params": {
                "triggerKind": "enemy_public_attack_declared",
                "reactionKind": "take_cover",
            },
        },
    ).json()
    armed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "arm-bear-cover"},
        json={"confirmations": draft["confirmation_requirements"]},
    ).json()
    encounter_id = "prepared-bear-encounter"
    create_encounter(test_db, encounter_id, room_id, "combat", "active", "test")
    add_participant(test_db, encounter_id, character_id, side="player", hp=10, hp_max=10)
    add_participant(
        test_db,
        encounter_id,
        "npc:prepared-bear",
        side="enemy",
        hp=20,
        hp_max=20,
        display_name="黑熊",
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, params, status) "
        "VALUES (%s, %s, %s, 'combat_action', %s, 'completed')",
        ("bear-source-action", room_id, character_id, json.dumps({"encounterId": encounter_id})),
    )
    test_db.commit()

    queued_enemy_attack = queue_black_bear_reaction(
        test_db,
        room_id=room_id,
        encounter_id=encounter_id,
        character_id=character_id,
        source_action_id="bear-source-action",
    )

    assert queued_enemy_attack is not None
    prepared = test_db.execute(
        "SELECT status, source_action_id FROM prepared_rule_actions WHERE action_id = %s",
        (armed["action_id"],),
    ).fetchone()
    assert dict(prepared) == {
        "status": "triggered",
        "source_action_id": "bear-source-action",
    }


@pytest.mark.asyncio
async def test_combat_start_rule_event_consumes_armed_action_after_authoritative_resolution(
    client, test_db
):
    from src.server.encounter_persistence import add_participant, create_encounter
    from src.server.engine.resolution_pipeline import ResolutionPipeline
    from src.server.models import PlayerIntent, ResolutionResult

    room_id, character_id, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={
            "declared_intent": "When combat starts, I take cover.",
            "intent_type": "prepared_action",
            "params": {
                "triggerKind": "combat_started",
                "reactionKind": "take_cover",
            },
        },
    ).json()
    armed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "arm-combat-start-cover"},
        json={"confirmations": draft["confirmation_requirements"]},
    ).json()
    encounter_id = "prepared-combat-start"
    create_encounter(test_db, encounter_id, room_id, "combat", "active", "test")
    add_participant(test_db, encounter_id, character_id, side="player", hp=10, hp_max=10)
    add_participant(
        test_db,
        encounter_id,
        "npc:prepared-watcher",
        side="enemy",
        hp=10,
        hp_max=10,
        display_name="Watcher",
        public_visibility="visible",
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, params, status) "
        "VALUES ('prepared-combat-start-source', %s, %s, 'combat_action', '{}', 'completed')",
        (room_id, character_id),
    )
    test_db.commit()

    triggered = await ResolutionPipeline(test_db)._apply_encounter_result(
        {
            "action_id": "prepared-combat-start-source",
            "room_id": room_id,
            "character_id": character_id,
        },
        PlayerIntent(
            intent_type="combat_action",
            params={"encounterId": encounter_id, "combatStarted": encounter_id},
        ),
        ResolutionResult(
            actionId="prepared-combat-start-source",
            roomId=room_id,
            characterId=character_id,
            mechanic="combat_attack",
            isSuccess=True,
        ),
    )

    assert len(triggered) == 1
    assert triggered[0]["prepared_action_id"] == armed["action_id"]
    reaction = test_db.execute(
        "SELECT params FROM actions WHERE action_id = %s",
        (triggered[0]["reaction_action_id"],),
    ).fetchone()
    assert reaction["params"]["encounterId"] == encounter_id


@pytest.mark.asyncio
async def test_public_enemy_entering_melee_range_consumes_armed_withdrawal(
    client, test_db
):
    from src.server.encounter_persistence import add_participant, create_encounter
    from src.server.engine.resolution_pipeline import ResolutionPipeline
    from src.server.models import PlayerIntent, ResolutionResult

    room_id, character_id, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={
            "declared_intent": "When an enemy reaches melee range, I withdraw.",
            "intent_type": "prepared_action",
            "params": {
                "triggerKind": "enemy_enters_melee_range",
                "reactionKind": "withdraw",
            },
        },
    ).json()
    armed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "arm-melee-withdraw"},
        json={"confirmations": draft["confirmation_requirements"]},
    ).json()
    encounter_id = "prepared-enemy-melee"
    enemy_id = "npc:prepared-melee"
    create_encounter(test_db, encounter_id, room_id, "combat", "active", "test")
    add_participant(test_db, encounter_id, character_id, side="player", hp=10, hp_max=10)
    add_participant(
        test_db,
        encounter_id,
        enemy_id,
        side="enemy",
        hp=10,
        hp_max=10,
        distance_band="near",
        display_name="Watcher",
        public_visibility="visible",
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, params, status) "
        "VALUES ('prepared-melee-source', %s, %s, 'combat_action', '{}', 'completed')",
        (room_id, character_id),
    )
    test_db.commit()

    triggered = await ResolutionPipeline(test_db)._apply_encounter_result(
        {
            "action_id": "prepared-melee-source",
            "room_id": room_id,
            "character_id": character_id,
        },
        PlayerIntent(intent_type="combat_action", params={"encounterId": encounter_id}),
        ResolutionResult(
            actionId="prepared-melee-source",
            roomId=room_id,
            characterId=character_id,
            mechanic="combat_attack",
            isSuccess=True,
            mutations=[
                {
                    "op": "replace",
                    "path": (
                        f"/encounter/{encounter_id}/participants/{enemy_id}/distance_band_delta"
                    ),
                    "value": -1,
                }
            ],
        ),
    )

    assert len(triggered) == 1
    assert triggered[0]["prepared_action_id"] == armed["action_id"]
    reaction = test_db.execute(
        "SELECT params FROM actions WHERE action_id = %s",
        (triggered[0]["reaction_action_id"],),
    ).fetchone()
    assert reaction["params"]["preparedRuleEvent"] == "enemy_enters_melee_range"
    assert reaction["params"]["encounterId"] == encounter_id


@pytest.mark.asyncio
async def test_public_damage_to_another_player_consumes_armed_protection(client, test_db):
    from src.server.encounter_persistence import add_participant, create_encounter
    from src.server.engine.resolution_pipeline import ResolutionPipeline
    from src.server.models import PlayerIntent, ResolutionResult

    room_id, character_id, player_token = _setup_player(client, test_db)
    ally = client.post(f"/api/player/rooms/{room_id}/join").json()
    attacker_id = "npc:prepared-attacker"
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, status, xlsx_data) "
        "VALUES (%s, %s, 'Watcher', 'prepared-attacker-token', 'ready', '{}')",
        (attacker_id, room_id),
    )
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={
            "declared_intent": "If an ally is publicly hurt, I protect them.",
            "intent_type": "prepared_action",
            "params": {
                "triggerKind": "ally_publicly_hurt",
                "reactionKind": "protect_ally",
                "targetId": ally["character_id"],
            },
        },
    ).json()
    armed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "arm-protect-public-ally"},
        json={"confirmations": draft["confirmation_requirements"]},
    ).json()
    encounter_id = "prepared-public-ally-harm"
    create_encounter(test_db, encounter_id, room_id, "combat", "active", "test")
    add_participant(test_db, encounter_id, character_id, side="player", hp=10, hp_max=10)
    add_participant(test_db, encounter_id, ally["character_id"], side="player", hp=10, hp_max=10)
    add_participant(
        test_db,
        encounter_id,
        attacker_id,
        side="enemy",
        hp=10,
        hp_max=10,
        display_name="Watcher",
        public_visibility="visible",
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, params, status) "
        "VALUES ('prepared-ally-harm-source', %s, %s, 'combat_action', '{}', 'completed')",
        (room_id, attacker_id),
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, params, status) "
        "VALUES ('prepared-private-ally-harm-source', %s, %s, 'combat_action', '{}', 'completed')",
        (room_id, attacker_id),
    )
    test_db.commit()

    pipeline = ResolutionPipeline(test_db)
    private_triggered = await pipeline._apply_encounter_result(
        {
            "action_id": "prepared-private-ally-harm-source",
            "room_id": room_id,
            "character_id": attacker_id,
        },
        PlayerIntent(
            intent_type="combat_action",
            params={"encounterId": encounter_id, "visibility": "private"},
        ),
        ResolutionResult(
            actionId="prepared-private-ally-harm-source",
            roomId=room_id,
            characterId=attacker_id,
            mechanic="combat_attack",
            isSuccess=True,
            mutations=[
                {
                    "op": "replace",
                    "path": (
                        f"/encounter/{encounter_id}/participants/{ally['character_id']}/hp_delta"
                    ),
                    "value": -1,
                }
            ],
        ),
    )

    assert private_triggered == []
    assert test_db.execute(
        "SELECT status FROM prepared_rule_actions WHERE action_id = %s",
        (armed["action_id"],),
    ).fetchone()["status"] == "armed"

    triggered = await pipeline._apply_encounter_result(
        {
            "action_id": "prepared-ally-harm-source",
            "room_id": room_id,
            "character_id": attacker_id,
        },
        PlayerIntent(intent_type="combat_action", params={"encounterId": encounter_id}),
        ResolutionResult(
            actionId="prepared-ally-harm-source",
            roomId=room_id,
            characterId=attacker_id,
            mechanic="combat_attack",
            isSuccess=True,
            mutations=[
                {
                    "op": "replace",
                    "path": (
                        f"/encounter/{encounter_id}/participants/{ally['character_id']}/hp_delta"
                    ),
                    "value": -2,
                }
            ],
        ),
    )

    assert len(triggered) == 1
    assert triggered[0]["prepared_action_id"] == armed["action_id"]
    reaction = test_db.execute(
        "SELECT params FROM actions WHERE action_id = %s",
        (triggered[0]["reaction_action_id"],),
    ).fetchone()
    assert reaction["params"]["preparedRuleEvent"] == "ally_publicly_hurt"
    assert reaction["params"]["targetId"] == ally["character_id"]


@pytest.mark.asyncio
async def test_triggered_reaction_completes_its_source_preparation(client, test_db):
    from src.server.encounter_persistence import add_participant, create_encounter
    from src.server.engine.resolution_pipeline import ResolutionPipeline
    from src.server.engine.solo_combat_reactions import queue_black_bear_reaction

    room_id, character_id, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={
            "declared_intent": "敌人公开攻击时我躲到柱子后",
            "intent_type": "prepared_action",
            "params": {
                "triggerKind": "enemy_public_attack_declared",
                "reactionKind": "take_cover",
            },
        },
    ).json()
    armed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "arm-bear-resolve"},
        json={"confirmations": draft["confirmation_requirements"]},
    ).json()
    encounter_id = "prepared-bear-resolve"
    create_encounter(test_db, encounter_id, room_id, "combat", "active", "test")
    add_participant(test_db, encounter_id, character_id, side="player", hp=10, hp_max=10)
    add_participant(
        test_db,
        encounter_id,
        "npc:prepared-bear-resolve",
        side="enemy",
        hp=20,
        hp_max=20,
        display_name="黑熊",
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, params, status) "
        "VALUES (%s, %s, %s, 'combat_action', %s, 'completed')",
        (
            "bear-source-resolve",
            room_id,
            character_id,
            json.dumps({"encounterId": encounter_id}),
        ),
    )
    test_db.commit()
    queue_black_bear_reaction(
        test_db,
        room_id=room_id,
        encounter_id=encounter_id,
        character_id=character_id,
        source_action_id="bear-source-resolve",
    )
    reaction = test_db.execute(
        "SELECT action_id FROM actions WHERE params ->> 'preparedActionId' = %s",
        (armed["action_id"],),
    ).fetchone()

    result = await ResolutionPipeline(test_db).resolve_action(reaction["action_id"])

    assert result["status"] in {"completed", "resolved"}
    prepared = test_db.execute(
        "SELECT status FROM prepared_rule_actions WHERE action_id = %s",
        (armed["action_id"],),
    ).fetchone()
    assert prepared["status"] == "completed"


@pytest.mark.asyncio
async def test_source_combat_resolution_automatically_settles_triggered_reaction(client, test_db):
    from src.server.encounter_persistence import add_participant, create_encounter
    from src.server.engine.resolution_pipeline import ResolutionPipeline

    room_id, character_id, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={
            "declared_intent": "敌人公开攻击时我躲到柱子后",
            "intent_type": "prepared_action",
            "params": {
                "triggerKind": "enemy_public_attack_declared",
                "reactionKind": "take_cover",
            },
        },
    ).json()
    armed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "arm-bear-auto"},
        json={"confirmations": draft["confirmation_requirements"]},
    ).json()
    encounter_id = "prepared-bear-auto"
    create_encounter(test_db, encounter_id, room_id, "combat", "active", "test")
    add_participant(test_db, encounter_id, character_id, side="player", hp=10, hp_max=10)
    add_participant(
        test_db,
        encounter_id,
        "npc:prepared-bear-auto",
        side="enemy",
        hp=20,
        hp_max=20,
        display_name="黑熊",
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, params, status) "
        "VALUES (%s, %s, %s, 'combat_action', %s, %s, 'queued')",
        (
            "bear-source-auto",
            room_id,
            character_id,
            "我攻击黑熊",
            json.dumps({"encounterId": encounter_id, "actionKind": "attack"}),
        ),
    )
    test_db.commit()

    source_result = await ResolutionPipeline(test_db).resolve_action("bear-source-auto")

    assert source_result["status"] in {"completed", "resolved"}
    reaction = test_db.execute(
        "SELECT status FROM actions WHERE params ->> 'preparedActionId' = %s",
        (armed["action_id"],),
    ).fetchone()
    assert reaction["status"] in {"completed", "resolved"}
    prepared = test_db.execute(
        "SELECT status FROM prepared_rule_actions WHERE action_id = %s",
        (armed["action_id"],),
    ).fetchone()
    assert prepared["status"] == "completed"


def test_protect_ally_preserves_an_explicit_same_room_target(client, test_db):
    from src.server.engine.prepared_rule_actions import (
        PreparedRuleEvent,
        consume_prepared_actions_for_rule_event,
    )

    room_id, character_id, player_token = _setup_player(client, test_db)
    ally = client.post(f"/api/player/rooms/{room_id}/join").json()
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={
            "declared_intent": "If a public attack hurts my ally, I protect them.",
            "intent_type": "prepared_action",
            "params": {
                "triggerKind": "ally_publicly_hurt",
                "reactionKind": "protect_ally",
                "targetId": ally["character_id"],
            },
        },
    ).json()
    assert draft["params"]["targetId"] == ally["character_id"]
    armed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "arm-protect-ally"},
        json={"confirmations": draft["confirmation_requirements"]},
    ).json()
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, status) "
        "VALUES (%s, %s, %s, 'combat_action', 'completed')",
        ("ally-hurt-source", room_id, character_id),
    )
    test_db.commit()

    triggered = consume_prepared_actions_for_rule_event(
        test_db,
        room_id=room_id,
        source_action_id="ally-hurt-source",
        rule_event=PreparedRuleEvent(kind="ally_publicly_hurt"),
    )

    assert len(triggered) == 1
    reaction = test_db.execute(
        "SELECT params FROM actions WHERE action_id = %s",
        (triggered[0]["reaction_action_id"],),
    ).fetchone()
    assert reaction["params"]["targetId"] == ally["character_id"]
    assert armed["status"] == "armed"


@pytest.mark.asyncio
async def test_rejected_internal_reaction_closes_its_source_preparation(client, test_db):
    from src.server.engine.prepared_rule_actions import (
        PreparedRuleEvent,
        consume_prepared_actions_for_rule_event,
    )
    from src.server.engine.resolution_pipeline import ResolutionPipeline

    room_id, character_id, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={
            "declared_intent": "When an enemy publicly attacks, take cover.",
            "intent_type": "prepared_action",
            "params": {
                "triggerKind": "enemy_public_attack_declared",
                "reactionKind": "take_cover",
            },
        },
    ).json()
    armed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "arm-rejected-reaction"},
        json={"confirmations": draft["confirmation_requirements"]},
    ).json()
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, status) "
        "VALUES (%s, %s, %s, 'combat_action', 'completed')",
        ("prepared-reject-source", room_id, character_id),
    )
    test_db.commit()
    triggered = consume_prepared_actions_for_rule_event(
        test_db,
        room_id=room_id,
        source_action_id="prepared-reject-source",
        rule_event=PreparedRuleEvent.enemy_public_attack_declared(),
    )
    reaction = test_db.execute(
        "SELECT * FROM actions WHERE action_id = %s",
        (triggered[0]["reaction_action_id"],),
    ).fetchone()

    await ResolutionPipeline(test_db)._reject(dict(reaction), "forced_rejection")

    prepared = test_db.execute(
        "SELECT status FROM prepared_rule_actions WHERE action_id = %s",
        (armed["action_id"],),
    ).fetchone()
    assert prepared["status"] == "rejected"
