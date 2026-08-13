import json
from contextlib import contextmanager

import pytest

from src.server.ai.rag import RAGStore, _cjk_lexical_patterns


class FakeEmbedding:
    def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class NamedEmbedding(FakeEmbedding):
    model_name = "embedding-v2"


class BrokenEmbedding:
    def embed(self, texts):
        raise RuntimeError("embedding offline")


class SearchCursor:
    def __init__(self, room=None, rows=None):
        self.room = room
        self.rows = rows or []
        self.main_sql = ""
        self.main_params = []
        self._room_lookup = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        if "FROM rooms" in sql and "scenario_version_id" in sql:
            self._room_lookup = True
            return
        self._room_lookup = False
        self.main_sql = sql
        self.main_params = list(params)

    def fetchone(self):
        return self.room if self._room_lookup else None

    def fetchall(self):
        return self.rows


class SearchConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor

    def cursor(self):
        return self.cursor_obj


class FakePgDb:
    def __init__(self, cursor):
        self.conn = SearchConnection(cursor)

    @contextmanager
    def get_conn(self):
        yield self.conn


def _row():
    return {
        "chunk_id": "chunk-1",
        "source_type": "scenario",
        "source_id": "sc-1",
        "source_part_id": "part-1",
        "scenario_version_id": "sv-1",
        "content": "the exact black key is beneath the altar",
        "metadata": json.dumps({"legacy": True}),
        "citation": json.dumps({"source_ref": "page:3", "page_number": 3}),
        "visibility": "party",
        "similarity": 0.75,
        "lexical_score": 1.0,
        "score": 0.8125,
    }


def test_search_keeps_legacy_positional_arguments_and_returns_citation():
    cursor = SearchCursor(
        room={"scenario_id": "sc-1", "scenario_version_id": "sv-1"},
        rows=[_row()],
    )
    store = RAGStore(FakePgDb(cursor), FakeEmbedding())

    results = store.search("black key", "room-1", ["scenario", "rule"], 2)

    assert len(results) == 1
    assert results[0]["citation"]["chunk_id"] == "chunk-1"
    assert results[0]["citation"]["scenario_version_id"] == "sv-1"
    assert results[0]["citation"]["source_ref"] == "page:3"
    assert "source_type IN" in cursor.main_sql
    assert "scenario_version_id" in cursor.main_sql
    assert cursor.main_params[-1] == 2


def test_search_player_acl_only_allows_public_and_party():
    cursor = SearchCursor(room={"scenario_id": "sc-1", "scenario_version_id": "sv-1"})
    store = RAGStore(FakePgDb(cursor), FakeEmbedding())

    store.search("clue", room_id="room-1", audience="player")

    assert "visibility IN" in cursor.main_sql
    assert "public" in cursor.main_params
    assert "party" in cursor.main_params
    assert "host_only" not in cursor.main_params
    assert "internal" not in cursor.main_params


def test_search_host_acl_includes_host_only_but_not_internal():
    cursor = SearchCursor(room={"scenario_id": "sc-1", "scenario_version_id": "sv-1"})
    store = RAGStore(FakePgDb(cursor), FakeEmbedding())

    store.search("clue", room_id="room-1", audience="host")

    assert "public" in cursor.main_params
    assert "party" in cursor.main_params
    assert "host_only" in cursor.main_params
    assert "internal" not in cursor.main_params


def test_search_admin_can_target_an_explicit_scenario_version():
    cursor = SearchCursor(rows=[_row()])
    store = RAGStore(FakePgDb(cursor), FakeEmbedding())

    store.search("truth", audience="admin", scenario_version_id="sv-1")

    assert "scenario_version_id = %s" in cursor.main_sql
    assert "scenario_rule_bindings" in cursor.main_sql
    assert "rule_set_version_id IN" in cursor.main_sql
    assert "sv-1" in cursor.main_params
    assert cursor.main_params.count("sv-1") == 2
    assert "visibility IN" not in cursor.main_sql


