import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from .config import Settings
from .db_adapter import PgDatabase
from .embedding import HybridEmbedding
from .rag import RAGStore
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
    embedding = HybridEmbedding()
    rag = RAGStore(pg_db, embedding)
    app.state.rag = rag
    app.state.engine = Engine(conn)
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
