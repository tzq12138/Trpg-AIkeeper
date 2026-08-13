import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from src.server.ai.rag import RAGStore
from src.server.rules.authoritative_coc7 import (
    AuthoritativeRulebookError,
    OfficialRulebookSpec,
    RuleSourcePage,
    approve_rule_source_review,
    authoritative_gate_snapshot,
    get_rule_version_audit,
    import_authoritative_coc7,
    validate_official_rulebook_path,
)
from src.server.rule_source_lifecycle import (
    current_authoritative_base_version,
    ensure_room_rule_source_available,
    retire_local_test_rule_versions,
)
from src.server import rule_source_lifecycle
from src.server.ai.ai_config import frozen_rule_policy_sources


def test_authoritative_rulebook_rejects_wrong_hash_and_page_count():
    """Rejecting a non-official file prevents an arbitrary PDF becoming authoritative."""
    with TemporaryDirectory() as directory:
        source = Path(directory) / "wrong.pdf"
        source.write_bytes(b"not the official rulebook")

        with pytest.raises(AuthoritativeRulebookError, match="sha256"):
            validate_official_rulebook_path(source)


@pytest.mark.parametrize("page_number", [151, 168, 205, 207, 341])
def test_body_page_that_mentions_archive_markers_remains_indexable(page_number):
    """Terms such as directory and index inside prose do not make a rules page archival."""
    from src.server.rules.authoritative_coc7 import _classify_page

    body = "正文中的目录、索引、版权和ISBN仅作为规则示例。" * 20

    assert _classify_page(body, page_number) == "indexable"


def test_only_blank_or_directory_structures_are_archived_non_retrieval():
    from src.server.rules.authoritative_coc7 import _classify_page

    assert _classify_page("   ", 1) == "archived_non_retrieval"
    assert _classify_page("目录\n第一章……1\n第二章……12\n索引……379", 3) == "archived_non_retrieval"


def test_rule_source_schema_stores_one_status_for_each_physical_page(test_db):
    """Each physical source page keeps its own extraction state for auditability."""
    test_db.execute(
        """
        INSERT INTO source_documents (
            source_document_id, source_kind, title, source_filename, mime_type,
            source_sha256, storage_path, license_type, created_by
        ) VALUES (
            'official-coc7-source', 'rulebook', 'CoC7 Core Rules',
            'COC7th核心规则书v1.2.1.pdf', 'application/pdf',
            '22f5f56b7a0989cbded695d39c7d5eddddd809cfc9d2c47e4cf4c5d7edea6815',
            'rules/COC7th核心规则书v1.2.1.pdf', 'authorized', 'test'
        )
        """
    )
    test_db.execute(
        """
        INSERT INTO rule_source_pages (
            rule_source_page_id, source_document_id, page_number, extraction_status,
            text_sha256, extraction_method
        ) VALUES (
            'official-coc7-page-1', 'official-coc7-source', 1, 'indexable',
            'page-text-sha256', 'text-extraction'
        )
        """
    )

    row = test_db.execute(
        "SELECT extraction_status FROM rule_source_pages WHERE rule_source_page_id = 'official-coc7-page-1'"
    ).fetchone()

    assert row["extraction_status"] == "indexable"


def test_authoritative_gate_snapshot_reads_the_version_gate(test_db):
    """An audit snapshot exposes the configured gate without publishing the version."""
    test_db.execute(
        """
        INSERT INTO rule_sets (
            rule_set_id, name, slug, system, is_base, license_type, status, created_by
        ) VALUES ('official-coc7', 'CoC7', 'official-coc7', 'coc7', TRUE, 'authorized', 'draft', 'test')
        """
    )
    test_db.execute(
        """
        INSERT INTO rule_set_versions (
            rule_set_version_id, rule_set_id, version_number, status, source_sha256, created_by
        ) VALUES (
            'official-coc7-v1', 'official-coc7', 1, 'draft',
            '22F5F56B7A0989CBDED695D39C7D5EDDDDD809CFC9D2C47E4CF4C5D7EDEA6815', 'test'
        )
        """
    )
    test_db.execute(
        """
        INSERT INTO rule_version_publication_gates (
            rule_set_version_id, status, diagnostics
        ) VALUES ('official-coc7-v1', 'pending', '{"missing_pages": 380}')
        """
    )

    snapshot = authoritative_gate_snapshot(test_db, 'official-coc7-v1')

    assert snapshot['rule_set_version_id'] == 'official-coc7-v1'
    assert snapshot['gate_status'] == 'pending'
    assert snapshot['runtime_eligible'] is False


