import logging
import json
import re
import uuid
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/rag')
_ALLOWED_RULE_LICENSES = {"authorized", "open"}
_RULE_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


def _require_auth_for_room(request: Request, room_id: str, write: bool = False):
    """Verify the request is from admin, room owner, or room player.
    For write operations, only admin or room owner is allowed."""
    from .router_auth import get_account_from_token
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "请先登录")
    conn = request.app.state.db
    room = conn.execute(
        "SELECT owner_account_id FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()
    if not room:
        raise HTTPException(404, "房间不存在")
    _require_room_rule_source(conn, room_id)
    if account.get("role") == "admin":
        return account
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


def _require_room_rule_source(conn, room_id: str) -> None:
    from .rule_source_lifecycle import (
        RuleSourceRetiredError,
        ensure_room_rule_source_available,
    )

    try:
        ensure_room_rule_source_available(conn, room_id)
    except RuleSourceRetiredError as exc:
        raise HTTPException(409, detail=exc.detail) from exc


def _require_admin(request: Request) -> dict:
    from .router_auth import get_account_from_token

    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "请先登录")
    if account.get("role") != "admin":
        raise HTTPException(403, "仅管理员可操作规则资料")
    return account


class IndexRequest(BaseModel):
    scenario_id: str
    room_id: str | None = None


class SearchRequest(BaseModel):
    query: str
    room_id: str | None = None
    source_types: list[str] | None = None
    top_k: int = 5
    scenario_version_id: str | None = None
    rule_set_version_id: str | None = None


@router.post('/index')
async def index_scenario(request: Request, body: IndexRequest):
    """Index scenario text — admin or room owner only."""
    if body.room_id:
        _require_auth_for_room(request, body.room_id, write=True)
        room = request.app.state.db.execute(
            "SELECT scenario_id, scenario_version_id FROM rooms WHERE room_id = %s",
            (body.room_id,),
        ).fetchone()
        if not room or room.get("scenario_id") != body.scenario_id:
            raise HTTPException(409, "剧本与房间不匹配")
        if room.get("scenario_version_id"):
            raise HTTPException(409, "版本房间必须使用指定版本重建接口")
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
    """Index an authorized document into a versioned rule set."""
    _require_admin(request)
    rag = request.app.state.rag
    if not rag:
        raise HTTPException(503, 'RAG not available')
    rule_set_version_id = str(body.get("rule_set_version_id") or "").strip()
    if not rule_set_version_id:
        raise HTTPException(400, "rule_set_version_id required")
    version = request.app.state.db.execute(
        """
        SELECT rsv.status, rs.license_type
        FROM rule_set_versions rsv
        JOIN rule_sets rs ON rs.rule_set_id = rsv.rule_set_id
        WHERE rsv.rule_set_version_id = %s
        """,
        (rule_set_version_id,),
    ).fetchone()
    if not version:
        raise HTTPException(404, "规则版本不存在")
    if version.get("status") != "draft":
        raise HTTPException(409, "已发布规则版本不可原地修改，请创建新版本")
    if version.get("license_type") not in _ALLOWED_RULE_LICENSES:
        raise HTTPException(409, "规则资料缺少可验证授权")

    doc_id = str(body.get('doc_id') or uuid.uuid4())
    title = str(body.get('title') or '').strip()
    category = str(body.get('category') or 'general').strip()
    content = str(body.get('content') or '')
    if not title or not content.strip():
        raise HTTPException(400, "title and content required")
    if len(content) > 5_000_000:
        raise HTTPException(413, "规则文档过大")
    count = rag.index_rules(
        doc_id,
        title,
        category,
        content,
        rule_set_version_id=rule_set_version_id,
        source_document_id=body.get("source_document_id"),
        source_part_id=body.get("source_part_id"),
        visibility="host_only",
        license_type=version["license_type"],
        source_ref=str(body.get("source_ref") or ""),
        citation_base=body.get("citation") if isinstance(body.get("citation"), dict) else {},
    )
    return {'chunks': count}


