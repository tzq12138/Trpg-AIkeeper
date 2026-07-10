import json
from contextlib import contextmanager

import pytest

from src.server.ai.rag import RAGStore


class FakeEmbedding:
    model_name = "fake-embedding-v1"

    def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class ShortEmbedding(FakeEmbedding):
    def embed(self, texts):
        return [[0.1, 0.2, 0.3]] if texts else []


class RecordingCursor:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.calls.append((sql, tuple(params)))


class RecordingConnection:
    def __init__(self):
        self.cursor_obj = RecordingCursor()

    def cursor(self):
        return self.cursor_obj


class RecordingDb:
    def __init__(self):
        self.conn = RecordingConnection()

    @contextmanager
    def get_conn(self):
        yield self.conn


def _insert_rows(cursor):
    rows = []
    for sql, params in cursor.calls:
        if "INSERT INTO document_chunks" not in sql:
            continue
        column_text = sql.split("(", 1)[1].split(")", 1)[0]
        columns = [column.strip() for column in column_text.split(",")]
        rows.append(dict(zip(columns, params)))
    return rows


def test_index_scenario_version_preserves_source_anchors_and_embedding_metadata():
    db = RecordingDb()
    store = RAGStore(db, FakeEmbedding())
    text = "C:\\secret\\module.pdf " + ("A" * 700)

    count = store.index_scenario_version(
        "sc-1",
        "sv-1",
        [{
            "source_part_id": "part-1",
            "text": text,
            "page_number": 7,
            "source_ref": "page:7",
            "anchor": {"page": 7},
        }],
        visibility="internal",
    )

    rows = _insert_rows(db.conn.cursor_obj)
    assert count == 2
    assert len(rows) == 2
    assert all(row["source_part_id"] == "part-1" for row in rows)
    assert all(row["scenario_version_id"] == "sv-1" for row in rows)
    assert all(row["visibility"] == "internal" for row in rows)
    assert all(row["embedding_model"] == "fake-embedding-v1" for row in rows)
    assert all(row["embedding_dimensions"] == 3 for row in rows)

    first_citation = json.loads(rows[0]["citation"])
    second_citation = json.loads(rows[1]["citation"])
    assert first_citation["source_ref"] == "page:7"
    assert first_citation["page_number"] == 7
    assert first_citation["anchor"] == {"page": 7}
    assert first_citation["start_offset"] == 0
    assert first_citation["end_offset"] == 500
    assert second_citation["start_offset"] == 450
    assert "C:\\secret" not in json.dumps(first_citation)
    assert "[redacted-path]" in first_citation["excerpt"]


def test_index_scenario_version_is_idempotent_without_deleting_other_versions():
    db = RecordingDb()
    store = RAGStore(db, FakeEmbedding())
    parts = [{"source_part_id": "part-1", "text": "enough scenario text"}]

    store.index_scenario_version("sc-1", "sv-1", parts)
    store.index_scenario_version("sc-1", "sv-2", parts)

    deletes = [
        params
        for sql, params in db.conn.cursor_obj.calls
        if "DELETE FROM document_chunks" in sql
    ]
    assert deletes == [("scenario", "sv-1"), ("scenario", "sv-2")]


def test_legacy_scenario_reindex_never_deletes_versioned_snapshots():
    db = RecordingDb()
    store = RAGStore(db, FakeEmbedding())

    store.index_scenario("sc-1", "legacy scenario text")

    delete_sql = next(
        sql for sql, _params in db.conn.cursor_obj.calls
        if "DELETE FROM document_chunks" in sql
    )
    assert "scenario_version_id IS NULL" in delete_sql


def test_version_index_rejects_partial_embedding_batches_before_deleting_old_index():
    db = RecordingDb()
    store = RAGStore(db, ShortEmbedding())
    parts = [{"source_part_id": "part-1", "text": "A" * 700}]

    with pytest.raises(RuntimeError, match="embedding_count_mismatch"):
        store.index_scenario_version("sc-1", "sv-1", parts)

    assert db.conn.cursor_obj.calls == []


def test_index_rules_preserves_rule_version_license_and_citation():
    db = RecordingDb()
    store = RAGStore(db, FakeEmbedding())

    count = store.index_rules(
        "rule-doc-1",
        "CoC7 技能检定",
        "checks",
        "奖励骰取较低的完整百分骰结果。",
        rule_set_version_id="rules-v1",
        source_part_id="rule-part-4",
        visibility="host_only",
        license_type="open",
        source_ref="coc7-srd#page=4",
        citation_base={"page_number": 4, "anchor": {"page": 4}},
    )

    rows = _insert_rows(db.conn.cursor_obj)
    assert count == 1
    assert rows[0]["rule_set_version_id"] == "rules-v1"
    assert rows[0]["source_part_id"] == "rule-part-4"
    assert rows[0]["visibility"] == "host_only"
    citation = json.loads(rows[0]["citation"])
    assert citation["source_ref"] == "coc7-srd#page=4"
    assert citation["anchor"] == {"page": 4}
    assert citation["rule_set_version_id"] == "rules-v1"

    rule_upserts = [
        params for sql, params in db.conn.cursor_obj.calls
        if "INSERT INTO rule_documents" in sql
    ]
    assert rule_upserts[0][1] == "rules-v1"
    assert rule_upserts[0][7] == "open"


def test_index_npc_graph_keeps_version_snapshots_and_auditable_citations():
    db = RecordingDb()
    store = RAGStore(db, FakeEmbedding())
    graph = {
        "npcs": [{
            "npc_id": "keeper",
            "name": "守钟人",
            "public_description": "沉默的老人",
            "description": "知道地下室入口",
        }]
    }

    store.index_npc_graph("sc-1", graph, scenario_version_id="sv-1")
    store.index_npc_graph("sc-1", graph, scenario_version_id="sv-2")

    deletes = [
        params
        for sql, params in db.conn.cursor_obj.calls
        if "DELETE FROM document_chunks" in sql
    ]
    assert deletes == [
        ("npc", "sc-1", "sv-1"),
        ("npc", "sc-1", "sv-2"),
    ]
    rows = _insert_rows(db.conn.cursor_obj)
    assert [row["scenario_version_id"] for row in rows] == ["sv-1", "sv-2"]
    assert all(row["visibility"] == "internal" for row in rows)
    citations = [json.loads(row["citation"]) for row in rows]
    assert [citation["scenario_version_id"] for citation in citations] == [
        "sv-1",
        "sv-2",
    ]
    assert all(citation["source_ref"] == "worldbook:npc:keeper" for citation in citations)
