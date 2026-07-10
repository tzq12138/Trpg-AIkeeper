import json
import logging
from pathlib import Path

import httpx
from openai import AsyncOpenAI

from .config import Config

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).parent / "prompts"
MAX_MULTIMODAL_IMAGES = 20
MAX_IMAGE_DATA_URL_CHARS = 8 * 1024 * 1024
SCENARIO_STRUCTURE_SYSTEM_PROMPT = """你是 TRPG 剧本结构化与图像识别器。只返回 JSON 对象，不得返回 Markdown。
输出必须包含 scenarioTitle、synopsis、scenes、npcs、clues、truth、endings、triggerMechanics。
对每个图像来源，必须在 source_part_texts 中返回 {"source_ref":"输入中给出的来源标识","text":"该图像的可检索转写或语义描述"}。
source_ref 必须逐字复用输入标识；无法确认的内容要明确标注不确定，不得伪造页码或引用。"""


class KpBrain:
    def __init__(self, config: Config):
        self.config = config
        self.provider = config.provider
        self.api_key = config.api_key
        self.api_base = config.api_base
        self.model = config.model
        self.system_prompt = self._load_system_prompt()

    def _load_system_prompt(self) -> str:
        soul = (PROMPT_DIR / "soul.md").read_text(encoding="utf-8")
        rules = (PROMPT_DIR / "rules.md").read_text(encoding="utf-8")
        contract = (PROMPT_DIR / "contract.md").read_text(encoding="utf-8")
        return f"{soul}\n\n---\n\n{rules}\n\n---\n\n{contract}"

    async def _call_llm(
        self,
        user_message: str | list[dict],
        temperature: float = 0.8,
        system_prompt: str | None = None,
    ) -> dict:
        if self.config.is_mock:
            return self._mock_response(user_message if isinstance(user_message, str) else "multimodal input")

        effective_system_prompt = system_prompt or self.system_prompt
        if self.provider == "openai":
            return await self._call_openai(user_message, temperature, effective_system_prompt)
        return await self._call_deepseek(user_message, temperature, effective_system_prompt)

    async def _call_openai(
        self,
        user_message: str | list[dict],
        temperature: float,
        system_prompt: str,
    ) -> dict:
        client = AsyncOpenAI(api_key=self.api_key, base_url=self.api_base)
        user_content = self._openai_user_content(user_message)
        response = await client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            text={"format": {"type": "json_object"}},
            temperature=temperature,
        )
        content = getattr(response, "output_text", "") or ""
        return self._parse_json_content(content)

    async def _call_deepseek(
        self,
        user_message: str | list[dict],
        temperature: float,
        system_prompt: str,
    ) -> dict:
        user_content = self._chat_user_content(user_message)
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
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": temperature,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        return self._parse_json_content(content)

    def _parse_json_content(self, content: str) -> dict:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning("LLM response is not valid JSON, returning raw text payload")
            return {
                "narrative": {"public": (content or "")[:500], "perCharacter": {}},
                "rollRequests": [],
                "stateMutations": [],
                "tacticalPrompts": [],
                "citations": [],
                "keeperNotes": "LLM returned non-JSON; raw text preserved.",
                "_error": None,
            }

    def _mock_response(self, user_message: str) -> dict:
        text = user_message[:120] if user_message else "继续推进调查。"
        return {
            "narrative": {
                "public": f"（KP MCP mock 模式）已收到：{text}",
                "perCharacter": {},
            },
            "rollRequests": [],
            "stateMutations": [],
            "tacticalPrompts": [
                {
                    "text": "（mock）请选择下一步行动",
                    "actions": [{"label": "继续探索", "intentType": "investigate"}],
                }
            ],
            "citations": [],
            "keeperNotes": "mock",
            "_error": None,
        }

    async def resolve_turn(self, args: dict) -> dict:
        if self.config.is_mock:
            return self._mock_response(args.get("action", {}).get("declaredIntent", ""))
        action = args.get("action", {})
        context = args.get("context", {})
        room_id = args.get("roomId", "")

        prompt = self._build_turn_prompt(room_id, action, context)
        return await self._call_llm(prompt, temperature=0.8)

    async def resolve_sanity(self, args: dict) -> dict:
        if self.config.is_mock:
            return self._mock_response(args.get("trigger", {}).get("description", ""))
        context = args.get("context", {})
        trigger = args.get("trigger", {})
        room_id = args.get("roomId", "")

        prompt = self._build_sanity_prompt(room_id, context, trigger)
        return await self._call_llm(prompt, temperature=0.7)

    async def resolve_combat_round(self, args: dict) -> dict:
        if self.config.is_mock:
            return self._mock_response("战斗回合")
        combatants = args.get("combatants", [])
        room_id = args.get("roomId", "")

        prompt = self._build_combat_prompt(room_id, combatants)
        return await self._call_llm(prompt, temperature=0.5)

    async def generate_narrative(self, args: dict) -> dict:
        if self.config.is_mock:
            return self._mock_response(
                args.get("player_words") or args.get("declared_intent", "")
            )
        system_prompt = args.get("system_prompt") or (
            "你是中文 TRPG 守秘人。你必须始终使用简体中文作答，"
            "紧扣玩家刚刚的发言与当前调查语境，禁止切换成日文、英文或其他语言，"
            "也不要编造与玩家输入无关的新场景。"
            "如果上下文不足，只允许围绕玩家当前动作与话语做最小、贴身、可感知的回应，"
            "不得自行引入未提及的地点、人物、机构或事件。"
            "请基于玩家输入生成一段沉浸式公开叙事。"
            "只返回 JSON，格式为 "
            "{\"narrative\":{\"public\":\"...\",\"perCharacter\":{}},"
            "\"rollRequests\":[],\"stateMutations\":[],\"tacticalPrompts\":[],"
            "\"citations\":[],\"keeperNotes\":\"\",\"_error\":null}"
        )
        prompt = args.get("user_message") or self._build_generate_narrative_prompt(args)
        return await self._call_llm(prompt, temperature=0.8, system_prompt=system_prompt)

    async def structure_scenario(self, args: dict) -> dict:
        if self.config.is_mock:
            return {
                "scenarioTitle": "mock",
                "scenes": [],
                "npcs": [],
                "clues": [],
                "truth": {},
                "endings": [],
                "triggerMechanics": [],
            }
        content_package = args.get("contentPackage")
        if content_package is not None:
            user_content = self._content_package_user_content(content_package)
            if not user_content:
                raise ValueError("content_package_empty")
            return await self._call_llm(
                user_content,
                temperature=0.3,
                system_prompt=SCENARIO_STRUCTURE_SYSTEM_PROMPT,
            )

        raw_text = args.get("rawText", "")
        truncated = raw_text[:12000]

        prompt = (
            "请分析以下 TRPG 剧本原文，并提取结构化信息。\n\n"
            "返回格式：\n"
            "{\n"
            '  "scenarioTitle": "...",\n'
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

    def _content_package_user_content(self, content_package: dict) -> list[dict]:
        canonical_text = str(content_package.get("canonical_text") or "").strip()
        if not canonical_text:
            canonical_text = "\n".join(
                str(part.get("text") or "").strip()
                for part in content_package.get("parts", [])
                if part.get("kind") in {"text", "page", "table"} and part.get("text")
            ).strip()

        image_parts = []
        image_count = 0
        for part in content_package.get("parts", []):
            if image_count >= MAX_MULTIMODAL_IMAGES:
                break
            data_url = str(part.get("data_url") or "")
            if not data_url.startswith("data:image/") or ";base64," not in data_url:
                continue
            if len(data_url) > MAX_IMAGE_DATA_URL_CHARS:
                continue
            image_parts.append({
                "type": "image",
                "data_url": data_url,
                "source_ref": str(part.get("source_ref") or f"image:{image_count + 1}"),
            })
            image_count += 1
        if not canonical_text and not image_parts:
            return []

        prompt_lines = ["请提取完整世界书，并为每张图像返回 source_part_texts。"]
        if canonical_text:
            prompt_lines.extend(["剧本文本：", canonical_text[:12000]])
        if image_parts:
            prompt_lines.append("图像顺序与来源标识：")
            prompt_lines.extend(
                f"{index}. {item['source_ref']}"
                for index, item in enumerate(image_parts, start=1)
            )
        content: list[dict] = [{"type": "text", "text": "\n".join(prompt_lines)}]
        content.extend(
            {"type": "image", "data_url": item["data_url"]}
            for item in image_parts
        )
        return content

    @staticmethod
    def _openai_user_content(user_message: str | list[dict]) -> str | list[dict]:
        if isinstance(user_message, str):
            return user_message
        converted: list[dict] = []
        for item in user_message:
            if item.get("type") == "text":
                converted.append({"type": "input_text", "text": str(item.get("text") or "")})
            elif item.get("type") == "image":
                converted.append({"type": "input_image", "image_url": item.get("data_url", "")})
        return converted

    @staticmethod
    def _chat_user_content(user_message: str | list[dict]) -> str | list[dict]:
        if isinstance(user_message, str):
            return user_message
        converted: list[dict] = []
        for item in user_message:
            if item.get("type") == "text":
                converted.append({"type": "text", "text": str(item.get("text") or "")})
            elif item.get("type") == "image":
                converted.append({
                    "type": "image_url",
                    "image_url": {"url": item.get("data_url", "")},
                })
        return converted

    async def query_rules(self, args: dict) -> dict:
        if self.config.is_mock:
            return {
                "answer": "（mock 模式）COC 七版规则知识库未启用。",
                "ruleReference": "mock",
                "mechanicSuggestion": None,
            }
        question = args.get("question", "")
        context = args.get("context", {})

        prompt = (
            "你是一位 COC 七版规则专家。请根据规则知识回答以下问题。\n\n"
            "返回格式：\n"
            "{\n"
            '  "answer": "规则解释",\n'
            '  "ruleReference": "规则出处",\n'
            '  "mechanicSuggestion": {"type":"...","permission":"validate","payload":{}}\n'
            "}\n\n"
            f"问题：{question}\n"
            f"相关上下文：{json.dumps(context, ensure_ascii=False)}"
        )
        return await self._call_llm(prompt, temperature=0.3)

    async def query_knowledge(self, args: dict) -> dict:
        if self.config.is_mock:
            return {
                "answer": "（mock 模式）知识检索未启用。",
                "citations": [],
                "confidence": "low",
            }
        query = args.get("query", "")
        room_id = args.get("roomId", "")
        sources = args.get("sources", ["scenario", "rules"])

        prompt = (
            "你是一位 COC 守秘人知识库助手。请根据已知剧本和规则知识回答 Host 的查询。\n\n"
            "返回格式：\n"
            "{\n"
            '  "answer": "回答内容",\n'
            '  "citations": [{"source":"...","text":"..."}],\n'
            '  "confidence": "high|medium|low"\n'
            "}\n\n"
            f"查询：{query}\n"
            f"房间：{room_id}\n"
            f"检索范围：{', '.join(sources)}"
        )
        return await self._call_llm(prompt, temperature=0.3)

    def _build_generate_narrative_prompt(self, args: dict) -> str:
        lines: list[str] = []
        if args.get("scenario_title"):
            lines.append(f"剧本：{args['scenario_title']}")
        if args.get("investigator_name") or args.get("occupation"):
            role = f"调查员：{args.get('investigator_name', '未知调查员')}"
            if args.get("occupation"):
                role += f"（{args['occupation']}）"
            lines.append(role)
        if args.get("background"):
            lines.append(f"背景：{args['background'][:300]}")
        spoken = args.get("player_words") or args.get("declared_intent")
        if spoken:
            lines.append(f"玩家输入：{spoken}")
        if args.get("intent_type"):
            lines.append(f"行动类型：{args['intent_type']}")
        if args.get("previous_narrative"):
            lines.append(f"上一版叙事：{args['previous_narrative'][:500]}")
        if args.get("spoiler_constraint"):
            lines.append(f"额外约束：{args['spoiler_constraint'][:500]}")
        if args.get("room_id"):
            lines.append(f"房间：{args['room_id']}")
        if args.get("character_id"):
            lines.append(f"角色：{args['character_id']}")
        lines.append("请直接返回当前场景下的公开叙事，不要泄露守秘信息，并使用简体中文。")
        lines.append("如果上下文不足，只描述眼前可感知的细节和对玩家话语的直接反应，不要补造新地点、新人物或新机构。")
        return "\n".join(lines)

    def _build_turn_prompt(self, room_id: str, action: dict, context: dict) -> str:
        lines = [
            f"房间: {room_id}",
            "",
            f"玩家行动: {action.get('characterId', '?')} 说“{action.get('declaredIntent', '')}”。",
            f"行动类型: {action.get('intentType', 'unknown')}",
            "",
            "--- 上下文 ---",
            f"当前场景: {context.get('sceneName', '未知')}",
            f"场景描述: {context.get('sceneDescription', '')[:500]}",
            f"在场 NPC: {json.dumps(context.get('npcsPresent', []), ensure_ascii=False)}",
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
            "理智触发事件:\n"
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
            "根据 COC 七版战斗规则，确定行动顺序、提出检定请求、判定战术结果。\n"
            "返回 KpResponse JSON。"
        )
