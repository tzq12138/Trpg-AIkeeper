import uuid
from fastapi import APIRouter, Request, HTTPException
from .models import RoomCreate

router = APIRouter(prefix="/api/rooms")


@router.post("")
async def create_room(request: Request, body: RoomCreate):
    conn = request.app.state.db
    room_id = str(uuid.uuid4())[:8]
    owner_token = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO rooms (room_id, scenario_id, owner_token, spoiler_level) VALUES (%s, %s, %s, %s)",
        (room_id, body.scenario_id, owner_token, body.spoiler_level),
    )
    conn.commit()
    return {"room_id": room_id, "owner_token": owner_token, "status": "lobby"}


@router.get("/{room_id}")
async def get_room(request: Request, room_id: str):
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "Room not found")
    return dict(room)


@router.post("/{room_id}/start")
async def start_room(request: Request, room_id: str):
    conn = request.app.state.db
    owner_token = request.headers.get("X-Owner-Token", "")
    room = conn.execute(
        "SELECT * FROM rooms WHERE room_id = %s AND owner_token = %s",
        (room_id, owner_token),
    ).fetchone()
    if not room:
        raise HTTPException(403, "Not room owner")
    conn.execute(
        "UPDATE rooms SET status = 'active', started_at = NOW() WHERE room_id = %s",
        (room_id,),
    )
    conn.commit()
    return {"status": "active"}