def test_search_admin_can_target_an_explicit_rule_set_version():
    cursor = SearchCursor(rows=[_row()])
    store = RAGStore(FakePgDb(cursor), FakeEmbedding())

    store.search("奖励骰", audience="admin", rule_set_version_id="rules-v1")

    assert "rule_set_version_id = %s" in cursor.main_sql
    assert "rules-v1" in cursor.main_params


def test_explicit_rule_version_still_requires_a_runtime_qualified_version():
    """An administrator-supplied ID must not revive a retired rule version."""
    cursor = SearchCursor(rows=[_row()])
    store = RAGStore(FakePgDb(cursor), FakeEmbedding())

    store.search("幸运值如何回复", audience="admin", rule_set_version_id="legacy-v1")

    assert "source_type <> 'rule' OR EXISTS" in cursor.main_sql
    assert "qualified_rsv.status = 'published'" in cursor.main_sql
    assert "qualified_rsv.runtime_eligible = TRUE" in cursor.main_sql
    assert "qualified_rs.status = 'published'" in cursor.main_sql
    assert "qualified_gate.status = 'ready'" in cursor.main_sql
    assert "legacy-v1" in cursor.main_params


def test_room_rule_scope_uses_room_then_scenario_then_published_base_bindings():
    cursor = SearchCursor(room={"scenario_id": "sc-1", "scenario_version_id": "sv-1"})
    store = RAGStore(FakePgDb(cursor), FakeEmbedding())

    store.search("追逐", room_id="room-1", source_types=["rule"])

    assert "room_rule_bindings" in cursor.main_sql
    assert "scenario_rule_bindings" in cursor.main_sql
    assert "rule_set_versions" in cursor.main_sql
    assert "is_base" in cursor.main_sql
    assert "rule_priority" in cursor.main_sql
    assert "ORDER BY rule_priority DESC" in cursor.main_sql


def test_search_uses_vector_and_lexical_scores_together():
    cursor = SearchCursor(rows=[_row()])
    store = RAGStore(FakePgDb(cursor), FakeEmbedding())

    results = store.search("black key")

    assert "embedding <=>" in cursor.main_sql
    assert "ILIKE" in cursor.main_sql
    assert "lexical_score" in cursor.main_sql
    assert results[0]["score"] == 0.8125


def test_cjk_rule_query_adds_character_lexical_candidates_after_question_words():
    """Chinese wording needs compact lexical evidence in addition to embeddings."""
    cursor = SearchCursor(rows=[_row()])
    store = RAGStore(FakePgDb(cursor), FakeEmbedding())

    store.search("孤注一掷失败会发生什么", source_types=["rule"])

    patterns = _cjk_lexical_patterns("孤注一掷失败会发生什么")
    assert "孤注" in patterns
    assert "一掷" in patterns
    assert "什么" not in patterns
    assert "%孤注%" in cursor.main_params
    assert "%一掷%" in cursor.main_params
    assert "lexical_evidence" in cursor.main_sql


def test_low_relevance_rule_rows_are_discarded_without_affecting_other_sources():
    """Rule-only safety thresholds must reject unsupported rules, not scenario prose."""
    low_score_rule = _row()
    low_score_rule.update({
        "source_type": "rule",
        "similarity": 0.0,
        "lexical_score": 0.0,
        "score": 0.0,
    })
    rule_store = RAGStore(
        FakePgDb(SearchCursor(rows=[low_score_rule])),
        FakeEmbedding(),
    )
    scenario_store = RAGStore(
        FakePgDb(SearchCursor(rows=[dict(low_score_rule, source_type="scenario")])),
        FakeEmbedding(),
    )

    assert rule_store.search("量子护盾", source_types=["rule"]) == []
    assert len(scenario_store.search("量子护盾", source_types=["scenario"])) == 1


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("幸运值如何回复", ["幸运", "运值", "值回", "回复"]),
        ("孤注一掷失败会发生什么", ["孤注", "一掷", "掷失", "失败"]),
    ],
)
def test_cjk_lexical_patterns_keep_relevant_two_character_candidates(query, expected):
    """Question filler is removed before candidates are generated."""
    patterns = _cjk_lexical_patterns(query)

    assert all(candidate in patterns for candidate in expected)


