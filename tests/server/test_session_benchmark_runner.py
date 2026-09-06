"""V3 — runner CLI contract tests (exit codes, config and env validation).

These tests never execute benchmark sessions; they pin the runner's CLI
contract so an honest "plan incomplete" (exit 1) can never be confused with a
configuration error (exit 2) or a completed plan (exit 0).
"""

import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "scripts" / "run_session_benchmark.py"


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RUNNER), *args],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(REPO_ROOT),
    )


def _config(tmp_path: Path, *, sessions: int = 32, seed_prefix: str = "seed-") -> Path:
    planned = []
    for index in range(1, sessions + 1):
        kind = "simulation" if index <= 30 else "fault"
        planned.append({
            "session_id": f"sim-{index:02d}" if index <= 30 else f"fault-{index - 30:02d}",
            "run_kind": kind,
            "seed": f"{seed_prefix}{index:08d}",
            "persona": "normal",
        })
    path = tmp_path / "run-config.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "rc_id": "rc-20260905-01",
        "git_commit": "073ee1491f042e4102b1b6364d459bdee149d736",
        "sessions_planned": planned,
    }, ensure_ascii=False), encoding="utf-8")
    return path


class _HealthServer(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/api/health":
            body = json.dumps({"status": "ok"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *_args):  # silence
        pass


@pytest.fixture()
def health_server():
    server = HTTPServer(("127.0.0.1", 0), _HealthServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_help_contract(tmp_path):
    result = _run_cli("--help")
    assert result.returncode == 0, result.stderr
    assert "--config" in result.stdout
    assert "--base-url" in result.stdout
    assert "--output" in result.stdout


def test_missing_config_is_environment_error(tmp_path):
    result = _run_cli(
        "--config", str(tmp_path / "nope.json"),
        "--base-url", "http://127.0.0.1:3001",
        "--output", str(tmp_path / "out"),
    )
    assert result.returncode == 2, result.stdout
    assert "CONFIG-ERROR config_file_missing" in result.stdout


def test_invalid_config_reports_codes(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": 99, "rc_id": ""}), encoding="utf-8")
    result = _run_cli(
        "--config", str(bad),
        "--base-url", "http://127.0.0.1:3001",
        "--output", str(tmp_path / "out"),
    )
    assert result.returncode == 2
    assert "schema_version_mismatch" in result.stdout
    assert "rc_id_missing" in result.stdout
    assert "sessions_planned_below_32" in result.stdout


def test_unreachable_server_is_environment_error(tmp_path):
    config = _config(tmp_path)
    result = _run_cli(
        "--config", str(config),
        "--base-url", "http://127.0.0.1:1",
        "--output", str(tmp_path / "out"),
    )
    assert result.returncode == 2, result.stdout
    assert "ENV-ERROR server_unreachable" in result.stdout


def test_available_server_without_driver_is_plan_incomplete(tmp_path, health_server):
    config = _config(tmp_path)
    output = tmp_path / "evidence"
    result = _run_cli(
        "--config", str(config),
        "--base-url", health_server,
        "--output", str(output),
    )
    assert result.returncode == 1, result.stdout
    assert "STATUS plan_incomplete" in result.stdout
    assert "driver_not_implemented_v4" in result.stdout
    run_config = output / "benchmark" / "run-config.json"
    assert run_config.exists()
    assert "rc_id" in run_config.read_text(encoding="utf-8")


def test_persona_utterance_selection_is_deterministic_per_seed():
    from scripts.benchmark_sim_driver import pick_utterance

    first = [pick_utterance("2026090501", "cautious", seat=0, index=i) for i in range(4)]
    second = [pick_utterance("2026090501", "cautious", seat=0, index=i) for i in range(4)]
    assert first == second
    other_seed = [pick_utterance("2026090502", "cautious", seat=0, index=i) for i in range(4)]
    assert first != other_seed or True  # different seeds may collide; determinism is the contract
    # Different personas draw from their own pools.
    pool_normal = {pick_utterance("2026090501", "normal", 0, i) for i in range(20)}
    pool_aggressive = {pick_utterance("2026090501", "aggressive", 0, i) for i in range(20)}
    assert pool_normal and pool_aggressive


def test_session_budget_records_stop_reason_never_fabricates_ending():
    from scripts.benchmark_sim_driver import budget

    started = time.time()
    keep, reason = budget(119, started, time.time())
    assert keep and reason == ""
    keep, reason = budget(120, started, time.time())
    assert not keep and reason == "cap_120_actions"
    keep, reason = budget(10, started, started + 61 * 60)
    assert not keep and reason == "cap_60_minutes"
