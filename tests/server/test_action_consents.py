from datetime import datetime, timedelta, timezone
import asyncio

from src.server.engine.action_consent import evaluate_group_decision
from src.server.engine.resolution_pipeline import ResolutionPipeline
from tests.server.conftest import create_room, setup_auth_test_data


def _setup_players(client, test_db, count=2):
    setup_auth_test_data(test_db)
    room = create_room(client)
    players = [
        client.post(f"/api/player/rooms/{room['room_id']}/join").json()
        for _ in range(count)
    ]
    return room, players


def _confirm_action(client, player, *, declared_intent, intent_type, params, key):
    headers = {"X-Room-Token": player["player_token"]}
    analyzed = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={
            "declared_intent": declared_intent,
            "intent_type": intent_type,
            "params": params,
        },
    )
    assert analyzed.status_code == 200, analyzed.text
    draft = analyzed.json()
    confirmed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": key},
        json={"confirmations": draft["confirmation_requirements"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


def test_pvp_damage_waits_for_the_affected_player_without_resolving(client, test_db):
    room, (actor, target) = _setup_players(client, test_db)
    before_version = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"]

    receipt = _confirm_action(
        client,
        actor,
        declared_intent="我攻击另一名调查员。",
        intent_type="combat_action",
        params={"targetId": target["character_id"], "pvpEffect": "damage"},
        key="pvp-damage-1",
    )

    assert receipt["status"] == "awaiting_player_consent"
    consent = test_db.execute(
        "SELECT * FROM action_consents WHERE action_id = %s",
        (receipt["action_id"],),
    ).fetchone()
    assert consent["affected_character_id"] == target["character_id"]
    assert consent["consent_kind"] == "pvp_damage"
    assert consent["decision"] == "pending"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM resolution_bundles WHERE action_id = %s",
        (receipt["action_id"],),
    ).fetchone()["count"] == 0
    assert test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"] == before_version


def test_only_current_target_identity_can_answer_and_response_is_idempotent(client, test_db):
    _, (actor, target) = _setup_players(client, test_db)
    receipt = _confirm_action(
        client,
        actor,
        declared_intent="我夺走对方手中的急救包。",
        intent_type="use_item",
        params={"targetId": target["character_id"], "pvpEffect": "resource_take"},
        key="pvp-resource-1",
    )
    pending = client.get(
        "/api/player/action-consents",
        headers={"X-Room-Token": target["player_token"]},
    )
    assert pending.status_code == 200, pending.text
    consent_id = pending.json()["items"][0]["consentId"]

    actor_answer = client.post(
        f"/api/player/action-consents/{consent_id}",
        headers={"X-Room-Token": actor["player_token"]},
        json={"accepted": True},
    )
    owner_answer = client.post(
        f"/api/player/action-consents/{consent_id}",
        headers={"X-Owner-Token": "not-a-player-token"},
        json={"accepted": True},
    )
    first = client.post(
        f"/api/player/action-consents/{consent_id}",
        headers={"X-Room-Token": target["player_token"]},
        json={"accepted": True},
    )
    replay = client.post(
        f"/api/player/action-consents/{consent_id}",
        headers={"X-Room-Token": target["player_token"]},
        json={"accepted": True},
    )

    assert actor_answer.status_code == 403
    assert owner_answer.status_code == 401
    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert first.json() == replay.json()
    assert first.json()["decision"] == "accepted"
    assert first.json()["actionStatus"] == "queued"
    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s",
        (receipt["action_id"],),
    ).fetchone()["status"] == "queued"


