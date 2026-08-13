"""Validation and audit helpers for the one approved CoC7 rulebook source."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class RuleSourcePage:
    """Extracted text and audit state for one physical rulebook page."""

    page_number: int
    text: str
    extraction_status: str
    extraction_method: str
    diagnostics: dict = field(default_factory=dict)


def _canonical_rulebook_path() -> Path:
    repository_root = Path(__file__).resolve().parents[3]
    candidates = sorted((repository_root / "data").rglob(OFFICIAL_RULEBOOK_FILENAME))
    for candidate in candidates:
        try:
            validate_official_rulebook_path(candidate)
        except AuthoritativeRulebookError:
            continue
        return candidate
    raise AuthoritativeRulebookError("registered official rulebook was not found")


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


def _classify_page(text: str, page_number: int | None = None) -> str:
    """Archive only blank pages and page-shaped navigational material, never prose by keyword."""
    normalized = re.sub(r"\s+", "", text)
    if not normalized:
        return "archived_non_retrieval"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    toc_lines = [
        line
        for line in lines
        if re.search(r"(?:…|\.\.)\s*\d+\s*$", line)
        or re.search(r"\s\d+\s*$", line)
    ]
    navigation_heading = bool(lines) and lines[0] in {"目录", "索引", "版权"}
    if navigation_heading and len(lines) >= 2 and len(toc_lines) * 2 >= len(lines):
        return "archived_non_retrieval"
    return "indexable"


def _safe_extract_page_text(page, page_number: int) -> tuple[str, str, dict]:
    """Keep a physical-page audit record even when an individual extractor fails."""
    try:
        text = (page.extract_text() or "").strip()
    except Exception:
        return "", "needs_review", {"code": "extract_text_failed"}
    return text, _classify_page(text, page_number), {}


def load_authoritative_rulebook_pages() -> tuple[OfficialRulebookSpec, str, list[RuleSourcePage]]:
    """Resolve and extract only the fixed, locally registered source file."""
    source_path = _canonical_rulebook_path()
    spec = validate_official_rulebook_path(source_path)
    try:
        reader = PdfReader(str(source_path))
        pages = []
        for page_number, page in enumerate(reader.pages, start=1):
            text, extraction_status, diagnostics = _safe_extract_page_text(page, page_number)
            pages.append(
                RuleSourcePage(
                    page_number=page_number,
                    text=text,
                    extraction_status=extraction_status,
                    extraction_method="pypdf-extract-text",
                    diagnostics=diagnostics,
                )
            )
    except Exception as exc:
        raise AuthoritativeRulebookError(f"official rulebook extraction failed: {exc}") from exc
    if len(pages) != spec.page_count:
        raise AuthoritativeRulebookError(
            f"extracted page count mismatch: expected {spec.page_count}, got {len(pages)}"
        )
    return spec, str(source_path.relative_to(Path(__file__).resolve().parents[3])), pages


def _page_status_counts(conn, source_document_id: str) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT extraction_status, COUNT(*) AS count
        FROM rule_source_pages
        WHERE source_document_id = %s
        GROUP BY extraction_status
        """,
        (source_document_id,),
    ).fetchall()
    counts = {"indexable": 0, "archived_non_retrieval": 0, "needs_review": 0}
    for row in rows:
        counts[str(row["extraction_status"])] = int(row["count"])
    counts["total"] = sum(counts.values())
    return counts


def _official_page_coverage(conn, source_document_id: str) -> dict:
    """Return one shared, exact audit predicate for approval and runtime eligibility."""
    rows = conn.execute(
        """
        SELECT page_number, extraction_status
        FROM rule_source_pages
        WHERE source_document_id = %s
        ORDER BY page_number
        """,
        (source_document_id,),
    ).fetchall()
    expected_numbers = list(range(1, OFFICIAL_RULEBOOK_PAGE_COUNT + 1))
    page_numbers = [int(row["page_number"]) for row in rows]
    allowed_statuses = {"indexable", "archived_non_retrieval", "needs_review"}
    invalid_statuses = [
        str(row["extraction_status"])
        for row in rows
        if str(row["extraction_status"]) not in allowed_statuses
    ]
    needs_review = any(str(row["extraction_status"]) == "needs_review" for row in rows)
    source_part_rows = conn.execute(
        """
        SELECT page_number
        FROM source_parts
        WHERE source_document_id = %s
          AND part_kind = 'page'
        ORDER BY page_number
        """,
        (source_document_id,),
    ).fetchall()
    source_part_numbers = [int(row["page_number"]) for row in source_part_rows]
    return {
        "complete": page_numbers == expected_numbers,
        "source_parts_complete": source_part_numbers == expected_numbers,
        "valid_statuses": not invalid_statuses,
        "needs_review": needs_review,
    }


