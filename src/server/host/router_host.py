import json
import logging
import uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, HTTPException
from ..models import EngineEvent, HostPublicSceneTimeUpdate, RevealTransaction
from .host_store import HostStore, HOST_VISIBLE_EVENTS, PRIVATE_EVENTS
from .public_stage import build_public_presentation_projection, build_public_stage_projection
from .ws_manager import manager as ws_manager
from ..runtime_lifecycle import lifecycle_guard

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/host")

_host_stores: dict[str, HostStore] = {}


def _verify_owner(request: Request, room_id: str) -> dict:
    """Verify room owner via X-Owner-Token or account-based auth (Bearer token).

    Priority: 1) X-Owner-Token  2) Authorization: Bearer account token
    For account auth: checks owner_account_id match or admin role.
    """
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "房间不存在")
    room = dict(room)

    # 1. X-Owner-Token (legacy)
    token = request.headers.get("X-Owner-Token", "")
    if token and room.get("owner_token") == token:
        return room

    # 2. Account-based auth
    try:
        from ..router_auth import get_account_from_token
        account = get_account_from_token(request)
        if account:
            if account.get("role") == "admin":
                logger.info("_verify_owner: admin account=%s room=%s", account.get("username"), room_id)
                return room
            if account.get("account_id") == room.get("owner_account_id"):
                logger.info("_verify_owner: owner account=%s room=%s", account.get("username"), room_id)
                return room
    except Exception as exc:
        logger.warning(
            "_verify_owner: account auth lookup failed room=%s error_type=%s",
            room_id,
            type(exc).__name__,
        )

    logger.warning("_verify_owner: denied room=%s (token=%s, account failed)", room_id, bool(token))
    raise HTTPException(403, "不是房间所有者")


def _event_safe_record(value: dict | None) -> dict:
    return {
        key: item.isoformat() if hasattr(item, "isoformat") else item
        for key, item in dict(value or {}).items()
    }


def _require_emergency_reason(body: dict, operation: str) -> str:
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, f"{operation} requires an emergency reason")
    return reason[:500]


def _audit_encounter_intervention(
    conn,
    room_id: str,
    owner_info: dict,
    *,
    operation: str,
    encounter_id: str,
    reason: str,
    target_id: str = "",
) -> None:
    from ..events.event_log import EventLog

    EventLog(conn).log_event(room_id, "host_encounter_intervention", "system", {
        "operation": operation,
        "encounterId": encounter_id,
        "reason": reason,
        "actorAccountId": owner_info.get("owner_account_id") or "host",
        "targetId": target_id,
    })


def get_host_store(room_id: str, db_conn=None) -> HostStore:
    if room_id not in _host_stores:
        store = HostStore(room_id)
        if db_conn is not None:
            store.restore_from_db(db_conn)
        _host_stores[room_id] = store
    return _host_stores[room_id]


def remove_host_store(room_id: str):
    _host_stores.pop(room_id, None)


@router.get("/{room_id}/hud")
async def get_hud(request: Request, room_id: str):
    _verify_owner(request, room_id)  # auth gate
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "Room not found")

    # Always build HUD from current DB state (never stale)
    from .hud_builder import build_hud
    hud = build_hud(conn, room_id)

    # Merge queue/engine state from HostStore if available
    store = _host_stores.get(room_id)
    if store:
        hud.queue_status = {
            "normal": len(store.normal_queue),
            "urgent": len(store.urgent_queue),
        }
        hud.engine_state = store.engine_state
        hud.scene_image_url = store.current_scene_image_url

    return hud.model_dump(by_alias=True)


@router.get("/{room_id}/stage-projection")
async def get_stage_projection(request: Request, room_id: str):
    """Return a display-safe projection without host controls or exact resources."""
    _verify_owner(request, room_id)
    conn = request.app.state.db

    from .hud_builder import build_hud
    from .public_stage import build_public_combat_round_projection
    hud = build_hud(conn, room_id)
    store = _host_stores.get(room_id)
    if store:
        hud.engine_state = store.engine_state
        hud.scene_image_url = store.current_scene_image_url

    rows = conn.execute(
        """SELECT event_type, payload, issued_at
           FROM events
           WHERE room_id = %s
             AND audience = 'party'
             AND event_type IN ('s2c_public_observation', 's2c_turn_resolved')
           ORDER BY sequence DESC
           LIMIT 5""",
        (room_id,),
    ).fetchall()
    public_events = []
    for row in reversed(rows):
        payload = row.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        text = ""
        if row.get("event_type") == "s2c_public_observation" and isinstance(payload, dict):
            text = str(payload.get("text", ""))
        elif row.get("event_type") == "s2c_turn_resolved" and isinstance(payload, dict):
            summary = payload.get("combat_summary")
            if isinstance(summary, dict):
                parts = [str(summary.get("title", ""))]
                public_facts = [str(item) for item in summary.get("public_facts", []) if item]
                parts.extend(public_facts)
                current_situation = summary.get("current_situation")
                if current_situation and str(current_situation).strip() != (public_facts[-1].strip() if public_facts else ""):
                    parts.append(str(current_situation))
                text = "\n".join(part for part in parts if part)
        public_events.append({"text": text, "issued_at": row.get("issued_at", "")})
    combat_round = build_public_combat_round_projection(
        conn,
        room_id,
        total_players=len(hud.players),
    )
    return build_public_stage_projection(hud, public_events, combat_round)


