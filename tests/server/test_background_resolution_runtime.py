from types import SimpleNamespace

from src.server.player import router_player


def test_background_pipeline_keeps_ai_guard_and_connection_scoped_state(monkeypatch):
    captured = {}

    class FakeDispatcher:
        def __init__(self, conn, **kwargs):
            captured["dispatcher"] = {"conn": conn, **kwargs}

    class FakeStateService:
        def __init__(self, conn, dispatcher):
            captured["state_service"] = {"conn": conn, "dispatcher": dispatcher}
            captured["state_service_instance"] = self

    class FakePipeline:
        def __init__(self, conn, **kwargs):
            captured["pipeline"] = {"conn": conn, **kwargs}

    monkeypatch.setattr(router_player, "ProjectionDispatcher", FakeDispatcher)
    monkeypatch.setattr(router_player, "ResolutionPipeline", FakePipeline)
    monkeypatch.setattr("src.server.engine.state_service.StateService", FakeStateService)

    connection = object()
    app = SimpleNamespace(state=SimpleNamespace(
        compiler="compiler",
        cache="cache",
        spoiler_guard="guard",
        gateway="gateway",
    ))

    router_player._create_background_pipeline(app, connection)

    assert captured["dispatcher"] == {
        "conn": connection,
        "cache": "cache",
        "spoiler_guard": "guard",
    }
    assert captured["state_service"]["conn"] is connection
    assert captured["pipeline"] == {
        "conn": connection,
        "compiler": "compiler",
        "dispatcher": captured["state_service"]["dispatcher"],
        "spoiler_guard": "guard",
        "gateway": "gateway",
        "state_service": captured["state_service_instance"],
    }
