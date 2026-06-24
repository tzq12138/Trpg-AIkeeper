# SQLite → PostgreSQL + pgvector Full Migration

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SQLite with PostgreSQL as the sole database, expand RAG to index all 6 data types, and persist HostStore state.

**Architecture:** A thin `PgAdapter` class wraps psycopg2's connection pool to expose a SQLite-compatible interface (`conn.execute(sql, params)` returning dict-like rows). This minimizes changes across 15 router/service files. RAG indexing expands from 3 to 6 source types. HostStore gets a `host_states` table for crash recovery.

**Tech Stack:** PostgreSQL 16 + pgvector, psycopg2-binary, sentence-transformers (optional), FastAPI

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/server/db_adapter.py` | **Create** | PgAdapter: SQLite-compatible wrapper over psycopg2 pool |
| `src/server/db_pg.py` | **Modify** | Add `host_states` and `rule_documents` tables to schema |
| `src/server/main.py` | **Modify** | Replace SQLite Database with PgAdapter, wire RAG + HostStore |
| `src/server/database.py` | **Delete** | No longer needed |
| `src/server/host_store.py` | **Modify** | Add `save_state()` / `load_state()` for DB persistence |
| `src/server/rag.py` | **Modify** | Add `index_character()`, `index_npc_graph()`, `index_rules()` |
| `src/server/rag_router.py` | **Modify** | Add endpoints for new index types |
| `src/server/engine.py` | **Modify** | `?` → `%s`, boolean handling, commit via adapter |
| `src/server/event_log.py` | **Modify** | `?` → `%s`, `lastrowid` → `RETURNING`, commit via adapter |
| `src/server/campaign_archive.py` | **Modify** | `?` → `%s`, commit via adapter |
| `src/server/spoiler_control.py` | **Modify** | `?` → `%s` |
| `src/server/ws_manager.py` | **Modify** | `?` → `%s` |
| `src/server/router_rooms.py` | **Modify** | `?` → `%s`, `datetime('now')` → `NOW()` |
| `src/server/router_player.py` | **Modify** | `?` → `%s` |
| `src/server/router_scenarios.py` | **Modify** | `?` → `%s` |
| `src/server/router_ai.py` | **Modify** | `?` → `%s` |
| `src/server/router_clues.py` | **Modify** | `?` → `%s`, `GROUP_CONCAT` → `STRING_AGG`, boolean fix |
| `src/server/router_reconnect.py` | **Modify** | `?` → `%s`, `INSERT OR REPLACE` → `ON CONFLICT` |
| `src/server/router_clarification.py` | **Modify** | `?` → `%s` |
| `src/server/router_player_archive.py` | **Modify** | `?` → `%s` |
| `src/server/router_objectives.py` | **Modify** | `?` → `%s` |
| `src/server/router_host.py` | **Modify** | `?` → `%s` |
| `src/server/config.py` | **Modify** | Remove `database_path` field |
| `tests/server/test_db_adapter.py` | **Create** | Tests for PgAdapter compatibility |

---

## Task 1: Create PgAdapter — SQLite-compatible psycopg2 wrapper

**Covers:** Connection pooling, `?` → `%s` translation, Row-like dict returns, auto-commit

**Files:**
- Create: `src/server/db_adapter.py`
- Test: `tests/server/test_db_adapter.py`

### Step 1: Write the PgAdapter

```python
# src/server/db_adapter.py
import re
import psycopg2
import psycopg2.pool
import psycopg2.extras
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

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
    state JSONB NOT NULL,
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


def _translate_sql(sql: str) -> str:
    """Translate SQLite-style ? placeholders to PostgreSQL %s."""
    return re.sub(r'\?', '%s', sql)


class PgCursorWrapper:
    """Wraps a psycopg2 cursor to behave like sqlite3.Cursor."""
    def __init__(self, cursor, conn, auto_commit=True):
        self._cursor = cursor
        self._conn = conn
        self._auto_commit = auto_commit

    def execute(self, sql, params=None):
        translated = _translate_sql(sql)
        try:
            if params:
                self._cursor.execute(translated, params)
            else:
                self._cursor.execute(translated)
            if self._auto_commit:
                self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [dict(r) for r in rows]

    @property
    def lastrowid(self):
        if self._cursor.rowcount > 0 and self._cursor.description:
            try:
                row = self._cursor.fetchone()
                if row:
                    return row[0]
            except Exception:
                pass
        return self._cursor.rowcount

    @property
    def rowcount(self):
        return self._cursor.rowcount