def _assert_official_page_coverage(conn, source_document_id: str) -> None:
    coverage = _official_page_coverage(conn, source_document_id)
    if not coverage["complete"]:
        raise AuthoritativeRulebookError("official source must cover physical pages 1 through 380 exactly")
    if not coverage["source_parts_complete"]:
        raise AuthoritativeRulebookError("official source is missing a physical page source part")
    if not coverage["valid_statuses"]:
        raise AuthoritativeRulebookError("official source has invalid page extraction status")
    if coverage["needs_review"]:
        raise AuthoritativeRulebookError("official source has pages marked needs_review")


def _linked_official_version(conn, source_document_id: str) -> dict | None:
    return conn.execute(
        """
        SELECT rsv.rule_set_version_id, rsv.source_sha256, gate.status AS gate_status
        FROM rule_set_versions AS rsv
        LEFT JOIN rule_version_publication_gates AS gate
          ON gate.rule_set_version_id = rsv.rule_set_version_id
        WHERE rsv.metadata ->> 'official_source_document_id' = %s
        ORDER BY rsv.version_number DESC
        LIMIT 1
        """,
        (source_document_id,),
    ).fetchone()


def import_authoritative_coc7(conn, rag, actor_id: str) -> dict:
    """Create a draft, page-auditable CoC7 version without publishing it."""
    spec, storage_path, pages = load_authoritative_rulebook_pages()
    if [page.page_number for page in pages] != list(range(1, spec.page_count + 1)):
        raise AuthoritativeRulebookError("official source pages must cover every physical page")
    allowed_statuses = {"indexable", "archived_non_retrieval", "needs_review"}
    if any(page.extraction_status not in allowed_statuses for page in pages):
        raise AuthoritativeRulebookError("official source has invalid page extraction status")

    existing_source = conn.execute(
        """
        SELECT source_document_id
        FROM source_documents
        WHERE source_kind = 'rulebook' AND source_sha256 = %s AND source_filename = %s
        """,
        (spec.sha256.lower(), spec.filename),
    ).fetchone()
    if existing_source:
        existing_version = _linked_official_version(conn, existing_source["source_document_id"])
        if existing_version:
            coverage = _official_page_coverage(conn, existing_source["source_document_id"])
            if not coverage["source_parts_complete"]:
                raise AuthoritativeRulebookError(
                    "existing official source import is missing a physical page source part"
                )
            if not coverage["complete"] or not coverage["valid_statuses"]:
                raise AuthoritativeRulebookError(
                    "existing official source import is incomplete or has invalid page status"
                )
            counts = _page_status_counts(conn, existing_source["source_document_id"])
            return {
                "source_document_id": existing_source["source_document_id"],
                "rule_set_version_id": existing_version["rule_set_version_id"],
                "source_sha256": spec.sha256,
                "page_count": counts["total"],
                "gate_status": existing_version.get("gate_status") or "pending_review",
            }

    source_document_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"coc7-source:{spec.sha256}"))
    rule_set_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "coc7-official-rule-set"))
    rule_set_version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"coc7-version:{spec.sha256}"))
    page_records = []
    with conn.transaction() as tx:
        tx.execute(
            """
            INSERT INTO source_documents (
                source_document_id, source_kind, title, source_filename, mime_type,
                source_sha256, storage_path, license_type, status, metadata, created_by
            ) VALUES (%s, 'rulebook', 'Call of Cthulhu 7th Edition Core Rules', %s,
                      'application/pdf', %s, %s, 'authorized', 'registered', %s, %s)
            ON CONFLICT (source_sha256, source_kind) DO NOTHING
            """,
            (
                source_document_id,
                spec.filename,
                spec.sha256.lower(),
                storage_path,
                json.dumps({"authoritative": True, "physical_page_count": spec.page_count}),
                actor_id,
            ),
        )
        source = tx.execute(
            """
            SELECT source_document_id
            FROM source_documents
            WHERE source_kind = 'rulebook' AND source_sha256 = %s AND source_filename = %s
            """,
            (spec.sha256.lower(), spec.filename),
        ).fetchone()
        if source is None:
            raise AuthoritativeRulebookError("official source registration failed")
        source_document_id = source["source_document_id"]

        tx.execute(
            """
            INSERT INTO rule_sets (
                rule_set_id, name, slug, system, description, is_base, license_type, status, created_by
            ) VALUES (%s, 'Call of Cthulhu 7th Edition Core Rules', 'official-coc7-core',
                      'coc7', 'Fixed authoritative CoC7 source.', TRUE, 'authorized', 'draft', %s)
            ON CONFLICT (slug) DO NOTHING
            """,
            (rule_set_id, actor_id),
        )
        rule_set = tx.execute(
            "SELECT rule_set_id FROM rule_sets WHERE slug = 'official-coc7-core'"
        ).fetchone()
        if rule_set is None:
            raise AuthoritativeRulebookError("official rule set registration failed")
        rule_set_id = rule_set["rule_set_id"]
        version = _linked_official_version(tx, source_document_id)
        if version:
            rule_set_version_id = version["rule_set_version_id"]
        else:
            next_version = tx.execute(
                "SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version "
                "FROM rule_set_versions WHERE rule_set_id = %s",
                (rule_set_id,),
            ).fetchone()["next_version"]
            tx.execute(
                """
                INSERT INTO rule_set_versions (
                    rule_set_version_id, rule_set_id, version_number, label, status,
                    source_sha256, metadata, created_by
                ) VALUES (%s, %s, %s, 'v1.2.1', 'draft', %s, %s, %s)
                """,
                (
                    rule_set_version_id,
                    rule_set_id,
                    next_version,
                    spec.sha256,
                    json.dumps({"official_source_document_id": source_document_id}),
                    actor_id,
                ),
            )
        for page in pages:
            source_part_id = str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"{source_document_id}:page:{page.page_number}")
            )
            text_sha256 = sha256(page.text.encode("utf-8")).hexdigest()
            tx.execute(
                """
                INSERT INTO source_parts (
                    source_part_id, source_document_id, ordinal, part_kind, page_number,
                    text_content, mime_type, anchor, checksum
                ) VALUES (%s, %s, %s, 'page', %s, %s, 'text/plain', %s, %s)
                ON CONFLICT (source_document_id, ordinal) DO NOTHING
                """,
                (
                    source_part_id,
                    source_document_id,
                    page.page_number,
                    page.page_number,
                    page.text,
                    json.dumps({"page_number": page.page_number}),
                    text_sha256,
                ),
            )
            source_part = tx.execute(
                "SELECT source_part_id FROM source_parts WHERE source_document_id = %s AND ordinal = %s",
                (source_document_id, page.page_number),
            ).fetchone()
            if source_part is None:
                raise AuthoritativeRulebookError("official page source part registration failed")
            page_records.append({
                "source_part_id": source_part["source_part_id"],
                "page_number": page.page_number,
                "text": page.text,
                "extraction_status": page.extraction_status,
            })
            tx.execute(
                """
                INSERT INTO rule_source_pages (
                    rule_source_page_id, source_document_id, page_number, extraction_status,
                    text_sha256, extraction_method, diagnostics
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_document_id, page_number) DO NOTHING
                """,
                (
                    str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source_document_id}:rule-page:{page.page_number}")),
                    source_document_id,
                    page.page_number,
                    page.extraction_status,
                    text_sha256,
                    page.extraction_method,
                    json.dumps(page.diagnostics),
                ),
            )
        counts = _page_status_counts(tx, source_document_id)
        gate_status = "pending_review"
        tx.execute(
            """
            INSERT INTO rule_version_publication_gates (rule_set_version_id, status, diagnostics)
            VALUES (%s, %s, %s)
            ON CONFLICT (rule_set_version_id) DO UPDATE
            SET status = EXCLUDED.status, diagnostics = EXCLUDED.diagnostics, updated_at = NOW()
            """,
            (rule_set_version_id, gate_status, json.dumps({"pages": counts})),
        )

    try:
        rag.index_rule_pages(source_document_id, rule_set_version_id, page_records)
    except Exception:
        with conn.transaction() as tx:
            tx.execute(
                "DELETE FROM document_chunks WHERE rule_set_version_id = %s",
                (rule_set_version_id,),
            )
            tx.execute(
                "DELETE FROM rule_source_pages WHERE source_document_id = %s",
                (source_document_id,),
            )
            tx.execute(
                "DELETE FROM source_parts WHERE source_document_id = %s",
                (source_document_id,),
            )
            tx.execute(
                "DELETE FROM rule_version_publication_gates WHERE rule_set_version_id = %s",
                (rule_set_version_id,),
            )
            tx.execute(
                "DELETE FROM rule_set_versions WHERE rule_set_version_id = %s",
                (rule_set_version_id,),
            )
            tx.execute(
                "DELETE FROM source_documents WHERE source_document_id = %s",
                (source_document_id,),
            )
        raise
    return {
        "source_document_id": source_document_id,
        "rule_set_version_id": rule_set_version_id,
        "source_sha256": spec.sha256,
        "page_count": spec.page_count,
        "gate_status": gate_status,
    }


