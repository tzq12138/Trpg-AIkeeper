import json
import re
import uuid
import logging
import httpx
from ..models import AIResponse, StateSuggestion, RollRequest, TacticalPrompt, ScenarioKnowledgeGraph, EncounterSuggestion
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
   - encounterSuggestion: 当需要战斗或追逐遭遇时提供 {type: combat/chase, reason, suggestedParticipants: [{name, side, hp, dex, mov}], initialDistance}，不需要时为null
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

        query = self._adjudication_question(batch)
        results = []
        rule_search_completed = False
        rag_context = ''
        if self.rag_store:
            try:
                if query.strip():
                    results = self.rag_store.search(query, room_id=room_id, top_k=3)
                    rule_search_completed = True
                    rag_context = '\n'.join([f"[{r['source_type']}] {r['content']}" for r in results])
            except Exception as e:
                logger.warning('RAG search failed: %s', e)

        context['rag_context'] = rag_context
        has_rule_evidence = any(
            isinstance(result, dict) and result.get("source_type") == "rule"
            for result in results
        )
        existing_adjudication = None
        if query and rule_search_completed and not has_rule_evidence:
            existing_adjudication = self._find_room_adjudication(room_id, query)
            if existing_adjudication:
                context["room_adjudication"] = existing_adjudication

        try:
            if self.is_mock:
                response = self._mock_response(batch, context)
            else:
                response = await self._call_deepseek(batch, context)

            if query and rule_search_completed and not has_rule_evidence and not existing_adjudication:
                self._store_room_adjudication(room_id, query, scenario)
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

        adjudication = context.get("room_adjudication")
        if isinstance(adjudication, dict):
            summary = str(adjudication.get("summary") or "").strip()
            if summary:
                parts.append("\n当前公开场景的既有处理:")
                parts.append(summary[:500])
            minimal_state = adjudication.get("minimal_state")
            if isinstance(minimal_state, dict):
                for key in ("scene", "visible_fact", "situation"):
                    value = minimal_state.get(key)
                    if isinstance(value, str) and value.strip():
                        parts.append(f"  {key}: {value[:500]}")

        return "\n".join(parts)

    @staticmethod
    def _adjudication_question(batch: dict) -> str:
        return " ".join(
            str(action.get("declared_intent") or action.get("intent") or "").strip()
            for action in batch.get("actions", [])
            if isinstance(action, dict)
        ).strip()

    def _find_room_adjudication(self, room_id: str, question: str) -> dict | None:
        if not self.spoiler_controller:
            return None
        from ..rule_source_lifecycle import find_room_adjudication

        return find_room_adjudication(self.spoiler_controller.conn, room_id, question)

    def _store_room_adjudication(self, room_id: str, question: str, scenario: dict) -> None:
        if not self.spoiler_controller:
            return
        from ..rule_source_lifecycle import upsert_room_adjudication

        # Never retain model output, truth, identity, tokens, or hidden scenario data.
        minimal_state: dict[str, str] = {}
        raw_graph = scenario.get("knowledge_graph") if isinstance(scenario, dict) else None
        if isinstance(raw_graph, str):
            try:
                raw_graph = json.loads(raw_graph)
            except json.JSONDecodeError:
                raw_graph = {}
        scene = raw_graph.get("scene_description") if isinstance(raw_graph, dict) else ""
        if isinstance(scene, str) and scene.strip():
            minimal_state["scene"] = scene.strip()[:500]
        try:
            upsert_room_adjudication(
                self.spoiler_controller.conn,
                room_id,
                question,
                "已按当前公开场景状态处理该行动。",
                minimal_state,
                None,
            )
        except Exception as exc:
            logger.warning("Could not save room-local adjudication for %s: %s", room_id, exc)

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
                        from ..models import TacticalAction
                        actions_list.append(TacticalAction(
                            label=a.get("label", ""),
                            intent_type=a.get("intentType", "dialogue"),
                            params=a.get("params", {}),
                        ))
                tactical_prompts.append(TacticalPrompt(
                    text=t.get("text", ""),
                    actions=actions_list,
                ))

        enc_sugg = raw.get("encounterSuggestion")
        encounter_suggestion = None
        if enc_sugg and isinstance(enc_sugg, dict):
            encounter_suggestion = EncounterSuggestion(
                type=enc_sugg.get("type", "combat"),
                reason=enc_sugg.get("reason", ""),
                suggestedParticipants=enc_sugg.get("suggestedParticipants", []),
                initialDistance=enc_sugg.get("initialDistance", "medium"),
            )

        return AIResponse(
            narrative=raw.get("narrative", ""),
            state_suggestions=state_suggestions,
            roll_requests=roll_requests,
            tactical_prompts=tactical_prompts,
            clues_to_release=raw.get("cluesToRelease", []),
            keeper_notes=raw.get("keeperNotes", ""),
            encounter_suggestion=encounter_suggestion,
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
            encounter_suggestion=None,
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
            encounter_suggestion=None,
        )

    def get_failure_count(self, room_id: str) -> int:
        return self._consecutive_failures.get(room_id, 0)


