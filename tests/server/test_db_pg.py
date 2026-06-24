import pytest
from src.server.db_pg import PgDatabase


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


def test_pg_connection(pg_db):
    with pg_db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT 1 as test')
            result = cur.fetchone()
            assert result['test'] == 1


def test_pg_tables_created(pg_db):
    with pg_db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            tables = {r['table_name'] for r in cur.fetchall()}
            assert 'rooms' in tables
            assert 'characters' in tables
            assert 'document_chunks' in tables


def test_pg_vector_extension(pg_db):
    with pg_db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT extname FROM pg_extension WHERE extname='vector'")
            result = cur.fetchone()
            assert result is not None


def test_pg_insert_and_query(pg_db):
    with pg_db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO rooms (room_id, owner_token) VALUES ('test-pg-1', 'token-1') ON CONFLICT DO NOTHING")
            cur.execute("SELECT * FROM rooms WHERE room_id = 'test-pg-1'")
            room = cur.fetchone()
            assert room['room_id'] == 'test-pg-1'
