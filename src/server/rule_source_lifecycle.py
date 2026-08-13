"""Task-one read-only lifecycle seams for authoritative rule sources."""

from __future__ import annotations

from .rules.authoritative_coc7 import (
    OFFICIAL_RULEBOOK_FILENAME,
    OFFICIAL_RULEBOOK_SHA256,
    _official_page_coverage,
)


def current_authoritative_base_version(conn) -> str | None:
    """Return the currently eligible fixed-source CoC7 base version, if one exists."""
    rows = conn.execute(
        """
        SELECT rsv.rule_set_version_id
        FROM rule_set_versions AS rsv
        JOIN rule_sets AS rs ON rs.rule_set_id = rsv.rule_set_id
        JOIN source_documents AS sd
          ON sd.source_document_id = rsv.metadata ->> 'official_source_document_id'
        JOIN rule_version_publication_gates AS gate
          ON gate.rule_set_version_id = rsv.rule_set_version_id
        WHERE rs.system = 'coc7'
          AND rs.is_base = TRUE
          AND rs.status = 'published'
          AND rsv.status = 'published'
          AND rsv.runtime_eligible = TRUE
          AND UPPER(rsv.source_sha256) = %s
          AND sd.source_filename = %s
          AND UPPER(sd.source_sha256) = %s
          AND gate.status = 'ready'
        ORDER BY rsv.version_number DESC
        """,
        (
            OFFICIAL_RULEBOOK_SHA256,
            OFFICIAL_RULEBOOK_FILENAME,
            OFFICIAL_RULEBOOK_SHA256,
        ),
    ).fetchall()
    for row in rows:
        source = conn.execute(
            """
            SELECT source_document_id
            FROM source_documents
            WHERE source_filename = %s AND UPPER(source_sha256) = %s
              AND source_document_id = (
                  SELECT rsv.metadata ->> 'official_source_document_id'
                  FROM rule_set_versions AS rsv
                  WHERE rsv.rule_set_version_id = %s
              )
            """,
            (OFFICIAL_RULEBOOK_FILENAME, OFFICIAL_RULEBOOK_SHA256, row["rule_set_version_id"]),
        ).fetchone()
        if source:
            coverage = _official_page_coverage(conn, source["source_document_id"])
            if coverage["complete"] and coverage["valid_statuses"] and not coverage["needs_review"]:
                return row["rule_set_version_id"]
    return None


def ensure_room_rule_source_available(conn, room_id: str) -> None:
    """Reserve a shared room-source check without altering room access in Task 1."""
    conn.execute("SELECT room_id FROM rooms WHERE room_id = %s", (room_id,)).fetchone()


def retire_local_test_rule_versions(conn) -> dict[str, int]:
    """Task 1 deliberately leaves existing versions and rooms untouched."""
    return {"retired_rule_versions": 0, "retired_rooms": 0}
