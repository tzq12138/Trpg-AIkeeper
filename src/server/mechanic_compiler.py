import json
import re
from typing import Any

import httpx

from .models import MechanicCompileResult, PlayerIntent


class MechanicCompiler:
    def __init__(
        self,
        api_key: str = "",
        model: str = "deepseek-v4-pro",
        api_base: str = "https://api.deepseek.com",
    ):
        self.api_key = api_key
        self.model = model
        self.api_base = api_base

    async def compile(
        self,
        intent: PlayerIntent,
        scenario: dict[str, Any],
        character: dict[str, Any],
    ) -> MechanicCompileResult:
        if self.api_key:
            for _ in range(2):
                try:
                    return await self._call_deepseek(intent, scenario, character)
                except Exception:
                    continue
        return self._compile_python(intent)

    def _compile_python(self, intent: PlayerIntent) -> MechanicCompileResult:
        params = intent.params or {}
        if intent.intent_type == "skill_check":
            return MechanicCompileResult(
                triggeredMechanic="skill_check",
                skillName=params.get("skillName") or params.get("skill_name") or "侦查",
                difficulty=params.get("difficulty", "regular"),
                itemConsumed=bool(params.get("itemConsumed") or params.get("item_consumed", False)),
            )
        if intent.intent_type == "use_item":
            return MechanicCompileResult(triggeredMechanic="auto_success")
        if intent.intent_type == "show_item":
            return MechanicCompileResult(triggeredMechanic="dialogue")

        text = intent.declared_intent or ""
        skill_name = self._skill_from_text(text)
        if skill_name:
            return MechanicCompileResult(
                triggeredMechanic="skill_check",
                skillName=skill_name,
                difficulty=self._difficulty_from_text(text),
            )
        if re.search(r"幸运|运气|luck", text, re.IGNORECASE):
            return MechanicCompileResult(triggeredMechanic="luck_check")
        if re.search(r"理智|sanity|san\b", text, re.IGNORECASE):
            return MechanicCompileResult(triggeredMechanic="sanity_check")
        return MechanicCompileResult(triggeredMechanic="dialogue")

    async def _call_deepseek(
        self,
        intent: PlayerIntent,
        scenario: dict[str, Any],
        character: dict[str, Any],
    ) -> MechanicCompileResult:
        prompt = {
            "intentType": intent.intent_type,
            "declaredIntent": intent.declared_intent,
            "params": intent.params,
            "scenarioTitle": scenario.get("title", ""),
            "character": {
                "name": character.get("player_name") or character.get("name", ""),
                "occupation": character.get("occupation", ""),
            },
            "instruction": (
                "只返回 JSON。字段为 triggeredMechanic, skillName, difficulty, "
                "itemConsumed, consequence。不要叙事文本。"
            ),
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{self.api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是 TRPG 机制编译器，只能输出结构化 JSON。",
                        },
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                    "temperature": 0,
                },
            )
            response.raise_for_status()
        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        raw = json.loads(content)
        return MechanicCompileResult(**raw)

    def _skill_from_text(self, text: str) -> str | None:
        patterns = [
            (r"侦查|搜索|搜查|观察|查看|检查|调查|look|search|examine|spot", "侦查"),
            (r"聆听|倾听|听|listen", "聆听"),
            (r"图书馆|资料|档案|library", "图书馆使用"),
            (r"说服|劝说|persuade", "说服"),
            (r"潜行|stealth", "潜行"),
            (r"闪避|dodge", "闪避"),
            (r"斗殴|拳|fight|brawl", "斗殴"),
        ]
        for pattern, skill in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return skill
        return None

    def _difficulty_from_text(self, text: str) -> str:
        if re.search(r"极难|极限|extreme", text, re.IGNORECASE):
            return "extreme"
        if re.search(r"困难|hard", text, re.IGNORECASE):
            return "hard"
        return "regular"
