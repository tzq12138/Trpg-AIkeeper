import asyncio
import json

import pytest

from src.server.events.event_log import EventLog
from src.server.export import export_json, export_markdown
from tests.server.conftest import create_scenario


def _setup_reveal_room(test_db):
    create_scenario(test_db, "reveal")
    test_db.execute(
        "INSERT INTO rooms "
        "(room_id, scenario_id, scenario_version_id, owner_token, state_version) "
        "VALUES ('reveal-room', 'reveal', 'sv-reveal', 'owner-secret', 3)"
    )
    for character_id in ("reveal-player-a", "reveal-player-b"):
        test_db.execute(
            "INSERT INTO characters "
            "(character_id, room_id, player_name, player_token, status) "
            "VALUES (%s, 'reveal-room', %s, %s, 'active')",
            (character_id, character_id, f"token-{character_id}"),
        )
    test_db.execute(
        "INSERT INTO room_scene_state "
        "(room_id, current_scene, visited_scenes, public_facts, version) "
        "VALUES ('reveal-room', 'study', '[\"study\"]', '[\"书房门已经打开\"]', 1)"
    )
    test_db.commit()


def _insert_fact(
    test_db,
    content_item_id: str,
    logical_key: str,
    title: str,
    *,
    visibility: str = "host_only",
    payload: dict | None = None,
):
    test_db.execute(
        "INSERT INTO content_items "
        "(content_item_id, scenario_version_id, item_type, logical_key, title, "
        "visibility, payload, citation, checksum) "
        "VALUES (%s, 'sv-reveal', 'fact', %s, %s, %s, %s, %s, %s)",
        (
            content_item_id,
            logical_key,
            title,
            visibility,
            json.dumps(payload or {"fact_text": title}, ensure_ascii=False),
            json.dumps({"page_number": 7, "source_part_id": "part-secret"}),
            f"sha-{content_item_id}",
        ),
    )
    test_db.commit()


def test_unmet_hidden_fact_proposal_is_rejected_without_leaking_secret(test_db):
    from src.server.engine.reveal_ledger import RevealLedger, RevealPolicyError

    _setup_reveal_room(test_db)
    secret = "保险库里的站长才是幕后凶手"
    _insert_fact(
        test_db,
        "fact-remote-secret",
        "sealed-vault",
        secret,
        payload={
            "fact_text": secret,
            "reveal_conditions": {"scene_ids": ["sealed-vault"]},
        },
    )

    with pytest.raises(RevealPolicyError) as raised:
        RevealLedger(test_db).validate_proposals(
            room_id="reveal-room",
            actor_character_id="reveal-player-a",
            proposals=[{
                "content_item_id": "fact-remote-secret",
                "audience": "party",
                "fact_text": "AI 不得提交这段伪造正文",
            }],
        )

    assert raised.value.code == "reveal_condition_unmet"
    assert secret not in str(raised.value)
    assert test_db.execute("SELECT COUNT(*) AS count FROM fact_reveals").fetchone()["count"] == 0
    rendered_events = json.dumps(
        [
            event.model_dump(mode="json")
            for event in EventLog(test_db).get_events_for_player(
                "reveal-room", "reveal-player-a"
            )
        ],
        ensure_ascii=False,
    )
    assert secret not in rendered_events
    assert "AI 不得提交这段伪造正文" not in rendered_events


@pytest.mark.parametrize(
    "conditions",
    [
        {"required_clue_ids": "clue-secret"},
        {"unknown_condition": True},
        {"scene_ids": []},
    ],
)
def test_malformed_or_unknown_hidden_conditions_fail_closed_without_leak(
    test_db,
    conditions,
):
    from src.server.engine.reveal_ledger import RevealLedger, RevealPolicyError

    _setup_reveal_room(test_db)
    secret = "格式错误的条件绝不能放行这段真相"
    _insert_fact(
        test_db,
        "fact-malformed-condition",
        "sealed-vault",
        secret,
        payload={"fact_text": secret, "reveal_conditions": conditions},
    )

    with pytest.raises(RevealPolicyError) as raised:
        RevealLedger(test_db).validate_proposals(
            room_id="reveal-room",
            actor_character_id="reveal-player-a",
            proposals=[{
                "content_item_id": "fact-malformed-condition",
                "audience": "party",
            }],
        )

    assert raised.value.code == "reveal_conditions_invalid"
    assert secret not in str(raised.value)
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM fact_reveals"
    ).fetchone()["count"] == 0


