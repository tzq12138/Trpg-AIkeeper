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


# ═══════════════════════════════════════════════════════════════════════════
# R3 — verified recovery executes and resumes the original action.
#
# Red chain: real narrator outage pauses the room with a journal row recorded
# in the same transaction; proposal → dry-run → execute must resume the SAME
# action/resolution to completion (not fake a completed result), keep the
# room/legacy states consistent, and leave the next action executable.
# ═══════════════════════════════════════════════════════════════════════════

from src.server.engine.resolution_journal import load_resolution


def _pause_move_action(
    client,
    test_db,
    player,
    room,
    dispatcher,
    move_key: str = "recovery-move-key-r3",
):
    """Build the failing pipeline for one state-changing move action."""
    move_draft = _analyze(
        client,
        player,
        "我移动到相邻地点。",
        **_move_draft_params(test_db, room["room_id"]),
    )
    move_receipt = _confirm(client, player, move_draft, move_key)
    failing_pipeline = ResolutionPipeline(
        conn=test_db,
        compiler=_GoldenFlowCompiler(),
        gateway=_FailingNarratorGateway(),
        dispatcher=dispatcher,
        state_service=StateService(test_db, dispatcher=dispatcher),
        host_connection_checker=lambda _room_id: False,
    )
    return failing_pipeline, move_receipt["action_id"]


async def _pause_move_action_resolve(failing_pipeline, action_id):
    """Run the failing resolution; the room must end paused_system."""
    outcome = await failing_pipeline.resolve_action(action_id)
    assert outcome.get("status") != "completed", outcome
    return outcome


