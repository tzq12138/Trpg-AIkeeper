import os
import re

import psycopg2
import pytest

from src.server.db_adapter import PgDatabase as AdapterPgDatabase
from src.server.db_pg import PgDatabase as LegacyPgDatabase
from tests.server.conftest import _DEFAULT_TEST_DB, _ensure_test_db_exists, _validate_test_db_url


def _variant_dsn(base_dsn: str, suffix: str) -> str:
    match = re.search(r"/([^/?]+)(\?|$)", base_dsn)
    if not match:
        raise RuntimeError(f"Unexpected PostgreSQL DSN: {base_dsn}")
    dbname = match.group(1)
    return f"{base_dsn[:match.start(1)]}{dbname}_{suffix}{base_dsn[match.end(1):]}"


@pytest.fixture(params=[
    ("adapter", AdapterPgDatabase),
    ("legacy", LegacyPgDatabase),
])
def initialized_db(request):
    base_dsn = _validate_test_db_url(os.getenv("TEST_DATABASE_URL", _DEFAULT_TEST_DB))
    dsn = _variant_dsn(base_dsn, f"scenario_versioning_{request.param[0]}")
    _ensure_test_db_exists(dsn)
    db = request.param[1](dsn=dsn)
    try:
        db.connect()
    except psycopg2.Error:
        pytest.skip("PostgreSQL not available")
    db.initialize()
    db.initialize()
    yield db
    db.close()


def _fetch_columns(db, table_name: str) -> dict[str, dict]:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable, column_default, udt_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
                """,
                (table_name,),
            )
            rows = cur.fetchall()
    return {row["column_name"]: row for row in rows}


def _fetch_constraints(db, table_name: str, constraint_type: str) -> list[tuple[str, ...]]:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT array_agg(kcu.column_name ORDER BY kcu.ordinal_position) AS columns
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = 'public'
                  AND tc.table_name = %s
                  AND tc.constraint_type = %s
                GROUP BY tc.constraint_name
                ORDER BY tc.constraint_name
                """,
                (table_name, constraint_type),
            )
            rows = cur.fetchall()
    normalized = []
    for row in rows:
        columns = row["columns"]
        if isinstance(columns, str):
            columns = tuple(part for part in columns.strip("{}").split(",") if part)
        else:
            columns = tuple(columns)
        normalized.append(columns)
    return normalized


def _fetch_foreign_keys(db, table_name: str) -> set[tuple[str, str, str]]:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT kcu.column_name, ccu.table_name AS foreign_table_name, ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON tc.constraint_name = ccu.constraint_name
                 AND tc.table_schema = ccu.table_schema
                WHERE tc.table_schema = 'public'
                  AND tc.table_name = %s
                  AND tc.constraint_type = 'FOREIGN KEY'
                ORDER BY kcu.column_name
                """,
                (table_name,),
            )
            rows = cur.fetchall()
    return {
        (row["column_name"], row["foreign_table_name"], row["foreign_column_name"])
        for row in rows
    }


def _fetch_index_defs(db, table_name: str) -> list[str]:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT indexdef
                FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = %s
                ORDER BY indexname
                """,
                (table_name,),
            )
            rows = cur.fetchall()
    return [" ".join(row["indexdef"].lower().split()) for row in rows]


def _assert_index(index_defs: list[str], column_fragment: str) -> None:
    normalized = " ".join(column_fragment.lower().split())
    assert any(normalized in index_def for index_def in index_defs), (
        f"Expected index containing {column_fragment!r}, got {index_defs}"
    )


