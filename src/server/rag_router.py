import logging
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/rag')


def _require_auth_for_room(request: Request, room_id: str, write: bool = False):
    """Verify the request is from admin, room owner, or room player.
    For write operations, only admin or room owner is allowed."""
    from .router_auth import get_account_from_token
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "请先登录")
    if account.get("role") == "admin":
        return account
    conn = request.app.state.db
    room = conn.execute(
        "SELECT owner_account_id FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()
    if not room:
        raise HTTPException(404, "房间不存在")
    if room.get("owner_account_id") == account.get("account_id"):
        return account
    if write:
        raise HTTPException(403, "仅房主或管理员可操作")
    # For read/search: check if the account has a character in this room
    char = conn.execute(
        "SELECT character_id FROM characters WHERE room_id = %s AND account_id = %s LIMIT 1",
        (room_id, account.get("account_id")),
    ).fetchone()
    if not char:
        raise HTTPException(403, "不是该房间的房主或玩家")
    return account


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
    """Index scenario text — admin or room owner only."""
    if body.room_id:
        _require_auth_for_room(request, body.room_id, write=True)
    else:
        from .router_auth import get_account_from_token
        account = get_account_from_token(request)
        if not account or account.get("role") != "admin":
            raise HTTPException(403, "仅管理员可索引全局剧本")
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
    """Index character data — admin or room owner only."""
    room_id = body.get('room_id')
    if room_id:
        _require_auth_for_room(request, room_id, write=True)
    else:
        from .router_auth import get_account_from_token
        account = get_account_from_token(request)
        if not account or account.get("role") != "admin":
            raise HTTPException(403, "仅管理员可操作")
    rag = request.app.state.rag
    if not rag:
        raise HTTPException(503, 'RAG not available')
    character_id = body.get('character_id')
    xlsx_data = body.get('xlsx_data', {})
    count = rag.index_character(room_id, character_id, xlsx_data)
    return {'chunks': count}


@router.post('/index-npc')
async def index_npc(request: Request, body: dict):
    """Index NPC graph — admin or room owner only."""
    room_id = body.get('room_id')
    if room_id:
        _require_auth_for_room(request, room_id, write=True)
    else:
        from .router_auth import get_account_from_token
        account = get_account_from_token(request)
        if not account or account.get("role") != "admin":
            raise HTTPException(403, "仅管理员可操作")
    rag = request.app.state.rag
    if not rag:
        raise HTTPException(503, 'RAG not available')
    scenario_id = body.get('scenario_id')
    knowledge_graph = body.get('knowledge_graph', {})
    count = rag.index_npc_graph(scenario_id, knowledge_graph, room_id)
    return {'chunks': count}


@router.post('/index-rules')
async def index_rules(request: Request, body: dict):
    """Index rules — admin or room owner."""
    room_id = body.get('doc_id')
    from .router_auth import get_account_from_token
    account = get_account_from_token(request)
    if not account or account.get("role") != "admin":
        raise HTTPException(403, "仅管理员可索引规则书")
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
    """Search RAG — must be room player, owner, or admin."""
    from .router_auth import get_account_from_token
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "请先登录")
    if account.get("role") == "admin":
        pass  # admin can search any room
    elif body.room_id:
        _require_auth_for_room(request, body.room_id, write=False)
    else:
        raise HTTPException(403, "请提供 room_id 或使用管理员账号")
    rag = request.app.state.rag
    if not rag:
        raise HTTPException(503, 'RAG not available')
    results = rag.search(body.query, body.room_id, body.source_types, body.top_k)
    return results


@router.get('/rule-docs')
async def rule_docs(request: Request):
    """List rule documents — requires login."""
    from .router_auth import get_account_from_token
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "请先登录")
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
    """RAG index stats — requires login."""
    from .router_auth import get_account_from_token
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "请先登录")
    rag = request.app.state.rag
    if not rag:
        raise HTTPException(503, 'RAG not available')
    return rag.get_stats()
