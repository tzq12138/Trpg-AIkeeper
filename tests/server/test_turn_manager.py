import json
import time

from src.server.turn_manager import TurnManager, _json_val
from tests.server.conftest import create_room, setup_auth_test_data


def test_ready_player_submission_settles_single_player_turn(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES ('turn-ready-room', 'owner', 'active')"
    )
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, status, xlsx_data)
        VALUES ('turn-ready-character', 'turn-ready-room', '玩家', 'token', 'ready', %s)
        """,
        (json.dumps({}),),
    )
    test_db.execute(
        """
        INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status)
        VALUES ('turn-ready-action', 'turn-ready-room', 'turn-ready-character', 'combat_action', '攻击黑熊', 'queued')
        """
    )

    turns = TurnManager(test_db)
    turns.submit_action('turn-ready-room', 'turn-ready-character', 'turn-ready-action')

    assert turns.all_submitted('turn-ready-room') is True


def test_turn_manager_parses_persisted_json_values():
    assert _json_val('{"steps": [{"action_id": "action-1"}]}') == {
        'steps': [{'action_id': 'action-1'}]
    }


def test_pending_affected_player_consent_blocks_turn_resolution(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) "
        "VALUES ('consent-turn-room', 'owner', 'active')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, status) "
        "VALUES ('consent-turn-character', 'consent-turn-room', 'Player', 'player-token', 'joined')"
    )
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('consent-turn-action', 'consent-turn-room', 'consent-turn-character', "
        "'combat_action', '等待受影响玩家同意', 'awaiting_player_consent')"
    )
    turns = TurnManager(test_db)
    turn = turns.ensure_current_turn("consent-turn-room")
    test_db.execute(
        "UPDATE actions SET turn_id = %s WHERE action_id = 'consent-turn-action'",
        (turn["turn_id"],),
    )
    test_db.commit()

    snapshot = turns.get_turn_snapshot("consent-turn-room")

    assert snapshot["players"][0]["submitted"] is True
    assert snapshot["all_submitted"] is False
    assert turns.all_submitted("consent-turn-room") is False


def test_active_combat_creates_a_declaration_round_with_encounter_context(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES ('combat-round-room', 'owner', 'active')"
    )
    for character_id in ('combat-round-a', 'combat-round-b'):
        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, status, xlsx_data) "
            "VALUES (%s, 'combat-round-room', %s, %s, 'ready', '{}')",
            (character_id, character_id, f'{character_id}-token'),
        )
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
        "VALUES ('combat-round-encounter', 'combat-round-room', 'combat', 'active', 0)"
    )
    test_db.commit()

    snapshot = TurnManager(test_db).get_turn_snapshot('combat-round-room')

    assert snapshot['mode'] == 'combat'
    assert snapshot['phase'] == 'declaration'
    assert snapshot['encounter_id'] == 'combat-round-encounter'
    assert snapshot['encounter_round'] == 1
    assert snapshot['all_submitted'] is False


def test_active_combat_does_not_reuse_an_open_scene_turn(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES ('combat-replaces-scene-room', 'owner', 'active')"
    )
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode) "
        "VALUES ('open-scene-turn', 'combat-replaces-scene-room', 1, 'collecting', 'scene')"
    )
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
        "VALUES ('combat-replaces-scene-encounter', 'combat-replaces-scene-room', 'combat', 'active', 0)"
    )
    test_db.commit()

    snapshot = TurnManager(test_db).get_turn_snapshot('combat-replaces-scene-room')

    assert snapshot['turn_id'] != 'open-scene-turn'
    assert snapshot['mode'] == 'combat'
    assert snapshot['phase'] == 'declaration'
    assert snapshot['encounter_id'] == 'combat-replaces-scene-encounter'
    assert snapshot['encounter_round'] == 1


def test_combat_round_plan_is_persisted_when_declarations_lock(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES ('combat-plan-room', 'owner', 'active')"
    )
    for character_id, dex in (('combat-plan-fast', 80), ('combat-plan-slow', 40)):
        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, status, xlsx_data) "
            "VALUES (%s, 'combat-plan-room', %s, %s, 'ready', '{}')",
            (character_id, character_id, f'{character_id}-token'),
        )
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
        "VALUES ('combat-plan-encounter', 'combat-plan-room', 'combat', 'active', 1)"
    )
    for character_id, dex in (('combat-plan-fast', 80), ('combat-plan-slow', 40)):
        test_db.execute(
            "INSERT INTO encounter_participants (encounter_id, character_id, dex) VALUES "
            "('combat-plan-encounter', %s, %s)",
            (character_id, dex),
        )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('combat-plan-slow-action', 'combat-plan-room', 'combat-plan-slow', 'combat_action', '我掩护安娜后退', 'queued')"
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('combat-plan-fast-action', 'combat-plan-room', 'combat-plan-fast', 'combat_action', '我朝人影开枪', 'queued')"
    )
    test_db.commit()

    turns = TurnManager(test_db)
    turn = turns.ensure_current_turn('combat-plan-room')
    turns.submit_action('combat-plan-room', 'combat-plan-slow', 'combat-plan-slow-action')
    turns.submit_action('combat-plan-room', 'combat-plan-fast', 'combat-plan-fast-action')
    assert turns.mark_resolving(turn['turn_id']) is True

    plan = turns.plan_combat_round(turn['turn_id'])
    stored = test_db.execute(
        "SELECT combat_plan FROM room_turns WHERE turn_id = %s", (turn['turn_id'],)
    ).fetchone()['combat_plan']

    assert [step['action_id'] for step in plan['steps']] == [
        'combat-plan-fast-action',
        'combat-plan-slow-action',
    ]
    assert stored['turn_id'] == turn['turn_id']


def test_combat_round_plan_includes_only_current_encounter_prepared_actions(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES ('prepared-plan-room', 'owner', 'active')"
    )
    for character_id, player_name in (
        ('prepared-plan-character', 'Ada'),
        ('prepared-plan-outside', 'Ben'),
    ):
        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, status, xlsx_data) "
            "VALUES (%s, 'prepared-plan-room', %s, %s, 'ready', '{}')",
            (character_id, player_name, f'{character_id}-token'),
        )
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
        "VALUES ('prepared-plan-encounter', 'prepared-plan-room', 'combat', 'active', 1)"
    )
    test_db.execute(
        "INSERT INTO encounter_participants (encounter_id, character_id, dex) VALUES "
        "('prepared-plan-encounter', 'prepared-plan-character', 65)"
    )
    for action_id, character_id in (
        ('prepared-plan-arm', 'prepared-plan-character'),
        ('prepared-plan-outside-arm', 'prepared-plan-outside'),
    ):
        test_db.execute(
            "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
            "VALUES (%s, 'prepared-plan-room', %s, 'prepared_action', 'I wait for a threat.', 'armed')",
            (action_id, character_id),
        )
        test_db.execute(
            "INSERT INTO prepared_rule_actions (action_id, room_id, character_id, trigger_kind, reaction_kind) "
            "VALUES (%s, 'prepared-plan-room', %s, 'enemy_public_attack_declared', 'take_cover')",
            (action_id, character_id),
        )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('prepared-plan-action', 'prepared-plan-room', 'prepared-plan-character', "
        "'combat_action', 'I keep watch.', 'queued')"
    )
    test_db.commit()

    turns = TurnManager(test_db)
    turn = turns.ensure_current_turn('prepared-plan-room')
    turns.submit_action('prepared-plan-room', 'prepared-plan-character', 'prepared-plan-action')
    assert turns.mark_resolving(turn['turn_id']) is True

    plan = turns.plan_combat_round(turn['turn_id'])

    assert plan['prepared_rule_actions'] == [
        {
            'character_id': 'prepared-plan-character',
            'actor_name': 'Ada',
            'trigger_kind': 'enemy_public_attack_declared',
            'reaction_kind': 'take_cover',
        }
    ]
    assert plan['observable_preparations'] == [
        'Ada举起武器，保持警戒。',
        'Ada 保持戒备，随时寻找掩护。',
    ]
    assert 'Ben' not in str(plan)


def test_combat_round_plan_includes_batched_collaboration_declarations(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES ('batched-combat-room', 'owner', 'active')"
    )
    for character_id, dex in (('batched-combat-fast', 80), ('batched-combat-slow', 40)):
        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, status, xlsx_data) "
            "VALUES (%s, 'batched-combat-room', %s, %s, 'ready', '{}')",
            (character_id, character_id, f'{character_id}-token'),
        )
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
        "VALUES ('batched-combat-encounter', 'batched-combat-room', 'combat', 'active', 1)"
    )
    for character_id, dex in (('batched-combat-fast', 80), ('batched-combat-slow', 40)):
        test_db.execute(
            "INSERT INTO encounter_participants (encounter_id, character_id, dex) VALUES "
            "('batched-combat-encounter', %s, %s)",
            (character_id, dex),
        )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('batched-combat-slow-action', 'batched-combat-room', 'batched-combat-slow', "
        "'combat_action', 'I cover the door.', 'batched')"
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('batched-combat-fast-action', 'batched-combat-room', 'batched-combat-fast', "
        "'combat_action', 'I rush the threat.', 'queued')"
    )
    test_db.commit()

    turns = TurnManager(test_db)
    turn = turns.ensure_current_turn('batched-combat-room')
    turns.submit_action('batched-combat-room', 'batched-combat-slow', 'batched-combat-slow-action')
    turns.submit_action('batched-combat-room', 'batched-combat-fast', 'batched-combat-fast-action')
    assert turns.mark_resolving(turn['turn_id']) is True

    plan = turns.plan_combat_round(turn['turn_id'])

    assert [step['action_id'] for step in plan['steps']] == [
        'batched-combat-fast-action',
        'batched-combat-slow-action',
    ]
    assert [action['action_id'] for action in turns.get_pending_actions(turn['turn_id'])] == [
        'batched-combat-fast-action',
        'batched-combat-slow-action',
    ]


def test_four_player_combat_round_locks_all_declarations_before_dex_planning(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES ('four-player-room', 'owner', 'active')"
    )
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
        "VALUES ('four-player-encounter', 'four-player-room', 'combat', 'active', 1)"
    )
    players = (
        ('four-player-a', 40),
        ('four-player-b', 80),
        ('four-player-c', 60),
        ('four-player-d', 20),
    )
    for character_id, dex in players:
        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, status, xlsx_data) "
            "VALUES (%s, 'four-player-room', %s, %s, 'ready', '{}')",
            (character_id, character_id, f'{character_id}-token'),
        )
        test_db.execute(
            "INSERT INTO encounter_participants (encounter_id, character_id, dex) VALUES "
            "('four-player-encounter', %s, %s)",
            (character_id, dex),
        )
        test_db.execute(
            "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
            "VALUES (%s, 'four-player-room', %s, 'combat_action', %s, 'queued')",
            (f'{character_id}-action', character_id, f'{character_id} keeps pressure on the threat'),
        )
    test_db.commit()

    turns = TurnManager(test_db)
    turn = turns.ensure_current_turn('four-player-room')
    for index, (character_id, _) in enumerate(players, start=1):
        turns.submit_action('four-player-room', character_id, f'{character_id}-action')
        assert turns.all_submitted('four-player-room') is (index == len(players))

    assert turns.mark_resolving(turn['turn_id']) is True
    plan = turns.plan_combat_round(turn['turn_id'])

    assert [step['action_id'] for step in plan['steps']] == [
        'four-player-b-action',
        'four-player-c-action',
        'four-player-a-action',
        'four-player-d-action',
    ]
    assert len(plan['presentation_clusters']) == 4


def test_eight_player_combat_round_plans_within_non_ai_latency_target(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES ('eight-player-room', 'owner', 'active')"
    )
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
        "VALUES ('eight-player-encounter', 'eight-player-room', 'combat', 'active', 1)"
    )
    for index in range(8):
        character_id = f'eight-player-{index}'
        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, status, xlsx_data) "
            "VALUES (%s, 'eight-player-room', %s, %s, 'ready', '{}')",
            (character_id, character_id, f'{character_id}-token'),
        )
        test_db.execute(
            "INSERT INTO encounter_participants (encounter_id, character_id, dex) VALUES "
            "('eight-player-encounter', %s, %s)",
            (character_id, 10 + index * 10),
        )
        test_db.execute(
            "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
            "VALUES (%s, 'eight-player-room', %s, 'combat_action', %s, 'queued')",
            (f'{character_id}-action', character_id, f'{character_id} declares a guarded advance'),
        )
    test_db.commit()

    turns = TurnManager(test_db)
    turn = turns.ensure_current_turn('eight-player-room')
    for index in range(8):
        character_id = f'eight-player-{index}'
        turns.submit_action('eight-player-room', character_id, f'{character_id}-action')
    assert turns.mark_resolving(turn['turn_id']) is True

    started_at = time.monotonic()
    plan = turns.plan_combat_round(turn['turn_id'])
    elapsed_seconds = time.monotonic() - started_at

    assert len(plan['steps']) == 8
    assert len(plan['presentation_clusters']) == 8
    assert elapsed_seconds <= 0.5


def test_pending_rule_reaction_blocks_opening_the_next_combat_round(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES ('reaction-block-room', 'owner', 'active')"
    )
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
        "VALUES ('reaction-block-encounter', 'reaction-block-room', 'combat', 'active', 2)"
    )
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode, encounter_id) "
        "VALUES ('reaction-block-turn', 'reaction-block-room', 1, 'resolved', 'combat', 'reaction-block-encounter')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, status) "
        "VALUES ('reaction-block-character', 'reaction-block-room', '玩家', 'token', 'ready')"
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('reaction-block-action', 'reaction-block-room', 'reaction-block-character', 'combat_action', '攻击', 'completed')"
    )
    test_db.execute(
        "INSERT INTO encounter_pending_reactions "
        "(reaction_id, room_id, encounter_id, source_action_id, character_id, attacker_id, round_number, attack_index, attack_name, damage_expression) "
        "VALUES ('reaction-block-pending', 'reaction-block-room', 'reaction-block-encounter', 'reaction-block-action', "
        "'reaction-block-character', 'npc:bear', 2, 1, '爪击', '1d3')"
    )
    test_db.commit()

    may_advance = TurnManager(test_db).advance_combat_round_if_ready('reaction-block-turn')
    encounter = test_db.execute(
        "SELECT current_round FROM encounters WHERE encounter_id = 'reaction-block-encounter'"
    ).fetchone()

    assert may_advance is False
    assert encounter['current_round'] == 2


def test_canceled_combat_declaration_no_longer_counts_as_submitted(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES ('withdraw-combat-room', 'owner', 'active')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, status) "
        "VALUES ('withdraw-combat-character', 'withdraw-combat-room', 'Player', 'token', 'ready')"
    )
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
        "VALUES ('withdraw-combat-encounter', 'withdraw-combat-room', 'combat', 'active', 1)"
    )
    test_db.commit()
    turns = TurnManager(test_db)
    turn = turns.ensure_current_turn('withdraw-combat-room')
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, turn_id, intent_type, declared_intent, status) "
        "VALUES ('withdrawn-combat-action', 'withdraw-combat-room', 'withdraw-combat-character', %s, "
        "'combat_action', '我射击人影', 'canceled')",
        (turn['turn_id'],),
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('replacement-combat-action', 'withdraw-combat-room', 'withdraw-combat-character', "
        "'combat_action', '我撤向掩体', 'queued')"
    )
    test_db.commit()

    snapshot = turns.get_turn_snapshot('withdraw-combat-room')
    replacement = turns.submit_action(
        'withdraw-combat-room',
        'withdraw-combat-character',
        'replacement-combat-action',
    )

    assert snapshot['players'][0]['submitted'] is False
    assert snapshot['actions'] == []
    assert replacement['status'] == 'queued'
    effective = test_db.execute(
        "SELECT action_id FROM actions WHERE turn_id = %s AND status NOT IN ('rejected', 'canceled', 'timeout')",
        (turn['turn_id'],),
    ).fetchall()
    assert effective == [{'action_id': 'replacement-combat-action'}]


def test_skip_character_only_accepts_documented_absent_policies(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES ('skip-policy-room', 'owner', 'active')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, status) "
        "VALUES ('skip-policy-character', 'skip-policy-room', '玩家', 'token', 'ready')"
    )
    test_db.commit()
    turn = TurnManager(test_db).ensure_current_turn('skip-policy-room')

    invalid = TurnManager(test_db).skip_character(
        'skip-policy-room', turn['turn_id'], 'skip-policy-character', 'attack_the_nearest_enemy'
    )
    valid = TurnManager(test_db).skip_character(
        'skip-policy-room', turn['turn_id'], 'skip-policy-character', 'maintain_existing'
    )

    assert invalid == {'status': 'invalid_policy'}
    assert valid['status'] == 'skipped'
    action = test_db.execute(
        "SELECT declared_intent FROM actions WHERE action_id = %s", (valid['action_id'],)
    ).fetchone()
    assert action['declared_intent'] == '本回合跳过: maintain_existing'


def test_expired_combat_turn_uses_player_absence_preset_once_and_never_invents_tactics(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES ('timeout-policy-room', 'owner', 'active')"
    )
    for character_id in ('timeout-ready', 'timeout-absent'):
        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, status) "
            "VALUES (%s, 'timeout-policy-room', %s, %s, 'ready')",
            (character_id, character_id, f'{character_id}-token'),
        )
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
        "VALUES ('timeout-policy-encounter', 'timeout-policy-room', 'combat', 'active', 1)"
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('timeout-ready-action', 'timeout-policy-room', 'timeout-ready', 'combat_action', 'I hold the door.', 'queued')"
    )
    test_db.execute(
        "INSERT INTO room_player_settings (room_id, character_id, absent_policy) "
        "VALUES ('timeout-policy-room', 'timeout-absent', 'maintain_existing')"
    )
    test_db.commit()

    turns = TurnManager(test_db)
    turn = turns.ensure_current_turn('timeout-policy-room')
    turns.submit_action('timeout-policy-room', 'timeout-ready', 'timeout-ready-action')
    test_db.execute(
        "UPDATE room_turns SET started_at = NOW() - INTERVAL '2 minutes' WHERE turn_id = %s",
        (turn['turn_id'],),
    )
    test_db.commit()

    first = turns.apply_expired_absence_policies('timeout-policy-room')
    second = turns.apply_expired_absence_policies('timeout-policy-room')
    actions = test_db.execute(
        "SELECT character_id, declared_intent, intent_type FROM actions "
        "WHERE turn_id = %s ORDER BY character_id",
        (turn['turn_id'],),
    ).fetchall()

    assert first == [{
        'room_id': 'timeout-policy-room',
        'turn_id': turn['turn_id'],
        'character_ids': ['timeout-absent'],
    }]
    assert second == []
    assert [dict(action) for action in actions] == [
        {
            'character_id': 'timeout-absent',
            'declared_intent': '本回合跳过: maintain_existing',
            'intent_type': 'system_skip',
        },
        {
            'character_id': 'timeout-ready',
            'declared_intent': 'I hold the door.',
            'intent_type': 'combat_action',
        },
    ]
    assert turns.all_submitted('timeout-policy-room') is True


def test_player_combat_round_projection_exposes_only_own_declaration_progress(client, test_db):
    setup_auth_test_data(test_db)
    room_id = create_room(client)['room_id']
    first = client.post(f'/api/player/rooms/{room_id}/join').json()
    second = client.post(f'/api/player/rooms/{room_id}/join').json()
    test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room_id,))
    test_db.execute(
        "UPDATE characters SET status = 'ready' WHERE room_id = %s",
        (room_id,),
    )
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
        "VALUES ('player-combat-encounter', %s, 'combat', 'active', 1)",
        (room_id,),
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('player-combat-action', %s, %s, 'combat_action', '我瞄准黑暗中的人影', 'queued')",
        (room_id, first['character_id']),
    )
    TurnManager(test_db).submit_action(room_id, first['character_id'], 'player-combat-action')

    response = client.get('/api/player/combat-round', headers={'X-Room-Token': first['player_token']})

    assert response.status_code == 200
    assert response.json() == {
        'hasCombat': True,
        'encounterId': 'player-combat-encounter',
        'roundNumber': 1,
        'phase': 'declaration',
        'turnId': response.json()['turnId'],
        'declaration': {
            'submitted': True,
            'locked': False,
            'submittedCount': 1,
            'totalPlayers': 2,
        },
    }


def test_player_can_declare_idle_for_current_combat_round(client, test_db):
    setup_auth_test_data(test_db)
    room_id = create_room(client)['room_id']
    player = client.post(f'/api/player/rooms/{room_id}/join').json()
    client.post(f'/api/player/rooms/{room_id}/join')
    test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room_id,))
    test_db.execute(
        "UPDATE characters SET status = 'ready' WHERE character_id = %s",
        (player['character_id'],),
    )
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
        "VALUES ('player-idle-encounter', %s, 'combat', 'active', 1)",
        (room_id,),
    )
    test_db.commit()
    headers = {'X-Room-Token': player['player_token']}

    round_before = client.get('/api/player/combat-round', headers=headers).json()
    response = client.post('/api/player/combat-round/idle', headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        'status': 'declared_idle',
        'turnId': round_before['turnId'],
        'actionId': response.json()['actionId'],
    }
    action = test_db.execute(
        "SELECT character_id, turn_id, intent_type, declared_intent FROM actions WHERE action_id = %s",
        (response.json()['actionId'],),
    ).fetchone()
    assert action == {
        'character_id': player['character_id'],
        'turn_id': round_before['turnId'],
        'intent_type': 'system_skip',
        'declared_intent': '本回合跳过: idle',
    }

    duplicate = client.post('/api/player/combat-round/idle', headers=headers)
    assert duplicate.status_code == 200
    assert duplicate.json() == response.json()

    test_db.execute(
        "UPDATE room_turns SET status = 'resolving' WHERE turn_id = %s",
        (round_before['turnId'],),
    )
    test_db.commit()
    locked = client.post('/api/player/combat-round/idle', headers=headers)
    assert locked.status_code == 409


def test_player_combat_round_projection_whitelists_public_clusters_after_lock(client, test_db):
    setup_auth_test_data(test_db)
    room_id = create_room(client)['room_id']
    player = client.post(f'/api/player/rooms/{room_id}/join').json()
    test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room_id,))
    test_db.execute(
        "UPDATE characters SET status = 'ready' WHERE character_id = %s",
        (player['character_id'],),
    )
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
        "VALUES ('public-cluster-encounter', %s, 'combat', 'active', 4)",
        (room_id,),
    )
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode, encounter_id, combat_plan) "
        "VALUES ('public-cluster-turn', %s, 1, 'resolving', 'combat', 'public-cluster-encounter', %s)",
        (
            room_id,
            json.dumps({
                'presentation_clusters': [
                    {
                        'public_title': 'Doorway exchange',
                        'action_ids': ['internal-action-id'],
                        'completed_public_facts': ['The door is still blocked.'],
                        'hidden_enemy_hp': 1,
                    },
                    {
                        'public_title': 'Secret handoff',
                        'action_ids': ['private-action-id'],
                        'visibility': 'private',
                    },
                ],
                'observable_preparations': [
                    'Ada raises a weapon and stays alert.',
                    {'text': 'This internal object must not reach players.'},
                ],
            }),
        ),
    )
    test_db.commit()

    response = client.get('/api/player/combat-round', headers={'X-Room-Token': player['player_token']})
    payload = response.json()

    assert response.status_code == 200
    assert payload['publicClusters'] == [{
        'publicTitle': 'Doorway exchange',
        'completedPublicFacts': ['The door is still blocked.'],
    }]
    assert payload['observablePreparations'] == ['Ada raises a weapon and stays alert.']
    assert 'internal-action-id' not in json.dumps(payload)
    assert 'private-action-id' not in json.dumps(payload)
    assert 'hidden_enemy_hp' not in json.dumps(payload)
    assert 'This internal object must not reach players.' not in json.dumps(payload)
