import re
import logging
from contextlib import contextmanager

import psycopg2
import psycopg2.pool
import psycopg2.extras

logger = logging.getLogger(__name__)

_placeholder_re = re.compile(r'\?')


def _translate_sql(sql: str) -> str:
    return _placeholder_re.sub('%s', sql)


SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rooms (
    room_id TEXT PRIMARY KEY,
    scenario_id TEXT,
    owner_token TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'lobby',
    spoiler_level TEXT DEFAULT 'standard',
    state_version INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    started_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS characters (
    character_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    player_name TEXT NOT NULL,
    player_token TEXT NOT NULL,
    xlsx_data JSONB,
    is_ready BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id TEXT PRIMARY KEY,
    title TEXT,
    raw_text TEXT,
    knowledge_graph JSONB,
    quality_report JSONB,
    import_status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS events (
    sequence BIGSERIAL PRIMARY KEY,
    room_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    audience TEXT NOT NULL,
    payload JSONB NOT NULL,
    issued_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS actions (
    action_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    intent_type TEXT NOT NULL,
    declared_intent TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    batch_id TEXT,
    result JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS player_sequences (
    character_id TEXT NOT NULL,
    room_id TEXT NOT NULL,
    last_delivered_sequence BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (character_id, room_id)
);

CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    state_snapshot JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS campaign_archives (
    archive_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    ending_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    highlights JSONB NOT NULL,
    character_arcs JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS clues (
    clue_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    text TEXT NOT NULL,
    source TEXT DEFAULT '',
    is_private BOOLEAN NOT NULL DEFAULT TRUE,
    discovered_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS clue_shares (
    share_id TEXT PRIMARY KEY,
    clue_id TEXT NOT NULL REFERENCES clues(clue_id),
    shared_by TEXT NOT NULL,
    shared_at TIMESTAMP NOT NULL DEFAULT NOW(),
    public_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS objectives (
    objective_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    character_id TEXT,
    text TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'team',
    status TEXT NOT NULL DEFAULT 'active',
    assigned_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS inventory (
    id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL,
    room_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    quantity INTEGER DEFAULT 1,
    is_secret BOOLEAN DEFAULT FALSE,
    source TEXT DEFAULT '',
    acquired_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS clarifications (
    clarification_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    target_action_id TEXT NOT NULL,
    text TEXT NOT NULL,
    evidence TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    window_expires_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMP,
    result JSONB
);

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    room_id TEXT,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    embedding vector(768),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_source ON document_chunks(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_chunks_room ON document_chunks(room_id);

CREATE TABLE IF NOT EXISTS host_states (
    room_id TEXT PRIMARY KEY REFERENCES rooms(room_id),
    state JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rule_documents (
    doc_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
"""


class PgCursorWrapper:
    def __init__(self, cursor, auto_commit: bool = True):
        self._cursor = cursor
        self._auto_commit = auto_commit
        self._connection = cursor.connection
        self._lastrowid = None

    def execute(self, sql, params=None):
        translated = _translate_sql(sql)
        try:
            if params is not None:
                self._cursor.execute(translated, params)
            else:
                self._cursor.execute(translated)

            if self._auto_commit:
                self._connection.commit()
        except Exception:
            if self._auto_commit:
                try:
                    self._connection.rollback()
                except Exception:
                    pass
            raise
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        if isinstance(row, dict):
            return row
        if isinstance(row, (list, tuple)):
            if self._cursor.description:
                return {desc[0]: val for desc, val in zip(self._cursor.description, row)}
            return row
        return row

    def fetchall(self):
        rows = self._cursor.fetchall()
        if not rows:
            return []
        first = rows[0]
        if isinstance(first, dict):
            return rows
        if isinstance(first, (list, tuple)) and self._cursor.description:
            return [
                {desc[0]: val for desc, val in zip(self._cursor.description, row)}
                for row in rows
            ]
        return rows

    @property
    def lastrowid(self):
        """Return the lastrowid value.

        For INSERT ... RETURNING queries, callers should use fetchone()
        directly instead of this property, as lastrowid does not consume
        RETURNING rows. Falls back to rowcount.
        """
        return self._lastrowid if self._lastrowid is not None else self._cursor.rowcount

    @property
    def rowcount(self):
        return self._cursor.rowcount


class PgConnection:
    def __init__(self, pool):
        self._pool = pool
        self._conn = None
        self._cursor = None

    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = self._pool.getconn()
        return self._conn

    def execute(self, sql, params=None):
        conn = self._get_conn()
        if self._cursor is not None:
            self._cursor.close()
        cursor = conn.cursor()
        self._cursor = cursor
        wrapper = PgCursorWrapper(cursor, auto_commit=True)
        wrapper.execute(sql, params)
        return wrapper

    def executescript(self, sql):
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

    def commit(self):
        conn = self._get_conn()
        conn.commit()

    def close(self):
        if self._cursor is not None:
            try:
                self._cursor.close()
            except Exception:
                pass
            self._cursor = None
        if self._conn and not self._conn.closed:
            self._pool.putconn(self._conn)
            self._conn = None


class PgDatabase:
    def __init__(self, dsn: str = ''):
        self.dsn = dsn or 'postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper'
        self._pool = None

    def connect(self):
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2, maxconn=10, dsn=self.dsn,
            cursor_factory=psycopg2.extras.RealDictCursor
        )
        return self._pool

    def get_connection(self) -> PgConnection:
        return PgConnection(self._pool)

    @contextmanager
    def get_conn(self):
        conn = self._pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def initialize(self):
        with self.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)

    def close(self):
        if self._pool:
            self._pool.closeall()
