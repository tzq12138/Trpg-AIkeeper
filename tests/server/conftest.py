import os
import re
import pytest
import psycopg2
from src.server.db_adapter import PgDatabase
from src.server.engine.engine import Engine
from src.server.main import app
from src.server.router_auth import _hash_password
from fastapi.testclient import TestClient

# ── Test database safety ─────────────────────────────────────────────

_DEFAULT_TEST_DB = "postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper_test"


def _validate_test_db_url(url: str) -> str:
    """Refuse to run if the database name does NOT contain 'test'."""
    # Parse dbname from DSN: postgresql://user:pass@host:port/dbname
    m = re.search(r"/([^/?]+)(?:\?|$)", url)
    dbname = (m.group(1) if m else "").lower()
    if "test" not in dbname:
        raise RuntimeError(
            f"REFUSING to run tests against non-test database: {url}\n"
            f"Set TEST_DATABASE_URL to a database name containing 'test' "
            f"(e.g. {_DEFAULT_TEST_DB})."
        )
    return url


def _ensure_test_db_exists(dsn: str) -> None:
    """Create the test database if it does not already exist."""
    # Rewrite DSN to connect to 'postgres' maintenance database
    maint_dsn = re.sub(r"/[^/?]+(\?|$)", "/postgres\\1", dsn)
    try:
        maint_conn = psycopg2.connect(maint_dsn)
        maint_conn.autocommit = True
        cur = maint_conn.cursor()
        dbname = dsn.rsplit("/", 1)[-1].split("?")[0]
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
        if cur.fetchone() is None:
            cur.execute(f'CREATE DATABASE "{dbname}"')
        cur.close()
        maint_conn.close()
    except Exception as e:
        # If we can't create it, let the fixture fail naturally with a clear error
        pass


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from src.server.player.router_player import _join_attempts
    _join_attempts.clear()
    yield
    _join_attempts.clear()


@pytest.fixture
def test_db():
    test_url = _validate_test_db_url(os.getenv("TEST_DATABASE_URL", _DEFAULT_TEST_DB))
    _ensure_test_db_exists(test_url)
    pg = PgDatabase(dsn=test_url)
    pg.connect()
    pg.initialize()
    conn = pg.get_connection()
    conn.execute(
        "TRUNCATE TABLE clarifications, clue_shares, clues, objectives, inventory, "
        "actions, events, player_sequences, checkpoints, campaign_archives, "
        "document_chunks, host_states, characters, rooms, scenarios, rule_documents, "
        "spoiler_sensitive_items, spoiler_audits, "
        "character_profiles, character_runtime_state, room_scene_state, "
        "accounts, ai_call_logs "
        "RESTART IDENTITY CASCADE"
    )
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


# ── Shared helpers for authenticated test setup ──

def create_account(conn, account_id: str, username: str, role: str, password: str = "test123"):
    """Insert account using ON CONFLICT for idempotent test fixtures."""
    conn.execute(
        "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (username) DO UPDATE "
        "SET role = %s, account_id = EXCLUDED.account_id",
        (account_id, username, _hash_password(password), username, role, role),
    )


def create_scenario(conn, scenario_id: str = "sc-test", title: str = "Test Scenario"):
    """Insert a structured scenario for test rooms."""
    conn.execute(
        "INSERT INTO scenarios (scenario_id, title, raw_text, import_status) "
        "VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (scenario_id) DO NOTHING",
        (scenario_id, title, "Test content", "structured"),
    )


def login(client, username: str = "testhost", password: str = "test123") -> str:
    """Login and return Bearer token."""
    res = client.post("/api/auth/login", json={
        "username": username, "password": password,
    })
    assert res.status_code == 200, f"Login failed for {username}: {res.text}"
    return res.json()["token"]


def create_room(client, token: str = None, scenario_id: str = "sc-test") -> dict:
    """Create a room with auth and return room data."""
    if token is None:
        token = login(client)
    res = client.post(
        "/api/rooms",
        json={"scenario_id": scenario_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, f"Create room failed: {res.text}"
    return res.json()


def setup_auth_test_data(conn):
    """Set up common auth test accounts and scenario. Idempotent."""
    for aid, uname, role in [
        ("acc-admin", "admin", "admin"),
        ("acc-host", "testhost", "host"),
        ("acc-player", "testplayer", "player"),
    ]:
        create_account(conn, aid, uname, role)
    create_scenario(conn)
    conn.commit()
