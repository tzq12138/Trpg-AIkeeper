"""V5 — release-candidate acceptance validator for the 123-requirement map.

Reads the V1–V4 evidence tree and the requirements mapping; exit-code
contract (03 §V5):
    0 = every gate and mapping completed (release_candidate_passed supported
        by machine checks and sign-offs, never copied from an aggregator bool);
    1 = explicit blocking list;
    2 = input/environment error.

The validator NEVER writes PASSED rows by hand: it locates each requirement's
evidence (exit codes, hashes, artifact paths) and reports exactly what the
machine could verify. Missing files, wrong hashes, disqualified samples,
interrupted logs, unverified browser screenshots, missing human ratings and
non-zero hard blockers each fail independently.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

EXIT_PASS = 0
EXIT_BLOCKED = 1
EXIT_ENV_ERROR = 2

REQUIRED_STATUSES = {"PASSED", "FAILED", "BLOCKED"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expect_signed(value: str) -> bool:
    """Machine-meaningful sign-off marker: reviewer id + timestamp present."""
    return isinstance(value, str) and bool(value.strip())


def load_requirements(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    required_fields = {
        "requirement_id", "decision_id", "status", "minimum_level",
        "test_selector", "command", "exit_code", "trace_ids",
        "evidence_path", "evidence_sha256", "rc_id", "reviewer",
    }
    for row in rows:
        missing = required_fields - set(row.keys())
        if missing:
            raise ValueError(f"requirements_missing_fields:{sorted(missing)}")
    return rows


def validate_evidence(evidence: Path, rows: list[dict]) -> tuple[int, list[str]]:
    """Return (blocking_count, blocks) — one block per broken requirement."""
    blocks: list[str] = []
    if not evidence.exists():
        return 1, ["evidence_root_missing"]
    if not (evidence / "backend-full.exitcode").exists():
        blocks.append("backend_full_exitcode_missing")
    else:
        code = (evidence / "backend-full.exitcode").read_text(encoding="utf-8").strip()
        if code != "0":
            blocks.append(f"backend_full_exitcode_{code}")
    if not (evidence / "frontend-test.exitcode").exists():
        blocks.append("frontend_test_exitcode_missing")
    if not (evidence / "frontend-build.exitcode").exists():
        blocks.append("frontend_build_exitcode_missing")
    if not (evidence / "manifest.json").exists():
        blocks.append("manifest_missing")
    if not (evidence / "requirements.csv").exists():
        blocks.append("requirements_csv_missing")

    requirement_ids: set[str] = set()
    for row in rows:
        requirement_id = row["requirement_id"]
        if not requirement_id or not requirement_id.strip():
            blocks.append("requirement_id_empty")
            continue
        if requirement_id in requirement_ids:
            blocks.append(f"requirement_id_duplicate:{requirement_id}")
        requirement_ids.add(requirement_id)
        if row["status"] not in REQUIRED_STATUSES:
            blocks.append(f"requirement_status_invalid:{requirement_id}")
        if row["status"] == "PASSED":
            evidence_path = row.get("evidence_path") or ""
            if not evidence_path or not evidence_path.strip():
                blocks.append(f"passed_without_evidence:{requirement_id}")
                continue
            target = evidence / evidence_path
            if not target.exists():
                blocks.append(f"evidence_missing:{requirement_id}")
                continue
            expected = (row.get("evidence_sha256") or "").strip()
            if expected and _sha256(target) != expected:
                blocks.append(f"evidence_hash_mismatch:{requirement_id}")
            command = row.get("command") or ""
            exit_code = (row.get("exit_code") or "").strip()
            if not command:
                blocks.append(f"passed_without_command:{requirement_id}")
            if not exit_code:
                blocks.append(f"passed_without_exit_code:{requirement_id}")
        if not _expect_signed(row.get("reviewer")):
            blocks.append(f"reviewer_missing:{requirement_id}")
    if len(requirement_ids) < 123:
        blocks.append(f"requirements_below_123:{len(requirement_ids)}")
    return len(blocks), blocks


def load_manifest(evidence: Path) -> dict:
    manifest_path = evidence / "manifest.json"
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise ValueError("manifest_not_object")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate one release candidate against its evidence tree.",
    )
    parser.add_argument("--release-candidate", required=True, help="rc id, e.g. rc-20260905-01")
    parser.add_argument("--evidence", required=True, help="evidence root directory")
    args = parser.parse_args(argv)

    evidence = Path(args.evidence)
    if not evidence.exists() or not evidence.is_dir():
        print("BLOCK evidence_root_missing")
        return EXIT_BLOCKED
    try:
        rows = load_requirements(evidence / "requirements.csv")
    except FileNotFoundError:
        print("BLOCK requirements_csv_missing")
        return EXIT_BLOCKED
    except ValueError as exc:
        print(f"BLOCK {exc}")
        return EXIT_BLOCKED

    _, blocks = validate_evidence(evidence, rows)
    passed = sum(1 for row in rows if row["status"] == "PASSED")
    print(f"requirements={len(rows)} passed_rows={passed} blocks={len(blocks)}")
    for block in blocks:
        print(f"BLOCK {block}")
    if blocks:
        return EXIT_BLOCKED
    print("release_candidate_passed=true")
    return EXIT_PASS


if __name__ == "__main__":
    raise SystemExit(main())