def test_versioning_tables_match_contract(initialized_db):
    table_contracts = {
        "source_documents": {
            "columns": {
                "source_document_id": {"nullable": "NO"},
                "scenario_id": {"nullable": "YES"},
                "source_kind": {"nullable": "NO"},
                "title": {"nullable": "NO"},
                "source_filename": {"nullable": "NO"},
                "mime_type": {"nullable": "NO"},
                "source_sha256": {"nullable": "NO"},
                "storage_path": {"nullable": "NO"},
                "license_type": {"nullable": "NO"},
                "license_ref": {"nullable": "YES"},
                "status": {"nullable": "NO"},
                "metadata": {"nullable": "NO", "udt_name": "jsonb"},
                "created_by": {"nullable": "NO"},
                "created_at": {"nullable": "NO"},
                "updated_at": {"nullable": "NO"},
            },
            "primary_key": ("source_document_id",),
            "unique": {("source_sha256", "source_kind")},
            "foreign_keys": {("scenario_id", "scenarios", "scenario_id")},
            "indexes": ["(source_sha256, source_kind)"],
        },
        "source_parts": {
            "columns": {
                "source_part_id": {"nullable": "NO"},
                "source_document_id": {"nullable": "NO"},
                "ordinal": {"nullable": "NO"},
                "part_kind": {"nullable": "NO"},
                "page_number": {"nullable": "YES"},
                "text_content": {"nullable": "NO"},
                "mime_type": {"nullable": "YES"},
                "storage_path": {"nullable": "YES"},
                "anchor": {"nullable": "NO", "udt_name": "jsonb"},
                "checksum": {"nullable": "NO"},
                "created_at": {"nullable": "NO"},
            },
            "primary_key": ("source_part_id",),
            "unique": {("source_document_id", "ordinal")},
            "foreign_keys": {("source_document_id", "source_documents", "source_document_id")},
            "indexes": ["(source_document_id, ordinal)"],
        },
        "import_jobs": {
            "columns": {
                "job_id": {"nullable": "NO"},
                "source_document_id": {"nullable": "NO"},
                "scenario_id": {"nullable": "YES"},
                "status": {"nullable": "NO"},
                "progress": {"nullable": "NO"},
                "error_message": {"nullable": "YES"},
                "diagnostics": {"nullable": "NO", "udt_name": "jsonb"},
                "created_at": {"nullable": "NO"},
                "updated_at": {"nullable": "NO"},
            },
            "primary_key": ("job_id",),
            "foreign_keys": {
                ("source_document_id", "source_documents", "source_document_id"),
                ("scenario_id", "scenarios", "scenario_id"),
            },
        },
        "scenario_versions": {
            "columns": {
                "scenario_version_id": {"nullable": "NO"},
                "scenario_id": {"nullable": "NO"},
                "version_number": {"nullable": "NO"},
                "status": {"nullable": "NO"},
                "knowledge_graph": {"nullable": "NO", "udt_name": "jsonb"},
                "quality_report": {"nullable": "NO", "udt_name": "jsonb"},
                "prep_package": {"nullable": "NO", "udt_name": "jsonb"},
                "rag_index_version": {"nullable": "YES"},
                "created_by": {"nullable": "NO"},
                "created_at": {"nullable": "NO"},
                "reviewed_by": {"nullable": "YES"},
                "reviewed_at": {"nullable": "YES"},
                "review_notes": {"nullable": "NO", "udt_name": "jsonb"},
                "published_at": {"nullable": "YES"},
            },
            "primary_key": ("scenario_version_id",),
            "unique": {("scenario_id", "version_number")},
            "foreign_keys": {("scenario_id", "scenarios", "scenario_id")},
            "indexes": ["(scenario_id, version_number)", "(scenario_id, status)"],
        },
        "scenario_version_sources": {
            "columns": {
                "scenario_version_id": {"nullable": "NO"},
                "source_document_id": {"nullable": "NO"},
                "ordinal": {"nullable": "NO"},
                "created_at": {"nullable": "NO"},
            },
            "primary_key": ("scenario_version_id", "source_document_id"),
            "unique": {("scenario_version_id", "ordinal")},
            "foreign_keys": {
                ("scenario_version_id", "scenario_versions", "scenario_version_id"),
                ("source_document_id", "source_documents", "source_document_id"),
            },
            "indexes": ["(source_document_id)"],
        },
        "rag_rebuild_records": {
            "columns": {
                "rebuild_id": {"nullable": "NO"},
                "scenario_version_id": {"nullable": "NO"},
                "status": {"nullable": "NO"},
                "embedding_model": {"nullable": "YES"},
                "embedding_dimensions": {"nullable": "YES"},
                "chunk_count": {"nullable": "NO"},
                "requested_by": {"nullable": "NO"},
                "error_message": {"nullable": "YES"},
                "started_at": {"nullable": "NO"},
                "completed_at": {"nullable": "YES"},
            },
            "primary_key": ("rebuild_id",),
            "foreign_keys": {
                ("scenario_version_id", "scenario_versions", "scenario_version_id"),
            },
            "indexes": ["(scenario_version_id, started_at)"],
        },
        "rule_sets": {
            "columns": {
                "rule_set_id": {"nullable": "NO"},
                "name": {"nullable": "NO"},
                "slug": {"nullable": "NO"},
                "system": {"nullable": "NO"},
                "description": {"nullable": "NO"},
                "is_base": {"nullable": "NO"},
                "license_type": {"nullable": "NO"},
                "status": {"nullable": "NO"},
                "created_by": {"nullable": "NO"},
                "created_at": {"nullable": "NO"},
            },
            "primary_key": ("rule_set_id",),
            "unique": {("slug",)},
            "indexes": ["(system, is_base, status)"],
        },
        "rule_set_versions": {
            "columns": {
                "rule_set_version_id": {"nullable": "NO"},
                "rule_set_id": {"nullable": "NO"},
                "version_number": {"nullable": "NO"},
                "label": {"nullable": "NO"},
                "status": {"nullable": "NO"},
                "source_sha256": {"nullable": "YES"},
                "metadata": {"nullable": "NO", "udt_name": "jsonb"},
                "created_by": {"nullable": "NO"},
                "created_at": {"nullable": "NO"},
                "published_at": {"nullable": "YES"},
            },
            "primary_key": ("rule_set_version_id",),
            "unique": {("rule_set_id", "version_number")},
            "foreign_keys": {("rule_set_id", "rule_sets", "rule_set_id")},
            "indexes": ["(rule_set_id, status)"],
        },
        "rule_documents": {
            "columns": {
                "doc_id": {"nullable": "NO"},
                "rule_set_version_id": {"nullable": "YES"},
                "source_document_id": {"nullable": "YES"},
                "title": {"nullable": "NO"},
                "category": {"nullable": "NO"},
                "content": {"nullable": "NO"},
                "visibility": {"nullable": "NO"},
                "license_type": {"nullable": "NO"},
                "source_ref": {"nullable": "YES"},
                "created_at": {"nullable": "NO"},
            },
            "primary_key": ("doc_id",),
            "foreign_keys": {
                ("rule_set_version_id", "rule_set_versions", "rule_set_version_id"),
                ("source_document_id", "source_documents", "source_document_id"),
            },
            "indexes": ["(rule_set_version_id, category)"],
        },
        "scenario_rule_bindings": {
            "columns": {
                "scenario_version_id": {"nullable": "NO"},
                "rule_set_version_id": {"nullable": "NO"},
                "priority": {"nullable": "NO"},
                "created_at": {"nullable": "NO"},
            },
            "primary_key": ("scenario_version_id", "rule_set_version_id"),
            "foreign_keys": {
                ("scenario_version_id", "scenario_versions", "scenario_version_id"),
                ("rule_set_version_id", "rule_set_versions", "rule_set_version_id"),
            },
            "indexes": ["(scenario_version_id, priority)"],
        },
        "room_rule_bindings": {
            "columns": {
                "room_id": {"nullable": "NO"},
                "rule_set_version_id": {"nullable": "NO"},
                "priority": {"nullable": "NO"},
                "created_at": {"nullable": "NO"},
            },
            "primary_key": ("room_id", "rule_set_version_id"),
            "foreign_keys": {
                ("room_id", "rooms", "room_id"),
                ("rule_set_version_id", "rule_set_versions", "rule_set_version_id"),
            },
            "indexes": ["(room_id, priority)"],
        },
    }

    for table_name, contract in table_contracts.items():
        columns = _fetch_columns(initialized_db, table_name)
        assert columns, f"Expected table {table_name} to exist"
        for column_name, expectations in contract["columns"].items():
            assert column_name in columns, f"Missing {table_name}.{column_name}"
            column = columns[column_name]
            if "nullable" in expectations:
                assert column["is_nullable"] == expectations["nullable"]
            if "udt_name" in expectations:
                assert column["udt_name"] == expectations["udt_name"]

        primary_keys = _fetch_constraints(initialized_db, table_name, "PRIMARY KEY")
        assert contract["primary_key"] in primary_keys

        unique_constraints = set(_fetch_constraints(initialized_db, table_name, "UNIQUE"))
        assert contract.get("unique", set()).issubset(unique_constraints)

        foreign_keys = _fetch_foreign_keys(initialized_db, table_name)
        assert contract.get("foreign_keys", set()).issubset(foreign_keys)

        index_defs = _fetch_index_defs(initialized_db, table_name)
        for fragment in contract.get("indexes", []):
            _assert_index(index_defs, fragment)


