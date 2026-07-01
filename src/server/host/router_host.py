import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, HTTPException
from ..models import EngineEvent, RevealTransaction
from .host_store import HostStore, HOST_VISIBLE_EVENTS, PRIVATE_EVENTS
from .ws_manager import manager as ws_manager

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
        logger.warning("_verify_owner: account auth lookup failed room=%s: %s", room_id, exc)

    logger.warning("_verify_owner: denied room=%s (token=%s, account failed)", room_id, bool(token))
    raise HTTPException(403, "不是房间所有者")


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
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "Room not found")
    store = get_host_store(room_id, conn)
    characters = conn.execute(
        "SELECT character_id, player_name FROM characters WHERE room_id = %s", (room_id,)
    ).fetchall()
    for char in characters:
        if not any(p.character_id == char["character_id"] for p in store.players):
            from ..models import PlayerPublicStatus
            store.players.append(PlayerPublicStatus(
                character_id=char["character_id"],
                player_name=char["player_name"],
            ))
    return store.get_hud().model_dump(by_alias=True)


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


@router.post("/{room_id}/retry-turn")
async def retry_turn(request: Request, room_id: str):
    _verify_owner(request, room_id)
    conn = request.app.state.db
    store = get_host_store(room_id, conn)
    if store.active_transaction:
        store.current_step_index = 0
        return {"status": "retried", "transaction_id": store.active_transaction_id}
    return {"status": "no_active_transaction", "room_id": room_id}


async def host_ws_endpoint(websocket: WebSocket, room_id: str):
    conn = websocket.app.state.db
    store = get_host_store(room_id, conn)
    await websocket.accept()
    ws_manager.register_accepted(websocket, room_id, "host")
    logger.info("Host connected to room %s", room_id)

    last_seq = 0
    try:
        while True:
            data = await websocket.receive_text()
            try:
                event_data = json.loads(data)
            except Exception as e:
                logger.error("Host %s bad JSON: %s", room_id, e)
                continue

            msg_type = event_data.get("type", "")

            if msg_type == "host_step_complete":
                step_index = event_data.get("step_index", store.current_step_index)
                ready = store.pop_ready_events(step_index)
                for ev in ready:
                    target_cid = ev.get("character_id")
                    if target_cid:
                        conn_id = f"player:{target_cid}"
                        from ..models import EngineEvent as _EE
                        player_event = _EE(
                            roomId=ev["room_id"],
                            type=ev["event_type"],
                            audience=ev.get("audience", "player"),
                            payload=ev["payload"],
                        )
                        await ws_manager.send_event(room_id, conn_id, player_event)
                        logger.info(
                            "Host %s flushed delayed event %s to player %s at step %d",
                            room_id, ev["event_type"], target_cid, step_index,
                        )
                remaining = store.flush_all_delayed()
                for ev in remaining:
                    target_cid = ev.get("character_id")
                    if target_cid:
                        conn_id = f"player:{target_cid}"
                        from ..models import EngineEvent as _EE
                        player_event = _EE(
                            roomId=ev["room_id"],
                            type=ev["event_type"],
                            audience=ev.get("audience", "player"),
                            payload=ev["payload"],
                        )
                        await ws_manager.send_event(room_id, conn_id, player_event)
                store.save_state(conn)
                continue

            try:
                event = EngineEvent(**event_data)
            except Exception as e:
                logger.error("Host %s bad event: %s", room_id, e)
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
                store.active_encounter = event.payload
                store.encounter_suggestion = None
                await websocket.send_text(json.dumps({
                    "type": "encounter_started",
                    "payload": event.payload,
                }))
            elif event.type == "s2c_encounter_updated":
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

    except WebSocketDisconnect:
        logger.info("Host disconnected from room %s", room_id)
    except Exception as e:
        logger.error("Host %s error: %s", room_id, e)
    finally:
        ws_manager.disconnect(room_id, "host")


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
    conn.execute("UPDATE characters SET status = 'left' WHERE character_id = %s", (character_id,))
    conn.commit()
    return {"status": "rejected", "character_id": character_id}


# ── Host Map Supervision ──

@router.get("/{room_id}/map/full")
async def get_host_full_map(request: Request, room_id: str):
    """Host sees the full map with all nodes, edges, player positions, and fog state."""
    _verify_owner(request, room_id)
    conn = request.app.state.db

    from ...map_persistence import (
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
        "mapStatus": scenario_map.get("status", "draft"),
    }