def test_lifecycle_helpers_do_not_activate_or_retire_anything_in_task_one(test_db):
    """Task-one lifecycle helpers only read the prepared model and leave rows intact."""
    test_db.execute("INSERT INTO rooms (room_id, owner_token) VALUES ('ready-room', 'owner')")

    assert current_authoritative_base_version(test_db) is None
    assert ensure_room_rule_source_available(test_db, 'ready-room') is None
    assert retire_local_test_rule_versions(test_db) == {
        'retired_rule_versions': 0,
        'retired_rooms': 0,
    }


def test_backfill_adds_ready_gate_only_for_eligible_nonofficial_versions(test_db):
    test_db.execute(
        "INSERT INTO rule_sets (rule_set_id, name, slug, system, license_type, status, created_by) VALUES "
        "('backfill-live-set', 'Live', 'backfill-live', 'coc7', 'authorized', 'published', 'test'), "
        "('backfill-retired-set', 'Retired', 'backfill-retired', 'coc7', 'authorized', 'published', 'test'), "
        "('backfill-draft-set', 'Draft', 'backfill-draft', 'coc7', 'authorized', 'published', 'test'), "
        "('backfill-official-set', 'Official', 'backfill-official', 'coc7', 'authorized', 'published', 'test'), "
        "('backfill-pending-set', 'Pending', 'backfill-pending', 'coc7', 'authorized', 'published', 'test')"
    )
    test_db.execute(
        "INSERT INTO rule_set_versions (rule_set_version_id, rule_set_id, version_number, status, "
        "runtime_eligible, source_sha256, metadata, created_by) VALUES "
        "('backfill-live-v1', 'backfill-live-set', 1, 'published', TRUE, NULL, '{}', 'test'), "
        "('backfill-retired-v1', 'backfill-retired-set', 1, 'published', TRUE, NULL, "
        "'{\"local_test_only\": true}', 'test'), "
        "('backfill-draft-v1', 'backfill-draft-set', 1, 'draft', TRUE, NULL, '{}', 'test'), "
        "('backfill-official-v1', 'backfill-official-set', 1, 'published', TRUE, "
        "'22F5F56B7A0989CBDED695D39C7D5EDDDDD809CFC9D2C47E4CF4C5D7EDEA6815', '{}', 'test'), "
        "('backfill-pending-v1', 'backfill-pending-set', 1, 'published', TRUE, NULL, '{}', 'test')"
    )
    test_db.execute(
        "INSERT INTO rule_version_publication_gates (rule_set_version_id, status) "
        "VALUES ('backfill-pending-v1', 'pending')"
    )

    assert rule_source_lifecycle.backfill_legacy_runtime_rule_publication_gates(test_db) == 1
    assert rule_source_lifecycle.backfill_legacy_runtime_rule_publication_gates(test_db) == 0
    gates = test_db.execute(
        "SELECT rule_set_version_id, status FROM rule_version_publication_gates "
        "ORDER BY rule_set_version_id"
    ).fetchall()
    assert gates == [
        {"rule_set_version_id": "backfill-live-v1", "status": "ready"},
        {"rule_set_version_id": "backfill-pending-v1", "status": "pending"},
    ]


