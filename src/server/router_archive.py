from typing import Literal

from fastapi import APIRouter, Request, HTTPException, Query
from .events.event_log import EventLog
from .campaign_archive import CampaignArchive, CampaignReadOnlyError
from .models import CampaignArchiveQuery
from .engine.host_autonomy import host_adjudication_block_detail, is_ai_only_room
from .engine.runtime_integrity import (
    CheckpointIntegrityError,
    issue_recovery_dry_run_token,
    recovery_proposal_hash,
    verify_recovery_dry_run_token,
)
from .engine.system_recovery import (
    SystemRecoveryError,
    create_system_recovery_proposal,
    dry_run_system_recovery,
    execute_system_recovery,
)
from .player.auth import find_player_character
from .rule_source_lifecycle import RuleSourceRetiredError, ensure_room_rule_source_available

router = APIRouter(prefix="/api/rooms")


# ── Auth helpers ──

def _verify_owner_or_admin(request: Request, room_id: str) -> dict:
    """Verify the room owner; admin role alone never grants private room access."""
    token = request.headers.get("X-Owner-Token", "")
    conn = request.app.state.db
    room = conn.execute(
        "SELECT * FROM rooms WHERE room_id = %s", (room_id,),
    ).fetchone()
    if not room:
        raise HTTPException(404, "房间不存在")
    room = dict(room)

    # 1. X-Owner-Token
    if token and room.get("owner_token") == token:
        _require_room_rule_source(conn, room_id)
        return room

    # 2. Account-based
    try:
        from .router_auth import get_account_from_token
        account = get_account_from_token(request)
        if account:
            if account.get("account_id") == room.get("owner_account_id"):
                _require_room_rule_source(conn, room_id)
                return room
    except HTTPException:
        raise
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "_verify_owner_or_admin: account lookup failed room=%s: %s", room_id, exc)

    raise HTTPException(403, "不是房间所有者")


def _require_room_rule_source(conn, room_id: str) -> None:
    try:
        ensure_room_rule_source_available(conn, room_id)
    except RuleSourceRetiredError as exc:
        raise HTTPException(409, detail=exc.detail) from exc


def _verify_player(request: Request, room_id: str = "") -> dict:
    token = request.headers.get("X-Room-Token", "")
    if not token:
        raise HTTPException(401, "缺少 X-Room-Token")
    conn = request.app.state.db
    try:
        char = find_player_character(conn, token)
    except RuleSourceRetiredError as exc:
        raise HTTPException(409, detail=exc.detail) from exc
    if not char or (room_id and char.get("room_id") != room_id):
        raise HTTPException(403, "令牌无效")
    return char


# ── Event endpoints ──

