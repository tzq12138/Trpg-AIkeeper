"""V5 — acceptance validator contract tests (never part of a real RC).

Each failing input produces an independent blocking result: a machine must
never copy an aggregator boolean or hand-write PASSED rows.
"""

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "run_ai_only_acceptance.py"


def _run_validator(evidence: Path, rc: str = "rc-20260905-01"):
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--release-candidate", rc, "--evidence", str(evidence)],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(REPO_ROOT),
    )


def _write_requirements(root: Path, rows: list[dict]) -> None:
    fields = [
        "requirement_id", "decision_id", "status", "minimum_level",
        "test_selector", "command", "exit_code", "trace_ids",
        "evidence_path", "evidence_sha256", "rc_id", "reviewer",
    ]
    with (root / "requirements.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _evidence_tree(tmp_path: Path, *, requirement_count: int = 123,
                   evidence_file: bool = True) -> Path:
    root = tmp_path / "evidence"
    root.mkdir(parents=True, exist_ok=True)
    (root / "backend-full.exitcode").write_text("0", encoding="utf-8")
    (root / "frontend-test.exitcode").write_text("0", encoding="utf-8")
    (root / "frontend-build.exitcode").write_text("0", encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps({"rc_id": "rc-20260905-01", "release_candidate_passed": True}),
        encoding="utf-8",
    )
    rows = []
    for index in range(1, requirement_count + 1):
        row: dict = {
            "requirement_id": f"AIO-{index:03d}",
            "decision_id": f"D{index:02d}",
            "status": "PASSED",
            "minimum_level": "M0",
            "test_selector": f"tests/server/test_x.py::test_{index}",
            "command": f"pytest -q tests/server/test_x.py -k test_{index}",
            "exit_code": "0",
            "trace_ids": "",
            "evidence_path": "backend-full.exitcode",
            "evidence_sha256": "",
            "rc_id": "rc-20260905-01",
            "reviewer": "qa-signer 2026-09-06",
        }
        rows.append(row)
    _write_requirements(root, rows)
    if evidence_file:
        (root / "backend-full.exitcode").write_text("0", encoding="utf-8")
    return root


def _sha256_of(path: Path) -> str:
    return hashlib_sha256(path)


def hashlib_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_valid_evidence_passes(tmp_path):
    root = _evidence_tree(tmp_path)
    result = _run_validator(root)
    assert result.returncode == 0, result.stdout
    assert "release_candidate_passed=true" in result.stdout


def test_fewer_than_123_unique_ids_blocks(tmp_path):
    root = _evidence_tree(tmp_path, requirement_count=122)
    result = _run_validator(root)
    assert result.returncode == 1, result.stdout
    assert "requirements_below_123:122" in result.stdout


def test_duplicate_ids_do_not_fake_123(tmp_path):
    root = _evidence_tree(tmp_path, requirement_count=123)
    rows = []
    with (root / "requirements.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows.append(row)
    rows[0]["requirement_id"] = "AIO-002"  # duplicate
    _write_requirements(root, rows)
    result = _run_validator(root)
    assert result.returncode == 1
    assert "requirement_id_duplicate:AIO-002" in result.stdout
    assert "requirements_below_123" in result.stdout


def test_passed_row_without_evidence_blocks(tmp_path):
    root = _evidence_tree(tmp_path)
    rows = []
    with (root / "requirements.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows.append(row)
    rows[0]["evidence_path"] = ""
    _write_requirements(root, rows)
    result = _run_validator(root)
    assert result.returncode == 1
    assert "passed_without_evidence:AIO-001" in result.stdout


def test_evidence_hash_mismatch_blocks(tmp_path):
    root = _evidence_tree(tmp_path)
    rows = []
    with (root / "requirements.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows.append(row)
    rows[0]["evidence_sha256"] = "0" * 64
    _write_requirements(root, rows)
    result = _run_validator(root)
    assert result.returncode == 1
    assert "evidence_hash_mismatch:AIO-001" in result.stdout


def test_backend_full_failure_blocks_even_with_pass_rows(tmp_path):
    root = _evidence_tree(tmp_path)
    (root / "backend-full.exitcode").write_text("1", encoding="utf-8")
    result = _run_validator(root)
    assert result.returncode == 1
    assert "backend_full_exitcode_1" in result.stdout


def test_missing_reviewer_blocks(tmp_path):
    root = _evidence_tree(tmp_path)
    rows = []
    with (root / "requirements.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows.append(row)
    rows[0]["reviewer"] = ""
    _write_requirements(root, rows)
    result = _run_validator(root)
    assert result.returncode == 1
    assert "reviewer_missing:AIO-001" in result.stdout


def test_evidence_root_missing_is_input_error(tmp_path):
    result = _run_validator(tmp_path / "no-such-evidence")
    assert result.returncode == 1
    assert "evidence_root_missing" in result.stdout
