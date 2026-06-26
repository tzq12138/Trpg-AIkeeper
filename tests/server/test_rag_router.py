import json


def test_rule_docs_lists_indexed_rule_documents(client, test_db):
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

    resp = client.get("/api/rag/rule-docs")

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