@pytest.mark.asyncio
async def test_fault_proposal_execute_resumes_original_action(
    client,
    test_db,
    monkeypatch,
):
    """Pause → proposal → dry-run → execute completes the SAME action."""
    monkeypatch.setenv("JWT_SECRET", "glass-rain-recovery-secret")
    monkeypatch.setattr(
        "src.server.rule_source_lifecycle.current_authoritative_base_version",
        lambda _conn: "coc7-base-v1",
    )
    monkeypatch.setattr(
        "src.server.engine.skill_check.random.randint",
        lambda _low, _high: 5,
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
    previous_compiler = getattr(client.app.state, "compiler", None)
    client.app.state.gateway = _DeterministicDirectorGateway()
    client.app.state.compiler = _GoldenFlowCompiler()
    dispatcher = _RecordingDispatcher()
    room_id = room["room_id"]
    try:
        # 1) Real narrator outage pauses the room and preserves the action.
        skill_draft = _analyze(
            client,
            player,
            "我用说服技能争取保安配合。",
            intent_type="skill_check",
            params={"skillName": "说服"},
        )
        skill_receipt = _confirm(client, player, skill_draft, "recovery-skill-key-r3-1")
        completed = await ResolutionPipeline(
            conn=test_db,
            compiler=_PersuadeCompiler(),
            dispatcher=dispatcher,
            state_service=state_service,
            host_connection_checker=lambda _room_id: False,
        ).resolve_action(skill_receipt["action_id"])
        assert completed["status"] == "completed", completed

        monkeypatch.setattr(
            ResolutionPipeline,
            "_can_use_verified_narration_fallback",
            lambda *_args, **_kwargs: False,
        )
        failing_pipeline, action_id = _pause_move_action(
            client, test_db, player, room, dispatcher
        )
        await _pause_move_action_resolve(failing_pipeline, action_id)

        room_row = test_db.execute(
            "SELECT runtime_status, status FROM rooms WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        assert room_row["runtime_status"] == "paused_system"
        assert room_row["status"] == "paused"

        # The pause transaction recorded a released journal claim so recovery
        # can resume the same resolution identity later.
        journal_before = load_resolution(test_db, action_id)
        assert journal_before is not None, "pause must journal the interrupted action"
        assert journal_before["resolution_id"]
        assert journal_before["claim_token"] is None
        resolution_id = journal_before["resolution_id"]

        # 2) proposal → dry-run via the real recovery APIs.
        proposal_resp = client.post(
            f"/api/rooms/{room_id}/recovery/proposals",
            headers={"X-Owner-Token": room["owner_token"]},
        )
        assert proposal_resp.status_code == 201, proposal_resp.text
        proposal = proposal_resp.json()["proposal"]
        proposal_id = proposal["proposal_id"]
        assert proposal["room_id"] == room_id

        dry_run = client.post(
            f"/api/rooms/{room_id}/recovery/proposals/{proposal_id}/dry-run",
            headers={"X-Owner-Token": room["owner_token"]},
        )
        assert dry_run.status_code == 200, dry_run.text
        assert dry_run.json()["status"] == "dry_run_verified"

        # The original action is still untouched before execute.
        before = test_db.execute(
            "SELECT status FROM actions WHERE action_id = %s", (action_id,)
        ).fetchone()
        assert before["status"] == "resolving"

        # 3) execute resumes the original action to completion.
        executed = client.post(
            f"/api/rooms/{room_id}/recovery/proposals/{proposal_id}/execute",
            headers={"X-Owner-Token": room["owner_token"]},
            json={"confirm": True},
        )
        assert executed.status_code == 200, executed.text
        body = executed.json()
        assert body["status"] == "running", body

        # Same action identity completed...
        action_row = test_db.execute(
            "SELECT status, idempotency_key FROM actions WHERE action_id = %s",
            (action_id,),
        ).fetchone()
        assert action_row["status"] == "completed", action_row
        assert action_row["idempotency_key"] == "recovery-move-key-r3"
        # ...with the same journal resolution identity (resumed, not re-created).
        journal_after = load_resolution(test_db, action_id)
        assert journal_after is not None
        assert journal_after["resolution_id"] == resolution_id
        assert journal_after["claim_generation"] >= 2

        # Room legacy + runtime states are consistent and healthy.
        room_row = test_db.execute(
            "SELECT status, runtime_status, integrity_status, integrity_reason "
            "FROM rooms WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        assert room_row["runtime_status"] == "running"
        assert room_row["status"] == "active"
        assert room_row["integrity_status"] == "healthy"
        assert room_row["integrity_reason"] is None

        proposal_row = test_db.execute(
            "SELECT status FROM runtime_recovery_proposals WHERE proposal_id = %s",
            (proposal_id,),
        ).fetchone()
        assert proposal_row["status"] == "executed"

        # 4) The next action resolves normally after recovery.
        second_draft = _analyze(
            client,
            player,
            "我用侦查技能查看周围情况。",
            intent_type="skill_check",
            params={"skillName": "侦查"},
        )
        second_receipt = _confirm(client, player, second_draft, "post-recovery-key-r3-1")
        completed = await ResolutionPipeline(
            conn=test_db,
            compiler=_PersuadeCompiler(),
            dispatcher=dispatcher,
            state_service=state_service,
            host_connection_checker=lambda _room_id: False,
        ).resolve_action(second_receipt["action_id"])
        assert completed["status"] == "completed", completed

        # 5) A repeated execute returns the known state without re-running.
        again = client.post(
            f"/api/rooms/{room_id}/recovery/proposals/{proposal_id}/execute",
            headers={"X-Owner-Token": room["owner_token"]},
            json={"confirm": True},
        )
        assert again.status_code == 200, again.text
        assert again.json().get("already_executed") is True
        room_row = test_db.execute(
            "SELECT runtime_status, status FROM rooms WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        assert room_row["runtime_status"] == "running"
        assert room_row["status"] == "active"
    finally:
        client.app.state.gateway = previous_gateway
        client.app.state.compiler = previous_compiler


@pytest.mark.asyncio
async def test_execute_without_dry_run_is_rejected_and_room_stays_paused(
    client,
    test_db,
    monkeypatch,
):
    """execute requires a dry-run-verified proposal and never fake-completes."""
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
    previous_compiler = getattr(client.app.state, "compiler", None)
    client.app.state.gateway = _DeterministicDirectorGateway()
    client.app.state.compiler = _GoldenFlowCompiler()
    dispatcher = _RecordingDispatcher()
    room_id = room["room_id"]
    try:
        monkeypatch.setattr(
            ResolutionPipeline,
            "_can_use_verified_narration_fallback",
            lambda *_args, **_kwargs: False,
        )
        failing_pipeline, action_id = _pause_move_action(
            client, test_db, player, room, dispatcher
        )
        await _pause_move_action_resolve(failing_pipeline, action_id)

        proposal_resp = client.post(
            f"/api/rooms/{room_id}/recovery/proposals",
            headers={"X-Owner-Token": room["owner_token"]},
        )
        proposal_id = proposal_resp.json()["proposal"]["proposal_id"]

        # execute directly without dry-run: refused, room still paused, the
        # action never transitions behind the caller's back.
        refused = client.post(
            f"/api/rooms/{room_id}/recovery/proposals/{proposal_id}/execute",
            headers={"X-Owner-Token": room["owner_token"]},
            json={"confirm": True},
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["code"] == "recovery_dry_run_required"
        room_row = test_db.execute(
            "SELECT runtime_status FROM rooms WHERE room_id = %s", (room_id,)
        ).fetchone()
        assert room_row["runtime_status"] == "paused_system"
        action_row = test_db.execute(
            "SELECT status FROM actions WHERE action_id = %s", (action_id,)
        ).fetchone()
        assert action_row["status"] == "resolving"
    finally:
        client.app.state.gateway = previous_gateway
        client.app.state.compiler = previous_compiler


def test_cross_room_recovery_proposal_execute_is_rejected(
    client,
    test_db,
    monkeypatch,
):
    """A proposal cannot be executed against another room."""
    monkeypatch.setenv("JWT_SECRET", "glass-rain-recovery-secret")
    monkeypatch.setattr(
        "src.server.rule_source_lifecycle.current_authoritative_base_version",
        lambda _conn: "coc7-base-v1",
    )
    installed, tokens, templates = _install_glass_rain(client, test_db)
    room_a, players_a, _state = _create_started_room(
        client,
        test_db,
        installed,
        tokens,
        templates,
    )
    room_b, _players_b, _state_b = _create_started_room(
        client,
        test_db,
        installed,
        tokens,
        templates,
    )
    from src.server.engine.room_pause import pause_room_for_system_integrity

    # Pause through the real system-pause helper (no fake SQL status seeds).
    for rid in (room_a["room_id"], room_b["room_id"]):
        pause_room_for_system_integrity(
            test_db,
            room_id=rid,
            reason="cross_room_probe",
            source="test_pause_entry",
        )
        test_db.commit()
    proposal_a = client.post(
        f"/api/rooms/{room_a['room_id']}/recovery/proposals",
        headers={"X-Owner-Token": room_a["owner_token"]},
    )
    assert proposal_a.status_code == 201, proposal_a.text
    pid_a = proposal_a.json()["proposal"]["proposal_id"]
    client.post(
        f"/api/rooms/{room_a['room_id']}/recovery/proposals/{pid_a}/dry-run",
        headers={"X-Owner-Token": room_a["owner_token"]},
    )
    # Dry-run-verified on room A, then executed against room B: refused.
    crossed = client.post(
        f"/api/rooms/{room_b['room_id']}/recovery/proposals/{pid_a}/execute",
        headers={"X-Owner-Token": room_b["owner_token"]},
        json={"confirm": True},
    )
    assert crossed.status_code == 409, crossed.text
    assert crossed.json()["detail"]["code"] == "recovery_proposal_not_found"
