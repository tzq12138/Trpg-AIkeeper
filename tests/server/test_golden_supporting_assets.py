import json

from scripts.run_golden_module_suite import DeterministicGoldenRag


def test_deterministic_rag_persists_versioned_rule_document_and_chunks(test_db):
    test_db.execute(
        "INSERT INTO rule_sets "
        "(rule_set_id, name, slug, system, license_type, status, created_by) "
        "VALUES ('golden-rule-set', 'Golden Rules', 'golden-rules', 'coc7', 'authorized', 'draft', 'test')"
    )
    test_db.execute(
        "INSERT INTO rule_set_versions "
        "(rule_set_version_id, rule_set_id, version_number, label, status, metadata, created_by) "
        "VALUES ('golden-rule-version', 'golden-rule-set', 1, 'v1', 'draft', %s, 'test')",
        (json.dumps({}),),
    )
    test_db.commit()

    rag = DeterministicGoldenRag(test_db)
    indexed = rag.index_rules(
        "golden-rule-doc",
        "Golden Rulebook",
        "core",
        "x" * 700,
        rule_set_version_id="golden-rule-version",
        visibility="host_only",
        license_type="authorized",
        source_ref="golden.pdf#page:1",
        citation_base={"page_number": 1},
    )

    assert indexed == 2
    document = test_db.execute(
        "SELECT rule_set_version_id, content, source_ref FROM rule_documents WHERE doc_id = %s",
        ("golden-rule-doc",),
    ).fetchone()
    assert document == {
        "rule_set_version_id": "golden-rule-version",
        "content": "x" * 700,
        "source_ref": "golden.pdf#page:1",
    }
    chunks = test_db.execute(
        "SELECT COUNT(*) AS count FROM document_chunks "
        "WHERE source_type = 'rule' AND source_id = %s",
        ("golden-rule-doc",),
    ).fetchone()
    assert chunks["count"] == 2
