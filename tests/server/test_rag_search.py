from contextlib import contextmanager

from src.server.rag import RAGStore


class FakeEmbedding:
    def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeCursor:
    def __init__(self):
        self.executed = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.executed = (sql, params)
        assert len(params) == 3
        assert params[0] == [0.1, 0.2, 0.3]
        assert params[1] == [0.1, 0.2, 0.3]
        assert params[2] == 5

    def fetchall(self):
        return []


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
    class FilterCursor(FakeCursor):
        def execute(self, sql, params):
            self.executed = (sql, params)
            assert "room_id = %s" in sql
            assert "source_type IN (%s,%s)" in sql
            assert params[0] == [0.1, 0.2, 0.3]
            assert params[1:4] == ["room-1", "scenario", "rule"]
            assert params[4] == [0.1, 0.2, 0.3]
            assert params[5] == 2

    pg_db = FakePgDb()
    pg_db.conn.cursor_obj = FilterCursor()
    store = RAGStore(pg_db, FakeEmbedding())

    assert store.search("线索", room_id="room-1", source_types=["scenario", "rule"], top_k=2) == []