def test_existing_tables_gain_versioning_columns_and_indexes(initialized_db):
    scenarios = _fetch_columns(initialized_db, "scenarios")
    rooms = _fetch_columns(initialized_db, "rooms")
    chunks = _fetch_columns(initialized_db, "document_chunks")

    assert scenarios["publish_status"]["is_nullable"] == "NO"
    assert "'draft'" in (scenarios["publish_status"]["column_default"] or "")
    assert scenarios["published_version_id"]["is_nullable"] == "YES"

    assert rooms["scenario_version_id"]["is_nullable"] == "YES"

    assert chunks["source_part_id"]["is_nullable"] == "YES"
    assert chunks["scenario_version_id"]["is_nullable"] == "YES"
    assert chunks["rule_set_version_id"]["is_nullable"] == "YES"
    assert chunks["visibility"]["is_nullable"] == "NO"
    assert "'internal'" in (chunks["visibility"]["column_default"] or "")
    assert chunks["citation"]["udt_name"] == "jsonb"
    assert chunks["embedding_model"]["is_nullable"] == "YES"
    assert chunks["embedding_dimensions"]["is_nullable"] == "YES"

    version_indexes = _fetch_index_defs(initialized_db, "scenario_versions")
    chunk_indexes = _fetch_index_defs(initialized_db, "document_chunks")
    _assert_index(version_indexes, "(scenario_id, status)")
    _assert_index(chunk_indexes, "(scenario_version_id, visibility)")


