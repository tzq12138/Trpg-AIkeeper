import uuid
import json
import logging
import secrets
from typing import Literal

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from .models import RoomCreate
from .turn_manager import TurnManager
from .engine.host_autonomy import host_adjudication_block_detail, is_ai_only_room

router = APIRouter(prefix="/api/rooms")
logger = logging.getLogger(__name__)


ACTION_TIMING_PRESETS = {
    "fast": {
        "input_hint_seconds": 30,
        "receipt_seconds": 3,
        "preview_seconds": 15,
        "resolution_seconds": 90,
    },
    "standard": {
        "input_hint_seconds": 60,
        "receipt_seconds": 5,
        "preview_seconds": 30,
        "resolution_seconds": 180,
    },
    "slow": {
        "input_hint_seconds": 120,
        "receipt_seconds": 10,
        "preview_seconds": 60,
        "resolution_seconds": 300,
    },
}

_AI_ONLY_SESSION_ZERO_STEPS = (
    "character_rules",
    "safety",
    "ai_host",
    "private_data",
    "connection",
)


def _ai_only_session_zero_blockers(conn, room: dict, chars: list[dict]) -> list[dict]:
    """Compute existing server-verifiable Session Zero requirements per player."""
    if not chars:
        return [{"scope": "room", "missing": ["players"]}]
    rows = conn.execute(
        "SELECT character_id, step, contract_version, contract_hash "
        "FROM session_zero_confirmations WHERE room_id = %s",
        (room["room_id"],),
    ).fetchall()
    confirmations: dict[str, dict[str, dict]] = {}
    for row in rows:
        confirmations.setdefault(str(row["character_id"]), {})[str(row["step"])] = dict(row)

    blockers: list[dict] = []
    for char in chars:
        character_id = str(char["character_id"])
        by_step = confirmations.get(character_id, {})
        missing = [step for step in _AI_ONLY_SESSION_ZERO_STEPS if step not in by_step]
        safety = by_step.get("safety")
        if room.get("risk_contract_hash") and (
            not safety
            or safety.get("contract_version") != room.get("risk_contract_version")
            or safety.get("contract_hash") != room.get("risk_contract_hash")
        ):
            if "risk_contract" not in missing:
                missing.append("risk_contract")
        if not char.get("is_ready"):
            missing.append("ready")
        if not missing:
            # Every confirmation button and ready flag is satisfied: engine
            # probes must still be valid (AIO-SZ-004/007). Invalid probes are
            # recomputed on every gate call (AIO-SZ-008).
            from .engine.session_zero_probes import required_probes_valid

            _, missing_probes = required_probes_valid(conn, room["room_id"], character_id)
            if missing_probes:
                missing.extend(f"probe_{probe_type}" for probe_type in missing_probes)
        if missing:
            blockers.append({"character_id": character_id, "missing": sorted(missing)})
    return blockers


def _latest_ready_runtime_package_id(conn, scenario_version_id: str) -> str | None:
    row = conn.execute(
        "SELECT runtime_package_version_id FROM runtime_package_versions "
        "WHERE scenario_version_id = %s AND gate_status = 'ready' "
        "ORDER BY package_version_number DESC LIMIT 1",
        (scenario_version_id,),
    ).fetchone()
    return str(row["runtime_package_version_id"]) if row else None


def _runtime_risk_contract(conn, scenario_version_id: str, package_id: str | None):
    from .engine.risk_contract import runtime_package_risk_contract

    contract = runtime_package_risk_contract(conn, package_id, scenario_version_id)
    return (
        contract,
        contract.get("schema_version") if contract else None,
        contract.get("contract_hash") if contract else None,
    )