@router.put("/{room_id}/public-scene-time")
async def update_public_scene_time(
    request: Request,
    room_id: str,
    payload: HostPublicSceneTimeUpdate,
):
    """Update the one scene field that is explicitly safe for public display."""
    room = _verify_owner(request, room_id)
    conn = request.app.state.db
    scene_row = conn.execute(
        "SELECT scene_variables FROM room_scene_state WHERE room_id = %s FOR UPDATE",
        (room_id,),
    ).fetchone()
    scene_variables = scene_row.get("scene_variables") if scene_row else {}
    if isinstance(scene_variables, str):
        try:
            scene_variables = json.loads(scene_variables)
        except json.JSONDecodeError:
            scene_variables = {}
    scene_variables = dict(scene_variables or {})
    scene_variables["public_time"] = payload.scene_time

    row = conn.execute(
        """
        INSERT INTO room_scene_state (room_id, scene_variables, version)
        VALUES (%s, %s, 1)
        ON CONFLICT (room_id) DO UPDATE SET
            scene_variables = EXCLUDED.scene_variables,
            version = room_scene_state.version + 1,
            updated_at = NOW()
        RETURNING version
        """,
        (room_id, json.dumps(scene_variables, ensure_ascii=False)),
    ).fetchone()
    from ..events.event_log import EventLog
    EventLog(conn).log_event(room_id, "host_public_scene_time_updated", "system", {
        "operation": "public_scene_time_updated",
        "actorAccountId": room.get("owner_account_id", "host"),
        "sceneTime": payload.scene_time,
        "sceneVersion": row["version"],
    })
    return {"sceneTime": payload.scene_time, "version": row["version"]}


@router.get("/{room_id}/safety-requests")
async def get_safety_requests(request: Request, room_id: str):
    _verify_owner(request, room_id)

    rows = request.app.state.db.execute(
        """
        SELECT submission.action_id, submission.created_at
        FROM player_action_submissions AS submission
        WHERE submission.room_id = %s
          AND submission.input_mode = 'safety'
          AND submission.status = 'safety_paused'
        ORDER BY submission.created_at DESC
        LIMIT 20
        """,
        (room_id,),
    ).fetchall()
    return {
        "items": [{
            "actionId": row["action_id"],
            "createdAt": str(row["created_at"]),
        } for row in rows]
    }


@router.post("/{room_id}/safety/extend")
async def extend_safety_pause(request: Request, room_id: str):
    _verify_owner(request, room_id)
    conn = request.app.state.db
    active = conn.execute(
        "SELECT COUNT(*) AS count FROM player_action_submissions "
        "WHERE room_id = %s AND input_mode = 'safety' "
        "AND status = 'safety_paused'",
        (room_id,),
    ).fetchone()
    active_count = int(active["count"] or 0)
    if active_count == 0:
        raise HTTPException(409, detail={"code": "safety_pause_not_active"})
    conn.execute(
        "UPDATE player_action_submissions SET updated_at = NOW() "
        "WHERE room_id = %s AND input_mode = 'safety' "
        "AND status = 'safety_paused'",
        (room_id,),
    )
    conn.commit()
    from ..engine.projection import ProjectionDispatcher

    dispatcher = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(
        conn,
    )
    await dispatcher.emit(
        room_id,
        "s2c_safety_state_changed",
        "party",
        {
            "status": "safety_paused",
            "activePauseCount": active_count,
            "extended": True,
        },
    )
    return {"status": "safety_paused", "activePauseCount": active_count}


@router.post("/{room_id}/safety/end-session")
async def end_session_for_safety(request: Request, room_id: str):
    _verify_owner(request, room_id)
    conn = request.app.state.db
    active = conn.execute(
        "SELECT 1 FROM player_action_submissions "
        "WHERE room_id = %s AND input_mode = 'safety' "
        "AND status = 'safety_paused' LIMIT 1",
        (room_id,),
    ).fetchone()
    if not active:
        raise HTTPException(409, detail={"code": "safety_pause_not_active"})

    from ..campaign_archive import finalize_campaign
    from ..events.event_log import EventLog

    with conn.transaction() as tx:
        tx.execute(
            "UPDATE player_action_submissions SET status = 'safety_ended', "
            "updated_at = NOW() WHERE room_id = %s AND input_mode = 'safety' "
            "AND status = 'safety_paused'",
            (room_id,),
        )
        safety_payload = {
            "status": "session_ended",
            "activePauseCount": 0,
        }
        safety_event_sequence = EventLog(tx).log_event(
            room_id,
            "s2c_safety_state_changed",
            "party",
            safety_payload,
            commit=False,
        )
        ending_payload = {
            "endingType": "safe_abort",
            "completion_source": "safety_tool",
        }
        finalized = finalize_campaign(
            conn,
            room_id,
            ending_type="safe_abort",
            summary="本次冒险依据安全工具请求安全结束。",
            highlights=["队伍选择了安全结束。"],
            expected_room_statuses=("lobby", "suggested", "active", "paused"),
            ending_event_payload=ending_payload,
            transaction=tx,
        )
        if finalized is None:
            raise HTTPException(409, detail={"code": "campaign_already_completed"})

    from ..engine.projection import ProjectionDispatcher

    dispatcher = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(
        conn,
    )
    publisher = getattr(dispatcher, "publish_committed_event", None)
    if publisher:
        await publisher(room_id, safety_event_sequence)
        await publisher(room_id, finalized.ending_event_sequence)
    else:
        await dispatcher.emit(
            room_id,
            "s2c_safety_state_changed",
            "party",
            safety_payload,
        )
        await dispatcher.emit(
            room_id,
            "s2c_campaign_ended",
            "party",
            ending_payload,
        )
    return {
        "status": "completed",
        "endingType": "safe_abort",
        "roomId": room_id,
    }


@router.post("/{room_id}/reset")
async def emergency_reset(request: Request, room_id: str):
    _verify_owner(request, room_id)
    conn = request.app.state.db
    store = get_host_store(room_id, conn)
    store.reset()
    store.save_state(conn)
    return {"status": "reset", "room_id": room_id}


@router.post("/{room_id}/pause")
async def pause_host(request: Request, room_id: str):
    _verify_owner(request, room_id)
    conn = request.app.state.db
    store = get_host_store(room_id, conn)
    store.is_paused = not store.is_paused
    store.save_state(conn)
    return {"status": "paused" if store.is_paused else "resumed", "room_id": room_id}


def _presentation_status(store: HostStore) -> dict:
    transaction = store.active_transaction
    total_steps = len(transaction.steps) if transaction else 0
    can_skip_visual = bool(
        transaction
        and store.current_step_index < total_steps
        and transaction.steps[store.current_step_index].kind == "scene_transition"
    )
    return {
        "transactionId": store.active_transaction_id,
        "currentStepIndex": store.current_step_index,
        "totalSteps": total_steps,
        "paused": store.presentation_paused,
        "completed": bool(transaction) and store.current_step_index >= total_steps,
        "queuedTransactions": len(store.normal_queue) + len(store.urgent_queue),
        "canSkipVisual": can_skip_visual,
    }


