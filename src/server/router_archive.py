from fastapi import APIRouter, Request, HTTPException, Query
from .event_log import EventLog
from .campaign_archive import CampaignArchive
from .models import CampaignArchiveQuery

router = APIRouter(prefix="/api/rooms")


@router.get("/{room_id}/events")
async def get_events(
    request: Request,
    room_id: str,
    since_sequence: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    conn = request.app.state.db
    event_log = EventLog(conn)
    events = event_log.get_events(room_id, since_sequence, limit)
    return {"events": [e.model_dump() for e in events]}


@router.get("/{room_id}/events/public")
async def get_public_events(
    request: Request,
    room_id: str,
    since_sequence: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    conn = request.app.state.db
    event_log = EventLog(conn)
    events = event_log.get_public_events(room_id, since_sequence, limit)
    return {"events": [e.model_dump() for e in events]}


@router.post("/{room_id}/checkpoint")
async def create_checkpoint(request: Request, room_id: str):
    conn = request.app.state.db
    event_log = EventLog(conn)
    checkpoint = event_log.create_checkpoint(room_id)
    return checkpoint.model_dump()


@router.get("/{room_id}/checkpoints")
async def list_checkpoints(request: Request, room_id: str):
    conn = request.app.state.db
    event_log = EventLog(conn)
    checkpoints = event_log.list_checkpoints(room_id)
    return {"checkpoints": [c.model_dump() for c in checkpoints]}


@router.post("/{room_id}/restore/{checkpoint_id}")
async def restore_checkpoint(request: Request, room_id: str, checkpoint_id: str):
    conn = request.app.state.db
    event_log = EventLog(conn)
    try:
        snapshot = event_log.restore_checkpoint(room_id, checkpoint_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"status": "restored", "snapshot": snapshot}


@router.get("/{room_id}/campaign")
async def get_campaign_summary(request: Request, room_id: str):
    conn = request.app.state.db
    archive = CampaignArchive(conn)
    try:
        summary = archive.get_campaign_summary(room_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return summary.model_dump()


@router.post("/{room_id}/end")
async def end_campaign(request: Request, room_id: str):
    conn = request.app.state.db
    archive = CampaignArchive(conn)
    ending = archive.generate_ending(room_id)
    return ending.model_dump()