def _initialize_runtime_scene_state(
    conn,
    room_id: str,
    scenario_version_id: str | None,
    runtime_package_version_id: str | None,
) -> None:
    if not scenario_version_id:
        return
    existing = conn.execute(
        "SELECT current_scene FROM room_scene_state WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    if existing and str(existing.get("current_scene") or ""):
        return
    if runtime_package_version_id:
        package_row = conn.execute(
            "SELECT runtime_package FROM runtime_package_versions "
            "WHERE runtime_package_version_id = %s AND scenario_version_id = %s "
            "AND gate_status = 'ready'",
            (runtime_package_version_id, scenario_version_id),
        ).fetchone()
    else:
        package_row = conn.execute(
            "SELECT runtime_package FROM runtime_package_versions "
            "WHERE scenario_version_id = %s AND gate_status = 'ready' "
            "ORDER BY package_version_number DESC LIMIT 1",
            (scenario_version_id,),
        ).fetchone()
    if not package_row:
        return
    runtime_package = package_row.get("runtime_package") or {}
    if isinstance(runtime_package, str):
        try:
            runtime_package = json.loads(runtime_package)
        except json.JSONDecodeError:
            return
    scenes = runtime_package.get("semantic_scenes") if isinstance(runtime_package, dict) else []
    if not isinstance(scenes, list):
        return
    candidates = [
        scene for scene in scenes
        if isinstance(scene, dict) and str(scene.get("scene_id") or "")
    ]
    if not candidates:
        return
    first_scene = min(
        candidates,
        key=lambda scene: (int(scene.get("order") or 0), str(scene["scene_id"])),
    )
    scene_id = str(first_scene["scene_id"])
    conn.execute(
        "INSERT INTO room_scene_state (room_id, current_scene, visited_scenes, scene_variables, version) "
        "VALUES (%s, %s, %s, %s, 1) "
        "ON CONFLICT (room_id) DO UPDATE SET current_scene = EXCLUDED.current_scene, "
        "visited_scenes = EXCLUDED.visited_scenes, version = room_scene_state.version + 1 "
        "WHERE room_scene_state.current_scene = ''",
        (room_id, scene_id, json.dumps([scene_id]), json.dumps({})),
    )
    conn.commit()


class ActionTimingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_hint_seconds: StrictInt = Field(ge=1, le=3600)
    receipt_seconds: StrictInt = Field(ge=1, le=3600)
    preview_seconds: StrictInt = Field(ge=1, le=3600)
    resolution_seconds: StrictInt = Field(ge=1, le=3600)


class RoomActionSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: Literal["fast", "standard", "slow", "custom"] | None = None
    timing: ActionTimingUpdate | None = None
    draft_analysis_enabled: StrictBool | None = None
    speech_routing: Literal["party_message", "npc_dialogue"] | None = None
    host_autonomy_policy: Literal["host_required", "conservative", "delegated"] | None = None

    @model_validator(mode="after")
    def validate_update(self):
        if not self.model_fields_set:
            raise ValueError("At least one action setting is required")
        if (
            "draft_analysis_enabled" in self.model_fields_set
            and self.draft_analysis_enabled is None
        ):
            raise ValueError("draft_analysis_enabled must be a boolean")
        if "speech_routing" in self.model_fields_set and self.speech_routing is None:
            raise ValueError("speech_routing must be party_message or npc_dialogue")
        if "host_autonomy_policy" in self.model_fields_set and self.host_autonomy_policy is None:
            raise ValueError("host_autonomy_policy must be host_required, conservative or delegated")
        if self.preset == "custom" and self.timing is None:
            raise ValueError("custom preset requires timing")
        if self.timing is not None and self.preset != "custom":
            raise ValueError("timing is only allowed for custom preset")
        return self


@router.post("")
async def create_room(request: Request):
    """Host or admin: create a room with scenario. Host creates for self; admin may specify owner."""
    conn = request.app.state.db
    from .router_auth import get_account_from_token
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "请先登录")
    role = account.get("role", "")
    if role not in ("admin", "host"):
        raise HTTPException(403, "仅房主或管理员可创建房间")

    body = await request.json()
    scenario_id = body.get("scenario_id", "")
    if not scenario_id:
        raise HTTPException(400, "请选择剧本")
    sc = conn.execute(
        "SELECT scenario_id, title, publish_status, published_version_id "
        "FROM scenarios WHERE scenario_id = %s",
        (scenario_id,),
    ).fetchone()
    if not sc:
        raise HTTPException(404, "剧本不存在")
    scenario_version_id = sc.get("published_version_id")
    if sc.get("publish_status") != "published" or not scenario_version_id:
        raise HTTPException(409, "剧本尚未确认发布，不能开房")
    from .rule_source_lifecycle import current_authoritative_base_version
    authoritative_base_version = current_authoritative_base_version(conn)
    if authoritative_base_version is None:
        has_coc7_base = conn.execute(
            "SELECT 1 FROM rule_sets WHERE system = 'coc7' AND is_base = TRUE LIMIT 1"
        ).fetchone()
        if has_coc7_base:
            raise HTTPException(409, detail={"code": "rule_source_unavailable"})
    runtime_package_version_id = _latest_ready_runtime_package_id(
        conn,
        scenario_version_id,
    )
    from .engine.runtime_governance import runtime_package_session_mode
    session_mode = runtime_package_session_mode(conn, runtime_package_version_id)
    risk_contract, risk_contract_version, risk_contract_hash = _runtime_risk_contract(
        conn,
        scenario_version_id,
        runtime_package_version_id,
    )

    # Admin may specify owner; host always creates for self
    if role == "host":
        owner_account_id = account["account_id"]
    else:
        owner_account_id = body.get("owner_account_id") or account["account_id"]

    room_id = str(uuid.uuid4())[:8]
    owner_token = str(uuid.uuid4())
    stage_token = secrets.token_urlsafe(32)
    from .ai.ai_config import pin_room_ai_runtime
    with conn.transaction() as tx:
        tx.execute(
            "INSERT INTO rooms (room_id, scenario_id, scenario_version_id, runtime_package_version_id, session_mode, "
            "owner_token, stage_token, owner_account_id, spoiler_level, risk_contract, "
            "risk_contract_version, risk_contract_hash) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                room_id, scenario_id, scenario_version_id, runtime_package_version_id, session_mode, owner_token, stage_token,
                owner_account_id, body.get("spoiler_level", "standard"),
                json.dumps(risk_contract, ensure_ascii=False) if risk_contract else None,
                risk_contract_version, risk_contract_hash,
            ),
        )
        if authoritative_base_version:
            tx.execute(
                "INSERT INTO room_rule_bindings (room_id, rule_set_version_id, priority) "
                "VALUES (%s, %s, %s)",
                (room_id, authoritative_base_version, 0),
            )
        pin_room_ai_runtime(
            tx,
            room_id,
            scenario_version_id=scenario_version_id,
            runtime_package_version_id=runtime_package_version_id,
        )
    return {
        "room_id": room_id, "owner_token": owner_token, "stage_token": stage_token,
        "status": "lobby", "scenario_title": sc["title"],
        "scenario_id": scenario_id, "scenario_version_id": scenario_version_id,
        "runtime_package_version_id": runtime_package_version_id,
        "session_mode": session_mode,
        "risk_contract_version": risk_contract_version,
        "risk_contract_hash": risk_contract_hash,
        "owner_account_id": owner_account_id,
    }