STRUCTURE_SYSTEM_PROMPT = """你是一个TRPG剧本分析器。给定一段剧本原文，提取结构化信息并以JSON格式返回。

返回格式：
{
  "scenes": [{"scene_id": "stable-scene-slug", "name": "场景名", "description": "描述", "order": 1, "citation": {"source_ref": "page:1", "page_number": 1}}],
  "npcs": [{
    "npc_id": "稳定ID（英文slug，如 'professor-zhang'）",
    "name": "NPC真名（truth层）",
    "public_name": "玩家可见称呼（如NPC有伪装身份则为伪装名）",
    "role": "角色定位（如 关键证人/反派/受害者/盟友/路人）",
    "type": "类型（story/monster/ally/neutral）",
    "public_description": "玩家可见的简短描述（不超过80字）",
    "description": "Host/AI可见详细描述",
    "personality": "性格特征",
    "motivation": "动机目标",
    "is_hidden": false
  }],
  "clues": [{"name": "线索名", "description": "描述", "location": "所在场景", "is_hidden": false}],
  "branches": [{"branch_id": "stable-branch-slug", "from_scene_id": "stable-scene-slug", "to_scene_id": "stable-scene-slug", "conditions": [{"kind": "clue|scene", "id": "稳定线索或场景ID"}], "citation": {"source_ref": "page:1", "page_number": 1}}],
  "truth": {"summary": "真相摘要"},
  "endings": [{"ending_id": "stable-ending-slug", "name": "结局名", "description": "描述", "type": "victory/defeat/mixed", "completion_conditions": {"entered_scenes": ["stable-scene-slug"], "all_clues": ["stable-clue-slug"]}, "citation": {"source_ref": "page:1", "page_number": 1}}]
}

注意：隐藏NPC（真相尚未公开的反派/幕后人物）必须设置 is_hidden=true，并提供 public_description 作为玩家初步印象。
npc_id、scene_id 和 branch_id 必须稳定且唯一，建议使用英文slug格式。
branches 只提取原文明示的场景转换；每条必须引用支持它的来源，不得猜测路径或前置条件。"""


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

    return _normalize_kg(result)


def _generate_npc_id(name: str, role: str = "", index: int = 0) -> str:
    """Generate a stable npc_id when AI doesn't provide one.

    Strategy: slugify the name (keep alphanumeric + Chinese chars), append role hint if ambiguous.
    Falls back to index-based ID for unparseable names.
    """
    import hashlib
    raw = f"{name}:{role}"
    # Use first 8 hex chars of sha256 for stability
    slug = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"npc-{slug}"


def _ensure_npc_ids(npcs: list[dict], scenario_id: str = "") -> list[dict]:
    """Ensure every NPC in the list has a stable npc_id.

    - If AI provides npc_id, use it.
    - Otherwise generate from name+role.
    - Deduplicate: if multiple NPCs share the same generated id, append index suffix.
    """
    seen_ids: dict[str, int] = {}
    result = []
    for i, npc in enumerate(npcs):
        npc = dict(npc)  # shallow copy to avoid mutating caller
        if not npc.get("npc_id"):
            name = npc.get("name", "")
            role = npc.get("role", "")
            npc["npc_id"] = _generate_npc_id(name, role, i)
        # Deduplicate
        nid = npc["npc_id"]
        if nid in seen_ids:
            seen_ids[nid] += 1
            npc["npc_id"] = f"{nid}-{seen_ids[nid]}"
        else:
            seen_ids[nid] = 0
        result.append(npc)
    return result


def normalize_knowledge_graph(raw: dict) -> dict:
    """Canonicalize provider output without discarding import-only metadata."""
    if not isinstance(raw, dict):
        return {}

    normalized = dict(raw)
    normalized["title"] = (
        raw.get("scenarioTitle") or raw.get("title") or raw.get("scenario_title", "")
    )
    normalized["scenes"], scene_aliases = _normalize_scenes(raw.get("scenes"))
    normalized["npcs"] = _ensure_npc_ids(_dict_list(raw.get("npcs")))
    normalized["clues"] = _dict_list(raw.get("clues"))
    normalized["truth"] = raw.get("truth") if isinstance(raw.get("truth"), dict) else {}
    normalized["endings"] = _normalize_endings(raw.get("endings"))
    normalized["branches"] = _normalize_branches(
        raw.get("branches") or raw.get("scenarioBranches"),
        scene_aliases,
    )
    normalized["trigger_mechanics"] = _dict_list(
        raw.get("triggerMechanics")
        or raw.get("trigger_mechanics")
        or raw.get("triggerMechanisms")
    )
    return normalized


