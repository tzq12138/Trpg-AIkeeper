"""StateService — unified game-state persistence layer for AI-Keeper TRPG.

Contract:
- All writes in apply_change() are sequenced before a single conn.commit().
- WebSocket push is fire-and-forget; push failure does NOT roll back persistence.
- Old write paths continue to work; this is an additive layer.
- Phase A: character mutations + scene state + pass-through for map/clue/inventory.
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..models import (
    StateChangeSet, CharacterMutationItem, SceneChange,
)
from ..events.event_log import EventLog
from ..campaign_archive import ensure_campaign_writable
from .projection import ProjectionDispatcher

logger = logging.getLogger(__name__)

MUTATION_PATH_HANDLERS: dict[str, str] = {
    "/character/hp": "hp",
    "/character/san": "san",
    "/character/mp": "mp",
    "/character/luck": "luck",
    "/character/hp_max": "hp_max",
    "/character/san_max": "san_max",
    "/character/mp_max": "mp_max",
}

CLAMP_FIELDS = {"hp", "san", "mp"}


def _json_val(value: Any) -> dict | list:
    if value is None:
        return {}
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
    return value


def _ensure_json(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _runtime_version(conn, room_id: str, character_id: str) -> int | None:
    row = conn.execute(
        "SELECT version FROM character_runtime_state "
        "WHERE room_id = %s AND character_id = %s",
        (room_id, character_id),
    ).fetchone()
    return int(row["version"]) if row else None


def build_action_conflict_guard(
    conn,
    *,
    room_id: str,
    actor_character_id: str,
    intent_type: str,
    params: dict[str, Any],
    base_state_version: int,
) -> dict[str, Any]:
    """Capture only authoritative state that can change this action's meaning."""

    room = conn.execute(
        "SELECT state_version, risk_contract_hash FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    scene = conn.execute(
        "SELECT current_scene, version FROM room_scene_state WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    actor = conn.execute(
        "SELECT status FROM characters WHERE character_id = %s AND room_id = %s",
        (actor_character_id, room_id),
    ).fetchone()
    resources: list[dict[str, Any]] = []
    keys = {f"actor:{room_id}:{actor_character_id}"}
    resources.append(
        {
            "kind": "actor",
            "characterId": actor_character_id,
            "status": actor.get("status") if actor else None,
            "version": _runtime_version(conn, room_id, actor_character_id),
        }
    )

    item_id = str(params.get("itemId") or "").strip()
    validation_error = None
    if item_id:
        item = conn.execute(
            "SELECT id, character_id, quantity, version FROM inventory "
            "WHERE id = %s AND room_id = %s AND character_id = %s",
            (item_id, room_id, actor_character_id),
        ).fetchone()
        if item:
            keys.add(f"item:{room_id}:{item_id}")
            resources.append(
                {
                    "kind": "inventory",
                    "itemId": item_id,
                    "characterId": actor_character_id,
                    "quantity": int(item.get("quantity") or 0),
                    "version": int(item.get("version") or 0),
                }
            )
        elif intent_type in {"use_item", "show_item"}:
            validation_error = "resource_not_available"

    target_id = str(params.get("targetId") or "").strip()
    if target_id and target_id != actor_character_id and intent_type in {
        "combat_action",
        "chase_action",
        "skill_check",
        "use_item",
    }:
        target = conn.execute(
            "SELECT status FROM characters WHERE character_id = %s AND room_id = %s",
            (target_id, room_id),
        ).fetchone()
        if target:
            keys.add(f"target:{room_id}:{target_id}")
            resources.append(
                {
                    "kind": "target",
                    "characterId": target_id,
                    "status": target.get("status"),
                    "version": _runtime_version(conn, room_id, target_id),
                }
            )
        else:
            encounter_target = conn.execute(
                "SELECT participants.character_id, participants.version "
                "FROM encounter_participants AS participants "
                "JOIN encounters ON encounters.encounter_id = participants.encounter_id "
                "WHERE encounters.room_id = %s AND participants.character_id = %s "
                "AND encounters.status IN ('suggested', 'active') "
                "ORDER BY encounters.created_at DESC LIMIT 1",
                (room_id, target_id),
            ).fetchone()
            if encounter_target:
                keys.add(f"target:{room_id}:{target_id}")
                resources.append(
                    {
                        "kind": "encounter_target",
                        "characterId": target_id,
                        "version": int(encounter_target.get("version") or 0),
                    }
                )

    decision_kind = str(params.get("groupDecisionKind") or "").strip()
    if decision_kind in {"shared_resource", "ending", "abandon_ally", "risk_expansion"}:
        keys.add(f"shared:{room_id}:{decision_kind}")

    same_turn_scene_target = ""
    if intent_type == "move":
        keys.add(f"scene:{room_id}")
        same_turn_scene_target = str(params.get("targetNodeId") or "").strip()

    return {
        "version": 1,
        "roomId": room_id,
        "baseStateVersion": int(base_state_version or 0),
        "capturedStateVersion": int(room.get("state_version") or 0) if room else 0,
        "riskContractHash": room.get("risk_contract_hash") if room else None,
        "scene": (
            {
                "currentScene": scene.get("current_scene") or "",
                "version": int(scene.get("version") or 0),
            }
            if scene
            else None
        ),
        "sameTurnSceneTarget": same_turn_scene_target or None,
        "keys": sorted(keys),
        "resources": resources,
        "validationError": validation_error,
    }