def _json_object(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _public_presentation_projection(conn, room_id: str, store: HostStore) -> dict:
    transaction = store.active_transaction
    stage_projection = None
    if transaction and transaction.action_id:
        row = conn.execute(
            """SELECT stage_projection FROM resolution_bundles
               WHERE room_id = %s AND action_id = %s AND release_status = 'released'""",
            (room_id, transaction.action_id),
        ).fetchone()
        if row:
            stage_projection = _json_object(row.get("stage_projection"))
    return build_public_presentation_projection(
        transaction,
        store.current_step_index,
        stage_projection,
        store.presentation_version,
    )


@router.get("/{room_id}/presentation")
async def get_presentation(request: Request, room_id: str):
    _verify_owner(request, room_id)
    return _presentation_status(get_host_store(room_id, request.app.state.db))


@router.get("/{room_id}/stage-presentation")
async def get_stage_presentation(request: Request, room_id: str):
    """Return only the safe, already-released narration selected for public playback."""
    _verify_owner(request, room_id)
    conn = request.app.state.db
    return _public_presentation_projection(conn, room_id, get_host_store(room_id, conn))


@router.post("/{room_id}/presentation/play")
async def play_presentation(request: Request, room_id: str):
    _verify_owner(request, room_id)
    store = get_host_store(room_id, request.app.state.db)
    store.presentation_paused = False
    store.start_next_presentation()
    store.save_state(request.app.state.db)
    return _presentation_status(store)


@router.post("/{room_id}/presentation/pause")
async def pause_presentation(request: Request, room_id: str):
    _verify_owner(request, room_id)
    store = get_host_store(room_id, request.app.state.db)
    store.presentation_paused = True
    store.save_state(request.app.state.db)
    return _presentation_status(store)


@router.post("/{room_id}/presentation/next")
async def advance_presentation(request: Request, room_id: str):
    _verify_owner(request, room_id)
    store = get_host_store(room_id, request.app.state.db)
    if store.presentation_paused:
        raise HTTPException(409, "Presentation is paused")
    step = store.advance_step()
    if step is None:
        raise HTTPException(409, "No presentation step is available")
    await _release_saved_player_events(
        room_id,
        store,
        store.active_transaction_id or "",
        store.current_step_index,
        step.step_id,
    )
    store.presentation_version += 1
    store.save_state(request.app.state.db)
    return _presentation_status(store)


@router.post("/{room_id}/presentation/skip-visual")
async def skip_visual_presentation_steps(request: Request, room_id: str):
    """Acknowledge contiguous scene-transition steps without exposing their payloads."""
    _verify_owner(request, room_id)
    store = get_host_store(room_id, request.app.state.db)
    if store.presentation_paused:
        raise HTTPException(409, "Presentation is paused")
    first_step_index = store.current_step_index
    skipped_steps = store.skip_visual_steps()
    if not skipped_steps:
        raise HTTPException(409, "No visual presentation step is available")
    for offset, step in enumerate(skipped_steps, start=1):
        await _release_saved_player_events(
            room_id,
            store,
            store.active_transaction_id or "",
            first_step_index + offset,
            step.step_id,
        )
    store.presentation_version += len(skipped_steps)
    store.save_state(request.app.state.db)
    return _presentation_status(store) | {"skippedVisualSteps": len(skipped_steps)}


@router.post("/{room_id}/presentation/replay")
async def replay_presentation(request: Request, room_id: str):
    """Request another render of the persisted public projection without changing authority."""
    _verify_owner(request, room_id)
    conn = request.app.state.db
    store = get_host_store(room_id, conn)
    store.presentation_version += 1
    store.save_state(conn)
    return _public_presentation_projection(conn, room_id, store)


@router.post("/{room_id}/retry-turn")
async def retry_turn(request: Request, room_id: str):
    _verify_owner(request, room_id)
    conn = request.app.state.db
    store = get_host_store(room_id, conn)
    if store.active_transaction:
        store.current_step_index = 0
        return {"status": "retried", "transaction_id": store.active_transaction_id}
    return {"status": "no_active_transaction", "room_id": room_id}


@router.get("/{room_id}/projection-replays")
async def list_projection_replays(request: Request, room_id: str):
    """List pending projection retries without exposing action text or results."""
    _verify_owner(request, room_id)
    rows = request.app.state.db.execute(
        "SELECT action_id, character_id FROM resolution_bundles "
        "WHERE room_id = %s AND release_status = 'projection_pending' ORDER BY created_at",
        (room_id,),
    ).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.post("/{room_id}/actions/{action_id}/replay-projection")
async def replay_action_projection(request: Request, room_id: str, action_id: str):
    """Replay persisted projections after delivery failed; never re-resolve the action."""
    _verify_owner(request, room_id)
    conn = request.app.state.db
    action = conn.execute(
        "SELECT action_id, room_id, status FROM actions WHERE action_id = %s AND room_id = %s",
        (action_id, room_id),
    ).fetchone()
    if not action:
        raise HTTPException(404, "Action not found")
    if action.get("status") not in {"completed", "resolved"}:
        raise HTTPException(409, "Action is not ready for projection replay")
    pipeline = getattr(request.app.state, "pipeline", None)
    replay = getattr(pipeline, "replay_projection", None)
    if not callable(replay):
        raise HTTPException(503, "Projection replay is unavailable")
    return await replay(action_id)


def _events_released_by_host_ack(
    store: HostStore,
    transaction_id: str,
    step_index: int,
    step_id: str,
) -> list[dict]:
    if transaction_id != store.active_transaction_id:
        return []
    acknowledged_step = min(max(step_index, 0), store.current_step_index)
    if not store.active_transaction or acknowledged_step <= 0:
        return []
    completed_step = store.active_transaction.steps[acknowledged_step - 1]
    if completed_step.step_id != step_id:
        return []
    return store.pop_ready_events(acknowledged_step)


async def _release_saved_player_events(
    room_id: str,
    store: HostStore,
    transaction_id: str,
    step_index: int,
    step_id: str,
) -> None:
    ready = _events_released_by_host_ack(store, transaction_id, step_index, step_id)
    for event_data in ready:
        character_id = event_data.get("character_id")
        if not character_id:
            continue
        try:
            player_event = EngineEvent(
                roomId=str(event_data.get("room_id") or room_id),
                type=event_data["event_type"],
                audience=event_data.get("audience", "player"),
                payload=event_data["payload"],
            )
            await ws_manager.send_event(room_id, f"player:{character_id}", player_event)
        except Exception as error:
            logger.warning(
                "Host %s could not release delayed event %s to player %s: %s",
                room_id,
                event_data.get("event_type"),
                character_id,
                error,
            )


async def host_ws_endpoint(websocket: WebSocket, room_id: str, owner_token: str = ""):
    from ..router_auth import verify_token
    conn = websocket.app.state.db

    # Auth: must have valid owner_token or admin account
    authorized = False
    if owner_token:
        room = conn.execute(
            "SELECT owner_token FROM rooms WHERE room_id = %s", (room_id,)
        ).fetchone()
        if room and room["owner_token"] == owner_token:
            authorized = True

    if not authorized:
        try:
            from ..router_auth import get_account_from_token
            account = get_account_from_token(websocket)
            if account:
                if account.get("role") == "admin":
                    authorized = True
                else:
                    room = conn.execute(
                        "SELECT owner_account_id FROM rooms WHERE room_id = %s", (room_id,)
                    ).fetchone()
                    if room and room.get("owner_account_id") == account.get("account_id"):
                        authorized = True
        except Exception:
            pass

    if not authorized:
        await websocket.close(code=1008, reason="Policy violation")
        logger.warning("Host WS auth failed for room=%s ownerToken=%s authorized=%s",
                       room_id, bool(owner_token), authorized)
        return

    store = get_host_store(room_id, conn)
    await websocket.accept()
    ws_manager.register_accepted(websocket, room_id, "host")
    logger.info("Host connected to room %s", room_id)

    # Push initial HUD immediately so HostStage has data without waiting
    try:
        from .hud_builder import build_hud
        hud = build_hud(conn, room_id)
        if store:
            hud.queue_status = {"normal": len(store.normal_queue), "urgent": len(store.urgent_queue)}
            hud.engine_state = store.engine_state
            hud.scene_image_url = store.current_scene_image_url
        await websocket.send_text(json.dumps({
            "type": "host_state_update",
            "hud": hud.model_dump(by_alias=True),
        }))
    except Exception:
        logger.exception("Failed to push initial HUD to host room=%s", room_id)
        ws_manager.disconnect(room_id, "host", websocket=websocket)
        return

    last_seq = 0
    try:
        while True:
            data = await websocket.receive_text()
            try:
                event_data = json.loads(data)
            except Exception as exc:
                logger.error(
                    "Host %s bad JSON error_type=%s",
                    room_id,
                    type(exc).__name__,
                )
                continue

            msg_type = event_data.get("type", "")

            if msg_type == "host_step_complete":
                transaction_id = event_data.get("transactionId")
                step_index = event_data.get("stepIndex", event_data.get("step_index"))
                step_id = event_data.get("stepId", event_data.get("step_id"))
                if (
                    not isinstance(transaction_id, str)
                    or not transaction_id
                    or not isinstance(step_index, int)
                    or isinstance(step_index, bool)
                    or not isinstance(step_id, str)
                    or not step_id
                ):
                    logger.warning("Host %s sent malformed step acknowledgement", room_id)
                    continue
                await _release_saved_player_events(
                    room_id,
                    store,
                    transaction_id,
                    step_index,
                    step_id,
                )
                store.save_state(conn)
                continue

            try:
                event = EngineEvent(**event_data)
            except Exception as exc:
                logger.error(
                    "Host %s bad event error_type=%s",
                    room_id,
                    type(exc).__name__,
                )
                continue

            if not store.route_event(event):
                continue

            if store.is_paused and event.type not in ("s2c_host_snapshot",):
                continue

            if event.type == "s2c_host_snapshot":
                store.apply_snapshot(event.payload)
                store.save_state(conn)
                await websocket.send_text(json.dumps({
                    "type": "host_state_update",
                    "hud": store.get_hud().model_dump(by_alias=True),
                }))
            elif event.type == "s2c_reveal_transaction":
                tx = RevealTransaction(**event.payload)
                if tx.audio_action:
                    store.pending_audio_action = tx.audio_action
                if store.active_transaction_id and tx.priority == "urgent":
                    store.preempt_for_urgent(tx)
                else:
                    store.enqueue_transaction(tx)
                hud = store.get_hud()
                store.consume_pending_audio_action()
                await websocket.send_text(json.dumps({
                    "type": "host_state_update",
                    "hud": hud.model_dump(by_alias=True),
                }))
            elif event.type == "s2c_resume_transaction":
                tx = store.resume_interrupted()
                if tx:
                    await websocket.send_text(json.dumps({
                        "type": "host_state_update",
                        "hud": store.get_hud().model_dump(by_alias=True),
                    }))
            elif event.type == "s2c_cancel_transaction":
                store.cancel_interrupted()
                store.complete_transaction()
                await websocket.send_text(json.dumps({
                    "type": "host_state_update",
                    "hud": store.get_hud().model_dump(by_alias=True),
                }))
            elif event.type == "s2c_atmosphere":
                store.apply_atmosphere(event.payload)
                store.save_state(conn)
                await websocket.send_text(json.dumps({
                    "type": "atmosphere_update",
                    "atmosphere": store.atmosphere,
                }))
            elif event.type == "s2c_engine_state":
                store.set_engine_state(event.payload.get("state", "idle"))
                store.save_state(conn)
                await websocket.send_text(json.dumps({
                    "type": "host_state_update",
                    "hud": store.get_hud().model_dump(by_alias=True),
                }))
            elif event.type == "s2c_scene_sync":
                store.set_scene_image(event.payload.get("image_url"))
                store.save_state(conn)
                await websocket.send_text(json.dumps({
                    "type": "scene_update",
                    "image_url": store.current_scene_image_url,
                }))
            elif event.type == "s2c_chat_stream":
                store.append_chat_message(event.payload)
                await websocket.send_text(json.dumps({
                    "type": "chat_message",
                    "message": event.payload,
                }))
            elif event.type == "s2c_public_observation":
                store.append_chat_message(event.payload)
                await websocket.send_text(json.dumps({
                    "type": "chat_message",
                    "message": event.payload,
                }))
            elif event.type == "s2c_map_updated":
                await websocket.send_text(json.dumps({
                    "type": "map_updated",
                    "payload": event.payload,
                }))
            elif event.type == "s2c_player_moved":
                await websocket.send_text(json.dumps({
                    "type": "player_moved",
                    "payload": event.payload,
                }))
            elif event.type == "s2c_map_revealed":
                await websocket.send_text(json.dumps({
                    "type": "map_revealed",
                    "payload": event.payload,
                }))
            elif event.type == "s2c_encounter_suggested":
                store.encounter_suggestion = event.payload
                await websocket.send_text(json.dumps({
                    "type": "encounter_suggested",
                    "payload": event.payload,
                }))
            elif event.type == "s2c_encounter_started":
                if isinstance(event.payload.get("participants"), list):
                    store.active_encounter = event.payload
                    store.encounter_suggestion = None
                    await websocket.send_text(json.dumps({
                        "type": "encounter_started",
                        "payload": event.payload,
                    }))
            elif event.type == "s2c_encounter_updated":
                if isinstance(event.payload.get("participants"), list):
                    store.active_encounter = event.payload
                    await websocket.send_text(json.dumps({
                        "type": "encounter_updated",
                        "payload": event.payload,
                    }))
            elif event.type == "s2c_encounter_resolved":
                store.active_encounter = None
                await websocket.send_text(json.dumps({
                    "type": "encounter_resolved",
                    "payload": event.payload,
                }))
            elif event.type == "s2c_team_message":
                await websocket.send_text(json.dumps({
                    "type": "team_message",
                    "payload": event.payload,
                }))
            elif event.type == "s2c_safety_request":
                await websocket.send_text(json.dumps({
                    "type": "safety_request",
                    "payload": event.payload,
                }))
            elif event.type == "s2c_room_lobby_snapshot":
                await websocket.send_text(json.dumps({
                    "type": "s2c_room_lobby_snapshot",
                    "payload": event.payload,
                }))

    except WebSocketDisconnect:
        logger.info("Host disconnected from room %s", room_id)
    except Exception as exc:
        logger.error(
            "Host %s error_type=%s",
            room_id,
            type(exc).__name__,
        )
    finally:
        ws_manager.disconnect(room_id, "host", websocket=websocket)


@router.post("/{room_id}/approve/{character_id}")
async def approve_character(request: Request, room_id: str, character_id: str):
    """Approve a pending_approval character to joined."""
    _verify_owner(request, room_id)
    conn = request.app.state.db
    char = conn.execute(
        "SELECT * FROM characters WHERE character_id = %s AND room_id = %s",
        (character_id, room_id),
    ).fetchone()
    if not char:
        raise HTTPException(404, "Character not found")
    if char.get("status") != "pending_approval":
        raise HTTPException(409, "Character is not pending approval")
    conn.execute("UPDATE characters SET status = 'joined' WHERE character_id = %s", (character_id,))
    conn.commit()

    # Broadcast updated lobby snapshot
    try:
        from ..player.router_player import _build_lobby_snapshot
        snapshot = _build_lobby_snapshot(conn, room_id)
        from ..engine.projection import ProjectionDispatcher
        dispatcher = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(conn)
        import asyncio as _asyncio
        _asyncio.create_task(dispatcher.emit(room_id, "s2c_room_lobby_snapshot", "party", snapshot))
    except Exception:
        logger.warning("Failed to broadcast lobby snapshot after approve", exc_info=True)

    return {"status": "approved", "character_id": character_id}


@router.post("/{room_id}/reject/{character_id}")
async def reject_character(request: Request, room_id: str, character_id: str):
    """Reject a pending_approval character."""
    _verify_owner(request, room_id)
    conn = request.app.state.db
    char = conn.execute(
        "SELECT * FROM characters WHERE character_id = %s AND room_id = %s",
        (character_id, room_id),
    ).fetchone()
    if not char:
        raise HTTPException(404, "Character not found")
    if char.get("status") != "pending_approval":
        raise HTTPException(409, "Character is not pending approval")
    conn.execute(
        "UPDATE characters SET status = 'left', player_token = %s WHERE character_id = %s",
        (str(uuid.uuid4()), character_id),
    )
    conn.commit()

    # Broadcast updated lobby snapshot
    try:
        from ..player.router_player import _build_lobby_snapshot
        snapshot = _build_lobby_snapshot(conn, room_id)
        from ..engine.projection import ProjectionDispatcher
        dispatcher = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(conn)
        import asyncio as _asyncio
        _asyncio.create_task(dispatcher.emit(room_id, "s2c_room_lobby_snapshot", "party", snapshot))
    except Exception:
        logger.warning("Failed to broadcast lobby snapshot after reject", exc_info=True)

    return {"status": "rejected", "character_id": character_id}


@router.post("/{room_id}/players/{character_id}/remove")
async def remove_active_character(
    request: Request,
    room_id: str,
    character_id: str,
    body: dict,
):
    """Terminate current access without transferring character ownership or data."""

    _verify_owner(request, room_id)
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, detail={"code": "removal_reason_required"})
    conn = request.app.state.db
    with conn.transaction() as tx:
        character = tx.execute(
            "SELECT character_id, status FROM characters "
            "WHERE character_id = %s AND room_id = %s FOR UPDATE",
            (character_id, room_id),
        ).fetchone()
        if not character:
            raise HTTPException(404, detail={"code": "character_not_found"})
        if character["status"] == "protected_inactive":
            return {"characterId": character_id, "status": "protected_inactive"}
        if character["status"] not in {"joined", "ready"}:
            raise HTTPException(409, detail={"code": "character_not_active"})
        tx.execute(
            "UPDATE characters SET status = 'protected_inactive', player_token = %s "
            "WHERE character_id = %s",
            (str(uuid.uuid4()), character_id),
        )
        tx.execute(
            "INSERT INTO events (room_id, event_type, audience, payload) "
            "VALUES (%s, 'character_access_terminated', 'system', %s)",
            (
                room_id,
                json.dumps(
                    {
                        "actor": "host",
                        "characterId": character_id,
                        "reason": reason[:500],
                        "result": "protected_inactive",
                    },
                    ensure_ascii=False,
                ),
            ),
        )
    return {"characterId": character_id, "status": "protected_inactive"}


