import json
import logging
import re
from typing import Any

from ..models import MechanicCompileResult, PlayerIntent, ResolutionResult
from ..rules.base import GameState
from ..rules.registry import get_handler
from ..rules.triggers import evaluate_triggers

logger = logging.getLogger(__name__)

_SAFE_PATCH_OPERATIONS = {
    "/character/hp": {"replace"},
    "/character/san": {"replace"},
    "/character/mp": {"replace"},
    "/character/luck": {"replace"},
    "/character/status_tag": {"add", "remove"},
}
_ENCOUNTER_MUTATION_PATTERN = re.compile(
    r"^/encounter/[^/]+/(?:participants/[^/]+/(hp_delta|distance_band_delta|status_tag)|metadata/(blocked_band))$"
)


class RuleExecutor:
    async def execute(
        self,
        intent: PlayerIntent,
        compiled: MechanicCompileResult,
        character: dict[str, Any],
        inventory: list[dict[str, Any]],
        scenario_assets: dict[str, Any] | None,
    ) -> ResolutionResult:
        xlsx_data = self._xlsx_data(character)
        state = GameState(
            character=xlsx_data,
            scene=scenario_assets or {},
            inventory=inventory,
        )
        mechanics = self._matching_trigger_mechanics(intent, scenario_assets or {})

        if compiled.triggered_mechanic not in {"dialogue", "auto_success", "auto_failure"}:
            mechanics.append(self._mechanic_from_compile(compiled, intent.params or {}))

        if compiled.triggered_mechanic == "auto_failure":
            return ResolutionResult(
                actionId=intent.action_id,
                roomId=character.get("room_id", ""),
                characterId=character.get("character_id", ""),
                mechanic="auto_failure",
                isSuccess=False,
                metadata={"reason": "compiled_auto_failure"},
            )

        if not mechanics:
            # Default mechanic for move intent
            if intent.intent_type == "move":
                mechanics.append({
                    "type": "move",
                    "params": {
                        "targetNodeId": (intent.params or {}).get("targetNodeId", ""),
                        "fromNodeId": (intent.params or {}).get("fromNodeId", ""),
                        "solo_adventure": bool((intent.params or {}).get("solo_adventure")),
                    }
                })
            else:
                return ResolutionResult(
                    actionId=intent.action_id,
                    roomId=character.get("room_id", ""),
                    characterId=character.get("character_id", ""),
                    mechanic=compiled.triggered_mechanic,
                    isSuccess=True,
                    metadata={},
                )

        overall_success = True
        merged_metadata: dict[str, Any] = {}
        mutations: list[dict[str, Any]] = []
        reveal_steps: list[dict[str, Any]] = []
        cascading: list[str] = []
        last_mechanic = mechanics[-1].get("type", compiled.triggered_mechanic)

        for mechanic in mechanics:
            mechanic_type = mechanic.get("type", "")
            params = self._normalize_params(mechanic.get("params", mechanic))
            params["_rule_policy"] = dict(
                (scenario_assets or {}).get("rule_policy") or {}
            )
            if mechanic_type == "apply_patch":
                mutation = {
                    "op": params.get("op", "replace"),
                    "path": params.get("path", ""),
                    "value": params.get("value"),
                }
                if self._is_safe_patch(mutation):
                    mutations.append(mutation)
                    self._apply_mutations_to_state(state.character, [mutation])
                else:
                    overall_success = False
                    self._add_pending_rule_suggestion(
                        merged_metadata,
                        mechanic_type,
                        params,
                        "unsafe_patch_rejected",
                    )
                continue

            handler = get_handler(mechanic_type)
            if not handler:
                logger.warning("execute: no handler for mechanic=%s action=%s",
                               mechanic_type, intent.action_id)
                merged_metadata.setdefault("warnings", []).append(
                    {"type": "rule_handler_not_found", "mechanic": mechanic_type}
                )
                overall_success = False
                self._add_pending_rule_suggestion(
                    merged_metadata,
                    mechanic_type,
                    params,
                    "rule_handler_not_found",
                )
                continue
            logger.debug("execute: handler=%s mechanic=%s action=%s",
                         type(handler).__name__, mechanic_type, intent.action_id)

            if mechanic_type == "skill_check":
                skill_name = params.get("skillName") or params.get("skill_name") or ""
                params["skillName"] = skill_name
                params["skillValue"] = self._skill_value(xlsx_data, skill_name)
                hidden_modifiers = self._hidden_modifiers(params)
                if hidden_modifiers:
                    params["bonusDice"] = int(params.get("bonusDice", 0) or 0) + sum(
                        item["bonus_dice"] for item in hidden_modifiers
                    )
            else:
                hidden_modifiers = []

            result = await handler.execute(state, params)
            if mechanic_type == "move" and params.get("solo_adventure"):
                result.mutations = []
                result.metadata["solo_adventure"] = True
            if hidden_modifiers:
                result.metadata["hidden_modifiers"] = hidden_modifiers
            merged_metadata.update(result.metadata)
            safe_mutations = []
            rejected_mutations = []
            for mutation in result.mutations:
                if self._is_safe_handler_mutation(mutation):
                    safe_mutations.append(mutation)
                else:
                    rejected_mutations.append(mutation)
            if rejected_mutations:
                self._add_pending_rule_suggestion(
                    merged_metadata,
                    mechanic_type,
                    params,
                    "unsafe_mutation_rejected",
                )
            overall_success = (
                overall_success and result.is_success and not rejected_mutations
            )
            mutations.extend(safe_mutations)
            reveal_steps.extend(result.reveal_steps)
            cascading.extend(result.cascading_state_changes)
            self._apply_mutations_to_state(state.character, safe_mutations)

        return ResolutionResult(
            actionId=intent.action_id,
            roomId=character.get("room_id", ""),
            characterId=character.get("character_id", ""),
            mechanic=last_mechanic,
            isSuccess=overall_success,
            metadata=merged_metadata,
            mutations=mutations,
            revealSteps=reveal_steps,
            cascadingStateChanges=cascading,
        )

    def _matching_trigger_mechanics(
        self, intent: PlayerIntent, scenario_assets: dict[str, Any]
    ) -> list[dict[str, Any]]:
        mechanics: list[dict[str, Any]] = []
        for scene in scenario_assets.get("scenes", []):
            mechanics.extend(
                evaluate_triggers(scene.get("triggers", []), intent.intent_type, intent.params or {})
            )
        mechanics.extend(
            evaluate_triggers(scenario_assets.get("triggers", []), intent.intent_type, intent.params or {})
        )
        return mechanics

    def _mechanic_from_compile(
        self,
        compiled: MechanicCompileResult,
        intent_params: dict[str, Any],
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            key: intent_params[key]
            for key in ("bonusDice", "pushed", "spendLuck")
            if key in intent_params
        }
        params.update({
            "difficulty": compiled.difficulty,
            "itemConsumed": compiled.item_consumed,
        })
        if compiled.skill_name:
            params["skillName"] = compiled.skill_name
        params.update(compiled.consequence or {})
        if compiled.triggered_mechanic == "move":
            params.update({
                key: intent_params[key]
                for key in ("fromNodeId", "targetNodeId", "solo_adventure")
                if key in intent_params
            })
        return {"type": compiled.triggered_mechanic, "params": params}

    def _normalize_params(self, params: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(params)
        aliases = {
            "successLoss": "success_loss",
            "failureLoss": "failure_loss",
            "skill_name": "skillName",
            "skill_value": "skillValue",
            "hiddenModifiers": "hidden_modifiers",
        }
        for src, dest in aliases.items():
            if src in normalized and dest not in normalized:
                normalized[dest] = normalized[src]
        return normalized

    def _hidden_modifiers(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        raw = params.get("hidden_modifiers")
        if not isinstance(raw, list):
            return []
        modifiers = []
        for item in raw[:10]:
            if not isinstance(item, dict):
                continue
            try:
                bonus_dice = max(-2, min(2, int(item.get("bonusDice", 0))))
            except (TypeError, ValueError):
                bonus_dice = 0
            modifiers.append({
                "source": str(item.get("source") or "hidden")[:200],
                "effect": str(item.get("effect") or f"bonus dice {bonus_dice}")[:200],
                "bonus_dice": bonus_dice,
            })
        return modifiers

    def _xlsx_data(self, character: dict[str, Any]) -> dict[str, Any]:
        data = character.get("xlsx_data") or {}
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = {}
        return dict(data)

    def _skill_value(self, xlsx_data: dict[str, Any], skill_name: str) -> int:
        skills = xlsx_data.get("skills", {}) or {}
        value = skills.get(skill_name, 0)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _apply_mutations_to_state(self, state: dict[str, Any], mutations: list[dict[str, Any]]):
        for mutation in mutations:
            path = mutation.get("path", "")
            operation = mutation.get("op")
            if path == "/character/san" and operation == "replace":
                state["san"] = mutation.get("value", state.get("san", 0))
            elif path == "/character/hp" and operation == "replace":
                state["hp"] = mutation.get("value", state.get("hp", 0))
            elif path == "/character/mp" and operation == "replace":
                state["mp"] = mutation.get("value", state.get("mp", 0))
            elif path == "/character/luck" and operation == "replace":
                state["luck"] = mutation.get("value", state.get("luck", 0))
            elif path == "/character/status_tag":
                tags = list(state.get("status_tags", []) or [])
                value = mutation.get("value")
                if operation == "add" and value and value not in tags:
                    tags.append(value)
                elif operation == "remove" and value in tags:
                    tags.remove(value)
                state["status_tags"] = tags

    def _is_safe_patch(self, mutation: dict[str, Any]) -> bool:
        path = str(mutation.get("path") or "")
        operation = str(mutation.get("op") or "")
        return operation in _SAFE_PATCH_OPERATIONS.get(path, set())

    def _is_safe_handler_mutation(self, mutation: dict[str, Any]) -> bool:
        if self._is_safe_patch(mutation):
            return True
        path = str(mutation.get("path") or "")
        operation = str(mutation.get("op") or "")
        match = _ENCOUNTER_MUTATION_PATTERN.fullmatch(path)
        if not match:
            return False
        participant_field, metadata_field = match.groups()
        if participant_field in {"hp_delta", "distance_band_delta"}:
            return operation == "replace" and isinstance(mutation.get("value"), int)
        if participant_field == "status_tag":
            return operation in {"add", "remove"} and bool(mutation.get("value"))
        return metadata_field == "blocked_band" and operation == "add"

    def _add_pending_rule_suggestion(
        self,
        metadata: dict[str, Any],
        mechanic_type: str,
        params: dict[str, Any],
        reason_code: str,
    ) -> None:
        citation = params.get("ruleCitation") or params.get("rule_citation") or {}
        if not isinstance(citation, dict):
            citation = {}
        citation = {
            key: value
            for key, value in citation.items()
            if not key.lower().endswith("_path")
            and key.lower() not in {"absolute_path", "storage_path"}
        }
        metadata.setdefault("pending_rule_suggestions", []).append({
            "mechanic": mechanic_type,
            "status": "pending_host_confirmation",
            "reason_code": reason_code,
            "citation": citation,
        })
