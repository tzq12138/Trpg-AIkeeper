# PostgreSQL + pgvector + RAG Implementation Plan

**Goal:** Migrate from SQLite to PostgreSQL with pgvector, add RAG pipeline for AI KP context retrieval.

**Architecture:** PostgreSQL with pgvector extension stores both structured data and vector embeddings. RAG pipeline chunks scenario text, embeds it (local or API), stores in pgvector, and retrieves relevant chunks for AI KP prompts.

**Tech Stack:** PostgreSQL 16 + pgvector, psycopg2-binary, sentence-transformers (local), numpy, httpx (remote embedding fallback)

---

## File Structure

```
mimo-aikeeper/
├── docker-compose.yml              # PostgreSQL + pgvector
├── src/server/
│   ├── database.py                 # MODIFY: PostgreSQL connection
│   ├── db_pg.py                    # NEW: PostgreSQL pool manager
│   ├── embedding.py                # NEW: Embedding service (local + remote)
│   ├── rag.py                      # NEW: RAG pipeline (chunk, embed, store, retrieve)
│   ├── rag_router.py               # NEW: RAG management endpoints
│   ├── ai_kp.py                    # MODIFY: Use RAG for context
│   ├── router_scenarios.py         # MODIFY: Trigger RAG indexing on import
│   └── ... (other routers unchanged)
├── tests/server/
│   ├── test_embedding.py           # NEW
│   ├── test_rag.py                 # NEW
│   └── ... (existing tests updated)
└── pyproject.toml                  # MODIFY: Add dependencies
```

---

## Task 1: Docker Compose + pgvector

**Files:** `docker-compose.yml`

- [ ] **Step 1: Create docker-compose.yml**

```yaml
version: "3.9"
services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: aikeeper-db
    environment:
      POSTGRES_USER: aikeeper
      POSTGRES_PASSWORD: aikeeper123
      POSTGRES_DB: aikeeper
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U aikeeper"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
```

- [ ] **Step 2: Start PostgreSQL**

```bash
cd G:\hermes-agent-workplace\D&D\mimo-aikeeper
docker compose up -d
```

- [ ] **Step 3: Verify connection**

```bash
docker exec aikeeper-db psql -U aikeeper -d aikeeper -c "SELECT 1;"
```

---

## Task 2: Dependencies + Database Connection

**Files:** `pyproject.toml`, `src/server/db_pg.py`

- [ ] **Step 1: Add dependencies to pyproject.toml**

```toml
dependencies = [
    # ... existing ...
    "psycopg2-binary>=2.9.9",
    "pgvector>=0.3.0",
    "numpy>=1.26.0",
    "sentence-transformers>=3.0.0",
]
```

- [ ] **Step 2: Install dependencies**

```bash
pip install psycopg2-binary pgvector numpy sentence-transformers
```

- [ ] **Step 3: Create db_pg.py**

