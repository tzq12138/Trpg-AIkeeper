import pytest

from src.server.scenario.import_service import (
    ScenarioImportFailure,
    ScenarioImportService,
    UploadedSource,
)


def test_default_import_limit_rejects_an_oversized_source():
    service = ScenarioImportService(None, max_file_bytes=4, max_total_bytes=8)

    with pytest.raises(ScenarioImportFailure, match="文件过大"):
        service._validate_sources(
            [UploadedSource(filename="large.pdf", content=b"12345")],
            "authorized",
        )


def test_golden_import_limit_accepts_a_larger_source_without_relaxing_default():
    service = ScenarioImportService(None, max_file_bytes=8, max_total_bytes=12)

    service._validate_sources(
        [UploadedSource(filename="large.pdf", content=b"12345678")],
        "authorized",
    )


def test_import_auto_binding_only_uses_qualified_base_rules(test_db):
    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title, import_status) "
        "VALUES ('import-rule-scenario', 'Import rules', 'structured')"
    )
    test_db.execute(
        "INSERT INTO scenario_versions (scenario_version_id, scenario_id, version_number, status, created_by) "
        "VALUES ('import-rule-scenario-v1', 'import-rule-scenario', 1, 'published', 'test')"
    )
    test_db.execute(
        "INSERT INTO rule_sets (rule_set_id, name, slug, system, is_base, license_type, status, created_by) VALUES "
        "('import-qualified-base', 'Qualified base', 'import-qualified-base', 'coc7', TRUE, 'authorized', 'published', 'test'), "
        "('import-retired-base', 'Retired base', 'import-retired-base', 'coc7', TRUE, 'authorized', 'published', 'test'), "
        "('import-ungated-base', 'Ungated base', 'import-ungated-base', 'coc7', TRUE, 'authorized', 'published', 'test')"
    )
    test_db.execute(
        "INSERT INTO rule_set_versions (rule_set_version_id, rule_set_id, version_number, status, "
        "runtime_eligible, metadata, created_by) VALUES "
        "('import-qualified-base-v1', 'import-qualified-base', 1, 'published', TRUE, '{}', 'test'), "
        "('import-retired-base-v1', 'import-retired-base', 1, 'published', FALSE, "
        "'{\"local_test_only\": true}', 'test'), "
        "('import-ungated-base-v1', 'import-ungated-base', 1, 'published', TRUE, '{}', 'test')"
    )
    test_db.execute(
        "INSERT INTO rule_version_publication_gates (rule_set_version_id, status) VALUES "
        "('import-qualified-base-v1', 'ready'), ('import-retired-base-v1', 'ready')"
    )

    with test_db.transaction() as tx:
        ScenarioImportService(test_db)._bind_published_base_rules(
            tx, "import-rule-scenario-v1"
        )

    bindings = test_db.execute(
        "SELECT rule_set_version_id FROM scenario_rule_bindings "
        "WHERE scenario_version_id = 'import-rule-scenario-v1' "
        "ORDER BY rule_set_version_id"
    ).fetchall()
    assert bindings == [{"rule_set_version_id": "import-qualified-base-v1"}]