def test_reveal_event_and_state_version_share_transaction_and_rollback_together(test_db):
    from src.server.engine.reveal_ledger import RevealLedger

    _setup_reveal_room(test_db)
    _insert_fact(test_db, "fact-study-clock", "study", "书房时钟停在十一点")
    ledger = RevealLedger(test_db)
    validated = ledger.validate_proposals(
        room_id="reveal-room",
        actor_character_id="reveal-player-a",
        proposals=[{"content_item_id": "fact-study-clock", "audience": "party"}],
    )

    with pytest.raises(RuntimeError, match="force rollback"):
        with test_db.transaction() as transaction:
            transaction.execute(
                "UPDATE rooms SET state_version = 4 WHERE room_id = 'reveal-room'"
            )
            ledger.commit_validated(
                room_id="reveal-room",
                source_action_id="action-rolled-back",
                actor_character_id="reveal-player-a",
                proposals=validated,
                state_version=4,
                executor=transaction,
            )
            EventLog(transaction).log_event(
                "reveal-room",
                "s2c_narration_completed",
                "party",
                {"actionId": "action-rolled-back", "narrativeText": "不应可见"},
                commit=False,
                action_id="action-rolled-back",
                state_version=4,
            )
            raise RuntimeError("force rollback")

    assert test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = 'reveal-room'"
    ).fetchone()["state_version"] == 3
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM fact_reveals WHERE source_action_id = 'action-rolled-back'"
    ).fetchone()["count"] == 0
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM events WHERE action_id = 'action-rolled-back'"
    ).fetchone()["count"] == 0

    with test_db.transaction() as transaction:
        transaction.execute(
            "UPDATE rooms SET state_version = 4 WHERE room_id = 'reveal-room'"
        )
        records = ledger.commit_validated(
            room_id="reveal-room",
            source_action_id="action-committed",
            actor_character_id="reveal-player-a",
            proposals=validated,
            state_version=4,
            executor=transaction,
        )
        narration_sequence = EventLog(transaction).log_event(
            "reveal-room",
            "s2c_narration_completed",
            "party",
            {"actionId": "action-committed", "narrativeText": "时钟停在十一点。"},
            commit=False,
            action_id="action-committed",
            state_version=4,
        )

    stored = test_db.execute(
        "SELECT state_version, event_sequence FROM fact_reveals "
        "WHERE reveal_id = %s",
        (records[0]["reveal_id"],),
    ).fetchone()
    assert stored["state_version"] == 4
    assert stored["event_sequence"] < narration_sequence
    event = test_db.execute(
        "SELECT state_version, action_id FROM events WHERE sequence = %s",
        (stored["event_sequence"],),
    ).fetchone()
    assert dict(event) == {"state_version": 4, "action_id": "action-committed"}


def test_public_player_and_director_fact_projections_are_audience_scoped(test_db):
    from src.server.engine.reveal_ledger import RevealLedger

    _setup_reveal_room(test_db)
    for item_id, title in (
        ("fact-party", "全队知道钟声响过三次"),
        ("fact-private-a", "甲独自看见袖口血迹"),
        ("fact-private-b", "乙独自听见地下室低语"),
    ):
        _insert_fact(
            test_db,
            item_id,
            item_id,
            title,
            payload={
                "fact_text": title,
                "reveal_conditions": {"scene_ids": ["study"]},
            },
        )
    ledger = RevealLedger(test_db)
    ledger.commit_proposals(
        room_id="reveal-room",
        source_action_id="action-party",
        actor_character_id="reveal-player-a",
        proposals=[{"content_item_id": "fact-party", "audience": "party"}],
        state_version=3,
    )
    ledger.commit_proposals(
        room_id="reveal-room",
        source_action_id="action-private-a",
        actor_character_id="reveal-player-a",
        proposals=[{"content_item_id": "fact-private-a", "audience": "player"}],
        state_version=3,
    )
    ledger.commit_proposals(
        room_id="reveal-room",
        source_action_id="action-private-b",
        actor_character_id="reveal-player-b",
        proposals=[{"content_item_id": "fact-private-b", "audience": "player"}],
        state_version=3,
    )

    public = ledger.project_facts("reveal-room", audience="public")
    player_a = ledger.project_facts(
        "reveal-room", audience="player", character_id="reveal-player-a"
    )
    player_b = ledger.project_facts(
        "reveal-room", audience="player", character_id="reveal-player-b"
    )
    director_a = ledger.project_facts(
        "reveal-room", audience="director", character_id="reveal-player-a"
    )

    assert {fact["fact_id"] for fact in public} == {"fact-party"}
    assert {fact["fact_id"] for fact in player_a} == {"fact-party", "fact-private-a"}
    assert {fact["fact_id"] for fact in player_b} == {"fact-party", "fact-private-b"}
    assert {fact["fact_id"] for fact in director_a} == {
        "fact-party",
        "fact-private-a",
    }


