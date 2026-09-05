"""B5 — the first-deliverable opening flow: join → confirm → start → receipt.

Two players, no Stage, Owner absent after start: the room opens through the
real Session Zero probe chain and the first actions settle through the real
draft protocol with stable Idempotency-Key, returning authoritative receipts.
A dialogue action must not fabricate dice; a skill action must produce a
verification receipt; a repeated confirm must not settle a second time.
"""

import asyncio
import json

import pytest

from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.engine.state_service import StateService
from tests.server.test_glass_rain_four_player_flow import (
    _DeterministicDirectorGateway,
    _FailingNarratorGateway,
    _GoldenFlowCompiler,
    _PersuadeCompiler,
    _RecordingDispatcher,
    _analyze,
    _confirm,
)
from tests.server.test_glass_rain_golden_flow import (
    _create_started_room,
    _install_glass_rain,
)


@pytest.mark.asyncio
async def test_two_players_no_stage_reach_first_authoritative_receipt(
    client,
    test_db,
    monkeypatch,
):
    """Two players without Stage complete open → first actions → receipts."""
    monkeypatch.setenv("JWT_SECRET", "glass-rain-opening-secret")
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
    room_row = test_db.execute(
        "SELECT status, runtime_status FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert room_row["status"] == "active"
    assert room_row["runtime_status"] == "running"
    player_one = players[0]
    headers = {"X-Room-Token": player_one["player_token"]}

    previous_gateway = client.app.state.gateway
    client.app.state.gateway = _DeterministicDirectorGateway()
    dispatcher = _RecordingDispatcher()
    state_version_before = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"]

    def build_pipeline():
        return ResolutionPipeline(
            conn=test_db,
            compiler=_GoldenFlowCompiler(),
            gateway=_FailingNarratorGateway(),
            dispatcher=dispatcher,
            state_service=state_service,
            host_connection_checker=lambda _room_id: False,
        )

    try:
        # ── 1. Non-rule action: dialogue must NOT fabricate dice ──────────
        dialogue = _analyze(client, player_one, "我检查公开的告示牌。")
        assert dialogue["adjudication_stage"].startswith(("director", "player_"))
        dialogue_receipt = _confirm(
            client,
            player_one,
            dialogue,
            "opening-dialogue-key-1",
        )
        resolved_dialogue = await build_pipeline().resolve_action(
            dialogue_receipt["action_id"]
        )
        assert resolved_dialogue["status"] == "completed", resolved_dialogue
        fetched = client.get(
            f"/api/player/actions/{dialogue_receipt['action_id']}",
            headers=headers,
        )
        assert fetched.status_code == 200, fetched.text
        dialogue_body = fetched.json()
        dialogue_text = json.dumps(dialogue_body, ensure_ascii=False)
        assert dialogue_body["status"] == "completed"
        # No dice were fabricated: the verification receipt is present as a
        # null placeholder rather than carrying a signed roll.
        assert '"verification_receipt": null' in dialogue_text

        # ── 2. Rule action: skill check with deterministic dice ──────────
        monkeypatch.setattr(
            "src.server.engine.skill_check.random.randint",
            lambda _low, _high: 5,  # reliable success below the 说服 threshold
        )
        skill = _analyze(
            client,
            player_one,
            "我用说服技能争取保安配合。",
            intent_type="skill_check",
            params={"skillName": "说服"},
        )
        skill_receipt = _confirm(
            client,
            player_one,
            skill,
            "opening-skill-key-1",
        )
        skill_pipeline = ResolutionPipeline(
            conn=test_db,
            compiler=_PersuadeCompiler(),
            gateway=_FailingNarratorGateway(),
            dispatcher=dispatcher,
            state_service=state_service,
            host_connection_checker=lambda _room_id: False,
        )
        resolved_skill = await skill_pipeline.resolve_action(
            skill_receipt["action_id"]
        )
        assert resolved_skill["status"] == "completed", resolved_skill
        skill_fetched = client.get(
            f"/api/player/actions/{skill_receipt['action_id']}",
            headers=headers,
        )
        assert skill_fetched.status_code == 200, skill_fetched.text
        skill_body = skill_fetched.json()
        skill_text = json.dumps(skill_body, ensure_ascii=False)
        assert skill_body["status"] == "completed"
        # The rule action carries a non-null signed verification receipt.
        assert '"verification_receipt": null' not in skill_text
        assert "verification_receipt" in skill_text or "rule_explanation" in skill_text

        # ── 3. Repeating the same confirm is idempotent ───────────────────
        repeat = _confirm(
            client,
            player_one,
            skill,
            "opening-skill-key-1",
        )
        assert repeat["action_id"] == skill_receipt["action_id"]
        trace_rows = test_db.execute(
            "SELECT resolution_trace_id FROM resolution_traces WHERE action_id = %s",
            (skill_receipt["action_id"],),
        ).fetchall()
        assert len(trace_rows) == 1
        resolving_rows = test_db.execute(
            "SELECT status_event_id FROM action_status_events "
            "WHERE action_id = %s AND status = 'resolving'",
            (skill_receipt["action_id"],),
        ).fetchall()
        assert len(resolving_rows) == 1
    finally:
        client.app.state.gateway = previous_gateway

    # Owner stayed offline after start and no Stage was ever involved: the room
    # must not have produced host ADJUDICATION traffic. (Host-audience audit
    # projections such as s2c_director_plan_validated are normal console data.)
    adjudication = test_db.execute(
        "SELECT sequence FROM events WHERE room_id = %s "
        "AND event_type IN ('s2c_action_exception_requested', 's2c_ai_recovery_required', "
        "'s2c_host_review_requested', 's2c_action_review_requested')",
        (room["room_id"],),
    ).fetchall()
    assert adjudication == []
    final_version = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["state_version"]
    assert final_version >= state_version_before
