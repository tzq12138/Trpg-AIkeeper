import pytest
from src.server.db_adapter import _translate_sql, PgCursorWrapper, PgConnection, PgDatabase


class TestTranslateSql:
    def test_single_placeholder(self):
        sql = "SELECT * FROM rooms WHERE room_id = ?"
        assert _translate_sql(sql) == "SELECT * FROM rooms WHERE room_id = %s"

    def test_multiple_placeholders(self):
        sql = "INSERT INTO rooms (room_id, owner_token) VALUES (?, ?)"
        assert _translate_sql(sql) == "INSERT INTO rooms (room_id, owner_token) VALUES (%s, %s)"

    def test_no_placeholders(self):
        sql = "SELECT * FROM rooms"
        assert _translate_sql(sql) == "SELECT * FROM rooms"

    def test_question_mark_in_string_literal(self):
        sql = "SELECT * FROM rooms WHERE status = 'what?'"
        assert _translate_sql(sql) == "SELECT * FROM rooms WHERE status = 'what%s'"

    def test_complex_query(self):
        sql = "INSERT INTO events (room_id, event_type, audience, payload) VALUES (?, ?, ?, ?)"
        expected = "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, %s, %s)"
        assert _translate_sql(sql) == expected

    def test_update_with_where(self):
        sql = "UPDATE rooms SET status = ? WHERE room_id = ?"
        assert _translate_sql(sql) == "UPDATE rooms SET status = %s WHERE room_id = %s"

    def test_delete_with_placeholder(self):
        sql = "DELETE FROM characters WHERE character_id = ?"
        assert _translate_sql(sql) == "DELETE FROM characters WHERE character_id = %s"


@pytest.fixture
def pg_db():
    db = PgDatabase()
    try:
        pool = db.connect()
        db.initialize()
        yield db
        db.close()
    except Exception:
        pytest.skip('PostgreSQL not available')


@pytest.fixture
def pg_conn(pg_db):
    conn = pg_db.get_connection()
    yield conn
    conn.close()


class TestPgConnectionIntegration:
    def test_execute_select(self, pg_conn):
        pg_conn.execute(
            "INSERT INTO rooms (room_id, owner_token) VALUES (?, ?)",
            ('test-adapter-1', 'token-1'),
        )
        row = pg_conn.execute(
            "SELECT * FROM rooms WHERE room_id = ?",
            ('test-adapter-1',),
        ).fetchone()
        assert row is not None
        assert row['room_id'] == 'test-adapter-1'

    def test_execute_fetchall(self, pg_conn):
        pg_conn.execute(
            "INSERT INTO rooms (room_id, owner_token) VALUES (?, ?)",
            ('test-adapter-2', 'token-2'),
        )
        pg_conn.execute(
            "INSERT INTO rooms (room_id, owner_token) VALUES (?, ?)",
            ('test-adapter-3', 'token-3'),
        )
        rows = pg_conn.execute("SELECT * FROM rooms WHERE room_id LIKE ?", ('test-adapter-%',)).fetchall()
        assert len(rows) >= 2

    def test_execute_returns_none_on_empty(self, pg_conn):
        row = pg_conn.execute(
            "SELECT * FROM rooms WHERE room_id = ?",
            ('nonexistent',),
        ).fetchone()
        assert row is None

    def test_executescript(self, pg_conn):
        pg_conn.executescript(
            "INSERT INTO rooms (room_id, owner_token) VALUES ('script-test', 'token-s')"
        )
        row = pg_conn.execute(
            "SELECT * FROM rooms WHERE room_id = ?",
            ('script-test',),
        ).fetchone()
        assert row is not None
        assert row['room_id'] == 'script-test'

    def test_insert_auto_commits(self, pg_conn):
        pg_conn.execute(
            "INSERT INTO rooms (room_id, owner_token) VALUES (?, ?)",
            ('auto-commit-test', 'token-ac'),
        )
        conn2 = pg_conn._pool.getconn()
        try:
            cur = conn2.cursor()
            cur.execute("SELECT * FROM rooms WHERE room_id = %s", ('auto-commit-test',))
            row = cur.fetchone()
            assert row is not None
            assert row['room_id'] == 'auto-commit-test'
        finally:
            pg_conn._pool.putconn(conn2)

    def test_rowcount(self, pg_conn):
        pg_conn.execute(
            "INSERT INTO rooms (room_id, owner_token) VALUES (?, ?)",
            ('rowcount-test', 'token-rc'),
        )
        wrapper = pg_conn.execute(
            "UPDATE rooms SET status = ? WHERE room_id = ?",
            ('active', 'rowcount-test'),
        )
        assert wrapper.rowcount == 1

    def test_dict_like_row_access(self, pg_conn):
        pg_conn.execute(
            "INSERT INTO rooms (room_id, owner_token, status) VALUES (?, ?, ?)",
            ('dict-test', 'token-d', 'lobby'),
        )
        row = pg_conn.execute(
            "SELECT room_id, owner_token, status FROM rooms WHERE room_id = ?",
            ('dict-test',),
        ).fetchone()
        assert row['room_id'] == 'dict-test'
        assert row['owner_token'] == 'token-d'
        assert row['status'] == 'lobby'
        assert dict(row)['room_id'] == 'dict-test'

    def test_characters_insert_with_jsonb(self, pg_conn):
        pg_conn.execute(
            "INSERT INTO rooms (room_id, owner_token) VALUES (?, ?)",
            ('jsonb-test', 'token-j'),
        )
        pg_conn.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) VALUES (?, ?, ?, ?, ?)",
            ('char-1', 'jsonb-test', 'Player1', 'ptoken-1', '{"str": 10}'),
        )
        row = pg_conn.execute(
            "SELECT * FROM characters WHERE character_id = ?",
            ('char-1',),
        ).fetchone()
        assert row is not None
        assert row['character_id'] == 'char-1'