# ── Host Map Supervision ──

@router.get("/{room_id}/map/full")
async def get_host_full_map(request: Request, room_id: str):
    """Host sees the full map with all nodes, edges, player positions, and fog state."""
    _verify_owner(request, room_id)
    conn = request.app.state.db

    from ..map_persistence import (
        get_room_map_state, get_scenario_map, get_all_positions_in_room, get_character_position,
    )
    map_state = get_room_map_state(conn, room_id)
    if not map_state:
        raise HTTPException(404, "No map initialized for this room")

    scenario_map = get_scenario_map(conn, map_state["map_id"])
    if not scenario_map:
        raise HTTPException(404, "Scenario map not found")

    positions = get_all_positions_in_room(conn, room_id)

    return {
        "roomId": room_id,
        "nodes": scenario_map.get("nodes", []),
        "edges": scenario_map.get("edges", []),
        "playerPositions": positions,
        "exploredNodes": map_state.get("explored_nodes", []),
        "hiddenNodes": map_state.get("hidden_nodes", []),
        "regions": [
            {
                "regionId": region.get("regionId", region.get("region_id", "")),
                "nodeId": region.get("nodeId", region.get("node_id", "")),
            }
            for region in scenario_map.get("regions", [])
            if isinstance(region, dict)
        ],
        "fogRegions": map_state.get("fog_regions", []),
        "mapStatus": scenario_map.get("status", "draft"),
    }


