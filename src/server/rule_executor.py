import json
from typing import Any

from .models import MechanicCompileResult, PlayerIntent, ResolutionResult
from .rules.base import GameState
from .rules.registry import get_handler
from .rules.triggers import evaluate_triggers


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
        state = GameState(character=xlsx_data, inventory=inventory)
        mechanics = self._matching_trigger_mechanics(intent, scenario_assets or {})

        if compiled.triggered_mechanic not in {"dialogue", "auto_success", "auto_failure"}:
            mechanics.append(self._mechanic_from_compile(compiled))

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
            if mechanic_type == "apply_patch":
                mutation = {
                    "op": params.get("op", "replace"),
                    "path": params.get("path", ""),
                    "value": params.get("value"),
                }
                if mutation["path"]:
                    mutations.append(mutation)
                continue

            handler = get_handler(mechanic_type)
            if not handler:
                merged_metadata.setdefault("warnings", []).append(
                    {"type": "rule_handler_not_found", "mechanic": mechanic_type}
                )
                continue

            if mechanic_type == "skill_check":
                skill_name = params.get("skillName") or params.get("skill_name") or ""
                params.setdefault("skillName", skill_name)
                params.setdefault("skillValue", self._skill_value(xlsx_data, skill_name))

            result = await handler.execute(state, params)
            overall_success = overall_success and result.is_success
            merged_metadata.update(result.metadata)
            mutations.extend(result.mutations)
            reveal_steps.extend(result.reveal_steps)
            cascading.extend(result.cascading_state_changes)
            self._apply_mutations_to_state(state.character, result.mutations)

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

    def _mechanic_from_compile(self, compiled: MechanicCompileResult) -> dict[str, Any]:
        params: dict[str, Any] = {
            "difficulty": compiled.difficulty,
            "itemConsumed": compiled.item_consumed,
        }
        if compiled.skill_name:
            params["skillName"] = compiled.skill_name
        params.update(compiled.consequence or {})
        return {"type": compiled.triggered_mechanic, "params": params}

    def _normalize_params(self, params: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(params)
        aliases = {
            "successLoss": "success_loss",
            "failureLoss": "failure_loss",
            "skill_name": "skillName",
            "skill_value": "skillValue",
        }
        for src, dest in aliases.items():
            if src in normalized and dest not in normalized:
                normalized[dest] = normalized[src]
        return normalized

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
            if mutation.get("op") != "replace":
                continue
            if path == "/character/san":
                state["san"] = mutation.get("value", state.get("san", 0))
            elif path == "/character/hp":
                state["hp"] = mutation.get("value", state.get("hp", 0))