```python
import psycopg2
import psycopg2.pool
import psycopg2.extras
from contextlib import contextmanager
from pathlib import Path

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

-- All existing tables (same as database.py but PostgreSQL syntax)
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
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    event_type TEXT NOT NULL,
    audience TEXT NOT NULL,
    payload JSONB NOT NULL,
    issued_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS actions (
    action_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    character_id TEXT NOT NULL REFERENCES characters(character_id),
    intent_type TEXT NOT NULL,
    declared_intent TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    batch_id TEXT,
    result JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- RAG tables
CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,          -- 'scenario', 'event', 'clue', 'action'
    source_id TEXT NOT NULL,            -- scenario_id, event sequence, etc.
    room_id TEXT,                       -- optional room association
    content TEXT NOT NULL,              -- the actual text chunk
    metadata JSONB DEFAULT '{}',        -- page, offset, tags, etc.
    embedding vector(768),              -- pgvector column (768 for text2vec-base-chinese)
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_source ON document_chunks(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_chunks_room ON document_chunks(room_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);

-- Keep other tables same as SQLite version
CREATE TABLE IF NOT EXISTS player_sequences (
    character_id TEXT NOT NULL REFERENCES characters(character_id),
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    last_delivered_sequence BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (character_id, room_id)
);

CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    state_snapshot JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS campaign_archives (
    archive_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    ending_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    highlights JSONB NOT NULL,
    character_arcs JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS clues (
    clue_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    character_id TEXT NOT NULL REFERENCES characters(character_id),
    text TEXT NOT NULL,
    source TEXT DEFAULT '',
    is_private BOOLEAN NOT NULL DEFAULT TRUE,
    discovered_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS clue_shares (
    share_id TEXT PRIMARY KEY,
    clue_id TEXT NOT NULL REFERENCES clues(clue_id),
    shared_by TEXT NOT NULL REFERENCES characters(character_id),
    shared_at TIMESTAMP NOT NULL DEFAULT NOW(),
    public_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS objectives (
    objective_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    character_id TEXT REFERENCES characters(character_id),
    text TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'team',
    status TEXT NOT NULL DEFAULT 'active',
    assigned_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS inventory (
    id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL REFERENCES characters(character_id),
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    quantity INTEGER DEFAULT 1,
    is_secret BOOLEAN DEFAULT FALSE,
    source TEXT DEFAULT '',
    acquired_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS clarifications (
    clarification_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL REFERENCES rooms(room_id),
    character_id TEXT NOT NULL REFERENCES characters(character_id),
    target_action_id TEXT NOT NULL,
    text TEXT NOT NULL,
    evidence TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    window_expires_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMP,
    result JSONB
);
"""


class PgDatabase:
    def __init__(self, dsn: str = ""):
        self.dsn = dsn or "postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper"
        self._pool = None

    def connect(self):
        """Create connection pool."""
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2, maxconn=10, dsn=self.dsn,
            cursor_factory=psycopg2.extras.RealDictCursor
        )
        return self._pool

    @contextmanager
    def get_conn(self):
        """Get a connection from the pool."""
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
        """Create all tables."""
        with self.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)
```

---

## Task 3: Embedding Service

**Files:** `src/server/embedding.py`, `tests/server/test_embedding.py`

- [ ] **Step 1: Create embedding.py**

```python
import numpy as np
import hashlib
import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LocalEmbedding:
    """sentence-transformers local embedding."""
    def __init__(self, model_name: str = "shibing624/text2vec-base-chinese"):
        self._model = None
        self._model_name = model_name

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading embedding model: %s", self._model_name)
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, normalize_embeddings=True)
        return vectors.tolist()


class RemoteEmbedding:
    """DeepSeek/OpenAI API embedding."""
    def __init__(self, api_key: str, model: str = "deepseek-embedding", api_base: str = "https://api.deepseek.com"):
        self.api_key = api_key
        self.model = model
        self.api_base = api_base

    def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx
        resp = httpx.post(
            f"{self.api_base}/v1/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "input": texts},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in data["data"]]


class HybridEmbedding:
    """Local first, remote fallback."""
    def __init__(self, local: LocalEmbedding | None = None, remote: RemoteEmbedding | None = None):
        self.local = local or LocalEmbedding()
        self.remote = remote

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            return self.local.embed(texts)
        except Exception as e:
            if self.remote:
                logger.warning("Local embedding failed (%s), using remote", e)
                return self.remote.embed(texts)
            raise

    @property
    def dimension(self) -> int:
        return 768  # text2vec-base-chinese


def cosine_similarity(a: list[float], b: list[float]) -> float:
    a_arr = np.array(a)
    b_arr = np.array(b)
    return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr) + 1e-10))
```

- [ ] **Step 2: Write tests**