@router.post("/{room_id}/map/reveal")
async def host_reveal_node(request: Request, room_id: str):
    """Host manually reveals or hides a map node. Only affects nodes belonging to this room's map."""
    _verify_owner(request, room_id)
    body = await request.json()
    node_id = body.get("node_id", body.get("nodeId", ""))
    visible = body.get("visible", True)

    if not node_id:
        raise HTTPException(400, "node_id is required")

    conn = request.app.state.db
    from ..map_persistence import host_set_node_visible, get_room_map_state, get_scenario_map

    # Validate node belongs to this room's map
    map_state = get_room_map_state(conn, room_id)
    if not map_state:
        raise HTTPException(404, "No map initialized for this room")
    scenario_map = get_scenario_map(conn, map_state["map_id"])
    if not scenario_map:
        raise HTTPException(404, "Scenario map not found")
    node_ids = {n.get("node_id", n.get("nodeId", "")) for n in scenario_map.get("nodes", [])}
    if node_id not in node_ids:
        raise HTTPException(400, "节点不属于当前房间地图")

    result = host_set_node_visible(conn, room_id, node_id, visible)
    if result is None:
        raise HTTPException(404, "No map initialized for this room")
    changed, map_version = result

    if changed:
        from ..engine.projection import ProjectionDispatcher
        dispatcher = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(conn)
        await dispatcher.emit(room_id, "s2c_map_revealed", "party", {
                "nodeId": node_id,
                "visible": visible,
                "mapVersion": map_version,
                "roomId": room_id,
        })

    return {"status": "ok", "nodeId": node_id, "visible": visible, "mapVersion": map_version}


