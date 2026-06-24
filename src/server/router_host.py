import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, HTTPException
from .models import EngineEvent, RevealTransaction
from .host_store import HostStore, HOST_VISIBLE_EVENTS, PRIVATE_EVENTS
from .ws_manager import manager as ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/host")

_host_stores: dict[str, HostStore] = {}


def _verify_owner(request: Request, room_id: str) -> dict:
    token = request.headers.get("X-Owner-Token", "")
    conn = request.app.state.db
    room = conn.execute(
        "SELECT * FROM rooms WHERE room_id = %s AND owner_token = %s",
        (room_id, token),
    ).fetchone()
    if not room:
        raise HTTPException(403, "Not room owner")
    return dict(room)


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
            from .models import PlayerPublicStatus
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
                        from .models import EngineEvent as _EE
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
                        from .models import EngineEvent as _EE
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

    except WebSocketDisconnect:
        logger.info("Host disconnected from room %s", room_id)
    except Exception as e:
        logger.error("Host %s error: %s", room_id, e)
    finally:
        ws_manager.disconnect(room_id, "host")
