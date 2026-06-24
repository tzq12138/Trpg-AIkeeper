import pytest
from src.server.db_adapter import PgDatabase
from src.server.engine import Engine
from src.server.main import app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from src.server.router_player import _join_attempts
    _join_attempts.clear()
    yield
    _join_attempts.clear()


@pytest.fixture
def test_db():
    pg = PgDatabase()
    pg.connect()
    pg.initialize()
    conn = pg.get_connection()
    yield conn
    conn.close()
    pg.close()


@pytest.fixture
def engine(test_db):
    return Engine(test_db)


@pytest.fixture
def client(test_db):
    c = TestClient(app)
    app.state.db = test_db
    app.state.engine = Engine(test_db)
    return c