def test_retiring_local_test_rules_marks_only_dependent_rooms_and_excludes_them_from_frozen_sources(test_db):
    """The old test corpus is quarantined in place without touching unrelated rooms."""
    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title, import_status, published_version_id) VALUES "
        "('legacy-scenario', 'Legacy', 'structured', 'legacy-sv'), "
        "('live-scenario', 'Live', 'structured', NULL)"
    )
    test_db.execute(
        "INSERT INTO scenario_versions (scenario_version_id, scenario_id, version_number, status, created_by) VALUES "
        "('legacy-sv', 'legacy-scenario', 1, 'published', 'test'), "
        "('live-sv', 'live-scenario', 1, 'published', 'test')"
    )
    test_db.execute(
        "INSERT INTO rooms (room_id, scenario_id, scenario_version_id, owner_token) VALUES "
        "('legacy-scenario-room', 'legacy-scenario', 'legacy-sv', 'owner'), "
        "('legacy-direct-room', 'live-scenario', 'live-sv', 'owner'), "
        "('legacy-fallback-room', 'legacy-scenario', NULL, 'owner'), "
        "('legacy-overridden-room', 'legacy-scenario', 'legacy-sv', 'owner'), "
        "('legacy-base-fallback-room', NULL, NULL, 'owner'), "
        "('unrelated-room', 'live-scenario', 'live-sv', 'owner')"
    )
    test_db.execute(
        "INSERT INTO rule_sets "
        "(rule_set_id, name, slug, system, is_base, license_type, status, created_by) VALUES "
        "('legacy-rules', 'Legacy', 'legacy-rules', 'coc7', FALSE, 'authorized', 'published', 'test'), "
        "('legacy-base-rules', 'Legacy base', 'legacy-base-rules', 'coc7', TRUE, 'authorized', 'published', 'test'), "
        "('qualified-rules', 'Qualified', 'qualified-rules', 'coc7', FALSE, 'authorized', 'published', 'test')"
    )
    test_db.execute(
        "INSERT INTO rule_set_versions (rule_set_version_id, rule_set_id, version_number, status, "
        "runtime_eligible, metadata, created_by) VALUES "
        "('legacy-rules-v1', 'legacy-rules', 1, 'published', TRUE, "
        "'{\"local_test_only\": true}', 'test'), "
        "('legacy-base-rules-v1', 'legacy-base-rules', 1, 'published', TRUE, "
        "'{\"local_test_only\": true}', 'test'), "
        "('qualified-rules-v1', 'qualified-rules', 1, 'published', TRUE, '{}', 'test')"
    )
    test_db.execute(
        "INSERT INTO rule_version_publication_gates (rule_set_version_id, status) VALUES "
        "('legacy-rules-v1', 'ready'), ('legacy-base-rules-v1', 'ready'), "
        "('qualified-rules-v1', 'ready')"
    )
    test_db.execute(
        "INSERT INTO scenario_rule_bindings (scenario_version_id, rule_set_version_id) VALUES "
        "('legacy-sv', 'legacy-rules-v1'), ('live-sv', 'qualified-rules-v1')"
    )
    test_db.execute(
        "INSERT INTO room_rule_bindings (room_id, rule_set_version_id) VALUES "
        "('legacy-direct-room', 'legacy-rules-v1'), "
        "('legacy-overridden-room', 'qualified-rules-v1')"
    )

    result = retire_local_test_rule_versions(test_db)

    assert result == {"retired_rule_versions": 2, "retired_rooms": 5}
    assert test_db.execute(
        "SELECT runtime_eligible FROM rule_set_versions WHERE rule_set_version_id = 'legacy-rules-v1'"
    ).fetchone()["runtime_eligible"] is False
    assert test_db.execute(
        "SELECT runtime_eligible FROM rule_set_versions WHERE rule_set_version_id = 'legacy-base-rules-v1'"
    ).fetchone()["runtime_eligible"] is False
    statuses = {
        row["room_id"]: (row["rule_source_status"], row["rule_source_reason"])
        for row in test_db.execute(
            "SELECT room_id, rule_source_status, rule_source_reason FROM rooms ORDER BY room_id"
        ).fetchall()
    }
    assert statuses["legacy-scenario-room"] == (
        "rule_source_retired", "local_test_rule_version"
    )
    assert statuses["legacy-direct-room"] == (
        "rule_source_retired", "local_test_rule_version"
    )
    assert statuses["legacy-fallback-room"] == (
        "rule_source_retired", "local_test_rule_version"
    )
    assert statuses["legacy-overridden-room"] == (
        "rule_source_retired", "local_test_rule_version"
    )
    assert statuses["legacy-base-fallback-room"] == (
        "rule_source_retired", "local_test_rule_version"
    )
    assert statuses["unrelated-room"] == ("ready", None)
    assert frozen_rule_policy_sources(test_db, "unrelated-room", "live-sv") == [{
        "scope": "scenario",
        "rule_set_version_id": "qualified-rules-v1",
        "metadata": {},
    }]
    assert test_db.execute("SELECT COUNT(*) AS count FROM rule_set_versions").fetchone()["count"] == 3
    assert retire_local_test_rule_versions(test_db) == {
        "retired_rule_versions": 0,
        "retired_rooms": 0,
    }


