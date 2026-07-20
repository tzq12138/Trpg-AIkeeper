import json
from tests.server.conftest import setup_auth_test_data, login


def test_rule_docs_lists_indexed_rule_documents(client, test_db):
    setup_auth_test_data(test_db)
    token = login(client)

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
    binding = test_db.execute(
        "SELECT rule_set_version_id, priority FROM scenario_rule_bindings "
        "WHERE scenario_version_id = 'sv-sc-test'"
    ).fetchone()
    assert binding == {
        "rule_set_version_id": rule_set_version_id,
        "priority": 100,
    }