```python
# tests/server/test_embedding.py
from src.server.embedding import LocalEmbedding, cosine_similarity

def test_cosine_similarity_identical():
    v = [1.0, 0.0, 0.0]
    assert cosine_similarity(v, v) > 0.99

def test_cosine_similarity_orthogonal():
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert abs(cosine_similarity(a, b)) < 0.01

def test_local_embedding_dimension():
    emb = LocalEmbedding()
    vectors = emb.embed(["你好世界"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 768

def test_local_embedding_batch():
    emb = LocalEmbedding()
    vectors = emb.embed(["测试一", "测试二", "测试三"])
    assert len(vectors) == 3
```

---

## Task 4: RAG Pipeline

**Files:** `src/server/rag.py`, `tests/server/test_rag.py`

- [ ] **Step 1: Create rag.py**

```python
import uuid
import json
import logging
from .embedding import HybridEmbedding

logger = logging.getLogger(__name__)


def chunk_text(text: str, max_chars: int = 500, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start = end - overlap
    return chunks


class RAGStore:
    def __init__(self, conn, embedding: HybridEmbedding):
        self.conn = conn
        self.embedding = embedding

    def index_scenario(self, scenario_id: str, raw_text: str, room_id: str | None = None):
        """Chunk and index a scenario's text."""
        chunks = chunk_text(raw_text)
        if not chunks:
            return 0

        vectors = self.embedding.embed(chunks)

        with self.conn.cursor() as cur:
            # Remove old chunks for this scenario
            cur.execute(
                "DELETE FROM document_chunks WHERE source_type = 'scenario' AND source_id = %s",
                (scenario_id,)
            )
            # Insert new chunks
            for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
                cur.execute(
                    "INSERT INTO document_chunks (chunk_id, source_type, source_id, room_id, content, metadata, embedding) "
                    "VALUES (%s, 'scenario', %s, %s, %s, %s, %s)",
                    (str(uuid.uuid4()), scenario_id, room_id, chunk,
                     json.dumps({"index": i, "total": len(chunks)}),
                     vec)
                )
        self.conn.commit()
        logger.info("Indexed %d chunks for scenario %s", len(chunks), scenario_id)
        return len(chunks)

    def index_event(self, room_id: str, event_type: str, payload: dict, sequence: int):
        """Index an event for later retrieval."""
        content = f"[{event_type}] {json.dumps(payload, ensure_ascii=False)}"
        if len(content) < 20:
            return
        vector = self.embedding.embed([content])[0]
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO document_chunks (chunk_id, source_type, source_id, room_id, content, metadata, embedding) "
                "VALUES (%s, 'event', %s, %s, %s, %s, %s)",
                (str(uuid.uuid4()), str(sequence), room_id, content,
                 json.dumps({"event_type": event_type, "sequence": sequence}),
                 vector)
            )
        self.conn.commit()

    def index_clue(self, room_id: str, clue_id: str, text: str, source: str = ""):
        """Index a clue."""
        vector = self.embedding.embed([text])[0]
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO document_chunks (chunk_id, source_type, source_id, room_id, content, metadata, embedding) "
                "VALUES (%s, 'clue', %s, %s, %s, %s, %s)",
                (str(uuid.uuid4()), clue_id, room_id, text,
                 json.dumps({"source": source}),
                 vector)
            )
        self.conn.commit()

    def search(self, query: str, room_id: str | None = None,
               source_types: list[str] | None = None, top_k: int = 5) -> list[dict]:
        """Semantic search across chunks."""
        query_vec = self.embedding.embed([query])[0]

        with self.conn.cursor() as cur:
            conditions = []
            params = [query_vec]
            if room_id:
                conditions.append("room_id = %s")
                params.append(room_id)
            if source_types:
                placeholders = ",".join(["%s"] * len(source_types))
                conditions.append(f"source_type IN ({placeholders})")
                params.extend(source_types)

            where = "WHERE " + " AND ".join(conditions) if conditions else ""
            params.append(top_k)

            cur.execute(f"""
                SELECT chunk_id, source_type, source_id, content, metadata,
                       1 - (embedding <=> %s::vector) as similarity
                FROM document_chunks
                {where}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """, params + [query_vec, top_k])

            return cur.fetchall()
```