@router.post("/{room_id}/map/reveal")
async def host_reveal_node(request: Request, room_id: str):
    """Host manually reveals or hides a map node."""
    _verify_owner(request, room_id)
    body = await request.json()
    node_id = body.get("node_id", body.get("nodeId", ""))
    visible = body.get("visible", True)

    if not node_id:
        raise HTTPException(400, "node_id is required")

    conn = request.app.state.db
    from ...map_persistence import host_set_node_visible
    host_set_node_visible(conn, room_id, node_id, visible)

    from ...engine.projection import ProjectionDispatcher
    dispatcher = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(conn)

    import asyncio
    try:
        asyncio.get_running_loop().create_task(
            dispatcher.emit(room_id, "s2c_map_revealed", "party", {
                "nodeId": node_id,
                "visible": visible,
            })
        )
    except RuntimeError:
        pass

    return {"status": "ok", "nodeId": node_id, "visible": visible}


@router.post("/{room_id}/map/move-character")
async def host_force_move(request: Request, room_id: str):
    """Host force-moves a character to a node."""
    _verify_owner(request, room_id)
    body = await request.json()
    character_id = body.get("character_id", body.get("characterId", ""))
    target_node_id = body.get("node_id", body.get("nodeId", ""))

    if not character_id or not target_node_id:
        raise HTTPException(400, "character_id and node_id are required")

    conn = request.app.state.db
    from ...map_persistence import set_character_position, mark_node_explored
    set_character_position(conn, character_id, room_id, target_node_id)
    mark_node_explored(conn, room_id, target_node_id)
    conn.execute(
        "UPDATE room_map_state SET state_version = state_version + 1, updated_at = NOW() WHERE room_id = %s",
        (room_id,),
    )
    conn.commit()

    from ...engine.projection import ProjectionDispatcher
    dispatcher = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(conn)

    import asyncio
    try:
        asyncio.get_running_loop().create_task(
            dispatcher.emit(room_id, "s2c_player_moved", "party", {
                "characterId": character_id,
                "fromNodeId": None,
                "toNodeId": target_node_id,
                "forced": True,
            })
        )
    except RuntimeError:
        pass

    return {"status": "ok", "characterId": character_id, "nodeId": target_node_id}


# ── Host Encounter Management ──

@router.get("/{room_id}/encounter")
async def get_host_encounter(request: Request, room_id: str):
    """Get current active encounter with participants for this room."""
    _verify_owner(request, room_id)
    conn = request.app.state.db
    from ...encounter_persistence import get_active_encounter, get_participants
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
    from ...encounter_persistence import (
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
        )

    from ...engine.projection import ProjectionDispatcher
    dispatcher = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(conn)
    import asyncio
    try:
        all_parts = [dict(p) for p in get_participants(conn, encounter_id)]
        asyncio.get_running_loop().create_task(
            dispatcher.emit(room_id, "s2c_encounter_started", "party", {
                "encounterId": encounter_id,
                "encounter": dict(get_encounter(conn, encounter_id)),
                "participants": all_parts,
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
    from ...encounter_persistence import update_encounter_status, get_encounter
    enc = get_encounter(conn, encounter_id)
    if not enc or enc.get("room_id") != room_id:
        raise HTTPException(404, "Encounter not found")
    update_encounter_status(conn, encounter_id, "cancelled", "Host rejected")
    return {"status": "cancelled", "encounterId": encounter_id}


@router.post("/{room_id}/encounter/next-round")
async def host_next_round(request: Request, room_id: str):
    """Advance encounter to next round — resets acted_this_round for all."""
    _verify_owner(request, room_id)
    conn = request.app.state.db
    from ...encounter_persistence import (
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

    from ...engine.projection import ProjectionDispatcher
    dispatcher = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(conn)
    import asyncio
    try:
        asyncio.get_running_loop().create_task(
            dispatcher.emit(room_id, "s2c_encounter_updated", "party", {
                "encounterId": enc["encounter_id"],
                "encounter": dict(get_active_encounter(conn, room_id)),
                "participants": [dict(p) for p in get_participants(conn, enc["encounter_id"])],
            })
        )
    except RuntimeError:
        pass

    return {"status": "ok", "encounterId": enc["encounter_id"], "currentRound": new_round}


@router.post("/{room_id}/encounter/resolve")
async def host_resolve_encounter(request: Request, room_id: str):
    """Host manually ends an encounter."""
    _verify_owner(request, room_id)
    conn = request.app.state.db
    from ...encounter_persistence import get_active_encounter, update_encounter_status
    enc = get_active_encounter(conn, room_id)
    if not enc:
        raise HTTPException(404, "No active encounter")

    update_encounter_status(conn, enc["encounter_id"], "resolved", "Host manually ended")

    from ...engine.projection import ProjectionDispatcher
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
    _verify_owner(request, room_id)
    body = await request.json()
    encounter_id = body.get("encounter_id", body.get("encounterId", ""))
    npc_name = body.get("name", "未命名NPC")

    if not encounter_id:
        raise HTTPException(400, "encounter_id is required")

    conn = request.app.state.db
    from ...encounter_persistence import add_participant, get_participants, get_encounter
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
    )

    parts = [dict(p) for p in get_participants(conn, encounter_id)]
    return {"status": "created", "npcId": npc_id, "name": npc_name, "participants": parts}