def test_test_db_fixture_still_supports_versioning_tables(test_db):
    test_db.execute(
        """
        INSERT INTO scenarios (scenario_id, title, publish_status)
        VALUES (?, ?, ?)
        """,
        ("scenario-fixture", "Fixture Scenario", "draft"),
    )
    test_db.execute(
        """
        INSERT INTO rooms (room_id, scenario_id, owner_token, scenario_version_id)
        VALUES (?, ?, ?, ?)
        """,
        ("room-fixture", "scenario-fixture", "owner-token", None),
    )
    test_db.execute(
        """
        INSERT INTO source_documents (
            source_document_id, scenario_id, source_kind, title, source_filename,
            mime_type, source_sha256, storage_path, license_type, license_ref,
            status, metadata, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "doc-fixture",
            "scenario-fixture",
            "upload",
            "Rulebook",
            "rulebook.pdf",
            "application/pdf",
            "sha-doc-fixture",
            "/tmp/rulebook.pdf",
            "internal",
            None,
            "ready",
            "{}",
            "tester",
        ),
    )
    test_db.execute(
        """
        INSERT INTO source_parts (
            source_part_id, source_document_id, ordinal, part_kind, page_number,
            text_content, mime_type, storage_path, anchor, checksum
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "part-fixture",
            "doc-fixture",
            1,
            "page",
            1,
            "第一页",
            "text/plain",
            None,
            "{}",
            "checksum-1",
        ),
    )
    test_db.execute(
        """
        INSERT INTO scenario_versions (
            scenario_version_id, scenario_id, version_number, status,
            knowledge_graph, quality_report, prep_package, rag_index_version, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "version-fixture",
            "scenario-fixture",
            1,
            "draft",
            "{}",
            "{}",
            "{}",
            "rag-v1",
            "tester",
        ),
    )
    test_db.execute(
        """
        INSERT INTO scenario_version_sources (
            scenario_version_id, source_document_id, ordinal
        ) VALUES (?, ?, ?)
        """,
        ("version-fixture", "doc-fixture", 1),
    )
    test_db.execute(
        """
        INSERT INTO rag_rebuild_records (
            rebuild_id, scenario_version_id, status, embedding_model,
            embedding_dimensions, chunk_count, requested_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "rebuild-fixture",
            "version-fixture",
            "complete",
            "text-embedding-3-large",
            3072,
            1,
            "tester",
        ),
    )
    test_db.execute(
        """
        INSERT INTO rule_sets (
            rule_set_id, name, slug, system, description, is_base,
            license_type, status, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "rules-fixture", "CoC 7e", "coc7-fixture", "coc7", "Fixture rules",
            True, "open", "published", "tester",
        ),
    )
    test_db.execute(
        """
        INSERT INTO rule_set_versions (
            rule_set_version_id, rule_set_id, version_number, label, status,
            source_sha256, metadata, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "rules-version-fixture", "rules-fixture", 1, "v1", "published",
            "rules-sha", "{}", "tester",
        ),
    )
    test_db.execute(
        """
        INSERT INTO rule_documents (
            doc_id, rule_set_version_id, source_document_id, title, category,
            content, visibility, license_type, source_ref
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "rule-doc-fixture", "rules-version-fixture", "doc-fixture", "技能检定",
            "checks", "规则内容", "host_only", "open", "rulebook.pdf#page=1",
        ),
    )
    test_db.execute(
        """
        INSERT INTO scenario_rule_bindings (
            scenario_version_id, rule_set_version_id, priority
        ) VALUES (?, ?, ?)
        """,
        ("version-fixture", "rules-version-fixture", 100),
    )
    test_db.execute(
        """
        INSERT INTO room_rule_bindings (room_id, rule_set_version_id, priority)
        VALUES (?, ?, ?)
        """,
        ("room-fixture", "rules-version-fixture", 200),
    )
    test_db.execute(
        """
        INSERT INTO import_jobs (
            job_id, source_document_id, scenario_id, status, progress, error_message, diagnostics
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "job-fixture",
            "doc-fixture",
            "scenario-fixture",
            "complete",
            100,
            None,
            "{}",
        ),
    )
    test_db.execute(
        """
        INSERT INTO document_chunks (
            chunk_id, source_type, source_id, room_id, content, metadata, source_part_id,
            scenario_version_id, rule_set_version_id, visibility, citation, embedding_model,
            embedding_dimensions
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "chunk-fixture",
            "scenario",
            "scenario-fixture",
            "room-fixture",
            "chunk content",
            "{}",
            "part-fixture",
            "version-fixture",
            None,
            "internal",
            "{}",
            "text-embedding-3-large",
            3072,
        ),
    )

    row = test_db.execute(
        """
        SELECT source_part_id, scenario_version_id, visibility
        FROM document_chunks
        WHERE chunk_id = ?
        """,
        ("chunk-fixture",),
    ).fetchone()
    assert row is not None
    assert row["source_part_id"] == "part-fixture"
    assert row["scenario_version_id"] == "version-fixture"
    assert row["visibility"] == "internal"

    source_link = test_db.execute(
        "SELECT source_document_id FROM scenario_version_sources WHERE scenario_version_id = ?",
        ("version-fixture",),
    ).fetchone()
    rebuild = test_db.execute(
        "SELECT status, chunk_count FROM rag_rebuild_records WHERE rebuild_id = ?",
        ("rebuild-fixture",),
    ).fetchone()
    assert source_link["source_document_id"] == "doc-fixture"
    assert rebuild["status"] == "complete"
    assert rebuild["chunk_count"] == 1

    rule_document = test_db.execute(
        "SELECT rule_set_version_id, visibility FROM rule_documents WHERE doc_id = ?",
        ("rule-doc-fixture",),
    ).fetchone()
    assert rule_document["rule_set_version_id"] == "rules-version-fixture"
    assert rule_document["visibility"] == "host_only"
