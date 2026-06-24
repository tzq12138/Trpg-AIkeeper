import json
from fastapi import APIRouter, Request, HTTPException
from .ai_kp import AIKP
from .spoiler_control import SpoilerController

router = APIRouter(prefix="/api/rooms")


def _get_ai_kp(request: Request) -> AIKP:
    from .config import Settings
    settings = Settings.from_env()
    conn = request.app.state.db
    spoiler_ctrl = SpoilerController(conn)
    rag_store = getattr(request.app.state, 'rag', None)
    return AIKP(
        api_key=settings.deepseek_api_key,
        model=settings.deepseek_model,
        spoiler_controller=spoiler_ctrl,
        rag_store=rag_store,
    )


def _get_scenario_for_room(conn, room_id: str) -> dict | None:
    room = conn.execute(
        "SELECT scenario_id FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()
    if not room or not room["scenario_id"]:
        return None
    scenario = conn.execute(
        "SELECT * FROM scenarios WHERE scenario_id = %s", (room["scenario_id"],)
    ).fetchone()
    if not scenario:
        return None
    return dict(scenario)


@router.post("/{room_id}/ai-turn")
async def trigger_ai_turn(request: Request, room_id: str):
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "Room not found")

    pipeline = getattr(request.app.state, "pipeline", None)
    if not pipeline:
        raise HTTPException(500, "Resolution pipeline unavailable")
    result = await pipeline.resolve_queued_room(room_id)
    if result["resolved"] == 0:
        raise HTTPException(400, "No pending actions to process")
    return result


@router.get("/{room_id}/ai-status")
async def get_ai_status(request: Request, room_id: str):
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "Room not found")

    ai_kp = _get_ai_kp(request)
    return {
        "room_id": room_id,
        "is_mock": ai_kp.is_mock,
        "consecutive_failures": ai_kp.get_failure_count(room_id),
        "model": ai_kp.model,
    }