@router.get("/mine")
async def list_my_rooms(request: Request):
    """List rooms owned by the authenticated host or admin account."""
    from .router_auth import get_account_from_token
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "请先登录")
    role = account.get("role", "")
    if role not in ("admin", "host"):
        raise HTTPException(403, "仅房主或管理员可查看")
    conn = request.app.state.db
    if role == "admin":
        rows = conn.execute("SELECT * FROM rooms ORDER BY created_at DESC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM rooms WHERE owner_account_id = %s ORDER BY created_at DESC",
            (account["account_id"],),
        ).fetchall()
    return [{
        "room_id": r["room_id"], "scenario_id": r.get("scenario_id", ""),
        "status": r["status"], "spoiler_level": r.get("spoiler_level", "standard"),
        "owner_account_id": r.get("owner_account_id", ""),
        "created_at": str(r.get("created_at", "")),
        "started_at": str(r.get("started_at", "")) if r.get("started_at") else None,
    } for r in rows]


@router.patch("/{room_id}/action-settings")
async def update_room_action_settings(
    request: Request,
    room_id: str,
    body: RoomActionSettingsUpdate,
):
    conn = request.app.state.db
    _verify_owner_or_admin(request, room_id, conn)
    room = conn.execute(
        "SELECT action_pacing_preset, action_timing, draft_analysis_enabled, speech_routing, host_autonomy_policy "
        "FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    if not room:
        raise HTTPException(404, "Room not found")

    preset = body.preset or room["action_pacing_preset"]
    if body.preset == "custom":
        timing = body.timing.model_dump()
    elif body.preset:
        timing = ACTION_TIMING_PRESETS[body.preset]
    else:
        timing = room["action_timing"]
    draft_analysis_enabled = (
        body.draft_analysis_enabled
        if "draft_analysis_enabled" in body.model_fields_set
        else bool(room["draft_analysis_enabled"])
    )
    speech_routing = (
        body.speech_routing
        if "speech_routing" in body.model_fields_set
        else str(room.get("speech_routing") or "party_message")
    )
    host_autonomy_policy = (
        body.host_autonomy_policy
        if "host_autonomy_policy" in body.model_fields_set
        else str(room.get("host_autonomy_policy") or "host_required")
    )

    conn.execute(
        "UPDATE rooms SET action_pacing_preset = %s, action_timing = %s, "
        "draft_analysis_enabled = %s, speech_routing = %s, host_autonomy_policy = %s WHERE room_id = %s",
        (
            preset,
            json.dumps(timing),
            draft_analysis_enabled,
            speech_routing,
            host_autonomy_policy,
            room_id,
        ),
    )
    conn.commit()
    return {
        "room_id": room_id,
        "preset": preset,
        "timing": timing,
        "draft_analysis_enabled": draft_analysis_enabled,
        "speech_routing": speech_routing,
        "host_autonomy_policy": host_autonomy_policy,
    }


@router.get("/{room_id}")
async def get_room(request: Request, room_id: str):
    """Public room info — never leaks owner_token or owner_account_id."""
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "Room not found")
    _require_room_rule_source(conn, room_id)
    scenario_title = ""
    player_count = 0
    if room.get("scenario_id"):
        sc = conn.execute(
            "SELECT title FROM scenarios WHERE scenario_id = %s", (room["scenario_id"],)
        ).fetchone()
        if sc:
            scenario_title = sc["title"]
    chars = conn.execute(
        """SELECT character_id, player_name, xlsx_data, status, is_ready
           FROM characters WHERE room_id = %s AND status != 'left'""",
        (room_id,),
    ).fetchall()
    player_count = len(chars)

    import json as _json_mod
    players = []
    for c in chars:
        xlsx_data = {}
        raw = c.get("xlsx_data")
        if raw:
            try:
                xlsx_data = raw if isinstance(raw, dict) else _json_mod.loads(raw)
            except Exception:
                pass
        players.append({
            "character_id": c["character_id"],
            "player_name": c["player_name"],
            "investigator_name": xlsx_data.get("name", "") if isinstance(xlsx_data, dict) else "",
            "status": c.get("status", "joined"),
            "is_ready": bool(c.get("is_ready")),
        })

    from .engine.risk_contract import public_risk_contract

    return {
        "room_id": room["room_id"],
        "status": room["status"],
        # R7: runtime status + integrity reason are party-safe machine codes
        # (paused_system/recovering/ended...) so the Owner console and lobby
        # can react without internal detail.
        "runtime_status": room.get("runtime_status") or room.get("status"),
        "integrity_reason": room.get("integrity_reason") or "",
        "scenario_id": room.get("scenario_id", ""),
        "scenario_title": scenario_title,
        "spoiler_level": room.get("spoiler_level", "standard"),
        "speech_routing": room.get("speech_routing", "party_message"),
        "host_autonomy_policy": room.get("host_autonomy_policy", "host_required"),
        "session_mode": room.get("session_mode") or "",
        "risk_contract": public_risk_contract(room.get("risk_contract")),
        "created_at": str(room.get("created_at", "")),
        "started_at": str(room.get("started_at", "")) if room.get("started_at") else None,
        "player_count": player_count,
        "players": players,
    }


