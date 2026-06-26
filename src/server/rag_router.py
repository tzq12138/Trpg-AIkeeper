import logging
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/rag')


class IndexRequest(BaseModel):
    scenario_id: str
    room_id: str | None = None


class SearchRequest(BaseModel):
    query: str
    room_id: str | None = None
    source_types: list[str] | None = None
    top_k: int = 5


@router.post('/index')
async def index_scenario(request: Request, body: IndexRequest):
    rag = request.app.state.rag
    if not rag:
        raise HTTPException(503, 'RAG not available')
    conn = request.app.state.db
    row = conn.execute('SELECT raw_text FROM scenarios WHERE scenario_id = %s', (body.scenario_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Scenario not found')
    count = rag.index_scenario(body.scenario_id, row['raw_text'], body.room_id)
    return {'chunks_indexed': count}


@router.post('/index-character')
async def index_character(request: Request, body: dict):
    rag = request.app.state.rag
    if not rag:
        raise HTTPException(503, 'RAG not available')
    room_id = body.get('room_id')
    character_id = body.get('character_id')
    xlsx_data = body.get('xlsx_data', {})
    count = rag.index_character(room_id, character_id, xlsx_data)
    return {'chunks': count}


@router.post('/index-npc')
async def index_npc(request: Request, body: dict):
    rag = request.app.state.rag
    if not rag:
        raise HTTPException(503, 'RAG not available')
    scenario_id = body.get('scenario_id')
    knowledge_graph = body.get('knowledge_graph', {})
    room_id = body.get('room_id')
    count = rag.index_npc_graph(scenario_id, knowledge_graph, room_id)
    return {'chunks': count}


@router.post('/index-rules')
async def index_rules(request: Request, body: dict):
    rag = request.app.state.rag
    if not rag:
        raise HTTPException(503, 'RAG not available')
    doc_id = body.get('doc_id')
    title = body.get('title', '')
    category = body.get('category', 'general')
    content = body.get('content', '')
    count = rag.index_rules(doc_id, title, category, content)
    return {'chunks': count}


@router.post('/search')
async def search(request: Request, body: SearchRequest):
    rag = request.app.state.rag
    if not rag:
        raise HTTPException(503, 'RAG not available')
    results = rag.search(body.query, body.room_id, body.source_types, body.top_k)
    return results


@router.get('/rule-docs')
async def rule_docs(request: Request):
    conn = request.app.state.db
    rows = conn.execute(
        """
        SELECT rd.doc_id, rd.title, rd.category, length(rd.content) AS content_chars,
               COUNT(dc.chunk_id) AS chunks
        FROM rule_documents rd
        LEFT JOIN document_chunks dc
          ON dc.source_type = 'rule' AND dc.source_id = rd.doc_id
        GROUP BY rd.doc_id, rd.title, rd.category, rd.content
        ORDER BY rd.title
        """
    ).fetchall()
    return [
        {
            "doc_id": row["doc_id"],
            "title": row["title"],
            "category": row["category"],
            "content_chars": row["content_chars"] or 0,
            "chunks": int(row["chunks"] or 0),
        }
        for row in rows
    ]


@router.get('/stats')
async def stats(request: Request):
    rag = request.app.state.rag
    if not rag:
        raise HTTPException(503, 'RAG not available')
    return rag.get_stats()