class PgConnection:
    """Drop-in replacement for sqlite3.Connection using psycopg2 pool.

    Usage in routers stays identical:
        conn = request.app.state.db
        row = conn.execute("SELECT * FROM rooms WHERE room_id = ?", (room_id,)).fetchone()
    """
    def __init__(self, pool: psycopg2.pool.ThreadedConnectionPool):
        self._pool = pool
        self._conn = None

    def _ensure_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = self._pool.getconn()
        return self._conn

    def execute(self, sql, params=None):
        conn = self._ensure_conn()
        cursor = conn.cursor()
        wrapper = PgCursorWrapper(cursor, conn, auto_commit=True)
        wrapper.execute(sql, params)
        return wrapper

    def executescript(self, sql):
        conn = self._ensure_conn()
        cursor = conn.cursor()
        cursor.execute(sql)
        conn.commit()

    def commit(self):
        conn = self._ensure_conn()
        conn.commit()

    def close(self):
        if self._conn and not self._conn.closed:
            self._pool.putconn(self._conn)
            self._conn = None


class PgDatabase:
    """PostgreSQL database manager with connection pooling."""
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._pool = None

    def connect(self):
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2, maxconn=10, dsn=self.dsn,
            cursor_factory=psycopg2.extras.RealDictCursor
        )
        return self._pool

    def get_connection(self) -> PgConnection:
        """Returns a PgConnection that acts like sqlite3.Connection."""
        return PgConnection(self._pool)

    @contextmanager
    def get_conn(self):
        """Context manager for direct psycopg2 connection (used by RAG, etc.)."""
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
```

### Step 2: Write tests for PgAdapter

```python
# tests/server/test_db_adapter.py
import pytest
from src.server.db_adapter import _translate_sql


class TestTranslateSQL:
    def test_single_placeholder(self):
        assert _translate_sql("SELECT * FROM rooms WHERE room_id = ?") == \
            "SELECT * FROM rooms WHERE room_id = %s"

    def test_multiple_placeholders(self):
        assert _translate_sql("INSERT INTO rooms (room_id, owner_token) VALUES (?, ?)") == \
            "INSERT INTO rooms (room_id, owner_token) VALUES (%s, %s)"

    def test_no_placeholders(self):
        sql = "SELECT * FROM rooms"
        assert _translate_sql(sql) == sql

    def test_question_mark_in_string_literal(self):
        # Note: this is a known limitation — ? inside string literals gets replaced too.
        # In practice this doesn't occur in our codebase.
        sql = "SELECT * FROM rooms WHERE name = 'what?'"
        result = _translate_sql(sql)
        assert "%s" in result  # replaced — acceptable for our use case
```

### Step 3: Run tests

```bash
cd mimo-aikeeper && python -m pytest tests/server/test_db_adapter.py -v
```

Expected: PASS

### Step 4: Commit

```bash
git add src/server/db_adapter.py tests/server/test_db_adapter.py
git commit -m "feat: add PgAdapter — SQLite-compatible psycopg2 wrapper"
```

---

## Task 2: Wire PgAdapter into main.py, remove SQLite

**Covers:** Application startup, connection lifecycle, RAG/HostStore initialization

**Files:**
- Modify: `src/server/main.py`
- Modify: `src/server/config.py`
- Delete: `src/server/database.py`

### Step 1: Update config.py — remove database_path

```python
# src/server/config.py
import os
from pydantic import BaseModel


class Settings(BaseModel):
    database_url: str = "postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-pro"
    host: str = "0.0.0.0"
    port: int = 3001

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL", "postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper"),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "3001")),
        )
```

### Step 2: Rewrite main.py lifespan

Replace the entire file with:

```python
# src/server/main.py
import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from .config import Settings
from .db_adapter import PgDatabase
from .engine import Engine
from .router_rooms import router as rooms_router
from .router_player import router as player_router
from .router_scenarios import router as scenarios_router
from .router_clues import router as clues_router
from .router_objectives import router as objectives_router
from .router_clarification import router as clarification_router
from .router_reconnect import router as reconnect_router
from .router_player_archive import router as player_archive_router
from .router_host import router as host_router, host_ws_endpoint
from .router_ai import router as ai_router
from .rag_router import router as rag_router
from .ws_manager import manager as ws_manager
from .event_log import EventLog
from .embedding import HybridEmbedding
from .rag import RAGStore

logger = logging.getLogger(__name__)

