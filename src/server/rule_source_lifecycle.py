"""Task-one read-only lifecycle seams for authoritative rule sources."""

from __future__ import annotations

import json
import re
import uuid

from .rules.authoritative_coc7 import (
    OFFICIAL_RULEBOOK_FILENAME,
    OFFICIAL_RULEBOOK_SHA256,
    _official_page_coverage,
)


def qualified_rule_version_predicate(version_sql: str) -> str:
    """Return the single runtime-eligibility predicate for a rule-version SQL expression.

    ``version_sql`` is always a static SQL column expression owned by the
    caller (never request input).  Keeping the gate in this predicate makes
    a published or explicitly selected legacy version fail closed.
    """
    return (
        "EXISTS ("
        "SELECT 1 "
        "FROM rule_set_versions AS qualified_rsv "
        "JOIN rule_sets AS qualified_rs "
        "ON qualified_rs.rule_set_id = qualified_rsv.rule_set_id "
        "JOIN rule_version_publication_gates AS qualified_gate "
        "ON qualified_gate.rule_set_version_id = qualified_rsv.rule_set_version_id "
        f"WHERE qualified_rsv.rule_set_version_id = {version_sql} "
        "AND qualified_rsv.status = 'published' "
        "AND qualified_rsv.runtime_eligible = TRUE "
        "AND qualified_rs.status = 'published' "
        "AND qualified_gate.status = 'ready'"
        ")"
    )


def is_runtime_qualified_rule_version(conn, rule_set_version_id: str) -> bool:
    """Return whether one version may be bound or used at runtime."""
    row = conn.execute(
        "SELECT 1 FROM rule_set_versions AS rsv "
        "WHERE rsv.rule_set_version_id = %s AND "
        + qualified_rule_version_predicate("rsv.rule_set_version_id"),
        (rule_set_version_id,),
    ).fetchone()
    return row is not None


def are_runtime_qualified_rule_sources(conn, sources: list[dict]) -> bool:
    """Fail closed unless every frozen rule-policy source remains qualified."""
    version_ids: list[str] = []
    for source in sources:
        if not isinstance(source, dict):
            return False
        rule_set_version_id = str(source.get("rule_set_version_id") or "").strip()
        if not rule_set_version_id:
            return False
        version_ids.append(rule_set_version_id)
    if not version_ids:
        return True
    rows = conn.execute(
        "SELECT rsv.rule_set_version_id "
        "FROM rule_set_versions AS rsv "
        "WHERE rsv.rule_set_version_id = ANY(%s) AND "
        + qualified_rule_version_predicate("rsv.rule_set_version_id"),
        (version_ids,),
    ).fetchall()
    return {str(row["rule_set_version_id"]) for row in rows} == set(version_ids)


def backfill_legacy_runtime_rule_publication_gates(conn) -> int:
    """Give pre-gate, runnable generic rules their one-time ready gate.

    Only already-published, already-runtime-eligible, non-official versions
    without a gate are eligible.  This preserves ordinary existing rules
    without turning a retired local fixture, a draft, or an official source
    into a runnable version.
    """
    with conn.transaction() as tx:
        inserted = tx.execute(
            """
            INSERT INTO rule_version_publication_gates (
                rule_set_version_id, status, diagnostics
            )
            SELECT rsv.rule_set_version_id, 'ready', '{}'::jsonb
            FROM rule_set_versions AS rsv
            JOIN rule_sets AS rs ON rs.rule_set_id = rsv.rule_set_id
            WHERE rsv.status = 'published'
              AND rsv.runtime_eligible = TRUE
              AND rs.status = 'published'
              AND NOT (rsv.metadata @> '{"local_test_only": true}'::jsonb)
              AND COALESCE(UPPER(rsv.source_sha256), '') <> %s
              AND NOT EXISTS (
                  SELECT 1
                  FROM rule_version_publication_gates AS gate
                  WHERE gate.rule_set_version_id = rsv.rule_set_version_id
              )
            ON CONFLICT (rule_set_version_id) DO NOTHING
            RETURNING rule_set_version_id
            """,
            (OFFICIAL_RULEBOOK_SHA256,),
        ).fetchall()
    return len(inserted)


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


class RuleSourceRetiredError(RuntimeError):
    """Raised when a room is retained for audit but no longer playable."""

    def __init__(self, reason: str | None = None):
        self.detail = {
            "code": "rule_source_retired",
            "reason": str(reason or "rule_source_retired"),
        }
        super().__init__(self.detail["code"])


def ensure_room_rule_source_available(conn, room_id: str) -> None:
    """Fail closed only for rooms explicitly retired by the rule-source lifecycle."""
    room = conn.execute(
        "SELECT rule_source_status, rule_source_reason FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    if room and room.get("rule_source_status") == "rule_source_retired":
        raise RuleSourceRetiredError(room.get("rule_source_reason"))


def normalize_room_adjudication_question(question: str) -> str:
    """Produce a stable, room-local lookup key without retaining raw prompt text."""
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(question or "").casefold())[:240]


def _safe_adjudication_state(minimal_state: object) -> dict[str, object]:
    if not isinstance(minimal_state, dict):
        return {}
    safe: dict[str, object] = {}
    for key in ("scene", "visible_fact", "visible_facts", "situation"):
        value = minimal_state.get(key)
        if isinstance(value, str) and value.strip():
            safe[key] = value.strip()[:500]
        elif key == "visible_facts" and isinstance(value, list):
            values = [item.strip()[:500] for item in value if isinstance(item, str) and item.strip()]
            if values:
                safe[key] = values[:8]
    return safe