def _advisory_lock_id(key: str) -> int:
    return int.from_bytes(
        hashlib.sha256(key.encode("utf-8")).digest()[:8],
        byteorder="big",
        signed=True,
    )


def acquire_action_conflict_locks(transaction, guard: dict[str, Any]) -> None:
    """Acquire shared resource locks in stable order to avoid deadlocks."""

    raw_keys = guard.get("keys") if isinstance(guard, dict) else None
    keys = sorted({str(key) for key in raw_keys or [] if str(key)})
    for key in keys:
        transaction.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            (_advisory_lock_id(key),),
        ).fetchone()


def validate_action_conflict_guard(
    conn,
    guard: dict[str, Any],
    *,
    allow_same_turn_scene_drift: bool = False,
) -> str | None:
    """Revalidate semantic/resource snapshots without using global version equality."""

    if not isinstance(guard, dict) or guard.get("version") != 1:
        return "conflict_guard_invalid"
    room_id = str(guard.get("roomId") or "")
    if not room_id:
        return "conflict_guard_invalid"
    room = conn.execute(
        "SELECT risk_contract_hash FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    if not room:
        return "room_context_missing"
    if room.get("risk_contract_hash") != guard.get("riskContractHash"):
        return "risk_context_changed"

    if not allow_same_turn_scene_drift:
        scene = conn.execute(
            "SELECT current_scene, version FROM room_scene_state WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        current_scene = (
            {
                "currentScene": scene.get("current_scene") or "",
                "version": int(scene.get("version") or 0),
            }
            if scene
            else None
        )
        if current_scene != guard.get("scene"):
            return "scene_context_changed"
    else:
        scene = conn.execute(
            "SELECT current_scene, version FROM room_scene_state WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        current_scene_id = str(scene.get("current_scene") or "") if scene else ""
        same_turn_target = str(guard.get("sameTurnSceneTarget") or "")
        if (
            ({
                "currentScene": current_scene_id,
                "version": int(scene.get("version") or 0),
            } if scene else None)
            != guard.get("scene")
            and (not same_turn_target or current_scene_id != same_turn_target)
        ):
            return "scene_context_changed"

    for snapshot in guard.get("resources") or []:
        if not isinstance(snapshot, dict):
            return "conflict_guard_invalid"
        kind = snapshot.get("kind")
        if kind == "inventory":
            row = conn.execute(
                "SELECT quantity, version FROM inventory "
                "WHERE id = %s AND room_id = %s AND character_id = %s",
                (
                    snapshot.get("itemId"),
                    room_id,
                    snapshot.get("characterId"),
                ),
            ).fetchone()
            current = (
                {
                    "quantity": int(row.get("quantity") or 0),
                    "version": int(row.get("version") or 0),
                }
                if row
                else None
            )
            expected = {
                "quantity": snapshot.get("quantity"),
                "version": snapshot.get("version"),
            }
            if current != expected:
                return "resource_conflict"
        elif kind in {"actor", "target"}:
            character_id = str(snapshot.get("characterId") or "")
            row = conn.execute(
                "SELECT status FROM characters WHERE character_id = %s AND room_id = %s",
                (character_id, room_id),
            ).fetchone()
            current = {
                "status": row.get("status") if row else None,
                "version": _runtime_version(conn, room_id, character_id),
            }
            expected = {
                "status": snapshot.get("status"),
                "version": snapshot.get("version"),
            }
            if current != expected:
                return "actor_state_changed" if kind == "actor" else "target_state_changed"
        elif kind == "encounter_target":
            row = conn.execute(
                "SELECT participants.version FROM encounter_participants AS participants "
                "JOIN encounters ON encounters.encounter_id = participants.encounter_id "
                "WHERE encounters.room_id = %s AND participants.character_id = %s "
                "AND encounters.status IN ('suggested', 'active') "
                "ORDER BY encounters.created_at DESC LIMIT 1",
                (room_id, snapshot.get("characterId")),
            ).fetchone()
            if not row or int(row.get("version") or 0) != int(snapshot.get("version") or 0):
                return "target_state_changed"
    return None


class StateService:
    """Unified game-state persistence layer.

    Usage:
        svc = StateService(conn, dispatcher=dispatcher)
        result = svc.apply_change(room_id, actor, changes, reason="Turn resolved")
    """

    def __init__(self, conn, dispatcher=None, event_log=None):
        self.conn = conn
        self.dispatcher = dispatcher or ProjectionDispatcher(conn)
        self.event_log = event_log or EventLog(conn)

    # ── Public API ────────────────────────────────────────────────────

    def apply_change(
        self,
        room_id: str,
        actor: dict[str, Any],
        changes: StateChangeSet,
        reason: str = "",
        transaction=None,
    ) -> dict[str, Any]:
        """Apply a set of state changes in one logical unit.

        Returns:
            {"room_id": str, "state_version": int, "base_state_version": int,
             "applied": {...}, "event_refs": [...], "no_op": bool}
        """
        if transaction is not None:
            worker = StateService(
                transaction,
                dispatcher=self.dispatcher,
                event_log=EventLog(transaction),
            )
            return worker._apply_change(room_id, actor, changes, reason, commit=False)
        if hasattr(self.conn, "transaction"):
            with self.conn.transaction() as tx:
                worker = StateService(
                    tx,
                    dispatcher=self.dispatcher,
                    event_log=EventLog(tx),
                )
                return worker._apply_change(
                    room_id,
                    actor,
                    changes,
                    reason,
                    commit=False,
                )
        return self._apply_change(room_id, actor, changes, reason, commit=True)

    def _apply_change(
        self,
        room_id: str,
        actor: dict[str, Any],
        changes: StateChangeSet,
        reason: str,
        *,
        commit: bool,
    ) -> dict[str, Any]:
        self._validate_room(room_id)

        base_version = self._read_room_version(room_id)
        applied: dict[str, Any] = {}
        event_seqs: list[int] = []
        has_changes = False

        # 1. Character mutations
        if changes.character_mutations:
            result = self._apply_character_mutations(
                room_id, changes.character_mutations,
            )
            if result:
                applied["character_mutations"] = result
                has_changes = True
                seq = self._write_state_patch_event(room_id, actor, changes)
                if seq:
                    event_seqs.append(seq)

        # 2. Scene changes
        if changes.scene_changes:
            self._apply_scene_changes(room_id, changes.scene_changes)
            applied["scene_changes"] = True
            has_changes = True
            seq = self.event_log.log_event(
                room_id, "s2c_scene_sync", "party",
                {
                    "actionId": actor.get("action_id", ""),
                    "currentScene": changes.scene_changes.current_scene or "",
                    "stateVersion": base_version + 1,
                },
                commit=False,
            )
            event_seqs.append(seq)

        # 3. Map changes (pass-through)
        if changes.map_changes:
            self._apply_map_changes(room_id, changes.map_changes, actor)
            applied["map_changes"] = True
            has_changes = True

        # 4. Clue changes
        if changes.clue_changes:
            self._apply_clue_changes(room_id, changes.clue_changes, actor)
            applied["clue_changes"] = len(changes.clue_changes)
            has_changes = True

        # 5. Inventory changes
        if changes.inventory_changes:
            self._apply_inventory_changes(room_id, changes.inventory_changes, actor)
            applied["inventory_changes"] = len(changes.inventory_changes)
            has_changes = True

        # 6. Encounter changes (NOT yet supported through StateService)
        if changes.encounter_changes:
            raise ValueError(
                "encounter_changes are not supported through StateService.apply_change(). "
                "Use encounter_persistence module directly."
            )

        # 7. Room-level changes
        if changes.room_changes:
            self._apply_room_changes(room_id, changes.room_changes)
            applied["room_changes"] = True
            has_changes = True

        # Only bump version if there were actual changes
        if not has_changes:
            if commit:
                self.conn.commit()
            return {
                "room_id": room_id,
                "base_state_version": base_version,
                "state_version": base_version,
                "applied": applied,
                "event_refs": event_seqs,
                "no_op": True,
            }

        new_version = self._bump_room_version(room_id)
        if commit:
            self.conn.commit()

        return {
            "room_id": room_id,
            "base_state_version": base_version,
            "state_version": new_version,
            "applied": applied,
            "event_refs": event_seqs,
            "no_op": False,
        }

    def initialize_character_state(
        self,
        character_id: str,
        room_id: str,
        *,
        commit: bool = True,
        transaction=None,
    ) -> dict[str, Any] | None:
        """Create runtime state + profile from characters.xlsx_data. Idempotent."""
        if transaction is not None:
            worker = StateService(
                transaction,
                dispatcher=self.dispatcher,
                event_log=EventLog(transaction),
            )
            return worker.initialize_character_state(
                character_id,
                room_id,
                commit=False,
            )
        if commit and hasattr(self.conn, "transaction"):
            with self.conn.transaction() as tx:
                worker = StateService(
                    tx,
                    dispatcher=self.dispatcher,
                    event_log=EventLog(tx),
                )
                return worker.initialize_character_state(
                    character_id,
                    room_id,
                    commit=False,
                )

        existing = self.conn.execute(
            "SELECT * FROM character_runtime_state WHERE character_id = %s AND room_id = %s",
            (character_id, room_id),
        ).fetchone()
        if existing:
            return dict(existing)

        char = self.conn.execute(
            "SELECT * FROM characters WHERE character_id = %s",
            (character_id,),
        ).fetchone()
        if not char:
            logger.warning("Character %s not found for state init", character_id)
            return None

        ensure_campaign_writable(self.conn, room_id)
        existing = self.conn.execute(
            "SELECT * FROM character_runtime_state WHERE character_id = %s AND room_id = %s",
            (character_id, room_id),
        ).fetchone()
        if existing:
            return dict(existing)

        char = dict(char)
        xlsx = _json_val(char.get("xlsx_data")) or {}

        # Create profile if account exists
        profile_id = None
        account_id = char.get("account_id")
        if account_id:
            profile_id = self._upsert_profile(account_id, xlsx)
            self.conn.execute(
                "UPDATE characters SET profile_id = %s WHERE character_id = %s",
                (profile_id, character_id),
            )

        runtime = {
            "character_id": character_id,
            "room_id": room_id,
            "profile_id": profile_id,
            "hp": int(xlsx.get("hp", 0)),
            "hp_max": int(xlsx.get("max_hp", xlsx.get("hp", 0))),
            "san": int(xlsx.get("san", 0)),
            "san_max": int(xlsx.get("max_san", xlsx.get("san", 0))),
            "mp": int(xlsx.get("mp", 0)),
            "mp_max": int(xlsx.get("max_mp", xlsx.get("mp", 0))),
            "luck": int(xlsx.get("luck", 0)),
            "status_tags": [],
            "temp_modifiers": {},
            "visibility": "visible",
            "version": 1,
        }
        self.conn.execute(
            """INSERT INTO character_runtime_state
               (character_id, room_id, profile_id, hp, hp_max, san, san_max,
                mp, mp_max, luck, status_tags, temp_modifiers, visibility, version)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                runtime["character_id"], runtime["room_id"], runtime["profile_id"],
                runtime["hp"], runtime["hp_max"], runtime["san"], runtime["san_max"],
                runtime["mp"], runtime["mp_max"], runtime["luck"],
                _ensure_json(runtime["status_tags"]),
                _ensure_json(runtime["temp_modifiers"]),
                runtime["visibility"], runtime["version"],
            ),
        )
        if commit:
            self.conn.commit()
        logger.info("StateService: initialized runtime state for %s in %s (hp=%s san=%s)",
                     character_id, room_id, runtime["hp"], runtime["san"])
        return runtime

    def get_runtime_state(self, character_id: str, room_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM character_runtime_state WHERE character_id = %s AND room_id = %s",
            (character_id, room_id),
        ).fetchone()
        return dict(row) if row else None

    def get_scene_state(self, room_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM room_scene_state WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        return dict(row) if row else None

    # ── Internal: Validation & Version ───────────────────────────────

    def _validate_room(self, room_id: str):
        room = self.conn.execute(
            "SELECT status FROM rooms WHERE room_id = %s FOR UPDATE", (room_id,)
        ).fetchone()
        if not room:
            raise ValueError(f"Room {room_id} not found")
        if str(room.get("status") or "") in {"completed", "archived"}:
            from ..campaign_archive import CampaignReadOnlyError

            raise CampaignReadOnlyError("campaign_completed_read_only")

    def _read_room_version(self, room_id: str) -> int:
        """Read current rooms.state_version without bumping."""
        row = self.conn.execute(
            "SELECT state_version FROM rooms WHERE room_id = %s", (room_id,)
        ).fetchone()
        return row["state_version"] if row else 0

    def _bump_room_version(self, room_id: str) -> int:
        row = self.conn.execute(
            "UPDATE rooms SET state_version = state_version + 1 WHERE room_id = %s RETURNING state_version",
            (room_id,),
        ).fetchone()
        return row["state_version"] if row else 0

    # ── Internal: Character Mutations ─────────────────────────────────

    def _apply_character_mutations(
        self, room_id: str, items: list[CharacterMutationItem],
    ) -> int:
        count = 0
        for item in items:
            runtime = self._get_or_create_runtime(item.character_id, room_id)
            if not runtime:
                continue

            changed = False
            for mutation in item.mutations:
                if self._apply_one_mutation(runtime, mutation):
                    changed = True

            if changed:
                runtime["version"] = runtime.get("version", 0) + 1
                self._persist_runtime_state(runtime)
                count += 1

        return count

    def _get_or_create_runtime(self, character_id: str, room_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM character_runtime_state WHERE character_id = %s AND room_id = %s",
            (character_id, room_id),
        ).fetchone()
        if row:
            return dict(row)
        # Lazy-init from xlsx_data
        return self.initialize_character_state(
            character_id,
            room_id,
            commit=hasattr(self.conn, "commit"),
        )

    def _apply_one_mutation(self, runtime: dict, mutation: dict) -> bool:
        path = mutation.get("path", "")
        op = mutation.get("op", "replace")
        value = mutation.get("value")

        # Direct field mutations
        field = MUTATION_PATH_HANDLERS.get(path)
        if field and op == "replace":
            if field in CLAMP_FIELDS:
                max_field = f"{field}_max"
                new_val = max(0, min(runtime.get(max_field, 999), int(value or 0)))
            else:
                new_val = max(0, int(value or 0))
            if runtime.get(field) != new_val:
                runtime[field] = new_val
                return True
            return False

        # Status tag mutations
        if "status_tag" in path:
            tag = str(value) if value else ""
            tags = list(runtime.get("status_tags", []) or [])
            if isinstance(tags, str):
                tags = json.loads(tags) if tags else []
            if op == "add" and tag and tag not in tags:
                tags.append(tag)
                runtime["status_tags"] = tags
                return True
            elif op == "remove" and tag in tags:
                tags.remove(tag)
                runtime["status_tags"] = tags
                return True
            return False

        # Temp modifier mutations
        if "temp_modifier" in path and op == "replace":
            modifiers = dict(runtime.get("temp_modifiers", {}) or {})
            if isinstance(modifiers, str):
                modifiers = json.loads(modifiers) if modifiers else {}
            mod_key = path.rsplit("/", 1)[-1]
            if modifiers.get(mod_key) != value:
                modifiers[mod_key] = value
                runtime["temp_modifiers"] = modifiers
                return True
            return False

        # distance_band_delta (encounter-related, store in temp_modifiers)
        if "distance_band_delta" in path:
            key = "distance_band_delta"
            mods = dict(runtime.get("temp_modifiers", {}) or {})
            if isinstance(mods, str):
                mods = json.loads(mods) if mods else {}
            cur = mods.get(key, 0)
            new_val = cur + int(value or 0)
            if cur != new_val:
                mods[key] = new_val
                runtime["temp_modifiers"] = mods
                return True
            return False

        logger.debug("Unhandled mutation path=%s op=%s", path, op)
        return False

    def _persist_runtime_state(self, runtime: dict):
        self.conn.execute(
            """UPDATE character_runtime_state
               SET hp = %s, hp_max = %s, san = %s, san_max = %s,
                   mp = %s, mp_max = %s, luck = %s,
                   status_tags = %s, temp_modifiers = %s,
                   visibility = %s, version = %s, updated_at = NOW()
               WHERE character_id = %s AND room_id = %s""",
            (
                runtime["hp"], runtime["hp_max"], runtime["san"], runtime["san_max"],
                runtime["mp"], runtime["mp_max"], runtime["luck"],
                _ensure_json(runtime.get("status_tags", [])),
                _ensure_json(runtime.get("temp_modifiers", {})),
                runtime.get("visibility", "visible"),
                runtime["version"],
                runtime["character_id"], runtime["room_id"],
            ),
        )

    # ── Internal: Profile ─────────────────────────────────────────────

    def _upsert_profile(self, account_id: str, xlsx: dict) -> str:
        profile_id = str(uuid.uuid4())[:8]
        self.conn.execute(
            """INSERT INTO character_profiles
               (profile_id, account_id, name, occupation, attributes, skills,
                background, backstory, version)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)""",
            (
                profile_id, account_id,
                xlsx.get("name", ""), xlsx.get("occupation", ""),
                _ensure_json(xlsx.get("attributes", {})),
                _ensure_json(xlsx.get("skills", {})),
                xlsx.get("background", ""),
                _ensure_json(xlsx.get("backstory", {})),
            ),
        )
        return profile_id

    # ── Internal: Scene Changes ───────────────────────────────────────

    def _apply_scene_changes(self, room_id: str, changes: SceneChange):
        existing = self.conn.execute(
            "SELECT * FROM room_scene_state WHERE room_id = %s", (room_id,)
        ).fetchone()

        if existing:
            state = dict(existing)
            visited = list(_json_val(state.get("visited_scenes")) or [])
            triggers = list(_json_val(state.get("triggered_triggers")) or [])
            facts = list(_json_val(state.get("public_facts")) or [])
            variables = dict(_json_val(state.get("scene_variables")) or {})
            version = state.get("version", 0) + 1
            current = state.get("current_scene", "")
            bgm = state.get("current_bgm", "")
            asset_url = state.get("current_asset_url", "")
        else:
            visited, triggers, facts, variables = [], [], [], {}
            version = 1
            current = ""
            bgm = ""
            asset_url = ""

        if changes.current_scene is not None:
            current = changes.current_scene
            if current and current not in visited:
                visited.append(current)

        if changes.visited_scenes_add:
            for s in changes.visited_scenes_add:
                if s not in visited:
                    visited.append(s)

        if changes.trigger_fired and changes.trigger_fired not in triggers:
            triggers.append(changes.trigger_fired)

        if changes.public_facts_add:
            for f in changes.public_facts_add:
                if f not in facts:
                    facts.append(f)

        if changes.variable_set:
            variables.update(changes.variable_set)

        if changes.bgm is not None:
            bgm = changes.bgm
        if changes.asset_url is not None:
            asset_url = changes.asset_url

        self.conn.execute(
            """INSERT INTO room_scene_state
               (room_id, current_scene, visited_scenes, triggered_triggers,
                public_facts, scene_variables, current_bgm, current_asset_url, version)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (room_id) DO UPDATE SET
               current_scene = EXCLUDED.current_scene,
               visited_scenes = EXCLUDED.visited_scenes,
               triggered_triggers = EXCLUDED.triggered_triggers,
               public_facts = EXCLUDED.public_facts,
               scene_variables = EXCLUDED.scene_variables,
               current_bgm = EXCLUDED.current_bgm,
               current_asset_url = EXCLUDED.current_asset_url,
               version = EXCLUDED.version,
               updated_at = NOW()""",
            (room_id, current, _ensure_json(visited), _ensure_json(triggers),
             _ensure_json(facts), _ensure_json(variables), bgm, asset_url, version),
        )

    # ── Internal: Map Changes ─────────────────────────────────────────

    def _apply_map_changes(self, room_id: str, changes, actor: dict):
        from ..map_persistence import (
            mark_node_explored, host_set_node_visible,
            set_character_position,
        )
        mc = changes if isinstance(changes, dict) else changes.model_dump()
        if mc.get("nodeExplored"):
            mark_node_explored(self.conn, room_id, mc["nodeExplored"])
        if mc.get("nodeHidden") is not None:
            host_set_node_visible(self.conn, room_id, mc["nodeHidden"], visible=False)
        if mc.get("nodeRevealed") is not None:
            host_set_node_visible(self.conn, room_id, mc["nodeRevealed"], visible=True)
        if mc.get("positionSet"):
            for char_id, node_id in mc["positionSet"].items():
                set_character_position(self.conn, char_id, room_id, node_id)

    # ── Internal: Clue Changes ────────────────────────────────────────

    def _apply_clue_changes(self, room_id: str, changes: list, actor: dict):
        SAFE_DEFAULT = "玩家分享了一条线索，但未公开完整内容。"
        for item in changes:
            cc = item if isinstance(item, dict) else item.model_dump()
            clue_id = cc.get("clueId", "")
            if not clue_id:
                continue
            if cc.get("shared") and cc.get("sharedBy"):
                public_version = cc.get("publicVersion", "") or cc.get("public_version", "")
                if not public_version:
                    public_version = SAFE_DEFAULT
                # Forward to clue sharing logic
                self.conn.execute(
                    "UPDATE clues SET is_private = FALSE WHERE clue_id = %s AND room_id = %s",
                    (clue_id, room_id),
                )
                self.conn.execute(
                    "INSERT INTO clue_shares (share_id, clue_id, shared_by, public_version, room_id) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (str(uuid.uuid4()), clue_id, cc["sharedBy"], public_version, room_id),
                )

    # ── Internal: Inventory Changes ───────────────────────────────────

    def _apply_inventory_changes(self, room_id: str, changes: list, actor: dict):
        for item in changes:
            ic = item if isinstance(item, dict) else item
            if ic.get("itemAdd"):
                item_data = ic["itemAdd"]
                item_data.setdefault("id", str(uuid.uuid4()))
                self.conn.execute(
                    """INSERT INTO inventory (id, character_id, room_id, name,
                       description, quantity, is_secret, source)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        item_data["id"],
                        ic.get("characterId", actor.get("character_id", "")),
                        room_id,
                        item_data.get("name", ""),
                        item_data.get("description", ""),
                        item_data.get("quantity", 1),
                        item_data.get("isSecret", False),
                        item_data.get("source", ""),
                    ),
                )
            if ic.get("itemRemove"):
                self.conn.execute(
                    "DELETE FROM inventory WHERE id = %s AND character_id = %s",
                    (ic["itemRemove"], ic.get("characterId", actor.get("character_id", ""))),
                )

    # ── Internal: Room Changes ────────────────────────────────────────

    def _apply_room_changes(self, room_id: str, changes: dict):
        rc = changes if isinstance(changes, dict) else changes.model_dump()
        set_parts = []
        params = []
        if "status" in rc:
            set_parts.append("status = %s")
            params.append(rc["status"])
        if "spoiler_level" in rc or "spoilerLevel" in rc:
            set_parts.append("spoiler_level = %s")
            params.append(rc.get("spoiler_level", rc.get("spoilerLevel")))
        if set_parts:
            params.append(room_id)
            self.conn.execute(
                f"UPDATE rooms SET {', '.join(set_parts)} WHERE room_id = %s",
                tuple(params),
            )

    # ── Internal: Event Writing ──────────────────────────────────────

    def _write_state_patch_event(
        self, room_id: str, actor: dict, changes: StateChangeSet,
    ) -> int | None:
        patches = []
        for item in changes.character_mutations:
            for m in item.mutations:
                patches.append({
                    "characterId": item.character_id,
                    "op": m.get("op", "replace"),
                    "path": m.get("path", ""),
                    "value": m.get("value"),
                    "permanent": item.permanent,
                })
        if not patches:
            return None
        # Read current version for trace (new version is bumped after changes)
        base_ver = self._read_room_version(room_id)
        return self.event_log.log_event(
            room_id, "s2c_state_patch", "party",
            {
                "actionId": actor.get("action_id", ""),
                "schemaVersion": 1,
                "baseStateVersion": base_ver,
                "stateVersion": base_ver + 1,  # post-bump version (applied later in apply_change)
                "patches": patches,
            },
            commit=False,
        )
