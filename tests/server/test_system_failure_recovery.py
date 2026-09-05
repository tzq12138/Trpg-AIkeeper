"""R1 — real fault entry aligns room/action states and reaches recovery APIs.

The system pause written by the resolution pipeline must:
- record runtime_status='paused_system' (+ legacy status) with the integrity
  reason in the SAME transaction;
- preserve the in-flight action as `resolving` with its committed artifacts
  (earlier original dice receipts stay intact) instead of terminating it;
- never broadcast a fake s2c_action_completed(status='rejected');
- make the real recovery API (proposal creation) reachable from the fault;
- block new game actions while paused_system/recovering.
"""

import pytest

from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.engine.state_service import StateService
from tests.server.test_glass_rain_four_player_flow import (
    _DeterministicDirectorGateway,
    _GoldenFlowCompiler,
    _PersuadeCompiler,
    _RecordingDispatcher,
    _analyze,
    _confirm,
)
from tests.server.test_glass_rain_golden_flow import (
    _create_started_room,
    _install_glass_rain,
    _runtime_package,
)


class _FailingNarratorGateway:
    """Gateway whose narrate task always times out (test-only fault adapter)."""

    async def narrate_action(self, *_args, **_kwargs):
        raise TimeoutError("simulated narrator timeout")


def _move_draft_params(test_db, room_id: str) -> dict:
    package = _runtime_package(test_db, room_id)
    edge = package["semantic_progression_rules"]["edges"][0]
    return {
        "intent_type": "move",
        "params": {
            "fromNodeId": edge["from_scene_id"],
            "targetNodeId": edge["to_scene_id"],
            "analysis": {
                "semantic_progression": {
                    "validated": True,
                    "fromNodeId": edge["from_scene_id"],
                    "targetNodeId": edge["to_scene_id"],
                }
            },
        },
    }


@pytest.mark.asyncio
async def test_provider_failure_enters_recovery_from_real_pipeline(
    client,
    test_db,
    monkeypatch,
):
    """A post-roll narrator outage pauses the room and preserves the action."""
    monkeypatch.setenv("JWT_SECRET", "glass-rain-recovery-secret")
    monkeypatch.setattr(
        "src.server.rule_source_lifecycle.current_authoritative_base_version",
        lambda _conn: "coc7-base-v1",
    )
    installed, tokens, templates = _install_glass_rain(client, test_db)
    room, players, state_service = _create_started_room(
        client,
        test_db,
        installed,
        tokens,
        templates,
    )
    player = players[0]
    previous_gateway = client.app.state.gateway
    client.app.state.gateway = _DeterministicDirectorGateway()
    dispatcher = _RecordingDispatcher()
    try:
        # 1) A rule action settles normally first, committing an original dice
        #    receipt that must survive the later pause untouched.
        monkeypatch.setattr(
            "src.server.engine.skill_check.random.randint",
            lambda _low, _high: 5,
        )
        skill_draft = _analyze(
            client,
            player,
            "我用说服技能争取保安配合。",
            intent_type="skill_check",
            params={"skillName": "说服"},
        )
        skill_receipt = _confirm(client, player, skill_draft, "recovery-skill-key-1")
        completed = await ResolutionPipeline(
            conn=test_db,
            compiler=_PersuadeCompiler(),
            dispatcher=dispatcher,
            state_service=state_service,
            host_connection_checker=lambda _room_id: False,
        ).resolve_action(skill_receipt["action_id"])
        assert completed["status"] == "completed", completed

        # 2) A state-changing move action hits a narrator provider outage after
        #    its authoritative parts are committed.
        move_draft = _analyze(
            client,
            player,
            "我移动到相邻地点。",
            **_move_draft_params(test_db, room["room_id"]),
        )
        move_receipt = _confirm(client, player, move_draft, "recovery-move-key-1")
        monkeypatch.setattr(
            ResolutionPipeline,
            "_can_use_verified_narration_fallback",
            lambda *_args, **_kwargs: False,
        )
        failing_pipeline = ResolutionPipeline(
            conn=test_db,
            compiler=_GoldenFlowCompiler(),
            gateway=_FailingNarratorGateway(),
            dispatcher=dispatcher,
            state_service=state_service,
            host_connection_checker=lambda _room_id: False,
        )
        outcome = await failing_pipeline.resolve_action(move_receipt["action_id"])
        assert outcome.get("status") != "completed", outcome

        room_row = test_db.execute(
            "SELECT status, runtime_status, integrity_status, integrity_reason "
            "FROM rooms WHERE room_id = %s",
            (room["room_id"],),
        ).fetchone()
        assert room_row["runtime_status"] == "paused_system", room_row
        assert room_row["status"] == "paused"
        assert room_row["integrity_status"] == "read_only_recovery"
        assert room_row["integrity_reason"] == "narrator_timeout"

        # The in-flight action is preserved (not terminated) for recovery...
        action_row = test_db.execute(
            "SELECT status FROM actions WHERE action_id = %s",
            (move_receipt["action_id"],),
        ).fetchone()
        assert action_row["status"] == "resolving", action_row
        # ...and no fake terminal event was broadcast for it.
        assert [
            event for event in dispatcher.events
            if event[1] == "s2c_action_completed" and event[3].get("actionId") == move_receipt["action_id"]
        ] == []
        assert [
            event for event in dispatcher.events
            if event[1] == "s2c_room_paused" and event[2] == "party"
        ], "s2c_room_paused must reach the party audience over WS"
        # The earlier dice receipt survived untouched.
        skill_status = test_db.execute(
            "SELECT status FROM actions WHERE action_id = %s",
            (skill_receipt["action_id"],),
        ).fetchone()
        assert skill_status["status"] == "completed"

        # 3) The recovery entry point is now reachable from the real fault.
        proposal = client.post(
            f"/api/rooms/{room['room_id']}/recovery/proposals",
            headers={"X-Owner-Token": room["owner_token"]},
        )
        assert proposal.status_code in (200, 201), proposal.text
        assert proposal.json()["proposal"]["proposal_id"]

        # 4) New game actions are blocked while paused_system.
        blocked = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player["player_token"]},
            json={"declared_intent": "我继续行动"},
        )
        assert blocked.status_code == 409, blocked.text
    finally:
        client.app.state.gateway = previous_gateway