def _safe_adjudication_summary(summary: object) -> str:
    return str(summary or "").strip()[:500]


def find_room_adjudication(conn, room_id: str, question: str) -> dict | None:
    """Return only the safe, reusable record for this room and action question."""
    question_key = normalize_room_adjudication_question(question)
    if not question_key:
        return None
    row = conn.execute(
        "SELECT question_key, summary, minimal_state FROM room_rule_adjudications "
        "WHERE room_id = %s AND question_key = %s",
        (room_id, question_key),
    ).fetchone()
    if not row:
        return None
    summary = _safe_adjudication_summary(row.get("summary"))
    if not summary:
        return None
    minimal_state = row.get("minimal_state")
    if isinstance(minimal_state, str):
        try:
            minimal_state = json.loads(minimal_state)
        except json.JSONDecodeError:
            minimal_state = {}
    return {
        "question_key": str(row.get("question_key") or question_key),
        "summary": summary,
        "minimal_state": _safe_adjudication_state(minimal_state),
    }


def upsert_room_adjudication(
    conn,
    room_id: str,
    question: str,
    summary: str,
    minimal_state: dict | None,
    rule_set_version_id: str | None = None,
) -> dict | None:
    """Persist the smallest safe room-local fallback, never the AI narrative."""
    question_key = normalize_room_adjudication_question(question)
    safe_summary = _safe_adjudication_summary(summary)
    if not question_key or not safe_summary:
        return None
    safe_state = _safe_adjudication_state(minimal_state)
    conn.execute(
        """
        INSERT INTO room_rule_adjudications (
            adjudication_id, room_id, question_key, summary, minimal_state, rule_set_version_id
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (room_id, question_key) DO UPDATE SET
            summary = EXCLUDED.summary,
            minimal_state = EXCLUDED.minimal_state,
            rule_set_version_id = EXCLUDED.rule_set_version_id,
            updated_at = NOW()
        """,
        (
            str(uuid.uuid4()),
            room_id,
            question_key,
            safe_summary,
            json.dumps(safe_state, ensure_ascii=False),
            rule_set_version_id,
        ),
    )
    return {
        "question_key": question_key,
        "summary": safe_summary,
        "minimal_state": safe_state,
    }


def retire_local_test_rule_versions(conn) -> dict[str, int]:
    """Quarantine only declared local-test rules and rooms that depend on them.

    This deliberately preserves the rule, source, chunk, and binding rows for
    administrator audit.  Runtime eligibility and the independent room source
    status are the only state changed here.
    """
    with conn.transaction() as tx:
        local_versions = tx.execute(
            "SELECT rule_set_version_id "
            "FROM rule_set_versions "
            "WHERE metadata @> %s::jsonb "
            "FOR UPDATE",
            ('{"local_test_only": true}',),
        ).fetchall()
        version_ids = [str(row["rule_set_version_id"]) for row in local_versions]
        if not version_ids:
            return {"retired_rule_versions": 0, "retired_rooms": 0}

        retired_versions = tx.execute(
            "UPDATE rule_set_versions "
            "SET runtime_eligible = FALSE "
            "WHERE rule_set_version_id = ANY(%s) "
            "AND runtime_eligible = TRUE "
            "RETURNING rule_set_version_id",
            (version_ids,),
        ).fetchall()
        retired_rooms = tx.execute(
            """
            UPDATE rooms AS room
            SET rule_source_status = 'rule_source_retired',
                rule_source_reason = 'local_test_rule_version'
            WHERE room.room_id IN (
                SELECT rrb.room_id
                FROM room_rule_bindings AS rrb
                WHERE rrb.rule_set_version_id = ANY(%s)
                UNION
                SELECT scenario_room.room_id
                FROM rooms AS scenario_room
                JOIN scenario_rule_bindings AS srb
                  ON srb.scenario_version_id = scenario_room.scenario_version_id
                WHERE srb.rule_set_version_id = ANY(%s)
                UNION
                SELECT legacy_room.room_id
                FROM rooms AS legacy_room
                JOIN scenarios AS scenario
                  ON scenario.scenario_id = legacy_room.scenario_id
                JOIN scenario_rule_bindings AS published_srb
                  ON published_srb.scenario_version_id = scenario.published_version_id
                WHERE legacy_room.scenario_version_id IS NULL
                  AND published_srb.rule_set_version_id = ANY(%s)
                UNION
                SELECT base_room.room_id
                FROM rooms AS base_room
                JOIN rule_set_versions AS base_rsv
                  ON base_rsv.rule_set_version_id = ANY(%s)
                JOIN rule_sets AS base_rs
                  ON base_rs.rule_set_id = base_rsv.rule_set_id
                WHERE base_room.scenario_version_id IS NULL
                  AND base_rs.system = 'coc7'
                  AND base_rs.is_base = TRUE
            )
              AND (
                room.rule_source_status IS DISTINCT FROM 'rule_source_retired'
                OR room.rule_source_reason IS DISTINCT FROM 'local_test_rule_version'
              )
            RETURNING room.room_id
            """,
            (version_ids, version_ids, version_ids, version_ids),
        ).fetchall()
    return {
        "retired_rule_versions": len(retired_versions),
        "retired_rooms": len(retired_rooms),
    }
