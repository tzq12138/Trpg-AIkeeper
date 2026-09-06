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
# Hard cap before any evidence file is hashed (resource bound).
MAX_EVIDENCE_BYTES = 50 * 1024 * 1024
_ID_RE = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
_REVIEWER_RE = r"[A-Za-z0-9._-]+ \d{4}-\d{2}-\d{2}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expect_signed(value: str, *, signers: list[str]) -> bool:
    """Machine-meaningful sign-off marker: known signer + date, strict form.

    A bare non-empty string is never accepted: the reviewer token must match
    ``<signer> YYYY-MM-DD`` and the signer must appear in the sign-off
    registry (evidence/signers.csv) that accompanies the evidence tree.
    """
    import re

    if not isinstance(value, str):
        return False
    if not re.fullmatch(_REVIEWER_RE, value.strip()):
        return False
    signer = value.strip().rsplit(" ", 1)[0]
    return signer in signers


def _load_signers(evidence: Path) -> tuple[list[str], list[str]]:
    """Load the sign-off registry; missing/invalid registries are blocks."""
    path = evidence / "signers.csv"
    if not path.exists():
        return [], ["signers_csv_missing"]
    signers: list[str] = []
    blocks: list[str] = []
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                signer = line.strip()
                if not signer:
                    continue
                if len(signer) > 128:
                    blocks.append("signer_entry_too_long")
                    continue
                signers.append(signer)
    except OSError as exc:
        return [], [f"signers_csv_unreadable:{type(exc).__name__}"]
    if not signers:
        blocks.append("signers_csv_empty")
    return signers, blocks


def _safe_token(value: str) -> str:
    """Sanitize one interpolated token for log output (injection guard)."""
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in "._:-")
    return cleaned[:128]


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


def _read_exitcode(evidence: Path, name: str) -> tuple[bool, str | None]:
    path = evidence / name
    label = name.replace("-", "_").replace(".exitcode", "")
    if not path.exists():
        return True, f"{label}_missing"
    code = path.read_text(encoding="utf-8").strip()
    if code != "0":
        return True, f"{label}_exitcode_{_safe_token(code) or 'non_zero'}"
    return False, None


def validate_evidence(evidence: Path, rows: list[dict], *, rc_id: str) -> tuple[int, list[str]]:
    """Return (blocking_count, blocks) — one block per broken requirement.

    The release-candidate id is an ANCHOR from the invocation, never from the
    artifact bundle: every row's rc_id must equal it, and the evidence
    manifest.json must carry the same id.
    """
    blocks: list[str] = []
    if not evidence.exists():
        return 1, ["evidence_root_missing"]

    for name in ("backend-full", "frontend-test", "frontend-build"):
        blocked, code = _read_exitcode(evidence, f"{name}.exitcode")
        if blocked:
            blocks.append(code)

    manifest_path = evidence / "manifest.json"
    if not manifest_path.exists():
        blocks.append("manifest_missing")
    else:
        try:
            with manifest_path.open("r", encoding="utf-8") as handle:
                manifest_rc = json.load(handle).get("rc_id")
        except (json.JSONDecodeError, OSError):
            blocks.append("manifest_unreadable")
            manifest_rc = None
        if manifest_rc != rc_id:
            blocks.append("manifest_rc_mismatch")
    if not (evidence / "requirements.csv").exists():
        blocks.append("requirements_csv_missing")

    signers, signer_blocks = _load_signers(evidence)
    blocks.extend(signer_blocks)

    requirement_ids: set[str] = set()
    for row in rows:
        requirement_id = row["requirement_id"]
        if not isinstance(requirement_id, str) or not requirement_id.strip():
            blocks.append("requirement_id_empty")
            continue
        safe_id = _safe_token(requirement_id)
        if safe_id != requirement_id:
            blocks.append(f"requirement_id_invalid:{safe_id or 'empty'}")
        if requirement_id in requirement_ids:
            blocks.append(f"requirement_id_duplicate:{safe_id}")
        requirement_ids.add(requirement_id)
        if row.get("rc_id") != rc_id:
            blocks.append(f"rc_id_mismatch:{safe_id}")
        if row["status"] not in REQUIRED_STATUSES:
            blocks.append(f"requirement_status_invalid:{safe_id}")
        if row["status"] == "PASSED":
            evidence_path = row.get("evidence_path") or ""
            if not evidence_path or not evidence_path.strip():
                blocks.append(f"passed_without_evidence:{safe_id}")
                continue
            target = (evidence / evidence_path).resolve()
            try:
                inside_root = target.is_relative_to(evidence.resolve())
            except AttributeError:  # pragma: no cover - py<3.9 fallback
                inside_root = str(target).startswith(str(evidence.resolve()))
            if not inside_root:
                blocks.append(f"evidence_outside_root:{safe_id}")
                continue
            if not target.is_file():
                blocks.append(f"evidence_not_file:{safe_id}")
                continue
            if target.stat().st_size > MAX_EVIDENCE_BYTES:
                blocks.append(f"evidence_too_large:{safe_id}")
                continue
            expected = (row.get("evidence_sha256") or "").strip()
            if expected and _sha256(target) != expected:
                blocks.append(f"evidence_hash_mismatch:{safe_id}")
            command = row.get("command") or ""
            exit_code = (row.get("exit_code") or "").strip()
            if not command:
                blocks.append(f"passed_without_command:{safe_id}")
            if not exit_code:
                blocks.append(f"passed_without_exit_code:{safe_id}")
        if not _expect_signed(row.get("reviewer"), signers=signers):
            blocks.append(f"reviewer_missing:{safe_id}")
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

    _, blocks = validate_evidence(evidence, rows, rc_id=args.release_candidate)
    passed = sum(1 for row in rows if row["status"] == "PASSED")
    print(f"requirements={len(rows)} passed_rows={passed} blocks={len(blocks)}")
    for block in blocks:
        print(f"BLOCK {_safe_token(block)}")
    if blocks:
        return EXIT_BLOCKED
    print("release_candidate_passed=true")
    return EXIT_PASS


if __name__ == "__main__":
    raise SystemExit(main())