def test_authoritative_base_version_requires_a_linked_source_page_gate(test_db):
    """A copied SHA alone never makes an arbitrary base version authoritative."""
    test_db.execute(
        """
        INSERT INTO rule_sets (
            rule_set_id, name, slug, system, is_base, license_type, status, created_by
        ) VALUES ('spoofed-set', 'Spoofed CoC7', 'spoofed-coc7', 'coc7', TRUE, 'authorized', 'published', 'test')
        """
    )
    test_db.execute(
        """
        INSERT INTO rule_set_versions (
            rule_set_version_id, rule_set_id, version_number, status, runtime_eligible,
            source_sha256, created_by
        ) VALUES (
            'spoofed-v1', 'spoofed-set', 1, 'published', TRUE,
            '22F5F56B7A0989CBDED695D39C7D5EDDDDD809CFC9D2C47E4CF4C5D7EDEA6815', 'test'
        )
        """
    )

    assert current_authoritative_base_version(test_db) is None


class _RecordingCursor:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.calls.append((sql, tuple(params)))


class _RecordingConnection:
    def __init__(self):
        self.cursor_obj = _RecordingCursor()

    def cursor(self):
        return self.cursor_obj


class _RecordingDb:
    def __init__(self):
        self.conn = _RecordingConnection()

    @contextmanager
    def get_conn(self):
        yield self.conn


class _FakeEmbedding:
    model_name = "fake-embedding-v1"

    def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class _FakeRag:
    def __init__(self):
        self.indexed_pages = []

    def index_rule_pages(self, source_document_id, rule_set_version_id, pages):
        self.indexed_pages.extend(pages)
        return sum(1 for page in pages if page["extraction_status"] == "indexable")


class _FailingRag:
    def index_rule_pages(self, _source_document_id, _rule_set_version_id, _pages):
        raise RuntimeError("index exploded")


def _fake_official_pages():
    return [
        RuleSourcePage(
            page_number=page_number,
            text=f"official page {page_number}",
            extraction_status="indexable",
            extraction_method="fake-test",
        )
        for page_number in range(1, 381)
    ]


def test_import_records_all_official_pages_and_indexes_only_page_bound_chunks(
    test_db, monkeypatch
):
    """The importer is page-complete while the indexer only receives page-bound text."""
    from src.server.rules import authoritative_coc7

    monkeypatch.setattr(
        authoritative_coc7,
        "load_authoritative_rulebook_pages",
        lambda: (
            OfficialRulebookSpec(
                filename="COC7th核心规则书v1.2.1.pdf",
                page_count=380,
                sha256="22F5F56B7A0989CBDED695D39C7D5EDDDDD809CFC9D2C47E4CF4C5D7EDEA6815",
            ),
            "registered/COC7th核心规则书v1.2.1.pdf",
            _fake_official_pages(),
        ),
    )
    rag = _FakeRag()

    imported = import_authoritative_coc7(test_db, rag, actor_id="acc-admin")

    assert imported["page_count"] == 380
    assert imported["gate_status"] == "pending_review"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM rule_source_pages WHERE source_document_id = %s",
        (imported["source_document_id"],),
    ).fetchone()["count"] == 380
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM source_parts WHERE source_document_id = %s",
        (imported["source_document_id"],),
    ).fetchone()["count"] == 380
    assert len(rag.indexed_pages) == 380
    assert all(page["source_part_id"] and page["page_number"] for page in rag.indexed_pages)


