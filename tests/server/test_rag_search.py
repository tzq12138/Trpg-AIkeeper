from contextlib import contextmanager

from src.server.ai.rag import RAGStore


class FakeEmbedding:
    def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeCursor:
    def __init__(self):
        self.executed = None
        self.call_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.call_count += 1
        self.executed = (sql, params)
        # First call is the rooms lookup (when room_id provided)
        if "scenario_id FROM rooms" in sql:
            return
        # Main search query
        assert len(params) >= 3, f"Expected at least 3 params, got {len(params)}: {params}"
        assert params[0] == [0.1, 0.2, 0.3]
        assert params[1] == [0.1, 0.2, 0.3]
        assert params[2] == 5

    def fetchall(self):
        return []

    def fetchone(self):
        return {"scenario_id": "sc-1"}


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()

    def cursor(self):
        return self.cursor_obj


class FakePgDb:
    def __init__(self):
        self.conn = FakeConnection()

    @contextmanager
    def get_conn(self):
        yield self.conn


def test_search_binds_vector_and_limit_once_without_filters():
    pg_db = FakePgDb()
    store = RAGStore(pg_db, FakeEmbedding())

    assert store.search("调查房间") == []


def test_search_keeps_filter_params_before_vector_params():
    call_count = [0]

    class FilterCursor(FakeCursor):
        def execute(self, sql, params):
            call_count[0] += 1
            self.executed = (sql, params)
            # First call: rooms lookup for scenario_id
            if call_count[0] == 1:
                assert "scenario_id FROM rooms" in sql
                assert params == ("room-1",)
                return
            # Second call: main search query
            assert "room_id = %s" in sql
            assert "source_type IN (%s,%s)" in sql
            # query_params structure: [query_vec, *filter_params, query_vec, top_k]
            n = len(params)
            assert params[0] == [0.1, 0.2, 0.3]        # first query_vec
            assert params[n - 2] == [0.1, 0.2, 0.3]    # second query_vec
            assert params[n - 1] == 2                    # top_k

        def fetchone(self):
            return {"scenario_id": "sc-1"}

    pg_db = FakePgDb()
    pg_db.conn.cursor_obj = FilterCursor()
    store = RAGStore(pg_db, FakeEmbedding())

    assert store.search("线索", room_id="room-1", source_types=["scenario", "rule"], top_k=2) == []