@router.post("/{room_id}/map/regions/{region_id}/visibility")
async def host_set_region_visibility(request: Request, room_id: str, region_id: str):
    """Host rescue control for image-map fog regions."""
    _verify_owner(request, room_id)
    body = await request.json()
    visible = body.get("visible")
    if not isinstance(visible, bool):
        raise HTTPException(422, "visible must be a boolean")

    conn = request.app.state.db
    from ..map_persistence import get_room_map_state, get_scenario_map, host_set_region_visible

    map_state = get_room_map_state(conn, room_id)
    if not map_state:
        raise HTTPException(404, "No map initialized for this room")
    scenario_map = get_scenario_map(conn, map_state["map_id"])
    if not scenario_map:
        raise HTTPException(404, "Scenario map not found")
    region_ids = {
        region.get("regionId", region.get("region_id", ""))
        for region in scenario_map.get("regions", [])
        if isinstance(region, dict)
    }
    if region_id not in region_ids:
        raise HTTPException(400, "区域不属于当前房间地图")

    result = host_set_region_visible(conn, room_id, region_id, visible)
    if result is None:
        raise HTTPException(404, "No map initialized for this room")
    changed, map_version = result
    if changed:
        from ..engine.projection import ProjectionDispatcher
        dispatcher = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(conn)
        await dispatcher.emit(room_id, "s2c_map_revealed", "party", {
            "regionId": region_id,
            "visible": visible,
            "mapVersion": map_version,
            "roomId": room_id,
        })

    return {
        "roomId": room_id,
        "regionId": region_id,
        "visible": visible,
        "mapVersion": map_version,
    }


@router.post("/{room_id}/map/move-character")
async def host_force_move(request: Request, room_id: str):
    body = await request.json()
    character_id = body.get("character_id", body.get("characterId", ""))
    target_node_id = body.get("node_id", body.get("nodeId", ""))
    if not character_id or not target_node_id:
        raise HTTPException(400, "character_id and node_id are required")
    async with lifecycle_guard(
        [f"room:{room_id}", f"character:{character_id}"],
        conn=request.app.state.db,
    ):
        return await _host_force_move_locked(request, room_id)


