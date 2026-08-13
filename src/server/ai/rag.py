import uuid
import json
import logging
import re
from .embedding import HybridEmbedding

logger = logging.getLogger(__name__)


def chunk_text(text: str, max_chars: int = 500, overlap: int = 50) -> list[str]:
    return [chunk for chunk, _start, _end in chunk_text_with_offsets(text, max_chars, overlap)]


def chunk_text_with_offsets(
    text: str, max_chars: int = 500, overlap: int = 50
) -> list[tuple[str, int, int]]:
    chunks: list[tuple[str, int, int]] = []
    start = 0
    step_back = min(overlap, max_chars - 1)
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunk = text[start:end]
        if chunk.strip():
            chunks.append((chunk.strip(), start, end))
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
        _validate_embedding_batch(chunks, vectors)
        model_name = _embedding_model_name(self.embedding)
        with self.pg_db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'DELETE FROM document_chunks WHERE source_type = %s AND source_id = %s '
                    'AND scenario_version_id IS NULL',
                    ('scenario', scenario_id)
                )
                for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
                    cur.execute(
                        'INSERT INTO document_chunks (chunk_id, source_type, source_id, room_id, content, metadata, embedding, '
                        'embedding_model, embedding_dimensions) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                        (str(uuid.uuid4()), 'scenario', scenario_id, room_id, chunk,
                         json.dumps({'index': i, 'total': len(chunks), 'scenario_id': scenario_id, 'visibility': 'internal'}),
                         vec, model_name, len(vec))
                    )
        logger.info('Indexed %d chunks for scenario %s', len(chunks), scenario_id)
        return len(chunks)

    def index_scenario_version(
        self,
        scenario_id: str,
        scenario_version_id: str,
        parts: list[dict],
        visibility: str = "internal",
        embedding_model: str = "",
    ) -> int:
        rows: list[dict] = []
        for part in parts:
            text = str(part.get("text") or part.get("text_content") or "")
            if not text.strip():
                continue
            chunks = chunk_text_with_offsets(text)
            for index, (chunk, start_offset, end_offset) in enumerate(chunks):
                rows.append({
                    "chunk_id": str(uuid.uuid4()),
                    "content": chunk,
                    "source_part_id": part.get("source_part_id") or "",
                    "source_ref": _safe_source_ref(part.get("source_ref") or ""),
                    "page_number": part.get("page_number"),
                    "anchor": _sanitize_mapping(part.get("anchor") or {}),
                    "index": index,
                    "total": len(chunks),
                    "start_offset": start_offset,
                    "end_offset": end_offset,
                })

        vectors = self.embedding.embed([row["content"] for row in rows]) if rows else []
        _validate_embedding_batch(rows, vectors)
        model_name = _embedding_model_name(self.embedding)
        if embedding_model and embedding_model != model_name:
            logger.warning(
                "Ignoring stale embedding model override %s; actual model is %s",
                embedding_model,
                model_name,
            )
        with self.pg_db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM document_chunks "
                    "WHERE source_type = %s AND scenario_version_id = %s",
                    ("scenario", scenario_version_id),
                )
                for row, vector in zip(rows, vectors):
                    citation = {
                        "chunk_id": row["chunk_id"],
                        "source_type": "scenario",
                        "source_id": scenario_id,
                        "scenario_version_id": scenario_version_id,
                        "source_part_id": row["source_part_id"],
                        "source_ref": row["source_ref"],
                        "page_number": row["page_number"],
                        "anchor": row["anchor"],
                        "start_offset": row["start_offset"],
                        "end_offset": row["end_offset"],
                        "excerpt": _sanitize_excerpt(row["content"][:240]),
                    }
                    metadata = {
                        "scenario_id": scenario_id,
                        "scenario_version_id": scenario_version_id,
                        "source_part_id": row["source_part_id"],
                        "anchor": row["anchor"],
                        "index": row["index"],
                        "total": row["total"],
                    }
                    cur.execute(
                        "INSERT INTO document_chunks "
                        "(chunk_id, source_type, source_id, room_id, content, metadata, embedding, "
                        "source_part_id, scenario_version_id, visibility, citation, embedding_model, "
                        "embedding_dimensions) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            row["chunk_id"], "scenario", scenario_id, None,
                            row["content"], json.dumps(metadata, ensure_ascii=False), vector,
                            row["source_part_id"] or None, scenario_version_id, visibility,
                            json.dumps(citation, ensure_ascii=False), model_name, len(vector),
                        ),
                    )
        logger.info(
            "Indexed %d chunks for scenario %s version %s",
            len(rows), scenario_id, scenario_version_id,
        )
        return len(rows)

    def index_event(self, room_id: str, event_type: str, payload: dict, sequence: int):
        content = f'[{event_type}] {json.dumps(payload, ensure_ascii=False)}'
        if len(content) < 20:
            return
        vector = self.embedding.embed([content])[0]
        model_name = _embedding_model_name(self.embedding)
        with self.pg_db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO document_chunks (chunk_id, source_type, source_id, room_id, content, metadata, embedding, '
                    'embedding_model, embedding_dimensions) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                    (str(uuid.uuid4()), 'event', str(sequence), room_id, content,
                     json.dumps({'event_type': event_type, 'sequence': sequence}),
                     vector, model_name, len(vector))
                )

    def index_clue(self, room_id: str, clue_id: str, text: str, source: str = ''):
        vector = self.embedding.embed([text])[0]
        model_name = _embedding_model_name(self.embedding)
        with self.pg_db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO document_chunks (chunk_id, source_type, source_id, room_id, content, metadata, embedding, '
                    'embedding_model, embedding_dimensions) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                    (str(uuid.uuid4()), 'clue', clue_id, room_id, text,
                     json.dumps({'source': source}),
                     vector, model_name, len(vector))
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
        _validate_embedding_batch(chunks, vectors)
        model_name = _embedding_model_name(self.embedding)
        with self.pg_db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'DELETE FROM document_chunks WHERE source_type = %s AND source_id = %s',
                    ('character', character_id)
                )
                for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
                    cur.execute(
                        'INSERT INTO document_chunks (chunk_id, source_type, source_id, room_id, content, metadata, embedding, '
                        'embedding_model, embedding_dimensions) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                        (str(uuid.uuid4()), 'character', character_id, room_id, chunk,
                         json.dumps({'index': i, 'total': len(chunks)}),
                         vec, model_name, len(vec))
                    )
        logger.info('Indexed %d chunks for character %s', len(chunks), character_id)
        return len(chunks)

    def index_npc_graph(
        self,
        scenario_id: str,
        knowledge_graph: dict,
        room_id: str | None = None,
        *,
        scenario_version_id: str | None = None,
        visibility: str = "internal",
    ) -> int:
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
        _validate_embedding_batch(chunks, vectors)
        model_name = _embedding_model_name(self.embedding)
        with self.pg_db.get_conn() as conn:
            with conn.cursor() as cur:
                if scenario_version_id:
                    cur.execute(
                        "DELETE FROM document_chunks WHERE source_type = %s "
                        "AND source_id = %s AND scenario_version_id = %s",
                        ("npc", scenario_id, scenario_version_id),
                    )
                else:
                    cur.execute(
                        "DELETE FROM document_chunks WHERE source_type = %s "
                        "AND source_id = %s AND scenario_version_id IS NULL",
                        ("npc", scenario_id),
                    )
                for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
                    chunk_id = str(uuid.uuid4())
                    npc_id = metadatas[i].get("npc_id", "")
                    citation = {
                        "chunk_id": chunk_id,
                        "source_type": "npc",
                        "source_id": scenario_id,
                        "scenario_version_id": scenario_version_id or "",
                        "source_ref": f"worldbook:npc:{npc_id or i}",
                        "excerpt": _sanitize_excerpt(chunk[:240]),
                    }
                    cur.execute(
                        "INSERT INTO document_chunks "
                        "(chunk_id, source_type, source_id, room_id, content, metadata, embedding, "
                        "scenario_version_id, visibility, citation, embedding_model, embedding_dimensions) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            chunk_id, "npc", scenario_id, room_id, chunk,
                            json.dumps(metadatas[i], ensure_ascii=False), vec,
                            scenario_version_id, visibility,
                            json.dumps(citation, ensure_ascii=False), model_name, len(vec),
                        ),
                    )
        logger.info('Indexed %d NPC chunks for scenario %s', len(chunks), scenario_id)
        return len(chunks)

    def index_content_projection(
        self,
        scenario_id: str,
        scenario_version_id: str,
        content_items: list[dict],
    ) -> int:
        rows: list[dict] = []
        for item in content_items:
            if not isinstance(item, dict):
                continue
            content = _content_projection_text(item)
            if not content:
                continue
            citation_base = _sanitize_mapping(_parse_json_dict(item.get("citation")))
            source_part_id = str(citation_base.get("source_part_id") or "")
            for index, (chunk, start_offset, end_offset) in enumerate(
                chunk_text_with_offsets(content)
            ):
                rows.append({
                    "content_item_id": str(item.get("content_item_id") or ""),
                    "item_type": str(item.get("item_type") or "content"),
                    "logical_key": str(item.get("logical_key") or ""),
                    "title": str(item.get("title") or ""),
                    "visibility": _content_visibility(item.get("visibility")),
                    "citation": citation_base,
                    "source_part_id": source_part_id or None,
                    "content": chunk,
                    "index": index,
                    "start_offset": start_offset,
                    "end_offset": end_offset,
                })

        vectors = self.embedding.embed([row["content"] for row in rows]) if rows else []
        _validate_embedding_batch(rows, vectors)
        model_name = _embedding_model_name(self.embedding)
        with self.pg_db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM document_chunks WHERE source_type = %s "
                    "AND scenario_version_id = %s",
                    ("content", scenario_version_id),
                )
                for row, vector in zip(rows, vectors):
                    chunk_id = str(uuid.uuid4())
                    citation = dict(row["citation"])
                    citation.update({
                        "chunk_id": chunk_id,
                        "source_type": "content",
                        "source_id": row["content_item_id"],
                        "scenario_version_id": scenario_version_id,
                        "source_part_id": row["source_part_id"] or "",
                        "source_ref": _safe_source_ref(
                            str(citation.get("source_ref") or "")
                            or f"content:{row['item_type']}:{row['logical_key']}"
                        ),
                        "start_offset": row["start_offset"],
                        "end_offset": row["end_offset"],
                        "excerpt": _sanitize_excerpt(row["content"][:240]),
                    })
                    metadata = {
                        "scenario_id": scenario_id,
                        "scenario_version_id": scenario_version_id,
                        "content_item_id": row["content_item_id"],
                        "item_type": row["item_type"],
                        "logical_key": row["logical_key"],
                        "title": row["title"],
                        "index": row["index"],
                    }
                    cur.execute(
                        "INSERT INTO document_chunks "
                        "(chunk_id, source_type, source_id, room_id, content, metadata, embedding, "
                        "source_part_id, scenario_version_id, visibility, citation, embedding_model, "
                        "embedding_dimensions) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            chunk_id,
                            "content",
                            row["content_item_id"],
                            None,
                            row["content"],
                            json.dumps(metadata, ensure_ascii=False),
                            vector,
                            row["source_part_id"],
                            scenario_version_id,
                            row["visibility"],
                            json.dumps(citation, ensure_ascii=False),
                            model_name,
                            len(vector),
                        ),
                    )
        logger.info(
            "Indexed %d canonical content chunks for scenario %s version %s",
            len(rows), scenario_id, scenario_version_id,
        )
        return len(rows)

    def index_rules(
        self,
        doc_id: str,
        title: str,
        category: str,
        content: str,
        *,
        rule_set_version_id: str | None = None,
        source_document_id: str | None = None,
        source_part_id: str | None = None,
        visibility: str = "host_only",
        license_type: str = "authorized",
        source_ref: str = "",
        citation_base: dict | None = None,
    ) -> int:
        chunks = chunk_text_with_offsets(content, max_chars=500, overlap=50)
        if not chunks:
            return 0

        vectors = self.embedding.embed([chunk for chunk, _start, _end in chunks])
        _validate_embedding_batch(chunks, vectors)
        model_name = _embedding_model_name(self.embedding)
        with self.pg_db.get_conn() as conn:
            with conn.cursor() as cur:
                if rule_set_version_id:
                    cur.execute(
                        "DELETE FROM document_chunks WHERE source_type = %s "
                        "AND source_id = %s AND rule_set_version_id = %s",
                        ("rule", doc_id, rule_set_version_id),
                    )
                else:
                    cur.execute(
                        "DELETE FROM document_chunks WHERE source_type = %s "
                        "AND source_id = %s AND rule_set_version_id IS NULL",
                        ("rule", doc_id),
                    )
                for index, ((chunk, start_offset, end_offset), vector) in enumerate(zip(chunks, vectors)):
                    chunk_id = str(uuid.uuid4())
                    citation = _sanitize_mapping(citation_base or {})
                    citation.update({
                        "chunk_id": chunk_id,
                        "source_type": "rule",
                        "source_id": doc_id,
                        "source_part_id": source_part_id or "",
                        "rule_set_version_id": rule_set_version_id or "",
                        "source_ref": _safe_source_ref(source_ref),
                        "start_offset": start_offset,
                        "end_offset": end_offset,
                        "excerpt": _sanitize_excerpt(chunk[:240]),
                    })
                    metadata = {
                        "title": title,
                        "category": category,
                        "index": index,
                        "total": len(chunks),
                        "license_type": license_type,
                        "rule_set_version_id": rule_set_version_id or "",
                    }
                    cur.execute(
                        "INSERT INTO document_chunks "
                        "(chunk_id, source_type, source_id, room_id, content, metadata, embedding, "
                        "source_part_id, rule_set_version_id, visibility, citation, embedding_model, "
                        "embedding_dimensions) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            chunk_id, "rule", doc_id, None, chunk,
                            json.dumps(metadata, ensure_ascii=False), vector,
                            source_part_id, rule_set_version_id, visibility,
                            json.dumps(citation, ensure_ascii=False), model_name, len(vector),
                        ),
                    )

        with self.pg_db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO rule_documents (
                           doc_id, rule_set_version_id, source_document_id, title, category,
                           content, visibility, license_type, source_ref
                       ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (doc_id) DO UPDATE SET
                           rule_set_version_id = EXCLUDED.rule_set_version_id,
                           source_document_id = EXCLUDED.source_document_id,
                           title = EXCLUDED.title,
                           category = EXCLUDED.category,
                           content = EXCLUDED.content,
                           visibility = EXCLUDED.visibility,
                           license_type = EXCLUDED.license_type,
                           source_ref = EXCLUDED.source_ref""",
                    (
                        doc_id, rule_set_version_id, source_document_id, title, category,
                        content, visibility, license_type, _safe_source_ref(source_ref),
                    ),
                )

        logger.info('Indexed %d chunks for rule %s (%s)', len(chunks), doc_id, category)
        return len(chunks)

    def index_rule_pages(
        self,
        source_document_id: str,
        rule_set_version_id: str,
        pages: list[dict],
    ) -> int:
        """Index only complete chunks whose offsets remain on one physical page."""
        rows = []
        for page in pages:
            if page.get("extraction_status") != "indexable":
                continue
            source_part_id = str(page.get("source_part_id") or "")
            page_number = int(page.get("page_number") or 0)
            text = str(page.get("text") or "")
            if not source_part_id or page_number < 1:
                raise ValueError("indexable rule page requires source part and page number")
            for chunk, start_offset, end_offset in chunk_text_with_offsets(text, max_chars=500, overlap=50):
                rows.append((source_part_id, page_number, chunk, start_offset, end_offset))
        if not rows:
            return 0
        vectors = self.embedding.embed([row[2] for row in rows])
        _validate_embedding_batch(rows, vectors)
        model_name = _embedding_model_name(self.embedding)
        with self.pg_db.get_conn() as conn:
            with conn.cursor() as cur:
                for source_part_id in {row[0] for row in rows}:
                    cur.execute(
                        "DELETE FROM document_chunks WHERE source_type = %s "
                        "AND rule_set_version_id = %s AND source_part_id = %s",
                        ("rule", rule_set_version_id, source_part_id),
                    )
                for index, ((source_part_id, page_number, chunk, start_offset, end_offset), vector) in enumerate(zip(rows, vectors)):
                    chunk_id = str(uuid.uuid4())
                    citation = {
                        "chunk_id": chunk_id,
                        "source_type": "rule",
                        "source_id": source_document_id,
                        "source_document_id": source_document_id,
                        "source_part_id": source_part_id,
                        "rule_set_version_id": rule_set_version_id,
                        "page_number": page_number,
                        "start_offset": start_offset,
                        "end_offset": end_offset,
                        "excerpt": _sanitize_excerpt(chunk[:240]),
                    }
                    metadata = {
                        "title": "Call of Cthulhu 7th Edition Core Rules",
                        "category": "coc7-core-rules",
                        "index": index,
                        "license_type": "authorized",
                        "rule_set_version_id": rule_set_version_id,
                    }
                    cur.execute(
                        "INSERT INTO document_chunks "
                        "(chunk_id, source_type, source_id, room_id, content, metadata, embedding, "
                        "source_part_id, rule_set_version_id, visibility, citation, embedding_model, "
                        "embedding_dimensions) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            chunk_id, "rule", source_document_id, None, chunk,
                            json.dumps(metadata, ensure_ascii=False), vector,
                            source_part_id, rule_set_version_id, "internal",
                            json.dumps(citation, ensure_ascii=False), model_name, len(vector),
                        ),
                    )
        return len(rows)

    def search(
        self,
        query: str,
        room_id: str | None = None,
        source_types: list[str] | None = None,
        top_k: int = 5,
        *,
        audience: str = "ai",
        scenario_version_id: str | None = None,
        rule_set_version_id: str | None = None,
    ) -> list[dict]:
        top_k = max(1, min(int(top_k), 50))
        try:
            query_vec = self.embedding.embed([query])[0]
            query_embedding_model = _embedding_model_name(self.embedding)
            query_embedding_dimensions = len(query_vec)
        except Exception as exc:
            logger.warning("Embedding unavailable for RAG search; using lexical fallback: %s", exc)
            query_vec = None
            query_embedding_model = ""
            query_embedding_dimensions = 0

        with self.pg_db.get_conn() as conn:
            with conn.cursor() as cur:
                conditions: list[str] = []
                filter_params: list = []
                rule_priority_sql = "0 AS rule_priority"
                rule_priority_params: list = []
                if room_id:
                    cur.execute(
                        "SELECT scenario_id, scenario_version_id FROM rooms WHERE room_id = %s",
                        (room_id,),
                    )
                    room_row = cur.fetchone()
                    scenario_id = room_row["scenario_id"] if room_row else None
                    bound_version = room_row.get("scenario_version_id") if room_row else None
                    priority_candidates = [
                        "COALESCE((SELECT 3000000 + LEAST(GREATEST(rrb.priority, 0), 999999) "
                        "FROM room_rule_bindings rrb "
                        "WHERE rrb.room_id = %s "
                        "AND rrb.rule_set_version_id = document_chunks.rule_set_version_id), 0)"
                    ]
                    rule_priority_params.append(room_id)
                    if bound_version:
                        priority_candidates.append(
                            "COALESCE((SELECT CASE WHEN bound_rs.is_base THEN 1000000 ELSE 2000000 END "
                            "+ LEAST(GREATEST(srb.priority, 0), 999999) "
                            "FROM scenario_rule_bindings srb "
                            "JOIN rule_set_versions bound_rsv ON bound_rsv.rule_set_version_id = srb.rule_set_version_id "
                            "JOIN rule_sets bound_rs ON bound_rs.rule_set_id = bound_rsv.rule_set_id "
                            "WHERE srb.scenario_version_id = %s "
                            "AND srb.rule_set_version_id = document_chunks.rule_set_version_id), 0)"
                        )
                        rule_priority_params.append(bound_version)
                    if not bound_version:
                        priority_candidates.append(
                            "COALESCE((SELECT 1000000 FROM rule_set_versions priority_rsv "
                            "JOIN rule_sets priority_rs ON priority_rs.rule_set_id = priority_rsv.rule_set_id "
                            "WHERE priority_rsv.rule_set_version_id = document_chunks.rule_set_version_id "
                            "AND priority_rs.system = 'coc7' AND priority_rs.is_base = TRUE "
                            "AND priority_rs.status = 'published' "
                            "AND priority_rsv.status = 'published'), 0)"
                        )
                    rule_priority_sql = (
                        "CASE WHEN source_type <> 'rule' THEN 0 "
                        "WHEN rule_set_version_id IS NULL THEN 500000 ELSE GREATEST("
                        + ", ".join(priority_candidates)
                        + ") END AS rule_priority"
                    )
                    scope = ["(room_id = %s AND source_type NOT IN (%s, %s, %s))"]
                    filter_params.extend([room_id, "scenario", "npc", "content"])
                    rule_scope = (
                        "(source_type = %s AND room_id IS NULL AND "
                        + ("rule_set_version_id IN (" if bound_version else "(rule_set_version_id IS NULL OR rule_set_version_id IN (")
                        + "SELECT rule_set_version_id FROM room_rule_bindings WHERE room_id = %s"
                    )
                    filter_params.extend(["rule", room_id])
                    if bound_version:
                        rule_scope += (
                            " UNION SELECT rule_set_version_id FROM scenario_rule_bindings "
                            "WHERE scenario_version_id = %s"
                        )
                        filter_params.append(bound_version)
                    if not bound_version:
                        rule_scope += (
                            " UNION SELECT rsv.rule_set_version_id "
                            "FROM rule_set_versions rsv JOIN rule_sets rs "
                            "ON rs.rule_set_id = rsv.rule_set_id "
                            "WHERE rs.system = 'coc7' AND rs.is_base = TRUE "
                            "AND rs.status = 'published' AND rsv.status = 'published'"
                        )
                    rule_scope += "))" if bound_version else ")))"
                    scope.append(rule_scope)
                    if scenario_id:
                        scenario_scope = (
                            "((source_type IN (%s, %s) AND source_id = %s) "
                            "OR source_type = %s"
                        )
                        filter_params.extend(["scenario", "npc", scenario_id, "content"])
                        if bound_version:
                            scenario_scope += " AND scenario_version_id = %s)"
                            filter_params.append(bound_version)
                        else:
                            scenario_scope += " AND scenario_version_id IS NULL)"
                        scope.append(scenario_scope)
                    conditions.append("(" + " OR ".join(scope) + ")")
                elif audience in {"ai", "admin"} and scenario_version_id:
                    conditions.append(
                        "(scenario_version_id = %s OR (source_type = %s "
                        "AND room_id IS NULL AND rule_set_version_id IN ("
                        "SELECT rule_set_version_id FROM scenario_rule_bindings "
                        "WHERE scenario_version_id = %s)))"
                    )
                    filter_params.extend([
                        scenario_version_id,
                        "rule",
                        scenario_version_id,
                    ])

                if rule_set_version_id:
                    conditions.append("rule_set_version_id = %s")
                    filter_params.append(rule_set_version_id)

                allowed_visibility = _allowed_visibilities(audience)
                if allowed_visibility is not None:
                    placeholders = ",".join(["%s"] * len(allowed_visibility))
                    conditions.append(f"visibility IN ({placeholders})")
                    filter_params.extend(allowed_visibility)

                if source_types:
                    placeholders = ','.join(['%s'] * len(source_types))
                    conditions.append(f'source_type IN ({placeholders})')
                    filter_params.extend(source_types)

                where = 'WHERE ' + ' AND '.join(conditions) if conditions else ''
                lexical_pattern = f"%{query}%"
                lexical_sql = (
                    "CASE WHEN content ILIKE %s THEN 1.0 "
                    "ELSE ts_rank_cd(to_tsvector('simple', content), "
                    "plainto_tsquery('simple', %s)) END"
                )
                selected_columns = (
                    "chunk_id, source_type, source_id, room_id, source_part_id, "
                    "scenario_version_id, rule_set_version_id, content, metadata, citation, visibility"
                )
                order_by = (
                    "rule_priority DESC, score DESC"
                    if source_types and set(source_types) == {"rule"}
                    else "score DESC"
                )
                if query_vec is not None:
                    sql = f"""
                        WITH ranked AS (
                            SELECT {selected_columns},
                                   CASE WHEN embedding_model = %s
                                          AND embedding_dimensions = %s
                                   THEN GREATEST(0.0, 1 - (embedding <=> %s::vector))
                                   ELSE 0.0 END AS similarity,
                                   {lexical_sql} AS lexical_score,
                                   {rule_priority_sql}
                            FROM document_chunks
                            {where}
                        )
                        SELECT *, (similarity * 0.75 + lexical_score * 0.25) AS score
                        FROM ranked
                        ORDER BY {order_by}
                        LIMIT %s
                    """
                    query_params = [
                        query_embedding_model, query_embedding_dimensions,
                        query_vec, lexical_pattern, query,
                        *rule_priority_params, *filter_params, top_k,
                    ]
                else:
                    sql = f"""
                        WITH ranked AS (
                            SELECT {selected_columns}, 0.0::float AS similarity,
                                   {lexical_sql} AS lexical_score,
                                   {rule_priority_sql}
                            FROM document_chunks
                            {where}
                        )
                        SELECT *, lexical_score AS score
                        FROM ranked
                        ORDER BY {order_by}
                        LIMIT %s
                    """
                    query_params = [
                        lexical_pattern, query,
                        *rule_priority_params, *filter_params, top_k,
                    ]

                cur.execute(sql, query_params)
                return [_normalize_search_row(row) for row in cur.fetchall()]

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
        model_name = _embedding_model_name(self.embedding)
        asset_id = asset_data.get("asset_id", str(uuid.uuid4()))
        with self.pg_db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO document_chunks (chunk_id, source_type, source_id, room_id, content, metadata, embedding, '
                    'embedding_model, embedding_dimensions) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
                    (str(uuid.uuid4()), 'asset', asset_id, None, content,
                     json.dumps({"original_name": asset_data.get("original_name", "")}),
                     vector, model_name, len(vector))
                )
        return 1

    def get_stats(self) -> dict:
        with self.pg_db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT source_type, COUNT(*) as cnt FROM document_chunks GROUP BY source_type')
                return {r['source_type']: r['cnt'] for r in cur.fetchall()}


def _allowed_visibilities(audience: str) -> list[str] | None:
    if audience in {"ai", "admin"}:
        return None
    if audience == "host":
        return ["public", "party", "host_only"]
    return ["public", "party"]


def _content_projection_text(item: dict) -> str:
    payload = _parse_json_dict(item.get("payload"))
    item_type = str(item.get("item_type") or "content").strip()
    title = str(item.get("title") or item.get("logical_key") or "").strip()
    if not item_type or not title:
        return ""
    fields = [f"{item_type}: {title}"]
    for key in ("description", "summary", "text", "public_description", "role", "location", "type"):
        value = payload.get(key)
        if value not in (None, ""):
            fields.append(f"{key}: {value}")
    if len(fields) == 1:
        fields.append(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return "\n".join(fields).strip()


def _content_visibility(value) -> str:
    visibility = str(value or "").strip()
    if visibility in {"public", "party", "host_only", "internal"}:
        return visibility
    return "host_only"


def _parse_json_dict(value) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _normalize_search_row(row) -> dict:
    result = dict(row)
    metadata = _parse_json_dict(result.get("metadata"))
    citation = _sanitize_mapping(_parse_json_dict(result.get("citation")))
    citation.setdefault("chunk_id", result.get("chunk_id", ""))
    citation.setdefault("source_type", result.get("source_type", ""))
    citation.setdefault("source_id", result.get("source_id", ""))
    citation.setdefault("source_part_id", result.get("source_part_id", ""))
    citation.setdefault("scenario_version_id", result.get("scenario_version_id", ""))
    citation.setdefault("rule_set_version_id", result.get("rule_set_version_id", ""))
    citation.setdefault("source_ref", metadata.get("source_ref", ""))
    citation["excerpt"] = _sanitize_excerpt(
        str(citation.get("excerpt") or result.get("content") or "")[:240]
    )
    result["metadata"] = metadata
    result["citation"] = citation
    similarity = float(result.get("similarity") or 0)
    lexical_score = float(result.get("lexical_score") or 0)
    result["similarity"] = similarity
    result["lexical_score"] = lexical_score
    result["score"] = float(result.get("score") or similarity * 0.75 + lexical_score * 0.25)
    return result


_PATH_KEYS = {"absolute_path", "local_path", "original_file_path", "relative_path", "storage_path"}
_EMBEDDED_PATH_PATTERNS = (
    re.compile(r"(?i)(?:\\\\[^\\\s\"'<>]+\\[^\s\"'<>]+)"),
    re.compile(r"(?i)(?<![\w])(?:[A-Z]:[\\/][^\s\"'<>]+)"),
    re.compile(r"(?i)(?:file://[^\s\"'<>]+)"),
    re.compile(r"(?<![\w:/])/(?:[^/\s\"'<>]+/)+[^/\s\"'<>]+"),
)


def _sanitize_mapping(value):
    if isinstance(value, dict):
        return {
            key: _sanitize_mapping(item)
            for key, item in value.items()
            if key.lower() not in _PATH_KEYS and not key.lower().endswith("_path")
        }
    if isinstance(value, list):
        return [_sanitize_mapping(item) for item in value]
    if isinstance(value, str):
        return _sanitize_excerpt(value)
    return value


def _safe_source_ref(value: str) -> str:
    sanitized = _sanitize_mapping(str(value))
    return sanitized if isinstance(sanitized, str) else ""


def _sanitize_excerpt(value: str) -> str:
    sanitized = value
    for pattern in _EMBEDDED_PATH_PATTERNS:
        sanitized = pattern.sub("[redacted-path]", sanitized)
    return sanitized


def _validate_embedding_batch(rows: list, vectors: list) -> None:
    if len(rows) != len(vectors):
        raise RuntimeError(
            f"embedding_count_mismatch: expected={len(rows)} actual={len(vectors)}"
        )
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) > 1:
        raise RuntimeError("embedding_dimension_mismatch")


def _embedding_model_name(embedding) -> str:
    return str(
        getattr(embedding, "model_name", "")
        or type(embedding).__name__
    )