settings = Settings.from_env()
pg_db = PgDatabase(settings.database_url)


@asynccontextmanager
async def lifespan(app: FastAPI):
    pg_db.connect()
    pg_db.initialize()

    conn = pg_db.get_connection()
    app.state.db = conn
    app.state.pg_db = pg_db
    app.state.engine = Engine(conn)

    embedding = HybridEmbedding()
    rag = RAGStore(pg_db, embedding)
    app.state.rag = rag

    yield

    conn.close()
    pg_db.close()


app = FastAPI(title="AI-Keeper", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return RedirectResponse(url="/docs")


@app.get("/api/health")
def health():
    return {"status": "ok"}


async def player_ws_endpoint(websocket: WebSocket, room_id: str, token: str, last_sequence: int = 0):
    conn = websocket.app.state.db
    char = conn.execute(
        "SELECT character_id, room_id FROM characters WHERE player_token = %s AND room_id = %s",
        (token, room_id),
    ).fetchone()
    if not char:
        await websocket.accept()
        await websocket.close(code=4003, reason="Invalid token")
        return

    character_id = char["character_id"]
    connection_id = f"player:{character_id}"

    await ws_manager.connect(websocket, room_id, connection_id)
    logger.info("Player %s connected to room %s", character_id, room_id)

    try:
        event_log = EventLog(conn)
        events = event_log.get_events(room_id, since_sequence=last_sequence)
        for ev in events:
            await websocket.send_text(json.dumps({
                "type": "catch_up",
                "sequence": ev.sequence,
                "event_type": ev.event_type,
                "audience": ev.audience,
                "payload": ev.payload,
                "issued_at": ev.issued_at,
            }))
        ws_manager.update_last_sequence(room_id, connection_id, last_sequence)

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("Player %s disconnected from room %s", character_id, room_id)
    except Exception as e:
        logger.error("Player %s error: %s", character_id, e)
    finally:
        ws_manager.disconnect(room_id, connection_id)


@app.websocket("/ws")
async def ws_handler(websocket: WebSocket, room: str = "", role: str = "", token: str = "", lastSequence: int = 0):
    if role == "host":
        await host_ws_endpoint(websocket, room)
    elif role == "player":
        await player_ws_endpoint(websocket, room, token, lastSequence)
    else:
        await websocket.accept()
        await websocket.close()


app.include_router(rooms_router)
app.include_router(player_router)
app.include_router(scenarios_router)
app.include_router(clues_router)
app.include_router(objectives_router)
app.include_router(clarification_router)
app.include_router(reconnect_router)
app.include_router(player_archive_router)
app.include_router(host_router)
app.include_router(ai_router)
app.include_router(rag_router)
```

### Step 3: Delete database.py

```bash
git rm src/server/database.py
```

### Step 4: Commit

```bash
git add src/server/main.py src/server/config.py
git commit -m "feat: switch main.py to PgAdapter, remove SQLite database.py"
```

---

## Task 3: Migrate SQL syntax in all service/router files

**Covers:** `?` → `%s`, `datetime('now')` → `NOW()`, `GROUP_CONCAT` → `STRING_AGG`, `INSERT OR REPLACE` → `ON CONFLICT`, `cursor.lastrowid` → `RETURNING`, boolean `0/1` → `TRUE/FALSE`

**Files:** (one commit per file or batch)

### 3a: `src/server/engine.py`

Changes:
- `is_ready = CASE WHEN is_ready = 1 THEN 0 ELSE 1 END` → `is_ready = NOT is_ready`
- All `?` → `%s` (already handled by PgAdapter, but clean up for consistency)

The PgAdapter handles `?` → `%s` automatically, so **no query changes needed** in this file. The boolean toggle needs fixing:

```python
# engine.py line ~26 — change:
self.conn.execute(
    "UPDATE characters SET is_ready = CASE WHEN is_ready = 1 THEN 0 ELSE 1 END WHERE character_id = ?",
    (character_id,),
)
# to:
self.conn.execute(
    "UPDATE characters SET is_ready = NOT is_ready WHERE character_id = %s",
    (character_id,),
)
```

### 3b: `src/server/event_log.py`

Changes:
- `cursor.lastrowid` → `RETURNING sequence`

```python
# event_log.py — the log_event method:
# Change from:
cursor = self.conn.execute(
    "INSERT INTO events (room_id, event_type, audience, payload) VALUES (?, ?, ?, ?)",
    (room_id, event_type, audience, payload),
)
return cursor.lastrowid

# To:
cursor = self.conn.execute(
    "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, %s, %s) RETURNING sequence",
    (room_id, event_type, audience, payload),
)
row = cursor.fetchone()
return row['sequence'] if row else 0
```

### 3c: `src/server/router_rooms.py`

Changes:
- `datetime('now')` → `NOW()`

```python
# line 41 — change:
"UPDATE rooms SET status = 'active', started_at = datetime('now') WHERE room_id = ?"
# to:
"UPDATE rooms SET status = 'active', started_at = NOW() WHERE room_id = %s"
```

### 3d: `src/server/router_clues.py`

Changes:
- `GROUP_CONCAT(cs.shared_by)` → `STRING_AGG(cs.shared_by, ',')`
- `is_private = 0` → `is_private = FALSE`

```python
# line 26 — change GROUP_CONCAT:
"SELECT c.*, GROUP_CONCAT(cs.shared_by) as shared_by_list ..."
# to:
"SELECT c.*, STRING_AGG(cs.shared_by, ',') as shared_by_list ..."

# line ~46 — change boolean:
"UPDATE clues SET is_private = 0 WHERE clue_id = ?"
# to:
"UPDATE clues SET is_private = FALSE WHERE clue_id = %s"
```

### 3e: `src/server/router_reconnect.py`

Changes:
- `INSERT OR REPLACE` → `INSERT ... ON CONFLICT ... DO UPDATE`

```python
# line 69 — change:
"INSERT OR REPLACE INTO player_sequences (character_id, room_id, last_delivered_sequence) VALUES (?, ?, ?)"
# to:
"""INSERT INTO player_sequences (character_id, room_id, last_delivered_sequence)
   VALUES (%s, %s, %s)
   ON CONFLICT (character_id, room_id)
   DO UPDATE SET last_delivered_sequence = EXCLUDED.last_delivered_sequence,
                 updated_at = NOW()"""
```

### 3f: All remaining files — bulk `?` → `%s` replacement

For these files, the ONLY change needed is replacing `?` with `%s` in all SQL strings:
- `router_player.py`
- `router_scenarios.py`
- `router_ai.py`
- `router_clarification.py`
- `router_player_archive.py`
- `router_objectives.py`
- `router_host.py`
- `campaign_archive.py`
- `spoiler_control.py`
- `ws_manager.py`

**Note:** The PgAdapter's `_translate_sql()` handles `?` → `%s` at runtime, so these files technically work without changes. However, for code clarity and to avoid confusion, replace `?` with `%s` in all files in a single pass.

### Step: Commit

```bash
git add src/server/
git commit -m "feat: migrate all SQL from SQLite to PostgreSQL syntax"
```

---

## Task 4: HostStore persistence

**Covers:** Room state survives server restart

**Files:**
- Modify: `src/server/host_store.py`
- Modify: `src/server/router_host.py`

### Step 1: Add save/load to HostStore

```python
# Add to HostStore class in host_store.py:

def save_state(self, db_conn):
    """Persist current state to database."""
    state = {
        "current_scene_image_url": self.current_scene_image_url,
        "chat_messages": self.chat_messages[-50:],  # keep last 50 for recovery
        "atmosphere": self.atmosphere,
        "engine_state": self.engine_state,
        "is_paused": self.is_paused,
        "last_host_sequence": self.last_host_sequence,
        "players": [
            {
                "character_id": p.character_id,
                "player_name": p.player_name,
                "hp": p.hp, "hp_max": p.hp_max,
                "san": p.san, "san_max": p.san_max,
                "mp": p.mp, "mp_max": p.mp_max,
                "luck": p.luck, "status_tags": p.status_tags,
            }
            for p in self.players
        ],
    }
    import json
    db_conn.execute(
        """INSERT INTO host_states (room_id, state, updated_at)
           VALUES (%s, %s, NOW())
           ON CONFLICT (room_id) DO UPDATE SET state = EXCLUDED.state, updated_at = NOW()""",
        (self.room_id, json.dumps(state)),
    )

@staticmethod
def load_state(room_id: str, db_conn) -> dict | None:
    """Load persisted state from database."""
    row = db_conn.execute(
        "SELECT state FROM host_states WHERE room_id = %s", (room_id,)
    ).fetchone()
    if row:
        return row["state"] if isinstance(row["state"], dict) else json.loads(row["state"])
    return None

def restore_from_db(self, db_conn):
    """Restore state from database if available."""
    state = self.load_state(self.room_id, db_conn)
    if not state:
        return
    self.current_scene_image_url = state.get("current_scene_image_url")
    self.chat_messages = state.get("chat_messages", [])
    self.atmosphere = state.get("atmosphere", {"bgm": None, "sfx_queue": [], "visual": None})
    self.engine_state = state.get("engine_state", "idle")
    self.is_paused = state.get("is_paused", False)
    self.last_host_sequence = state.get("last_host_sequence", 0)
    from .models import PlayerPublicStatus
    self.players = [PlayerPublicStatus(**p) for p in state.get("players", [])]
```

### Step 2: Auto-save on key state changes in router_host.py

In the host WS endpoint, call `store.save_state(conn)` after processing events that change state (snapshot, atmosphere, engine state changes).

### Step 3: Commit

```bash
git add src/server/host_store.py src/server/router_host.py
git commit -m "feat: persist HostStore state to PostgreSQL for crash recovery"
```

---

## Task 5: Expand RAG indexing to all 6 data types

**Covers:** Character cards, NPC knowledge graph, CoC rules

**Files:**
- Modify: `src/server/rag.py`
- Modify: `src/server/rag_router.py`
- Modify: `src/server/router_scenarios.py` (auto-index NPC on import)
- Modify: `src/server/router_player.py` (auto-index character on import)

### Step 1: Add new index methods to RAGStore

```python
# Add to RAGStore class in rag.py:

def index_character(self, room_id: str, character_id: str, xlsx_data: dict):
    """Index character sheet data for RAG retrieval."""
    parts = []
    if xlsx_data.get("name"):
        parts.append(f"角色名: {xlsx_data['name']}")
    if xlsx_data.get("occupation"):
        parts.append(f"职业: {xlsx_data['occupation']}")
    if xlsx_data.get("background"):
        parts.append(f"背景: {xlsx_data['background']}")
    for skill_name, skill_val in xlsx_data.get("skills", {}).items():
        if skill_val and int(skill_val) > 0:
            parts.append(f"技能 {skill_name}: {skill_val}")
    if xlsx_data.get("description"):
        parts.append(f"描述: {xlsx_data['description']}")

    content = "\n".join(parts)
    if len(content) < 10:
        return 0

    chunks = chunk_text(content, max_chars=300, overlap=30)
    vectors = self.embedding.embed(chunks)
    with self.pg_db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'DELETE FROM document_chunks WHERE source_type = %s AND source_id = %s',
                ('character', character_id)
            )
            for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
                cur.execute(
                    'INSERT INTO document_chunks (chunk_id, source_type, source_id, room_id, content, metadata, embedding) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s)',
                    (str(uuid.uuid4()), 'character', character_id, room_id, chunk,
                     json.dumps({'index': i, 'total': len(chunks)}),
                     vec)
                )
    logger.info('Indexed %d chunks for character %s', len(chunks), character_id)
    return len(chunks)


