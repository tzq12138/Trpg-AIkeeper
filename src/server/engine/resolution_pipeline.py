import json
import re
import uuid
import logging
from datetime import datetime, timezone
from typing import Any

from ..ai.mechanic_compiler import MechanicCompiler
from ..models import MechanicCompileResult, PlayerIntent, ResolutionResult
from .projection import ProjectionDispatcher
from .rule_executor import RuleExecutor

logger = logging.getLogger(__name__)


class ResolutionPipeline:
    def __init__(
        self,
        conn,
        compiler: MechanicCompiler | None = None,
        dispatcher=None,
        rule_executor: RuleExecutor | None = None,
        spoiler_guard=None,
        gateway=None,
        state_service=None,
    ):
        self.conn = conn
        self.compiler = compiler or MechanicCompiler(api_key="")
        self.dispatcher = dispatcher or ProjectionDispatcher(conn)
        self.rule_executor = rule_executor or RuleExecutor()
        self.spoiler_guard = spoiler_guard
        self.gateway = gateway
        self.state_service = state_service

    async def resolve_queued_room(self, room_id: str) -> dict[str, Any]:
        rows = self.conn.execute(
            "SELECT * FROM actions WHERE room_id = %s AND status = %s ORDER BY created_at",
            (room_id, "queued"),
        ).fetchall()
        results = []
        for action in rows:
            results.append(await self.resolve_action(action["action_id"]))

        # Auto-checkpoint after turn resolution
        if results:
            try:
                from ..events.event_log import EventLog
                EventLog(self.conn).create_checkpoint(room_id, auto=True, reason="Turn resolved")
            except Exception as exc:
                logger.warning("Auto-checkpoint failed after turn resolution room=%s: %s", room_id, exc)

        return {"room_id": room_id, "resolved": len(results), "results": results}

    async def resolve_action(self, action_id: str) -> dict[str, Any]:
        action = self.conn.execute(
            "SELECT * FROM actions WHERE action_id = %s", (action_id,)
        ).fetchone()
        if not action:
            return {"status": "missing", "action_id": action_id}
        if action["status"] == "resolved":
            return {"status": "resolved", "action_id": action_id}
        if action["status"] == "rejected":
            return {"status": "rejected", "action_id": action_id}

        self.conn.execute("UPDATE actions SET status = %s WHERE action_id = %s", ("resolving", action_id))
        self.conn.commit()

        character = self.conn.execute(
            "SELECT * FROM characters WHERE character_id = %s", (action["character_id"],)
        ).fetchone()
        room = self.conn.execute(
            "SELECT * FROM rooms WHERE room_id = %s", (action["room_id"],)
        ).fetchone()
        if not character or not room:
            await self._reject(action, "missing room or character")
            return {"status": "rejected", "action_id": action_id}

        scenario = self._load_scenario(room)
        scenario_assets = self._json_value(scenario.get("scenario_assets") if scenario else None) or {}
        inventory = self.conn.execute(
            "SELECT * FROM inventory WHERE character_id = %s", (action["character_id"],)
        ).fetchall()

        intent = PlayerIntent(
            action_id=action["action_id"],
            intent_type=action["intent_type"],
            declared_intent=action.get("declared_intent") or "",
            params=self._json_value(action.get("params")) or {},
        )

        # ── Pre-resolution validation for move intent ──
        if action["intent_type"] == "move":
            move_err = await self._validate_move(action, intent)
            if move_err:
                await self._reject(action, move_err)
                return {"status": "rejected", "action_id": action_id, "reason": move_err}

        # ── Pre-resolution validation for encounter actions ──
        if action["intent_type"] in ("combat_action", "chase_action", "system_skip"):
            enc_err = await self._validate_encounter_action(action, intent)
            if enc_err:
                await self._reject(action, enc_err)
                return {"status": "rejected", "action_id": action_id, "reason": enc_err}

        try:
            compiled = await self.compiler.compile(intent, scenario or {}, dict(character))
            resolution = await self.rule_executor.execute(
                intent,
                compiled,
                dict(character),
                [dict(i) for i in inventory],
                scenario_assets,
            )
        except Exception as exc:
            await self._reject(action, f"resolution failed: {exc}")
            return {"status": "rejected", "action_id": action_id, "reason": str(exc)}
        resolution.narrative = self._render_fallback_narrative(intent, compiled, resolution, dict(character))

        # For dialogue intents, attempt AI-enriched narrative
        if compiled.triggered_mechanic == "dialogue" and self.gateway:
            enriched = await self._enrich_dialogue_narrative(
                action, dict(character), dict(room), dict(scenario) if scenario else None,
            )
            if enriched:
                resolution.narrative = enriched

        # State version bump is handled by StateService.apply_change() — the single state writer.
        result_payload = resolution.model_dump(by_alias=True)
        self.conn.execute(
            "UPDATE actions SET status = %s, result = %s, completed_at = %s WHERE action_id = %s",
            (
                "resolved",
                json.dumps(result_payload, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
                action_id,
            ),
        )
        self.conn.commit()

        await self._project(action, resolution)

        # ── Persist character mutations via StateService ──
        if resolution.mutations and self.state_service:
            try:
                from ..models import StateChangeSet, CharacterMutationItem
                self.state_service.apply_change(
                    room_id=action["room_id"],
                    actor={
                        "character_id": action["character_id"],
                        "action_id": action["action_id"],
                    },
                    changes=StateChangeSet(
                        characterMutations=[
                            CharacterMutationItem(
                                characterId=action["character_id"],
                                mutations=resolution.mutations,
                            )
                        ]
                    ),
                    reason=f"Action {action['action_id']} resolved",
                )
            except Exception:
                logger.exception(
                    "StateService failed for action %s", action["action_id"]
                )

        # ── Post-resolution map updates for move intent ──
        if action["intent_type"] == "move" and resolution.is_success:
            await self._apply_move_result(action, resolution)

        # ── Post-resolution encounter updates ──
        if action["intent_type"] in ("combat_action", "chase_action", "system_skip") and resolution.is_success:
            await self._apply_encounter_result(action, intent, resolution)

        return {"status": "resolved", "action_id": action_id, "result": result_payload}

    def _load_scenario(self, room: dict[str, Any]) -> dict[str, Any] | None:
        scenario_id = room.get("scenario_id")
        if not scenario_id:
            return None
        row = self.conn.execute(
            "SELECT * FROM scenarios WHERE scenario_id = %s", (scenario_id,)
        ).fetchone()
        return dict(row) if row else None

    async def _reject(self, action: dict[str, Any], reason: str):
        payload = {"reason": reason}
        self.conn.execute(
            "UPDATE actions SET status = %s, result = %s, completed_at = %s WHERE action_id = %s",
            (
                "rejected",
                json.dumps(payload, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
                action["action_id"],
            ),
        )
        self.conn.commit()
        await self.dispatcher.emit(
            action["room_id"],
            "s2c_action_completed",
            "player",
            {"actionId": action["action_id"], "status": "rejected", "reason": reason},
            character_id=action["character_id"],
        )

    async def _project(self, action: dict[str, Any], resolution: ResolutionResult):
        host_steps = []
        for step in resolution.reveal_steps:
            if step.get("kind") == "roll":
                host_steps.append({"kind": "roll", "payload": step})
            else:
                host_steps.append({"kind": "status_delta", "payload": step})
        if resolution.mutations:
            host_steps.append({"kind": "status_delta", "payload": {"mutations": resolution.mutations}})
        host_steps.append({"kind": "narrative_text", "payload": {"text": resolution.narrative}})

        await self.dispatcher.emit(
            action["room_id"],
            "s2c_reveal_transaction",
            "host",
            {
                "transactionId": str(uuid.uuid4()),
                "priority": "normal",
                "steps": host_steps,
                "summaryText": resolution.narrative,
            },
        )
        if resolution.mutations:
            await self.dispatcher.emit(
                action["room_id"],
                "s2c_state_patch",
                "player",
                {
                    "actionId": action["action_id"],
                    "patches": resolution.mutations,
                    "cascadingStateChanges": resolution.cascading_state_changes,
                },
                character_id=action["character_id"],
            )

        # ── SpoilerGuard check on public narrative ──
        public_text = resolution.narrative
        final_text = public_text
        spoiler_status = "none"

        if self.spoiler_guard and public_text:
            room_id = action["room_id"]
            room = self.conn.execute(
                "SELECT * FROM rooms WHERE room_id = %s", (room_id,)
            ).fetchone()
            scenario = self._load_scenario(dict(room)) if room else None
            if scenario:
                scenario_id = scenario.get("scenario_id", "")
                if scenario_id:
                    try:
                        index = self.spoiler_guard.load_index(scenario_id)
                        if index:
                            unlock = self.spoiler_guard.compute_unlock_state(room_id)
                            review = self.spoiler_guard.review(
                                public_text, "party", action["character_id"], unlock, index,
                            )
                            if not review.allowed:
                                # Attempt 1: retry with constraint
                                retry_text = await self._retry_with_constraint(
                                    action, resolution, review.retry_prompt,
                                )
                                if retry_text:
                                    review2 = self.spoiler_guard.review(
                                        retry_text, "party", action["character_id"], unlock, index,
                                    )
                                    if not review2.allowed:
                                        # Attempt 2 failed → fallback
                                        final_text = self.spoiler_guard.get_safe_fallback("general")
                                        spoiler_status = "blocked_fallback"
                                        self.spoiler_guard.log_audit(
                                            room_id, action["action_id"], public_text,
                                            review.violations, 2, "blocked_fallback",
                                            final_text, unlock,
                                        )
                                    else:
                                        final_text = retry_text
                                        spoiler_status = "retry_ok"
                                        self.spoiler_guard.log_audit(
                                            room_id, action["action_id"], public_text,
                                            review.violations, 1, "retry_ok",
                                            final_text, unlock,
                                        )
                                else:
                                    # Retry not available → immediate fallback
                                    final_text = self.spoiler_guard.get_safe_fallback("general")
                                    spoiler_status = "blocked_fallback"
                                    self.spoiler_guard.log_audit(
                                        room_id, action["action_id"], public_text,
                                        review.violations, 0, "blocked_fallback",
                                        final_text, unlock,
                                    )
                    except Exception as e:
                        logger.warning("SpoilerGuard review failed for action %s: %s", action["action_id"], e)

        await self.dispatcher.emit(
            action["room_id"],
            "s2c_public_observation",
            "party",
            {"actionId": action["action_id"], "text": final_text,
             "spoilerStatus": spoiler_status} if spoiler_status != "none" else {"actionId": action["action_id"], "text": final_text},
        )
        await self.dispatcher.emit(
            action["room_id"],
            "s2c_action_completed",
            "player",
            self._action_completed_payload(action, resolution),
            character_id=action["character_id"],
        )

    def _action_completed_payload(
        self, action: dict[str, Any], resolution: ResolutionResult
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "actionId": action["action_id"],
            "status": "resolved",
            "turnId": action.get("turn_id", ""),
            "roomId": action.get("room_id", ""),
            "characterId": action.get("character_id", ""),
        }
        metadata = resolution.metadata or {}
        if resolution.mechanic == "skill_check" or "roll" in metadata:
            skill_name = metadata.get("skill_name") or metadata.get("skillName") or ""
            level = metadata.get("success_level") or metadata.get("level") or ""
            payload.update({
                "skill_name": skill_name,
                "skillName": skill_name,
                "skill_value": metadata.get("skill_value", metadata.get("skillValue")),
                "skillValue": metadata.get("skill_value", metadata.get("skillValue")),
                "roll": metadata.get("roll"),
                "target": metadata.get("target"),
                "difficulty": metadata.get("difficulty"),
                "level": level,
                "success_level": level,
                "successLevel": level,
                "success": resolution.is_success,
            })
        return payload

    async def _retry_with_constraint(
        self, action: dict[str, Any], resolution: ResolutionResult, retry_prompt: str,
    ) -> str | None:
        """Attempt AI retry with spoiler constraint. Returns new narrative text or None."""
        if not self.gateway:
            return None
        try:
            context = {
                "room_id": action["room_id"],
                "character_id": action["character_id"],
                "declared_intent": action.get("declared_intent", ""),
                "intent_type": action.get("intent_type", ""),
                "previous_narrative": resolution.narrative,
                "spoiler_constraint": retry_prompt,
            }
            result = await self.gateway.generate_narrative(context, action["room_id"])
            if isinstance(result, dict):
                narrative = result.get("narrative", {})
                if isinstance(narrative, dict):
                    return narrative.get("public", "")
                return result.get("text", "") or result.get("public", "")
            return None
        except Exception as e:
            logger.warning("Spoiler retry failed for action %s: %s", action["action_id"], e)
            return None

    def _render_fallback_narrative(
        self,
        intent: PlayerIntent,
        compiled: MechanicCompileResult,
        resolution: ResolutionResult,
        character: dict | None = None,
    ) -> str:
        if resolution.cascading_state_changes:
            facts = "；".join(resolution.cascading_state_changes)
            return f"{intent.declared_intent}。结果已经确定：{facts}。"
        if compiled.triggered_mechanic == "skill_check":
            level = resolution.metadata.get("success_level", "success" if resolution.is_success else "failure")
            roll = resolution.metadata.get("roll")
            target = resolution.metadata.get("target")
            return f"{intent.declared_intent}。检定结果 {roll}/{target}，{level}。"

        # Dialogue / free-form text: do NOT just echo the player's input
        declared = intent.declared_intent or ""
        if compiled.triggered_mechanic == "dialogue":
            # "Who am I" type questions → respond with character identity
            if re.search(r"我是谁|我又是谁|who am i|我的身份|我叫什么|自我介绍", declared, re.IGNORECASE):
                if character:
                    xlsx = self._json_value(character.get("xlsx_data")) or {}
                    inv_name = xlsx.get("name", "") if isinstance(xlsx, dict) else ""
                    occupation = xlsx.get("occupation", "") if isinstance(xlsx, dict) else ""
                    parts = [f"你是{inv_name or character.get('player_name', '一名调查员')}"]
                    if occupation:
                        parts.append(f"职业是{occupation}")
                    parts.append("你目前身处当前场景之中，记忆与状态以角色卡为准。")
                    return "，".join(parts) + "。"
                return "你是一名调查员。你目前身处当前场景之中，记忆与状态以角色卡为准。"
            if len(declared) > 200:
                declared = declared[:200] + "..."

        if resolution.is_success:
            return f"你说：「{declared}」。周围暂时没有新的变化。"
        return f"你说：「{declared}」。没有明显效果。"

    async def _enrich_dialogue_narrative(
        self, action: dict, character: dict, room: dict, scenario: dict | None,
    ) -> str | None:
        """Try to generate AI-enriched narrative for dialogue actions."""
        try:
            xlsx = self._json_value(character.get("xlsx_data")) or {}
            context = {
                "scenario_title": (scenario or {}).get("title", ""),
                "investigator_name": xlsx.get("name", character.get("player_name", "")),
                "occupation": xlsx.get("occupation", ""),
                "background": (xlsx.get("background", "") or "")[:300],
                "player_words": action.get("declared_intent", ""),
                "intent_type": "dialogue",
                "system_prompt": (
                    "你是TRPG守秘人。玩家说了以下内容。请以场景叙事的方式回应。"
                    "使用角色信息丰富回应。只返回JSON: {\"narrative\": {\"public\": \"...\"}}"
                ),
            }
            result = await self.gateway.generate_narrative(context, action["room_id"])
            if isinstance(result, dict):
                narrative = result.get("narrative", {})
                if isinstance(narrative, dict) and narrative.get("public"):
                    return narrative["public"]
                if result.get("public"):
                    return result["public"]
                if result.get("text"):
                    return result["text"]
            return None
        except Exception:
            return None

    async def _validate_move(self, action: dict[str, Any], intent: PlayerIntent) -> str | None:
        """Validate move pre-conditions. Returns error string or None if valid."""
        params = intent.params or {}
        target = params.get("targetNodeId", "")
        from_node = params.get("fromNodeId", "")
        room_id = action["room_id"]

        if not target:
            return "targetNodeId is required"

        # Check room has initialized map
        from ..map_persistence import get_room_map_state, is_node_hidden, are_nodes_adjacent
        map_state = get_room_map_state(self.conn, room_id)
        if not map_state:
            return "no_map"

        # Check target not hidden by host
        if is_node_hidden(self.conn, room_id, target):
            return "node_hidden"

        # Load scenario map edges for adjacency check
        from ..map_persistence import get_scenario_map
        scenario_map = get_scenario_map(self.conn, map_state["map_id"])
        if not scenario_map:
            return "map_not_found"

        nodes = scenario_map.get("nodes", [])
        edges = scenario_map.get("edges", [])

        # If from_node not provided, look up current position
        if not from_node:
            from ..map_persistence import get_character_position
            pos = get_character_position(self.conn, action["character_id"], room_id)
            from_node = pos or ""
            if not from_node:
                return "no_current_position"

        if not are_nodes_adjacent(nodes, edges, from_node, target):
            return "not_adjacent"

        return None

    async def _apply_move_result(self, action: dict[str, Any], resolution: ResolutionResult):
        """Post-resolution: update character position, mark node explored, emit map events."""
        params = (self._json_value(action.get("params")) or {}) if isinstance(action.get("params"), str) else (action.get("params") or {})
        target = params.get("targetNodeId", "")
        room_id = action["room_id"]
        character_id = action["character_id"]

        from ..map_persistence import mark_node_explored, set_character_position, get_room_map_state, get_all_positions_in_room

        mark_node_explored(self.conn, room_id, target)
        set_character_position(self.conn, character_id, room_id, target)

        # Emit s2c_player_moved
        await self.dispatcher.emit(
            room_id,
            "s2c_player_moved",
            "party",
            {
                "characterId": character_id,
                "fromNodeId": params.get("fromNodeId", ""),
                "toNodeId": target,
            },
        )

        # Emit s2c_map_updated with current state
        map_state = get_room_map_state(self.conn, room_id)
        positions = get_all_positions_in_room(self.conn, room_id)
        await self.dispatcher.emit(
            room_id,
            "s2c_map_updated",
            "party",
            {
                "exploredNodes": map_state.get("explored_nodes", []) if map_state else [],
                "currentPositions": positions,
            },
        )

    async def _validate_encounter_action(self, action: dict[str, Any], intent: PlayerIntent) -> str | None:
        """Validate encounter pre-conditions. Returns error string or None."""
        params = intent.params or {}
        encounter_id = params.get("encounterId", "")
        room_id = action["room_id"]
        character_id = action["character_id"]

        if not encounter_id:
            return "encounterId is required"

        from ..encounter_persistence import get_encounter, get_participant
        enc = get_encounter(self.conn, encounter_id)
        if not enc:
            return "encounter_not_found"
        if enc["status"] != "active":
            return f"encounter_not_active (status={enc['status']})"

        # System skip is always allowed
        if intent.intent_type == "system_skip":
            return None

        participant = get_participant(self.conn, encounter_id, character_id)
        if not participant:
            return "character_not_in_encounter"

        if participant.get("acted_this_round") and intent.intent_type not in ("",):
            action_kind = params.get("actionKind", "")
            if action_kind not in ("wait",):
                return "already_acted_this_round"

        # Inject encounter context into intent params for handler access
        from ..encounter_persistence import get_participants
        all_participants = get_participants(self.conn, encounter_id)
        intent.params["encounter_context"] = {
            "participant": dict(participant),
            "allParticipants": [dict(p) for p in all_participants],
            "encounter": dict(enc),
        }
        intent.params["characterId"] = character_id

        return None

    async def _apply_encounter_result(
        self, action: dict[str, Any], intent: PlayerIntent, resolution: ResolutionResult,
    ):
        """Post-resolution: update participant state from mutations, emit encounter events."""
        params = intent.params or {}
        encounter_id = params.get("encounterId", "")
        room_id = action["room_id"]
        character_id = action["character_id"]

        if not encounter_id:
            return

        from ..encounter_persistence import (
            get_participant, update_participant, get_participants,
            update_encounter_status, get_active_encounter, shift_band,
        )

        participant = get_participant(self.conn, encounter_id, character_id)
        if not participant:
            return

        # Apply HP damage from mutations
        for mutation in resolution.mutations:
            path = mutation.get("path", "")
            if "hp_delta" in path:
                delta = mutation.get("value", 0)
                new_hp = max(0, participant["hp"] + delta)
                status_tags = list(participant.get("status_tags", []) or [])
                if new_hp <= 0 and "unconscious" not in status_tags:
                    status_tags.append("unconscious")
                update_participant(self.conn, encounter_id, character_id,
                                   hp=new_hp, status_tags=status_tags)
            # Apply distance band delta
            if "distance_band_delta" in path:
                delta = mutation.get("value", 0)
                if delta != 0:
                    current_band = participant.get("distance_band", "medium")
                    new_band = shift_band(current_band, delta)
                    update_participant(self.conn, encounter_id, character_id, distance_band=new_band)
            # Apply status tag additions
            if "status_tag" in path and mutation.get("op") == "add":
                tag = mutation.get("value", "")
                if tag:
                    status_tags = list(participant.get("status_tags", []) or [])
                    if tag not in status_tags:
                        status_tags.append(tag)
                    update_participant(self.conn, encounter_id, character_id, status_tags=status_tags)

        # Mark acted_this_round
        update_participant(self.conn, encounter_id, character_id, acted_this_round=True)

        # Check auto-resolve conditions
        all_parts = get_participants(self.conn, encounter_id)
        enc = get_active_encounter(self.conn, room_id)
        should_resolve = False
        resolve_reason = ""

        if enc and enc["type"] == "combat":
            enemies = [p for p in all_parts if p.get("side") == "enemy"]
            if enemies and all(p.get("hp", 0) <= 0 for p in enemies):
                should_resolve = True
                resolve_reason = "所有敌人已倒下"
        elif enc and enc["type"] == "chase":
            # Check if any participant reached 'escaped'
            for p in all_parts:
                if p.get("distance_band") == "escaped":
                    should_resolve = True
                    resolve_reason = f"{p.get('character_id')} 已逃脱"
                    break

        if should_resolve:
            update_encounter_status(self.conn, encounter_id, "resolved", resolve_reason)

        # Emit s2c_encounter_updated
        updated_enc = get_active_encounter(self.conn, room_id) or enc
        updated_parts = get_participants(self.conn, encounter_id)
        await self.dispatcher.emit(
            room_id,
            "s2c_encounter_updated",
            "party",
            {
                "encounterId": encounter_id,
                "encounter": dict(updated_enc) if updated_enc else {},
                "participants": [dict(p) for p in updated_parts],
            },
        )

        if should_resolve:
            await self.dispatcher.emit(
                room_id,
                "s2c_encounter_resolved",
                "party",
                {
                    "encounterId": encounter_id,
                    "reason": resolve_reason,
                },
            )

    def _json_value(self, value):
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return value