def _normalize_kg(raw: dict) -> dict:
    """Backward-compatible alias for callers using the former private helper."""
    return normalize_knowledge_graph(raw)


def _dict_list(value) -> list[dict]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _normalize_scenes(value) -> tuple[list[dict], dict[str, str]]:
    scenes: list[dict] = []
    aliases: dict[str, str] = {}
    for index, raw_scene in enumerate(_dict_list(value)):
        scene = dict(raw_scene)
        scene_id = _stable_identifier(
            scene,
            ("scene_id", "sceneId", "id"),
            "scene",
            index,
        )
        for key in ("scene_id", "sceneId", "id", "name"):
            alias = str(scene.get(key) or "").strip()
            if alias and alias not in aliases:
                aliases[alias] = scene_id
        scene.pop("sceneId", None)
        scene["scene_id"] = scene_id
        scenes.append(scene)
    return scenes, aliases


def _normalize_branches(value, scene_aliases: dict[str, str]) -> list[dict]:
    branches: list[dict] = []
    alias_keys = {"branchId", "fromSceneId", "toSceneId", "from", "to", "id"}
    for index, raw_branch in enumerate(_dict_list(value)):
        branch = {
            key: item
            for key, item in raw_branch.items()
            if key not in alias_keys and key not in {"branch_id", "from_scene_id", "to_scene_id"}
        }
        branch["branch_id"] = _stable_identifier(
            raw_branch,
            ("branch_id", "branchId", "id"),
            "branch",
            index,
        )
        from_scene_id = str(
            raw_branch.get("from_scene_id")
            or raw_branch.get("fromSceneId")
            or raw_branch.get("from")
            or ""
        ).strip()
        to_scene_id = str(
            raw_branch.get("to_scene_id")
            or raw_branch.get("toSceneId")
            or raw_branch.get("to")
            or ""
        ).strip()
        branch["from_scene_id"] = scene_aliases.get(from_scene_id, from_scene_id)
        branch["to_scene_id"] = scene_aliases.get(to_scene_id, to_scene_id)
        branch["conditions"] = _dict_list(raw_branch.get("conditions"))
        citation = raw_branch.get("citation")
        if isinstance(citation, dict):
            branch["citation"] = dict(citation)
        branches.append(branch)
    return branches


def _normalize_endings(value) -> list[dict]:
    endings: list[dict] = []
    alias_keys = {"endingId", "completionConditions", "id"}
    for index, raw_ending in enumerate(_dict_list(value)):
        ending = {
            key: item
            for key, item in raw_ending.items()
            if key not in alias_keys and key not in {"ending_id", "completion_conditions"}
        }
        ending["ending_id"] = _stable_identifier(
            raw_ending,
            ("ending_id", "endingId", "id"),
            "ending",
            index,
        )
        conditions = (
            raw_ending.get("completion_conditions")
            or raw_ending.get("completionConditions")
        )
        if isinstance(conditions, dict):
            ending["completion_conditions"] = dict(conditions)
        citation = raw_ending.get("citation")
        if isinstance(citation, dict):
            ending["citation"] = dict(citation)
        endings.append(ending)
    return endings


def _stable_identifier(value: dict, keys: tuple[str, ...], prefix: str, index: int) -> str:
    for key in keys:
        candidate = str(value.get(key) or "").strip()
        if candidate:
            return candidate
    import hashlib

    seed = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return f"{prefix}-{hashlib.sha256(f'{index}:{seed}'.encode('utf-8')).hexdigest()[:12]}"


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
            npcs.append({"name": name, "role": "未知", "description": "", "is_hidden": False})
        if len(npcs) >= 10:
            break

    npcs = _ensure_npc_ids(npcs)

    clues = []
    clue_patterns = re.findall(r"(?:线索|证据|发现|物品)[：:]\s*(.+?)(?:\n|$)", raw_text)
    for clue in clue_patterns[:5]:
        clues.append({"name": clue.strip()[:30], "description": clue.strip(), "location": ""})

    return {
        "scenes": scenes,
        "npcs": npcs,
        "clues": clues,
        "branches": [],
        "truth": None,
        "endings": [],
    }