def test_private_reveal_stays_out_of_public_archive_team_evidence_and_other_reconnect(test_db):
    from src.server.engine.reveal_ledger import RevealLedger

    _setup_reveal_room(test_db)
    secret = "只有甲知道窗帘后藏着备用钥匙"
    _insert_fact(test_db, "fact-private-key", "study", secret)
    RevealLedger(test_db).commit_proposals(
        room_id="reveal-room",
        source_action_id="action-private-key",
        actor_character_id="reveal-player-a",
        proposals=[{"content_item_id": "fact-private-key", "audience": "player"}],
        state_version=3,
    )

    public_export = export_markdown(test_db, "reveal-room", scope="public")["content"]
    team_evidence = test_db.execute(
        "SELECT title, body FROM evidence_cards "
        "WHERE room_id = 'reveal-room' AND visibility = 'party'"
    ).fetchall()
    other_events = EventLog(test_db).get_events_for_player(
        "reveal-room", "reveal-player-b"
    )
    own_events = EventLog(test_db).get_events_for_player(
        "reveal-room", "reveal-player-a"
    )

    assert secret not in public_export
    assert secret not in json.dumps([dict(row) for row in team_evidence], ensure_ascii=False)
    assert secret not in json.dumps(
        [event.model_dump(mode="json") for event in other_events], ensure_ascii=False
    )
    assert secret in json.dumps(
        [event.model_dump(mode="json") for event in own_events], ensure_ascii=False
    )


def test_party_narrator_context_uses_ledger_not_static_or_private_facts(test_db):
    from src.server.ai.narrator import build_narrator_context
    from src.server.engine.reveal_ledger import RevealLedger
    from src.server.models import ResolutionResult

    _setup_reveal_room(test_db)
    for item_id, title, visibility in (
        ("narrator-party-fact", "全队已经看见信封上的蜡印", "host_only"),
        ("narrator-private-fact", "只有甲闻到信纸上的药味", "host_only"),
        ("narrator-static-public", "仅标成 public 但尚未写入账本", "public"),
    ):
        _insert_fact(
            test_db,
            item_id,
            item_id,
            title,
            visibility=visibility,
            payload={
                "fact_text": title,
                "reveal_conditions": {"scene_ids": ["study"]},
            },
        )
    ledger = RevealLedger(test_db)
    ledger.commit_proposals(
        room_id="reveal-room",
        source_action_id="narrator-party-action",
        actor_character_id="reveal-player-a",
        proposals=[{"content_item_id": "narrator-party-fact", "audience": "party"}],
        state_version=3,
    )
    ledger.commit_proposals(
        room_id="reveal-room",
        source_action_id="narrator-private-action",
        actor_character_id="reveal-player-a",
        proposals=[{"content_item_id": "narrator-private-fact", "audience": "player"}],
        state_version=3,
    )
    runtime_secret = "运行包里尚未由揭示账本授权的幕后身份"
    test_db.execute(
        "INSERT INTO runtime_package_versions "
        "(runtime_package_version_id, scenario_version_id, package_version_number, "
        "gate_status, input_checksum, runtime_package, created_by) "
        "VALUES ('reveal-narrator-runtime', 'sv-reveal', 1, 'ready', 'sha', %s, 'test')",
        (json.dumps({
            "allowed_facts": [{
                "fact_ref": "fact:runtime-unrevealed",
                "text": runtime_secret,
            }],
        }, ensure_ascii=False),),
    )
    test_db.execute(
        "UPDATE rooms SET runtime_package_version_id = 'reveal-narrator-runtime' "
        "WHERE room_id = 'reveal-room'"
    )
    test_db.commit()
    action = {
        "action_id": "narrator-context-action",
        "room_id": "reveal-room",
        "character_id": "reveal-player-a",
        "declared_intent": "我查看信封。",
        "params": {"director_plan": {"visibility": "party"}},
    }
    character = dict(test_db.execute(
        "SELECT * FROM characters WHERE character_id = 'reveal-player-a'"
    ).fetchone())
    room = dict(test_db.execute(
        "SELECT * FROM rooms WHERE room_id = 'reveal-room'"
    ).fetchone())

    context = build_narrator_context(
        test_db,
        action,
        character,
        room,
        ResolutionResult(
            actionId="narrator-context-action",
            roomId="reveal-room",
            characterId="reveal-player-a",
            isSuccess=True,
        ),
    )
    rendered = json.dumps(context["allowed_facts"], ensure_ascii=False)

    assert "全队已经看见信封上的蜡印" in rendered
    assert "只有甲闻到信纸上的药味" not in rendered
    assert "仅标成 public 但尚未写入账本" not in rendered
    assert runtime_secret not in rendered


