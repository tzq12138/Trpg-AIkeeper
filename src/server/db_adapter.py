import json
import re
import logging
from contextlib import contextmanager

import psycopg2
import psycopg2.pool
import psycopg2.extras

logger = logging.getLogger(__name__)

_placeholder_re = re.compile(r'\?')
_sqlite_datetime_hour_re = re.compile(r"datetime\('now',\s*'-(\d+)\s+hour'\)", re.IGNORECASE)
_sqlite_datetime_now_re = re.compile(r"datetime\('now'\)", re.IGNORECASE)


def _translate_sql(sql: str) -> str:
    sql = _sqlite_datetime_hour_re.sub(r"(NOW() - INTERVAL '\1 hour')", sql)
    sql = _sqlite_datetime_now_re.sub("NOW()", sql)
    return _placeholder_re.sub('%s', sql)


def _coerce_jsonb_result_literals(sql: str) -> str:
    lower_sql = sql.lower()
    if "insert into actions" not in lower_sql or "result" not in lower_sql:
        return sql

    match = re.search(
        r"(insert\s+into\s+actions\s*\((?P<columns>[^)]+)\)\s*values\s*\()(?P<values>.*)(\)\s*)$",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return sql

    columns = [column.strip().strip('"').lower() for column in match.group("columns").split(",")]
    if "result" not in columns:
        return sql

    values = _split_sql_values(match.group("values"))
    result_idx = columns.index("result")
    if result_idx >= len(values):
        return sql

    result_value = values[result_idx].strip()
    if len(result_value) < 2 or not (result_value.startswith("'") and result_value.endswith("'")):
        return sql

    inner = result_value[1:-1].replace("''", "'")
    try:
        json.loads(inner)
        return sql
    except Exception:
        values[result_idx] = "'" + json.dumps(inner, ensure_ascii=False).replace("'", "''") + "'"
        return match.group(1) + ", ".join(values) + match.group(4)


def _split_sql_values(values_sql: str) -> list[str]:
    values: list[str] = []
    current: list[str] = []
    in_string = False
    i = 0
    while i < len(values_sql):
        char = values_sql[i]
        if char == "'":
            current.append(char)
            if in_string and i + 1 < len(values_sql) and values_sql[i + 1] == "'":
                current.append(values_sql[i + 1])
                i += 2
                continue
            in_string = not in_string
        elif char == "," and not in_string:
            values.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        i += 1
    values.append("".join(current).strip())
    return values


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
    scenario_assets JSONB,
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
    params JSONB DEFAULT '{}',
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

ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS scenario_assets JSONB;
ALTER TABLE actions ADD COLUMN IF NOT EXISTS params JSONB DEFAULT '{}';
"""


class PgCursorWrapper:
    def __init__(self, cursor, auto_commit: bool = True):
        self._cursor = cursor
        self._auto_commit = auto_commit
        self._connection = cursor.connection
        self._lastrowid = None

    def execute(self, sql, params=None):
        translated = _coerce_jsonb_result_literals(_translate_sql(sql))
        params = self._coerce_params(translated, params)
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

    def _coerce_params(self, sql, params=None):
        if params is None or not isinstance(params, (tuple, list)):
            return params
        values = list(params)
        lower_sql = sql.lower()
        boolean_columns = ("is_private", "is_ready", "is_secret")
        if any(column in lower_sql for column in boolean_columns):
            columns = self._insert_columns(lower_sql)
            for column in boolean_columns:
                if column in columns:
                    idx = columns.index(column)
                    if idx < len(values) and values[idx] in (0, 1):
                        values[idx] = bool(values[idx])
            if "set is_private = %s" in lower_sql and values and values[0] in (0, 1):
                values[0] = bool(values[0])
            if "set is_ready = %s" in lower_sql and values and values[0] in (0, 1):
                values[0] = bool(values[0])
            if "set is_secret = %s" in lower_sql and values and values[0] in (0, 1):
                values[0] = bool(values[0])
        if "result" in lower_sql:
            columns = self._insert_columns(lower_sql)
            if "result" in columns:
                idx = columns.index("result")
                if idx < len(values):
                    values[idx] = self._json_param(values[idx])
            elif "result = %s" in lower_sql:
                update_columns = self._update_columns(lower_sql)
                if "result" in update_columns:
                    idx = update_columns.index("result")
                    if idx < len(values):
                        values[idx] = self._json_param(values[idx])
        return tuple(values) if isinstance(params, tuple) else values

    def _insert_columns(self, sql: str) -> list[str]:
        match = re.search(r"insert\s+into\s+\w+\s*\(([^)]+)\)", sql)
        if not match:
            return []
        return [column.strip().strip('"') for column in match.group(1).split(",")]

    def _update_columns(self, sql: str) -> list[str]:
        match = re.search(r"update\s+\w+\s+set\s+(.+?)\s+where\s+", sql, re.DOTALL)
        if not match:
            return []
        assignments = match.group(1).split(",")
        return [
            assignment.split("=", 1)[0].strip().strip('"')
            for assignment in assignments
            if "=" in assignment and "%s" in assignment
        ]

    def _json_param(self, value):
        if value is None or not isinstance(value, str):
            return value
        try:
            json.loads(value)
            return value
        except Exception:
            return json.dumps(value, ensure_ascii=False)

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
