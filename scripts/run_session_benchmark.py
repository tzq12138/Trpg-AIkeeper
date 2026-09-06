"""V3 — real session benchmark runner CLI.

Exit-code contract (03 §V3):
    0 = the planned sessions completed their collection (NOT a release pass);
    1 = session failure / missing evidence (blocking codes or failures);
    2 = configuration or environment error.

The runner never writes results after a run ("补跑后补 seed"), never touches
the database, and drives sessions exclusively through the normal HTTP/WS
chain. Session drivers (per run_kind) live in scripts/benchmark_sim_driver.py;
when a driver is unavailable the session is recorded as failed with a
machine-readable reason — the runner never fabricates a session.

Usage:
    python scripts/run_session_benchmark.py --help
    python scripts/run_session_benchmark.py \
        --config <benchmark/run-config.json> \
        --base-url http://127.0.0.1:3001 \
        --output <evidence-root>
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.server.scenario.benchmark_evidence import (  # noqa: E402
    SCHEMA_VERSION,
    manifest_digest,
    validate_evidence_manifest,
)

EXIT_PLAN_COMPLETE = 0
EXIT_SESSION_FAILURE = 1
EXIT_CONFIG_ERROR = 2


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_run_config(path: Path) -> tuple[dict | None, list[str]]:
    if not path.exists():
        return None, ["config_file_missing"]
    try:
        with path.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
    except json.JSONDecodeError as exc:
        return None, [f"config_json_invalid:{exc.msg}"]
    if not isinstance(config, dict):
        return None, ["config_not_object"]
    errors: list[str] = []
    if config.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version_mismatch")
    for key in ("rc_id", "git_commit"):
        if not isinstance(config.get(key), str) or not config[key]:
            errors.append(f"{key}_missing")
    planned = config.get("sessions_planned")
    if not isinstance(planned, list) or len(planned) < 32:
        errors.append("sessions_planned_below_32")
    else:
        for entry in planned:
            if not isinstance(entry, dict):
                errors.append("session_plan_entry_invalid")
                continue
            if entry.get("run_kind") not in ("simulation", "browser", "fault"):
                errors.append("session_plan_kind_invalid")
            if not isinstance(entry.get("seed"), str):
                errors.append("session_plan_seed_missing")
    if errors:
        return None, errors
    return config, []


def check_server(base_url: str) -> str | None:
    try:
        with urllib.request.urlopen(f"{base_url}/api/health", timeout=5) as response:
            if response.status != 200:
                return f"health_http_{response.status}"
    except urllib.error.URLError as exc:
        return f"server_unreachable:{type(exc.reason).__name__ if exc.reason else 'unknown'}"
    except Exception as exc:  # noqa: BLE001 - environment diagnostics
        return f"server_unreachable:{type(exc).__name__}"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the fixed-seed AI-only session benchmark over real HTTP/WS.",
    )
    parser.add_argument("--config", required=True, help="benchmark/run-config.json")
    parser.add_argument("--base-url", required=True, help="http://127.0.0.1:3001")
    parser.add_argument("--output", required=True, help="evidence output root")
    args = parser.parse_args(argv)

    config, errors = load_run_config(Path(args.config))
    if config is None:
        for code in errors:
            print(f"CONFIG-ERROR {code}")
        return EXIT_CONFIG_ERROR

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    server_error = check_server(args.base_url)
    if server_error:
        print(f"ENV-ERROR {server_error}")
        return EXIT_CONFIG_ERROR

    # Evidence manifest root mirrors the V3 shapes; the runner records the
    # pre-run digest so post-run seeds/results cannot be written in later.
    planned = config["sessions_planned"]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "rc_id": config.get("rc_id"),
        "git_commit": config.get("git_commit"),
        "run_config": config,
        "sessions": [],
        "actions": [],
        "annotations": [],
        "trace_manifest": {
            "expected_action_ids": [],
            "complete_trace_action_ids": [],
        },
        "ratings": {},
    }
    run_started = _stamp()
    (output / "benchmark").mkdir(parents=True, exist_ok=True)
    (output / "benchmark" / "run-config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    digest = manifest_digest(manifest)
    print(f"PLAN sessions={len(planned)} rc={config.get('rc_id')} "
          f"digest={digest[:16]} started={run_started}")

    failures: list[str] = []
    for index, plan_entry in enumerate(planned, start=1):
        session_id = f"{plan_entry.get('session_id') or index:>03}"
        run_kind = plan_entry.get("run_kind")
        try:
            from scripts.benchmark_sim_driver import run_session

            outcome = run_session(
                session_id=session_id,
                plan=plan_entry,
                base_url=args.base_url,
                output_dir=str(output),
            )
        except ImportError:
            outcome = {
                "session_id": session_id,
                "ok": False,
                "reason_code": "driver_not_available",
            }
        except NotImplementedError:
            # The live drivers require the frozen service window (V4); the
            # plan stays honest: incomplete, never fabricated.
            outcome = {
                "session_id": session_id,
                "ok": False,
                "reason_code": "driver_not_implemented_v4",
            }
        except Exception as exc:  # noqa: BLE001 - one bad session must not hide the rest
            outcome = {
                "session_id": session_id,
                "ok": False,
                "reason_code": f"driver_error:{type(exc).__name__}",
            }
        if not outcome.get("ok"):
            failures.append(session_id)
            print(f"SESSION-FAIL {session_id} kind={run_kind} "
                  f"reason={outcome.get('reason_code')}")
        else:
            print(f"SESSION-OK {session_id} kind={run_kind}")
            manifest["sessions"].append(outcome.get("session_row", {}))
            manifest["actions"].extend(outcome.get("action_rows", []))

    manifest_path = output / "benchmark" / "sessions.jsonl"
    with manifest_path.open("w", encoding="utf-8") as handle:
        for session in manifest["sessions"]:
            handle.write(json.dumps(session, ensure_ascii=False) + "\n")
    actions_path = output / "benchmark" / "actions.jsonl"
    with actions_path.open("w", encoding="utf-8") as handle:
        for action in manifest["actions"]:
            handle.write(json.dumps(action, ensure_ascii=False) + "\n")

    run_ended = _stamp()
    print(f"END started={run_started} ended={run_ended} "
          f"ok={len(planned) - len(failures)}/{len(planned)} "
          f"failures={','.join(failures) or '-'}")
    if failures:
        print("STATUS plan_incomplete")
        return EXIT_SESSION_FAILURE
    print("STATUS plan_complete")
    return EXIT_PLAN_COMPLETE


if __name__ == "__main__":
    raise SystemExit(main())