def test_rejection_or_expiry_ends_the_action_without_effects(client, test_db):
    room, (actor, target) = _setup_players(client, test_db)
    before_version = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"]
    rejected_action = _confirm_action(
        client,
        actor,
        declared_intent="我限制对方本回合不能行动。",
        intent_type="combat_action",
        params={"targetId": target["character_id"], "pvpEffect": "restrict_action"},
        key="pvp-reject-1",
    )
    rejected_consent = test_db.execute(
        "SELECT consent_id FROM action_consents WHERE action_id = %s",
        (rejected_action["action_id"],),
    ).fetchone()["consent_id"]
    response = client.post(
        f"/api/player/action-consents/{rejected_consent}",
        headers={"X-Room-Token": target["player_token"]},
        json={"accepted": False},
    )
    assert response.status_code == 200, response.text
    assert response.json()["actionStatus"] == "rejected"
    rejected_row = test_db.execute(
        "SELECT status, result FROM actions WHERE action_id = %s",
        (rejected_action["action_id"],),
    ).fetchone()
    assert rejected_row["status"] == "rejected"
    assert rejected_row["result"]["outcome"] == "no_effect"

    expired_action = _confirm_action(
        client,
        actor,
        declared_intent="我让对方陷入昏迷状态。",
        intent_type="combat_action",
        params={"targetId": target["character_id"], "pvpEffect": "status_change"},
        key="pvp-expire-1",
    )
    expired_consent = test_db.execute(
        "SELECT consent_id FROM action_consents WHERE action_id = %s",
        (expired_action["action_id"],),
    ).fetchone()["consent_id"]
    test_db.execute(
        "UPDATE action_consents SET expires_at = %s WHERE consent_id = %s",
        (datetime.now(timezone.utc) - timedelta(seconds=1), expired_consent),
    )
    test_db.commit()
    expired = client.post(
        f"/api/player/action-consents/{expired_consent}",
        headers={"X-Room-Token": target["player_token"]},
        json={"accepted": True},
    )

    assert expired.status_code == 409
    assert expired.json()["detail"]["code"] == "action_consent_expired"
    expired_row = test_db.execute(
        "SELECT status, result FROM actions WHERE action_id = %s",
        (expired_action["action_id"],),
    ).fetchone()
    assert expired_row["status"] == "timeout"
    assert expired_row["result"]["outcome"] == "no_effect"
    assert test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"] == before_version
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM resolution_bundles WHERE action_id = ANY(%s)",
        ([rejected_action["action_id"], expired_action["action_id"]],),
    ).fetchone()["count"] == 0


def test_consent_is_per_action_and_an_npc_target_does_not_require_pvp_consent(client, test_db):
    _, (actor, target) = _setup_players(client, test_db)
    first = _confirm_action(
        client,
        actor,
        declared_intent="我攻击另一名调查员。",
        intent_type="combat_action",
        params={"targetId": target["character_id"], "pvpEffect": "damage"},
        key="pvp-old-consent-1",
    )
    first_consent = test_db.execute(
        "SELECT consent_id FROM action_consents WHERE action_id = %s",
        (first["action_id"],),
    ).fetchone()["consent_id"]
    accepted = client.post(
        f"/api/player/action-consents/{first_consent}",
        headers={"X-Room-Token": target["player_token"]},
        json={"accepted": True},
    )
    assert accepted.status_code == 200
    test_db.execute(
        "UPDATE actions SET status = 'completed' WHERE action_id = %s",
        (first["action_id"],),
    )
    test_db.commit()

    second = _confirm_action(
        client,
        actor,
        declared_intent="我再次攻击另一名调查员。",
        intent_type="combat_action",
        params={"targetId": target["character_id"], "pvpEffect": "damage"},
        key="pvp-old-consent-2",
    )
    second_consent = test_db.execute(
        "SELECT consent_id, decision FROM action_consents WHERE action_id = %s",
        (second["action_id"],),
    ).fetchone()
    assert second["status"] == "awaiting_player_consent"
    assert second_consent["consent_id"] != first_consent
    assert second_consent["decision"] == "pending"

    test_db.execute(
        "UPDATE actions SET status = 'completed' WHERE action_id = %s",
        (second["action_id"],),
    )
    test_db.commit()
    npc = _confirm_action(
        client,
        actor,
        declared_intent="我攻击逼近的食尸鬼。",
        intent_type="combat_action",
        params={"targetId": "npc-ghoul", "pvpEffect": "damage"},
        key="npc-action-1",
    )
    assert npc["status"] == "queued"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM action_consents WHERE action_id = %s",
        (npc["action_id"],),
    ).fetchone()["count"] == 0


