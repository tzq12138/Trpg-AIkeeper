import json
from fastapi import APIRouter, Request, HTTPException
from .ai.ai_kp import AIKP
from .ai.spoiler_control import SpoilerController
from .router_auth import get_account_from_token

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


def _verify_room_owner_or_admin(request: Request, room_id: str) -> dict:
    """Verify the requester is room owner or admin. Returns account dict."""
    account = get_account_from_token(request)
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "房间不存在")
    room = dict(room)
    # Legacy X-Owner-Token fallback
    owner_token = request.headers.get("X-Owner-Token", "")
    if owner_token and room.get("owner_token") == owner_token:
        _require_room_rule_source(conn, room_id)
        return account or {"role": "owner", "account_id": room.get("owner_account_id")}

    if not account:
        raise HTTPException(401, "请先登录")
    if account.get("role") == "admin":
        _require_room_rule_source(conn, room_id)
        return account
    if account.get("account_id") == room.get("owner_account_id"):
        _require_room_rule_source(conn, room_id)
        return account
    raise HTTPException(403, "仅房主或管理员可执行此操作")


def _get_account_role(request: Request) -> str:
    """Get account role. Returns 'anonymous' if not logged in."""
    try:
        account = get_account_from_token(request)
        return account.get("role", "player") if account else "anonymous"
    except Exception:
        return "anonymous"


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
    """Trigger AI to process queued actions. Owner/Admin only."""
    _verify_room_owner_or_admin(request, room_id)
    conn = request.app.state.db
    pipeline = getattr(request.app.state, "pipeline", None)
    if not pipeline:
        raise HTTPException(500, "Resolution pipeline unavailable")
    result = await pipeline.resolve_queued_room(room_id)
    if result["resolved"] == 0:
        raise HTTPException(400, "No pending actions to process")
    return result


@router.get("/{room_id}/ai-status")
async def get_ai_status(request: Request, room_id: str):
    """Get AI status. Player: low-sensitivity. Owner/Admin: full diagnostics."""
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "Room not found")
    _require_room_rule_source(conn, room_id)

    ai_kp = _get_ai_kp(request)
    role = _get_account_role(request)

    if role in ("admin", "host"):
        # Full diagnostics for owner/admin
        return {
            "room_id": room_id,
            "enabled": not ai_kp.is_mock,
            "is_mock": ai_kp.is_mock,
            "consecutive_failures": ai_kp.get_failure_count(room_id),
            "model": ai_kp.model if role == "admin" else "configured",
        }
    # Player-safe: only low-sensitivity fields
    return {
        "room_id": room_id,
        "enabled": not ai_kp.is_mock,
        "is_mock": ai_kp.is_mock,
        "degraded": ai_kp.get_failure_count(room_id) >= 3,
    }


def _require_room_rule_source(conn, room_id: str) -> None:
    from .rule_source_lifecycle import (
        RuleSourceRetiredError,
        ensure_room_rule_source_available,
    )

    try:
        ensure_room_rule_source_available(conn, room_id)
    except RuleSourceRetiredError as exc:
        raise HTTPException(409, detail=exc.detail) from exc