def test_import_is_idempotent_for_the_fixed_source_hash(test_db, monkeypatch):
    from src.server.rules import authoritative_coc7

    monkeypatch.setattr(
        authoritative_coc7,
        "load_authoritative_rulebook_pages",
        lambda: (
            OfficialRulebookSpec(
                filename="COC7th核心规则书v1.2.1.pdf",
                page_count=380,
                sha256="22F5F56B7A0989CBDED695D39C7D5EDDDDD809CFC9D2C47E4CF4C5D7EDEA6815",
            ),
            "registered/COC7th核心规则书v1.2.1.pdf",
            _fake_official_pages(),
        ),
    )
    rag = _FakeRag()

    first = import_authoritative_coc7(test_db, rag, actor_id="acc-admin")
    second = import_authoritative_coc7(test_db, rag, actor_id="acc-admin")

    assert second == first
    assert len(rag.indexed_pages) == 380
    assert test_db.execute("SELECT COUNT(*) AS count FROM rule_set_versions").fetchone()["count"] == 1


def test_import_rejects_an_existing_official_source_with_incomplete_page_coverage(
    test_db, monkeypatch
):
    """Idempotence never turns a damaged prior import into a successful source."""
    from src.server.rules import authoritative_coc7

    monkeypatch.setattr(
        authoritative_coc7,
        "load_authoritative_rulebook_pages",
        lambda: (
            OfficialRulebookSpec(
                filename="COC7th核心规则书v1.2.1.pdf",
                page_count=380,
                sha256="22F5F56B7A0989CBDED695D39C7D5EDDDDD809CFC9D2C47E4CF4C5D7EDEA6815",
            ),
            "registered/COC7th核心规则书v1.2.1.pdf",
            _fake_official_pages(),
        ),
    )
    first = import_authoritative_coc7(test_db, _FakeRag(), actor_id="acc-admin")
    test_db.execute(
        "DELETE FROM rule_source_pages WHERE source_document_id = %s AND page_number = 380",
        (first["source_document_id"],),
    )

    with pytest.raises(AuthoritativeRulebookError, match="incomplete"):
        import_authoritative_coc7(test_db, _FakeRag(), actor_id="acc-admin")


def test_rule_page_indexer_keeps_chunks_on_their_physical_page():
    db = _RecordingDb()
    store = RAGStore(db, _FakeEmbedding())

    count = store.index_rule_pages(
        "source-1",
        "official-v1",
        [{
            "source_part_id": "source-1-page-9",
            "page_number": 9,
            "text": "X" * 700,
            "extraction_status": "indexable",
        }],
    )

    rows = []
    for sql, params in db.conn.cursor_obj.calls:
        if "INSERT INTO document_chunks" not in sql:
            continue
        columns = [column.strip() for column in sql.split("(", 1)[1].split(")", 1)[0].split(",")]
        rows.append(dict(zip(columns, params)))
    assert count == 2
    assert all(row["source_part_id"] == "source-1-page-9" for row in rows)
    citations = [json.loads(row["citation"]) for row in rows]
    assert all(citation["page_number"] == 9 for citation in citations)
    assert [(citation["start_offset"], citation["end_offset"]) for citation in citations] == [
        (0, 500),
        (450, 700),
    ]


