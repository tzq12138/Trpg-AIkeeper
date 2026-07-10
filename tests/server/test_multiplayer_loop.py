import httpx

from scripts import run_multiplayer_loop as loop


def test_wait_for_actions_resolution_skips_fallback_while_auto_settlement_runs(monkeypatch):
    status_results = iter(["resolving", "resolved"])
    clock_values = iter([0.0, 15.0, 16.0, 17.0])

    def fake_get_action_status(_client, _token, _action_id):
        return {"status": next(status_results)}

    def fail_if_fallback_runs(*_args, **_kwargs):
        raise AssertionError("auto-settling action must not trigger manual ai-turn")

    monkeypatch.setattr(loop, "get_action_status", fake_get_action_status)
    monkeypatch.setattr(loop, "maybe_trigger_ai_turn", fail_if_fallback_runs)
    monkeypatch.setattr(loop.time, "monotonic", lambda: next(clock_values))
    monkeypatch.setattr(loop.time, "sleep", lambda _seconds: None)

    result = loop.wait_for_actions_resolution(
        client=object(),
        room_id="room-1",
        owner_token="owner-token",
        submitted_actions=[{"player_token": "player-token", "action_id": "action-1"}],
        timeout_seconds=60,
        ai_fallback_after=10,
    )

    assert result["_fallback_triggered"] is False
    assert result["actions"][0]["status_result"]["status"] == "resolved"


def test_manual_ai_turn_timeout_does_not_abort_loop():
    class TimeoutClient:
        def post(self, *_args, **_kwargs):
            raise httpx.ReadTimeout("AI response is still pending")

    assert loop.maybe_trigger_ai_turn(TimeoutClient(), "room-1", "owner-token") is False
