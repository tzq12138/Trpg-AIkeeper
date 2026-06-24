import asyncio
import json
import logging
from datetime import datetime, timezone
from .models import (
    EngineEvent, RevealTransaction, TransactionStep,
    PlayerPublicStatus, HostHUD, AtmosphereCommand,
)

logger = logging.getLogger(__name__)

MAX_CHAT_MESSAGES = 200

HOST_VISIBLE_EVENTS = {
    "s2c_reveal_transaction", "s2c_resume_transaction", "s2c_cancel_transaction",
    "s2c_atmosphere", "s2c_engine_state", "s2c_scene_sync", "s2c_host_snapshot",
    "s2c_chat_stream", "s2c_public_observation",
}

PRIVATE_EVENTS = {
    "s2c_full_snapshot", "s2c_state_patch", "s2c_private_notice",
    "s2c_tactical_prompt", "s2c_clarification_prompt", "s2c_clarification_result",
    "s2c_action_queued", "s2c_action_batched", "s2c_action_completed",
    "s2c_room_lobby_snapshot", "s2c_campaign_ended",
}


class HostStore:
    def __init__(self, room_id: str):
        self.room_id = room_id
        self.current_scene_image_url: str | None = None
        self.chat_messages: list[dict] = []
        self.current_roll_event: dict | None = None
        self.normal_queue: list[RevealTransaction] = []
        self.urgent_queue: list[RevealTransaction] = []
        self.active_transaction_id: str | None = None
        self.active_transaction: RevealTransaction | None = None
        self.current_step_index: int = 0
        self.interrupted_transaction: RevealTransaction | None = None
        self.interrupted_step_index: int = 0
        self.last_host_sequence: int = 0
        self.atmosphere: dict = {"bgm": None, "sfx_queue": [], "visual": None}
        self.players: list[PlayerPublicStatus] = []
        self.engine_state: str = "idle"
        self.is_paused: bool = False
        self.pending_audio_action: str | None = None
        self.delayed_events: list[dict] = []
        self._step_timers: dict[str, asyncio.Task] = {}
        self._event_loop: asyncio.AbstractEventLoop | None = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self._event_loop = loop

    def route_event(self, event: EngineEvent) -> bool:
        if event.type in PRIVATE_EVENTS:
            logger.warning("Host %s dropped private event %s", self.room_id, event.type)
            return False
        if event.type not in HOST_VISIBLE_EVENTS:
            logger.warning("Host %s dropped unknown event %s", self.room_id, event.type)
            return False
        if event.room_sequence <= self.last_host_sequence and event.room_sequence > 0:
            logger.debug("Host %s dropped duplicate seq %d", self.room_id, event.room_sequence)
            return False
        if event.room_sequence > 0:
            self.last_host_sequence = event.room_sequence
        return True

    def apply_snapshot(self, payload: dict):
        players_data = payload.get("players", [])
        self.players = []
        for p in players_data:
            self.players.append(PlayerPublicStatus(
                character_id=p.get("character_id", ""),
                player_name=p.get("player_name", ""),
                hp=p.get("hp", 0),
                hp_max=p.get("hp_max", 0),
                san=p.get("san", 0),
                san_max=p.get("san_max", 0),
                mp=p.get("mp", 0),
                mp_max=p.get("mp_max", 0),
                luck=p.get("luck", 0),
                status_tags=p.get("status_tags", []),
            ))
        if "scene_image_url" in payload:
            self.current_scene_image_url = payload["scene_image_url"]
        seq = payload.get("host_sequence", 0)
        if seq > 0:
            self.last_host_sequence = seq

    def apply_public_status_delta(self, payload: dict):
        char_id = payload.get("character_id", "")
        player = next((p for p in self.players if p.character_id == char_id), None)
        if not player:
            logger.warning("Host %s status_delta for unknown char %s", self.room_id, char_id)
            return
        for field in ("hp", "hp_max", "san", "san_max", "mp", "mp_max", "luck"):
            if field in payload:
                setattr(player, field, payload[field])
        if "status_tags" in payload:
            player.status_tags = payload["status_tags"]

    def set_scene_image(self, url: str | None):
        self.current_scene_image_url = url

    def append_chat_message(self, msg: dict):
        self.chat_messages.append(msg)
        if len(self.chat_messages) > MAX_CHAT_MESSAGES:
            self.chat_messages = self.chat_messages[-MAX_CHAT_MESSAGES:]

    def apply_atmosphere(self, payload: dict):
        cmd = AtmosphereCommand(**payload)
        if cmd.bgm is not None:
            self.atmosphere["bgm"] = cmd.bgm
        if cmd.sfx:
            self.atmosphere["sfx_queue"].extend(cmd.sfx)
        if cmd.visual is not None:
            self.atmosphere["visual"] = cmd.visual

    def set_engine_state(self, state: str):
        self.engine_state = state

    def enqueue_transaction(self, tx: RevealTransaction):
        if tx.priority == "urgent":
            self.urgent_queue.append(tx)
        else:
            self.normal_queue.append(tx)

    def pop_next_transaction(self) -> RevealTransaction | None:
        if self.urgent_queue:
            return self.urgent_queue.pop(0)
        if self.normal_queue:
            return self.normal_queue.pop(0)
        return None

    def start_transaction(self, tx: RevealTransaction):
        self.active_transaction_id = tx.transaction_id
        self.active_transaction = tx
        self.current_step_index = 0
        if tx.audio_action:
            self.pending_audio_action = tx.audio_action

    def advance_step(self) -> TransactionStep | None:
        if not self.active_transaction:
            return None
        if self.current_step_index >= len(self.active_transaction.steps):
            return None
        step = self.active_transaction.steps[self.current_step_index]
        self.current_step_index += 1
        return step

    def consume_pending_audio_action(self) -> str | None:
        action = self.pending_audio_action
        self.pending_audio_action = None
        return action

    def complete_transaction(self):
        self.active_transaction_id = None
        self.active_transaction = None
        self.current_step_index = 0
        self.current_roll_event = None

    def add_delayed_event(self, event: dict):
        self.delayed_events.append(event)

    def pop_ready_events(self, step_index: int) -> list[dict]:
        ready = [e for e in self.delayed_events if e.get("execute_after_step", 0) <= step_index]
        self.delayed_events = [e for e in self.delayed_events if e.get("execute_after_step", 0) > step_index]
        return ready

    def flush_all_delayed(self) -> list[dict]:
        ready = list(self.delayed_events)
        self.delayed_events = []
        return ready

    def preempt_for_urgent(self, urgent_tx: RevealTransaction):
        if self.active_transaction:
            self.interrupted_transaction = self.active_transaction
            self.interrupted_step_index = self.current_step_index
        self.active_transaction_id = urgent_tx.transaction_id
        self.active_transaction = urgent_tx
        self.current_step_index = 0

    def resume_interrupted(self) -> RevealTransaction | None:
        tx = self.interrupted_transaction
        step_idx = self.interrupted_step_index
        self.interrupted_transaction = None
        self.interrupted_step_index = 0
        if tx:
            self.active_transaction_id = tx.transaction_id
            self.active_transaction = tx
            self.current_step_index = step_idx
        return tx

    def cancel_interrupted(self):
        self.interrupted_transaction = None
        self.interrupted_step_index = 0

    def reset(self):
        self.current_scene_image_url = None
        self.chat_messages = []
        self.current_roll_event = None
        self.normal_queue = []
        self.urgent_queue = []
        self.active_transaction_id = None
        self.active_transaction = None
        self.current_step_index = 0
        self.interrupted_transaction = None
        self.interrupted_step_index = 0
        self.last_host_sequence = 0
        self.atmosphere = {"bgm": None, "sfx_queue": [], "visual": None}
        self.players = []
        self.engine_state = "idle"
        self.is_paused = False
        self.delayed_events = []
        self.pending_audio_action = None

    def save_state(self, db_conn):
        """Persist current state to database."""
        state = {
            "current_scene_image_url": self.current_scene_image_url,
            "chat_messages": self.chat_messages[-50:],
            "atmosphere": self.atmosphere,
            "engine_state": self.engine_state,
            "is_paused": self.is_paused,
            "last_host_sequence": self.last_host_sequence,
            "players": [
                {
                    "character_id": p.character_id,
                    "player_name": p.player_name,
                    "hp": p.hp, "hp_max": p.hp_max,
                    "san": p.san, "san_max": p.san_max,
                    "mp": p.mp, "mp_max": p.mp_max,
                    "luck": p.luck, "status_tags": p.status_tags,
                }
                for p in self.players
            ],
            "delayed_events": self.delayed_events,
        }
        db_conn.execute(
            """INSERT INTO host_states (room_id, state, updated_at)
               VALUES (?, ?, NOW())
               ON CONFLICT (room_id) DO UPDATE SET state = EXCLUDED.state, updated_at = NOW()""",
            (self.room_id, json.dumps(state)),
        )

    @staticmethod
    def load_state(room_id: str, db_conn) -> dict | None:
        """Load persisted state from database."""
        row = db_conn.execute(
            "SELECT state FROM host_states WHERE room_id = ?", (room_id,)
        ).fetchone()
        if row:
            return row["state"] if isinstance(row["state"], dict) else json.loads(row["state"])
        return None

    def restore_from_db(self, db_conn):
        """Restore state from database if available."""
        state = self.load_state(self.room_id, db_conn)
        if not state:
            return
        self.current_scene_image_url = state.get("current_scene_image_url")
        self.chat_messages = state.get("chat_messages", [])
        self.atmosphere = state.get("atmosphere", {"bgm": None, "sfx_queue": [], "visual": None})
        self.engine_state = state.get("engine_state", "idle")
        self.is_paused = state.get("is_paused", False)
        self.last_host_sequence = state.get("last_host_sequence", 0)
        self.players = [PlayerPublicStatus(**p) for p in state.get("players", [])]
        self.delayed_events = state.get("delayed_events", [])

    def get_hud(self) -> HostHUD:
        return HostHUD(
            room_id=self.room_id,
            players=self.players,
            scene_image_url=self.current_scene_image_url,
            engine_state=self.engine_state,
            queue_status={
                "normal": len(self.normal_queue),
                "urgent": len(self.urgent_queue),
            },
            audio_action=self.pending_audio_action,
        )
