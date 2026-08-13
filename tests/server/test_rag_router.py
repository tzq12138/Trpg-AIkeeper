import json
from tests.server.conftest import setup_auth_test_data, login


def _insert_unreviewed_official_version(test_db):
    test_db.execute(
        """
        INSERT INTO source_documents (
            source_document_id, source_kind, title, source_filename, mime_type,
            source_sha256, storage_path, license_type, created_by
        ) VALUES (
            'official-source', 'rulebook', 'CoC7 Core',
            'COC7th核心规则书v1.2.1.pdf', 'application/pdf',
            '22F5F56B7A0989CBDED695D39C7D5EDDDDD809CFC9D2C47E4CF4C5D7EDEA6815',
            'registered/COC7th核心规则书v1.2.1.pdf', 'authorized', 'test'
        )
        """
    )
    test_db.execute(
        """
        INSERT INTO rule_sets (
            rule_set_id, name, slug, system, is_base, license_type, status, created_by
        ) VALUES ('official-set', 'CoC7 Core', 'official-coc7-gated', 'coc7', TRUE, 'authorized', 'draft', 'test')
        """
    )
    test_db.execute(
        """
        INSERT INTO rule_set_versions (
            rule_set_version_id, rule_set_id, version_number, status, source_sha256,
            metadata, created_by
        ) VALUES (
            'official-v1', 'official-set', 1, 'draft',
            '22F5F56B7A0989CBDED695D39C7D5EDDDDD809CFC9D2C47E4CF4C5D7EDEA6815',
            '{"official_source_document_id":"official-source"}', 'test'
        )
        """
    )
    test_db.execute(
        """
        INSERT INTO rule_version_publication_gates (rule_set_version_id, status)
        VALUES ('official-v1', 'pending_review')
        """
    )
    return "official-v1"


def test_rule_docs_lists_indexed_rule_documents(client, test_db):
    setup_auth_test_data(test_db)
    token = login(client, "admin")

    test_db.execute(
        "INSERT INTO rule_documents (doc_id, title, category, content) VALUES (%s, %s, %s, %s)",
        ("rule-1", "COC7th核心规则书v1.2.1.pdf", "coc7-core-rules", "abcdef"),
    )
    test_db.execute(
        "INSERT INTO document_chunks (chunk_id, source_type, source_id, content, metadata) "
        "VALUES (%s, %s, %s, %s, %s)",
        ("chunk-1", "rule", "rule-1", "技能检定", json.dumps({"index": 0})),
    )
    test_db.execute(
        "INSERT INTO document_chunks (chunk_id, source_type, source_id, content, metadata) "
        "VALUES (%s, %s, %s, %s, %s)",
        ("chunk-2", "rule", "rule-1", "理智检定", json.dumps({"index": 1})),
    )
    test_db.commit()

    resp = client.get("/api/rag/rule-docs", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json() == [
        {
            "doc_id": "rule-1",
            "title": "COC7th核心规则书v1.2.1.pdf",
            "category": "coc7-core-rules",
            "content_chars": 6,
            "chunks": 2,
        }
    ]


def test_publishing_base_coc7_rules_binds_existing_published_scenarios(client, test_db):
    setup_auth_test_data(test_db)
    token = login(client, "admin")
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        "/api/rag/rule-sets",
        headers=headers,
        json={
            "name": "CoC7 Core",
            "slug": "coc7",
            "system": "coc7",
            "license_type": "authorized",
            "is_base": True,
        },
    )
    assert created.status_code == 200
    rule_set_id = created.json()["rule_set_id"]

    version = client.post(
        f"/api/rag/rule-sets/{rule_set_id}/versions",
        headers=headers,
        json={"label": "local-test-v1"},
    )
    assert version.status_code == 200
    rule_set_version_id = version.json()["rule_set_version_id"]

    published = client.post(
        f"/api/rag/rule-set-versions/{rule_set_version_id}/publish",
        headers=headers,
    )

    assert published.status_code == 200
    published_version = test_db.execute(
        "SELECT runtime_eligible FROM rule_set_versions "
        "WHERE rule_set_version_id = %s",
        (rule_set_version_id,),
    ).fetchone()
    publication_gate = test_db.execute(
        "SELECT status FROM rule_version_publication_gates "
        "WHERE rule_set_version_id = %s",
        (rule_set_version_id,),
    ).fetchone()
    assert published_version == {"runtime_eligible": True}
    assert publication_gate == {"status": "ready"}
    binding = test_db.execute(
        "SELECT rule_set_version_id, priority FROM scenario_rule_bindings "
        "WHERE scenario_version_id = 'sv-sc-test'"
    ).fetchone()
    assert binding == {
        "rule_set_version_id": rule_set_version_id,
        "priority": 100,
    }


