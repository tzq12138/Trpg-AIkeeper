import json
import re
import uuid
import logging
import httpx
from .models import AIResponse, StateSuggestion, RollRequest, TacticalPrompt, ScenarioKnowledgeGraph
from .spoiler_control import SpoilerController

logger = logging.getLogger(__name__)

AIKP_SYSTEM_PROMPT = """你是一位TRPG主持人(KP)，负责推进剧情、扮演NPC、控制氛围和释放线索。

规则：
1. 不要自行决定骰子结果，需要检定时只提出检定请求。
2. 每次回应最多释放一个明确线索碎片。
3. 不要剧透真相和结局。
4. 输出必须是JSON对象，包含以下字段：
   - narrative: 叙事文本（简体中文）
   - stateSuggestions: 数组，每项包含 {type, target, value, reason}
   - rollRequests: 数组，每项包含 {skillName, difficulty, bonusDice, reason, visibility, targetCharacter}
   - tacticalPrompts: 数组，每项包含 {text, actions: [{label, intentType, params}]}
   - cluesToRelease: 数组，线索ID列表
   - keeperNotes: 内部备注（不展示给玩家）
"""


class AIKP:
    def __init__(
        self,
        api_key: str = "",
        model: str = "deepseek-v4-pro",
        api_base: str = "https://api.deepseek.com",
        spoiler_controller: SpoilerController | None = None,
        rag_store=None,
    ):
        self.api_key = api_key
        self.model = model
        self.api_base = api_base
        self.spoiler_controller = spoiler_controller
        self.rag_store = rag_store
        self._consecutive_failures: dict[str, int] = {}

    @property
    def is_mock(self) -> bool:
        return not self.api_key

    async def process_batch(self, room_id: str, batch: dict, scenario: dict) -> AIResponse:
        if self.spoiler_controller:
            context = self.spoiler_controller.build_kp_context(
                room_id, scenario, batch.get("actions", [])
            )
        else:
            context = {
                "spoiler_level": "standard",
                "actions": batch.get("actions", []),
                "scenario_title": scenario.get("title", ""),
            }

        rag_context = ''
        if self.rag_store:
            try:
                action_texts = [a.get('declared_intent', '') for a in batch.get('actions', [])]
                query = ' '.join(action_texts)
                if query.strip():
                    results = self.rag_store.search(query, room_id=room_id, top_k=3)
                    rag_context = '\n'.join([f"[{r['source_type']}] {r['content']}" for r in results])
            except Exception as e:
                logger.warning('RAG search failed: %s', e)

        context['rag_context'] = rag_context

        try:
            if self.is_mock:
                response = self._mock_response(batch, context)
            else:
                response = await self._call_deepseek(batch, context)

            self._consecutive_failures[room_id] = 0
            return response
        except Exception as e:
            logger.error(f"AI KP error for room {room_id}: {e}")
            failures = self._consecutive_failures.get(room_id, 0) + 1
            self._consecutive_failures[room_id] = failures
            return self._fallback_response(batch, str(e), failures)

    async def _call_deepseek(self, batch: dict, context: dict) -> AIResponse:
        user_msg = self._build_user_message(batch, context)

        async with httpx.AsyncClient(timeout=30) as client:
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
                        {"role": "system", "content": AIKP_SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": 0.8,
                },
            )
            response.raise_for_status()
            data = response.json()

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            raise RuntimeError("DeepSeek response missing content")

        try:
            raw = json.loads(content)
        except json.JSONDecodeError:
            raise RuntimeError("DeepSeek response is not valid JSON")

        return self._normalize_response(raw)

    def _build_user_message(self, batch: dict, context: dict) -> str:
        actions = batch.get("actions", [])
        action_lines = []
        for a in actions:
            char_id = a.get("character_id", "unknown")
            intent = a.get("declared_intent", a.get("intent", ""))
            action_lines.append(f"- {char_id}: {intent}")

        parts = [
            f"场景: {context.get('scenario_title', '未知')}",
            f"剧透级别: {context.get('spoiler_level', 'standard')}",
            "",
            "玩家行动:",
            *action_lines,
        ]

        for cc in context.get("character_contexts", []):
            vis = cc.get("visible_scenario", {})
            parts.append(f"\n角色 {cc['character_id']} 可见信息:")
            if vis.get("scene_description"):
                parts.append(f"  场景: {vis['scene_description'][:200]}")
            for clue in vis.get("visible_clues", [])[:3]:
                parts.append(f"  线索: {clue.get('text', '')[:100]}")

        if context.get("rag_context"):
            parts.append("\n相关知识库参考:")
            parts.append(context["rag_context"])

        return "\n".join(parts)

    def _normalize_response(self, raw: dict) -> AIResponse:
        state_suggestions = []
        for s in raw.get("stateSuggestions", []):
            if isinstance(s, dict):
                state_suggestions.append(StateSuggestion(
                    type=s.get("type", "status_tag"),
                    target=s.get("target", ""),
                    value=s.get("value", ""),
                    reason=s.get("reason", ""),
                ))

        roll_requests = []
        for r in raw.get("rollRequests", []):
            if isinstance(r, dict):
                roll_requests.append(RollRequest(
                    skill_name=r.get("skillName", "侦查"),
                    difficulty=r.get("difficulty", "regular"),
                    bonus_dice=r.get("bonusDice", 0),
                    reason=r.get("reason", ""),
                    visibility=r.get("visibility", "public"),
                    target_character=r.get("targetCharacter"),
                ))

        tactical_prompts = []
        for t in raw.get("tacticalPrompts", []):
            if isinstance(t, dict):
                actions_list = []
                for a in t.get("actions", []):
                    if isinstance(a, dict):
                        from .models import TacticalAction
                        actions_list.append(TacticalAction(
                            label=a.get("label", ""),
                            intent_type=a.get("intentType", "dialogue"),
                            params=a.get("params", {}),
                        ))
                tactical_prompts.append(TacticalPrompt(
                    text=t.get("text", ""),
                    actions=actions_list,
                ))

        return AIResponse(
            narrative=raw.get("narrative", ""),
            state_suggestions=state_suggestions,
            roll_requests=roll_requests,
            tactical_prompts=tactical_prompts,
            clues_to_release=raw.get("cluesToRelease", []),
            keeper_notes=raw.get("keeperNotes", ""),
        )

    def _mock_response(self, batch: dict, context: dict) -> AIResponse:
        actions = batch.get("actions", [])
        first_action = actions[0] if actions else {}
        intent_text = first_action.get("declared_intent", first_action.get("intent", ""))
        char_id = first_action.get("character_id", "unknown")

        is_investigate = bool(re.search(r"调查|搜索|查看|观察|检查|侦查|look|search|examine", intent_text))
        is_dialogue = bool(re.search(r"说话|交谈|问|对话|talk|ask|speak", intent_text))
        is_move = bool(re.search(r"走|移动|前进|进入|move|go|enter", intent_text))

        narrative = self._mock_narrative(intent_text, char_id, is_investigate, is_dialogue, is_move)

        roll_requests = []
        if is_investigate:
            roll_requests.append(RollRequest(
                skill_name="侦查",
                difficulty="regular",
                reason=f"{char_id}正在仔细调查周围环境。",
                visibility="public",
            ))
        elif is_dialogue:
            roll_requests.append(RollRequest(
                skill_name="话术",
                difficulty="regular",
                reason=f"{char_id}正在与人交谈。",
                visibility="public",
            ))

        tactical_prompts = []
        if is_investigate:
            tactical_prompts.append(TacticalPrompt(
                text="你可以选择更仔细地检查某个特定区域，或者询问同伴是否注意到什么。",
            ))

        return AIResponse(
            narrative=narrative,
            roll_requests=roll_requests,
            tactical_prompts=tactical_prompts,
            keeper_notes=f"模拟AI响应。行动: {intent_text[:50]}",
        )

    def _mock_narrative(self, intent: str, char_id: str, is_inv: bool, is_dial: bool, is_move: bool) -> str:
        if is_inv:
            return f"KP注视着{char_id}的动作：\u201c{intent}\u201d。空气中似乎弥漫着某种不易察觉的异样。你需要进行一次侦查检定，才能确定你注意到的是否真的值得关注。"
        if is_dial:
            return f"KP转向{char_id}：\u201c{intent}\u201d。对方的目光在你身上停留了片刻，似乎在衡量着什么。"
        if is_move:
            return f"{char_id}向前移动。KP描述道：你的脚步声在空旷的空间里回荡。前方的走廊在微弱的光线下延伸向未知。"
        return f"KP记录下{char_id}的行动：\u201c{intent}\u201d。场景继续向前推进，但真相暂时仍藏在阴影之后。"

    def _fallback_response(self, batch: dict, error: str, failures: int) -> AIResponse:
        actions = batch.get("actions", [])
        first_action = actions[0] if actions else {}
        intent_text = first_action.get("declared_intent", first_action.get("intent", "未知行动"))

        narrative = f"KP稍作停顿，重新整理思绪。({failures}次尝试后降级处理)"

        if failures >= 3:
            narrative = f"KP连续处理失败（{failures}次），建议房主检查场景配置或切换为手动模式。"

        return AIResponse(
            narrative=narrative,
            keeper_notes=f"AI降级响应。错误: {error}。连续失败: {failures}",
        )

    def get_failure_count(self, room_id: str) -> int:
        return self._consecutive_failures.get(room_id, 0)