async def _host_force_move_locked(request: Request, room_id: str):
    """Host force-moves a character to a node. Requires reason. Validates ownership."""
    owner_info = _verify_owner(request, room_id)
    body = await request.json()
    character_id = body.get("character_id", body.get("characterId", ""))
    target_node_id = body.get("node_id", body.get("nodeId", ""))
    reason = body.get("reason", "").strip()
    from_node_id = body.get("from_node_id", body.get("fromNodeId", ""))

    if not character_id or not target_node_id:
        raise HTTPException(400, "character_id and node_id are required")
    if not reason:
        raise HTTPException(400, "force move requires reason")

    conn = request.app.state.db

    # Validate character belongs to this room
    char = conn.execute(
        "SELECT * FROM characters WHERE character_id = %s AND room_id = %s",
        (character_id, room_id),
    ).fetchone()
    if not char:
        raise HTTPException(400, "角色不属于当前房间")

    # Validate node belongs to this room's map
    from ..map_persistence import (
        set_character_position, mark_node_explored, get_room_map_state, get_scenario_map,
        get_character_position, reveal_regions_for_node,
    )
    map_state = get_room_map_state(conn, room_id)
    if not map_state:
        raise HTTPException(404, "No map initialized for this room")
    scenario_map = get_scenario_map(conn, map_state["map_id"])
    if not scenario_map:
        raise HTTPException(404, "Scenario map not found")
    node_ids = {n.get("node_id", n.get("nodeId", "")) for n in scenario_map.get("nodes", [])}
    if target_node_id not in node_ids:
        raise HTTPException(400, "目标节点不属于当前房间地图")

    actual_from = from_node_id or get_character_position(conn, character_id, room_id) or "?"

    set_character_position(conn, character_id, room_id, target_node_id)
    mark_node_explored(conn, room_id, target_node_id)
    revealed_region_ids = reveal_regions_for_node(conn, room_id, target_node_id)
    current_map_state = get_room_map_state(conn, room_id)
    map_version = current_map_state.get("state_version", 0) if current_map_state else 0

    from ..engine.projection import ProjectionDispatcher
    dispatcher = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(conn)

    import asyncio
    try:
        asyncio.get_running_loop().create_task(
            dispatcher.emit(room_id, "s2c_player_moved", "party", {
                "characterId": character_id,
                "fromNodeId": actual_from,
                "toNodeId": target_node_id,
                "forced": True,
                "mapVersion": map_version,
                "revealedRegionIds": revealed_region_ids,
                "reason": reason,
            })
        )
        # Write audit event for force move
        from ..events.event_log import EventLog
        el = EventLog(conn)
        el.log_event(room_id, "host_force_move", "system", {
            "operation": "force_move",
            "roomId": room_id,
            "actorAccountId": owner_info.get("owner_account_id", "host"),
            "targetCharacterId": character_id,
            "fromNodeId": actual_from,
            "toNodeId": target_node_id,
            "reason": reason,
            "mapVersion": map_version,
        })
    except RuntimeError:
        pass

    return {
        "status": "ok",
        "characterId": character_id,
        "nodeId": target_node_id,
        "fromNodeId": actual_from,
        "mapVersion": map_version,
        "revealedRegionIds": revealed_region_ids,
    }


# ── Host Encounter Management ──

@router.get("/{room_id}/encounter")
async def get_host_encounter(request: Request, room_id: str):
    """Get current active encounter with participants for this room."""
    _verify_owner(request, room_id)
    conn = request.app.state.db
    from ..encounter_persistence import get_active_encounter, get_participants
    enc = get_active_encounter(conn, room_id)
    if not enc:
        return {"hasEncounter": False}
    parts = get_participants(conn, enc["encounter_id"])
    return {
        "hasEncounter": True,
        "encounter": dict(enc),
        "participants": [dict(p) for p in parts],
    }


@router.post("/{room_id}/encounter/confirm")
async def host_confirm_encounter(request: Request, room_id: str):
    """Host confirms a suggested encounter — creates participants and sets active.
    If no encounter_id provided, auto-creates an encounter first."""
    _verify_owner(request, room_id)
    body = await request.json()
    encounter_id = body.get("encounter_id", body.get("encounterId", ""))

    conn = request.app.state.db
    from ..encounter_persistence import (
        get_encounter, create_encounter, update_encounter_status, add_participant,
        get_participants,
    )
    import uuid as _uuid

    if not encounter_id:
        # Auto-create encounter from suggestion data
        enc_type = body.get("type", "combat")
        encounter_id = f"enc_{str(_uuid.uuid4())[:8]}"
        create_encounter(conn, encounter_id, room_id, enc_type, "active",
                         body.get("reason", "Host confirmed encounter"))
    else:
        enc = get_encounter(conn, encounter_id)
        if not enc or enc.get("room_id") != room_id:
            raise HTTPException(404, "Encounter not found")
        if enc["status"] != "suggested":
            raise HTTPException(400, "Encounter is not in suggested status")
        update_encounter_status(conn, encounter_id, "active")

    # Add participants from body
    participants = body.get("participants", [])
    for p in participants:
        cid = p.get("character_id", p.get("characterId", ""))
        if not cid:
            continue
        add_participant(
            conn, encounter_id, cid,
            side=p.get("side", "player"),
            hp=p.get("hp", 10), hp_max=p.get("hp_max", p.get("hpMax", 10)),
            san=p.get("san", 50), san_max=p.get("san_max", p.get("sanMax", 50)),
            dex=p.get("dex", 50), mov=p.get("mov", 7),
            distance_band=p.get("distance_band", p.get("distanceBand", "medium")),
            weapon_name=p.get("weapon_name", p.get("weaponName", "")),
            damage_expression=p.get("damage_expression", p.get("damageExpression", "1d3")),
            main_skill=p.get("main_skill", p.get("mainSkill", "")),
            display_name=p.get("display_name", p.get("displayName", "")),
            public_visibility=p.get("public_visibility", p.get("publicVisibility", "hidden")),
            public_label=p.get("public_label", p.get("publicLabel", "")),
            last_observed_position=p.get("last_observed_position", p.get("lastObservedPosition", "")),
        )

    from ..engine.projection import ProjectionDispatcher
    dispatcher = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(conn)
    import asyncio
    try:
        full_encounter = _event_safe_record(get_encounter(conn, encounter_id))
        full_parts = [dict(p) for p in get_participants(conn, encounter_id)]
        asyncio.get_running_loop().create_task(
            dispatcher.emit(room_id, "s2c_encounter_started", "party", {
                **build_public_encounter_event_projection(
                    full_encounter,
                    build_public_combat_units_for_encounter(conn, encounter_id),
                ),
            })
        )
        asyncio.get_running_loop().create_task(
            dispatcher.emit(room_id, "s2c_encounter_started", "host", {
                "encounterId": encounter_id,
                "encounter": full_encounter,
                "participants": full_parts,
            })
        )
    except RuntimeError:
        pass

    return {"status": "active", "encounterId": encounter_id}


