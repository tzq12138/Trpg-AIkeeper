import json
import re
import uuid
import logging
import re
from datetime import datetime, timezone
from typing import Any

from ..ai.contracts import KpResponse, NarrativePayload
from ..ai.mechanic_compiler import MechanicCompiler
from ..models import MechanicCompileResult, NarrationResultDTO, PlayerIntent, ResolutionResult
from ..models import RuleExplanationDTO
from ..ai.narrator import build_narrator_context, validate_narration_result
from .action_lifecycle import complete_action, transition_action
from .fallback_narrative import render_action_aware_fallback
from .projection import ProjectionDispatcher
from .retro_items import RetroactiveClaimError, RetroactiveItemService
from .roll_receipt import create_roll_receipt
from .rule_executor import RuleExecutor

logger = logging.getLogger(__name__)


def _rule_policy_from_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    if not isinstance(value, dict):
        return {}
    raw = value.get("deterministic_policy")
    if not isinstance(raw, dict):
        return {}
    policy: dict[str, Any] = {}
    if "max_bonus_dice" in raw:
        try:
            policy["max_bonus_dice"] = max(0, min(2, int(raw["max_bonus_dice"])))
        except (TypeError, ValueError):
            pass
    for key in ("allow_luck_spend", "allow_pushed_roll"):
        if key in raw and isinstance(raw[key], bool):
            policy[key] = raw[key]
    if "low_skill_fumble_min" in raw:
        try:
            policy["low_skill_fumble_min"] = max(96, min(100, int(raw["low_skill_fumble_min"])))
        except (TypeError, ValueError):
            pass
    return policy


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
        if action["status"] in ("resolved", "completed"):
            return {"status": action["status"], "action_id": action_id}
        if action["status"] == "rejected":
            return {"status": "rejected", "action_id": action_id}
        if action["status"] != "queued":
            return {"status": action["status"], "action_id": action_id}

        is_v2 = bool(action.get("draft_id"))
        if is_v2:
            won_claim = transition_action(
                self.conn,
                action_id,
                from_statuses=("queued",),
                to_status="resolving",
                metadata={"ai_stage": "retrieving"},
            )
            claimed = self.conn.execute(
                "SELECT * FROM actions WHERE action_id = %s",
                (action_id,),
            ).fetchone() if won_claim else None
        else:
            claimed = self.conn.execute(
                "UPDATE actions SET status = %s WHERE action_id = %s AND status = %s RETURNING *",
                ("resolving", action_id, "queued"),
            ).fetchone()
        if not claimed:
            current = self.conn.execute(
                "SELECT * FROM actions WHERE action_id = %s", (action_id,)
            ).fetchone()
            return {
                "status": current["status"] if current else "missing",
                "action_id": action_id,
            }

        action = claimed
        self.conn.commit()
        await self._emit_ai_stage(action, "retrieving")

        character = self.conn.execute(
            "SELECT * FROM characters WHERE character_id = %s", (action["character_id"],)
        ).fetchone()
        room = self.conn.execute(
            "SELECT * FROM rooms WHERE room_id = %s", (action["room_id"],)
        ).fetchone()
        if not character or not room:
            await self._reject(action, "missing room or character")
            return {"status": "rejected", "action_id": action_id}
        character_data = dict(character)
        state_before = self._runtime_snapshot(
            self.conn,
            action["character_id"],
            action["room_id"],
        )
        xlsx_data = self._json_value(character_data.get("xlsx_data")) or {}
        if state_before:
            xlsx_data.update(state_before)
            character_data["xlsx_data"] = xlsx_data
        else:
            state_before = {
                key: xlsx_data.get(key)
                for key in ("hp", "san", "mp", "luck")
                if key in xlsx_data
            }

        scenario = self._load_scenario(room)
        scenario_assets = self._json_value(scenario.get("scenario_assets") if scenario else None) or {}
        scenario_assets["rule_policy"] = self._load_rule_policy(dict(room))
        inventory = self.conn.execute(
            "SELECT * FROM inventory WHERE character_id = %s", (action["character_id"],)
        ).fetchall()

        intent = PlayerIntent(
            action_id=action["action_id"],
            intent_type=action["intent_type"],
            declared_intent=action.get("declared_intent") or "",
            params=self._json_value(action.get("params")) or {},
        )
        if is_v2:
            await self._emit_ai_stage(action, "directing")
            director_err = self._validate_director_plan(action, intent, dict(room))
            if director_err:
                await self._await_host_exception(action, director_err)
                return {
                    "status": "awaiting_host_exception",
                    "action_id": action_id,
                    "reason": director_err,
                }
        retroactive_decision = None
        if is_v2 and intent.intent_type == "retroactive_item_claim":
            try:
                retroactive_decision = RetroactiveItemService(self.conn).evaluate_claim(
                    intent,
                    character_data,
                    scenario_assets,
                )
            except RetroactiveClaimError as exc:
                await self._reject(action, exc.detail)
                return {
                    "status": "rejected",
                    "action_id": action_id,
                    "reason": exc.detail,
                }

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
            await self._emit_ai_stage(action, "validating_rules")
            compiled = await self.compiler.compile(intent, scenario or {}, character_data)
            if retroactive_decision and retroactive_decision.branch == "roll_required":
                compiled = MechanicCompileResult(triggeredMechanic="luck_check")
            resolution = await self.rule_executor.execute(
                intent,
                compiled,
                character_data,
                [dict(i) for i in inventory],
                scenario_assets,
            )
        except Exception as exc:
            await self._reject(action, f"resolution failed: {exc}")
            return {"status": "rejected", "action_id": action_id, "reason": str(exc)}
        resolution.narrative = self._render_fallback_narrative(intent, compiled, resolution, character_data)

        inventory_changes = None
        if retroactive_decision:
            resolution.metadata["retroactive_item_claim"] = {
                "branch": retroactive_decision.branch,
                "claimed_item_name": retroactive_decision.claimed_item_name,
            }
            if resolution.is_success:
                item = retroactive_decision.item
                narrative = item.get("narrative") or {}
                inventory_changes = [
                    {
                        "characterId": action["character_id"],
                        "itemAdd": {
                            "name": item.get("name", retroactive_decision.claimed_item_name),
                            "description": narrative.get(
                                "description", item.get("description", "")
                            ),
                            "quantity": 1,
                            "isSecret": False,
                            "source": "backstory",
                        },
                    }
                ]

        result_payload = resolution.model_dump(by_alias=True)
        completion_status = "completed" if is_v2 else "resolved"
        completed_with_state = False
        rule_explanation_for_completion = None
        pending_consequence = (resolution.metadata or {}).get("pending_consequence")
        if (
            is_v2
            and isinstance(pending_consequence, dict)
            and pending_consequence.get("status") == "pending_host_confirmation"
        ):
            reason_code = str(
                pending_consequence.get("reason") or "rule_consequence_confirmation_required"
            )
            await self._await_host_exception(
                action,
                reason_code,
                result=result_payload,
            )
            return {
                "status": "awaiting_host_exception",
                "action_id": action_id,
                "reason": reason_code,
            }
        pending_rule_suggestions = (resolution.metadata or {}).get(
            "pending_rule_suggestions"
        )
        if is_v2 and isinstance(pending_rule_suggestions, list) and pending_rule_suggestions:
            first_suggestion = pending_rule_suggestions[0]
            reason_code = (
                str(first_suggestion.get("reason_code") or "rule_confirmation_required")
                if isinstance(first_suggestion, dict)
                else "rule_confirmation_required"
            )
            await self._await_host_exception(
                action,
                reason_code,
                result=result_payload,
            )
            return {
                "status": "awaiting_host_exception",
                "action_id": action_id,
                "reason": reason_code,
            }
        if resolution.mutations or inventory_changes:
            if not self.state_service:
                if is_v2:
                    await self._await_host_exception(action, "state_service_unavailable")
                    return {
                        "status": "awaiting_host_exception",
                        "action_id": action_id,
                        "reason": "state_service_unavailable",
                    }
            else:
                try:
                    from ..models import StateChangeSet, CharacterMutationItem
                    state_changes = StateChangeSet(
                        characterMutations=[
                            CharacterMutationItem(
                                characterId=action["character_id"],
                                mutations=resolution.mutations,
                            )
                        ] if resolution.mutations else [],
                        inventoryChanges=inventory_changes,
                    )
                    if is_v2:
                        with self.conn.transaction() as tx:
                            self.state_service.apply_change(
                                room_id=action["room_id"],
                                actor={
                                    "character_id": action["character_id"],
                                    "action_id": action["action_id"],
                                },
                                changes=state_changes,
                                reason=f"Action {action['action_id']} resolved",
                                transaction=tx,
                            )
                            rule_explanation = self._build_rule_explanation(
                                action,
                                character_data,
                                resolution,
                                state_before=state_before,
                                state_after=self._runtime_snapshot(
                                    tx,
                                    action["character_id"],
                                    action["room_id"],
                                ),
                            )
                            rule_explanation_for_completion = rule_explanation
                    else:
                        self.state_service.apply_change(
                            room_id=action["room_id"],
                            actor={
                                "character_id": action["character_id"],
                                "action_id": action["action_id"],
                            },
                            changes=state_changes,
                            reason=f"Action {action['action_id']} resolved",
                        )
                except Exception:
                    logger.exception("StateService failed for action %s", action["action_id"])
                    if is_v2:
                        await self._await_host_exception(action, "state_persistence_failed")
                        return {
                            "status": "awaiting_host_exception",
                            "action_id": action_id,
                            "reason": "state_persistence_failed",
                        }

        solo_transition = None
        if is_v2 and intent.params.get("solo_adventure") and resolution.is_success:
            try:
                from ..scenario.solo_runtime import SoloAdventureRuntime
                with self.conn.transaction() as tx:
                    solo_transition = SoloAdventureRuntime(self.conn).transition(
                        action["room_id"],
                        from_node_id=str(intent.params.get("fromNodeId") or ""),
                        target_node_id=str(intent.params.get("targetNodeId") or ""),
                        transaction=tx,
                    )
                    current_solo_scene = SoloAdventureRuntime(self.conn).current(
                        action["room_id"]
                    )
                    if current_solo_scene:
                        resolution.narrative = self._render_solo_scene_narrative(
                            current_solo_scene
                        )
                    resolution.metadata["solo_adventure_transition"] = solo_transition
                    result_payload = resolution.model_dump(by_alias=True)
                    rule_explanation = self._build_rule_explanation(
                        action, character_data, resolution,
                        state_before=state_before, state_after=state_before,
                    )
                    rule_explanation_for_completion = rule_explanation
            except Exception as exc:
                await self._reject(action, f"solo_transition_failed:{exc}")
                return {"status": "rejected", "action_id": action_id, "reason": str(exc)}

        if self.gateway and hasattr(self.gateway, "narrate_action"):
            await self._emit_ai_stage(action, "narrating")
            narration_error = await self._apply_narrator(
                action,
                character_data,
                dict(room),
                resolution,
            )
            if narration_error:
                await self._emit_ai_stage(action, "recovering")
                await self._await_host_exception(
                    action,
                    narration_error,
                    result=resolution.model_dump(by_alias=True),
                    ai_recovery=True,
                )
                return {
                    "status": "awaiting_host_exception",
                    "action_id": action_id,
                    "reason": narration_error,
                }
            result_payload = resolution.model_dump(by_alias=True)

        if is_v2:
            if not completed_with_state:
                rule_explanation = rule_explanation_for_completion or self._build_rule_explanation(
                    action,
                    character_data,
                    resolution,
                    state_before=state_before,
                    state_after=state_before,
                )
                complete_action(
                    self.conn,
                    action_id,
                    from_statuses=("resolving",),
                    to_status=completion_status,
                    result=result_payload,
                    receipt=rule_explanation,
                        metadata={"has_rule_explanation": True},
                )
        else:
            self.conn.execute(
                "UPDATE actions SET status = %s, result = %s, completed_at = %s WHERE action_id = %s",
                (
                    completion_status,
                    json.dumps(result_payload, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(),
                    action_id,
                ),
            )
            self.conn.commit()

        await self._project(action, resolution)
        await self._emit_ai_stage(action, "completed")

        if solo_transition:
            await self.dispatcher.emit(
                action["room_id"],
                "s2c_scene_sync",
                "party",
                {
                    "currentScene": solo_transition["current_scene"],
                    "soloAdventure": solo_transition,
                },
            )

        # ── Post-resolution map updates for move intent ──
        if action["intent_type"] == "move" and resolution.is_success:
            await self._apply_move_result(action, resolution)

        # ── Post-resolution encounter updates ──
        if action["intent_type"] in ("combat_action", "chase_action", "system_skip") and resolution.is_success:
            await self._apply_encounter_result(action, intent, resolution)

        return {"status": completion_status, "action_id": action_id, "result": result_payload}

    def _build_rule_explanation(
        self,
        action: dict[str, Any],
        character: dict[str, Any],
        resolution: ResolutionResult,
        *,
        state_before: dict[str, Any] | None = None,
        state_after: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = resolution.metadata or {}
        target = metadata.get("target")
        raw_rolls = self._raw_rolls(resolution)
        rolled_at = datetime.now(timezone.utc).isoformat()
        rule_set_version = action.get("rule_set_version_id") or "unversioned"
        verification_receipt = None
        if raw_rolls:
            verification_receipt = create_roll_receipt(
                action_id=action["action_id"],
                rule_set_version=rule_set_version,
                rolled_at=rolled_at,
                raw_rolls=raw_rolls,
            )
        params = self._json_value(action.get("params")) or {}
        analysis = params.get("analysis") if isinstance(params.get("analysis"), dict) else {}
        citations = analysis.get("citations") if isinstance(analysis.get("citations"), list) else []
        hidden_effects = metadata.get("hidden_modifiers")
        hidden_sources = []
        if isinstance(hidden_effects, list):
            hidden_sources = [
                {"source": "hidden", "effect": item.get("effect")}
                for item in hidden_effects
                if isinstance(item, dict) and item.get("effect") is not None
            ]
        xlsx_data = self._json_value(character.get("xlsx_data")) or {}
        if state_before is None:
            state_before = {
                key: xlsx_data.get(key)
                for key in ("hp", "san", "mp", "luck")
                if key in xlsx_data
            }
        if state_after is None:
            state_after = dict(state_before)
        explanation = RuleExplanationDTO(
            authoritative_inputs={
                "intent_type": action.get("intent_type"),
                "declared_intent": action.get("declared_intent") or "",
                "skill_name": metadata.get("skill_name") or metadata.get("skillName"),
                "skill_value": metadata.get("skill_value", metadata.get("skillValue")),
                "target": target,
                "raw_rolls": raw_rolls,
            },
            modifiers={
                "difficulty": metadata.get("difficulty"),
                "bonus_dice": metadata.get("bonus_dice", metadata.get("bonusDice", 0)),
            },
            hidden_sources=hidden_sources,
            formula=f"d100 <= {target}" if target is not None else resolution.mechanic,
            state_before=state_before,
            state_after=state_after,
            rule_set_version=rule_set_version,
            citations=citations,
            verification_receipt=verification_receipt,
        )
        return explanation.model_dump(mode="json")

    def _validate_director_plan(
        self,
        action: dict[str, Any],
        intent: PlayerIntent,
        room: dict[str, Any],
    ) -> str | None:
        plan = intent.params.get("director_plan")
        if not isinstance(plan, dict):
            return "director_plan_required"
        if plan.get("state_patch_authority") != "advisory_only":
            return "director_plan_unverified"
        context_version = plan.get("context_version")
        if context_version is not None:
            try:
                if int(context_version) != int(room.get("state_version") or 0):
                    return "director_context_stale"
            except (TypeError, ValueError):
                return "director_context_invalid"
        preconditions = plan.get("preconditions") or []
        if not isinstance(preconditions, list):
            return "director_preconditions_invalid"
        permissions = plan.get("permissions") or []
        if not isinstance(permissions, list):
            return "director_permissions_invalid"
        for permission in permissions:
            if not isinstance(permission, dict):
                return "director_permissions_invalid"
            if permission.get("allowed") is False:
                return "director_permission_denied"
            if "allowed" not in permission:
                return "director_permissions_invalid"
        for precondition in preconditions:
            if not isinstance(precondition, dict):
                return "director_preconditions_invalid"
            kind = precondition.get("kind")
            if kind == "room_status":
                expected = precondition.get("expected")
                if expected and room.get("status") != expected:
                    return "director_precondition_failed"
            elif kind == "state_version":
                expected = precondition.get("expected")
                try:
                    if expected is not None and int(expected) != int(room.get("state_version") or 0):
                        return "director_precondition_failed"
                except (TypeError, ValueError):
                    return "director_preconditions_invalid"
            elif kind in {"position", "resource", "visibility", "permission"}:
                return "director_precondition_unverified"
            else:
                return "director_precondition_unsupported"
        return None

    @staticmethod
    def _runtime_snapshot(executor, character_id: str, room_id: str) -> dict[str, Any]:
        try:
            row = executor.execute(
                "SELECT hp, san, mp, luck FROM character_runtime_state "
                "WHERE character_id = %s AND room_id = %s",
                (character_id, room_id),
            ).fetchone()
        except Exception:
            return {}
        return dict(row) if row else {}

    @staticmethod
    def _raw_rolls(resolution: ResolutionResult) -> list[dict[str, Any]]:
        rolls = []
        for step in resolution.reveal_steps:
            if not isinstance(step, dict) or step.get("kind") not in ("roll", "damage"):
                continue
            trace = step.get("rollTrace") or step.get("roll_trace") or {}
            rolls.append({
                "dice": step.get("dice") or "unknown",
                "values": trace,
                "result": step.get("result"),
            })
        return rolls

    def _load_scenario(self, room: dict[str, Any]) -> dict[str, Any] | None:
        scenario_id = room.get("scenario_id")
        if not scenario_id:
            return None
        row = self.conn.execute(
            "SELECT * FROM scenarios WHERE scenario_id = %s", (scenario_id,)
        ).fetchone()
        return dict(row) if row else None

    def _load_rule_policy(self, room: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        sources: list[dict[str, Any]] = []
        scenario_version_id = room.get("scenario_version_id")
        try:
            if scenario_version_id:
                rows = self.conn.execute(
                    """
                    SELECT rsv.rule_set_version_id, rsv.metadata, rs.is_base,
                           srb.priority
                    FROM scenario_rule_bindings srb
                    JOIN rule_set_versions rsv
                      ON rsv.rule_set_version_id = srb.rule_set_version_id
                    JOIN rule_sets rs ON rs.rule_set_id = rsv.rule_set_id
                    WHERE srb.scenario_version_id = %s
                    ORDER BY CASE WHEN rs.is_base THEN 0 ELSE 1 END,
                             srb.priority, rsv.rule_set_version_id
                    """,
                    (scenario_version_id,),
                ).fetchall()
                for row in rows:
                    scope = "base" if row.get("is_base") else "scenario"
                    policy = _rule_policy_from_metadata(row.get("metadata"))
                    if policy:
                        merged.update(policy)
                        sources.append({
                            "scope": scope,
                            "rule_set_version_id": row["rule_set_version_id"],
                        })
            else:
                rows = self.conn.execute(
                    """
                    SELECT rsv.rule_set_version_id, rsv.metadata
                    FROM rule_set_versions rsv
                    JOIN rule_sets rs ON rs.rule_set_id = rsv.rule_set_id
                    WHERE rs.system = 'coc7' AND rs.is_base = TRUE
                      AND rs.status = 'published' AND rsv.status = 'published'
                    ORDER BY rsv.version_number, rsv.rule_set_version_id
                    """
                ).fetchall()
                for row in rows:
                    policy = _rule_policy_from_metadata(row.get("metadata"))
                    if policy:
                        merged.update(policy)
                        sources.append({
                            "scope": "base",
                            "rule_set_version_id": row["rule_set_version_id"],
                        })

            room_id = room.get("room_id")
            if room_id:
                rows = self.conn.execute(
                    """
                    SELECT rsv.rule_set_version_id, rsv.metadata, rrb.priority
                    FROM room_rule_bindings rrb
                    JOIN rule_set_versions rsv
                      ON rsv.rule_set_version_id = rrb.rule_set_version_id
                    WHERE rrb.room_id = %s
                    ORDER BY rrb.priority, rsv.rule_set_version_id
                    """,
                    (room_id,),
                ).fetchall()
                for row in rows:
                    policy = _rule_policy_from_metadata(row.get("metadata"))
                    if policy:
                        merged.update(policy)
                        sources.append({
                            "scope": "room",
                            "rule_set_version_id": row["rule_set_version_id"],
                        })
        except Exception as exc:
            logger.warning("Failed to resolve rule policy for room=%s: %s", room.get("room_id"), exc)
            return {}
        if sources:
            merged["_sources"] = sources
        return merged

    async def _reject(self, action: dict[str, Any], reason: str):
        payload = {"reason": reason}
        if action.get("draft_id"):
            complete_action(
                self.conn,
                action["action_id"],
                from_statuses=("resolving",),
                to_status="rejected",
                result=payload,
                metadata={"reason_code": "resolution_rejected"},
            )
        else:
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

    async def _await_host_exception(
        self,
        action: dict[str, Any],
        reason_code: str,
        *,
        result: dict | None = None,
        ai_recovery: bool = False,
    ):
        transition_action(
            self.conn,
            action["action_id"],
            from_statuses=("resolving",),
            to_status="awaiting_host_exception",
            metadata={
                "reason_code": reason_code,
                **({"ai_stage": "recovering"} if ai_recovery else {}),
            },
            result=result,
        )
        await self.dispatcher.emit(
            action["room_id"],
            "s2c_action_exception_requested",
            "host",
            {
                "actionId": action["action_id"],
                "characterId": action["character_id"],
                "reasonCode": reason_code,
            },
        )
        if ai_recovery:
            await self.dispatcher.emit(
                action["room_id"],
                "s2c_ai_recovery_required",
                "player",
                {
                    "actionId": action["action_id"],
                    "characterId": action["character_id"],
                    "reasonCode": reason_code,
                },
                character_id=action["character_id"],
            )

    async def _emit_ai_stage(self, action: dict[str, Any], stage: str) -> None:
        if not action.get("draft_id"):
            return
        try:
            self._record_ai_stage(action["action_id"], stage)
            await self.dispatcher.emit(
                action["room_id"],
                "s2c_ai_stage_changed",
                "player",
                {
                    "actionId": action["action_id"],
                    "stage": stage,
                },
                character_id=action["character_id"],
            )
        except Exception:
            logger.debug("Failed to emit AI stage %s for action %s", stage, action["action_id"])

    def _record_ai_stage(self, action_id: str, stage: str) -> None:
        row = self.conn.execute(
            "SELECT status_event_id, metadata FROM action_status_events "
            "WHERE action_id = %s ORDER BY status_event_id DESC LIMIT 1",
            (action_id,),
        ).fetchone()
        if not row:
            return
        metadata = self._json_value(row.get("metadata")) or {}
        metadata["ai_stage"] = stage
        self.conn.execute(
            "UPDATE action_status_events SET metadata = %s WHERE status_event_id = %s",
            (json.dumps(metadata, ensure_ascii=False), row["status_event_id"]),
        )
        self.conn.commit()

    async def _apply_narrator(
        self,
        action: dict[str, Any],
        character: dict[str, Any],
        room: dict[str, Any],
        resolution: ResolutionResult,
    ) -> str | None:
        try:
            context = build_narrator_context(
                self.conn,
                action,
                character,
                room,
                resolution,
            )
            payload = dict(context)
            raw = await self.gateway.narrate_action(
                payload,
                action["room_id"],
                action_id=action["action_id"],
            )
            if not isinstance(raw, dict):
                return "narrator_invalid_response"
            narration = NarrationResultDTO(**raw)
            violation = validate_narration_result(narration, context)
            if violation:
                return violation
            resolution.narrative = narration.narrative_text
            metadata = dict(resolution.metadata or {})
            metadata["narration"] = narration.model_dump(mode="json")
            resolution.metadata = metadata
            return None
        except Exception as exc:
            logger.warning(
                "Narrator failed for action %s: %s",
                action.get("action_id"),
                type(exc).__name__,
            )
            return "narrator_invalid_response"

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
                "actionId": action["action_id"],
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
        narration = (resolution.metadata or {}).get("narration")
        if isinstance(narration, dict):
            await self.dispatcher.emit(
                action["room_id"],
                "s2c_narration_completed",
                "party",
                {
                    "actionId": action["action_id"],
                    "narrativeText": final_text,
                    "environmentChanges": narration.get("environment_changes") or [],
                    "interactableObjects": narration.get("interactable_objects") or [],
                    "openQuestion": narration.get("open_question") or "",
                    "stylePackVersion": narration.get("style_pack_version") or "",
                    "redactedCitations": narration.get("redacted_citations") or [],
                },
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
            "status": "completed" if action.get("draft_id") else "resolved",
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
            return self._extract_public_narrative(result)
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

        return render_action_aware_fallback(
            declared,
            character_name=(character or {}).get("player_name", ""),
            succeeded=resolution.is_success,
        )

    @staticmethod
    def _render_solo_scene_narrative(scene: dict[str, Any]) -> str:
        title = str(scene.get("title") or f"条目 {scene.get('node_id', '')}").strip()
        text = str(scene.get("text") or "").strip()
        choices = [
            f"转到条目 {node_id}"
            for node_id in scene.get("target_node_ids") or []
            if str(node_id).strip()
        ]
        direction = (
            f"接下来可选方向：{'、'.join(choices)}。你准备怎么做？"
            if choices
            else "当前条目没有新的编号方向；你可以描述调查、交谈或其他行动。"
        )
        return "\n\n".join(part for part in (title, text, direction) if part)

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
            return self._extract_public_narrative(result)
        except Exception:
            return None

    def _extract_public_narrative(self, result: Any) -> str | None:
        if isinstance(result, NarrativePayload):
            return result.public or None
        if isinstance(result, KpResponse):
            return result.narrative.public or None
        if isinstance(result, dict):
            narrative = result.get("narrative")
            if isinstance(narrative, NarrativePayload):
                return narrative.public or None
            if isinstance(narrative, dict) and narrative.get("public"):
                return narrative["public"]
            if result.get("public"):
                return result["public"]
            if result.get("text"):
                return result["text"]
        if isinstance(result, str):
            return result or None
        return None

    async def _validate_move(self, action: dict[str, Any], intent: PlayerIntent) -> str | None:
        """Validate move pre-conditions. Returns error string or None if valid."""
        params = intent.params or {}
        target = params.get("targetNodeId", "")
        from_node = params.get("fromNodeId", "")
        room_id = action["room_id"]

        if not target:
            return "targetNodeId is required"

        from ..scenario.solo_runtime import SoloAdventureRuntime
        solo_validation = SoloAdventureRuntime(self.conn).validate_transition(
            room_id,
            from_node_id=str(from_node or ""),
            target_node_id=str(target),
        )
        if solo_validation is not None:
            if solo_validation:
                return solo_validation
            intent.params["solo_adventure"] = True
            return None

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

        from ..scenario.solo_runtime import SoloAdventureRuntime
        if SoloAdventureRuntime(self.conn).current(room_id) is not None:
            return

        from ..map_persistence import (
            get_all_positions_in_room,
            get_room_map_state,
            mark_node_explored,
            reveal_regions_for_node,
            set_character_position,
            set_token_visibility,
        )

        mark_node_explored(self.conn, room_id, target)
        revealed_region_ids = reveal_regions_for_node(self.conn, room_id, target)
        set_character_position(self.conn, character_id, room_id, target)
        analysis = params.get("analysis") if isinstance(params.get("analysis"), dict) else {}
        private_move = analysis.get("visibility") == "private"
        set_token_visibility(
            self.conn,
            room_id,
            character_id,
            "hidden" if private_move else "party",
        )
        audience = "player" if private_move else "party"
        event_character_id = character_id if private_move else None

        # Emit s2c_player_moved
        await self.dispatcher.emit(
            room_id,
            "s2c_player_moved",
            audience,
            {
                "characterId": character_id,
                "fromNodeId": params.get("fromNodeId", ""),
                "toNodeId": target,
                "private": private_move,
            },
            character_id=event_character_id,
        )

        # Emit s2c_map_updated with current state
        map_state = get_room_map_state(self.conn, room_id)
        positions = get_all_positions_in_room(self.conn, room_id)
        await self.dispatcher.emit(
            room_id,
            "s2c_map_updated",
            audience,
            {
                "exploredNodes": map_state.get("explored_nodes", []) if map_state else [],
                "currentPositions": (
                    {character_id: positions.get(character_id)} if private_move else positions
                ),
                "private": private_move,
                "revealedRegionIds": revealed_region_ids,
                "mapVersion": map_state.get("state_version", 0) if map_state else 0,
            },
            character_id=event_character_id,
        )

    async def _validate_encounter_action(self, action: dict[str, Any], intent: PlayerIntent) -> str | None:
        """Validate encounter pre-conditions. Returns error string or None."""
        params = intent.params or {}
        encounter_id = params.get("encounterId", "")
        room_id = action["room_id"]
        character_id = action["character_id"]

        from ..encounter_persistence import (
            get_active_encounter,
            get_encounter,
            get_participant,
            get_participants,
        )
        if not encounter_id:
            active_encounter = get_active_encounter(self.conn, room_id)
            if not active_encounter and intent.intent_type == "combat_action":
                active_encounter = self._bootstrap_solo_combat_encounter(
                    room_id,
                    character_id,
                    intent.declared_intent,
                )
            if not active_encounter:
                return "encounterId is required"
            encounter_id = active_encounter["encounter_id"]
            intent.params["encounterId"] = encounter_id

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
        all_participants = get_participants(self.conn, encounter_id)
        if intent.intent_type == "combat_action":
            intent.params.setdefault("actionKind", "attack")
            if not intent.params.get("targetId"):
                enemy = next(
                    (item for item in all_participants if item.get("side") == "enemy"),
                    None,
                )
                if enemy:
                    intent.params["targetId"] = enemy["character_id"]
        authoritative_participants = []
        for item in all_participants:
            participant_data = dict(item)
            character_row = self.conn.execute(
                "SELECT xlsx_data FROM characters WHERE character_id = %s",
                (participant_data.get("character_id"),),
            ).fetchone()
            if character_row:
                character_sheet = self._json_value(character_row.get("xlsx_data")) or {}
                participant_data["skills"] = dict(character_sheet.get("skills") or {})
            authoritative_participants.append(participant_data)
        intent.params["encounter_context"] = {
            "participant": dict(participant),
            "allParticipants": authoritative_participants,
            "encounter": dict(enc),
        }
        intent.params["characterId"] = character_id

        return None

    def _bootstrap_solo_combat_encounter(
        self,
        room_id: str,
        character_id: str,
        declared_intent: str,
    ) -> dict[str, Any] | None:
        from ..encounter_persistence import (
            add_participant,
            create_encounter,
            get_encounter,
            update_encounter_round,
        )
        from ..scenario.solo_runtime import SoloAdventureRuntime

        scene = SoloAdventureRuntime(self.conn).current(room_id)
        text = str(scene.get("text") or "") if scene else ""
        if not scene or not all(marker in text for marker in ("黑熊", "生命值", "爪击")):
            return None
        node_id = str(scene["node_id"])
        encounter_id = f"solo:{room_id}:{node_id}"
        existing = get_encounter(self.conn, encounter_id)
        if existing:
            return existing
        character = self.conn.execute(
            "SELECT player_name, xlsx_data FROM characters WHERE character_id = %s",
            (character_id,),
        ).fetchone()
        if not character:
            return None
        sheet = self._json_value(character.get("xlsx_data")) or {}
        attributes = sheet.get("attributes") or {}
        skills = sheet.get("skills") or {}
        main_skill = next(
            (name for name in ("格斗（斗殴）", "格斗(斗殴)", "斗殴", "格斗") if name in skills),
            "格斗（斗殴）",
        )
        uses_knife = "刀" in declared_intent
        encounter = create_encounter(
            self.conn,
            encounter_id,
            room_id,
            enc_type="combat",
            status="active",
            summary=f"{scene['title']}：黑熊近身战",
        )
        update_encounter_round(self.conn, encounter_id, 1)
        add_participant(
            self.conn,
            encounter_id,
            character_id,
            side="player",
            hp=int(sheet.get("hp", 0) or 0),
            hp_max=int(sheet.get("max_hp", sheet.get("hp", 0)) or 0),
            san=int(sheet.get("san", 0) or 0),
            san_max=int(sheet.get("max_san", sheet.get("san", 0)) or 0),
            dex=int(attributes.get("dex", 0) or 0),
            weapon_name="小刀" if uses_knife else "徒手",
            damage_expression="1d4" if uses_knife else "1d3",
            main_skill=main_skill,
            display_name=str(sheet.get("name") or character.get("player_name") or "调查员"),
        )
        add_participant(
            self.conn,
            encounter_id,
            f"npc:bear:{node_id}",
            side="enemy",
            hp=20,
            hp_max=20,
            dex=58,
            weapon_name="爪击",
            damage_expression="2d6",
            main_skill="爪击",
            notes="厚皮每轮吸收前3点伤害；第一轮双爪，第二轮爪击与啃咬，第三轮双爪。",
            display_name="黑熊",
        )
        return get_encounter(self.conn, encounter_id) or encounter

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

        # Apply encounter mutations to the participant named in each path.
        for mutation in resolution.mutations:
            path = mutation.get("path", "")
            match = re.match(
                r"^/encounter/([^/]+)/participants/([^/]+)/(hp_delta|distance_band_delta|status_tag)$",
                path,
            )
            if not match or match.group(1) != encounter_id:
                continue
            target_character_id = match.group(2)
            target_participant = get_participant(
                self.conn, encounter_id, target_character_id
            )
            if not target_participant:
                continue
            if "hp_delta" in path:
                delta = mutation.get("value", 0)
                new_hp = max(0, target_participant["hp"] + delta)
                status_tags = list(target_participant.get("status_tags", []) or [])
                if new_hp <= 0 and "unconscious" not in status_tags:
                    status_tags.append("unconscious")
                update_participant(self.conn, encounter_id, target_character_id,
                                   hp=new_hp, status_tags=status_tags)
            # Apply distance band delta
            if "distance_band_delta" in path:
                delta = mutation.get("value", 0)
                if delta != 0:
                    current_band = target_participant.get("distance_band", "medium")
                    new_band = shift_band(current_band, delta)
                    update_participant(self.conn, encounter_id, target_character_id, distance_band=new_band)
            # Apply status tag additions
            if "status_tag" in path and mutation.get("op") == "add":
                tag = mutation.get("value", "")
                if tag:
                    status_tags = list(target_participant.get("status_tags", []) or [])
                    if tag not in status_tags:
                        status_tags.append(tag)
                    update_participant(self.conn, encounter_id, target_character_id, status_tags=status_tags)

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
                "encounter": self._event_safe_record(updated_enc) if updated_enc else {},
                "participants": [self._event_safe_record(p) for p in updated_parts],
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

    @staticmethod
    def _event_safe_record(value: Any) -> dict[str, Any]:
        record = dict(value)
        for key, item in record.items():
            if isinstance(item, (datetime,)):
                record[key] = item.isoformat()
        return record

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
