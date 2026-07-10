from src.server.models import EngineEvent, EngineEventType
from src.server.events.events_registry import ALL_EVENTS


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
    """All registered event types must be in EngineEventType Literal."""
    registry_types = [ev.type for ev in ALL_EVENTS.values()]
    assert len(registry_types) >= 29, f"Expected 29+ events, got {len(registry_types)}"
    for t in registry_types:
        assert t in EngineEventType.__args__, f"Missing EngineEventType: {t}"


def test_checkpoint_created_is_valid_engine_event():
    event = EngineEvent(
        room_id="room-1",
        type="s2c_checkpoint_created",
        audience="system",
        payload={"checkpointId": "cp-1"},
    )

    assert event.type == "s2c_checkpoint_created"
