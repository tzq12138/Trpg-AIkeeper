import json
import logging
import re
from typing import Any

import httpx

from ..models import MechanicCompileResult, PlayerIntent

logger = logging.getLogger(__name__)


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
            for attempt in range(2):
                try:
                    logger.debug("compile: AI attempt=%s intent=%s", attempt + 1, intent.intent_type)
                    return await self._call_deepseek(intent, scenario, character)
                except Exception as exc:
                    logger.warning("compile: AI attempt %s failed for %s: %s", attempt + 1, intent.intent_type, exc)
                    continue
        logger.info("compile: using Python fallback for intent=%s", intent.intent_type)
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
        if intent.intent_type == "move":
            return MechanicCompileResult(
                triggeredMechanic="move",
                consequence={
                    "targetNodeId": (intent.params or {}).get("targetNodeId", ""),
                    "fromNodeId": (intent.params or {}).get("fromNodeId", ""),
                },
            )
        if intent.intent_type == "combat_action":
            action_kind = (intent.params or {}).get("actionKind", "attack")
            return MechanicCompileResult(
                triggeredMechanic=f"combat_{action_kind}",
                consequence={**(intent.params or {})},
            )
        if intent.intent_type == "chase_action":
            action_kind = (intent.params or {}).get("actionKind", "pursue")
            return MechanicCompileResult(
                triggeredMechanic=f"chase_{action_kind}",
                consequence={**(intent.params or {})},
            )
        if intent.intent_type == "system_skip":
            return MechanicCompileResult(triggeredMechanic="auto_success")

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
        normalized = self._normalize_raw_result(raw)
        try:
            return MechanicCompileResult(**normalized)
        except Exception as e:
            logger.warning(
                "compile: validation failed after normalization. raw_keys=%s norm_keys=%s err=%s",
                list(raw.keys()), list(normalized.keys()), e,
            )
            raise

    def _normalize_raw_result(self, raw: dict) -> dict:
        """Normalize DeepSeek JSON output to match MechanicCompileResult schema.

        DeepSeek may return camelCase, snake_case, or Chinese enum values.
        This maps them all to the canonical form before Pydantic validation.
        """
        n = dict(raw)

        # ── 1. triggeredMechanic ──────────────────────────────────
        tm = (n.get("triggeredMechanic")
              or n.get("triggered_mechanic")
              or n.get("triggeredmechanic")
              or "dialogue")
        tm_key = str(tm).lower().replace(" ", "_").replace("-", "_")
        TM_MAP = {
            "skill_check": "skill_check", "skillcheck": "skill_check",
            "dialogue": "dialogue", "identity_check": "dialogue",
            "identitycheck": "dialogue", "identity_check": "dialogue",
            "auto_success": "auto_success", "autosuccess": "auto_success",
            "luck_check": "luck_check", "luckcheck": "luck_check",
            "sanity_check": "sanity_check", "sanitycheck": "sanity_check",
            "use_item": "auto_success", "useitem": "auto_success",
            "show_item": "dialogue", "showitem": "dialogue",
        }
        n["triggeredMechanic"] = TM_MAP.get(tm_key, tm_key)

        # ── 2. difficulty ────────────────────────────────────────
        diff = n.get("difficulty", "regular")
        if diff is None:
            diff = "regular"
        diff_key = str(diff).lower()
        DIFF_MAP = {
            "normal": "regular", "medium": "regular",
            "普通": "regular", "一般": "regular",
            "regular": "regular", "hard": "hard",
            "困难": "hard", "extreme": "extreme",
            "极难": "extreme", "极限": "extreme",
        }
        n["difficulty"] = DIFF_MAP.get(diff_key, "regular")

        # ── 3. itemConsumed ──────────────────────────────────────
        ic = n.get("itemConsumed") or n.get("item_consumed")
        if ic is None:
            n["itemConsumed"] = False
        else:
            n["itemConsumed"] = bool(ic)

        # ── 4. consequence ───────────────────────────────────────
        cons = n.get("consequence")
        if cons is None:
            n["consequence"] = {}
        elif isinstance(cons, str):
            n["consequence"] = {"note": cons}
        elif isinstance(cons, (int, float, bool)):
            n["consequence"] = {"note": str(cons)}

        # ── 5. skillName alias ───────────────────────────────────
        if not n.get("skillName") and n.get("skill_name"):
            n["skillName"] = n["skill_name"]

        return n

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
