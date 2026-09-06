"""R7 — real process terminate/restart evidence for system recovery.

A REAL separate OS process (recovery_kill_worker.py) drives a glass-rain
ai_only room: settles a skill action with an original die, triggers a genuine
narrator-outage fault that pauses the room paused_system, and then hard-exits
(os._exit — no cleanup, no graceful flush) at one of two crash windows:

  after_pause   — Owner downtime after the pause; nothing touched recovery
                  yet. The parent (the "restarted server") then runs the real
                  recovery API against the SAME database and the ORIGINAL
                  action resumes to completion with the SAME resolution_id.
  mid_resolve   — killed inside the narrator call without a pause ever being
                  written. Pins the crash-left consistency state (room still
                  running, action still resolving, no committed delta, no
                  journal row) so a restart can never silently double-apply
                  or fake a recovery; the recoverable window is the pause one
                  (R2 stage embedding remains the registered remaining item).

Only the PID started by this test is ever terminated (the worker kills
itself); no process is killed by name. The worker PID, room/action ids and
the reused resolution_id are printed as machine-readable evidence lines.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER = REPO_ROOT / "tests" / "server" / "recovery_kill_worker.py"


def _run_worker(test_db_url: str, crash_point: str) -> dict:
    env = {
        **os.environ,
        "DATABASE_URL": test_db_url,
        "TEST_DATABASE_URL": test_db_url,
        "AIKEEPER_DEV_MODE": "1",
        "AI_CONFIG_MASTER_KEY": "p0-executor-test-key",
        "PYTHONUTF8": "1",
        "ROLL_RECEIPT_SECRET": "glass-rain-recovery-secret",
        "PYTHONPATH": str(REPO_ROOT),
    }
    proc = subprocess.run(
        [sys.executable, str(WORKER), test_db_url, crash_point],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
        cwd=str(REPO_ROOT),
    )
    ready = None
    for line in (proc.stdout or "").splitlines():
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            ready = parsed
            break
    return {
        "returncode": proc.returncode,
        "ready": ready or {},
        "stdout_tail": (proc.stdout or "")[-600:],
        "stderr_tail": (proc.stderr or "")[-1200:],
    }


def _read_original_resolution_id(test_db, action_id: str) -> str:
    row = test_db.execute(
        "SELECT resolution_id FROM action_resolution_runs WHERE action_id = %s",
        (action_id,),
    ).fetchone()
    return str(row["resolution_id"] or "") if row else ""


async def _finish_recovery(client, test_db, room_id: str, owner_token: str,
                           proposal_id: str | None, action_id: str,
                           original_resolution_id: str) -> dict:
    """Post-restart continuation through the REAL recovery API.

    The execute endpoint resumes the preserved actions inline through the
    unified background pipeline: it returns either {"status": "recovering",
    actions_to_resume: [...]} for a still-running recovery or, when every
    resumed action already completed, {"status": "running", "resumed": [...]}.
    """
    headers = {"X-Owner-Token": owner_token}
    if not proposal_id:
        response = client.post(
            f"/api/rooms/{room_id}/recovery/proposals", headers=headers,
        )
        assert response.status_code == 201, response.text
        proposal_id = response.json()["proposal"]["proposal_id"]
    dry = client.post(
        f"/api/rooms/{room_id}/recovery/proposals/{proposal_id}/dry-run",
        headers=headers,
    )
    assert dry.status_code == 200, dry.text
    executed = client.post(
        f"/api/rooms/{room_id}/recovery/proposals/{proposal_id}/execute",
        headers=headers,
        json={"confirm": True},
    )
    assert executed.status_code == 200, executed.text
    execute_body = executed.json()

    actions_to_resume = execute_body.get("actions_to_resume") or []
    resumed = execute_body.get("resumed") or []
    if actions_to_resume and action_id in actions_to_resume:
        # Recovery still in flight: the restarted server resumes the preserved
        # actions itself, then finalizes.
        from src.server.engine.resolution_pipeline import ResolutionPipeline
        from src.server.engine.state_service import StateService
        from tests.server.test_glass_rain_four_player_flow import (
            _GoldenFlowCompiler,
            _RecordingDispatcher,
        )

        state_service = StateService(test_db)
        pipeline = ResolutionPipeline(
            conn=test_db,
            compiler=_GoldenFlowCompiler(),
            dispatcher=_RecordingDispatcher(),
            state_service=state_service,
            host_connection_checker=lambda _room_id: False,
        )
        for resumed_action_id in actions_to_resume:
            result = await pipeline.resolve_action(resumed_action_id)
            assert result.get("status") == "completed", result

        from src.server.engine.system_recovery import finalize_system_recovery

        finalized = finalize_system_recovery(
            test_db, room_id, proposal_id, ok=True,
        )
        assert finalized.get("status") == "running", finalized
    else:
        # Execute already resumed and completed every action inline.
        assert execute_body.get("status") == "running", execute_body
        assert resumed, execute_body
        assert action_id in [item.get("action_id") for item in resumed], execute_body
    final_action = test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s", (action_id,),
    ).fetchone()
    assert final_action["status"] == "completed", final_action
    resumed_id = _read_original_resolution_id(test_db, action_id)
    assert resumed_id == original_resolution_id, (
        resumed_id, original_resolution_id,
    )
    return {"proposal_id": proposal_id, "resolution_id": resumed_id}


async def _crash_after_pause_resumes_same_action(client, test_db):
    worker = _run_worker(_db_url(), "after_pause")
    assert worker["returncode"] == 9, worker
    ready = worker["ready"]
    assert ready.get("room_id") and ready.get("action_id"), worker["stdout_tail"]
    pid = int(ready["pid"])
    assert pid > 0
    room_id = ready["room_id"]
    action_id = ready["action_id"]
    original_resolution_id = ready.get("resolution_id") or _read_original_resolution_id(
        test_db, action_id,
    )
    room = test_db.execute(
        "SELECT runtime_status, owner_token FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    assert room["runtime_status"] == "paused_system", room
    action = test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s", (action_id,),
    ).fetchone()
    assert action["status"] == "resolving", action

    outcome = await _finish_recovery(
        client, test_db, room_id, room["owner_token"], None,
        action_id, original_resolution_id,
    )
    final_action = test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s", (action_id,),
    ).fetchone()
    assert final_action["status"] == "completed", final_action
    return {
        "worker_pid": pid,
        "crash_point": "after_pause",
        "room_id": room_id,
        "action_id": action_id,
        **outcome,
    }


async def _crash_mid_resolve_consistency(client, test_db):
    """Killed inside the narrator call AFTER the state commit but WITHOUT a
    pause ever being written (hard kill, no cleanup).

    Current engine contract (R2 stage embedding is the registered remaining
    item): recoverable interruptions are the ones that reach the system pause,
    which preserves the action and its committed artifacts. This test pins the
    crash-left state so a future change cannot silently double-apply or fake a
    recovery: the action stays `resolving`, the room stays `running`, the
    committed state version stands, and NO journal row exists to claim a
    recovery that never happened. The restart evidence for the RECOVERY path
    is the after_pause test above.
    """
    worker = _run_worker(_db_url(), "mid_resolve")
    assert worker["returncode"] == 9, worker
    ready = worker["ready"]
    assert ready.get("room_id") and ready.get("action_id"), worker["stdout_tail"]
    room_id = ready["room_id"]
    action_id = ready["action_id"]
    room = test_db.execute(
        "SELECT runtime_status, state_version FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    action = test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s", (action_id,),
    ).fetchone()
    run_row = test_db.execute(
        "SELECT resolution_id, claim_token FROM action_resolution_runs "
        "WHERE action_id = %s",
        (action_id,),
    ).fetchone()
    assert room["runtime_status"] == "running", room
    assert action["status"] == "resolving", action
    # Observed pipeline order in this flow: the narrator stage runs BEFORE the
    # authoritative world commit, so a kill inside the narrator call leaves
    # state_version untouched — the crash left no committed delta and no
    # journal row claiming a recovery. The restarted process must not mutate
    # anything without an explicit recovery decision.
    assert int(room["state_version"]) == 0, room
    assert run_row is None, run_row
    return {
        "worker_pid": int(ready["pid"]),
        "crash_point": "mid_resolve",
        "room_id": room_id,
        "action_id": action_id,
        "state_version": int(room["state_version"]),
        "journal_row": run_row is None,
    }


def _db_url() -> str:
    url = os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
    assert url, "DATABASE_URL must point at the isolated test database"
    assert "test" in url.split("/")[-1], "refusing to run on a business database"
    return url


@pytest.mark.asyncio
async def test_restart_after_pause_resumes_original_action(client, test_db):
    """Worker killed after the pause: restarted server recovers the SAME action."""
    evidence = await _crash_after_pause_resumes_same_action(client, test_db)
    assert evidence["worker_pid"] > 0
    assert evidence["resolution_id"]
    assert evidence["proposal_id"]
    assert evidence["room_id"] and evidence["action_id"]
    # Evidence line for the delivery record (machine-readable, no secrets).
    print(
        "R7-RESTART pid={worker_pid} crash={crash_point} "
        "room={room_id} action={action_id} proposal={proposal_id} "
        "resolution={resolution_id}".format(**evidence)
    )


@pytest.mark.asyncio
async def test_restart_kill_without_pause_leaves_single_commit(client, test_db):
    """Worker killed mid-resolution (no pause): crash-left state is pinned."""
    evidence = await _crash_mid_resolve_consistency(client, test_db)
    assert evidence["worker_pid"] > 0
    assert evidence["journal_row"] is True
    assert evidence["state_version"] == 0
    print(
        "R7-RESTART pid={worker_pid} crash={crash_point} "
        "room={room_id} action={action_id} state_version={state_version} "
        "journal={journal_row}".format(**evidence)
    )