- [ ] **Step 2: Write tests**

```python
# tests/server/test_rag.py
from src.server.rag import chunk_text

def test_chunk_text_basic():
    chunks = chunk_text("A" * 1000, max_chars=200, overlap=20)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)

def test_chunk_text_short():
    chunks = chunk_text("Short text")
    assert len(chunks) == 1
    assert chunks[0] == "Short text"

def test_chunk_text_empty():
    chunks = chunk_text("")
    assert len(chunks) == 0

def test_chunk_text_overlap():
    text = "ABCDEFGHIJ" * 10  # 100 chars
    chunks = chunk_text(text, max_chars=30, overlap=10)
    # Should have overlapping content
    assert len(chunks) > 1
```

---

## Task 5: RAG Router + Integration

**Files:** `src/server/rag_router.py`, `src/server/ai_kp.py` (modify), `src/server/main.py` (modify)

- [ ] **Step 1: Create rag_router.py**

```python
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/rag")


class IndexRequest(BaseModel):
    scenario_id: str
    room_id: str | None = None


class SearchRequest(BaseModel):
    query: str
    room_id: str | None = None
    source_types: list[str] | None = None
    top_k: int = 5


@router.post("/index")
async def index_scenario(request: Request, body: IndexRequest):
    conn = request.app.state.db
    rag = request.app.state.rag
    row = conn.execute(
        "SELECT raw_text FROM scenarios WHERE scenario_id = %s", (body.scenario_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Scenario not found")
    count = rag.index_scenario(body.scenario_id, row["raw_text"], body.room_id)
    return {"chunks_indexed": count}


@router.post("/search")
async def search(request: Request, body: SearchRequest):
    rag = request.app.state.rag
    results = rag.search(body.query, body.room_id, body.source_types, body.top_k)
    return results


@router.get("/stats")
async def stats(request: Request):
    conn = request.app.state.db
    with conn.cursor() as cur:
        cur.execute("SELECT source_type, COUNT(*) as cnt FROM document_chunks GROUP BY source_type")
        rows = cur.fetchall()
    return {r["source_type"]: r["cnt"] for r in rows}
```

- [ ] **Step 2: Update ai_kp.py to use RAG**

In `ai_kp.py`, modify `process_batch` to retrieve relevant context:

```python
async def process_batch(self, room_id: str, batch: dict, scenario: dict) -> AIResponse:
    # Retrieve relevant context via RAG
    rag_context = ""
    if self.rag_store:
        action_texts = [a.get("declared_intent", "") for a in batch.get("actions", [])]
        query = " ".join(action_texts)
        if query.strip():
            results = self.rag_store.search(query, room_id=room_id, top_k=3)
            rag_context = "\n".join([r["content"] for r in results])

    # Build prompt with RAG context
    prompt = self._build_prompt(scenario, batch, rag_context)
    # ... rest of existing logic
```

- [ ] **Step 3: Update main.py to initialize RAG**

```python
from .db_pg import PgDatabase
from .embedding import HybridEmbedding, LocalEmbedding, RemoteEmbedding
from .rag import RAGStore
from .rag_router import router as rag_router

# In lifespan:
pg_db = PgDatabase(settings.database_url)
pool = pg_db.connect()
pg_db.initialize()
app.state.db_pool = pg_db

# RAG
local_emb = LocalEmbedding()
remote_emb = RemoteEmbedding(settings.deepseek_api_key) if settings.deepseek_api_key else None
embedding = HybridEmbedding(local=local_emb, remote=remote_emb)
rag = RAGStore(conn_from_pool, embedding)
app.state.rag = rag

app.include_router(rag_router)
```

---

## Execution Order

1. **Task 1**: Docker Compose → start PostgreSQL
2. **Task 2**: Dependencies + db_pg.py → connect
3. **Task 3**: Embedding service → test local embedding
4. **Task 4**: RAG pipeline → test chunking
5. **Task 5**: Integration → wire everything together
