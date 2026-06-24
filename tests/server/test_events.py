from src.server.models import EngineEvent, EngineEventType


def test_engine_event_envelope_fields():
    event = EngineEvent(
        room_id="room-1",
        type="s2c_host_snapshot",
        audience="host",
        payload={"data": "test"},
    )
    assert event.event_id is not None
    assert event.room_id == "room-1"
    assert event.type == "s2c_host_snapshot"
    assert event.audience == "host"
    assert event.issued_at is not None


def test_audience_allows_only_valid_values():
    for audience in ["host", "player", "party", "system"]:
        event = EngineEvent(
            room_id="r", type="s2c_host_snapshot", audience=audience, payload={}
        )
        assert event.audience == audience


def test_engine_event_type_enum():
    valid_types = [
        "s2c_reveal_transaction", "s2c_resume_transaction", "s2c_cancel_transaction",
        "s2c_chat_stream", "s2c_atmosphere", "s2c_engine_state", "s2c_scene_sync",
        "s2c_host_snapshot", "s2c_full_snapshot", "s2c_state_patch",
        "s2c_private_notice", "s2c_public_observation", "s2c_tactical_prompt",
        "s2c_room_lobby_snapshot", "s2c_campaign_ended",
        "s2c_action_queued", "s2c_action_batched", "s2c_action_completed",
        "s2c_clarification_prompt", "s2c_clarification_result",
    ]
    assert len(valid_types) == 20
    for t in valid_types:
        assert t in EngineEventType.__args__
