import json
import logging
import os
import sys
import asyncio
from contextlib import asynccontextmanager

from .log_config import setup_logging

# Must run BEFORE any module that emits log messages.
setup_logging(
    level_name=os.getenv("LOG_LEVEL", "INFO"),
    log_file=os.getenv("LOG_FILE", ""),
)

# Harden stdlib XML parsers against XXE / billion-laughs / entity-injection
# attacks before any module that uses XML (openpyxl, etree, etc.) is imported.
# openpyxl auto-detects defusedxml, but defuse_stdlib() also protects
# xml.sax, xml.dom.minidom, and xml.dom.pulldom across the entire process.
import defusedxml

defusedxml.defuse_stdlib()

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from .config import Settings
from .db_adapter import PgDatabase
from .ai.embedding import HybridEmbedding
from .ai.rag import RAGStore
from .engine.engine import Engine
from .ai.mechanic_compiler import MechanicCompiler
from .engine.projection import ProjectionDispatcher
from .engine.resolution_pipeline import ResolutionPipeline
from .router_rooms import router as rooms_router
from .player.router_player import router as player_router
from .player.auth import find_player_character
from .scenario.router_scenarios import router as scenarios_router
from .player.router_clues import router as clues_router
from .player.router_objectives import router as objectives_router
from .player.router_clarification import router as clarification_router
from .player.router_reconnect import router as reconnect_router
from .player.router_player_archive import router as player_archive_router
from .player.router_actions_v2 import router as player_actions_v2_router
from .player.router_action_decisions import router as player_action_decisions_router
from .player.router_collaboration_contracts import router as collaboration_contracts_router
from .player.router_player_settings import router as player_settings_router
from .player.router_action_reviews import router as player_action_reviews_router
from .player.router_action_consents import router as player_action_consents_router
from .player.router_campaign_v2 import (
    router as player_campaign_v2_router,
    host_router as campaign_host_v2_router,
    evidence_router as campaign_evidence_v2_router,
    library_router as campaign_library_v2_router,
)
from .host.router_host import router as host_router, host_ws_endpoint
from .host.router_action_reviews import router as host_action_reviews_router
from .router_ai import router as ai_router
from .rag_router import router as rag_router
from .router_auth import router as auth_router
from .router_map import router as map_router, maps_router
from .router_admin import router as admin_router
from .router_archive import router as archive_router
from .router_migration import router as migration_router
from .agent.game_agent import GameAgent
from .game_loop import GameLoop
from .redis_cache import RedisCache
from .host.ws_manager import manager as ws_manager
from .events.event_log import EventLog
from .models import EngineEvent

logger = logging.getLogger(__name__)

settings = Settings.from_env()
pg_db = PgDatabase(settings.database_url)