def test_correction_and_safety_flag_append_without_erasing_seen_history(test_db):
    from src.server.engine.reveal_ledger import RevealLedger
    from src.server.engine.spoiler_guard import SpoilerGuard

    _setup_reveal_room(test_db)
    _insert_fact(test_db, "fact-clock-owner", "study", "时钟属于站长")
    ledger = RevealLedger(test_db)
    original = ledger.commit_proposals(
        room_id="reveal-room",
        source_action_id="action-wrong-reveal",
        actor_character_id="reveal-player-a",
        proposals=[{"content_item_id": "fact-clock-owner", "audience": "party"}],
        state_version=3,
    )[0]

    correction = ledger.append_correction(
        room_id="reveal-room",
        reveal_id=original["reveal_id"],
        corrected_text="更正：时钟属于管理员，不属于站长",
        citation={"page_number": 8},
        source_action_id="action-correction",
        state_version=3,
    )
    effective_after_correction = ledger.project_facts(
        "reveal-room", audience="public"
    )
    assert [fact["record_kind"] for fact in effective_after_correction] == [
        "correction"
    ]
    assert effective_after_correction[0]["fact_text"] == (
        "更正：时钟属于管理员，不属于站长"
    )
    safety = ledger.flag_safety_event(
        room_id="reveal-room",
        reveal_id=original["reveal_id"],
        reason_code="erroneous_reveal",
        source_action_id="action-safety",
        state_version=3,
    )
    effective_after_safety = ledger.project_facts(
        "reveal-room", audience="public"
    )
    assert [fact["record_kind"] for fact in effective_after_safety] == [
        "safety_event"
    ]
    assert effective_after_safety[0]["fact_text"] == ""
    unlock = SpoilerGuard(test_db).compute_unlock_state("reveal-room")
    assert "fact-clock-owner" not in unlock.revealed_fact_ids
    assert "fact-clock-owner" not in unlock.revealed_content_item_ids

    rows = ledger.project_history("reveal-room", audience="public")
    assert {row["record_kind"] for row in rows} == {
        "reveal",
        "correction",
        "safety_event",
    }
    assert any(row["fact_text"] == "时钟属于站长" for row in rows)
    assert correction["corrects_reveal_id"] == original["reveal_id"]
    assert safety["status"] == "safety_flagged"
    event_types = {
        row["event_type"]
        for row in test_db.execute(
            "SELECT event_type FROM events WHERE room_id = 'reveal-room'"
        ).fetchall()
    }
    assert {
        "s2c_fact_revealed",
        "s2c_fact_corrected",
        "s2c_fact_safety_event",
    } <= event_types