STRUCTURE_SYSTEM_PROMPT = """你是一个TRPG剧本分析器。给定一段剧本原文，提取结构化信息并以JSON格式返回。

返回格式：
{
  "scenes": [{"name": "场景名", "description": "描述", "order": 1}],
  "npcs": [{"name": "NPC名", "role": "角色定位", "description": "描述"}],
  "clues": [{"name": "线索名", "description": "描述", "location": "所在场景"}],
  "truth": {"summary": "真相摘要"},
  "endings": [{"name": "结局名", "description": "描述", "type": "victory/defeat/mixed"}]
}"""


async def structure_scenario(raw_text: str, api_key: str = "", api_base: str = "https://api.deepseek.com", model: str = "deepseek-v4-pro") -> dict:
    if api_key:
        return await _structure_with_ai(raw_text, api_key, api_base, model)
    return _structure_mock(raw_text)


async def _structure_with_ai(raw_text: str, api_key: str, api_base: str, model: str) -> dict:
    truncated = raw_text[:8000]
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{api_base}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": STRUCTURE_SYSTEM_PROMPT},
                    {"role": "user", "content": f"请分析以下TRPG剧本原文：\n\n{truncated}"},
                ],
                "temperature": 0.3,
            },
        )
        response.raise_for_status()
        data = response.json()

    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        return _structure_mock(raw_text)

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        return _structure_mock(raw_text)

    return {
        "scenes": result.get("scenes", []),
        "npcs": result.get("npcs", []),
        "clues": result.get("clues", []),
        "truth": result.get("truth"),
        "endings": result.get("endings", []),
    }


