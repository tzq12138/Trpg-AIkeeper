from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from src.server.rules.authoritative_coc7 import (
    AuthoritativeRulebookError,
    authoritative_gate_snapshot,
    validate_official_rulebook_path,
)
from src.server.rule_source_lifecycle import (
    current_authoritative_base_version,
    ensure_room_rule_source_available,
    retire_local_test_rule_versions,
)


def test_authoritative_rulebook_rejects_wrong_hash_and_page_count():
    """Rejecting a non-official file prevents an arbitrary PDF becoming authoritative."""
    with TemporaryDirectory() as directory:
        source = Path(directory) / "wrong.pdf"
        source.write_bytes(b"not the official rulebook")

        with pytest.raises(AuthoritativeRulebookError, match="sha256"):
            validate_official_rulebook_path(source)


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