@router.get("/{room_id}/scenario-options")
async def get_scenario_options(request: Request, room_id: str):
    """List imported scenarios that can be assigned to this room. Requires owner or admin."""
    _verify_owner_or_admin(request, room_id, request.app.state.db)
    conn = request.app.state.db
    rows = conn.execute(
        "SELECT scenario_id, title, import_status, quality_report, published_version_id "
        "FROM scenarios WHERE publish_status = 'published' "
        "AND published_version_id IS NOT NULL "
        "ORDER BY created_at DESC"
    ).fetchall()
    scenarios = []
    for r in rows:
        quality_level = "unknown"
        if r.get("quality_report"):
            qr = r["quality_report"]
            if isinstance(qr, str):
                try:
                    import json
                    qr = json.loads(qr)
                except Exception:
                    qr = {}
            quality_level = qr.get("level", "unknown")
        # Skip blocked scenarios
        if quality_level == "blocked":
            continue
        scenarios.append({
            "scenario_id": r["scenario_id"],
            "title": r["title"] or "未命名剧本",
            "import_status": r["import_status"],
            "scenario_version_id": r.get("published_version_id"),
            "quality_level": quality_level,
        })
    return {"scenarios": scenarios}


@router.patch("/{room_id}/scenario")
async def set_room_scenario(request: Request, room_id: str):
    """Assign a scenario to the room. Only allowed in draft/lobby/paused status."""
    _verify_owner_or_admin(request, room_id, request.app.state.db)
    body = await request.json()
    scenario_id = body.get("scenario_id", "")
    if not scenario_id:
        raise HTTPException(400, "scenario_id is required")
    conn = request.app.state.db
    # Verify scenario exists
    sc = conn.execute(
        "SELECT scenario_id, publish_status, published_version_id "
        "FROM scenarios WHERE scenario_id = %s",
        (scenario_id,),
    ).fetchone()
    if not sc:
        raise HTTPException(404, "Scenario not found")
    scenario_version_id = sc.get("published_version_id")
    if sc.get("publish_status") != "published" or not scenario_version_id:
        raise HTTPException(409, "剧本尚未确认发布")
    runtime_package_version_id = _latest_ready_runtime_package_id(
        conn,
        scenario_version_id,
    )
    risk_contract, risk_contract_version, risk_contract_hash = _runtime_risk_contract(
        conn,
        scenario_version_id,
        runtime_package_version_id,
    )
    # Check room status
    room = conn.execute(
        "SELECT status, session_mode_frozen_at FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    if not room:
        raise HTTPException(404, "Room not found")
    if room.get("session_mode_frozen_at"):
        raise HTTPException(409, detail={"code": "runtime_contract_frozen"})
    if room["status"] in ("active", "completed", "archived"):
        raise HTTPException(409, "Cannot change scenario in active/completed/archived room")
    from .engine.runtime_governance import runtime_package_session_mode

    session_mode = runtime_package_session_mode(conn, runtime_package_version_id)
    conn.execute(
        "UPDATE rooms SET scenario_id = %s, scenario_version_id = %s, "
        "runtime_package_version_id = %s, risk_contract = %s, "
        "risk_contract_version = %s, risk_contract_hash = %s, session_mode = %s "
        "WHERE room_id = %s",
        (
            scenario_id,
            scenario_version_id,
            runtime_package_version_id,
            json.dumps(risk_contract, ensure_ascii=False) if risk_contract else None,
            risk_contract_version,
            risk_contract_hash,
            session_mode,
            room_id,
        ),
    )
    conn.commit()
    # Return updated room with title
    return await get_room(request, room_id)


@router.patch("/{room_id}")
async def update_room(request: Request, room_id: str):
    """Admin: update room scenario, owner, status, or archive."""
    _verify_owner_or_admin(request, room_id, request.app.state.db)
    body = await request.json()
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "房间不存在")

    # Update scenario
    if "scenario_id" in body:
        if room.get("session_mode_frozen_at"):
            raise HTTPException(409, detail={"code": "runtime_contract_frozen"})
        if room["status"] in ("active",):
            raise HTTPException(409, "进行中的房间不能切换剧本，请先暂停")
        sc = conn.execute(
            "SELECT scenario_id, publish_status, published_version_id "
            "FROM scenarios WHERE scenario_id = %s",
            (body["scenario_id"],),
        ).fetchone()
        if not sc:
            raise HTTPException(404, "剧本不存在")
        if sc.get("publish_status") != "published" or not sc.get("published_version_id"):
            raise HTTPException(409, "剧本尚未确认发布")
        runtime_package_version_id = _latest_ready_runtime_package_id(
            conn,
            sc["published_version_id"],
        )
        risk_contract, risk_contract_version, risk_contract_hash = _runtime_risk_contract(
            conn,
            sc["published_version_id"],
            runtime_package_version_id,
        )
        from .engine.runtime_governance import runtime_package_session_mode

        session_mode = runtime_package_session_mode(conn, runtime_package_version_id)
        conn.execute(
            "UPDATE rooms SET scenario_id = %s, scenario_version_id = %s, "
            "runtime_package_version_id = %s, risk_contract = %s, "
            "risk_contract_version = %s, risk_contract_hash = %s, session_mode = %s "
            "WHERE room_id = %s",
            (
                body["scenario_id"],
                sc["published_version_id"],
                runtime_package_version_id,
                json.dumps(risk_contract, ensure_ascii=False) if risk_contract else None,
                risk_contract_version,
                risk_contract_hash,
                session_mode,
                room_id,
            ),
        )

    # Update owner
    if "owner_account_id" in body:
        conn.execute("UPDATE rooms SET owner_account_id = %s WHERE room_id = %s", (body["owner_account_id"], room_id))

    # Update status
    if "status" in body:
        if room.get("session_mode_frozen_at") and is_ai_only_room(conn, room_id):
            raise HTTPException(
                409,
                detail={"code": "ai_only_runtime_state_patch_forbidden"},
            )
        valid = {"draft", "lobby", "active", "paused", "completed", "archived"}
        if body["status"] not in valid:
            raise HTTPException(400, f"无效状态: {body['status']}")
        conn.execute("UPDATE rooms SET status = %s WHERE room_id = %s", (body["status"], room_id))

    conn.commit()
    return await get_room(request, room_id)