def test_approval_requires_a_complete_official_source_and_returns_admin_audit(
    test_db, monkeypatch
):
    from src.server.rules import authoritative_coc7

    pages = _fake_official_pages()
    pages[-1] = RuleSourcePage(
        page_number=380,
        text="",
        extraction_status="needs_review",
        extraction_method="fake-test",
    )
    monkeypatch.setattr(
        authoritative_coc7,
        "load_authoritative_rulebook_pages",
        lambda: (
            OfficialRulebookSpec(
                filename="COC7th核心规则书v1.2.1.pdf",
                page_count=380,
                sha256="22F5F56B7A0989CBDED695D39C7D5EDDDDD809CFC9D2C47E4CF4C5D7EDEA6815",
            ),
            "registered/COC7th核心规则书v1.2.1.pdf",
            pages,
        ),
    )
    imported = import_authoritative_coc7(test_db, _FakeRag(), actor_id="acc-admin")

    with pytest.raises(AuthoritativeRulebookError, match="needs_review"):
        approve_rule_source_review(test_db, imported["rule_set_version_id"], "acc-admin")

    audit = get_rule_version_audit(test_db, imported["rule_set_version_id"])
    assert audit["source"]["sha256"] == imported["source_sha256"]
    assert audit["pages"]["total"] == 380
    assert audit["pages"]["needs_review"] == 1


def test_approval_marks_a_complete_official_source_ready(test_db, monkeypatch):
    """A fully audited 380-page source becomes publishable without publishing itself."""
    from src.server.rules import authoritative_coc7

    monkeypatch.setattr(
        authoritative_coc7,
        "load_authoritative_rulebook_pages",
        lambda: (
            OfficialRulebookSpec(
                filename="COC7th核心规则书v1.2.1.pdf",
                page_count=380,
                sha256="22F5F56B7A0989CBDED695D39C7D5EDDDDD809CFC9D2C47E4CF4C5D7EDEA6815",
            ),
            "registered/COC7th核心规则书v1.2.1.pdf",
            _fake_official_pages(),
        ),
    )
    imported = import_authoritative_coc7(test_db, _FakeRag(), actor_id="acc-admin")

    approved = approve_rule_source_review(
        test_db,
        imported["rule_set_version_id"],
        "acc-admin",
    )

    assert approved["gate"]["status"] == "ready"
    assert approved["version_status"] == "draft"


def test_index_failure_rethrows_original_error_and_removes_all_new_source_rows(
    test_db, monkeypatch
):
    """A failed vector write cannot leave an idempotently reusable half-import behind."""
    from src.server.rules import authoritative_coc7

    monkeypatch.setattr(
        authoritative_coc7,
        "load_authoritative_rulebook_pages",
        lambda: (
            OfficialRulebookSpec(
                filename="COC7th核心规则书v1.2.1.pdf",
                page_count=380,
                sha256="22F5F56B7A0989CBDED695D39C7D5EDDDDD809CFC9D2C47E4CF4C5D7EDEA6815",
            ),
            "registered/COC7th核心规则书v1.2.1.pdf",
            _fake_official_pages(),
        ),
    )

    with pytest.raises(RuntimeError, match="index exploded"):
        import_authoritative_coc7(test_db, _FailingRag(), actor_id="acc-admin")

    for table in (
        "document_chunks",
        "rule_source_pages",
        "source_parts",
        "rule_version_publication_gates",
        "rule_set_versions",
        "source_documents",
    ):
        assert test_db.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"] == 0


def test_approval_rejects_page_381_when_physical_page_380_is_missing(test_db, monkeypatch):
    """Page count is insufficient: the audit must cover exactly physical pages 1 through 380."""
    from src.server.rules import authoritative_coc7

    monkeypatch.setattr(
        authoritative_coc7,
        "load_authoritative_rulebook_pages",
        lambda: (
            OfficialRulebookSpec(
                filename="COC7th核心规则书v1.2.1.pdf",
                page_count=380,
                sha256="22F5F56B7A0989CBDED695D39C7D5EDDDDD809CFC9D2C47E4CF4C5D7EDEA6815",
            ),
            "registered/COC7th核心规则书v1.2.1.pdf",
            _fake_official_pages(),
        ),
    )
    imported = import_authoritative_coc7(test_db, _FakeRag(), actor_id="acc-admin")
    test_db.execute(
        "UPDATE rule_source_pages SET page_number = 381 WHERE source_document_id = %s AND page_number = 380",
        (imported["source_document_id"],),
    )

    with pytest.raises(AuthoritativeRulebookError, match="physical pages"):
        approve_rule_source_review(test_db, imported["rule_set_version_id"], "acc-admin")


