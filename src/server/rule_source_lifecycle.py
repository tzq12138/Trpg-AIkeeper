"""Task-one read-only lifecycle seams for authoritative rule sources."""

from __future__ import annotations

from .rules.authoritative_coc7 import OFFICIAL_RULEBOOK_SHA256


def current_authoritative_base_version(conn) -> str | None:
    """Return the currently eligible fixed-source CoC7 base version, if one exists."""
    row = conn.execute(
        """
        SELECT rsv.rule_set_version_id
        FROM rule_set_versions AS rsv
        JOIN rule_sets AS rs ON rs.rule_set_id = rsv.rule_set_id
        WHERE rs.system = 'coc7'
          AND rs.is_base = TRUE
          AND rs.status = 'published'
          AND rsv.status = 'published'
          AND rsv.runtime_eligible = TRUE
          AND UPPER(rsv.source_sha256) = %s
        ORDER BY rsv.version_number DESC
        LIMIT 1
        """,
        (OFFICIAL_RULEBOOK_SHA256,),
    ).fetchone()
    return row["rule_set_version_id"] if row else None


def ensure_room_rule_source_available(conn, room_id: str) -> None:
    """Reserve a shared room-source check without altering room access in Task 1."""
    conn.execute("SELECT room_id FROM rooms WHERE room_id = %s", (room_id,)).fetchone()


def retire_local_test_rule_versions(conn) -> dict[str, int]:
    """Task 1 deliberately leaves existing versions and rooms untouched."""
    return {"retired_rule_versions": 0, "retired_rooms": 0}