@router.patch("/{room_id}/session-mode")
async def update_room_session_mode(request: Request, room_id: str):
    """Choose a runtime-package-supported mode before authoritative play begins."""
    conn = request.app.state.db
    _verify_owner_or_admin(request, room_id, conn)
    body = await request.json()
    requested_mode = str(body.get("session_mode") or "").strip()
    if not requested_mode:
        raise HTTPException(400, detail={"code": "session_mode_required"})
    room = conn.execute(
        "SELECT room_id, status, runtime_package_version_id, session_mode_frozen_at "
        "FROM rooms WHERE room_id = %s FOR UPDATE",
        (room_id,),
    ).fetchone()
    if not room:
        raise HTTPException(404, "房间不存在")
    if room.get("session_mode_frozen_at") or room.get("status") != "lobby":
        raise HTTPException(409, detail={"code": "session_mode_frozen"})
    from .engine.runtime_governance import runtime_package_supported_session_modes

    supported_modes = runtime_package_supported_session_modes(
        conn,
        room.get("runtime_package_version_id"),
    )
    if requested_mode not in supported_modes:
        raise HTTPException(
            409,
            detail={
                "code": "session_mode_not_supported_for_runtime",
                "supported_session_modes": sorted(supported_modes),
            },
        )
    conn.execute(
        "UPDATE rooms SET session_mode = %s WHERE room_id = %s",
        (requested_mode, room_id),
    )
    conn.commit()
    return {"room_id": room_id, "session_mode": requested_mode, "frozen": False}