def test_correction_idempotency_key_cannot_change_target_or_content(test_db):
    from src.server.engine.reveal_ledger import RevealLedger, RevealPolicyError

    _setup_reveal_room(test_db)
    _insert_fact(test_db, "fact-idempotent", "study", "档案由站长保管")
    ledger = RevealLedger(test_db)
    original = ledger.commit_proposals(
        room_id="reveal-room",
        source_action_id="action-idempotent-reveal",
        actor_character_id="reveal-player-a",
        proposals=[{"content_item_id": "fact-idempotent", "audience": "party"}],
        state_version=3,
    )[0]
    ledger.append_correction(
        room_id="reveal-room",
        reveal_id=original["reveal_id"],
        corrected_text="档案实际由副站长保管",
        citation={"page_number": 8},
        source_action_id="action-idempotent-correction",
        state_version=3,
    )

    with pytest.raises(RevealPolicyError) as conflict:
        ledger.append_correction(
            room_id="reveal-room",
            reveal_id=original["reveal_id"],
            corrected_text="同一动作不能改写成另一段正文",
            citation={"page_number": 9},
            source_action_id="action-idempotent-correction",
            state_version=3,
        )

    assert conflict.value.code == "reveal_idempotency_conflict"


def test_fact_reveal_event_sequence_is_unique(test_db):
    from src.server.engine.reveal_ledger import RevealLedger

    _setup_reveal_room(test_db)
    _insert_fact(test_db, "fact-unique-sequence", "study", "门锁已经损坏")
    record = RevealLedger(test_db).commit_proposals(
        room_id="reveal-room",
        source_action_id="action-unique-sequence",
        actor_character_id="reveal-player-a",
        proposals=[{"content_item_id": "fact-unique-sequence", "audience": "party"}],
        state_version=3,
    )[0]

    with pytest.raises(Exception):
        with test_db.transaction() as transaction:
            transaction.execute(
                "INSERT INTO fact_reveals "
                "(reveal_id, room_id, fact_id, audience, source_action_id, "
                "state_version, event_sequence) "
                "VALUES ('duplicate-sequence', 'reveal-room', 'other-fact', "
                "'party', 'other-action', 3, %s)",
                (record["event_sequence"],),
            )
def test_fact_reference_is_canonicalized_to_unique_content_item_id(test_db):
    from src.server.engine.reveal_ledger import RevealLedger

    _setup_reveal_room(test_db)
    _insert_fact(test_db, "fact-canonical-clock", "study", "时钟停在十一点")

    record = RevealLedger(test_db).commit_proposals(
        room_id="reveal-room",
        source_action_id="action-canonical-reference",
        actor_character_id="reveal-player-a",
        proposals=[{"fact_id": "study", "audience": "party"}],
        state_version=3,
    )[0]

    assert record["fact_id"] == "fact-canonical-clock"
    assert record["content_item_id"] == "fact-canonical-clock"


def test_fact_event_without_matching_ledger_record_is_not_projected(test_db):
    _setup_reveal_room(test_db)
    forged_secret = "伪造事件试图直接公开幕后真相"
    EventLog(test_db).log_event(
        "reveal-room",
        "s2c_fact_revealed",
        "party",
        {
            "revealId": "forged-reveal",
            "factId": "forged-fact",
            "factText": forged_secret,
        },
        action_id="forged-action",
        state_version=3,
    )

    player_events = EventLog(test_db).get_events_for_player(
        "reveal-room", "reveal-player-a"
    )
    public_events = EventLog(test_db).get_public_events("reveal-room")

    assert forged_secret not in json.dumps(
        [event.model_dump(mode="json") for event in player_events],
        ensure_ascii=False,
    )
    assert forged_secret not in json.dumps(
        [event.model_dump(mode="json") for event in public_events],
        ensure_ascii=False,
    )


def test_fact_event_payload_must_match_ledger_record_before_projection(test_db):
    from src.server.engine.reveal_ledger import RevealLedger

    _setup_reveal_room(test_db)
    _insert_fact(test_db, "fact-ledger-bound", "study", "书桌抽屉已经打开")
    record = RevealLedger(test_db).commit_proposals(
        room_id="reveal-room",
        source_action_id="action-ledger-bound",
        actor_character_id="reveal-player-a",
        proposals=[{"content_item_id": "fact-ledger-bound", "audience": "party"}],
        state_version=3,
    )[0]
    forged_secret = "篡改合法事件后塞入的幕后真相"
    test_db.execute(
        "UPDATE events SET payload = %s WHERE sequence = %s",
        (
            json.dumps({
                "revealId": record["reveal_id"],
                "factId": record["fact_id"],
                "contentItemId": record["content_item_id"],
                "factText": forged_secret,
                "citation": {"label": "已校验依据", "verified": True},
                "status": "revealed",
            }, ensure_ascii=False),
            record["event_sequence"],
        ),
    )
    test_db.commit()

    rendered = json.dumps(
        [
            event.model_dump(mode="json")
            for event in EventLog(test_db).get_public_events("reveal-room")
        ],
        ensure_ascii=False,
    )

    assert forged_secret not in rendered
    assert "fact-ledger-bound" not in rendered


