"""R7 restart-evidence worker: a REAL separate OS process that drives the
glass-rain ai_only room until a crash point, then hard-exits (os._exit, no
cleanup — like a killed server). The parent pytest process then acts as the
"restarted server" against the SAME database and completes the recovery.

Usage (launched by test_recovery_process_restart.py):
    python recovery_kill_worker.py <dsn> <crash_point>
    crash_point:
      after_pause        real narrator fault pauses the room; exit BEFORE any
                         recovery API is touched (owner downtime window)
      mid_resolve        a state-changing move action committed its state and
                         the worker is killed INSIDE the narrator call — no
                         pause is ever written, so the stale resolution claim
                         must fence a second writer until the restarted server
                         releases it (response-lost window at process death)

The worker prints one JSON line on stdout when its state is ready:
{"pid": ..., "room_id": ..., "action_id": ..., "resolution_id": ...,
 "proposal_id"?, "crash_point": ...}
"""

from __future__ import annotations

import asyncio
import json
import os
import sys


def _out(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _failing_narrator_gateway():
    """Gateway whose narrate task always times out (test-only fault adapter)."""

    class _FailingNarratorGateway:
        async def narrate_action(self, *_args, **_kwargs):
            raise TimeoutError("simulated narrator timeout")

    return _FailingNarratorGateway()


def _killing_narrator_gateway():
    """Gateway whose narrate call hard-kills the process (crash, no pause)."""

    class _KillingNarratorGateway:
        async def narrate_action(self, *_args, **_kwargs):
            os._exit(9)  # noqa: PLR1722 — killed mid-resolution

    return _KillingNarratorGateway()


def _move_draft_params(conn, room_id: str) -> dict:
    from tests.server.test_glass_rain_golden_flow import _runtime_package

    package = _runtime_package(conn, room_id)
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


async def _run_flow(dsn: str, crash_point: str) -> int:
    os.environ.setdefault("AIKEEPER_DEV_MODE", "1")
    from fastapi.testclient import TestClient

    from src.server.db_adapter import PgDatabase
    from src.server.engine.resolution_pipeline import ResolutionPipeline
    from src.server.engine.state_service import StateService
    from src.server.main import app
    import src.server.rule_source_lifecycle as rule_source_lifecycle
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
    )

    # The R1 test monkeypatches this to a fixed base version; a worker process
    # cannot monkeypatch, so set the same module attribute directly.
    rule_source_lifecycle.current_authoritative_base_version = (
        lambda _conn: "coc7-base-v1"
    )

    pg = PgDatabase(dsn=dsn)
    pg.connect()
    pg.initialize()
    conn = pg.get_connection()
    app.state.db = conn
    from src.server.engine import Engine

    app.state.engine = Engine(conn)
    app.state.gateway = None
    client = TestClient(app)

    from src.server.engine import skill_check

    # Deterministic d100 = 5 for the first settled skill action (the R1 test
    # monkeypatches the same module attribute in-process).
    skill_check.random.randint = lambda _low, _high: 5  # type: ignore[assignment]

    try:
        installed, tokens, templates = _install_glass_rain(client, conn)
        room, players, state_service = _create_started_room(
            client, conn, installed, tokens, templates,
        )
        player = players[0]
        client.app.state.gateway = _DeterministicDirectorGateway()
        dispatcher = _RecordingDispatcher()

        # 1) A rule action settles normally first, committing an original dice
        #    receipt that must survive the later pause untouched.
        skill_draft = _analyze(
            client, player, "我用说服技能争取保安配合。",
            intent_type="skill_check", params={"skillName": "说服"},
        )
        skill_receipt = _confirm(client, player, skill_draft, "recovery-skill-key-1")
        completed = await ResolutionPipeline(
            conn=conn,
            compiler=_PersuadeCompiler(),
            dispatcher=dispatcher,
            state_service=state_service,
            host_connection_checker=lambda _room_id: False,
        ).resolve_action(skill_receipt["action_id"])
        if not completed or completed.get("status") != "completed":
            _out({"error": "skill_settle_failed", "completed": str(completed)[:300]})
            return 2

        # 2) A state-changing move action hits a narrator outage after its
        #    authoritative parts are committed -> real system pause.
        move_draft = _analyze(
            client, player, "我移动到相邻地点。",
            **_move_draft_params(conn, room["room_id"]),
        )
        move_receipt = _confirm(client, player, move_draft, "recovery-move-key-1")
        ResolutionPipeline._can_use_verified_narration_fallback = (
            lambda *_args, **_kwargs: False
        )
        narrator_gateway = (
            _killing_narrator_gateway()
            if crash_point == "mid_resolve"
            else _failing_narrator_gateway()
        )
        failing_pipeline = ResolutionPipeline(
            conn=conn,
            compiler=_GoldenFlowCompiler(),
            gateway=narrator_gateway,
            dispatcher=dispatcher,
            state_service=state_service,
            host_connection_checker=lambda _room_id: False,
        )
        action_id = move_receipt["action_id"]
        if crash_point == "mid_resolve":
            # The state commit and journal stage precede narration in the
            # pipeline; this process dies inside the narrator call.
            _out({
                "pid": os.getpid(),
                "room_id": room["room_id"],
                "action_id": action_id,
                "crash_point": crash_point,
                "phase": "about_to_crash_inside_narrator",
            })
            await failing_pipeline.resolve_action(action_id)
            _out({"error": "resolve_returned_after_kill"})
            return 2

        outcome = await failing_pipeline.resolve_action(action_id)
        if not outcome or outcome.get("status") == "completed":
            _out({"error": "pause_not_reached", "outcome": str(outcome)[:300]})
            return 2

        resolution_id = ""
        run_row = conn.execute(
            "SELECT resolution_id FROM action_resolution_runs WHERE action_id = %s",
            (action_id,),
        ).fetchone()
        if run_row:
            resolution_id = str(run_row.get("resolution_id") or "")
        _out({
            "pid": os.getpid(),
            "room_id": room["room_id"],
            "action_id": action_id,
            "resolution_id": resolution_id,
            "runtime_status": "paused_system",
            "crash_point": crash_point,
        })

        if crash_point == "after_pause":
            os._exit(9)  # noqa: PLR1722 — hard kill: no cleanup, no flush
        _out({"error": "unknown_crash_point", "crash_point": crash_point})
        return 2
    except Exception as exc:  # pragma: no cover - failure diagnostics
        _out({"error": type(exc).__name__, "detail": str(exc)[:400]})
        return 3


def main() -> int:
    dsn = sys.argv[1]
    crash_point = sys.argv[2]
    os.environ["JWT_SECRET"] = "glass-rain-recovery-secret"
    os.environ["DATABASE_URL"] = dsn
    return asyncio.run(_run_flow(dsn, crash_point))


if __name__ == "__main__":
    raise SystemExit(main())