@router.get("/{room_id}/events")
async def get_events(
    request: Request,
    room_id: str,
    since_sequence: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    _verify_owner_or_admin(request, room_id)
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
    _verify_player(request, room_id)  # any valid player in this room can read public events
    conn = request.app.state.db
    event_log = EventLog(conn)
    events = event_log.get_public_events(room_id, since_sequence, limit)
    return {"events": [e.model_dump() for e in events]}


@router.get("/{room_id}/timeline")
async def get_timeline(
    request: Request,
    room_id: str,
    since_sequence: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    event_type: str = Query("", description="Filter by event type"),
    keyword: str = Query("", description="Search payload text"),
):
    """Host timeline with filters."""
    _verify_owner_or_admin(request, room_id)
    conn = request.app.state.db
    event_log = EventLog(conn)
    events = event_log.get_events(room_id, since_sequence, limit)
    if event_type:
        events = [e for e in events if e.event_type == event_type]
    if keyword:
        import json
        kw = keyword.lower()
        events = [e for e in events if kw in json.dumps(e.payload, ensure_ascii=False).lower()]
    return {"events": [e.model_dump() for e in events]}


@router.get("/{room_id}/timeline/{sequence}")
async def get_timeline_event(request: Request, room_id: str, sequence: int):
    """Get a single event by sequence for replay."""
    _verify_owner_or_admin(request, room_id)
    conn = request.app.state.db
    row = conn.execute(
        "SELECT sequence, room_id, event_type, audience, payload, action_id, "
        "state_version, payload_hash, issued_at "
        "FROM events WHERE room_id = %s AND sequence = %s",
        (room_id, sequence),
    ).fetchone()
    if not row:
        raise HTTPException(404, "事件不存在")
    from .events.event_log import _decode_json, _to_iso
    from .models import EventLogEntry
    entry = EventLogEntry(
        sequence=row["sequence"], room_id=row["room_id"],
        event_type=row["event_type"], audience=row["audience"],
        payload=_decode_json(row["payload"]), issued_at=_to_iso(row["issued_at"]),
        action_id=row.get("action_id"), state_version=row.get("state_version"),
        payload_hash=row.get("payload_hash") or "",
    )
    return entry.model_dump()


# ── Checkpoint endpoints ──

@router.post("/{room_id}/checkpoint")
async def create_checkpoint(request: Request, room_id: str):
    _verify_owner_or_admin(request, room_id)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    conn = request.app.state.db
    event_log = EventLog(conn)
    auto = body.get("auto", False)
    reason = body.get("reason", body.get("note", ""))
    checkpoint = event_log.create_checkpoint(room_id, auto=auto, reason=reason)
    return checkpoint.model_dump()


@router.get("/{room_id}/checkpoints")
async def list_checkpoints(request: Request, room_id: str):
    _verify_owner_or_admin(request, room_id)
    conn = request.app.state.db
    event_log = EventLog(conn)
    checkpoints = event_log.list_checkpoints(room_id)
    return {"checkpoints": [c.model_dump() for c in checkpoints]}


@router.post("/{room_id}/restore/{checkpoint_id}")
async def restore_checkpoint(request: Request, room_id: str, checkpoint_id: str):
    _verify_owner_or_admin(request, room_id)
    if is_ai_only_room(request.app.state.db, room_id):
        raise HTTPException(409, detail=host_adjudication_block_detail())
    body = await request.json()
    proposal = body.get("proposal")
    if not isinstance(proposal, dict):
        raise HTTPException(400, "恢复 checkpoint 必须提供结构化 proposal")
    if (
        proposal.get("mode") != "checkpoint_restore"
        or proposal.get("checkpointId") != checkpoint_id
    ):
        raise HTTPException(400, "恢复 proposal 与 checkpoint 不匹配")
    dry_run_token = str(body.get("dryRunToken") or body.get("dry_run_token") or "")
    if not dry_run_token:
        raise HTTPException(400, "需要先完成 dry-run")
    if body.get("confirm") is not True:
        raise HTTPException(400, "需要二次确认（发送 confirm: true）")
    reason = body.get("reason", "").strip()
    if not reason:
        raise HTTPException(400, "恢复 checkpoint 必须提供 reason")
    confirmations = body.get("confirmations")
    if not isinstance(confirmations, dict):
        raise HTTPException(400, "恢复 checkpoint 需要哈希与状态版本双确认")
    conn = request.app.state.db
    event_log = EventLog(conn)
    try:
        dry_run = event_log.dry_run_restore(room_id, checkpoint_id)
        expected_claims = {
            "roomId": room_id,
            "checkpointId": checkpoint_id,
            "checkpointHash": dry_run["checkpointHash"],
            "currentStateVersion": dry_run["currentStateVersion"],
            "proposalHash": recovery_proposal_hash(proposal, reason),
        }
        verify_recovery_dry_run_token(dry_run_token, expected_claims)
        if confirmations.get("checkpointHash") != dry_run["checkpointHash"]:
            raise CheckpointIntegrityError("checkpoint_confirmation_mismatch")
        try:
            confirmed_state_version = int(confirmations.get("currentStateVersion"))
        except (TypeError, ValueError) as exc:
            raise CheckpointIntegrityError("state_version_confirmation_mismatch") from exc
        if confirmed_state_version != dry_run["currentStateVersion"]:
            raise CheckpointIntegrityError("state_version_confirmation_mismatch")
        event_log.restore_checkpoint(
            room_id,
            checkpoint_id,
            expected_current_state_version=dry_run["currentStateVersion"],
        )
    except CheckpointIntegrityError as exc:
        from .engine.projection import ProjectionDispatcher

        room = conn.execute(
            "SELECT state_version, integrity_status, integrity_reason FROM rooms WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        if room and room.get("integrity_status") == "read_only_recovery":
            await ProjectionDispatcher(conn).emit(
                room_id,
                "s2c_runtime_integrity_changed",
                "party",
                {
                    "status": "read_only_recovery",
                    "reasonCode": room.get("integrity_reason") or exc.code,
                    "stateVersion": int(room.get("state_version") or 0),
                    "allowedOperations": ["read", "export", "recovery_check"],
                },
            )
        raise HTTPException(409, {"code": exc.code}) from exc
    except ValueError as e:
        raise HTTPException(404, str(e))

    from datetime import datetime, timezone
    actor_id = "host"
    try:
        from .router_auth import get_account_from_token
        acct = get_account_from_token(request)
        if acct:
            actor_id = acct.get("account_id", "host")
    except Exception:
        pass
    event_log.log_event(room_id, "s2c_checkpoint_restored", "host", {
        "checkpointId": checkpoint_id,
        "actorAccountId": actor_id,
        "reason": reason,
        "restoreMode": "verified_checkpoint",
        "proposalHash": recovery_proposal_hash(proposal, reason),
        "snapshotSha256": dry_run["checkpointHash"],
        "previousStateVersion": dry_run["currentStateVersion"],
        "createdAt": datetime.now(timezone.utc).isoformat(),
    })
    restored_room = conn.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    from .engine.projection import ProjectionDispatcher

    await ProjectionDispatcher(conn).emit(
        room_id,
        "s2c_runtime_integrity_changed",
        "party",
        {
            "status": "healthy",
            "checkpointId": checkpoint_id,
            "stateVersion": int(restored_room.get("state_version") or 0),
            "allowedOperations": ["read", "export", "action"],
        },
    )
    return {
        "status": "restored",
        "checkpointId": checkpoint_id,
        "snapshotSha256": dry_run["checkpointHash"],
        "stateVersion": int(restored_room.get("state_version") or 0),
    }


@router.post("/{room_id}/restore/{checkpoint_id}/dry-run")
async def dry_run_restore_checkpoint(
    request: Request,
    room_id: str,
    checkpoint_id: str,
):
    _verify_owner_or_admin(request, room_id)
    body = await request.json()
    proposal = body.get("proposal")
    reason = str(body.get("reason") or "").strip()
    if not isinstance(proposal, dict):
        raise HTTPException(400, "恢复 checkpoint 必须提供结构化 proposal")
    if (
        proposal.get("mode") != "checkpoint_restore"
        or proposal.get("checkpointId") != checkpoint_id
    ):
        raise HTTPException(400, "恢复 proposal 与 checkpoint 不匹配")
    if not reason:
        raise HTTPException(400, "恢复 checkpoint 必须提供 reason")
    event_log = EventLog(request.app.state.db)
    try:
        result = event_log.dry_run_restore(room_id, checkpoint_id)
    except CheckpointIntegrityError as exc:
        raise HTTPException(409, {"code": exc.code}) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    claims = {
        "roomId": room_id,
        "checkpointId": checkpoint_id,
        "checkpointHash": result["checkpointHash"],
        "currentStateVersion": result["currentStateVersion"],
        "proposalHash": recovery_proposal_hash(proposal, reason),
    }
    return {**result, "dryRunToken": issue_recovery_dry_run_token(claims)}


# ── AI-only system recovery ──

def _require_ai_only_system_recovery(conn, room_id: str) -> None:
    if not is_ai_only_room(conn, room_id):
        raise HTTPException(409, detail={"code": "ai_only_recovery_required"})


@router.post("/{room_id}/recovery/proposals", status_code=201)
async def create_ai_only_recovery_proposal(request: Request, room_id: str):
    """Generate a recovery proposal from the newest verified checkpoint.

    The caller cannot nominate a checkpoint or submit a replacement proposal:
    recovery provenance remains entirely system-generated for AI-only rooms.
    """
    _verify_owner_or_admin(request, room_id)
    conn = request.app.state.db
    _require_ai_only_system_recovery(conn, room_id)
    try:
        proposal = create_system_recovery_proposal(conn, room_id)
    except SystemRecoveryError as exc:
        raise HTTPException(409, detail={"code": exc.code}) from exc
    return {"status": "proposed", "proposal": proposal}


@router.post("/{room_id}/recovery/proposals/{proposal_id}/dry-run")
async def dry_run_ai_only_recovery_proposal(
    request: Request,
    room_id: str,
    proposal_id: str,
):
    _verify_owner_or_admin(request, room_id)
    conn = request.app.state.db
    _require_ai_only_system_recovery(conn, room_id)
    try:
        return dry_run_system_recovery(conn, room_id, proposal_id)
    except SystemRecoveryError as exc:
        raise HTTPException(409, detail={"code": exc.code}) from exc


@router.post("/{room_id}/recovery/proposals/{proposal_id}/execute")
async def execute_ai_only_recovery_proposal(
    request: Request,
    room_id: str,
    proposal_id: str,
):
    _verify_owner_or_admin(request, room_id)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    if body.get("confirm") is not True:
        raise HTTPException(400, detail={"code": "recovery_confirmation_required"})
    conn = request.app.state.db
    _require_ai_only_system_recovery(conn, room_id)
    try:
        return execute_system_recovery(conn, room_id, proposal_id)
    except SystemRecoveryError as exc:
        raise HTTPException(409, detail={"code": exc.code}) from exc


# ── Campaign endpoints ──

@router.get("/{room_id}/campaign")
async def get_campaign_summary(request: Request, room_id: str,
                                scope: Literal["public", "full"] = Query("public")):
    """Get campaign summary. scope=public for players, scope=full for owner/admin."""
    conn = request.app.state.db
    character_id = None
    if scope == "full":
        _verify_owner_or_admin(request, room_id)
    else:
        character_id = _verify_player(request, room_id)["character_id"]
    archive = CampaignArchive(conn)
    try:
        summary = archive.get_campaign_summary(
            room_id,
            character_id=character_id,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    return summary.model_dump() if hasattr(summary, 'model_dump') else summary


@router.post("/{room_id}/end")
async def end_campaign(request: Request, room_id: str):
    room = _verify_owner_or_admin(request, room_id)
    conn = request.app.state.db
    if is_ai_only_room(conn, room_id):
        actor_id = str(room.get("owner_account_id") or "owner")
        try:
            from .router_auth import get_account_from_token

            account = get_account_from_token(request)
            if account:
                actor_id = str(account.get("account_id") or actor_id)
        except Exception:
            pass
        archive = CampaignArchive(conn)
        try:
            finalized = archive.terminate_by_owner(room_id, actor_id=actor_id)
        except CampaignReadOnlyError as exc:
            raise HTTPException(409, detail={"code": str(exc)}) from exc
        return {
            "status": "ended",
            "ending_type": "aborted",
            "ending_status": "aborted",
            "ending_id": None,
            "termination_reason": "owner_terminated",
            "state_version": finalized.state_version,
        }

    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}

    ending_type = body.get("ending_type") or "mixed"
    ending_name = body.get("ending_name") or ""
    text = body.get("text") or body.get("summary") or ""
    payload = {"ending_type": ending_type}
    if ending_name:
        payload["endingName"] = ending_name
        payload["endingPhase"] = ending_name
    if text:
        payload["text"] = text

    archive = CampaignArchive(conn)
    try:
        ending = archive.generate_ending(
            room_id,
            ending_event_payload=payload,
        )
    except CampaignReadOnlyError as exc:
        raise HTTPException(409, detail={"code": str(exc)}) from exc
    return ending.model_dump()


# ── Export endpoints ──

@router.get("/{room_id}/export")
async def export_room(request: Request, room_id: str,
                      format: Literal["markdown", "json"] = Query("markdown"),
                      scope: Literal["public", "full"] = Query("public")):
    """Export room data as Markdown or JSON."""
    if scope == "full":
        _verify_owner_or_admin(request, room_id)
    else:
        _verify_player(request, room_id)
    conn = request.app.state.db
    from .export import export_markdown, export_json
    if format == "json":
        return export_json(conn, room_id, scope)
    return export_markdown(conn, room_id, scope)