def test_fact_event_with_extra_sensitive_field_is_rejected_everywhere(test_db):
    from src.server.engine.projection import ProjectionDispatcher
    from src.server.engine.reveal_ledger import RevealLedger

    _setup_reveal_room(test_db)
    _insert_fact(test_db, "fact-no-extra-fields", "study", "窗闩已经从里面扣上")
    record = RevealLedger(test_db).commit_proposals(
        room_id="reveal-room",
        source_action_id="action-no-extra-fields",
        actor_character_id="reveal-player-a",
        proposals=[{"content_item_id": "fact-no-extra-fields", "audience": "party"}],
        state_version=3,
    )[0]
    event = test_db.execute(
        "SELECT payload FROM events WHERE sequence = %s",
        (record["event_sequence"],),
    ).fetchone()
    payload = event["payload"] if isinstance(event["payload"], dict) else json.loads(event["payload"])
    extra_secret = "不属于揭示账本的原始安全边界文本"
    test_db.execute(
        "UPDATE events SET payload = %s WHERE sequence = %s",
        (
            json.dumps({**payload, "rawSafetyText": extra_secret}, ensure_ascii=False),
            record["event_sequence"],
        ),
    )
    test_db.commit()

    class RecordingWsManager:
        def __init__(self):
            self.events = []

        async def send_event(self, *args):
            self.events.append(args)

        async def broadcast_to_room(self, *args):
            self.events.append(args)

    manager = RecordingWsManager()
    published = asyncio.run(
        ProjectionDispatcher(test_db, ws_manager=manager).publish_committed_fact_event(
            "reveal-room",
            record["event_sequence"],
        )
    )

    assert EventLog(test_db).get_public_events("reveal-room") == []
    assert published is False
    assert manager.events == []


def test_fact_event_with_nested_extra_field_is_not_projected(test_db):
    from src.server.engine.reveal_ledger import RevealLedger

    _setup_reveal_room(test_db)
    _insert_fact(test_db, "fact-no-nested-extra", "study", "地板上只有一道新划痕")
    record = RevealLedger(test_db).commit_proposals(
        room_id="reveal-room",
        source_action_id="action-no-nested-extra",
        actor_character_id="reveal-player-a",
        proposals=[{"content_item_id": "fact-no-nested-extra", "audience": "party"}],
        state_version=3,
    )[0]
    event = test_db.execute(
        "SELECT payload FROM events WHERE sequence = %s",
        (record["event_sequence"],),
    ).fetchone()
    payload = event["payload"] if isinstance(event["payload"], dict) else json.loads(event["payload"])
    payload["citation"] = {
        **dict(payload.get("citation") or {}),
        "unrevealedSecret": "嵌套字段也不能被清洗后放行",
    }
    test_db.execute(
        "UPDATE events SET payload = %s WHERE sequence = %s",
        (json.dumps(payload, ensure_ascii=False), record["event_sequence"]),
    )
    test_db.commit()

    assert EventLog(test_db).get_public_events("reveal-room") == []


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("room_id", "other-room"),
        ("action_id", None),
        ("state_version", None),
    ],
)
def test_fact_event_binding_requires_exact_room_action_and_state(
    test_db,
    column,
    value,
):
    from src.server.engine.reveal_ledger import RevealLedger

    _setup_reveal_room(test_db)
    _insert_fact(test_db, "fact-event-binding", "study", "抽屉封条已经断开")
    record = RevealLedger(test_db).commit_proposals(
        room_id="reveal-room",
        source_action_id="action-event-binding",
        actor_character_id="reveal-player-a",
        proposals=[{"content_item_id": "fact-event-binding", "audience": "party"}],
        state_version=3,
    )[0]
    test_db.execute(
        f"UPDATE events SET {column} = %s WHERE sequence = %s",
        (value, record["event_sequence"]),
    )
    test_db.commit()

    projected_room = "other-room" if column == "room_id" else "reveal-room"
    assert EventLog(test_db).get_public_events(projected_room) == []


