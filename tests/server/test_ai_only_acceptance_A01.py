"""A01 regression — all-failed / all-blocked mappings must never pass the RC."""

import csv

from tests.server.test_ai_only_acceptance import _evidence_tree, _run_validator, _write_requirements


def _load_rows(root):
    with (root / "requirements.csv").open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _all_status(tree, status):
    rows = []
    with (tree / "requirements.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            row["status"] = status
            rows.append(row)
    _write_requirements(tree, rows)


def test_all_failed_rows_never_report_release_candidate_passed(tmp_path):
    """A01: a mapping whose 123 rows are all FAILED must block — the validator
    must never print release_candidate_passed=true for zero passed rows."""
    root = _evidence_tree(tmp_path)
    _all_status(root, "FAILED")
    result = _run_validator(root)
    assert result.returncode == 1, result.stdout
    assert "zero_passed_rows" in result.stdout
    assert "release_candidate_passed=true" not in result.stdout


def test_all_blocked_rows_never_report_release_candidate_passed(tmp_path):
    """A01: all-BLOCKED rows are equally not a passing mapping."""
    root = _evidence_tree(tmp_path)
    _all_status(root, "BLOCKED")
    result = _run_validator(root)
    assert result.returncode == 1, result.stdout
    assert "zero_passed_rows" in result.stdout
    assert "release_candidate_passed=true" not in result.stdout


def test_blocker_level_requirement_must_be_passed(tmp_path):
    """A01: a requirement whose minimum_level is 'blocker' may not be FAILED
    or BLOCKED in a passing release candidate."""
    root = _evidence_tree(tmp_path)
    rows = _load_rows(root)
    rows[0]["minimum_level"] = "blocker"
    rows[0]["status"] = "FAILED"
    _write_requirements(root, rows)
    result = _run_validator(root)
    assert result.returncode == 1, result.stdout
    assert "blocker_not_passed:AIO-001" in result.stdout
    assert "release_candidate_passed=true" not in result.stdout


def test_single_passed_row_with_rest_blocked_is_still_blocked(tmp_path):
    """A01 edge: one PASSED row among 122 BLOCKED rows still fails — PASSED
    rows need their own machine-checked evidence, and the failed majority
    keeps the mapping red."""
    root = _evidence_tree(tmp_path)
    _all_status(root, "BLOCKED")
    rows = _load_rows(root)
    rows[0]["status"] = "PASSED"
    _write_requirements(root, rows)
    result = _run_validator(root)
    assert result.returncode == 1, result.stdout
    assert "release_candidate_passed=true" not in result.stdout


def test_zero_passed_is_reported_but_not_double_counted(tmp_path):
    """A01: zero passed rows produces exactly the zero_passed_rows marker and
    never a fake release_candidate_passed=true (injection guard parity)."""
    root = _evidence_tree(tmp_path)
    _all_status(root, "FAILED")
    result = _run_validator(root)
    assert "zero_passed_rows" in result.stdout
    # No duplicate block line, no spoofed success.
    assert result.stdout.count("zero_passed_rows") == 1
    assert "release_candidate_passed=true" not in result.stdout
