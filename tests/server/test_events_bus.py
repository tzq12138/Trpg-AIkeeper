from src.server.events import EventBus
from src.server.models import EngineEvent
from src.server.projection import ProjectionBuilder


def test_event_bus_publish_and_subscribe():
    bus = EventBus()
    received = []
    bus.subscribe("room-1", lambda e: received.append(e))
    event = EngineEvent(
        room_id="room-1", type="s2c_host_snapshot", audience="host", payload={}
    )
    bus.publish(event)
    assert len(received) == 1
    assert received[0].type == "s2c_host_snapshot"


def test_event_bus_filters_by_room():
    bus = EventBus()
    received = []
    bus.subscribe("room-1", lambda e: received.append(e))
    event = EngineEvent(
        room_id="room-2", type="s2c_host_snapshot", audience="host", payload={}
    )
    bus.publish(event)
    assert len(received) == 0


def test_projection_builder_generates_host_and_player_events():
    builder = ProjectionBuilder()
    event = EngineEvent(
        room_id="room-1",
        type="s2c_reveal_transaction",
        audience="host",
        payload={"steps": []},
    )
    projections = builder.build(event)
    assert any(p.audience == "host" for p in projections)


def test_projection_party_generates_host_and_player():
    builder = ProjectionBuilder()
    event = EngineEvent(
        room_id="room-1",
        type="s2c_public_observation",
        audience="party",
        payload={"text": "a door creaks"},
    )
    projections = builder.build(event)
    audiences = {p.audience for p in projections}
    assert "host" in audiences
    assert "player" in audiences
