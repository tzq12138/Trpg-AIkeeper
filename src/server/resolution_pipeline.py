import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .mechanic_compiler import MechanicCompiler
from .models import MechanicCompileResult, PlayerIntent, ResolutionResult
from .projection import ProjectionDispatcher
from .rule_executor import RuleExecutor


class ResolutionPipeline:
    def __init__(
        self,
        conn,
        compiler: MechanicCompiler | None = None,
        dispatcher=None,
        rule_executor: RuleExecutor | None = None,
    ):
        self.conn = conn
        self.compiler = compiler or MechanicCompiler(api_key="")
        self.dispatcher = dispatcher or ProjectionDispatcher(conn)
        self.rule_executor = rule_executor or RuleExecutor()

    async def resolve_queued_room(self, room_id: str) -> dict[str, Any]:
        rows = self.conn.execute(
            "SELECT * FROM actions WHERE room_id = %s AND status = %s ORDER BY created_at",
            (room_id, "queued"),
        ).fetchall()
        results = []
        for action in rows:
            results.append(await self.resolve_action(action["action_id"]))
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
        resolution.narrative = self._render_fallback_narrative(intent, compiled, resolution)

        self.conn.execute(
            "UPDATE rooms SET state_version = state_version + 1 WHERE room_id = %s",
            (action["room_id"],),
        )
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
        await self.dispatcher.emit(
            action["room_id"],
            "s2c_public_observation",
            "party",
            {"actionId": action["action_id"], "text": resolution.narrative},
        )
        await self.dispatcher.emit(
            action["room_id"],
            "s2c_action_completed",
            "player",
            {"actionId": action["action_id"], "status": "resolved"},
            character_id=action["character_id"],
        )

    def _render_fallback_narrative(
        self,
        intent: PlayerIntent,
        compiled: MechanicCompileResult,
        resolution: ResolutionResult,
    ) -> str:
        if resolution.cascading_state_changes:
            facts = "；".join(resolution.cascading_state_changes)
            return f"{intent.declared_intent}。结果已经确定：{facts}。"
        if compiled.triggered_mechanic == "skill_check":
            level = resolution.metadata.get("success_level", "success" if resolution.is_success else "failure")
            roll = resolution.metadata.get("roll")
            target = resolution.metadata.get("target")
            return f"{intent.declared_intent}。检定结果 {roll}/{target}，{level}。"
        if resolution.is_success:
            return intent.declared_intent or "行动完成。"
        return f"{intent.declared_intent}。行动未能奏效。"

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