# ── Production safety: refuse to start with default JWT_SECRET ──
_jwt_secret = os.getenv("JWT_SECRET", "")
_dev_mode = os.getenv("AIKEEPER_DEV_MODE", "").lower() in ("1", "true", "yes")
if not _dev_mode and (not _jwt_secret or _jwt_secret == "aikeeper-change-me-in-production"):
    print("FATAL: JWT_SECRET is set to the default value (or is empty).", file=sys.stderr)
    print("       Set JWT_SECRET to a strong random value, or set AIKEEPER_DEV_MODE=1 to bypass.", file=sys.stderr)
    sys.exit(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("-" * 50)
    logger.info("AI-Keeper starting -- initialising components ...")
    logger.info("-" * 50)

    # ── 1. Database ──
    t0 = __import__("time").monotonic()
    try:
        pg_db.connect()
        pg_db.initialize()
        logger.info("Database  [OK]  pool connected, schema ensured")
    except Exception as exc:
        logger.critical("Database  [FAIL]  connection failed: %s", exc)
        raise
    conn = pg_db.get_connection()
    app.state.db = conn
    app.state.pg_db = pg_db
    from .router_auth import ensure_reserved_admin
    ensure_reserved_admin(conn)
    logger.info("Authentication [OK] reserved admin account ensured")

    # ── 2. Embedding ──
    try:
        embedding = HybridEmbedding()
        # Probe whether the local model is available without a full load
        try:
            import sentence_transformers  # noqa: F401
            emb_mode = "local (text2vec-base-chinese)"
        except ImportError:
            emb_mode = "hash fallback (sentence_transformers not installed)"
        logger.info("Embedding [OK]  %s", emb_mode)
    except Exception as exc:
        logger.warning("Embedding [WARN]  init failed (%s), using hash fallback", exc)
        embedding = HybridEmbedding()
    app.state.embedding = embedding

    # ── 3. RAG ──
    try:
        rag = RAGStore(pg_db, embedding)
        app.state.rag = rag
        logger.info("RAGStore  [OK]  ready")
    except Exception as exc:
        logger.warning("RAGStore  [WARN]  init failed: %s", exc)
        app.state.rag = None

    # ── 4. Engine ──
    try:
        app.state.engine = Engine(conn)
        logger.info("Engine    [OK]  ready")
    except Exception as exc:
        logger.critical("Engine    [FAIL]  init failed: %s", exc)
        raise

    # ── 5. MechanicCompiler ──
    compiler = MechanicCompiler(
        api_key=settings.deepseek_api_key,
        model=settings.deepseek_model,
    )
    app.state.compiler = compiler
    if settings.deepseek_api_key:
        logger.info("Compiler  [OK]  DeepSeek API configured (model=%s)", settings.deepseek_model)
    else:
        logger.info("Compiler  [WARN]  no API key — local regex fallback only")

    # ── 6. Redis cache ──
    if settings.redis_url:
        try:
            cache = RedisCache(settings.redis_url)
            app.state.cache = cache
            logger.info("Redis     [OK]  connected")
        except Exception as exc:
            logger.warning("Redis     [WARN]  unavailable (%s), cache disabled", exc)
            app.state.cache = RedisCache("")
    else:
        app.state.cache = RedisCache("")
        logger.info("Redis     [SKIP]   skipped (REDIS_URL not set)")

    # ── 7. SpoilerGuard ──
    try:
        from .engine.spoiler_guard import SpoilerGuard
        spoiler_guard = SpoilerGuard(conn)
        app.state.spoiler_guard = spoiler_guard
        logger.info("SpoilerGuard [OK]  ready")
    except Exception as exc:
        logger.warning("SpoilerGuard [WARN]  init failed (%s), spoiler checks disabled", exc)
        spoiler_guard = None
        app.state.spoiler_guard = None

    # ── 8. ResolutionPipeline ──
    try:
        dispatcher = ProjectionDispatcher(conn, cache=app.state.cache, spoiler_guard=spoiler_guard)
        app.state.pipeline = ResolutionPipeline(
            conn, compiler=compiler, dispatcher=dispatcher,
            spoiler_guard=spoiler_guard,
            gateway=None,  # set below after Gateway init
            host_connection_checker=lambda room_id: ws_manager.is_connected(room_id, "host"),
        )
        logger.info("Pipeline  [OK]  ready")
    except Exception as exc:
        logger.critical("Pipeline  [FAIL]  init failed: %s", exc)
        raise

    # ── 9. StateService ──
    try:
        from .engine.state_service import StateService
        state_service = StateService(conn, dispatcher=dispatcher)
        app.state.state_service = state_service
        app.state.pipeline.state_service = state_service
        logger.info("StateSvc  [OK]  ready")
    except Exception as exc:
        logger.warning("StateSvc  [WARN]  init failed (%s), state persistence disabled", exc)
        app.state.state_service = None

    # ── 10. Agent (optional) ──
    if settings.agent_enabled:
        try:
            app.state.agent = GameAgent(
                api_key=settings.deepseek_api_key,
                model=settings.deepseek_model,
                api_base="https://api.deepseek.com",
            )
            app.state.game_loop = GameLoop(
                conn, engine=Engine(conn), pipeline=app.state.pipeline,
            )
            logger.info("Agent     [OK]  GameAgent + GameLoop enabled")
        except Exception as exc:
            logger.warning("Agent     [WARN]  init failed (%s), agent disabled", exc)
            app.state.agent = None
            app.state.game_loop = None
    else:
        app.state.agent = None
        app.state.game_loop = None
        logger.info("Agent     [SKIP]   disabled (AGENT_ENABLED not set)")

    # ── 11. AiGateway ──
    try:
        from .ai.gateway import AiGateway
        app.state.gateway = AiGateway(settings, conn)
        logger.info("AiGateway [OK]  provider_order=%s", ",".join(app.state.gateway._provider_order))
    except Exception as exc:
        logger.warning("AiGateway [WARN]  init failed (%s), using fallback only", exc)
        app.state.gateway = None

    # Wire gateway into pipeline for spoiler retry
    if app.state.gateway and app.state.pipeline:
        app.state.pipeline.gateway = app.state.gateway

    from .turn_timeout_worker import run_turn_timeout_worker
    turn_timeout_stop = asyncio.Event()
    turn_timeout_task = asyncio.create_task(
        run_turn_timeout_worker(app, turn_timeout_stop)
    )
    app.state.turn_timeout_stop = turn_timeout_stop
    app.state.turn_timeout_task = turn_timeout_task

    elapsed = __import__("time").monotonic() - t0
    logger.info("-" * 50)
    logger.info("Startup complete (%.1fs) -- listening on :%s", elapsed, settings.port)
    logger.info("-" * 50)

    yield

    logger.info("AI-Keeper shutting down...")
    turn_timeout_stop.set()
    await turn_timeout_task
    conn.close()
    pg_db.close()
    logger.info("Shutdown complete")


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
async def health(request: Request):
    ok = {"status": "ok"}
    components = {}

    # DB
    try:
        conn = request.app.state.db
        conn.execute("SELECT 1").fetchone()
        components["db"] = "ok"
    except Exception as e:
        components["db"] = f"error:{e}"
        ok["status"] = "degraded"

    # Embedding
    emb = getattr(request.app.state, "embedding", None)
    components["embedding"] = "available" if emb else "missing"

    # RAG
    rag = getattr(request.app.state, "rag", None)
    components["rag"] = "available" if rag else "missing"

    # Compiler
    compiler = getattr(request.app.state, "compiler", None)
    if compiler:
        components["compiler"] = "deepseek" if getattr(compiler, "api_key", "") else "regex_fallback"
    else:
        components["compiler"] = "missing"

    # Cache
    cache = getattr(request.app.state, "cache", None)
    components["cache"] = "redis" if cache and getattr(cache, "available", False) else "disabled"

    # AI Gateway
    gateway = getattr(request.app.state, "gateway", None)
    if gateway:
        try:
            ai_status = await gateway.health_check()
            components["ai"] = ai_status
        except Exception as e:
            components["ai"] = {"error": str(e)}
    else:
        components["ai"] = "not_initialized"

    ok["components"] = components
    return ok


async def player_ws_endpoint(websocket: WebSocket, room_id: str, token: str, last_sequence: int = 0):
    conn = websocket.app.state.db
    char = find_player_character(conn, token)
    if not char or char["room_id"] != room_id:
        await websocket.accept()
        await websocket.close(code=4003, reason="Invalid token")
        return

    character_id = char["character_id"]
    connection_id = f"player:{character_id}"

    await ws_manager.connect(websocket, room_id, connection_id)
    current = find_player_character(conn, token)
    if (
        not current
        or current["room_id"] != room_id
        or current["character_id"] != character_id
    ):
        await ws_manager.revoke_player(room_id, character_id)
        return
    logger.info("Player %s connected to room %s", character_id, room_id)

    try:
        event_log = EventLog(conn)
        events = event_log.get_events_for_player(room_id, character_id, since_sequence=last_sequence)
        for ev in events:
            # Use standard EngineEvent format so the frontend parser sees
            # roomSequence / type / payload matching its EngineEvent interface.
            try:
                catch_up_event = EngineEvent(
                    event_id=f"catchup:{ev.sequence}",
                    room_id=room_id,
                    type=ev.event_type,
                    room_sequence=ev.sequence,
                    audience=ev.audience,
                    payload=json.loads(ev.payload) if isinstance(ev.payload, str) else (ev.payload or {}),
                )
                await websocket.send_text(catch_up_event.model_dump_json(by_alias=True))
            except Exception as catchup_err:
                err_msg = str(catchup_err) or type(catchup_err).__name__
                logger.warning("Player %s catch-up skip seq=%s type=%s: %s",
                               character_id, ev.sequence, ev.event_type, err_msg)
                # If the WS is dead, stop catch-up — can't send any more events
                if "Cannot call" in err_msg or "close message" in err_msg:
                    break
        ws_manager.update_last_sequence(room_id, connection_id, last_sequence)

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("Player %s disconnected from room %s", character_id, room_id)
    except Exception as e:
        logger.error("Player %s error: %s", character_id, e)
    finally:
        ws_manager.disconnect(room_id, connection_id, websocket=websocket)


@app.websocket("/ws")
async def ws_handler(websocket: WebSocket, room: str = "", role: str = "",
                     token: str = "", lastSequence: int = 0,
                     ownerToken: str = ""):
    if role == "host":
        await host_ws_endpoint(websocket, room, ownerToken)
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
app.include_router(player_actions_v2_router)
app.include_router(player_action_decisions_router)
app.include_router(collaboration_contracts_router)
app.include_router(player_settings_router)
app.include_router(player_action_reviews_router)
app.include_router(player_action_consents_router)
app.include_router(player_campaign_v2_router)
app.include_router(campaign_host_v2_router)
app.include_router(campaign_evidence_v2_router)
app.include_router(campaign_library_v2_router)
app.include_router(host_router)
app.include_router(host_action_reviews_router)
app.include_router(ai_router)
app.include_router(rag_router)
app.include_router(auth_router)
app.include_router(map_router)
app.include_router(maps_router)
app.include_router(admin_router)
app.include_router(archive_router)
app.include_router(migration_router)