@router.post("/{room_id}/start")
async def start_room(request: Request, room_id: str):
    conn = request.app.state.db
    owner_token = request.headers.get("X-Owner-Token", "")

    # Allow owner_token, owner account, or admin account
    is_owner = False
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "房间不存在")
    room = dict(room)

    if owner_token and room.get("owner_token") == owner_token:
        is_owner = True

    if not is_owner:
        try:
            from .router_auth import get_account_from_token
            account = get_account_from_token(request)
            if account:
                if account.get("role") == "admin":
                    is_owner = True
                elif account.get("account_id") == room.get("owner_account_id"):
                    is_owner = True
        except Exception:
            pass

    if not is_owner:
        raise HTTPException(403, "不是房间所有者或管理员")
    _require_room_rule_source(conn, room_id)

    # Require scenario
    if not room.get("scenario_id"):
        raise HTTPException(400, "请先选择剧本再开始游戏")

    # Readiness check
    chars = conn.execute(
        "SELECT * FROM characters WHERE room_id = %s AND status IN ('active', 'joined')",
        (room_id,),
    ).fetchall()

    # Check for force_start param
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    force_start = body.get("force_start", False)

    ai_only_blockers = (
        _ai_only_session_zero_blockers(conn, room, chars)
        if is_ai_only_room(conn, room_id)
        else []
    )
    if ai_only_blockers:
        raise HTTPException(
            409,
            detail={
                "code": "AI_ONLY_SESSION_ZERO_INCOMPLETE",
                "missing": ai_only_blockers,
            },
        )
    if force_start and is_ai_only_room(conn, room_id):
        raise HTTPException(
            409,
            detail={
                "code": "AI_ONLY_FORCE_START_FORBIDDEN",
                "reason": "纯 AI 房间不得跳过 Session Zero 或就绪门禁",
            },
        )

    # ── force_start hardening ──
    # New clients MUST send reason + confirm.  Old {force_start: true} payload
    # is tolerated as transitional but logged as a warning.
    if force_start:
        if "confirm" in body or "reason" in body:
            reason = str(body.get("reason", "")).strip()
            confirm = body.get("confirm", False)
            if not reason:
                raise HTTPException(400, "force_start requires reason")
            if not confirm:
                raise HTTPException(400, "force_start requires confirm: true")
        else:
            logger.warning("Room %s force_start used without reason/confirm (legacy payload)", room_id)
            reason = "force_start (legacy — no reason provided)"

    # Must have at least one player
    if not chars:
        if force_start and is_owner:
            logger.warning("Force-starting empty room %s reason=%s", room_id, reason if force_start else "N/A")
        else:
            raise HTTPException(409, "至少需要一名玩家加入后才能开始")

    not_ready = [c for c in chars if not c["is_ready"]]
    if not_ready and not force_start:
        raise HTTPException(
            409,
            detail={
                "status": "not_ready",
                "not_ready_players": [
                    {"character_id": c["character_id"], "player_name": c["player_name"],
                     "is_ready": c["is_ready"]}
                    for c in not_ready
                ],
                "hint": "发送 force_start: true 确认强制开始",
            },
        )

    if is_ai_only_room(conn, room_id):
        from .engine.runtime_governance import (
            RoomRuntimeContractError,
            freeze_room_runtime_contract,
        )

        try:
            freeze_room_runtime_contract(
                conn,
                room_id,
                reason="session_zero_completed",
            )
        except RoomRuntimeContractError as exc:
            raise HTTPException(409, detail={"code": exc.code}) from exc
        # Freeze each player's initial absent policy as snapshot v1 in the same
        # start transaction (AIO-SZ-005). Later settings changes append higher
        # versions and never overwrite this baseline.
        frozen_rows = conn.execute(
            "SELECT settings.character_id, settings.absent_policy "
            "FROM room_player_settings AS settings WHERE settings.room_id = %s",
            (room_id,),
        ).fetchall()
        for frozen in frozen_rows:
            conn.execute(
                "INSERT INTO absent_policy_snapshots "
                "(snapshot_id, room_id, character_id, absent_policy, snapshot_version, reason) "
                "VALUES (%s, %s, %s, %s, 1, 'session_zero_freeze') "
                "ON CONFLICT (room_id, character_id, snapshot_version) DO NOTHING",
                (
                    f"snap-{room_id}-{frozen['character_id']}-1",
                    room_id,
                    frozen["character_id"],
                    frozen["absent_policy"],
                ),
            )

    conn.execute(
        "UPDATE rooms SET status = 'active', runtime_status = 'running', "
        "campaign_lifecycle_status = 'running', started_at = NOW() WHERE room_id = %s",
        (room_id,),
    )
    conn.commit()

    # Write force_start audit event if used
    if force_start:
        try:
            from .events.event_log import EventLog
            audit_reason = reason
            EventLog(conn).log_event(room_id, "s2c_force_start_audit", "system",
                                     {"reason": audit_reason, "player_count": len(chars),
                                      "not_ready_count": len(not_ready)})
        except Exception as e:
            logger.warning("Failed to log force_start audit: %s", e)

    # Initialize room map state from confirmed scenario map
    scenario_id = room.get("scenario_id")
    if scenario_id:
        try:
            from .map_persistence import (
                get_character_position,
                get_scenario_map_by_scenario,
                init_room_map_state,
                mark_node_explored,
                set_character_position,
            )
            scenario_map = get_scenario_map_by_scenario(conn, scenario_id)
            if scenario_map and scenario_map.get("status") == "confirmed":
                init_room_map_state(conn, room_id, scenario_map["map_id"])
                start_node = next(
                    (
                        node.get("node_id", node.get("nodeId", ""))
                        for node in scenario_map.get("nodes", [])
                        if node.get("is_start", node.get("isStart", False))
                    ),
                    "",
                )
                if not start_node and scenario_map.get("nodes"):
                    first_node = scenario_map["nodes"][0]
                    start_node = first_node.get("node_id", first_node.get("nodeId", ""))
                if start_node:
                    for char in chars:
                        if not get_character_position(conn, char["character_id"], room_id):
                            set_character_position(conn, char["character_id"], room_id, start_node)
                    mark_node_explored(conn, room_id, start_node)
                logger.info("Map initialized for room %s from scenario %s", room_id, scenario_id)
        except Exception as e:
            logger.warning("Failed to init map for room %s: %s", room_id, e)

    _initialize_runtime_scene_state(
        conn,
        room_id,
        room.get("scenario_version_id"),
        room.get("runtime_package_version_id"),
    )

    # Auto-checkpoint on room start
    try:
        from .events.event_log import EventLog
        EventLog(conn).create_checkpoint(room_id, auto=True, reason="Room started")
    except Exception as e:
        logger.warning("Auto-checkpoint failed: %s", e)

    # Create first turn
    tm = TurnManager(conn)
    turn = tm.ensure_current_turn(room_id)

    # Fetch scenario_title for broadcast (must query after commit)
    scenario_title = ""
    if room.get("scenario_id"):
        sc = conn.execute(
            "SELECT title FROM scenarios WHERE scenario_id = %s", (room["scenario_id"],)
        ).fetchone()
        if sc:
            scenario_title = sc["title"]

    # Broadcast active lobby snapshot so PlayerLobby auto-transitions
    try:
        from .engine.projection import ProjectionDispatcher
        import json as _json2
        dispatcher_inst = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(conn)
        snap_players = []
        for c in chars:
            inv_name = ""
            raw = c.get("xlsx_data")
            if raw:
                try:
                    xd = raw if isinstance(raw, dict) else _json2.loads(raw)
                    inv_name = xd.get("name", "") if isinstance(xd, dict) else ""
                except Exception:
                    pass
            snap_players.append({
                "character_id": c["character_id"],
                "player_name": c["player_name"],
                "investigator_name": inv_name,
                "status": c.get("status", "joined"),
                "is_ready": bool(c.get("is_ready")),
            })
        await dispatcher_inst.emit(room_id, "s2c_room_lobby_snapshot", "party", {
            "room_id": room_id,
            "room_status": "active",
            "scenario_title": scenario_title,
            "players": snap_players,
        })
    except Exception as e:
        logger.warning("Failed to broadcast active snapshot on start: %s", e)

    return {"status": "active", "turn_id": turn["turn_id"], "turn_index": turn["turn_index"]}