def _structure_mock(raw_text: str) -> dict:
    scene_splits = re.split(r"\n{2,}|\n(?=第[一二三四五六七八九十\d]+[章节幕]|Scene\s*\d|场景\s*\d)", raw_text)
    scenes = []
    for i, chunk in enumerate(scene_splits[:10]):
        chunk = chunk.strip()
        if len(chunk) < 10:
            continue
        name = chunk[:30].split("\n")[0].strip()
        scenes.append({"name": name, "description": chunk[:200], "order": i + 1})

    if not scenes:
        scenes.append({"name": "默认场景", "description": raw_text[:200], "order": 1})

    npcs = []
    npc_patterns = re.findall(r"(?:NPC|角色|人物)[：:]\s*(.+?)(?:\n|$)", raw_text)
    name_patterns = re.findall(r"[\u300c\u201c\u300e](.+?)[\u300d\u201d\u300f]", raw_text)
    seen_names: set[str] = set()
    for name in npc_patterns + name_patterns:
        name = name.strip()
        if 1 < len(name) < 20 and name not in seen_names:
            seen_names.add(name)
            npcs.append({"name": name, "role": "未知", "description": ""})
        if len(npcs) >= 10:
            break

    clues = []
    clue_patterns = re.findall(r"(?:线索|证据|发现|物品)[：:]\s*(.+?)(?:\n|$)", raw_text)
    for clue in clue_patterns[:5]:
        clues.append({"name": clue.strip()[:30], "description": clue.strip(), "location": ""})

    return {
        "scenes": scenes,
        "npcs": npcs,
        "clues": clues,
        "truth": None,
        "endings": [],
    }