def test_publishing_official_rules_rejects_an_unreviewed_gate(client, test_db):
    setup_auth_test_data(test_db)
    token = login(client, "admin")
    rule_set_version_id = _insert_unreviewed_official_version(test_db)

    response = client.post(
        f"/api/rag/rule-set-versions/{rule_set_version_id}/publish",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "rule_version_gate_not_ready"


def test_publishing_official_rules_rejects_a_missing_page_source_part(client, test_db):
    """A ready gate does not override missing page-level source evidence."""
    setup_auth_test_data(test_db)
    token = login(client, "admin")
    rule_set_version_id = _insert_unreviewed_official_version(test_db)
    test_db.execute(
        "UPDATE rule_version_publication_gates SET status = 'ready' "
        "WHERE rule_set_version_id = %s",
        (rule_set_version_id,),
    )
    for page_number in range(1, 381):
        test_db.execute(
            "INSERT INTO rule_source_pages "
            "(rule_source_page_id, source_document_id, page_number, extraction_status, text_sha256, extraction_method) "
            "VALUES (%s, 'official-source', %s, 'indexable', %s, 'test')",
            (f'official-page-{page_number}', page_number, f'page-{page_number}'),
        )
        if page_number != 380:
            test_db.execute(
                "INSERT INTO source_parts "
                "(source_part_id, source_document_id, ordinal, part_kind, page_number, text_content, checksum) "
                "VALUES (%s, 'official-source', %s, 'page', %s, 'page', %s)",
                (f'official-part-{page_number}', page_number, page_number, f'part-{page_number}'),
            )
    test_db.commit()

    response = client.post(
        f"/api/rag/rule-set-versions/{rule_set_version_id}/publish",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "rule_version_gate_not_ready"


def test_publishing_local_test_rules_is_rejected_without_reactivation(client, test_db):
    """A retired local fixture must never be made runnable through publish."""
    setup_auth_test_data(test_db)
    test_db.execute(
        "INSERT INTO rule_sets (rule_set_id, name, slug, system, license_type, status, created_by) "
        "VALUES ('retired-local-set', 'Retired local', 'retired-local', 'coc7', 'authorized', 'published', 'test')"
    )
    test_db.execute(
        "INSERT INTO rule_set_versions (rule_set_version_id, rule_set_id, version_number, status, "
        "runtime_eligible, metadata, created_by) "
        "VALUES ('retired-local-v1', 'retired-local-set', 1, 'published', FALSE, "
        "'{\"local_test_only\": true}', 'test')"
    )
    test_db.execute(
        "INSERT INTO rule_version_publication_gates (rule_set_version_id, status) "
        "VALUES ('retired-local-v1', 'pending')"
    )
    test_db.commit()

    response = client.post(
        "/api/rag/rule-set-versions/retired-local-v1/publish",
        headers={"Authorization": f"Bearer {login(client, 'admin')}"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "rule_version_retired"
    assert test_db.execute(
        "SELECT runtime_eligible FROM rule_set_versions WHERE rule_set_version_id = 'retired-local-v1'"
    ).fetchone() == {"runtime_eligible": False}
    assert test_db.execute(
        "SELECT status FROM rule_version_publication_gates WHERE rule_set_version_id = 'retired-local-v1'"
    ).fetchone() == {"status": "pending"}


def test_authoritative_audit_is_not_available_to_a_host(client, test_db):
    setup_auth_test_data(test_db)
    token = login(client, "testhost")

    response = client.get(
        "/api/rag/rule-set-versions/official-v1/audit",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_current_authoritative_audit_uses_the_registered_official_source(client, test_db):
    setup_auth_test_data(test_db)
    rule_set_version_id = _insert_unreviewed_official_version(test_db)

    response = client.get(
        "/api/rag/coc7/authoritative-audit",
        headers={"Authorization": f"Bearer {login(client, 'admin')}"},
    )

    assert response.status_code == 200
    assert response.json()["rule_set_version_id"] == rule_set_version_id
    assert response.json()["source"]["filename"] == "COC7th核心规则书v1.2.1.pdf"


def test_current_authoritative_audit_remains_admin_only(client, test_db):
    setup_auth_test_data(test_db)
    _insert_unreviewed_official_version(test_db)

    response = client.get(
        "/api/rag/coc7/authoritative-audit",
        headers={"Authorization": f"Bearer {login(client, 'testhost')}"},
    )

    assert response.status_code == 403


def test_rule_bindings_reject_a_published_but_runtime_ineligible_version(client, test_db):
    """Publishing status alone cannot attach an ineligible legacy ruleset."""
    setup_auth_test_data(test_db)
    admin_token = login(client, "admin")
    host_token = login(client, "testhost")
    test_db.execute(
        "INSERT INTO rooms (room_id, scenario_id, scenario_version_id, owner_token, owner_account_id) "
        "VALUES ('binding-room', 'sc-test', 'sv-sc-test', 'owner', 'acc-host')"
    )
    test_db.execute(
        "INSERT INTO rule_sets (rule_set_id, name, slug, system, license_type, status, created_by) "
        "VALUES ('legacy-set', 'Legacy', 'legacy-binding', 'coc7', 'authorized', 'published', 'test')"
    )
    test_db.execute(
        "INSERT INTO rule_set_versions (rule_set_version_id, rule_set_id, version_number, status, "
        "runtime_eligible, metadata, created_by) "
        "VALUES ('legacy-v1', 'legacy-set', 1, 'published', FALSE, "
        "'{\"local_test_only\": true}', 'test')"
    )
    test_db.commit()

    room_response = client.post(
        "/api/rag/rule-bindings/rooms/binding-room",
        headers={"Authorization": f"Bearer {host_token}"},
        json={"rule_set_version_id": "legacy-v1"},
    )
    scenario_response = client.post(
        "/api/rag/rule-bindings/scenarios/sv-sc-test",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"rule_set_version_id": "legacy-v1"},
    )

    assert room_response.status_code == 409
    assert scenario_response.status_code == 409