def test_public_json_export_excludes_host_and_unledgered_fact_events(test_db):
    _setup_reveal_room(test_db)
    host_secret = "仅 Engine 可见的未揭示结局"
    forged_secret = "没有账本记录却伪装成公开事实"
    EventLog(test_db).log_event(
        "reveal-room",
        "s2c_action_exception_requested",
        "host",
        {"text": host_secret},
        action_id="host-only-action",
        state_version=3,
    )
    EventLog(test_db).log_event(
        "reveal-room",
        "s2c_fact_revealed",
        "party",
        {
            "revealId": "forged-export-reveal",
            "factId": "forged-export-fact",
            "factText": forged_secret,
        },
        action_id="forged-export-action",
        state_version=3,
    )

    exported = export_json(test_db, "reveal-room", scope="public")
    rendered = json.dumps(
        exported,
        ensure_ascii=False,
        default=str,
    )

    assert host_secret not in rendered
    assert forged_secret not in rendered
    assert "owner_token" not in exported["data"]["room"]
    assert "owner_account_id" not in exported["data"]["room"]
    assert all(
        "player_token" not in character and "xlsx_data" not in character
        for character in exported["data"]["characters"]
    )


@pytest.mark.parametrize(
    "event_type",
    ["s2c_fact_revealed", "s2c_fact_unregistered"],
)
def test_generic_projection_dispatcher_cannot_broadcast_fact_events(
    test_db,
    event_type,
):
    from src.server.engine.projection import ProjectionDispatcher

    _setup_reveal_room(test_db)

    class RecordingWsManager:
        def __init__(self):
            self.events = []

        async def send_event(self, *args):
            self.events.append(args)

        async def broadcast_to_room(self, *args):
            self.events.append(args)

    manager = RecordingWsManager()
    dispatcher = ProjectionDispatcher(test_db, ws_manager=manager)

    with pytest.raises(ValueError, match="fact_event_requires_reveal_ledger"):
        asyncio.run(dispatcher.emit(
            "reveal-room",
            event_type,
            "party",
            {"factText": "绕过账本的实时秘密"},
        ))

    assert manager.events == []
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM events WHERE event_type = %s",
        (event_type,),
    ).fetchone()["count"] == 0


def test_unregistered_fact_event_is_never_publicly_projected(test_db):
    _setup_reveal_room(test_db)
    EventLog(test_db).log_event(
        "reveal-room",
        "s2c_fact_unregistered",
        "party",
        {"factText": "未注册事实事件不能成为公开旁路"},
        action_id="action-unregistered-fact",
        state_version=3,
    )

    assert EventLog(test_db).get_public_events("reveal-room") == []


def test_committed_fact_event_can_be_published_from_ledger_only(test_db):
    from src.server.engine.projection import ProjectionDispatcher
    from src.server.engine.reveal_ledger import RevealLedger

    _setup_reveal_room(test_db)
    _insert_fact(test_db, "fact-live-publish", "study", "墙上时钟停在十一点")
    record = RevealLedger(test_db).commit_proposals(
        room_id="reveal-room",
        source_action_id="action-live-publish",
        actor_character_id="reveal-player-a",
        proposals=[{"content_item_id": "fact-live-publish", "audience": "party"}],
        state_version=3,
    )[0]

    class RecordingWsManager:
        def __init__(self):
            self.events = []

        async def send_event(self, *args):
            self.events.append(args)

        async def broadcast_to_room(self, *args):
            self.events.append(args)

    manager = RecordingWsManager()
    published = asyncio.run(
        ProjectionDispatcher(test_db, ws_manager=manager).publish_committed_fact_event(
            "reveal-room", record["event_sequence"]
        )
    )

    assert published is True
    assert len(manager.events) == 1
    event = manager.events[0][1]
    assert event.type == "s2c_fact_revealed"
    assert event.payload["factText"] == "墙上时钟停在十一点"