# ── Turn endpoints ──

@router.get("/{room_id}/turns/current")
async def get_current_turn(request: Request, room_id: str):
    conn = request.app.state.db
    _verify_owner_or_admin(request, room_id, conn)
    tm = TurnManager(conn)
    return tm.get_turn_snapshot(room_id)


@router.post("/{room_id}/turns/{turn_id}/skip-character")
async def skip_character(request: Request, room_id: str, turn_id: str):
    conn = request.app.state.db
    _verify_owner_or_admin(request, room_id, conn)
    if is_ai_only_room(conn, room_id):
        raise HTTPException(409, detail=host_adjudication_block_detail())
    body = await request.json()
    character_id = body.get("character_id", "")
    if not character_id:
        raise HTTPException(400, "character_id required")
    tm = TurnManager(conn)
    result = tm.skip_character(room_id, turn_id, character_id, body.get("policy", "idle"))
    if result.get("status") == "not_found":
        raise HTTPException(404, "Turn not found")
    if result.get("status") == "invalid_policy":
        raise HTTPException(422, "policy must be idle or maintain_existing")
    if tm.all_submitted(room_id):
        import asyncio
        from .player.router_player import _settle_turn_background
        asyncio.create_task(_settle_turn_background(request.app, room_id, turn_id))
    return result


@router.post("/{room_id}/turns/{turn_id}/retry")
async def retry_turn(request: Request, room_id: str, turn_id: str):
    conn = request.app.state.db
    _verify_owner_or_admin(request, room_id, conn)
    turn = conn.execute(
        "SELECT * FROM room_turns WHERE turn_id = %s AND room_id = %s",
        (turn_id, room_id),
    ).fetchone()
    if not turn:
        raise HTTPException(404, "Turn not found")
    import asyncio
    from .player.router_player import _settle_turn_background
    asyncio.create_task(_settle_turn_background(request.app, room_id, turn_id))
    return {"status": "retrying", "turn_id": turn_id}


def _verify_owner_or_admin(request: Request, room_id: str, conn):
    """Verify the request is from room owner (token or account) or admin account."""
    owner_token = request.headers.get("X-Owner-Token", "")
    if owner_token:
        room = conn.execute(
            "SELECT * FROM rooms WHERE room_id = %s AND owner_token = %s", (room_id, owner_token)
        ).fetchone()
        if room:
            _require_room_rule_source(conn, room_id)
            return
    try:
        from .router_auth import get_account_from_token
        account = get_account_from_token(request)
        if account:
            if account.get("role") == "admin":
                _require_room_rule_source(conn, room_id)
                return
            room = conn.execute(
                "SELECT owner_account_id FROM rooms WHERE room_id = %s", (room_id,)
            ).fetchone()
            if room and room.get("owner_account_id") == account.get("account_id"):
                _require_room_rule_source(conn, room_id)
                return
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("_verify_owner_or_admin: account lookup failed room=%s: %s", room_id, exc)
    raise HTTPException(403, "不是房间所有者或管理员")


def _require_room_rule_source(conn, room_id: str) -> None:
    from .rule_source_lifecycle import (
        RuleSourceRetiredError,
        ensure_room_rule_source_available,
    )

    try:
        ensure_room_rule_source_available(conn, room_id)
    except RuleSourceRetiredError as exc:
        raise HTTPException(409, detail=exc.detail) from exc


@router.get("/{room_id}/ai-status")
async def ai_status(request: Request, room_id: str):
    """Return AI provider status for the room."""
    conn = request.app.state.db
    _verify_owner_or_admin(request, room_id, conn)
    turn = conn.execute(
        "SELECT * FROM room_turns WHERE room_id = %s ORDER BY turn_index DESC LIMIT 1", (room_id,)
    ).fetchone()
    provider = getattr(request.app.state, "narrative_provider", None)
    provider_name = type(provider).__name__ if provider else "TemplateNarrativeProvider"
    return {
        "room_id": room_id,
        "provider": provider_name if provider else "none",
        "turn_status": dict(turn)["status"] if turn else "no_turns",
        "turn_index": dict(turn)["turn_index"] if turn else 0,
    }


# ── Room AI Config ──

@router.get("/{room_id}/ai-config")
async def get_room_ai_config(request: Request, room_id: str):
    """Get room-level AI config override."""
    _verify_owner_or_admin(request, room_id, request.app.state.db)
    from .ai.ai_config import get_room_ai_config, get_global_ai_config
    room_cfg = get_room_ai_config(request.app.state.db, room_id)
    global_cfg = get_global_ai_config(request.app.state.db)
    return {
        "room_id": room_id,
        "room_config": room_cfg,
        "global_config": global_cfg,
    }


@router.patch("/{room_id}/ai-config")
async def update_room_ai_config(request: Request, room_id: str):
    """Set room-level AI config override."""
    _verify_owner_or_admin(request, room_id, request.app.state.db)
    body = await request.json()
    from .ai.ai_config import RoomAiConfigLockedError, update_room_ai_config
    try:
        update_room_ai_config(request.app.state.db, room_id, body)
    except RoomAiConfigLockedError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "updated", "room_id": room_id}