@router.post("/{room_id}/encounter/reject")
async def host_reject_encounter(request: Request, room_id: str):
    """Host rejects a suggested encounter."""
    _verify_owner(request, room_id)
    body = await request.json()
    encounter_id = body.get("encounter_id", body.get("encounterId", ""))
    if not encounter_id:
        return {"status": "ignored"}  # No encounter to reject

    conn = request.app.state.db
    from ..encounter_persistence import update_encounter_status, get_encounter
    enc = get_encounter(conn, encounter_id)
    if not enc or enc.get("room_id") != room_id:
        raise HTTPException(404, "Encounter not found")
    update_encounter_status(conn, encounter_id, "cancelled", "Host rejected")
    return {"status": "cancelled", "encounterId": encounter_id}


@router.post("/{room_id}/encounter/next-round")
async def host_next_round(request: Request, room_id: str):
    """Advance encounter to next round — resets acted_this_round for all."""
    owner_info = _verify_owner(request, room_id)
    reason = _require_emergency_reason(await request.json(), "advance_round")
    conn = request.app.state.db
    from ..encounter_persistence import (
        get_active_encounter, update_encounter_round, reset_round_actions, get_participants,
    )
    enc = get_active_encounter(conn, room_id)
    if not enc:
        raise HTTPException(404, "No active encounter")
    if enc["status"] != "active":
        raise HTTPException(400, "Encounter is not active")

    new_round = enc["current_round"] + 1
    update_encounter_round(conn, enc["encounter_id"], new_round)
    reset_round_actions(conn, enc["encounter_id"])
    _audit_encounter_intervention(
        conn,
        room_id,
        owner_info,
        operation="advance_round",
        encounter_id=enc["encounter_id"],
        reason=reason,
    )

    from ..engine.projection import ProjectionDispatcher
    from .public_stage import (
        build_public_combat_units_for_encounter,
        build_public_encounter_event_projection,
    )
    dispatcher = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(conn)
    import asyncio
    try:
        asyncio.get_running_loop().create_task(
            dispatcher.emit(room_id, "s2c_encounter_updated", "party", {
                **build_public_encounter_event_projection(
                    _event_safe_record(get_active_encounter(conn, room_id)),
                    build_public_combat_units_for_encounter(conn, enc["encounter_id"]),
                ),
            })
        )
        asyncio.get_running_loop().create_task(
            dispatcher.emit(room_id, "s2c_encounter_updated", "host", {
                "encounterId": enc["encounter_id"],
                "encounter": _event_safe_record(get_active_encounter(conn, room_id)),
                "participants": [dict(p) for p in get_participants(conn, enc["encounter_id"])],
            })
        )
    except RuntimeError:
        pass

    return {"status": "ok", "encounterId": enc["encounter_id"], "currentRound": new_round}


@router.post("/{room_id}/encounter/resolve")
async def host_resolve_encounter(request: Request, room_id: str):
    """Host manually ends an encounter."""
    owner_info = _verify_owner(request, room_id)
    reason = _require_emergency_reason(await request.json(), "resolve_encounter")
    conn = request.app.state.db
    from ..encounter_persistence import get_active_encounter, update_encounter_status
    enc = get_active_encounter(conn, room_id)
    if not enc:
        raise HTTPException(404, "No active encounter")

    update_encounter_status(conn, enc["encounter_id"], "resolved", "Host manually ended")
    _audit_encounter_intervention(
        conn,
        room_id,
        owner_info,
        operation="resolve_encounter",
        encounter_id=enc["encounter_id"],
        reason=reason,
    )

    from ..engine.projection import ProjectionDispatcher
    dispatcher = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(conn)
    import asyncio
    try:
        asyncio.get_running_loop().create_task(
            dispatcher.emit(room_id, "s2c_encounter_resolved", "party", {
                "encounterId": enc["encounter_id"],
                "reason": "Host manually ended",
            })
        )
    except RuntimeError:
        pass

    return {"status": "resolved", "encounterId": enc["encounter_id"]}


@router.post("/{room_id}/encounter/npc")
async def host_create_npc(request: Request, room_id: str):
    """Quick-create an NPC participant for an encounter."""
    owner_info = _verify_owner(request, room_id)
    body = await request.json()
    reason = _require_emergency_reason(body, "create_encounter_participant")
    encounter_id = body.get("encounter_id", body.get("encounterId", ""))
    npc_name = body.get("name", "未命名NPC")

    if not encounter_id:
        raise HTTPException(400, "encounter_id is required")

    conn = request.app.state.db
    from ..encounter_persistence import add_participant, get_participants, get_encounter
    import uuid as _uuid

    # Verify encounter belongs to this room
    enc = get_encounter(conn, encounter_id)
    if not enc or enc.get("room_id") != room_id:
        raise HTTPException(404, "Encounter not found")

    npc_id = f"npc:{str(_uuid.uuid4())[:8]}"
    add_participant(
        conn, encounter_id, npc_id,
        side=body.get("side", "enemy"),
        hp=body.get("hp", 10), hp_max=body.get("hp_max", body.get("hpMax", 10)),
        dex=body.get("dex", 50), mov=body.get("mov", 7),
        distance_band=body.get("distance_band", body.get("distanceBand", "medium")),
        weapon_name=body.get("weapon_name", body.get("weaponName", "")),
        damage_expression=body.get("damage_expression", body.get("damageExpression", "1d3")),
        main_skill=body.get("main_skill", body.get("mainSkill", "")),
        notes=body.get("notes", ""),
        display_name=npc_name,
        public_visibility=body.get("public_visibility", body.get("publicVisibility", "hidden")),
        public_label=body.get("public_label", body.get("publicLabel", "")),
        last_observed_position=body.get("last_observed_position", body.get("lastObservedPosition", "")),
    )
    _audit_encounter_intervention(
        conn,
        room_id,
        owner_info,
        operation="create_encounter_participant",
        encounter_id=encounter_id,
        reason=reason,
        target_id=npc_id,
    )

    parts = [dict(p) for p in get_participants(conn, encounter_id)]
    return {"status": "created", "npcId": npc_id, "name": npc_name, "participants": parts}