def index_npc_graph(self, scenario_id: str, knowledge_graph: dict, room_id: str | None = None):
    """Index NPCs from scenario knowledge graph."""
    npcs = knowledge_graph.get("npcs", [])
    if not npcs:
        return 0

    chunks = []
    for npc in npcs:
        parts = [f"NPC: {npc.get('name', '未知')}"]
        if npc.get("role"):
            parts.append(f"角色定位: {npc['role']}")
        if npc.get("description"):
            parts.append(f"描述: {npc['description']}")
        chunks.append("\n".join(parts))

    if not chunks:
        return 0

    vectors = self.embedding.embed(chunks)
    with self.pg_db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'DELETE FROM document_chunks WHERE source_type = %s AND source_id = %s',
                ('npc', scenario_id)
            )
            for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
                cur.execute(
                    'INSERT INTO document_chunks (chunk_id, source_type, source_id, room_id, content, metadata, embedding) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s)',
                    (str(uuid.uuid4()), 'npc', scenario_id, room_id, chunk,
                     json.dumps({'npc_name': npcs[i].get('name', ''), 'index': i}),
                     vec)
                )
    logger.info('Indexed %d NPC chunks for scenario %s', len(chunks), scenario_id)
    return len(chunks)


def index_rules(self, doc_id: str, title: str, category: str, content: str):
    """Index a CoC rule document."""
    chunks = chunk_text(content, max_chars=500, overlap=50)
    if not chunks:
        return 0

    vectors = self.embedding.embed(chunks)
    with self.pg_db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'DELETE FROM document_chunks WHERE source_type = %s AND source_id = %s',
                ('rule', doc_id)
            )
            for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
                cur.execute(
                    'INSERT INTO document_chunks (chunk_id, source_type, source_id, room_id, content, metadata, embedding) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s)',
                    (str(uuid.uuid4()), 'rule', doc_id, None, chunk,
                     json.dumps({'title': title, 'category': category, 'index': i, 'total': len(chunks)}),
                     vec)
                )

    with self.pg_db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO rule_documents (doc_id, title, category, content)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (doc_id) DO UPDATE SET title = EXCLUDED.title, category = EXCLUDED.category, content = EXCLUDED.content""",
                (doc_id, title, category, content)
            )

    logger.info('Indexed %d chunks for rule %s (%s)', len(chunks), doc_id, category)
    return len(chunks)
```

### Step 2: Add RAG router endpoints

```python
# Add to rag_router.py:

@router.post("/index-character")
async def index_character(request: Request, body: dict):
    rag = request.app.state.rag
    if not rag:
        raise HTTPException(503, "RAG not available")
    room_id = body.get("room_id")
    character_id = body.get("character_id")
    xlsx_data = body.get("xlsx_data", {})
    count = rag.index_character(room_id, character_id, xlsx_data)
    return {"chunks": count}


@router.post("/index-npc")
async def index_npc(request: Request, body: dict):
    rag = request.app.state.rag
    if not rag:
        raise HTTPException(503, "RAG not available")
    scenario_id = body.get("scenario_id")
    knowledge_graph = body.get("knowledge_graph", {})
    room_id = body.get("room_id")
    count = rag.index_npc_graph(scenario_id, knowledge_graph, room_id)
    return {"chunks": count}


@router.post("/index-rules")
async def index_rules(request: Request, body: dict):
    rag = request.app.state.rag
    if not rag:
        raise HTTPException(503, "RAG not available")
    doc_id = body.get("doc_id")
    title = body.get("title", "")
    category = body.get("category", "general")
    content = body.get("content", "")
    count = rag.index_rules(doc_id, title, category, content)
    return {"chunks": count}
```

### Step 3: Auto-index on scenario import

In `router_scenarios.py`, after successfully structuring a scenario, call:
```python
if request.app.state.rag and knowledge_graph:
    request.app.state.rag.index_npc_graph(scenario_id, knowledge_graph)
```

### Step 4: Auto-index on character import

In `router_player.py`, after importing xlsx_data, call:
```python
if request.app.state.rag:
    request.app.state.rag.index_character(room_id, character_id, parsed_data)
```

### Step 5: Commit

```bash
git add src/server/rag.py src/server/rag_router.py src/server/router_scenarios.py src/server/router_player.py
git commit -m "feat: expand RAG indexing to characters, NPCs, and rules"
```

---

## Task 6: End-to-end verification

**Covers:** All changes work together

### Step 1: Start PostgreSQL

```bash
docker compose up -d
```

### Step 2: Install dependencies

```bash
cd mimo-aikeeper && pip install -e .
```

### Step 3: Run existing tests

```bash
python -m pytest tests/server/ -v
```

### Step 4: Start the server

```bash
uvicorn src.server.main:app --reload --port 3001
```

### Step 5: Smoke test via API

```bash
# Create a room
curl -X POST http://localhost:3001/api/rooms -H "Content-Type: application/json" -d '{"spoiler_level": "standard"}'

# Check health
curl http://localhost:3001/api/health

# Check RAG stats
curl http://localhost:3001/api/rag/stats
```

### Step 6: Commit final state

```bash
git add -A
git commit -m "chore: complete SQLite to PostgreSQL migration"
```

---

## Migration Checklist

- [x] PgAdapter created and targeted tests added
- [x] main.py wired to PgAdapter, SQLite removed from active path
- [x] All `datetime('now')` → `NOW()` on active PostgreSQL path
- [x] All active `INSERT OR REPLACE` → `ON CONFLICT`
- [x] No active `GROUP_CONCAT` usage remains
- [x] Active generated IDs avoid `cursor.lastrowid`; `RETURNING` used where needed
- [x] Boolean test SQL updated to `TRUE/FALSE`
- [x] HostStore save/load implemented
- [x] RAG: character indexing implemented
- [x] RAG: NPC graph indexing implemented
- [x] RAG: rules indexing implemented
- [x] Full suite pass under `scripts/test.ps1`
- [ ] Smoke test creates room and queries work under fresh Docker volume