async def _publish_committed_room_event(
    request: Request,
    room_id: str,
    sequence: int,
) -> None:
    from .engine.projection import ProjectionDispatcher

    dispatcher = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(
        request.app.state.db
    )
    try:
        await dispatcher.publish_committed_event(room_id, sequence)
    except Exception:
        logger.warning(
            "Failed to publish committed room event room=%s sequence=%s",
            room_id,
            sequence,
        )


@router.get("/{room_id}/ai-provider/status")
async def get_room_ai_provider_status(request: Request, room_id: str):
    conn = request.app.state.db
    _verify_owner_or_admin(request, room_id, conn)
    room = conn.execute(
        "SELECT integrity_status, integrity_reason FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    from .ai.provider_health import current_runtime_binding

    binding = current_runtime_binding(conn, room_id)
    health = conn.execute(
        "SELECT consecutive_failures, last_error_category "
        "FROM room_provider_health WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    return {
        "room_id": room_id,
        "status": str(room.get("integrity_status") or "healthy"),
        "reason_code": str(room.get("integrity_reason") or ""),
        "primary_provider": str(binding.get("primary_provider") or ""),
        "primary_model": str(binding.get("primary_model") or ""),
        "binding_revision": int(binding.get("binding_revision") or 1),
        "consecutive_failures": int(
            health.get("consecutive_failures") or 0 if health else 0
        ),
        "last_error_category": str(
            health.get("last_error_category") or "" if health else ""
        ),
    }


@router.get("/{room_id}/stage-access")
async def get_stage_access(request: Request, room_id: str):
    """Issue the room's separate read-only StageClient credential to its owner."""
    conn = request.app.state.db
    _verify_owner_or_admin(request, room_id, conn)
    with conn.transaction() as tx:
        room = tx.execute(
            "SELECT stage_token FROM rooms WHERE room_id = %s FOR UPDATE",
            (room_id,),
        ).fetchone()
        if not room:
            raise HTTPException(404, "Room not found")
        stage_token = str(room.get("stage_token") or "")
        if not stage_token:
            stage_token = secrets.token_urlsafe(32)
            tx.execute(
                "UPDATE rooms SET stage_token = %s WHERE room_id = %s",
                (stage_token, room_id),
            )
    return {
        "room_id": room_id,
        "stage_token": stage_token,
        "stage_url": f"/host/{room_id}/stage#stage_token={stage_token}",
    }


@router.post("/{room_id}/ai-provider/recover")
async def recover_room_ai_provider(request: Request, room_id: str):
    conn = request.app.state.db
    _verify_owner_or_admin(request, room_id, conn)
    body = await request.json()
    if body.get("confirm") is not True:
        raise HTTPException(400, "请确认后再恢复 AI provider")
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "恢复 AI provider 必须填写原因")

    from .ai.gateway import AiGateway
    from .ai.provider_health import (
        RoomProviderHealth,
        binding_id,
        current_runtime_binding,
    )
    from .router_auth import get_account_from_token

    binding = current_runtime_binding(conn, room_id)
    gateway = getattr(request.app.state, "gateway", None) or AiGateway(db_conn=conn)
    providers = gateway._get_runtime_bound_providers(binding)
    primary_name = str(binding.get("primary_provider") or "")
    configured_id = str(binding.get("configured_provider_id") or "")
    primary = next(
        (
            provider
            for provider in providers
            if (
                configured_id
                and getattr(provider, "provider_config_id", "") == configured_id
            )
            or provider.name == primary_name
        ),
        None,
    )
    if primary is None or not bool(await primary.health_check()):
        raise HTTPException(409, detail={"code": "provider_health_check_failed"})
    account = get_account_from_token(request)
    actor_id = str(account.get("account_id") if account else "room-owner")
    try:
        sequence = RoomProviderHealth(conn).recover(
            room_id,
            binding_id(binding),
            actor_id=actor_id,
        )
    except ValueError as exc:
        raise HTTPException(409, detail={"code": str(exc)}) from exc
    await _publish_committed_room_event(request, room_id, sequence)
    return {"room_id": room_id, "status": "healthy"}


@router.post("/{room_id}/ai-provider/switch")
async def switch_room_ai_provider(request: Request, room_id: str):
    conn = request.app.state.db
    _verify_owner_or_admin(request, room_id, conn)
    body = await request.json()
    if body.get("confirm") is not True:
        raise HTTPException(400, "请确认后再切换 AI provider")
    reason = str(body.get("reason") or "").strip()
    provider_config_id = str(body.get("provider_config_id") or "").strip()
    if not reason or not provider_config_id:
        raise HTTPException(400, "provider_config_id 和切换原因不能为空")

    from .ai.ai_config import switch_room_ai_runtime
    from .router_auth import get_account_from_token

    account = get_account_from_token(request)
    actor_id = str(account.get("account_id") if account else "room-owner")
    try:
        with conn.transaction() as tx:
            binding, sequence = switch_room_ai_runtime(
                tx,
                room_id,
                provider_config_id=provider_config_id,
                reason=reason,
                actor_id=actor_id,
            )
    except ValueError as exc:
        code = str(exc)
        status = 404 if code in {"room_not_found", "provider_not_found"} else 409
        raise HTTPException(status, detail={"code": code}) from exc
    await _publish_committed_room_event(request, room_id, sequence)
    return {
        "room_id": room_id,
        "status": "healthy",
        "binding_id": binding["binding_id"],
        "binding_revision": binding["binding_revision"],
    }
