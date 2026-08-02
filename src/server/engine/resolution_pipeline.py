import asyncio
import hashlib
import json
import re
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..ai.contracts import KpResponse, NarrativePayload
from ..ai.mechanic_compiler import MechanicCompiler
from ..models import MechanicCompileResult, NarrationResultDTO, PlayerIntent, ResolutionResult
from ..models import RuleExplanationDTO
from ..ai.narrator import (
    build_verified_narration,
    build_narrator_context,
    validate_narration_result,
)
from .action_lifecycle import complete_action, transition_action
from .fallback_narrative import render_action_aware_fallback
from .host_autonomy import decide_host_autonomy
from .projection import ProjectionDispatcher
from .retro_items import RetroactiveClaimError, RetroactiveItemService
from .reveal_ledger import RevealPolicyError
from .roll_receipt import create_roll_receipt
from .rule_executor import RuleExecutor

logger = logging.getLogger(__name__)

_NARRATOR_TIMEOUT_SECONDS = 30
_SAFE_LAST_OBSERVED_DISTANCES = {
    "engaged": "近处",
    "near": "近距离",
    "short": "短距离",
    "medium": "中距离",
    "long": "远距离",
}


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
        host_connection_checker: Callable[[str], bool] | None = None,
    ):
        self.conn = conn
        self.compiler = compiler or MechanicCompiler(api_key="")
        self.dispatcher = dispatcher or ProjectionDispatcher(conn)
        self.rule_executor = rule_executor or RuleExecutor()
        self.spoiler_guard = spoiler_guard
        self.gateway = gateway
        self.state_service = state_service
        self.host_connection_checker = host_connection_checker

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

    @staticmethod
    def _composite_steps(params: dict[str, Any]) -> list[dict[str, Any]]:
        raw_steps = params.get("composite_steps") if isinstance(params, dict) else None
        if not isinstance(raw_steps, list) or len(raw_steps) != 2:
            return []
        allowed_types = {
            "dialogue",
            "skill_check",
            "move",
            "use_item",
            "show_item",
            "combat_action",
            "chase_action",
        }
        accepted: list[dict[str, Any]] = []
        for item in raw_steps:
            if not isinstance(item, dict):
                return []
            intent_type = str(item.get("intent_type") or "")
            step_id = str(item.get("step_id") or "")
            declared_intent = str(item.get("declared_intent") or "")
            if (
                intent_type not in allowed_types
                or not step_id
                or not declared_intent
                or not isinstance(item.get("params") or {}, dict)
                or any(step["step_id"] == step_id for step in accepted)
            ):
                return []
            policy = str(item.get("on_previous_failure") or "cancel")
            if policy not in {"cancel", "continue"}:
                policy = "cancel"
            condition = str(item.get("execution_condition") or (
                "always" if policy == "continue" else "previous_step_success"
            ))
            if condition not in {"always", "previous_step_success", "previous_step_failure"}:
                return []
            if condition == "always":
                policy = "continue"
            accepted.append({
                "step_id": step_id,
                "summary": str(item.get("summary") or declared_intent),
                "declared_intent": declared_intent,
                "intent_type": intent_type,
                "params": dict(item.get("params") or {}),
                "execution_condition": condition if len(accepted) else "always",
                "on_previous_failure": policy,
            })
        return accepted

    async def _resolve_composite_action(
        self,
        intent: PlayerIntent,
        initial_compiled: MechanicCompileResult,
        steps: list[dict[str, Any]],
        scenario: dict[str, Any],
        character: dict[str, Any],
        inventory: list[dict[str, Any]],
        scenario_assets: dict[str, Any],
    ) -> tuple[MechanicCompileResult, ResolutionResult]:
        working_character = dict(character)
        working_character["xlsx_data"] = dict(character.get("xlsx_data") or {})
        phases: list[dict[str, Any]] = []
        merged_metadata: dict[str, Any] = {}
        mutations: list[dict[str, Any]] = []
        reveal_steps: list[dict[str, Any]] = []
        cascading_state_changes: list[str] = []
        overall_success = True
        last_compiled = initial_compiled
        last_mechanic = initial_compiled.triggered_mechanic
        resume_progress = intent.params.get("composite_progress")
        resume_decision = ""
        start_index = 0
        if isinstance(resume_progress, dict) and resume_progress.get("decision") in {"continue", "cancel"}:
            try:
                first_resolution = ResolutionResult.model_validate(
                    resume_progress["first_resolution"]
                )
            except (KeyError, TypeError, ValueError):
                first_resolution = None
            if first_resolution is not None and str(resume_progress.get("pending_step_id") or "") == steps[1]["step_id"]:
                stored_composite = first_resolution.metadata.get("composite_action")
                phases = list(stored_composite.get("phases") or []) if isinstance(stored_composite, dict) else []
                phases = [phase for phase in phases if phase.get("status") != "awaiting_choice"]
                merged_metadata = {
                    key: value
                    for key, value in (first_resolution.metadata or {}).items()
                    if key != "composite_action"
                }
                mutations = list(first_resolution.mutations)
                reveal_steps = list(first_resolution.reveal_steps)
                cascading_state_changes = list(first_resolution.cascading_state_changes)
                overall_success = first_resolution.is_success
                last_mechanic = first_resolution.mechanic
                resume_decision = str(resume_progress["decision"])
                start_index = 1
                if resume_decision == "cancel":
                    phases.append({
                        "stepId": steps[1]["step_id"],
                        "summary": steps[1]["summary"],
                        "intentType": steps[1]["intent_type"],
                        "status": "canceled",
                        "failurePolicy": "cancel",
                    })

        for index, step in enumerate(steps[start_index:], start=start_index):
            if resume_decision == "cancel":
                break
            if index and step["execution_condition"] == "previous_step_failure" and overall_success:
                phases.append({
                    "stepId": step["step_id"],
                    "summary": step["summary"],
                    "intentType": step["intent_type"],
                    "status": "skipped_condition",
                    "executionCondition": step["execution_condition"],
                })
                break
            if (
                index
                and not overall_success
                and step["execution_condition"] == "previous_step_success"
            ):
                policy = step["on_previous_failure"]
                if policy != "continue":
                    phases.append({
                        "stepId": step["step_id"],
                        "summary": step["summary"],
                        "intentType": step["intent_type"],
                        "status": "canceled",
                        "executionCondition": step["execution_condition"],
                        "failurePolicy": policy,
                    })
                    break
            step_intent = PlayerIntent(
                action_id=intent.action_id,
                intent_type=step["intent_type"],
                declared_intent=step["declared_intent"],
                base_state_version=intent.base_state_version,
                params=step["params"],
            )
            compiled = (
                initial_compiled
                if index == 0
                else await self.compiler.compile(step_intent, scenario or {}, working_character)
            )
            last_compiled = compiled
            step_resolution = await self.rule_executor.execute(
                step_intent,
                compiled,
                working_character,
                inventory,
                scenario_assets,
            )
            phases.append({
                "stepId": step["step_id"],
                "summary": step["summary"],
                "intentType": step["intent_type"],
                "status": "completed" if step_resolution.is_success else "failed",
                "executionCondition": step["execution_condition"],
                "failurePolicy": step["on_previous_failure"],
                "mechanic": step_resolution.mechanic,
            })
            merged_metadata.update(step_resolution.metadata or {})
            mutations.extend(step_resolution.mutations)
            reveal_steps.extend(step_resolution.reveal_steps)
            cascading_state_changes.extend(step_resolution.cascading_state_changes)
            overall_success = overall_success and step_resolution.is_success
            last_mechanic = step_resolution.mechanic
            self._apply_composite_mutations(working_character, step_resolution.mutations)

        composite_metadata: dict[str, Any] = {
            "phases": phases,
            "action_cost": 1,
        }
        if phases and phases[-1].get("status") == "awaiting_choice":
            if mutations:
                merged_metadata.setdefault("pending_rule_suggestions", []).append({
                    "mechanic": "composite_action",
                    "reason_code": "composite_choice_requires_host",
                    "status": "pending_host_confirmation",
                })
            else:
                composite_metadata["awaiting_choice"] = {
                    "step_id": steps[1]["step_id"],
                    "summary": steps[1]["summary"],
                    "question": "第一步未成功，仍要继续下一步吗？",
                }
        merged_metadata["composite_action"] = composite_metadata
        return last_compiled, ResolutionResult(
            actionId=intent.action_id,
            roomId=character.get("room_id", ""),
            characterId=character.get("character_id", ""),
            mechanic=last_mechanic,
            isSuccess=overall_success,
            metadata=merged_metadata,
            mutations=mutations,
            revealSteps=reveal_steps,
            cascadingStateChanges=cascading_state_changes,
        )

    @staticmethod
    def _apply_composite_mutations(character: dict[str, Any], mutations: list[dict[str, Any]]) -> None:
        sheet = character.get("xlsx_data")
        if not isinstance(sheet, dict):
            sheet = {}
            character["xlsx_data"] = sheet
        for mutation in mutations:
            if not isinstance(mutation, dict) or mutation.get("op") not in {"add", "replace"}:
                continue
            path = str(mutation.get("path") or "")
            if not path.startswith("/character/") or "/" in path.removeprefix("/character/"):
                continue
            sheet[path.removeprefix("/character/")] = mutation.get("value")

    async def _await_composite_choice(
        self,
        action: dict[str, Any],
        resolution: ResolutionResult,
    ) -> dict[str, Any]:
        composite = resolution.metadata.get("composite_action") or {}
        awaiting_choice = composite.get("awaiting_choice") if isinstance(composite, dict) else None
        if not isinstance(awaiting_choice, dict):
            raise ValueError("composite_choice_missing")
        params = self._json_value(action.get("params")) or {}
        params["composite_progress"] = {
            "pending_step_id": awaiting_choice["step_id"],
            "first_resolution": resolution.model_dump(by_alias=True),
        }
        self.conn.execute(
            "UPDATE actions SET params = %s WHERE action_id = %s",
            (json.dumps(params, ensure_ascii=False), action["action_id"]),
        )
        result_payload = resolution.model_dump(by_alias=True)
        transitioned = transition_action(
            self.conn,
            action["action_id"],
            from_statuses=("resolving",),
            to_status="awaiting_player_choice",
            metadata={"reason_code": "composite_follow_up_choice"},
            result=result_payload,
        )
        if not transitioned:
            return {"status": "sync_required", "action_id": action["action_id"]}
        await self.dispatcher.emit(
            action["room_id"],
            "s2c_action_choice_requested",
            "player",
            {
                "actionId": action["action_id"],
                "status": "awaiting_player_choice",
                "question": awaiting_choice["question"],
                "stepId": awaiting_choice["step_id"],
            },
            character_id=action["character_id"],
        )
        return {
            "status": "awaiting_player_choice",
            "action_id": action["action_id"],
            "result": result_payload,
        }

    async def _await_coc_followup(
        self,
        action: dict[str, Any],
        character: dict[str, Any],
        resolution: ResolutionResult,
        *,
        state_before: dict[str, Any],
    ) -> dict[str, Any]:
        raw_follow_up = (resolution.metadata or {}).get("follow_up")
        if not isinstance(raw_follow_up, dict):
            raise ValueError("coc_followup_missing")
        follow_up = json.loads(json.dumps(raw_follow_up, ensure_ascii=False, default=str))
        engine = follow_up.pop("_engine", None)
        if not isinstance(engine, dict):
            raise ValueError("coc_followup_engine_context_missing")

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=180)
        follow_up["expires_at"] = expires_at.isoformat()
        resolution.metadata = {
            **dict(resolution.metadata or {}),
            "follow_up": follow_up,
        }
        result_payload = resolution.model_dump(by_alias=True)
        rule_explanation = self._build_rule_explanation(
            action,
            character,
            resolution,
            state_before=state_before,
            state_after=state_before,
        )
        verification_receipt = rule_explanation.get("verification_receipt")
        state_version = (
            verification_receipt.get("state_version")
            if isinstance(verification_receipt, dict)
            else None
        )
        progress = {
            "status": "pending",
            "allowed_decisions": list(follow_up.get("allowed_decisions") or []),
            "luck": follow_up.get("luck") or {},
            "push": follow_up.get("push") or {},
            "expires_at": follow_up["expires_at"],
            "state_version": int(state_version or 0),
            "engine": engine,
            "initial_resolution": result_payload,
            "initial_verification_receipt": verification_receipt,
        }
        params = self._json_value(action.get("params")) or {}
        params["coc_followup_progress"] = progress

        with self.conn.transaction() as tx:
            cursor = tx.execute(
                "UPDATE actions SET status = 'awaiting_player_choice', params = %s, "
                "result = %s, receipt = %s "
                "WHERE action_id = %s AND status = 'resolving'",
                (
                    json.dumps(params, ensure_ascii=False, default=str),
                    json.dumps(result_payload, ensure_ascii=False, default=str),
                    json.dumps(rule_explanation, ensure_ascii=False, default=str),
                    action["action_id"],
                ),
            )
            if cursor.rowcount:
                tx.execute(
                    "INSERT INTO action_status_events (action_id, status, metadata) "
                    "VALUES (%s, 'awaiting_player_choice', %s)",
                    (
                        action["action_id"],
                        json.dumps({"reason_code": "coc_followup_required"}),
                    ),
                )
        if cursor.rowcount == 0:
            return {"status": "sync_required", "action_id": action["action_id"]}

        self._persist_resolution_bundle(
            action,
            "awaiting_player_choice",
            result_payload,
            rule_explanation,
            resolution,
        )
        await self.dispatcher.emit(
            action["room_id"],
            "s2c_action_choice_requested",
            "player",
            {
                "actionId": action["action_id"],
                "status": "awaiting_player_choice",
                "kind": "coc_followup",
                "followUp": follow_up,
            },
            character_id=action["character_id"],
        )
        return {
            "status": "awaiting_player_choice",
            "action_id": action["action_id"],
            "result": result_payload,
        }

    async def _await_sanity_background(
        self,
        action: dict[str, Any],
        character: dict[str, Any],
        resolution: ResolutionResult,
        *,
        state_before: dict[str, Any],
    ) -> dict[str, Any]:
        raw_background = (resolution.metadata or {}).get("background_change")
        if not isinstance(raw_background, dict):
            raise ValueError("sanity_background_missing")
        background = json.loads(
            json.dumps(raw_background, ensure_ascii=False, default=str)
        )
        engine = background.pop("_engine", None)
        if not isinstance(engine, dict):
            raise ValueError("sanity_background_engine_context_missing")
        resolution.metadata = {
            **dict(resolution.metadata or {}),
            "background_change": background,
        }
        result_payload = resolution.model_dump(by_alias=True)
        rule_explanation = self._build_rule_explanation(
            action,
            character,
            resolution,
            state_before=state_before,
            state_after=state_before,
        )
        progress = {
            "status": "pending",
            "allowed_decisions": list(background.get("allowed_decisions") or []),
            "engine": engine,
            "initial_resolution": result_payload,
        }
        params = self._json_value(action.get("params")) or {}
        params["sanity_background_progress"] = progress

        with self.conn.transaction() as tx:
            cursor = tx.execute(
                "UPDATE actions SET status = 'awaiting_player_choice', params = %s, "
                "result = %s, receipt = %s "
                "WHERE action_id = %s AND status = 'resolving'",
                (
                    json.dumps(params, ensure_ascii=False, default=str),
                    json.dumps(result_payload, ensure_ascii=False, default=str),
                    json.dumps(rule_explanation, ensure_ascii=False, default=str),
                    action["action_id"],
                ),
            )
            if cursor.rowcount:
                tx.execute(
                    "INSERT INTO action_status_events (action_id, status, metadata) "
                    "VALUES (%s, 'awaiting_player_choice', %s)",
                    (
                        action["action_id"],
                        json.dumps({"reason_code": "coc_background_change_required"}),
                    ),
                )
        if cursor.rowcount == 0:
            return {"status": "sync_required", "action_id": action["action_id"]}

        self._persist_resolution_bundle(
            action,
            "awaiting_player_choice",
            result_payload,
            rule_explanation,
            resolution,
        )
        await self.dispatcher.emit(
            action["room_id"],
            "s2c_action_choice_requested",
            "player",
            {
                "actionId": action["action_id"],
                "status": "awaiting_player_choice",
                "kind": "coc_background_change",
                "backgroundChange": background,
            },
            character_id=action["character_id"],
        )
        return {
            "status": "awaiting_player_choice",
            "action_id": action["action_id"],
            "result": result_payload,
        }

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
        action_params = self._json_value(action.get("params")) or {}
        composite_progress = action_params.get("composite_progress")
        is_composite_resume = (
            action["status"] == "awaiting_player_choice"
            and isinstance(composite_progress, dict)
            and composite_progress.get("decision") in {"continue", "cancel"}
        )
        coc_followup_progress = action_params.get("coc_followup_progress")
        is_coc_followup_resume = (
            action["status"] in {"awaiting_player_choice", "queued", "batched"}
            and isinstance(coc_followup_progress, dict)
            and coc_followup_progress.get("status") == "submitted"
            and coc_followup_progress.get("decision") in {"spend_luck", "push", "decline"}
        )
        sanity_background_progress = action_params.get("sanity_background_progress")
        is_sanity_background_resume = (
            action["status"] == "awaiting_player_choice"
            and isinstance(sanity_background_progress, dict)
            and sanity_background_progress.get("status") == "submitted"
            and sanity_background_progress.get("decision") in {"accept", "reject"}
        )
        is_player_choice_resume = (
            is_composite_resume
            or is_coc_followup_resume
            or is_sanity_background_resume
        )
        if action["status"] not in {"queued", "batched"} and not is_player_choice_resume:
            return {"status": action["status"], "action_id": action_id}
        if not is_player_choice_resume:
            from .action_consent import enforce_action_consent_gate

            if not enforce_action_consent_gate(self.conn, action_id):
                current = self.conn.execute(
                    "SELECT status FROM actions WHERE action_id = %s",
                    (action_id,),
                ).fetchone()
                return {
                    "status": current["status"] if current else "missing",
                    "action_id": action_id,
                }
        if self.conn.execute(
            """
            SELECT 1
            FROM player_action_submissions
            WHERE room_id = %s
              AND input_mode = 'safety'
              AND status = 'safety_paused'
            LIMIT 1
            """,
            (action["room_id"],),
        ).fetchone():
            return {"status": "safety_paused", "action_id": action_id}

        is_v2 = bool(action.get("draft_id"))
        if is_v2:
            won_claim = transition_action(
                self.conn,
                action_id,
                from_statuses=(action["status"],) if is_player_choice_resume else ("queued", "batched"),
                to_status="resolving",
                metadata={
                    "ai_stage": "retrieving",
                    "reason_code": (
                        "coc_followup_submitted"
                        if is_coc_followup_resume
                        else "coc_background_change_submitted"
                        if is_sanity_background_resume
                        else "composite_choice_submitted"
                        if is_composite_resume
                        else "action_resolution_started"
                    ),
                },
            )
            claimed = self.conn.execute(
                "SELECT * FROM actions WHERE action_id = %s",
                (action_id,),
            ).fetchone() if won_claim else None
        else:
            claimed = self.conn.execute(
                "UPDATE actions SET status = %s WHERE action_id = %s AND status = %s RETURNING *",
                ("resolving", action_id, action["status"]),
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
        if (room.get("integrity_status") or "healthy") != "healthy":
            integrity_status = str(room.get("integrity_status") or "healthy")
            reason = (
                "room_provider_paused"
                if integrity_status == "paused_provider"
                else "room_read_only_recovery"
            )
            await self._reject(action, reason)
            return {"status": "rejected", "action_id": action_id, "reason": reason}
        action_params = self._json_value(action.get("params")) or {}
        action_params.pop("_sanity_background", None)
        if is_coc_followup_resume:
            refreshed_progress = action_params.get("coc_followup_progress")
            if isinstance(refreshed_progress, dict):
                action_params["_coc_followup"] = refreshed_progress
        if is_sanity_background_resume:
            refreshed_progress = action_params.get("sanity_background_progress")
            if isinstance(refreshed_progress, dict):
                action_params["_sanity_background"] = refreshed_progress
        conflict_guard = action_params.get("_conflictGuard")
        allow_same_turn_scene_drift = False
        semantic_guard_valid = False
        if isinstance(conflict_guard, dict):
            try:
                guard_base_version = int(conflict_guard.get("baseStateVersion") or 0)
            except (TypeError, ValueError):
                guard_base_version = -1
            allow_same_turn_scene_drift = self._uses_current_turn_snapshot(
                action,
                guard_base_version,
            )
            from .state_service import validate_action_conflict_guard

            conflict_reason = validate_action_conflict_guard(
                self.conn,
                conflict_guard,
                allow_same_turn_scene_drift=allow_same_turn_scene_drift,
            )
            if conflict_reason:
                return await self._require_action_resync(action, conflict_reason)
            semantic_guard_valid = True
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
                for key in (
                    "hp",
                    "san",
                    "mp",
                    "luck",
                    "status_tags",
                    "temp_modifiers",
                )
                if key in xlsx_data
            }
        status_tags = self._json_value(state_before.get("status_tags")) or []
        sanity_state = self._json_value(
            (self._json_value(state_before.get("temp_modifiers")) or {}).get(
                "coc7_sanity"
            )
        ) or {}
        runtime_package = self._runtime_package_for_room(action["room_id"])
        compiled_bout_transition = self._has_compiled_bout_transition(
            runtime_package,
            action["intent_type"],
            action_params,
        )
        if (
            "permanent_insanity" in status_tags
            or sanity_state.get("insanity_type") == "permanent"
            or sanity_state.get("control") == "ai_keeper"
            and sanity_state.get("phase") in {"bout", "permanent"}
        ) and not (
            sanity_state.get("phase") == "bout" and compiled_bout_transition
        ):
            await self._reject(action, "investigator_not_player_controlled")
            return {
                "status": "rejected",
                "action_id": action_id,
                "reason": "investigator_not_player_controlled",
            }

        scenario = self._load_scenario(room)
        scenario_assets = self._json_value(scenario.get("scenario_assets") if scenario else None) or {}
        runtime_rule_triggers = runtime_package.get("rule_triggers")
        if isinstance(runtime_rule_triggers, list):
            legacy_triggers = scenario_assets.get("triggers")
            merged_triggers = (
                [trigger for trigger in legacy_triggers if isinstance(trigger, dict)]
                if isinstance(legacy_triggers, list)
                else []
            )
            merged_triggers.extend(
                trigger
                for trigger in runtime_rule_triggers
                if isinstance(trigger, dict)
            )
            scenario_assets["triggers"] = merged_triggers
        scenario_assets["rule_policy"] = self._load_rule_policy(dict(room))
        scenario_assets["_party_luck_values"] = self._party_luck_values(
            action["room_id"]
        )
        character_control = self._json_value(runtime_package.get("character_control"))
        scenario_assets["_runtime_character_control"] = (
            character_control if isinstance(character_control, dict) else {}
        )
        scene_row = None
        if character_control or self._runtime_has_sanity_rules(runtime_package):
            scene_row = self.conn.execute(
                "SELECT current_scene, scene_variables FROM room_scene_state WHERE room_id = %s",
                (action["room_id"],),
            ).fetchone()
        scene_variables = self._json_value(
            scene_row.get("scene_variables") if scene_row else None
        )
        scenario_assets["_runtime_scene"] = {
            "current_scene": str(scene_row.get("current_scene") or "") if scene_row else "",
            **(scene_variables if isinstance(scene_variables, dict) else {}),
        }
        runtime_policy = self._json_value(runtime_package.get("runtime_policy"))
        if not isinstance(runtime_policy, dict):
            runtime_policy = {}
        session_mode = str(runtime_policy.get("session_mode") or "")
        is_ai_only = session_mode == "ai_only"
        inventory = self.conn.execute(
            "SELECT * FROM inventory WHERE character_id = %s", (action["character_id"],)
        ).fetchall()

        intent = PlayerIntent(
            action_id=action["action_id"],
            intent_type=action["intent_type"],
            declared_intent=action.get("declared_intent") or "",
            params=action_params,
        )
        autonomy = decide_host_autonomy(
            policy=room.get("host_autonomy_policy"),
            session_mode=session_mode,
            host_connected=self._is_host_connected(action["room_id"]),
            intent_type=intent.intent_type,
            params=intent.params,
        )
        if not is_player_choice_resume and autonomy.route == "deferred_host_review":
            await self._await_host_exception(action, autonomy.reason_code or "host_offline_policy")
            return {
                "status": "awaiting_host_exception",
                "action_id": action_id,
                "reason": autonomy.reason_code or "host_offline_policy",
            }
        if not is_player_choice_resume and autonomy.route == "engine_policy":
            reason_code = autonomy.reason_code or "ai_only_policy_required"
            await self._reject(action, reason_code)
            return {
                "status": "rejected",
                "action_id": action_id,
                "reason": reason_code,
            }
        solo_skill_check, solo_skill_check_error = self._validated_solo_skill_check(
            action["room_id"], intent.params, intent.declared_intent
        )
        if solo_skill_check_error:
            await self._reject(action, solo_skill_check_error)
            return {
                "status": "rejected",
                "action_id": action_id,
                "reason": solo_skill_check_error,
            }
        solo_fixed_healing = None
        solo_fixed_damage = None
        solo_fixed_sanity_loss = None
        solo_daily_penalty_die = None
        solo_damage_transition = None
        solo_item_purchase = None
        reveal_proposals: list[dict[str, Any]] = []
        if is_v2:
            await self._emit_ai_stage(action, "directing")
            director_err = self._validate_director_plan(
                action,
                intent,
                dict(room),
                semantic_guard_valid=semantic_guard_valid,
            )
            if director_err:
                if is_ai_only:
                    await self._reject(action, director_err)
                else:
                    await self._await_host_exception(action, director_err)
                return {
                    "status": "rejected" if is_ai_only else "awaiting_host_exception",
                    "action_id": action_id,
                    "reason": director_err,
                }
            director_plan = intent.params.get("director_plan")
            raw_reveal_proposals = (
                director_plan.get("reveal_proposals")
                if isinstance(director_plan, dict)
                else []
            )
            if isinstance(raw_reveal_proposals, list):
                reveal_proposals = [
                    proposal
                    for proposal in raw_reveal_proposals
                    if isinstance(proposal, dict)
                ][:10]
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
            if is_v2 and intent.params.get("solo_adventure_damage"):
                from ..scenario.solo_runtime import (
                    SoloAdventureRuntime,
                    extract_solo_damage_transition,
                )

                current_solo_scene = SoloAdventureRuntime(self.conn).current(
                    action["room_id"]
                )
                damage_transition = extract_solo_damage_transition(
                    current_solo_scene or {}
                )
                if (
                    not damage_transition
                    or damage_transition["from_node_id"]
                    != str(intent.params.get("fromNodeId") or "")
                ):
                    await self._reject(action, "solo_damage_transition_invalid")
                    return {
                        "status": "rejected",
                        "action_id": action_id,
                        "reason": "solo_damage_transition_invalid",
                    }
                solo_damage_transition = damage_transition
                intent.params["solo_adventure"] = True
            else:
                move_err = await self._validate_move(action, intent)
                if move_err:
                    await self._reject(action, move_err)
                    return {"status": "rejected", "action_id": action_id, "reason": move_err}
            if is_v2 and intent.params.get("solo_adventure"):
                from ..scenario.solo_runtime import (
                    SoloAdventureRuntime,
                    extract_solo_fixed_damage,
                    extract_solo_fixed_healing,
                    extract_solo_fixed_sanity_loss,
                    extract_solo_daily_penalty_die,
                    extract_solo_item_purchase,
                )

                current_solo_scene = SoloAdventureRuntime(self.conn).current(action["room_id"])
                fixed_damage = extract_solo_fixed_damage(current_solo_scene or {})
                healing = extract_solo_fixed_healing(current_solo_scene or {})
                sanity_loss = extract_solo_fixed_sanity_loss(current_solo_scene or {})
                daily_penalty_die = extract_solo_daily_penalty_die(current_solo_scene or {})
                if (
                    fixed_damage
                    and fixed_damage["from_node_id"] == str(intent.params.get("fromNodeId") or "")
                    and fixed_damage["target_node_id"] == str(intent.params.get("targetNodeId") or "")
                ):
                    solo_fixed_damage = fixed_damage
                if (
                    healing
                    and healing["from_node_id"] == str(intent.params.get("fromNodeId") or "")
                    and healing["target_node_id"] == str(intent.params.get("targetNodeId") or "")
                ):
                    solo_fixed_healing = healing
                if sanity_loss and sanity_loss["from_node_id"] == str(intent.params.get("fromNodeId") or "") and sanity_loss["target_node_id"] == str(intent.params.get("targetNodeId") or ""):
                    solo_fixed_sanity_loss = sanity_loss
                if (
                    daily_penalty_die
                    and daily_penalty_die["from_node_id"] == str(intent.params.get("fromNodeId") or "")
                    and daily_penalty_die["target_node_id"] == str(intent.params.get("targetNodeId") or "")
                ):
                    solo_daily_penalty_die = daily_penalty_die
                purchase = extract_solo_item_purchase(
                    current_solo_scene or {}, intent.declared_intent
                )
                if (
                    purchase
                    and purchase["from_node_id"] == str(intent.params.get("fromNodeId") or "")
                    and purchase["target_node_id"] == str(intent.params.get("targetNodeId") or "")
                ):
                    solo_item_purchase = purchase

        # ── Pre-resolution validation for encounter actions ──
        if action["intent_type"] in ("combat_action", "chase_action", "system_skip"):
            enc_err = await self._validate_encounter_action(action, intent)
            if enc_err:
                await self._reject(action, enc_err)
                return {"status": "rejected", "action_id": action_id, "reason": enc_err}

        try:
            await self._emit_ai_stage(action, "validating_rules")
            composite_steps = self._composite_steps(intent.params)
            if composite_steps:
                initial_compiled = await self.compiler.compile(
                    PlayerIntent(
                        action_id=intent.action_id,
                        intent_type=composite_steps[0]["intent_type"],
                        declared_intent=composite_steps[0]["declared_intent"],
                        base_state_version=intent.base_state_version,
                        params=composite_steps[0]["params"],
                    ),
                    scenario or {},
                    character_data,
                )
                compiled, resolution = await self._resolve_composite_action(
                    intent,
                    initial_compiled,
                    composite_steps,
                    scenario or {},
                    character_data,
                    [dict(i) for i in inventory],
                    scenario_assets,
                )
            elif solo_skill_check:
                if solo_skill_check.get("mechanic") == "sanity_check":
                    compiled = MechanicCompileResult(
                        triggeredMechanic="sanity_check",
                        consequence={
                            "success_loss": solo_skill_check["success_loss"],
                            "failure_loss": solo_skill_check["failure_loss"],
                        },
                    )
                else:
                    compiled = MechanicCompileResult(
                        triggeredMechanic="skill_check",
                        skillName=solo_skill_check["skill_name"],
                        difficulty=solo_skill_check["difficulty"],
                    )
            elif intent.params.get("solo_adventure"):
                compiled = MechanicCompileResult(triggeredMechanic="move")
            else:
                compiled = await self.compiler.compile(intent, scenario or {}, character_data)
            if retroactive_decision and retroactive_decision.branch == "roll_required":
                compiled = MechanicCompileResult(triggeredMechanic="luck_check")
            if not composite_steps:
                resolution = await self.rule_executor.execute(
                    intent,
                    compiled,
                    character_data,
                    [dict(i) for i in inventory],
                    scenario_assets,
                )
            if solo_skill_check and solo_skill_check.get("damage_dice"):
                self._apply_solo_damage(
                    resolution,
                    character_data,
                    solo_skill_check["damage_dice"],
                )
            if solo_fixed_damage and resolution.is_success:
                self._apply_solo_fixed_damage(
                    resolution,
                    character_data,
                    int(solo_fixed_damage["amount"]),
                )
            if solo_fixed_healing and resolution.is_success:
                self._apply_solo_fixed_healing(
                    resolution,
                    character_data,
                    int(solo_fixed_healing["amount"]),
                )
            if solo_fixed_sanity_loss and resolution.is_success:
                self._apply_solo_fixed_sanity_loss(resolution, character_data, solo_fixed_sanity_loss["loss_dice"])
            if solo_damage_transition and resolution.is_success:
                self._apply_solo_damage(
                    resolution,
                    character_data,
                    solo_damage_transition["damage_dice"],
                )
        except Exception as exc:
            await self._reject(action, f"resolution failed: {exc}")
            return {"status": "rejected", "action_id": action_id, "reason": str(exc)}
        follow_up_error = (resolution.metadata or {}).get("follow_up_error")
        if is_v2 and follow_up_error:
            return await self._require_action_resync(action, str(follow_up_error))
        composite_state = (resolution.metadata or {}).get("composite_action")
        if (
            is_v2
            and isinstance(composite_state, dict)
            and isinstance(composite_state.get("awaiting_choice"), dict)
        ):
            return await self._await_composite_choice(action, resolution)
        resolution.narrative = self._render_fallback_narrative(intent, compiled, resolution, character_data)
        coc_follow_up = (resolution.metadata or {}).get("follow_up")
        if (
            is_v2
            and not is_coc_followup_resume
            and isinstance(coc_follow_up, dict)
            and coc_follow_up.get("status") == "pending"
        ):
            return await self._await_coc_followup(
                action,
                character_data,
                resolution,
                state_before=state_before,
            )
        sanity_background = (resolution.metadata or {}).get("background_change")
        if (
            is_v2
            and not is_sanity_background_resume
            and isinstance(sanity_background, dict)
            and sanity_background.get("status") == "pending"
        ):
            return await self._await_sanity_background(
                action,
                character_data,
                resolution,
                state_before=state_before,
            )

        inventory_changes = []
        if retroactive_decision:
            resolution.metadata["retroactive_item_claim"] = {
                "branch": retroactive_decision.branch,
                "claimed_item_name": retroactive_decision.claimed_item_name,
            }
            if resolution.is_success:
                item = retroactive_decision.item
                narrative = item.get("narrative") or {}
                inventory_changes.append(
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
                )
        if solo_item_purchase:
            resolution.metadata["solo_item_purchase"] = {
                "name": solo_item_purchase["name"],
                "source": solo_item_purchase["source"],
                "citation": solo_item_purchase["citation"],
            }
            existing_purchase = self.conn.execute(
                "SELECT 1 FROM inventory WHERE character_id = %s AND source = %s LIMIT 1",
                (action["character_id"], solo_item_purchase["source"]),
            ).fetchone()
            if resolution.is_success and not existing_purchase:
                inventory_changes.append(
                    {
                        "characterId": action["character_id"],
                        "itemAdd": {
                            "name": solo_item_purchase["name"],
                            "description": solo_item_purchase["description"],
                            "quantity": 1,
                            "isSecret": False,
                            "source": solo_item_purchase["source"],
                        },
                    }
                )
        if not inventory_changes:
            inventory_changes = None

        generic_scene_transition = intent.params.get("generic_scene_progression")
        scene_change = None
        if (
            is_v2
            and resolution.is_success
            and isinstance(generic_scene_transition, dict)
            and not generic_scene_transition.get("already_applied")
        ):
            target_scene_id = str(generic_scene_transition.get("target_scene_id") or "")
            if target_scene_id:
                from ..models import SceneChange

                scene_change = SceneChange(currentScene=target_scene_id)
                resolution.metadata = {
                    **(resolution.metadata or {}),
                    "generic_scene_transition": generic_scene_transition,
                }

        result_payload = resolution.model_dump(by_alias=True)
        completion_status = "completed" if is_v2 else "resolved"
        completed_with_state = False
        sanity_state_transition = self._has_sanity_state_transition(resolution)
        character_control_revoked = False
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
            if is_ai_only:
                await self._reject(action, reason_code)
            else:
                await self._await_host_exception(
                    action,
                    reason_code,
                    result=result_payload,
                )
            return {
                "status": "rejected" if is_ai_only else "awaiting_host_exception",
                "action_id": action_id,
                "reason": reason_code,
            }
        pending_rule_suggestions = (resolution.metadata or {}).get(
            "pending_rule_suggestions"
        )
        host_rule_suggestions = [
            suggestion
            for suggestion in pending_rule_suggestions or []
            if isinstance(suggestion, dict)
            and suggestion.get("status") == "pending_host_confirmation"
        ] if isinstance(pending_rule_suggestions, list) else []
        if is_v2 and host_rule_suggestions:
            first_suggestion = host_rule_suggestions[0]
            reason_code = (
                str(first_suggestion.get("reason_code") or "rule_confirmation_required")
                if isinstance(first_suggestion, dict)
                else "rule_confirmation_required"
            )
            if is_ai_only:
                await self._reject(action, reason_code)
            else:
                await self._await_host_exception(
                    action,
                    reason_code,
                    result=result_payload,
                )
            return {
                "status": "rejected" if is_ai_only else "awaiting_host_exception",
                "action_id": action_id,
                "reason": reason_code,
            }
        narration_applied_before_state = False
        if (
            is_v2
            and sanity_state_transition
            and self.gateway
            and hasattr(self.gateway, "narrate_action")
        ):
            await self._emit_ai_stage(action, "narrating")
            narration_error = await self._apply_narrator(
                action,
                character_data,
                dict(room),
                resolution,
                ai_only=is_ai_only,
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
            narration_applied_before_state = True
        state_mutations = self._state_service_mutations(resolution.mutations)
        has_state_changes = bool(state_mutations or inventory_changes or scene_change)
        if has_state_changes and not self.state_service and is_v2:
            if is_ai_only:
                await self._pause_room_for_integrity(
                    action,
                    "state_service_unavailable",
                )
            else:
                await self._await_host_exception(
                    action,
                    "state_service_unavailable",
                )
            return {
                "status": "rejected" if is_ai_only else "awaiting_host_exception",
                "action_id": action_id,
                "reason": "state_service_unavailable",
            }

        state_changes = None
        if has_state_changes:
            from ..models import StateChangeSet, CharacterMutationItem

            state_changes = StateChangeSet(
                characterMutations=[
                    CharacterMutationItem(
                        characterId=action["character_id"],
                        mutations=state_mutations,
                    )
                ] if state_mutations else [],
                sceneChanges=scene_change,
                inventoryChanges=inventory_changes,
            )

        committed_reveals: list[dict[str, Any]] = []
        reveal_proposals_to_commit = (
            reveal_proposals if resolution.is_success else []
        )

        def commit_reveals(transaction) -> list[dict[str, Any]]:
            if not reveal_proposals_to_commit:
                return []
            from .reveal_ledger import RevealLedger

            ledger = RevealLedger(self.conn)
            validated = ledger.validate_proposals(
                room_id=action["room_id"],
                actor_character_id=action["character_id"],
                proposals=reveal_proposals_to_commit,
                executor=transaction,
            )
            state_row = transaction.execute(
                "SELECT state_version FROM rooms WHERE room_id = %s",
                (action["room_id"],),
            ).fetchone()
            return ledger.commit_validated(
                room_id=action["room_id"],
                source_action_id=action["action_id"],
                actor_character_id=action["character_id"],
                proposals=validated,
                state_version=int(state_row.get("state_version") or 0),
                executor=transaction,
            )

        try:
            if is_v2 and isinstance(conflict_guard, dict):
                from .state_service import (
                    acquire_action_conflict_locks,
                    validate_action_conflict_guard,
                )

                commit_conflict_reason = None
                with self.conn.transaction() as tx:
                    acquire_action_conflict_locks(tx, conflict_guard)
                    commit_conflict_reason = validate_action_conflict_guard(
                        tx,
                        conflict_guard,
                        allow_same_turn_scene_drift=allow_same_turn_scene_drift,
                    )
                    if not commit_conflict_reason and state_changes is not None:
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
                        state_version_row = tx.execute(
                            "SELECT state_version FROM rooms WHERE room_id = %s",
                            (action["room_id"],),
                        ).fetchone()
                        resolution.metadata = {
                            **dict(resolution.metadata or {}),
                            "receipt_state_version": int(
                                state_version_row.get("state_version") or 0
                            ) if state_version_row else 0,
                        }
                        result_payload = resolution.model_dump(by_alias=True)
                        rule_explanation_for_completion = self._build_rule_explanation(
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
                    if not commit_conflict_reason:
                        if sanity_state_transition:
                            character_control_revoked = (
                                self._apply_character_control_transition(
                                    tx,
                                    action,
                                    resolution,
                                )
                                or character_control_revoked
                            )
                        committed_reveals = commit_reveals(tx)
                        if (
                            state_changes is not None
                            and sanity_state_transition
                        ):
                            rule_explanation_for_completion = (
                                rule_explanation_for_completion
                                or self._build_rule_explanation(
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
                            )
                            if not complete_action(
                                self.conn,
                                action_id,
                                from_statuses=("resolving",),
                                to_status=completion_status,
                                result=result_payload,
                                receipt=rule_explanation_for_completion,
                                metadata={"has_rule_explanation": True},
                                transaction=tx,
                            ):
                                raise RuntimeError("action_completion_conflict")
                            completed_with_state = True
                if commit_conflict_reason:
                    return await self._require_action_resync(
                        action,
                        commit_conflict_reason,
                    )
            elif state_changes is not None and self.state_service:
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
                        state_version_row = tx.execute(
                            "SELECT state_version FROM rooms WHERE room_id = %s",
                            (action["room_id"],),
                        ).fetchone()
                        resolution.metadata = {
                            **dict(resolution.metadata or {}),
                            "receipt_state_version": int(
                                state_version_row.get("state_version") or 0
                            ) if state_version_row else 0,
                        }
                        result_payload = resolution.model_dump(by_alias=True)
                        if sanity_state_transition:
                            character_control_revoked = (
                                self._apply_character_control_transition(
                                    tx,
                                    action,
                                    resolution,
                                )
                                or character_control_revoked
                            )
                        rule_explanation_for_completion = self._build_rule_explanation(
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
                        committed_reveals = commit_reveals(tx)
                        if sanity_state_transition:
                            if not complete_action(
                                self.conn,
                                action_id,
                                from_statuses=("resolving",),
                                to_status=completion_status,
                                result=result_payload,
                                receipt=rule_explanation_for_completion,
                                metadata={"has_rule_explanation": True},
                                transaction=tx,
                            ):
                                raise RuntimeError("action_completion_conflict")
                            completed_with_state = True
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
            elif is_v2 and reveal_proposals_to_commit:
                with self.conn.transaction() as tx:
                    committed_reveals = commit_reveals(tx)
        except RevealPolicyError as exc:
            await self._reject(action, exc.code)
            return {
                "status": "rejected",
                "action_id": action_id,
                "reason": exc.code,
            }
        except Exception:
            logger.exception("StateService failed for action %s", action["action_id"])
            if is_v2:
                if is_ai_only:
                    await self._pause_room_for_integrity(
                        action,
                        "state_persistence_failed",
                    )
                else:
                    await self._await_host_exception(
                        action,
                        "state_persistence_failed",
                    )
                return {
                    "status": "rejected" if is_ai_only else "awaiting_host_exception",
                    "action_id": action_id,
                    "reason": "state_persistence_failed",
                }

        if character_control_revoked:
            await self._revoke_character_player_connection(action)

        if committed_reveals:
            resolution.metadata = {
                **dict(resolution.metadata or {}),
                "fact_reveals": [
                    {
                        "reveal_id": record["reveal_id"],
                        "fact_id": record["fact_id"],
                        "audience": record["audience"],
                        "state_version": record["state_version"],
                        "event_sequence": record["event_sequence"],
                    }
                    for record in committed_reveals
                ],
            }
            result_payload = resolution.model_dump(by_alias=True)
            publisher = getattr(
                self.dispatcher,
                "publish_committed_fact_event",
                None,
            )
            if publisher:
                for record in committed_reveals:
                    try:
                        published = await publisher(
                            action["room_id"],
                            record["event_sequence"],
                        )
                        if not published:
                            logger.error(
                                "Committed fact event failed ledger publication "
                                "room=%s sequence=%s",
                                action["room_id"],
                                record["event_sequence"],
                            )
                    except Exception:
                        logger.exception(
                            "Committed fact event publication failed "
                            "room=%s sequence=%s",
                            action["room_id"],
                            record["event_sequence"],
                        )

        solo_transition = None
        solo_target_node_id = ""
        solo_from_node_id = ""
        solo_damage_terminal = False
        verified_ending = None
        if is_v2 and solo_damage_transition and resolution.is_success:
            damage_metadata = resolution.metadata or {}
            if solo_damage_transition.get("target_node_id"):
                solo_damage_terminal = bool(
                    solo_damage_transition.get("damage_ends_on_zero")
                    and int(damage_metadata.get("hp_after", 0) or 0) <= 0
                )
                if not solo_damage_terminal:
                    solo_target_node_id = solo_damage_transition["target_node_id"]
            else:
                sheet = character_data.get("xlsx_data")
                if not isinstance(sheet, dict):
                    sheet = {}
                hp_max = max(1, int(sheet.get("hp_max", sheet.get("max_hp", 1)) or 1))
                damage = int(damage_metadata.get("damage", 0) or 0)
                solo_target_node_id = (
                    solo_damage_transition["high_damage_target_node_id"]
                    if damage >= (hp_max + 1) // 2
                    else solo_damage_transition["low_damage_target_node_id"]
                )
            solo_from_node_id = solo_damage_transition["from_node_id"]
        elif is_v2 and intent.params.get("solo_adventure") and resolution.is_success:
            solo_target_node_id = str(intent.params.get("targetNodeId") or "")
            solo_from_node_id = str(intent.params.get("fromNodeId") or "")
        elif is_v2 and solo_skill_check:
            if solo_skill_check.get("mechanic") == "sanity_check":
                if solo_skill_check.get("target_node_id"):
                    solo_target_node_id = str(solo_skill_check["target_node_id"])
                else:
                    solo_target_node_id = str(
                        solo_skill_check[
                            "success_target_node_id"
                            if resolution.is_success
                            else "failure_target_node_id"
                        ]
                    )
            else:
                solo_target_node_id = str(
                    solo_skill_check[
                        "success_target_node_id"
                        if resolution.is_success
                        else "failure_target_node_id"
                    ]
                )
            solo_from_node_id = solo_skill_check["from_node_id"]
        if solo_target_node_id:
            try:
                from ..scenario.solo_runtime import SoloAdventureRuntime
                with self.conn.transaction() as tx:
                    if solo_daily_penalty_die:
                        resolution.metadata = {
                            **dict(resolution.metadata or {}),
                            "solo_skill_bonus_dice": int(solo_daily_penalty_die["bonus_dice"]),
                            "solo_skill_bonus_dice_citation": solo_daily_penalty_die["citation"],
                        }
                    solo_transition = SoloAdventureRuntime(self.conn).transition(
                        action["room_id"],
                        from_node_id=solo_from_node_id,
                        target_node_id=solo_target_node_id,
                        scene_variables=(
                            {"solo_skill_bonus_dice": int(solo_daily_penalty_die["bonus_dice"])}
                            if solo_daily_penalty_die
                            else None
                        ),
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
                        state_before=state_before,
                        state_after=self._runtime_snapshot(
                            tx,
                            action["character_id"],
                            action["room_id"],
                        ),
                    )
                    rule_explanation_for_completion = rule_explanation
            except Exception as exc:
                await self._reject(action, f"solo_transition_failed:{exc}")
                return {"status": "rejected", "action_id": action_id, "reason": str(exc)}
        elif solo_damage_terminal:
            with self.conn.transaction() as tx:
                tx.execute(
                    "UPDATE rooms SET status = 'completed', state_version = state_version + 1 "
                    "WHERE room_id = %s AND status IN ('suggested', 'active')",
                    (action["room_id"],),
                )
            resolution.metadata["solo_adventure_terminal"] = {
                "reason": "hp_zero",
                "citation": solo_damage_transition.get("citation") or {},
            }
            resolution.narrative = "火焰带走了你最后的力气。你的冒险到此结束。"
            result_payload = resolution.model_dump(by_alias=True)

        if is_v2 and resolution.is_success and not solo_damage_terminal:
            discovered_runtime_clues = await self._persist_named_runtime_clues(
                action,
                intent,
            )
            if discovered_runtime_clues:
                resolution.metadata = {
                    **(resolution.metadata or {}),
                    "runtime_clue_discoveries": discovered_runtime_clues,
                }
                result_payload = resolution.model_dump(by_alias=True)
            verified_ending = self._evaluate_verified_runtime_ending(action["room_id"])
            if verified_ending:
                resolution.metadata = {
                    **(resolution.metadata or {}),
                    "verified_ending": {
                        "ending_id": verified_ending.ending_id,
                        "ending_type": verified_ending.ending_type,
                        "citation": verified_ending.citation,
                    },
                }
                result_payload = resolution.model_dump(by_alias=True)

        if (
            not solo_damage_terminal
            and not narration_applied_before_state
            and self.gateway
            and hasattr(self.gateway, "narrate_action")
        ):
            await self._emit_ai_stage(action, "narrating")
            narration_error = await self._apply_narrator(
                action,
                character_data,
                dict(room),
                resolution,
                ai_only=is_ai_only,
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

        ending_committed = False
        if verified_ending:
            ending_committed = self._commit_verified_runtime_ending(
                action["room_id"],
                verified_ending,
            )
            if ending_committed:
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
                rule_explanation_for_completion = rule_explanation
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

        rule_explanation_for_bundle = rule_explanation_for_completion or self._build_rule_explanation(
            action,
            character_data,
            resolution,
            state_before=state_before,
            state_after=self._runtime_snapshot(
                self.conn,
                action["character_id"],
                action["room_id"],
            ) or state_before,
        )
        bundle = self._persist_resolution_bundle(
            action,
            completion_status,
            result_payload,
            rule_explanation_for_bundle,
            resolution,
        )
        try:
            await self._project(action, resolution, bundle)
        except Exception:
            logger.exception("Projection failed for completed action %s", action_id)
            self._mark_resolution_bundle_projection_pending(bundle)
        if ending_committed:
            await self.dispatcher.emit(
                action["room_id"],
                "s2c_campaign_ended",
                "party",
                {
                    "ending_id": verified_ending.ending_id,
                    "ending_type": verified_ending.ending_type,
                    "citation": verified_ending.citation,
                    "completion_source": "verified_runtime_ending",
                },
            )
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
        prepared_reactions = []
        if action["intent_type"] in ("combat_action", "chase_action", "system_skip"):
            prepared_reactions = await self._apply_encounter_result(action, intent, resolution)

        if isinstance(intent.params, dict) and intent.params.get("preparedReaction"):
            from .prepared_rule_actions import complete_triggered_prepared_reaction

            complete_triggered_prepared_reaction(
                self.conn,
                reaction_action_id=action_id,
                terminal_status="completed",
            )

        for prepared_reaction in prepared_reactions:
            await self.resolve_action(prepared_reaction["reaction_action_id"])

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
        if target is None:
            target = metadata.get("skill_value", metadata.get("skillValue"))
        raw_rolls = self._raw_rolls(resolution)
        rule_set_version = action.get("rule_set_version_id") or "unversioned"
        params = self._json_value(action.get("params")) or {}
        analysis = params.get("analysis") if isinstance(params.get("analysis"), dict) else {}
        citations = analysis.get("citations") if isinstance(analysis.get("citations"), list) else []
        hidden_effects = metadata.get("hidden_modifiers")
        hidden_sources = []
        if isinstance(hidden_effects, list):
            for item in hidden_effects:
                if not isinstance(item, dict) or item.get("effect") is None:
                    continue
                source = str(item.get("source") or "hidden")
                commitment = hashlib.sha256(
                    f"{action['action_id']}\x00{rule_set_version}\x00{source}".encode("utf-8")
                ).hexdigest()
                hidden_sources.append({
                    "source": "hidden",
                    "effect": item.get("effect"),
                    "source_commitment": commitment,
                })
        locked_inputs = metadata.get("receipt_locked_inputs")
        if not isinstance(locked_inputs, dict):
            locked_inputs = {
                "intent_type": action.get("intent_type"),
                "declared_intent": action.get("declared_intent") or "",
                "mechanic": resolution.mechanic,
            }
        else:
            locked_inputs = json.loads(
                json.dumps(locked_inputs, ensure_ascii=False, default=str)
            )
        if hidden_sources:
            locked_inputs["hidden_source_commitments"] = [
                source["source_commitment"] for source in hidden_sources
            ]

        receipt_state_version = metadata.get("receipt_state_version")
        if not isinstance(receipt_state_version, int):
            conflict_guard = params.get("_conflictGuard")
            receipt_state_version = (
                conflict_guard.get("baseStateVersion")
                if isinstance(conflict_guard, dict)
                and isinstance(conflict_guard.get("baseStateVersion"), int)
                else None
            )
        if not isinstance(receipt_state_version, int):
            room_id = action.get("room_id") or resolution.room_id
            room_state = (
                self.conn.execute(
                    "SELECT state_version FROM rooms WHERE room_id = %s",
                    (room_id,),
                ).fetchone()
                if self.conn is not None and room_id
                else None
            )
            receipt_state_version = int(room_state.get("state_version") or 0) if room_state else 0
        purpose = str(metadata.get("receipt_purpose") or f"{resolution.mechanic}.initial")
        receipt_draws = metadata.get("receipt_raw_draws")
        if not isinstance(receipt_draws, list):
            receipt_draws = raw_rolls
        verification_receipt = None
        if raw_rolls or metadata.get("receipt_purpose"):
            receipt_room_id = str(action.get("room_id") or resolution.room_id)
            verification_receipt = create_roll_receipt(
                version="v2",
                room_id=receipt_room_id,
                state_version=receipt_state_version,
                action_id=action["action_id"],
                purpose=purpose,
                rule_set_version=rule_set_version,
                locked_inputs=locked_inputs,
                raw_draws=receipt_draws,
                idempotency_key=str(action.get("idempotency_key") or action["action_id"]),
            )
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
                "success_level": metadata.get("success_level") or metadata.get("level"),
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

    async def _require_action_resync(
        self,
        action: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        category = {
            "scene_context_changed": "scene",
            "risk_context_changed": "risk",
            "resource_conflict": "resource",
            "actor_state_changed": "actor",
            "target_state_changed": "target",
        }.get(reason, "context")
        transitioned = transition_action(
            self.conn,
            action["action_id"],
            from_statuses=("resolving",),
            to_status="sync_required",
            metadata={
                "reason_code": reason,
                "conflict_category": category,
            },
        )
        if transitioned:
            await self.dispatcher.emit(
                action["room_id"],
                "s2c_private_notice",
                "player",
                {
                    "kind": "action_resync_required",
                    "actionId": action["action_id"],
                    "characterId": action["character_id"],
                    "reasonCode": reason,
                },
                character_id=action["character_id"],
            )
        current = self.conn.execute(
            "SELECT status FROM actions WHERE action_id = %s",
            (action["action_id"],),
        ).fetchone()
        return {
            "status": current["status"] if current else "missing",
            "action_id": action["action_id"],
            "reason": reason,
        }

    def _validate_director_plan(
        self,
        action: dict[str, Any],
        intent: PlayerIntent,
        room: dict[str, Any],
        *,
        semantic_guard_valid: bool = False,
    ) -> str | None:
        plan = intent.params.get("director_plan")
        if not isinstance(plan, dict):
            return "director_plan_required"
        if plan.get("state_patch_authority") != "advisory_only":
            return "director_plan_unverified"
        context_version = plan.get("context_version")
        uses_turn_snapshot = False
        if context_version is not None:
            try:
                expected_context_version = int(context_version)
                current_state_version = int(room.get("state_version") or 0)
                uses_turn_snapshot = self._uses_current_turn_snapshot(
                    action,
                    expected_context_version,
                )
                if (
                    expected_context_version != current_state_version
                    and not uses_turn_snapshot
                    and not semantic_guard_valid
                ):
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
                    if (
                        expected is not None
                        and int(expected) != int(room.get("state_version") or 0)
                        and not uses_turn_snapshot
                        and not semantic_guard_valid
                    ):
                        return "director_precondition_failed"
                except (TypeError, ValueError):
                    return "director_preconditions_invalid"
            elif kind in {"position", "resource", "visibility", "permission"}:
                return "director_precondition_unverified"
            else:
                return "director_precondition_unsupported"
        return None

    def _is_host_connected(self, room_id: str) -> bool:
        if self.host_connection_checker is None:
            return True
        try:
            return bool(self.host_connection_checker(room_id))
        except Exception:
            logger.warning("Host connection check failed for room=%s", room_id)
            return False

    def _uses_current_turn_snapshot(
        self,
        action: dict[str, Any],
        context_version: int,
    ) -> bool:
        turn_id = str(action.get("turn_id") or "")
        if not turn_id:
            return False
        turn = self.conn.execute(
            "SELECT room_id, status, base_state_version FROM room_turns WHERE turn_id = %s",
            (turn_id,),
        ).fetchone()
        if not turn or turn.get("room_id") != action.get("room_id"):
            return False
        if turn.get("status") != "resolving":
            return False
        try:
            return int(turn.get("base_state_version") or 0) == context_version
        except (TypeError, ValueError):
            return False

    def _validated_solo_skill_check(
        self,
        room_id: str,
        params: dict[str, Any],
        declared_intent: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        raw = params.get("solo_adventure_check")
        if raw is None:
            return None, None
        if not isinstance(raw, dict):
            return None, "solo_skill_check_invalid"
        from ..scenario.solo_runtime import SoloAdventureRuntime, extract_solo_skill_check

        scene = SoloAdventureRuntime(self.conn).current(room_id)
        rule = extract_solo_skill_check(scene or {}, declared_intent)
        if not rule:
            return None, "solo_skill_check_invalid"
        if rule.get("mechanic") == "sanity_check":
            expected = {
                "mechanic": "sanity_check",
                "fromNodeId": rule["from_node_id"],
                "successLoss": rule["success_loss"],
                "failureLoss": rule["failure_loss"],
            }
            if rule.get("target_node_id"):
                expected["targetNodeId"] = rule["target_node_id"]
            else:
                expected["successTargetNodeId"] = rule["success_target_node_id"]
                expected["failureTargetNodeId"] = rule["failure_target_node_id"]
        else:
            expected = {
                "fromNodeId": rule["from_node_id"],
                "successTargetNodeId": rule["success_target_node_id"],
                "failureTargetNodeId": rule["failure_target_node_id"],
            }
            if rule.get("damage_dice"):
                expected["damageDice"] = rule["damage_dice"]
                expected["damageEndsOnZero"] = bool(rule.get("damage_ends_on_zero"))
        if any(str(raw.get(key) or "") != str(value) for key, value in expected.items()):
            return None, "solo_skill_check_invalid"
        if (
            str(params.get("skillName") or "") != rule["skill_name"]
            or str(params.get("difficulty") or "") != rule["difficulty"]
        ):
            return None, "solo_skill_check_invalid"
        return rule, None

    @staticmethod
    def _apply_solo_damage(
        resolution: ResolutionResult,
        character: dict[str, Any],
        damage_dice: str,
    ) -> dict[str, int]:
        from ..rules.coc_handlers import roll_dice

        sheet = character.get("xlsx_data")
        if not isinstance(sheet, dict):
            sheet = {}
        hp_before = max(0, int(sheet.get("hp", 0) or 0))
        damage, draws, modifier = roll_dice(damage_dice)
        hp_after = max(0, hp_before - damage)
        metadata = dict(resolution.metadata or {})
        metadata["damage"] = damage
        metadata["damage_dice"] = damage_dice
        metadata["hp_before"] = hp_before
        metadata["hp_after"] = hp_after
        resolution.metadata = metadata
        resolution.mutations = [
            {"op": "replace", "path": "/character/hp", "value": hp_after},
            *resolution.mutations,
        ]
        resolution.reveal_steps = [
            {
                "kind": "damage",
                "dice": damage_dice,
                "result": damage,
                "rollTrace": {"draws": draws, "modifier": modifier},
            },
            *resolution.reveal_steps,
        ]
        return {"damage": damage, "hp_before": hp_before, "hp_after": hp_after}

    @staticmethod
    def _apply_solo_fixed_damage(
        resolution: ResolutionResult,
        character: dict[str, Any],
        amount: int,
    ) -> dict[str, int]:
        sheet = character.get("xlsx_data")
        if not isinstance(sheet, dict):
            sheet = {}
        hp_before = max(0, int(sheet.get("hp", 0) or 0))
        damage = max(0, amount)
        hp_after = max(0, hp_before - damage)
        metadata = dict(resolution.metadata or {})
        metadata["fixed_damage"] = damage
        metadata["hp_before"] = hp_before
        metadata["hp_after"] = hp_after
        resolution.metadata = metadata
        resolution.mutations = [
            {"op": "replace", "path": "/character/hp", "value": hp_after},
            *resolution.mutations,
        ]
        resolution.reveal_steps = [
            {"kind": "damage", "amount": damage},
            *resolution.reveal_steps,
        ]
        return {"damage": damage, "hp_before": hp_before, "hp_after": hp_after}

    @staticmethod
    def _apply_solo_fixed_healing(
        resolution: ResolutionResult,
        character: dict[str, Any],
        amount: int,
    ) -> dict[str, int]:
        sheet = character.get("xlsx_data")
        if not isinstance(sheet, dict):
            sheet = {}
        hp_before = max(0, int(sheet.get("hp", 0) or 0))
        hp_max = max(
            hp_before,
            int(sheet.get("hp_max", sheet.get("max_hp", hp_before)) or hp_before),
        )
        hp_after = min(hp_max, hp_before + max(0, amount))
        metadata = dict(resolution.metadata or {})
        metadata["fixed_healing"] = hp_after - hp_before
        metadata["hp_before"] = hp_before
        metadata["hp_after"] = hp_after
        resolution.metadata = metadata
        resolution.mutations = [
            {"op": "replace", "path": "/character/hp", "value": hp_after},
            *resolution.mutations,
        ]
        resolution.reveal_steps = [
            {"kind": "healing", "amount": hp_after - hp_before},
            *resolution.reveal_steps,
        ]
        return {
            "healing": hp_after - hp_before,
            "hp_before": hp_before,
            "hp_after": hp_after,
        }

    @staticmethod
    def _apply_solo_fixed_sanity_loss(resolution: ResolutionResult, character: dict[str, Any], loss_dice: str) -> None:
        from ..rules.coc_handlers import roll_dice

        sheet = character.get("xlsx_data") if isinstance(character.get("xlsx_data"), dict) else {}
        before = max(0, int(sheet.get("san", 0) or 0))
        loss, draws, modifier = roll_dice(loss_dice)
        after = max(0, before - loss)
        resolution.metadata = {**dict(resolution.metadata or {}), "fixed_sanity_loss": loss, "san_before": before, "san_after": after}
        resolution.mutations = [{"op": "replace", "path": "/character/san", "value": after}, *resolution.mutations]
        resolution.reveal_steps = [{"kind": "san_loss", "loss": loss, "dice": loss_dice, "rollTrace": {"draws": draws, "modifier": modifier}}, *resolution.reveal_steps]

    @staticmethod
    def _runtime_snapshot(executor, character_id: str, room_id: str) -> dict[str, Any]:
        try:
            row = executor.execute(
                "SELECT hp, san, mp, luck, status_tags, temp_modifiers "
                "FROM character_runtime_state "
                "WHERE character_id = %s AND room_id = %s",
                (character_id, room_id),
            ).fetchone()
        except Exception:
            return {}
        if not row:
            return {}
        snapshot = dict(row)
        for key, fallback in (("status_tags", []), ("temp_modifiers", {})):
            value = snapshot.get(key)
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    value = fallback
            snapshot[key] = value if isinstance(value, type(fallback)) else fallback
        return snapshot

    def _party_luck_values(self, room_id: str) -> list[int]:
        values: list[int] = []
        try:
            rows = self.conn.execute(
                "SELECT luck FROM character_runtime_state WHERE room_id = %s",
                (room_id,),
            ).fetchall()
        except Exception:
            rows = []
        for row in rows:
            try:
                values.append(max(0, int(row["luck"] or 0)))
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(values)

    @staticmethod
    def _raw_rolls(resolution: ResolutionResult) -> list[dict[str, Any]]:
        rolls = []
        for step in resolution.reveal_steps:
            if not isinstance(step, dict) or step.get("kind") not in ("roll", "damage"):
                continue
            if step.get("kind") == "damage" and not step.get("dice"):
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
        room_id = str(room.get("room_id") or "")
        player_experience_version = str(
            room.get("player_experience_version") or ""
        )
        if room_id and not player_experience_version:
            try:
                version_row = self.conn.execute(
                    "SELECT player_experience_version FROM rooms "
                    "WHERE room_id = %s",
                    (room_id,),
                ).fetchone()
                player_experience_version = str(
                    version_row.get("player_experience_version") or ""
                ) if version_row else ""
            except Exception:
                player_experience_version = ""
        if room_id:
            try:
                from ..ai.ai_config import get_room_ai_config
                from ..ai.rule_policy_compiler import (
                    validate_compiled_rule_artifact,
                )

                room_ai_config = get_room_ai_config(self.conn, room_id) or {}
                runtime_binding = room_ai_config.get("runtime_binding")
                if (
                    isinstance(runtime_binding, dict)
                    and runtime_binding.get("locked") is True
                ):
                    frozen_sources = runtime_binding.get(
                        "rule_policy_sources"
                    )
                    compiled = runtime_binding.get("compiled_rule_policy")
                    runtime_package_artifact_id = str(
                        runtime_binding.get("runtime_package_artifact_id")
                        or ""
                    )
                    artifact_id = str(
                        runtime_binding.get("compiled_rule_artifact_id")
                        or ""
                    )
                    if not (
                        isinstance(frozen_sources, list)
                        and isinstance(compiled, dict)
                        and validate_compiled_rule_artifact(
                            runtime_package_artifact_id=(
                                runtime_package_artifact_id
                            ),
                            sources=frozen_sources,
                            compiled_rule_policy=compiled,
                            artifact_id=artifact_id,
                        )
                    ):
                        logger.error(
                            "Frozen rule artifact invalid room=%s",
                            room_id,
                        )
                        return {}
                    policy = compiled.get("policy")
                    compiled_sources = compiled.get("sources")
                    if not (
                        isinstance(policy, dict)
                        and isinstance(compiled_sources, list)
                    ):
                        return {}
                    merged = dict(policy)
                    if compiled_sources:
                        merged["_sources"] = [
                            {
                                "scope": str(
                                    source.get("scope") or "room"
                                ),
                                "rule_set_version_id": str(
                                    source.get("rule_set_version_id") or ""
                                ),
                            }
                            for source in compiled_sources
                            if isinstance(source, dict)
                        ]
                    return merged
                if player_experience_version != "v1":
                    logger.error(
                        "Non-legacy room missing locked rule artifact room=%s",
                        room_id,
                    )
                    return {}
            except Exception as exc:
                logger.warning(
                    "Failed to load frozen rule policy room=%s: %s",
                    room_id,
                    exc,
                )
                return {}
        elif player_experience_version != "v1":
            return {}
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
        params = self._json_value(action.get("params")) or {}
        if params.get("preparedReaction"):
            from .prepared_rule_actions import complete_triggered_prepared_reaction

            complete_triggered_prepared_reaction(
                self.conn,
                reaction_action_id=action["action_id"],
                terminal_status="rejected",
            )
        await self.dispatcher.emit(
            action["room_id"],
            "s2c_action_completed",
            "player",
            {"actionId": action["action_id"], "status": "rejected", "reason": reason},
            character_id=action["character_id"],
        )

    async def _pause_room_for_integrity(
        self,
        action: dict[str, Any],
        reason: str,
    ) -> None:
        payload = {"reason": reason}
        with self.conn.transaction() as tx:
            complete_action(
                self.conn,
                action["action_id"],
                from_statuses=("resolving",),
                to_status="rejected",
                result=payload,
                metadata={"reason_code": "room_integrity_paused"},
                transaction=tx,
            )
            tx.execute(
                "UPDATE rooms SET status = 'paused', "
                "integrity_status = 'read_only_recovery', integrity_reason = %s, "
                "integrity_source = 'resolution_pipeline', "
                "integrity_state_version = state_version, integrity_updated_at = NOW() "
                "WHERE room_id = %s",
                (reason, action["room_id"]),
            )
        await self.dispatcher.emit(
            action["room_id"],
            "s2c_action_completed",
            "player",
            {
                "actionId": action["action_id"],
                "status": "rejected",
                "reason": reason,
            },
            character_id=action["character_id"],
        )
        await self.dispatcher.emit(
            action["room_id"],
            "s2c_room_paused",
            "party",
            {"reasonCode": reason, "mode": "read_only_recovery"},
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
        await self.dispatcher.emit(
            action["room_id"],
            "s2c_action_deferred",
            "player",
            {
                "actionId": action["action_id"],
                "status": "awaiting_host_exception",
                "reasonCode": reason_code,
            },
            character_id=action["character_id"],
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

    def _apply_verified_narration_fallback(
        self,
        context: dict[str, Any],
        action: dict[str, Any],
        resolution: ResolutionResult,
        *,
        rejected_provider_reason: str | None = None,
    ) -> None:
        narration = build_verified_narration(
            context,
            action_id=action["action_id"],
        )
        resolution.narrative = narration.narrative_text
        metadata = dict(resolution.metadata or {})
        metadata["narration"] = narration.model_dump(mode="json")
        if rejected_provider_reason:
            metadata["narration"]["rejected_provider_reason"] = rejected_provider_reason
        resolution.metadata = metadata

    async def _apply_narrator(
        self,
        action: dict[str, Any],
        character: dict[str, Any],
        room: dict[str, Any],
        resolution: ResolutionResult,
        *,
        ai_only: bool = False,
    ) -> str | None:
        context: dict[str, Any] | None = None
        is_solo_transition = False
        try:
            context = build_narrator_context(
                self.conn,
                action,
                character,
                room,
                resolution,
            )
            is_solo_transition = isinstance(
                (resolution.metadata or {}).get("solo_adventure_transition"),
                dict,
            )
            payload = dict(context)
            try:
                raw = await asyncio.wait_for(
                    self.gateway.narrate_action(
                        payload,
                        action["room_id"],
                        action_id=action["action_id"],
                    ),
                    timeout=_NARRATOR_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                if is_solo_transition or self._can_use_verified_narration_fallback(action, room):
                    self._apply_verified_narration_fallback(
                        context,
                        action,
                        resolution,
                        rejected_provider_reason="narrator_timeout",
                    )
                    return None
                return "narrator_timeout"
            if not isinstance(raw, dict):
                if is_solo_transition or ai_only:
                    self._apply_verified_narration_fallback(
                        context,
                        action,
                        resolution,
                        rejected_provider_reason="narrator_invalid_response",
                    )
                    return None
                return "narrator_invalid_response"
            try:
                narration = NarrationResultDTO(**raw)
            except Exception:
                if is_solo_transition or ai_only:
                    self._apply_verified_narration_fallback(
                        context,
                        action,
                        resolution,
                        rejected_provider_reason="narrator_invalid_response",
                    )
                    return None
                return "narrator_invalid_response"
            violation = validate_narration_result(narration, context)
            if violation:
                if ai_only or (
                    violation in {
                        "narrator_fact_violation",
                        "narrator_hypothesis_violation",
                    }
                    and (
                        is_solo_transition
                        or self._can_use_verified_narration_fallback(action, room)
                    )
                ):
                    self._apply_verified_narration_fallback(
                        context,
                        action,
                        resolution,
                        rejected_provider_reason=violation,
                    )
                    return None
                return violation
            resolution.narrative = narration.narrative_text
            metadata = dict(resolution.metadata or {})
            metadata["narration"] = narration.model_dump(mode="json")
            resolution.metadata = metadata
            return None
        except Exception as exc:
            if (
                context is not None
                and (
                    ai_only
                    or is_solo_transition
                    or self._can_use_verified_narration_fallback(action, room)
                )
            ):
                self._apply_verified_narration_fallback(
                    context,
                    action,
                    resolution,
                    rejected_provider_reason="narrator_provider_failed",
                )
                return None
            logger.warning(
                "Narrator failed for action %s: %s",
                action.get("action_id"),
                type(exc).__name__,
            )
            return "narrator_invalid_response"

    def _can_use_verified_narration_fallback(
        self,
        action: dict[str, Any],
        room: dict[str, Any],
    ) -> bool:
        if str(room.get("player_experience_version") or "") != "v2":
            return False
        params = self._json_value(action.get("params")) or {}
        plan = params.get("director_plan")
        if not isinstance(plan, dict):
            return False
        if plan.get("state_patch_authority") != "advisory_only":
            return False
        permissions = plan.get("permissions")
        if not isinstance(permissions, list):
            return False
        return all(
            isinstance(permission, dict)
            and permission.get("allowed") is not False
            and "allowed" in permission
            for permission in permissions
        )

    def _host_reveal_steps(self, resolution: ResolutionResult) -> list[dict[str, Any]]:
        host_steps = []
        for step in resolution.reveal_steps:
            if step.get("kind") == "roll":
                host_steps.append({"kind": "roll", "payload": step})
            else:
                host_steps.append({"kind": "status_delta", "payload": step})
        if resolution.mutations:
            host_steps.append({"kind": "status_delta", "payload": {"mutations": resolution.mutations}})
        host_steps.append({"kind": "narrative_text", "payload": {"text": resolution.narrative}})
        return host_steps

    def _persist_resolution_bundle(
        self,
        action: dict[str, Any],
        status: str,
        result_payload: dict[str, Any],
        rule_explanation: dict[str, Any],
        resolution: ResolutionResult,
    ) -> dict[str, Any]:
        state_row = self.conn.execute(
            "SELECT state_version FROM rooms WHERE room_id = %s",
            (action["room_id"],),
        ).fetchone()
        canonical_result = dict(result_payload)
        canonical_result["stateVersion"] = int(state_row["state_version"]) if state_row else 0
        bundle = {
            "action_id": action["action_id"],
            "status": status,
            "authoritative_result": canonical_result,
            "rule_explanation": rule_explanation,
            "host_projection": {
                "transactionId": str(uuid.uuid4()),
                "actionId": action["action_id"],
                "priority": "normal",
                "steps": self._host_reveal_steps(resolution),
                "summaryText": resolution.narrative,
            },
            "player_projection": {
                "actionId": action["action_id"],
                "result": self._player_result_projection(result_payload),
                "state_patch": {
                    "actionId": action["action_id"],
                    "patches": resolution.mutations,
                    "cascadingStateChanges": resolution.cascading_state_changes,
                } if resolution.mutations else None,
                "action_completed": self._action_completed_payload(action, resolution),
            },
            "party_projection": {
                "actionId": action["action_id"],
                "narrativeText": resolution.narrative,
                "spoilerStatus": "none",
                "narration": (resolution.metadata or {}).get("narration"),
            },
        }
        self.conn.execute(
            "INSERT INTO resolution_bundles "
            "(action_id, room_id, character_id, canonical_result, rule_explanation, "
            "actor_projection, stage_projection, host_console, release_status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (action_id) DO UPDATE SET "
            "canonical_result = EXCLUDED.canonical_result, "
            "rule_explanation = EXCLUDED.rule_explanation, "
            "actor_projection = EXCLUDED.actor_projection, "
            "stage_projection = EXCLUDED.stage_projection, "
            "host_console = EXCLUDED.host_console, "
            "release_status = EXCLUDED.release_status, released_at = NULL",
            (
                action["action_id"],
                action["room_id"],
                action["character_id"],
                json.dumps(canonical_result, ensure_ascii=False, default=str),
                json.dumps(rule_explanation, ensure_ascii=False, default=str),
                json.dumps(bundle["player_projection"], ensure_ascii=False, default=str),
                json.dumps(bundle["party_projection"], ensure_ascii=False, default=str),
                json.dumps(bundle["host_projection"], ensure_ascii=False, default=str),
                "ready",
            ),
        )
        self.conn.commit()
        return bundle

    @staticmethod
    def _player_result_projection(result_payload: dict[str, Any]) -> dict[str, Any]:
        projected = json.loads(json.dumps(result_payload, ensure_ascii=False, default=str))
        metadata = projected.get("metadata")
        if not isinstance(metadata, dict):
            return projected
        hidden_modifiers = metadata.get("hidden_modifiers")
        if not isinstance(hidden_modifiers, list):
            return projected
        metadata["hidden_modifiers"] = [
            {key: value for key, value in modifier.items() if key != "source"} | {"source": "hidden"}
            for modifier in hidden_modifiers
            if isinstance(modifier, dict)
        ]
        return projected

    def _mark_resolution_bundle_projected(self, bundle: dict[str, Any]) -> None:
        self.conn.execute(
            "UPDATE resolution_bundles SET actor_projection = %s, stage_projection = %s, "
            "host_console = %s, release_status = %s, released_at = NOW() WHERE action_id = %s",
            (
                json.dumps(bundle["player_projection"], ensure_ascii=False, default=str),
                json.dumps(bundle["party_projection"], ensure_ascii=False, default=str),
                json.dumps(bundle["host_projection"], ensure_ascii=False, default=str),
                "released",
                bundle["action_id"],
            ),
        )
        self.conn.commit()

    def _mark_resolution_bundle_projection_pending(self, bundle: dict[str, Any]) -> None:
        self.conn.execute(
            "UPDATE resolution_bundles SET release_status = %s WHERE action_id = %s",
            ("projection_pending", bundle["action_id"]),
        )
        self.conn.commit()

    async def replay_projection(self, action_id: str) -> dict[str, str]:
        """Replay saved projections without invoking AI, rules, or state mutation."""
        action = self.conn.execute(
            "SELECT * FROM actions WHERE action_id = %s", (action_id,)
        ).fetchone()
        if not action:
            return {"status": "missing", "action_id": action_id}
        action = dict(action)
        bundle_row = self.conn.execute(
            "SELECT actor_projection, stage_projection, host_console, release_status "
            "FROM resolution_bundles WHERE action_id = %s",
            (action_id,),
        ).fetchone()
        if not bundle_row:
            return {"status": "missing_bundle", "action_id": action_id}
        bundle_row = dict(bundle_row)
        if bundle_row.get("release_status") == "released":
            return {"status": "already_released", "action_id": action_id}
        bundle = {
            "action_id": action_id,
            "player_projection": self._json_value(bundle_row.get("actor_projection")) or {},
            "party_projection": self._json_value(bundle_row.get("stage_projection")) or {},
            "host_projection": self._json_value(bundle_row.get("host_console")) or {},
        }
        await self._project_saved_bundle(action, bundle)
        return {"status": "replayed", "action_id": action_id}

    async def _project(
        self,
        action: dict[str, Any],
        resolution: ResolutionResult,
        bundle: dict[str, Any],
    ):
        host_projection = bundle["host_projection"]

        await self.dispatcher.emit(
            action["room_id"],
            "s2c_reveal_transaction",
            "host",
            host_projection,
        )
        player_projection = bundle["player_projection"]
        if player_projection["state_patch"]:
            await self.dispatcher.emit(
                action["room_id"],
                "s2c_state_patch",
                "player",
                player_projection["state_patch"],
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

        party_projection = bundle["party_projection"]
        party_projection["narrativeText"] = final_text
        party_projection["spoilerStatus"] = spoiler_status
        public_payload = {"actionId": action["action_id"], "text": final_text}
        if spoiler_status != "none":
            public_payload["spoilerStatus"] = spoiler_status
        await self.dispatcher.emit(
            action["room_id"],
            "s2c_public_observation",
            "party",
            public_payload,
        )
        narration = party_projection["narration"]
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
            player_projection["action_completed"],
            character_id=action["character_id"],
        )
        self._mark_resolution_bundle_projected(bundle)

    async def _project_saved_bundle(self, action: dict[str, Any], bundle: dict[str, Any]) -> None:
        """Emit persisted view projections only; this path must never touch authority."""
        host_projection = bundle["host_projection"]
        await self.dispatcher.emit(
            action["room_id"],
            "s2c_reveal_transaction",
            "host",
            host_projection,
        )
        player_projection = bundle["player_projection"]
        state_patch = player_projection.get("state_patch")
        if isinstance(state_patch, dict):
            await self.dispatcher.emit(
                action["room_id"],
                "s2c_state_patch",
                "player",
                state_patch,
                character_id=action["character_id"],
            )
        party_projection = bundle["party_projection"]
        narrative_text = str(party_projection.get("narrativeText") or "")
        public_payload = {"actionId": action["action_id"], "text": narrative_text}
        spoiler_status = party_projection.get("spoilerStatus")
        if isinstance(spoiler_status, str) and spoiler_status != "none":
            public_payload["spoilerStatus"] = spoiler_status
        await self.dispatcher.emit(
            action["room_id"],
            "s2c_public_observation",
            "party",
            public_payload,
        )
        narration = party_projection.get("narration")
        if isinstance(narration, dict):
            await self.dispatcher.emit(
                action["room_id"],
                "s2c_narration_completed",
                "party",
                {
                    "actionId": action["action_id"],
                    "narrativeText": narrative_text,
                    "environmentChanges": narration.get("environment_changes") or [],
                    "interactableObjects": narration.get("interactable_objects") or [],
                    "openQuestion": narration.get("open_question") or "",
                    "stylePackVersion": narration.get("style_pack_version") or "",
                    "redactedCitations": narration.get("redacted_citations") or [],
                },
            )
        completed = player_projection.get("action_completed")
        if isinstance(completed, dict):
            await self.dispatcher.emit(
                action["room_id"],
                "s2c_action_completed",
                "player",
                completed,
                character_id=action["character_id"],
            )
        self._mark_resolution_bundle_projected(bundle)

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
        from ..scenario.solo_runtime import render_player_safe_solo_narrative

        return render_player_safe_solo_narrative(scene)

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
        params.pop("generic_scene_progression", None)
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

        generic_transition, generic_error = self._validated_generic_scene_transition(
            action,
            intent,
        )
        if generic_error:
            return generic_error
        if generic_transition:
            intent.params["generic_scene_progression"] = generic_transition
            action["params"] = intent.params
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

    def _validated_generic_scene_transition(
        self,
        action: dict[str, Any],
        intent: PlayerIntent,
    ) -> tuple[dict[str, Any] | None, str | None]:
        params = intent.params or {}
        analysis = params.get("analysis")
        if not isinstance(analysis, dict):
            return None, None
        progression = analysis.get("semantic_progression")
        if not isinstance(progression, dict) or not progression:
            return None, None
        if progression.get("validated") is not True:
            return None, "generic_scene_progression_unverified"
        from_scene_id = str(
            progression.get("fromNodeId") or progression.get("from_node_id") or ""
        )
        target_scene_id = str(
            progression.get("targetNodeId") or progression.get("target_node_id") or ""
        )
        if (
            not from_scene_id
            or not target_scene_id
            or str(params.get("fromNodeId") or "") != from_scene_id
            or str(params.get("targetNodeId") or "") != target_scene_id
        ):
            return None, "generic_scene_progression_invalid"
        state = self.conn.execute(
            "SELECT current_scene FROM room_scene_state WHERE room_id = %s",
            (action["room_id"],),
        ).fetchone()
        current_scene_id = str(state.get("current_scene") or "") if state else ""
        director_plan = params.get("director_plan")
        shared_turn_arrival = False
        if current_scene_id == target_scene_id and isinstance(director_plan, dict):
            try:
                shared_turn_arrival = self._uses_current_turn_snapshot(
                    action,
                    int(director_plan.get("context_version")),
                )
            except (TypeError, ValueError):
                shared_turn_arrival = False
        if not state or (
            current_scene_id != from_scene_id and not shared_turn_arrival
        ):
            return None, "generic_scene_transition_stale"
        runtime_package = self._runtime_package_for_room(action["room_id"])
        rules = runtime_package.get("semantic_progression_rules")
        edges = rules.get("edges") if isinstance(rules, dict) else []
        if not isinstance(edges, list):
            return None, "generic_scene_progression_invalid"
        from ..ai.director import _citation_matches, _generic_edge_conditions_are_met

        rule_citation = progression.get("ruleCitation") or progression.get("rule_citation")
        if not isinstance(rule_citation, dict):
            return None, "generic_scene_progression_invalid"
        for edge in edges:
            if not isinstance(edge, dict) or edge.get("relation_type") != "transitions_to":
                continue
            if (
                str(edge.get("from_scene_id") or "") != from_scene_id
                or str(edge.get("to_scene_id") or "") != target_scene_id
            ):
                continue
            edge_citation = edge.get("citation") if isinstance(edge.get("citation"), dict) else {}
            if not _citation_matches(rule_citation, [edge_citation]):
                continue
            if not _generic_edge_conditions_are_met(
                self.conn,
                action["room_id"],
                edge.get("conditions"),
            ):
                return None, "generic_scene_conditions_unmet"
            return {
                "from_scene_id": from_scene_id,
                "target_scene_id": target_scene_id,
                "citation": edge_citation,
                "already_applied": shared_turn_arrival,
            }, None
        return None, "generic_scene_progression_invalid"

    def _evaluate_verified_runtime_ending(self, room_id: str):
        from .ending_conditions import evaluate_ending_conditions

        runtime_package = self._runtime_package_for_room(room_id)
        return evaluate_ending_conditions(
            self.conn,
            room_id,
            runtime_package.get("ending_conditions"),
        )

    def _runtime_package_for_room(self, room_id: str) -> dict[str, Any]:
        room = self.conn.execute(
            "SELECT scenario_version_id, runtime_package_version_id FROM rooms WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        if not room or not room.get("scenario_version_id"):
            return {}
        if room.get("runtime_package_version_id"):
            package_row = self.conn.execute(
                """
                SELECT runtime_package
                FROM runtime_package_versions
                WHERE runtime_package_version_id = %s
                  AND scenario_version_id = %s
                  AND gate_status = 'ready'
                """,
                (room["runtime_package_version_id"], room["scenario_version_id"]),
            ).fetchone()
        else:
            package_row = self.conn.execute(
                """
                SELECT runtime_package
                FROM runtime_package_versions
                WHERE scenario_version_id = %s AND gate_status = 'ready'
                ORDER BY package_version_number DESC
                LIMIT 1
                """,
                (room["scenario_version_id"],),
            ).fetchone()
        return self._json_value(
            package_row.get("runtime_package") if package_row else None
        ) or {}

    @staticmethod
    def _has_compiled_bout_transition(
        runtime_package: dict[str, Any],
        intent_type: str,
        params: dict[str, Any],
    ) -> bool:
        triggers = runtime_package.get("rule_triggers")
        if not isinstance(triggers, list):
            return False
        from ..rules.triggers import evaluate_triggers

        for mechanic in evaluate_triggers(triggers, intent_type, params):
            mechanic_params = mechanic.get("params", mechanic)
            if (
                mechanic.get("type") == "sanity_advance"
                and isinstance(mechanic_params, dict)
                and mechanic_params.get("event") == "bout_elapsed"
            ):
                return True
        return False

    @staticmethod
    def _runtime_has_sanity_rules(runtime_package: dict[str, Any]) -> bool:
        triggers = runtime_package.get("rule_triggers")
        if not isinstance(triggers, list):
            return False
        for trigger in triggers:
            mechanics = trigger.get("mechanics") if isinstance(trigger, dict) else None
            if not isinstance(mechanics, list):
                continue
            if any(
                isinstance(mechanic, dict)
                and str(mechanic.get("type") or "").startswith("sanity_")
                for mechanic in mechanics
            ):
                return True
        return False

    async def _persist_named_runtime_clues(
        self,
        action: dict[str, Any],
        intent: PlayerIntent,
    ) -> list[dict[str, Any]]:
        declared = self._normalize_runtime_text(intent.declared_intent)
        if not declared:
            return []
        current_scene_row = self.conn.execute(
            "SELECT current_scene FROM room_scene_state WHERE room_id = %s",
            (action["room_id"],),
        ).fetchone()
        current_scene_id = str(
            current_scene_row.get("current_scene") if current_scene_row else ""
        ).strip()
        if not current_scene_id:
            return []
        runtime_package = self._runtime_package_for_room(action["room_id"])
        dependencies = runtime_package.get("clue_dependencies")
        if not isinstance(dependencies, list):
            return []
        scene_names = self._runtime_scene_names(runtime_package, current_scene_id)
        discovered: list[dict[str, Any]] = []
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                continue
            canonical_id = str(dependency.get("clue_id") or "").strip()
            name = str(dependency.get("name") or "").strip()
            normalized_name = self._normalize_runtime_text(name)
            if (
                not canonical_id
                or not normalized_name
                or normalized_name not in declared
                or not self._runtime_clue_matches_scene(
                    dependency,
                    current_scene_id,
                    scene_names,
                )
            ):
                continue
            source = f"runtime:{canonical_id}"
            clue_id = "runtime-" + uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{action['room_id']}:{action['character_id']}:{canonical_id}",
            ).hex[:20]
            description = str(dependency.get("description") or "").strip()
            text = f"{name}：{description}" if description else name
            created = self.conn.execute(
                """
                INSERT INTO clues (clue_id, room_id, character_id, text, source, is_private)
                VALUES (%s, %s, %s, %s, %s, TRUE)
                ON CONFLICT (clue_id) DO NOTHING
                RETURNING clue_id
                """,
                (
                    clue_id,
                    action["room_id"],
                    action["character_id"],
                    text,
                    source,
                ),
            ).fetchone()
            if not created:
                continue
            await self.dispatcher.emit(
                action["room_id"],
                "s2c_clue_discovered",
                "player",
                {
                    "clueId": clue_id,
                    "name": name,
                    "source": source,
                    "visibility": "self",
                },
                character_id=action["character_id"],
            )
            discovered.append({
                "canonicalId": canonical_id,
                "clueId": clue_id,
                "name": name,
            })
        return discovered

    @staticmethod
    def _normalize_runtime_text(value: Any) -> str:
        return "".join(char.casefold() for char in str(value or "") if char.isalnum())

    def _runtime_scene_names(
        self,
        runtime_package: dict[str, Any],
        current_scene_id: str,
    ) -> set[str]:
        names = {self._normalize_runtime_text(current_scene_id)}
        for scene in runtime_package.get("semantic_scenes") or []:
            if not isinstance(scene, dict):
                continue
            payload = self._json_value(scene.get("payload")) or {}
            identifiers = {
                str(scene.get("logical_key") or ""),
                str(scene.get("scene_id") or ""),
                str(payload.get("scene_id") or ""),
                str(payload.get("id") or ""),
            }
            if current_scene_id not in identifiers:
                continue
            names.update(
                self._normalize_runtime_text(value)
                for value in (
                    scene.get("name"),
                    scene.get("title"),
                    payload.get("name"),
                    payload.get("title"),
                )
                if value
            )
        names.discard("")
        return names

    def _runtime_clue_matches_scene(
        self,
        dependency: dict[str, Any],
        current_scene_id: str,
        scene_names: set[str],
    ) -> bool:
        dependency_scene_id = str(dependency.get("scene_id") or "").strip()
        if dependency_scene_id:
            return dependency_scene_id == current_scene_id
        location = self._normalize_runtime_text(dependency.get("location"))
        return bool(location and location in scene_names)

    def _commit_verified_runtime_ending(self, room_id: str, ending) -> bool:
        with self.conn.transaction() as tx:
            row = tx.execute(
                """
                UPDATE rooms
                SET status = 'completed', state_version = state_version + 1
                WHERE room_id = %s
                  AND status = %s
                RETURNING room_id
                """,
                (room_id, ending.room_status),
            ).fetchone()
            if row:
                character_arcs = self._archive_character_arcs(tx, room_id)
                tx.execute(
                    """
                    INSERT INTO campaign_archives
                    (archive_id, room_id, ending_type, summary, highlights, character_arcs)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        str(uuid.uuid4())[:8],
                        room_id,
                        ending.ending_type,
                        "本次冒险已按已验证条件结束。",
                        json.dumps(["已完成已验证的结局条件。"], ensure_ascii=False),
                        json.dumps(character_arcs, ensure_ascii=False),
                    ),
                )
        return bool(row)

    def _archive_character_arcs(self, executor, room_id: str) -> list[dict[str, Any]]:
        from ..campaign_archive import build_character_arcs

        return build_character_arcs(executor, room_id)

    async def _apply_move_result(self, action: dict[str, Any], resolution: ResolutionResult):
        """Post-resolution: update character position, mark node explored, emit map events."""
        params = (self._json_value(action.get("params")) or {}) if isinstance(action.get("params"), str) else (action.get("params") or {})
        target = params.get("targetNodeId", "")
        room_id = action["room_id"]
        character_id = action["character_id"]

        if isinstance(params.get("generic_scene_progression"), dict):
            return

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
            bootstrapped_encounter_id = ""
            if not active_encounter and intent.intent_type == "combat_action":
                active_encounter = self._bootstrap_solo_combat_encounter(
                    room_id,
                    character_id,
                    intent.declared_intent,
                )
                if active_encounter and active_encounter.get("status") == "active":
                    bootstrapped_encounter_id = str(active_encounter.get("encounter_id") or "")
            if not active_encounter:
                return "encounterId is required"
            encounter_id = active_encounter["encounter_id"]
            intent.params["encounterId"] = encounter_id
            if bootstrapped_encounter_id == encounter_id:
                intent.params["combatStarted"] = encounter_id

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

        is_authorized_prepared_reaction = False
        if params.get("preparedReaction"):
            prepared_action_id = params.get("preparedActionId")
            source_action_id = params.get("sourceActionId")
            if not isinstance(prepared_action_id, str) or not isinstance(source_action_id, str):
                return "prepared_reaction_not_authorized"
            prepared = self.conn.execute(
                "SELECT 1 FROM prepared_rule_actions WHERE action_id = %s AND room_id = %s "
                "AND character_id = %s AND source_action_id = %s AND status = 'triggered'",
                (prepared_action_id, room_id, character_id, source_action_id),
            ).fetchone()
            if not prepared:
                return "prepared_reaction_not_authorized"
            is_authorized_prepared_reaction = True

        if (
            participant.get("acted_this_round")
            and intent.intent_type not in ("",)
            and not is_authorized_prepared_reaction
        ):
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
            notes=(
                "厚皮每轮吸收前3点伤害；"
                "爪击35%/2d6，啃咬25%/1d8；"
                "第一轮双爪，第二轮爪击与啃咬，第三轮双爪。"
            ),
            display_name="黑熊",
            public_visibility="visible",
            public_label="黑熊",
        )
        return get_encounter(self.conn, encounter_id) or encounter

    async def _apply_encounter_result(
        self, action: dict[str, Any], intent: PlayerIntent, resolution: ResolutionResult,
    ) -> list[dict[str, str]]:
        """Post-resolution: update participant state from mutations, emit encounter events."""
        params = intent.params or {}
        encounter_id = params.get("encounterId", "")
        room_id = action["room_id"]
        character_id = action["character_id"]

        if not encounter_id:
            return []

        from ..encounter_persistence import (
            get_participant, update_participant, get_participants,
            update_encounter_status, get_active_encounter, shift_band,
        )

        participant = get_participant(self.conn, encounter_id, character_id)
        if not participant:
            return []

        from .prepared_rule_actions import (
            PreparedRuleEvent,
            consume_prepared_actions_for_rule_event,
        )

        prepared_reactions: list[dict[str, str]] = []
        prepared_rule_events: list[PreparedRuleEvent] = []
        prepared_event_kinds: set[str] = set()

        def queue_prepared_rule_event(rule_event: PreparedRuleEvent) -> None:
            if rule_event.kind not in prepared_event_kinds:
                prepared_event_kinds.add(rule_event.kind)
                prepared_rule_events.append(rule_event)

        is_public_rule_event = str(params.get("visibility") or "public") in {"public", "party"}
        if params.get("combatStarted") == encounter_id:
            queue_prepared_rule_event(PreparedRuleEvent.combat_started(encounter_id))

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
                if (
                    is_public_rule_event
                    and delta < 0
                    and target_character_id != character_id
                    and target_participant.get("side") == "player"
                ):
                    queue_prepared_rule_event(
                        PreparedRuleEvent.ally_publicly_hurt(encounter_id)
                    )
            # Apply distance band delta
            if "distance_band_delta" in path:
                delta = mutation.get("value", 0)
                if delta != 0:
                    current_band = target_participant.get("distance_band", "medium")
                    new_band = shift_band(current_band, delta)
                    update_participant(self.conn, encounter_id, target_character_id, distance_band=new_band)
                    if (
                        target_participant.get("side") == "enemy"
                        and target_participant.get("public_visibility") == "visible"
                        and current_band != "engaged"
                        and new_band == "engaged"
                    ):
                        queue_prepared_rule_event(
                            PreparedRuleEvent.enemy_enters_melee_range(encounter_id)
                        )
                    if (
                        target_participant.get("side") == "enemy"
                        and target_participant.get("public_visibility") == "visible"
                        and new_band == "escaped"
                    ):
                        update_participant(
                            self.conn,
                            encounter_id,
                            target_character_id,
                            public_visibility="lost",
                            last_observed_position=_SAFE_LAST_OBSERVED_DISTANCES.get(
                                current_band,
                                "视野边缘",
                            ),
                        )
                        target_participant["public_visibility"] = "lost"
            # Apply status tag additions
            if "status_tag" in path and mutation.get("op") == "add":
                tag = mutation.get("value", "")
                if tag:
                    status_tags = list(target_participant.get("status_tags", []) or [])
                    if tag not in status_tags:
                        status_tags.append(tag)
                    update_participant(self.conn, encounter_id, target_character_id, status_tags=status_tags)
            if (
                target_participant.get("side") == "enemy"
                and target_participant.get("public_visibility") != "visible"
                and "hp_delta" in path
                and mutation.get("value", 0) != 0
            ):
                enemies = [
                    item for item in get_participants(self.conn, encounter_id)
                    if item.get("side") == "enemy"
                ]
                enemy_ids = sorted(str(item.get("character_id") or "") for item in enemies)
                ordinal = (
                    enemy_ids.index(target_character_id) + 1
                    if target_character_id in enemy_ids
                    else 1
                )
                public_label = str(target_participant.get("public_label") or "").strip()
                update_participant(
                    self.conn,
                    encounter_id,
                    target_character_id,
                    public_visibility="visible",
                    public_label=public_label or f"敌对身影 {ordinal}",
                )
                target_participant["public_visibility"] = "visible"

        source_action_id = str(action.get("action_id") or resolution.action_id)
        for rule_event in prepared_rule_events:
            prepared_reactions.extend(
                consume_prepared_actions_for_rule_event(
                    self.conn,
                    room_id=room_id,
                    source_action_id=source_action_id,
                    rule_event=rule_event,
                )
            )

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

        pending_reaction = None
        if (
            not should_resolve
            and intent.intent_type == "combat_action"
            and enc
            and enc.get("type") == "combat"
            and not params.get("preparedReaction")
        ):
            from .solo_combat_reactions import (
                queue_enemy_reaction,
                reaction_projection,
            )

            pending_reaction = queue_enemy_reaction(
                self.conn,
                room_id=room_id,
                encounter_id=encounter_id,
                character_id=character_id,
                source_action_id=str(action.get("action_id") or resolution.action_id),
            )
            if pending_reaction:
                prepared_reactions.extend(pending_reaction.get("prepared_reactions") or [])

        if should_resolve:
            update_encounter_status(self.conn, encounter_id, "resolved", resolve_reason)

        # Emit s2c_encounter_updated
        updated_enc = get_active_encounter(self.conn, room_id) or enc
        updated_parts = get_participants(self.conn, encounter_id)
        from ..host.public_stage import (
            build_public_combat_unit_projection,
            build_public_encounter_event_projection,
        )
        await self.dispatcher.emit(
            room_id,
            "s2c_encounter_updated",
            "party",
            build_public_encounter_event_projection(
                updated_enc,
                build_public_combat_unit_projection(updated_parts),
            ),
        )
        await self.dispatcher.emit(
            room_id,
            "s2c_encounter_updated",
            "host",
            {
                "encounterId": encounter_id,
                "encounter": self._event_safe_record(updated_enc) if updated_enc else {},
                "participants": [self._event_safe_record(participant) for participant in updated_parts],
            },
        )

        if pending_reaction:
            await self.dispatcher.emit(
                room_id,
                "s2c_solo_combat_reaction_requested",
                "player",
                {"reaction": reaction_projection(pending_reaction)},
                character_id=character_id,
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
        return prepared_reactions

    @staticmethod
    def _event_safe_record(value: Any) -> dict[str, Any]:
        record = dict(value)
        for key, item in record.items():
            if isinstance(item, (datetime,)):
                record[key] = item.isoformat()
        return record

    @staticmethod
    def _state_service_mutations(mutations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            mutation
            for mutation in mutations
            if str(mutation.get("path") or "").startswith("/character/")
        ]

    @staticmethod
    def _has_sanity_state_transition(resolution: ResolutionResult) -> bool:
        insanity_tags = {
            "temporary_insanity",
            "indefinite_insanity",
            "permanent_insanity",
        }
        return any(
            mutation.get("path") in {
                "/character/san",
                "/character/temp_modifier/coc7_sanity",
            }
            or (
                mutation.get("path") == "/character/status_tag"
                and mutation.get("value") in insanity_tags
            )
            for mutation in resolution.mutations
            if isinstance(mutation, dict)
        )

    async def _revoke_character_player_connection(
        self,
        action: dict[str, Any],
    ) -> None:
        manager = getattr(self.dispatcher, "ws_manager", None)
        revoke_player = getattr(manager, "revoke_player", None)
        if not callable(revoke_player):
            return
        try:
            await revoke_player(action["room_id"], action["character_id"])
        except Exception:
            logger.exception(
                "Failed to revoke player connection room=%s character=%s",
                action["room_id"],
                action["character_id"],
            )

    def _apply_character_control_transition(
        self,
        executor,
        action: dict[str, Any],
        _resolution: ResolutionResult,
    ) -> bool:
        runtime = executor.execute(
            "SELECT san, temp_modifiers FROM character_runtime_state "
            "WHERE character_id = %s AND room_id = %s FOR UPDATE",
            (action["character_id"], action["room_id"]),
        ).fetchone()
        modifiers = self._json_value(runtime.get("temp_modifiers")) if runtime else {}
        sanity = (
            modifiers.get("coc7_sanity")
            if isinstance(modifiers, dict)
            else None
        )
        if (
            not runtime
            or int(runtime.get("san") or 0) != 0
            or not isinstance(sanity, dict)
            or sanity.get("insanity_type") != "permanent"
            or sanity.get("phase") != "permanent"
            or sanity.get("control") != "ai_keeper"
        ):
            return False
        cursor = executor.execute(
            "UPDATE characters SET status = 'restricted_npc', is_ready = FALSE "
            "WHERE character_id = %s AND room_id = %s "
            "AND status IN ('joined', 'ready')",
            (action["character_id"], action["room_id"]),
        )
        return bool(cursor.rowcount)

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