@router.post('/rule-sets')
async def create_rule_set(request: Request, body: dict):
    account = _require_admin(request)
    name = str(body.get("name") or "").strip()
    slug = str(body.get("slug") or "").strip().lower()
    system = str(body.get("system") or "coc7").strip().lower()
    license_type = str(body.get("license_type") or "").strip().lower()
    if not name or not _RULE_SLUG_PATTERN.fullmatch(slug):
        raise HTTPException(400, "name or slug invalid")
    if license_type not in _ALLOWED_RULE_LICENSES:
        raise HTTPException(400, "仅允许 authorized 或 open 授权资料")
    existing = request.app.state.db.execute(
        "SELECT rule_set_id FROM rule_sets WHERE slug = %s",
        (slug,),
    ).fetchone()
    if existing:
        raise HTTPException(409, "规则集 slug 已存在")
    rule_set_id = str(uuid.uuid4())
    request.app.state.db.execute(
        """
        INSERT INTO rule_sets (
            rule_set_id, name, slug, system, description, is_base,
            license_type, status, created_by
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            rule_set_id,
            name,
            slug,
            system,
            str(body.get("description") or ""),
            bool(body.get("is_base", False)),
            license_type,
            "draft",
            account.get("account_id", "unknown"),
        ),
    )
    return {"rule_set_id": rule_set_id, "status": "draft"}


@router.post('/rule-sets/{rule_set_id}/versions')
async def create_rule_set_version(request: Request, rule_set_id: str, body: dict):
    account = _require_admin(request)
    conn = request.app.state.db
    rule_set = conn.execute(
        "SELECT rule_set_id FROM rule_sets WHERE rule_set_id = %s",
        (rule_set_id,),
    ).fetchone()
    if not rule_set:
        raise HTTPException(404, "规则集不存在")
    row = conn.execute(
        "SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version "
        "FROM rule_set_versions WHERE rule_set_id = %s",
        (rule_set_id,),
    ).fetchone()
    version_number = int(row["next_version"])
    rule_set_version_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO rule_set_versions (
            rule_set_version_id, rule_set_id, version_number, label, status,
            source_sha256, metadata, created_by
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            rule_set_version_id,
            rule_set_id,
            version_number,
            str(body.get("label") or f"v{version_number}"),
            "draft",
            body.get("source_sha256"),
            json.dumps(
                body.get("metadata") if isinstance(body.get("metadata"), dict) else {},
                ensure_ascii=False,
            ),
            account.get("account_id", "unknown"),
        ),
    )
    return {
        "rule_set_version_id": rule_set_version_id,
        "version_number": version_number,
        "status": "draft",
    }


@router.post('/rule-set-versions/{rule_set_version_id}/publish')
async def publish_rule_set_version(request: Request, rule_set_version_id: str):
    _require_admin(request)
    conn = request.app.state.db
    from .rules.authoritative_coc7 import (
        OFFICIAL_RULEBOOK_FILENAME,
        OFFICIAL_RULEBOOK_SHA256,
    )
    version = conn.execute(
        "SELECT rsv.rule_set_id, rs.system, rs.is_base, rsv.source_sha256, "
        "rsv.metadata @> '{\"local_test_only\": true}'::jsonb AS is_local_test_only, "
        "sd.source_document_id AS official_source_document_id, sd.source_filename, "
        "sd.source_sha256 AS official_source_sha256, gate.status AS gate_status "
        "FROM rule_set_versions rsv "
        "JOIN rule_sets rs ON rs.rule_set_id = rsv.rule_set_id "
        "LEFT JOIN source_documents sd "
        "ON sd.source_document_id = rsv.metadata ->> 'official_source_document_id' "
        "LEFT JOIN rule_version_publication_gates gate "
        "ON gate.rule_set_version_id = rsv.rule_set_version_id "
        "WHERE rsv.rule_set_version_id = %s",
        (rule_set_version_id,),
    ).fetchone()
    if not version:
        raise HTTPException(404, "规则版本不存在")
    if version.get("is_local_test_only") is True:
        raise HTTPException(409, detail={"code": "rule_version_retired"})
    claimed_official = str(version.get("source_sha256") or "").upper() == OFFICIAL_RULEBOOK_SHA256
    if claimed_official:
        linked_source_is_official = (
            bool(version.get("official_source_document_id"))
            and version.get("source_filename") == OFFICIAL_RULEBOOK_FILENAME
            and str(version.get("official_source_sha256") or "").upper() == OFFICIAL_RULEBOOK_SHA256
        )
        if not linked_source_is_official or version.get("gate_status") != "ready":
            raise HTTPException(409, detail={"code": "rule_version_gate_not_ready"})
        from .rules.authoritative_coc7 import _official_page_coverage

        coverage = _official_page_coverage(conn, version["official_source_document_id"])
        if not coverage["complete"] or not coverage["valid_statuses"] or coverage["needs_review"]:
            raise HTTPException(409, detail={"code": "rule_version_gate_not_ready"})
    with conn.transaction() as tx:
        if not claimed_official:
            tx.execute(
                """
                INSERT INTO rule_version_publication_gates (
                    rule_set_version_id, status, diagnostics
                ) VALUES (%s, 'ready', '{}'::jsonb)
                ON CONFLICT (rule_set_version_id)
                DO UPDATE SET status = 'ready', updated_at = NOW()
                """,
                (rule_set_version_id,),
            )
        tx.execute(
            "UPDATE rule_set_versions SET status = 'superseded', runtime_eligible = FALSE "
            "WHERE rule_set_id = %s AND status = 'published' "
            "AND rule_set_version_id <> %s",
            (version["rule_set_id"], rule_set_version_id),
        )
        tx.execute(
            "UPDATE rule_set_versions SET status = 'published', runtime_eligible = TRUE, published_at = NOW() "
            "WHERE rule_set_version_id = %s",
            (rule_set_version_id,),
        )
        tx.execute(
            "UPDATE rule_sets SET status = 'published' WHERE rule_set_id = %s",
            (version["rule_set_id"],),
        )
        if version.get("system") == "coc7" and version.get("is_base"):
            tx.execute(
                """
                INSERT INTO scenario_rule_bindings (
                    scenario_version_id, rule_set_version_id, priority
                )
                SELECT s.published_version_id, %s, 100
                FROM scenarios s
                JOIN scenario_versions sv
                  ON sv.scenario_version_id = s.published_version_id
                WHERE s.publish_status = 'published'
                  AND s.published_version_id IS NOT NULL
                  AND sv.status = 'published'
                ON CONFLICT (scenario_version_id, rule_set_version_id) DO NOTHING
                """,
                (rule_set_version_id,),
            )
    return {"rule_set_version_id": rule_set_version_id, "status": "published"}


@router.post('/coc7/import-authoritative')
async def import_authoritative_coc7_rules(request: Request):
    account = _require_admin(request)
    rag = request.app.state.rag
    if not rag:
        raise HTTPException(503, "RAG not available")
    from .rules.authoritative_coc7 import import_authoritative_coc7

    try:
        return import_authoritative_coc7(
            request.app.state.db,
            rag,
            str(account.get("account_id") or "unknown"),
        )
    except ValueError as exc:
        raise HTTPException(409, detail={"code": "authoritative_import_failed", "reason": str(exc)}) from exc


@router.post('/retire-local-test-rules')
async def retire_local_test_rules(request: Request, body: dict):
    """Explicitly quarantine the legacy local-test corpus and dependent rooms."""
    _require_admin(request)
    if body.get("confirm") is not True:
        raise HTTPException(
            400,
            detail={"code": "retire_local_test_rules_confirmation_required"},
        )
    from .rule_source_lifecycle import retire_local_test_rule_versions

    result = retire_local_test_rule_versions(request.app.state.db)
    return {"code": "local_test_rule_versions_retired", **result}


@router.get('/rule-set-versions/{rule_set_version_id}/audit')
async def get_authoritative_rule_audit(request: Request, rule_set_version_id: str):
    _require_admin(request)
    from .rules.authoritative_coc7 import (
        AuthoritativeRulebookError,
        get_rule_version_audit,
    )

    try:
        return get_rule_version_audit(request.app.state.db, rule_set_version_id)
    except AuthoritativeRulebookError as exc:
        raise HTTPException(404, detail={"code": "authoritative_rule_version_not_found"}) from exc


@router.post('/rule-set-versions/{rule_set_version_id}/audit/approve')
async def approve_authoritative_rule_audit(request: Request, rule_set_version_id: str):
    account = _require_admin(request)
    from .rules.authoritative_coc7 import (
        AuthoritativeRulebookError,
        approve_rule_source_review,
    )

    try:
        return approve_rule_source_review(
            request.app.state.db,
            rule_set_version_id,
            str(account.get("account_id") or "unknown"),
        )
    except AuthoritativeRulebookError as exc:
        raise HTTPException(
            409,
            detail={"code": "rule_version_gate_not_ready", "reason": str(exc)},
        ) from exc


@router.post('/rule-bindings/rooms/{room_id}')
async def bind_room_rule_version(request: Request, room_id: str, body: dict):
    _require_auth_for_room(request, room_id, write=True)
    from .ai.ai_config import get_room_ai_config

    room_ai_config = get_room_ai_config(request.app.state.db, room_id) or {}
    runtime_binding = room_ai_config.get("runtime_binding")
    if isinstance(runtime_binding, dict) and runtime_binding.get("locked") is True:
        raise HTTPException(409, "房间规则运行版本已固定，不能静默切换")
    rule_set_version_id = str(body.get("rule_set_version_id") or "").strip()
    from .rule_source_lifecycle import is_runtime_qualified_rule_version

    version = request.app.state.db.execute(
        "SELECT rule_set_version_id FROM rule_set_versions WHERE rule_set_version_id = %s",
        (rule_set_version_id,),
    ).fetchone()
    if not version:
        raise HTTPException(404, "规则版本不存在")
    if not is_runtime_qualified_rule_version(
        request.app.state.db, rule_set_version_id
    ):
        raise HTTPException(409, "只能绑定合格且已发布的规则版本")
    priority = max(0, min(int(body.get("priority", 200)), 1000))
    request.app.state.db.execute(
        """
        INSERT INTO room_rule_bindings (room_id, rule_set_version_id, priority)
        VALUES (%s, %s, %s)
        ON CONFLICT (room_id, rule_set_version_id)
        DO UPDATE SET priority = EXCLUDED.priority
        """,
        (room_id, rule_set_version_id, priority),
    )
    return {
        "room_id": room_id,
        "rule_set_version_id": rule_set_version_id,
        "priority": priority,
    }


@router.post('/rule-bindings/scenarios/{scenario_version_id}')
async def bind_scenario_rule_version(
    request: Request, scenario_version_id: str, body: dict
):
    _require_admin(request)
    conn = request.app.state.db
    scenario_version = conn.execute(
        "SELECT scenario_version_id FROM scenario_versions WHERE scenario_version_id = %s",
        (scenario_version_id,),
    ).fetchone()
    if not scenario_version:
        raise HTTPException(404, "剧本版本不存在")
    rule_set_version_id = str(body.get("rule_set_version_id") or "").strip()
    from .rule_source_lifecycle import is_runtime_qualified_rule_version

    rule_version = conn.execute(
        "SELECT rule_set_version_id FROM rule_set_versions WHERE rule_set_version_id = %s",
        (rule_set_version_id,),
    ).fetchone()
    if not rule_version:
        raise HTTPException(404, "规则版本不存在")
    if not is_runtime_qualified_rule_version(conn, rule_set_version_id):
        raise HTTPException(409, "只能绑定合格且已发布的规则版本")
    priority = max(0, min(int(body.get("priority", 100)), 1000))
    conn.execute(
        """
        INSERT INTO scenario_rule_bindings (
            scenario_version_id, rule_set_version_id, priority
        ) VALUES (%s, %s, %s)
        ON CONFLICT (scenario_version_id, rule_set_version_id)
        DO UPDATE SET priority = EXCLUDED.priority
        """,
        (scenario_version_id, rule_set_version_id, priority),
    )
    return {
        "scenario_version_id": scenario_version_id,
        "rule_set_version_id": rule_set_version_id,
        "priority": priority,
    }


@router.post('/search')
async def search(request: Request, body: SearchRequest):
    """Search RAG — must be room player, owner, or admin."""
    from .router_auth import get_account_from_token
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "请先登录")
    if account.get("role") == "admin":
        audience = "admin"
    elif body.room_id:
        _require_auth_for_room(request, body.room_id, write=False)
        if body.scenario_version_id or body.rule_set_version_id:
            raise HTTPException(403, "仅管理员可指定检索版本")
        room = request.app.state.db.execute(
            "SELECT owner_account_id FROM rooms WHERE room_id = %s",
            (body.room_id,),
        ).fetchone()
        audience = (
            "host"
            if room and room.get("owner_account_id") == account.get("account_id")
            else "player"
        )
    else:
        raise HTTPException(403, "请提供 room_id 或使用管理员账号")
    rag = request.app.state.rag
    if not rag:
        raise HTTPException(503, 'RAG not available')
    results = rag.search(
        body.query,
        body.room_id,
        body.source_types,
        body.top_k,
        audience=audience,
        scenario_version_id=body.scenario_version_id,
        rule_set_version_id=body.rule_set_version_id,
    )
    if audience == "admin":
        return results
    return [_project_search_result(result) for result in results]


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


def _project_search_result(result: dict) -> dict:
    raw_citation = result.get("citation") if isinstance(result.get("citation"), dict) else {}
    allowed_fields = {
        "chunk_id", "source_type", "source_id", "source_part_id",
        "scenario_version_id", "rule_set_version_id", "source_ref",
        "page_number", "anchor", "start_offset", "end_offset", "excerpt",
    }
    citation = {
        key: _safe_citation_value(value)
        for key, value in raw_citation.items()
        if key in allowed_fields
    }
    citation["excerpt"] = str(citation.get("excerpt") or "")[:240]
    citation["source_ref"] = str(citation.get("source_ref") or "")[:240]
    return {
        "chunk_id": result.get("chunk_id", ""),
        "source_type": result.get("source_type", ""),
        "content": str(citation.get("excerpt") or "")[:240],
        "score": float(result.get("score") or 0),
        "citation": citation,
    }


def _safe_citation_value(value):
    if isinstance(value, dict):
        return {
            str(key)[:64]: _safe_citation_value(item)
            for key, item in list(value.items())[:32]
            if not str(key).lower().endswith("_path")
        }
    if isinstance(value, list):
        return [_safe_citation_value(item) for item in value[:32]]
    if isinstance(value, str):
        return value[:240]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:240]
