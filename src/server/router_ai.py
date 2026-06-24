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

    actions = conn.execute(
        "SELECT * FROM actions WHERE room_id = %s AND status = 'queued' ORDER BY created_at",
        (room_id,),
    ).fetchall()

    if not actions:
        raise HTTPException(400, "No pending actions to process")

    action_dicts = [dict(a) for a in actions]
    batch = {
        "batch_id": f"manual-{room_id}",
        "room_id": room_id,
        "actions": action_dicts,
    }

    scenario = _get_scenario_for_room(conn, room_id)
    if not scenario:
        scenario = {"title": "默认场景", "raw_text": ""}

    ai_kp = _get_ai_kp(request)
    response = await ai_kp.process_batch(room_id, batch, scenario)

    for a in action_dicts:
        conn.execute(
            "UPDATE actions SET status = 'resolved', result = %s WHERE action_id = %s",
            (response.narrative[:200], a["action_id"]),
        )

    conn.execute(
        "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, 'host', %s)",
        (room_id, "s2c_reveal_transaction", json.dumps({
            "narrative": response.narrative,
            "batch_id": batch["batch_id"],
        })),
    )

    for roll_req in response.roll_requests:
        conn.execute(
            "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, 'player', %s)",
            (room_id, "s2c_tactical_prompt", json.dumps({
                "skill_name": roll_req.skill_name,
                "difficulty": roll_req.difficulty,
                "reason": roll_req.reason,
                "target_character": roll_req.target_character,
            })),
        )

    conn.commit()

    return {
        "batch_id": batch["batch_id"],
        "narrative": response.narrative,
        "roll_requests": [r.model_dump() for r in response.roll_requests],
        "state_suggestions": [s.model_dump() for s in response.state_suggestions],
        "tactical_prompts": [t.model_dump() for t in response.tactical_prompts],
        "clues_to_release": response.clues_to_release,
        "keeper_notes": response.keeper_notes,
    }


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
