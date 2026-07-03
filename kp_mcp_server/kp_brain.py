import json
import logging
from pathlib import Path

import httpx

from .config import Config

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).parent / "prompts"


class KpBrain:
    def __init__(self, config: Config):
        self.config = config
        self.api_key = config.deepseek_api_key
        self.api_base = config.deepseek_api_base
        self.model = config.deepseek_model
        self.system_prompt = self._load_system_prompt()

    # ── prompt ──────────────────────────────────────────

    def _load_system_prompt(self) -> str:
        soul = (PROMPT_DIR / "soul.md").read_text(encoding="utf-8")
        rules = (PROMPT_DIR / "rules.md").read_text(encoding="utf-8")
        contract = (PROMPT_DIR / "contract.md").read_text(encoding="utf-8")
        return f"{soul}\n\n---\n\n{rules}\n\n---\n\n{contract}"

    # ── LLM call ────────────────────────────────────────

    async def _call_llm(self, user_message: str, temperature: float = 0.8) -> dict:
        """Call DeepSeek, return parsed JSON."""
        if self.config.is_mock:
            return self._mock_response(user_message)

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    "temperature": temperature,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning("LLM response is not valid JSON, returning raw")
            return {"narrative": {"public": content[:500]}, "rollRequests": [],
                    "stateMutations": [], "tacticalPrompts": [], "citations": [],
                    "keeperNotes": "LLM returned non-JSON; raw text preserved.", "_error": None}

    # ── mock (no API key) ───────────────────────────────

    def _mock_turn(self) -> dict:
        return {
            "narrative": {"public": "（KP MCP mock 模式。设置 DEEPSEEK_API_KEY 启用完整 AI。）", "perCharacter": {}},
            "rollRequests": [],
            "stateMutations": [],
            "tacticalPrompts": [{"text": "（mock）请选择行动", "actions": [{"label": "继续探索", "intentType": "investigate"}]}],
            "citations": [],
            "keeperNotes": "mock",
            "_error": None,
        }

    # ── tool implementations ─────────────────────────────

    async def resolve_turn(self, args: dict) -> dict:
        if self.config.is_mock:
            return self._mock_turn()
        action = args.get("action", {})
        context = args.get("context", {})
        room_id = args.get("roomId", "")

        prompt = self._build_turn_prompt(room_id, action, context)
        return await self._call_llm(prompt, temperature=0.8)

    async def resolve_sanity(self, args: dict) -> dict:
        if self.config.is_mock:
            return self._mock_turn()
        context = args.get("context", {})
        trigger = args.get("trigger", {})
        room_id = args.get("roomId", "")

        prompt = self._build_sanity_prompt(room_id, context, trigger)
        return await self._call_llm(prompt, temperature=0.7)

    async def resolve_combat_round(self, args: dict) -> dict:
        if self.config.is_mock:
            return self._mock_turn()
        combatants = args.get("combatants", [])
        room_id = args.get("roomId", "")

        prompt = self._build_combat_prompt(room_id, combatants)
        return await self._call_llm(prompt, temperature=0.5)

    async def structure_scenario(self, args: dict) -> dict:
        if self.config.is_mock:
            return {"scenarioTitle": "mock", "scenes": [], "npcs": [], "clues": [], "truth": {}, "endings": [], "triggerMechanics": []}
        raw_text = args.get("rawText", "")
        truncated = raw_text[:12000]

        prompt = (
            "请分析以下 TRPG 剧本原文，提取结构化信息。\n\n"
            "返回格式：\n"
            '{\n  "scenarioTitle": "...",\n'
            '  "scenes": [{"name":"...","order":1,"description":"...","npcsPresent":[],"cluesAvailable":[]}],\n'
            '  "npcs": [{"name":"...","role":"...","personality":"...","motivation":"...","secret":"..."}],\n'
            '  "clues": [{"name":"...","description":"...","location":"...","importance":"core|support|danger"}],\n'
            '  "truth": {"summary":"..."},\n'
            '  "endings": [{"name":"...","description":"...","type":"victory|defeat|mixed"}],\n'
            '  "triggerMechanics": [{"condition":"...","effect":"..."}]\n'
            "}\n\n"
            f"原文：\n{truncated}"
        )
        return await self._call_llm(prompt, temperature=0.3)

    async def query_rules(self, args: dict) -> dict:
        if self.config.is_mock:
            return {"answer": "（mock 模式——COC 七版规则知识库未启用。设置 DEEPSEEK_API_KEY。）", "ruleReference": "mock", "mechanicSuggestion": None}
        question = args.get("question", "")
        context = args.get("context", {})

        prompt = (
            "你是一位 COC 七版规则专家。请根据规则知识回答以下问题。\n\n"
            "返回格式：\n"
            '{\n  "answer": "规则解释",\n'
            '  "ruleReference": "规则出处",\n'
            '  "mechanicSuggestion": {"type":"...","permission":"validate","payload":{}}\n'
            "}\n\n"
            f"问题：{question}\n"
            f"相关上下文：{json.dumps(context, ensure_ascii=False)}"
        )
        return await self._call_llm(prompt, temperature=0.3)

    async def query_knowledge(self, args: dict) -> dict:
        if self.config.is_mock:
            return {"answer": "（mock 模式）", "citations": [], "confidence": "low"}
        query = args.get("query", "")
        room_id = args.get("roomId", "")
        sources = args.get("sources", ["scenario", "rules"])

        prompt = (
            "你是一位 COC 守秘人知识库助手。请根据已知的剧本和规则知识回答 Host 的查询。\n\n"
            "返回格式：\n"
            '{\n  "answer": "回答内容",\n'
            '  "citations": [{"source":"...","text":"..."}],\n'
            '  "confidence": "high|medium|low"\n'
            "}\n\n"
            f"查询：{query}\n"
            f"房间：{room_id}\n"
            f"检索范围：{', '.join(sources)}"
        )
        return await self._call_llm(prompt, temperature=0.3)

    # ── prompt builders ──────────────────────────────────

    def _build_turn_prompt(self, room_id: str, action: dict, context: dict) -> str:
        lines = [
            f"房间: {room_id}",
            "",
            f"玩家行动: {action.get('characterId', '?')} 说「{action.get('declaredIntent', '')}」",
            f"行动类型: {action.get('intentType', 'unknown')}",
            "",
            "--- 上下文 ---",
            f"当前场景: {context.get('sceneName', '未知')}",
            f"场景描述: {context.get('sceneDescription', '')[:500]}",
            f"在场NPC: {json.dumps(context.get('npcsPresent', []), ensure_ascii=False)}",
            "",
            f"已发现线索: {json.dumps(context.get('visibleClues', []), ensure_ascii=False)}",
            "",
            "角色状态:",
            json.dumps(context.get("characterState", {}), ensure_ascii=False),
            "",
            "最近事件:",
        ]
        for evt in context.get("recentEvents", [])[-5:]:
            lines.append(f"  {evt}")
        lines.append("")
        lines.append(f"剧本阶段: {context.get('campaignPhase', 'investigation')}")
        lines.append("")
        lines.append("--- 请返回完整的 KpResponse JSON ---")
        return "\n".join(lines)

    def _build_sanity_prompt(self, room_id: str, context: dict, trigger: dict) -> str:
        return (
            f"房间: {room_id}\n\n"
            f"理智触发事件:\n"
            f"  类型: {trigger.get('type', 'witness_horror')}\n"
            f"  描述: {trigger.get('description', '')}\n"
            f"  SAN公式: {trigger.get('sanityFormula', 'auto')}\n\n"
            f"角色状态: {json.dumps(context.get('characterState', {}), ensure_ascii=False)}\n\n"
            "根据 COC 七版规则判定 SAN 损失公式并生成叙事。\n"
            "返回 KpResponse JSON。"
        )

    def _build_combat_prompt(self, room_id: str, combatants: list) -> str:
        return (
            f"房间: {room_id}\n\n"
            f"参战角色:\n{json.dumps(combatants, ensure_ascii=False, indent=2)}\n\n"
            "根据 COC 七版战斗规则：确定行动顺序、提出检定请求、判定战术结果。\n"
            "返回 KpResponse JSON。"
        )