def test_extract_text_failure_is_stored_as_a_review_page_without_error_text(test_db, monkeypatch):
    """One unreadable page remains auditable and blocks approval without leaking parser details."""
    from src.server.rules import authoritative_coc7

    class FakePage:
        def __init__(self, page_number):
            self.page_number = page_number

        def extract_text(self):
            if self.page_number == 17:
                raise RuntimeError("C:/sensitive/path.pdf parser failure")
            return f"page {self.page_number}"

    class FakeReader:
        pages = [FakePage(page_number) for page_number in range(1, 381)]

    source_path = Path(__file__).resolve().parents[2] / "registered" / "COC7th核心规则书v1.2.1.pdf"
    monkeypatch.setattr(authoritative_coc7, "validate_official_rulebook_path", lambda _path: OfficialRulebookSpec(
        filename="COC7th核心规则书v1.2.1.pdf",
        page_count=380,
        sha256="22F5F56B7A0989CBDED695D39C7D5EDDDDD809CFC9D2C47E4CF4C5D7EDEA6815",
    ))
    monkeypatch.setattr(authoritative_coc7, "PdfReader", lambda _path: FakeReader())
    monkeypatch.setattr(authoritative_coc7, "_canonical_rulebook_path", lambda: source_path)

    _spec, _storage_path, pages = authoritative_coc7.load_authoritative_rulebook_pages()

    failed = pages[16]
    assert len(pages) == 380
    assert failed.extraction_status == "needs_review"
    assert failed.diagnostics == {"code": "extract_text_failed"}
    monkeypatch.setattr(
        authoritative_coc7,
        "load_authoritative_rulebook_pages",
        lambda: (
            _spec,
            "registered/COC7th核心规则书v1.2.1.pdf",
            pages,
        ),
    )
    imported = import_authoritative_coc7(test_db, _FakeRag(), actor_id="acc-admin")
    with pytest.raises(AuthoritativeRulebookError, match="needs_review"):
        approve_rule_source_review(test_db, imported["rule_set_version_id"], "acc-admin")


def test_admin_audit_returns_bounded_review_entries_only_to_admin(client, test_db, monkeypatch):
    """The audit endpoint lets an administrator inspect review targets without returning raw pages."""
    from src.server.rules import authoritative_coc7
    from tests.server.conftest import login, setup_auth_test_data

    pages = _fake_official_pages()
    pages[-1] = RuleSourcePage(
        page_number=380,
        text="reviewable excerpt only",
        extraction_status="needs_review",
        extraction_method="fake-test",
    )
    monkeypatch.setattr(
        authoritative_coc7,
        "load_authoritative_rulebook_pages",
        lambda: (
            OfficialRulebookSpec(
                filename="COC7th核心规则书v1.2.1.pdf",
                page_count=380,
                sha256="22F5F56B7A0989CBDED695D39C7D5EDDDDD809CFC9D2C47E4CF4C5D7EDEA6815",
            ),
            "registered/COC7th核心规则书v1.2.1.pdf",
            pages,
        ),
    )
    setup_auth_test_data(test_db)
    imported = import_authoritative_coc7(test_db, _FakeRag(), actor_id="acc-admin")
    token = login(client, "admin")

    response = client.get(
        f"/api/rag/rule-set-versions/{imported['rule_set_version_id']}/audit",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["review_entries"] == [{
        "page_number": 380,
        "extraction_status": "needs_review",
        "excerpt": "reviewable excerpt only",
    }]
