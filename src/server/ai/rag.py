import uuid
import json
import logging
from .embedding import HybridEmbedding

logger = logging.getLogger(__name__)


def chunk_text(text: str, max_chars: int = 500, overlap: int = 50) -> list[str]:
    chunks = []
    start = 0
    step_back = min(overlap, max_chars - 1)
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        if end >= len(text):
            break
        start = end - step_back
    return chunks


class RAGStore:
    def __init__(self, pg_db, embedding: HybridEmbedding):
        self.pg_db = pg_db
        self.embedding = embedding

    def index_scenario(self, scenario_id: str, raw_text: str, room_id: str | None = None) -> int:
        chunks = chunk_text(raw_text)
        if not chunks:
            return 0
        vectors = self.embedding.embed(chunks)
        with self.pg_db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'DELETE FROM document_chunks WHERE source_type = %s AND source_id = %s',
                    ('scenario', scenario_id)
                )
                for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
                    cur.execute(
                        'INSERT INTO document_chunks (chunk_id, source_type, source_id, room_id, content, metadata, embedding) '
                        'VALUES (%s, %s, %s, %s, %s, %s, %s)',
                        (str(uuid.uuid4()), 'scenario', scenario_id, room_id, chunk,
                         json.dumps({'index': i, 'total': len(chunks), 'scenario_id': scenario_id, 'visibility': 'internal'}),
                         vec)
                    )
        logger.info('Indexed %d chunks for scenario %s', len(chunks), scenario_id)
        return len(chunks)

    def index_event(self, room_id: str, event_type: str, payload: dict, sequence: int):
        content = f'[{event_type}] {json.dumps(payload, ensure_ascii=False)}'
        if len(content) < 20:
            return
        vector = self.embedding.embed([content])[0]
        with self.pg_db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO document_chunks (chunk_id, source_type, source_id, room_id, content, metadata, embedding) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s)',
                    (str(uuid.uuid4()), 'event', str(sequence), room_id, content,
                     json.dumps({'event_type': event_type, 'sequence': sequence}),
                     vector)
                )

    def index_clue(self, room_id: str, clue_id: str, text: str, source: str = ''):
        vector = self.embedding.embed([text])[0]
        with self.pg_db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO document_chunks (chunk_id, source_type, source_id, room_id, content, metadata, embedding) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s)',
                    (str(uuid.uuid4()), 'clue', clue_id, room_id, text,
                     json.dumps({'source': source}),
                     vector)
                )

    def index_character(self, room_id: str, character_id: str, xlsx_data: dict) -> int:
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

    def index_npc_graph(self, scenario_id: str, knowledge_graph: dict, room_id: str | None = None) -> int:
        npcs = knowledge_graph.get("npcs", [])
        if not npcs:
            return 0

        chunks = []
        metadatas = []
        for npc in npcs:
            parts = [f"NPC: {npc.get('name', '未知')}"]
            if npc.get("role"):
                parts.append(f"角色定位: {npc['role']}")
            if npc.get("public_description"):
                parts.append(f"公开描述: {npc['public_description']}")
            if npc.get("description"):
                parts.append(f"详细描述: {npc['description']}")
            chunks.append("\n".join(parts))
            metadatas.append({
                'npc_id': npc.get('npc_id', ''),
                'npc_name': npc.get('name', ''),
                'index': npcs.index(npc),
                'scenario_id': scenario_id,
                'is_hidden': npc.get('is_hidden', False),
                'role': npc.get('role', ''),
            })

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
                         json.dumps(metadatas[i]),
                         vec)
                    )
        logger.info('Indexed %d NPC chunks for scenario %s', len(chunks), scenario_id)
        return len(chunks)

    def index_rules(self, doc_id: str, title: str, category: str, content: str) -> int:
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

    def search(self, query: str, room_id: str | None = None,
               source_types: list[str] | None = None, top_k: int = 5) -> list[dict]:
        query_vec = self.embedding.embed([query])[0]
        with self.pg_db.get_conn() as conn:
            with conn.cursor() as cur:
                conditions = []
                params = []
                if room_id:
                    # Find the room's scenario_id first
                    cur.execute("SELECT scenario_id FROM rooms WHERE room_id = %s", (room_id,))
                    room_row = cur.fetchone()
                    scenario_id = room_row["scenario_id"] if room_row else None
                    # Safe scoping:
                    # (a) room-scoped chunks for this room
                    # (b) global rules (source_type = 'rule' with room_id IS NULL)
                    # (c) scenario chunks for THIS room's scenario only
                    conditions.append(
                        '(room_id = %s OR (source_type = %s AND room_id IS NULL)'
                    )
                    params.extend([room_id, 'rule'])
                    if scenario_id:
                        conditions[-1] += f" OR (source_type = %s AND source_id = %s)"
                        params.extend(['scenario', scenario_id])
                    conditions[-1] += ')'
                if source_types:
                    placeholders = ','.join(['%s'] * len(source_types))
                    conditions.append(f'source_type IN ({placeholders})')
                    params.extend(source_types)

                where = 'WHERE ' + ' AND '.join(conditions) if conditions else ''
                query_params = [query_vec, *params, query_vec, top_k]

                cur.execute(f"""
                    SELECT chunk_id, source_type, source_id, content, metadata,
                           1 - (embedding <=> %s::vector) as similarity
                    FROM document_chunks
                    {where}
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """, query_params)

                return cur.fetchall()

    def index_asset(self, scenario_id: str, asset_data: dict) -> int:
        """Index asset metadata (filename, type, tags, description)."""
        parts = []
        if asset_data.get("original_name"):
            parts.append(f"素材: {asset_data['original_name']}")
        if asset_data.get("mime_type"):
            parts.append(f"类型: {asset_data['mime_type']}")
        if asset_data.get("tags"):
            parts.append(f"标签: {asset_data['tags']}")
        if asset_data.get("description"):
            parts.append(f"描述: {asset_data['description']}")
        content = "\n".join(parts)
        if len(content) < 10:
            return 0
        vector = self.embedding.embed([content])[0]
        asset_id = asset_data.get("asset_id", str(uuid.uuid4()))
        with self.pg_db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO document_chunks (chunk_id, source_type, source_id, room_id, content, metadata, embedding) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s)',
                    (str(uuid.uuid4()), 'asset', asset_id, None, content,
                     json.dumps({"original_name": asset_data.get("original_name", "")}),
                     vector)
                )
        return 1

    def get_stats(self) -> dict:
        with self.pg_db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT source_type, COUNT(*) as cnt FROM document_chunks GROUP BY source_type')
                return {r['source_type']: r['cnt'] for r in cur.fetchall()}