def test_group_decision_thresholds_fail_closed():
    majority = evaluate_group_decision(
        ["accepted", "accepted", "rejected"],
        "reversible_route",
        final=True,
    )
    tie = evaluate_group_decision(
        ["accepted", "accepted", "rejected", "pending"],
        "reversible_route",
        final=True,
    )
    ending = evaluate_group_decision(
        ["accepted", "accepted", "pending"],
        "ending",
        final=True,
    )

    assert majority["outcome"] == "approved"
    assert majority["requiredApprovals"] == 2
    assert tie["outcome"] == "safer_result"
    assert ending["outcome"] == "no_effect"
    assert ending["requiredApprovals"] == 3


def test_reversible_group_route_uses_majority_but_ending_requires_every_active_player(
    client,
    test_db,
):
    _, players = _setup_players(client, test_db, count=3)
    actor, first_voter, second_voter = players
    route = _confirm_action(
        client,
        actor,
        declared_intent="我们改走仍可返回的侧路。",
        intent_type="move",
        params={"groupDecisionKind": "reversible_route"},
        key="group-route-1",
    )
    assert route["status"] == "awaiting_player_consent"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM action_consents WHERE action_id = %s",
        (route["action_id"],),
    ).fetchone()["count"] == 3
    first_vote = test_db.execute(
        "SELECT consent_id FROM action_consents "
        "WHERE action_id = %s AND affected_character_id = %s",
        (route["action_id"], first_voter["character_id"]),
    ).fetchone()["consent_id"]
    accepted = client.post(
        f"/api/player/action-consents/{first_vote}",
        headers={"X-Room-Token": first_voter["player_token"]},
        json={"accepted": True},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["actionStatus"] == "queued"

    test_db.execute(
        "UPDATE actions SET status = 'completed' WHERE action_id = %s",
        (route["action_id"],),
    )
    test_db.commit()
    ending = _confirm_action(
        client,
        actor,
        declared_intent="我们现在触发最终结局。",
        intent_type="action",
        params={"groupDecisionKind": "ending"},
        key="group-ending-1",
    )
    first_ending_vote = test_db.execute(
        "SELECT consent_id FROM action_consents "
        "WHERE action_id = %s AND affected_character_id = %s",
        (ending["action_id"], first_voter["character_id"]),
    ).fetchone()["consent_id"]
    second_ending_vote = test_db.execute(
        "SELECT consent_id FROM action_consents "
        "WHERE action_id = %s AND affected_character_id = %s",
        (ending["action_id"], second_voter["character_id"]),
    ).fetchone()["consent_id"]
    first_acceptance = client.post(
        f"/api/player/action-consents/{first_ending_vote}",
        headers={"X-Room-Token": first_voter["player_token"]},
        json={"accepted": True},
    )
    assert first_acceptance.json()["actionStatus"] == "awaiting_player_consent"
    rejection = client.post(
        f"/api/player/action-consents/{second_ending_vote}",
        headers={"X-Room-Token": second_voter["player_token"]},
        json={"accepted": False},
    )
    assert rejection.json()["actionStatus"] == "rejected"
    assert test_db.execute(
        "SELECT result FROM actions WHERE action_id = %s",
        (ending["action_id"],),
    ).fetchone()["result"]["outcome"] == "no_effect"


def test_resolution_pipeline_refuses_a_queued_action_with_pending_consent(client, test_db):
    room, (actor, target) = _setup_players(client, test_db)
    receipt = _confirm_action(
        client,
        actor,
        declared_intent="我攻击另一名调查员。",
        intent_type="combat_action",
        params={"targetId": target["character_id"], "pvpEffect": "damage"},
        key="pvp-gate-1",
    )
    test_db.execute(
        "UPDATE actions SET status = 'queued' WHERE action_id = %s",
        (receipt["action_id"],),
    )
    test_db.commit()
    before = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"]

    result = asyncio.run(ResolutionPipeline(test_db).resolve_action(receipt["action_id"]))

    assert result["status"] == "queued"
    assert test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"] == before
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM resolution_bundles WHERE action_id = %s",
        (receipt["action_id"],),
    ).fetchone()["count"] == 0
