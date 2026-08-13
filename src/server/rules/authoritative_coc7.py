"""Validation and audit helpers for the one approved CoC7 rulebook source."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from pypdf import PdfReader


OFFICIAL_RULEBOOK_FILENAME = "COC7th核心规则书v1.2.1.pdf"
OFFICIAL_RULEBOOK_PAGE_COUNT = 380
OFFICIAL_RULEBOOK_SHA256 = (
    "22F5F56B7A0989CBDED695D39C7D5EDDDDD809CFC9D2C47E4CF4C5D7EDEA6815"
)


class AuthoritativeRulebookError(ValueError):
    """Raised when a source cannot be proved to be the approved rulebook."""


@dataclass(frozen=True)
class OfficialRulebookSpec:
    filename: str
    page_count: int
    sha256: str


def validate_official_rulebook_path(path: Path) -> OfficialRulebookSpec:
    """Return the fixed source spec only when *path* matches every identifier."""
    if not path.is_file():
        raise AuthoritativeRulebookError(f"official rulebook not found: {path}")
    actual_sha256 = sha256(path.read_bytes()).hexdigest().upper()
    if actual_sha256 != OFFICIAL_RULEBOOK_SHA256:
        raise AuthoritativeRulebookError(
            f"sha256 mismatch: expected {OFFICIAL_RULEBOOK_SHA256}, got {actual_sha256}"
        )
    if path.name != OFFICIAL_RULEBOOK_FILENAME:
        raise AuthoritativeRulebookError(
            f"filename must be {OFFICIAL_RULEBOOK_FILENAME}, got {path.name}"
        )

    try:
        page_count = len(PdfReader(str(path)).pages)
    except Exception as exc:  # pypdf normalizes several malformed-PDF errors.
        raise AuthoritativeRulebookError(f"page_count could not be read: {exc}") from exc
    if page_count != OFFICIAL_RULEBOOK_PAGE_COUNT:
        raise AuthoritativeRulebookError(
            f"page_count mismatch: expected {OFFICIAL_RULEBOOK_PAGE_COUNT}, got {page_count}"
        )

    return OfficialRulebookSpec(
        filename=OFFICIAL_RULEBOOK_FILENAME,
        page_count=OFFICIAL_RULEBOOK_PAGE_COUNT,
        sha256=OFFICIAL_RULEBOOK_SHA256,
    )


def authoritative_gate_snapshot(conn, rule_set_version_id: str) -> dict:
    """Read the configured publication gate without changing version state."""
    row = conn.execute(
        """
        SELECT
            rsv.rule_set_version_id,
            rsv.status AS version_status,
            rsv.runtime_eligible,
            rsv.source_sha256,
            gate.status AS gate_status,
            gate.diagnostics AS gate_diagnostics
        FROM rule_set_versions AS rsv
        LEFT JOIN rule_version_publication_gates AS gate
          ON gate.rule_set_version_id = rsv.rule_set_version_id
        WHERE rsv.rule_set_version_id = %s
        """,
        (rule_set_version_id,),
    ).fetchone()
    if row is None:
        raise AuthoritativeRulebookError(
            f"rule set version not found: {rule_set_version_id}"
        )
    return dict(row)