def get_rule_version_audit(conn, rule_set_version_id: str) -> dict:
    """Return only administrator audit metadata for a linked official version."""
    row = conn.execute(
        """
        SELECT rsv.rule_set_version_id, rsv.status AS version_status, rsv.runtime_eligible,
               sd.source_document_id, sd.source_filename, sd.source_sha256,
               gate.status AS gate_status, gate.diagnostics AS gate_diagnostics
        FROM rule_set_versions AS rsv
        JOIN source_documents AS sd
          ON sd.source_document_id = rsv.metadata ->> 'official_source_document_id'
        LEFT JOIN rule_version_publication_gates AS gate
          ON gate.rule_set_version_id = rsv.rule_set_version_id
        WHERE rsv.rule_set_version_id = %s
          AND sd.source_filename = %s
          AND UPPER(sd.source_sha256) = %s
          AND UPPER(rsv.source_sha256) = %s
        """,
        (rule_set_version_id, OFFICIAL_RULEBOOK_FILENAME, OFFICIAL_RULEBOOK_SHA256, OFFICIAL_RULEBOOK_SHA256),
    ).fetchone()
    if row is None:
        raise AuthoritativeRulebookError("authoritative rule version not found")
    counts = _page_status_counts(conn, row["source_document_id"])
    review_rows = conn.execute(
        """
        SELECT rsp.page_number, rsp.extraction_status, sp.text_content
        FROM rule_source_pages AS rsp
        JOIN source_parts AS sp
          ON sp.source_document_id = rsp.source_document_id
         AND sp.page_number = rsp.page_number
        WHERE rsp.source_document_id = %s
          AND rsp.extraction_status IN ('needs_review', 'archived_non_retrieval')
        ORDER BY rsp.page_number
        LIMIT 50
        """,
        (row["source_document_id"],),
    ).fetchall()
    review_entries = [
        {
            "page_number": int(review_row["page_number"]),
            "extraction_status": review_row["extraction_status"],
            "excerpt": str(review_row.get("text_content") or "")[:240],
        }
        for review_row in review_rows
    ]
    return {
        "rule_set_version_id": row["rule_set_version_id"],
        "version_status": row["version_status"],
        "runtime_eligible": bool(row["runtime_eligible"]),
        "source": {
            "document_id": row["source_document_id"],
            "filename": row["source_filename"],
            "sha256": str(row["source_sha256"]).upper(),
        },
        "pages": counts,
        "gate": {"status": row.get("gate_status") or "pending_review", "diagnostics": row.get("gate_diagnostics") or {}},
        "review_entries": review_entries,
    }


def approve_rule_source_review(conn, rule_set_version_id: str, actor_id: str) -> dict:
    """Mark a complete official source ready for publication, never publish it."""
    audit = get_rule_version_audit(conn, rule_set_version_id)
    _assert_official_page_coverage(conn, audit["source"]["document_id"])
    counts = audit["pages"]
    with conn.transaction() as tx:
        tx.execute(
            """
            UPDATE rule_version_publication_gates
            SET status = 'ready', reviewed_by = %s, reviewed_at = NOW(),
                diagnostics = %s, updated_at = NOW()
            WHERE rule_set_version_id = %s
            """,
            (actor_id, json.dumps({"pages": counts}), rule_set_version_id),
        )
    return get_rule_version_audit(conn, rule_set_version_id)


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