def test_search_only_scores_vectors_from_the_current_embedding_space():
    cursor = SearchCursor(rows=[_row()])
    store = RAGStore(FakePgDb(cursor), NamedEmbedding())

    store.search("black key")

    assert "embedding_model = %s" in cursor.main_sql
    assert "embedding_dimensions = %s" in cursor.main_sql
    assert cursor.main_params[:3] == ["embedding-v2", 3, [0.1, 0.2, 0.3]]


def test_search_falls_back_to_lexical_when_embedding_is_unavailable():
    cursor = SearchCursor(rows=[_row()])
    store = RAGStore(FakePgDb(cursor), BrokenEmbedding())

    results = store.search("black key")

    assert "embedding <=>" not in cursor.main_sql
    assert "ILIKE" in cursor.main_sql
    assert cursor.main_params[-1] == 5
    assert results[0]["citation"]["excerpt"].startswith("the exact black key")


def test_search_clamps_top_k_to_safe_range():
    cursor = SearchCursor()
    store = RAGStore(FakePgDb(cursor), FakeEmbedding())

    store.search("q", top_k=999)

    assert cursor.main_params[-1] == 50


def test_search_legacy_room_without_version_keeps_legacy_scenario_scope():
    cursor = SearchCursor(room={"scenario_id": "legacy-sc", "scenario_version_id": None})
    store = RAGStore(FakePgDb(cursor), FakeEmbedding())

    store.search("legacy clue", room_id="legacy-room")

    assert "legacy-sc" in cursor.main_params
    assert "AND scenario_version_id = %s" not in cursor.main_sql
    assert "scenario_version_id IS NULL" in cursor.main_sql


def test_bound_room_does_not_allow_room_local_legacy_scenario_bypass():
    cursor = SearchCursor(room={"scenario_id": "sc-1", "scenario_version_id": "sv-1"})
    store = RAGStore(FakePgDb(cursor), FakeEmbedding())

    store.search("clue", room_id="room-1")

    assert "room_id = %s AND source_type NOT IN" in cursor.main_sql
    assert "scenario_version_id = %s" in cursor.main_sql


def test_search_sanitizes_absolute_paths_from_citation_excerpt():
    row = _row()
    row["content"] = "source C:\\secret\\scenario.pdf contains the clue"
    row["citation"] = "{}"
    cursor = SearchCursor(rows=[row])
    store = RAGStore(FakePgDb(cursor), FakeEmbedding())

    result = store.search("clue")[0]

    assert "C:\\secret" not in result["citation"]["excerpt"]
    assert "[redacted-path]" in result["citation"]["excerpt"]


def test_search_sanitizes_unc_paths_from_citation_excerpt():
    row = _row()
    row["content"] = r"source \\server\share\scenario.pdf contains the clue"
    row["citation"] = "{}"
    cursor = SearchCursor(rows=[row])
    store = RAGStore(FakePgDb(cursor), FakeEmbedding())

    result = store.search("clue")[0]

    assert r"\\server\share" not in result["citation"]["excerpt"]
    assert "[redacted-path]" in result["citation"]["excerpt"]


def test_search_sanitizes_embedded_paths_in_citation_source_ref_and_anchor():
    row = _row()
    row["citation"] = json.dumps({
        "source_ref": r"imported from C:\secret\scenario.pdf page 3",
        "anchor": {"note": r"cached at \\server\share\scenario.pdf"},
    })
    cursor = SearchCursor(rows=[row])
    store = RAGStore(FakePgDb(cursor), FakeEmbedding())

    citation = store.search("clue")[0]["citation"]

    serialized = json.dumps(citation)
    assert "C:\\\\secret" not in serialized
    assert "server\\\\share" not in serialized
    assert serialized.count("[redacted-path]") == 2
