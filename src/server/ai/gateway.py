"""AiGateway — unified AI call entry point with per-task validation and provider chain."""

import json
import logging
import time
from typing import Any

from ..config import Settings
from .contracts import KpResponse, KnowledgeAnswer, NarrativePayload
from ..models import DirectorPlanDTO, NarrationResultDTO
from .providers import (
    BaseAiProvider,
    ConfiguredOpenAIProvider,
    DeepSeekProvider,
    KpMcpProvider,
    LocalFallbackProvider,
)
from ..scenario.content_package import ContentPackage

logger = logging.getLogger(__name__)
_IMPORT_STRUCTURE_TIMEOUT_SECONDS = 180

SCENARIO_STRUCTURE_SYSTEM_PROMPT = """你是TRPG剧本分析器。只返回JSON对象。
提取 scenes、npcs、clues、branches、truth、endings。
每个 scene 必须有稳定 scene_id；每个 branch 必须有 branch_id、from_scene_id、to_scene_id、conditions 和 citation。
每个 ending 必须有 ending_id、citation，以及只使用 all_clues、any_clues、entered_scenes、event_types、room_status 的 completion_conditions。
branches 只包含原文明示的场景转换，citation 必须定位支持该转换的来源；不得猜测路径或条件。"""

RUNTIME_CONTRACT_REPAIR_PROMPT = """你是TRPG剧本运行时证据契约修复器。只返回JSON对象，且只能返回 branches 和 endings。
只能依据输入剧本与既有稳定 ID 补充缺失字段，不得新增场景、线索、NPC、事实或结局。
每个 branch 必须使用已有 scene_id，包含 branch_id、from_scene_id、to_scene_id、conditions 和 citation；若原文没有明确转换，返回空数组。
每个 ending 必须使用已有 ending_id，citation 必须是 {"source_ref":"page:N","page_number":N} 形式的对象。
completion_conditions 只能使用 all_clues、any_clues、entered_scenes、event_types、room_status；数组必须非空，room_status 只能为 active，event_types 只能为 s2c_clue_discovered、s2c_scene_sync、s2c_action_completed 或 s2c_encounter_resolved。
无法从来源验证的字段必须省略，绝不能用文字引用、虚构事件名或猜测路径。"""

# Per-task expected return shapes for validation (fallback to raw dict if no schema)
TASK_SCHEMAS: dict[str, Any] = {
    "resolve_turn": KpResponse,
    "generate_narrative": None,
    "structure_scenario": None,        # validated by caller
    "compile_mechanic": None,           # validated by caller
    "generate_map": None,               # validated by caller
    "bind_scenario_assets": None,       # validated by caller
    "review_scenario": None,            # validated by scenario review service
    "analyze_director_action": DirectorPlanDTO,
    "narrate_action": None,            # validated after local action_id/provider_source injection
    "query_knowledge": KnowledgeAnswer,
    "resolve_sanity": KpResponse,
    "resolve_combat_round": KpResponse,
}

DIRECTOR_REQUIRED_KEYS = {
    "action_id",
    "context_version",
    "actor_display_name",
    "declared_intent",
    "interpreted_intent",
    "intent_type",
    "preconditions",
    "mechanic_plan",
    "state_patch",
    "event_plan",
    "semantic_progression",
    "npc_reactions",
    "time_impact",
    "visibility",
    "basis_refs",
    "citations",
    "confidence",
    "requires_player_clarification",
    "clarification_options",
    "requires_host_exception",
    "exception_reason",
    "narration_mode",
}

DIRECTOR_PROVIDER_CORE_KEYS = {
    "interpreted_intent",
    "intent_type",
    "confidence",
    "requires_player_clarification",
    "requires_host_exception",
    "narration_mode",
}
DIRECTOR_SUPPORTED_INTENT_TYPES = {
    "voice_command",
    "dialogue",
    "skill_check",
    "move",
    "use_item",
    "show_item",
    "combat_action",
    "chase_action",
    "retroactive_item_claim",
}


class AiGateway:
    """Unified gateway for all AI calls. Provider order from env/DB config."""

    def __init__(self, settings: Settings | None = None, db_conn=None):
        self.settings = settings or Settings.from_env()
        self.db = db_conn
        self._providers: dict[str, BaseAiProvider] = {}
        self._provider_order: list[str] = []
        self._init_providers()

    def _init_providers(self):
        s = self.settings
        self._providers["deepseek"] = DeepSeekProvider(
            api_key=s.deepseek_api_key, model=s.deepseek_model)
        self._providers["mcp"] = KpMcpProvider(
            server_url=s.kp_mcp_server_url, timeout=s.ai_timeout_seconds)
        self._providers["local"] = LocalFallbackProvider()
        self._provider_order = [p.strip() for p in s.ai_provider_order.split(",") if p.strip() in self._providers]
        if not self._provider_order:
            self._provider_order = ["mcp", "deepseek", "local"]

    def _get_ordered_providers(self, room_id: str | None = None) -> list[BaseAiProvider]:
        order = self._provider_order
        if room_id and self.db:
            try:
                from .ai_config import get_room_ai_config
                room_cfg = get_room_ai_config(self.db, room_id)
                if room_cfg and room_cfg.get("provider_order"):
                    order = [p.strip() for p in room_cfg["provider_order"].split(",") if p.strip() in self._providers]
            except Exception as exc:
                logger.warning("Failed to load room AI config for room=%s: %s", room_id, exc)
        providers = [self._providers[p] for p in order]
        if self.db:
            try:
                from .provider_config import AiProviderConfigStore

                active = AiProviderConfigStore(self.db).get_active_internal()
                if active and active.get("test_status") == "passed":
                    providers.insert(
                        0,
                        ConfiguredOpenAIProvider(
                            active,
                            timeout=self.settings.ai_timeout_seconds,
                        ),
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to load active configured AI provider: %s",
                    type(exc).__name__,
                )
        return providers

    # ── Public API ──

    async def generate_narrative(self, context: dict, room_id: str | None = None) -> NarrativePayload:
        result = await self._call_providers(
            "generate_narrative",
            self._prepare_narrative_context(context),
            room_id,
        )
        return self._normalize_narrative_result(result)

    async def analyze_action_draft(self, context: dict, room_id: str | None = None) -> dict | None:
        prepared = dict(context)
        prepared["system_prompt"] = (
            "你是TRPG行动分析器。只输出JSON，不执行骰子或状态修改。"
            "字段仅限 understanding_summary, risk, intent_type, suggested_skill, difficulty, "
            "resource_impacts, visibility, movement_target, confirmation_requirements, confidence, citations。"
        )
        prepared["user_message"] = json.dumps(
            {
                "declared_intent": context.get("declared_intent", ""),
                "intent_type": context.get("intent_type", ""),
                "base_state_version": context.get("base_state_version", 0),
            },
            ensure_ascii=False,
        )
        result = await self._call_providers(
            "analyze_action_draft",
            prepared,
            room_id,
            disable_local_fallback=True,
        )
        return result if isinstance(result, dict) else None

    async def analyze_director_action(self, context: dict, room_id: str | None = None) -> dict | None:
        prepared = dict(context)
        prepared["system_prompt"] = (
            "You are AI-Keeper Director. Return structured JSON only. "
            "Do not directly mutate authoritative game state; state_patch is advisory only. "
            "Required fields include interpreted_intent, intent_type, confidence, "
            "requires_player_clarification, requires_host_exception, narration_mode. "
            "intent_type must be one of voice_command, dialogue, skill_check, move, use_item, "
            "show_item, combat_action, chase_action, retroactive_item_claim. "
            "Set requires_host_exception to true only when exception_reason is a concrete, "
            "player-safe reason that cannot be resolved by the supplied evidence. "
            "For a normal visible action, set it to false. When the declared action selects "
            "a visible semantic branch, return semantic_progression.targetNodeId with the "
            "matching supplied citation; never mention internal node or entry identifiers in "
            "interpreted_intent. "
            "Use actor_display_name for narration identity, not character_id."
        )
        prepared["user_message"] = json.dumps(context, ensure_ascii=False)
        result = await self._call_providers(
            "analyze_director_action",
            prepared,
            room_id,
            disable_local_fallback=True,
        )
        if isinstance(result, DirectorPlanDTO):
            return result.model_dump(mode="json", by_alias=True)
        if not isinstance(result, dict):
            return None
        try:
            validated = DirectorPlanDTO(**result)
        except Exception:
            return None
        return validated.model_dump(mode="json", by_alias=True)

    async def narrate_action(
        self,
        context: dict,
        room_id: str | None = None,
        *,
        action_id: str | None = None,
    ) -> dict | None:
        local_action_id = str(action_id or context.get("local_action_id") or context.get("action_id") or "")
        prepared = _scrub_narrator_provider_payload(context)
        prepared["system_prompt"] = (
            "You are AI-Keeper Narrator. Return JSON only. "
            "Narrate only from allowed_facts and deterministic_rule_outcome. "
            "Do not create state_patch, mutations, hidden facts, room_id, character_id, action_id, or internal IDs. "
            "Required fields: context_version, director_plan_digest, narrative_text, "
            "environment_changes, interactable_objects, open_question, redacted_citations, "
            "style_pack_version, fact_refs, status. status must be exactly 'completed'. "
            "fact_refs must be an object with exactly narrative_text, environment_changes, "
            "interactable_objects, and open_question keys; every value must be a non-empty "
            "list of fact_ref values copied from allowed_facts. Do not return provider_source."
        )
        prepared["user_message"] = json.dumps(
            _scrub_narrator_provider_payload(context),
            ensure_ascii=False,
        )
        result = await self._call_providers(
            "narrate_action",
            prepared,
            room_id,
            disable_local_fallback=True,
        )
        if not isinstance(result, dict):
            return None
        result = _normalize_narrator_provider_result(result, context)
        result = {**result, "action_id": local_action_id}
        try:
            validated = NarrationResultDTO(**result)
        except Exception:
            return None
        return validated.model_dump(mode="json", by_alias=True)

    async def structure_scenario(self, raw_text: str) -> dict:
        # Truncate to avoid 400 from DeepSeek (matches MCP-side 12000-char limit).
        # 59-page PDFs can easily exceed model context windows.
        truncated = raw_text[:12000]
        context = {"rawText": truncated, "format": "full",
                   "timeout_seconds": _IMPORT_STRUCTURE_TIMEOUT_SECONDS,
                   "system_prompt": SCENARIO_STRUCTURE_SYSTEM_PROMPT,
                   "user_message": json.dumps({"rawText": truncated}, ensure_ascii=False)}
        return await self._call_providers("structure_scenario", context)

    async def structure_content_package(self, package: ContentPackage | dict) -> dict:
        if isinstance(package, ContentPackage):
            payload = package.to_provider_payload()
        else:
            payload = dict(package)

        canonical_text = (
            payload.get("canonical_text")
            or payload.get("rawText")
            or ""
        )
        requires_multimodal = bool(payload.get("requires_multimodal"))

        if requires_multimodal:
            context = {
                "contentPackage": payload,
                "canonical_text": canonical_text,
                "rawText": canonical_text,
                "format": "full",
                "timeout_seconds": _IMPORT_STRUCTURE_TIMEOUT_SECONDS,
                "system_prompt": SCENARIO_STRUCTURE_SYSTEM_PROMPT,
                "user_message": json.dumps(payload, ensure_ascii=False),
            }
            result = await self._call_providers(
                "structure_scenario",
                context,
                required_capabilities={"image"},
                disable_local_fallback=True,
            )
            if result is not None:
                return result
            if len(canonical_text.strip()) >= 50:
                return await self.structure_scenario(canonical_text)
            raise RuntimeError("multimodal_provider_unavailable")

        return await self.structure_scenario(canonical_text)

    async def repair_runtime_contract(
        self,
        package: ContentPackage | dict,
        knowledge_graph: dict,
    ) -> dict | None:
        payload = (
            package.to_provider_payload()
            if isinstance(package, ContentPackage)
            else dict(package)
        )
        canonical_text = str(payload.get("canonical_text") or "")
        payload["canonical_text"] = (
            f"{canonical_text}\n\n既有稳定世界书（只能引用其中 ID）：\n"
            f"{json.dumps(knowledge_graph, ensure_ascii=False)}"
        )
        context = {
            "contentPackage": payload,
            "canonical_text": payload["canonical_text"],
            "rawText": payload["canonical_text"],
            "format": "runtime_contract_repair",
            "timeout_seconds": _IMPORT_STRUCTURE_TIMEOUT_SECONDS,
            "system_prompt": RUNTIME_CONTRACT_REPAIR_PROMPT,
            "user_message": json.dumps(payload, ensure_ascii=False),
        }
        required_capabilities = {"image"} if payload.get("requires_multimodal") else None
        return await self._call_providers(
            "repair_runtime_contract",
            context,
            required_capabilities=required_capabilities,
            disable_local_fallback=True,
        )

    async def compile_mechanic(self, intent: Any, scenario: dict, character: dict) -> dict:
        intent_dict = intent.model_dump() if hasattr(intent, 'model_dump') else intent
        context = {"intent": intent_dict, "scenario": scenario, "character": character,
                   "system_prompt": "你是TRPG机制编译器。返回 triggeredMechanic, skillName, difficulty。",
                   "user_message": json.dumps(intent_dict, ensure_ascii=False)}
        return await self._call_providers("compile_mechanic", context)

    async def generate_map(self, scenes: list[dict]) -> dict:
        context = {"scenes": scenes,
                   "system_prompt": "你是TRPG地图生成器。必须返回 JSON 对象，包含 nodes 和 edges 数组。",
                   "user_message": json.dumps({"scenes": scenes}, ensure_ascii=False)}
        result = await self._call_providers(
            "generate_map",
            context,
            disable_local_fallback=True,
        )
        if not isinstance(result, dict):
            return None
        nodes = result.get("nodes")
        edges = result.get("edges")
        if not isinstance(nodes, list) or not isinstance(edges, list):
            return None
        return result

    async def bind_scenario_assets(
        self,
        assets: list[dict],
        targets: list[dict],
    ) -> list[dict]:
        package = {
            "canonical_text": json.dumps({"targets": targets}, ensure_ascii=False),
            "requires_multimodal": True,
            "parts": [
                {
                    "ordinal": index,
                    "kind": "image",
                    "mime_type": asset.get("mime_type", "image/png"),
                    "data_url": asset.get("data_url", ""),
                    "source_ref": asset.get("asset_id", f"asset:{index}"),
                    "metadata": {
                        "asset_id": asset.get("asset_id", ""),
                        "filename": asset.get("original_name", ""),
                    },
                }
                for index, asset in enumerate(assets, start=1)
            ],
        }
        context = {
            "contentPackage": package,
            "system_prompt": (
                "你是TRPG图片素材绑定器。只返回JSON对象：bindings数组。"
                "每项字段为 asset_id,target_type,target_key,confidence,evidence。"
                "target_type和target_key只能从给定targets中选择；无法判断时confidence设为0。"
            ),
            "user_message": json.dumps({"targets": targets}, ensure_ascii=False),
        }
        result = await self._call_providers(
            "bind_scenario_assets",
            context,
            required_capabilities={"image"},
            disable_local_fallback=True,
        )
        bindings = result.get("bindings") if isinstance(result, dict) else None
        return [item for item in (bindings or []) if isinstance(item, dict)]

    async def review_scenario(self, context: dict) -> dict | None:
        prepared = dict(context)
        prepared["system_prompt"] = (
            "You review a TRPG module against its supplied source excerpts. "
            "Return JSON only with summary and suggestions. Each suggestion must contain "
            "target_type, target_key, payload, provenance, citation, and confidence. "
            "Use provenance=source only when citation.source_part_id names a supplied excerpt; "
            "never invent facts, citations, or source IDs. Suggestions are drafts for a human "
            "administrator and must not claim to have applied changes."
        )
        prepared["user_message"] = json.dumps(
            {
                "mode": prepared.get("mode", "issue"),
                "issue": prepared.get("issue"),
                "knowledge_graph": prepared.get("knowledge_graph", {}),
                "source_parts": prepared.get("source_parts", []),
            },
            ensure_ascii=False,
        )
        result = await self._call_providers(
            "review_scenario",
            prepared,
            disable_local_fallback=True,
        )
        return result if isinstance(result, dict) else None

    async def query_knowledge(self, query: str, room_id: str, sources: str = "both") -> KnowledgeAnswer:
        context = {"query": query, "roomId": room_id, "sources": sources,
                   "system_prompt": "你是TRPG知识库。从剧本和规则书中检索回答。返回 answer, citations, confidence。",
                   "user_message": json.dumps({"query": query, "sources": sources}, ensure_ascii=False)}
        result = await self._call_providers("query_knowledge", context, room_id)
        if isinstance(result, KnowledgeAnswer):
            return result
        if isinstance(result, dict):
            return KnowledgeAnswer(**result)
        return KnowledgeAnswer(answer=str(result))

    async def resolve_turn(self, context: dict, room_id: str | None = None) -> KpResponse:
        result = await self._call_providers("resolve_turn", context, room_id)
        if isinstance(result, KpResponse):
            return result
        return KpResponse(**result) if isinstance(result, dict) else KpResponse()

    async def resolve_sanity(self, context: dict, room_id: str | None = None) -> KpResponse:
        result = await self._call_providers("resolve_sanity", context, room_id)
        if isinstance(result, KpResponse):
            return result
        return KpResponse(**result) if isinstance(result, dict) else KpResponse()

    async def resolve_combat_round(self, context: dict, room_id: str | None = None) -> KpResponse:
        result = await self._call_providers("resolve_combat_round", context, room_id)
        if isinstance(result, KpResponse):
            return result
        return KpResponse(**result) if isinstance(result, dict) else KpResponse()

    async def health_check(self) -> dict:
        results = {}
        for name, provider in self._providers.items():
            try:
                results[name] = await provider.health_check()
            except Exception as e:
                results[name] = f"error:{e}"
        return {
            "deepseek_configured": bool(self.settings.deepseek_api_key),
            "hermes_reachable": results.get("mcp", False),
            "hermes_url": self.settings.kp_mcp_server_url,
            "provider_order": self._provider_order,
            "provider_health": results,
        }

    # ── Internal ──

    async def _call_providers(
        self,
        task_type: str,
        context: dict,
        room_id: str | None = None,
        required_capabilities: str | set[str] | None = None,
        disable_local_fallback: bool = False,
    ) -> Any:
        providers = self._get_ordered_providers(room_id)
        required_set = _normalize_required_capabilities(required_capabilities)
        if required_set:
            providers = [provider for provider in providers if provider.supports(required_set)]
        if disable_local_fallback:
            providers = [provider for provider in providers if provider.name != "local"]
        fallback_chain: list[str] = []
        t_start = time.monotonic()
        last_error = ""
        provider_used = "none"
        status = "error"
        final_result: Any = None

        for provider in providers:
            try:
                raw = await provider.call(task_type, context)
                if raw is None:
                    fallback_chain.append(f"{provider.name}:null_response")
                    continue
                if task_type == "analyze_director_action":
                    if (
                        not isinstance(raw, dict)
                        or not DIRECTOR_PROVIDER_CORE_KEYS.issubset(raw.keys())
                    ):
                        fallback_chain.append(f"{provider.name}:incomplete_director_plan")
                        continue
                    raw = _normalize_director_provider_result(raw, context)
                    if not DIRECTOR_REQUIRED_KEYS.issubset(raw.keys()):
                        fallback_chain.append(f"{provider.name}:incomplete_director_plan")
                        continue
                if task_type == "narrate_action":
                    if not isinstance(raw, dict):
                        fallback_chain.append(f"{provider.name}:invalid_narration")
                        continue
                    raw = _normalize_narrator_provider_result(raw, context)
                    try:
                        NarrationResultDTO(
                            **{
                                **raw,
                                "action_id": "provider-validation",
                                "provider_source": _analysis_source_for_provider(provider.name),
                            }
                        )
                    except Exception:
                        fallback_chain.append(f"{provider.name}:invalid_narration")
                        continue
                if task_type == "structure_scenario" and not _is_worldbook_result(raw):
                    logger.warning(
                        "structure_scenario returned an invalid worldbook from %s",
                        provider.name,
                    )
                    fallback_chain.append(f"{provider.name}:invalid_worldbook")
                    continue

                # Per-task validation
                schema = TASK_SCHEMAS.get(task_type)
                if schema and (hasattr(schema, "model_fields") or hasattr(schema, "__fields__")):
                    try:
                        validated = schema(**raw)
                        final_result = validated
                    except Exception as ve:
                        logger.warning("%s schema validation failed for %s: %s", task_type, provider.name, ve)
                        fallback_chain.append(f"{provider.name}:schema_fail")
                        continue
                else:
                    final_result = raw

                provider_used = provider.name
                status = "success"
                if task_type == "analyze_director_action":
                    source = _analysis_source_for_provider(provider.name)
                    if hasattr(final_result, "model_copy"):
                        final_result = final_result.model_copy(
                            update={"analysis_source": source}
                        )
                    elif isinstance(final_result, dict):
                        final_result = {**final_result, "analysis_source": source}
                if task_type == "narrate_action" and isinstance(final_result, dict):
                    final_result = {
                        **final_result,
                        "provider_source": _analysis_source_for_provider(provider.name),
                    }
                if isinstance(final_result, KpResponse) and final_result.error:
                    status = "fallback"
                    last_error = str(final_result.error)
                fallback_chain.append(f"{provider.name}:ok")
                break
            except Exception as e:
                last_error = str(e)
                fallback_chain.append(f"{provider.name}:{type(e).__name__}")
                logger.warning("Provider %s failed for %s: %s", provider.name, task_type, e)
        else:
            # All providers failed
            final_result = await self._fallback_for_task(
                task_type,
                context,
                fallback_chain,
                last_error,
                disable_local_fallback=disable_local_fallback,
            )
            status = "fallback"

        duration_ms = int((time.monotonic() - t_start) * 1000)
        self._log_call(task_type, room_id, provider_used, status, duration_ms,
                       fallback_chain, last_error, final_result, context=context)
        return final_result

    async def _fallback_for_task(
        self,
        task_type: str,
        context: dict,
        chain: list[str],
        error: str,
        disable_local_fallback: bool = False,
    ) -> Any:
        if disable_local_fallback:
            return None
        lb = self._providers.get("local", LocalFallbackProvider())
        raw = await lb.call(task_type, context)
        if raw is None:
            raw = {}
        schema = TASK_SCHEMAS.get(task_type)
        if schema and raw:
            try:
                return schema(**raw)
            except Exception:
                pass
        return raw

    def _normalize_narrative_result(self, result: Any) -> NarrativePayload:
        if isinstance(result, NarrativePayload):
            return result
        if isinstance(result, KpResponse):
            return result.narrative
        if isinstance(result, dict):
            narrative = result.get("narrative")
            if isinstance(narrative, NarrativePayload):
                return narrative
            if isinstance(narrative, dict):
                return NarrativePayload(**narrative)
            return NarrativePayload(**result)
        if isinstance(result, str):
            return NarrativePayload(public=result)
        return NarrativePayload()

    def _prepare_narrative_context(self, context: dict) -> dict:
        prepared = dict(context)
        if prepared.get("user_message"):
            return prepared

        scenario_title = prepared.get("scenario_title", "")
        investigator_name = prepared.get("investigator_name", "")
        occupation = prepared.get("occupation", "")
        background = prepared.get("background", "")
        player_words = prepared.get("player_words", "")
        declared_intent = prepared.get("declared_intent", "")
        intent_type = prepared.get("intent_type", "")
        previous_narrative = prepared.get("previous_narrative", "")
        spoiler_constraint = prepared.get("spoiler_constraint", "")
        room_id = prepared.get("room_id", "")
        character_id = prepared.get("character_id", "")

        lines = []
        if scenario_title:
            lines.append(f"剧本：{scenario_title}")
        if investigator_name or occupation:
            role_line = f"调查员：{investigator_name or '未知调查员'}"
            if occupation:
                role_line += f"（{occupation}）"
            lines.append(role_line)
        if background:
            lines.append(f"背景：{background[:300]}")
        if room_id:
            lines.append(f"房间：{room_id}")
        if character_id:
            lines.append(f"角色：{character_id}")
        if intent_type:
            lines.append(f"行动类型：{intent_type}")
        if player_words:
            lines.append(f"玩家发言：{player_words}")
        if declared_intent and declared_intent != player_words:
            lines.append(f"声明意图：{declared_intent}")
        if previous_narrative:
            lines.append(f"上一版叙事：{previous_narrative[:500]}")
        if spoiler_constraint:
            lines.append(f"额外约束：{spoiler_constraint[:500]}")
        lines.append("请直接返回当前场景下的沉浸式公开叙事，不要泄露守秘信息。")
        prepared["user_message"] = "\n".join(lines)
        return prepared

    def _log_call(self, task_type: str, room_id: str | None, provider: str,
                  status: str, duration_ms: int, fallback_chain: list[str],
                  error_message: str, response: Any, context: dict | None = None):
        if not self.db:
            return
        if (context or {}).get("suppress_response_log"):
            return
        try:
            ctx = context or {}
            summary = ""
            if isinstance(response, KpResponse) and response.narrative:
                summary = (response.narrative.public or response.keeper_notes or "")[:256]
            elif isinstance(response, KnowledgeAnswer):
                summary = response.answer[:256]
            elif isinstance(response, dict):
                summary = json.dumps(response, ensure_ascii=False)[:256]
            self.db.execute(
                "INSERT INTO ai_call_logs "
                "(room_id, task_type, provider, provider_order, duration_ms, status, "
                "fallback_chain, response_summary, error_message, "
                "spoiler_review_status, spoiler_hit_items, retry_count) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (room_id, task_type, provider, ",".join(self._provider_order),
                 duration_ms, status, fallback_chain, summary[:256], error_message[:256],
                 ctx.get("spoiler_review_status", ""),
                 json.dumps(ctx.get("spoiler_hit_items", []), ensure_ascii=False),
                 ctx.get("retry_count", 0)),
            )
            self.db.commit()
        except Exception as e:
            logger.debug("Failed to log AI call: %s", e)


def _normalize_required_capabilities(required_capabilities: str | set[str] | None) -> set[str]:
    if required_capabilities is None:
        return set()
    if isinstance(required_capabilities, str):
        return {required_capabilities}
    return {capability for capability in required_capabilities if capability}


def _analysis_source_for_provider(provider_name: str) -> str:
    if provider_name.startswith("configured:"):
        return "configured_provider"
    if provider_name == "local":
        return "local_fallback"
    return "fallback_provider"


def _normalize_director_provider_result(
    raw: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    local_analysis = context.get("local_analysis")
    if not isinstance(local_analysis, dict):
        local_analysis = {}
    result = dict(raw)
    if result.get("intent_type") == "observation":
        result["intent_type"] = "dialogue"
    local_intent_type = str(local_analysis.get("intent_type") or "dialogue")
    if local_intent_type not in DIRECTOR_SUPPORTED_INTENT_TYPES:
        local_intent_type = "dialogue"
    if result.get("intent_type") not in DIRECTOR_SUPPORTED_INTENT_TYPES:
        result["intent_type"] = local_intent_type
    if not isinstance(result.get("state_patch"), list):
        result["state_patch"] = []
    result.setdefault("action_id", str(local_analysis.get("draft_id") or "director-plan"))
    result.setdefault("context_version", int(context.get("context_version") or 0))
    result.setdefault("actor_display_name", str(context.get("actor_display_name") or ""))
    result.setdefault("declared_intent", str(context.get("declared_intent") or ""))
    result.setdefault("preconditions", [])
    result.setdefault("permissions", [])
    result.setdefault("mechanic_plan", {"mechanic": "dialogue"})
    result.setdefault("state_patch", [])
    result.setdefault("event_plan", [])
    result.setdefault("semantic_progression", {})
    result.setdefault("npc_reactions", [])
    result.setdefault("time_impact", {})
    result.setdefault("visibility", str(local_analysis.get("visibility") or "public"))
    result.setdefault("basis_refs", [])
    result.setdefault("citations", [])
    result.setdefault("clarification_options", [])
    result.setdefault("exception_reason", None)
    raw_citations = result["citations"] if isinstance(result["citations"], list) else []
    result["citations"] = [
        _normalize_director_citation(item)
        for item in raw_citations
        if isinstance(item, dict)
    ]
    result["basis_refs"] = _normalize_director_basis_refs(result["basis_refs"])
    result["semantic_progression"] = _normalize_semantic_progression(
        result["semantic_progression"]
    )
    if result.get("requires_host_exception") and not str(
        result.get("exception_reason") or ""
    ).strip():
        result["requires_host_exception"] = False
    return {
        key: value
        for key, value in result.items()
        if key in DirectorPlanDTO.model_fields
    }


def _normalize_director_citation(value: dict[str, Any]) -> dict[str, Any]:
    page_number = value.get("page_number", value.get("page"))
    try:
        page_number = int(page_number) if page_number is not None else None
    except (TypeError, ValueError):
        page_number = None
    return {
        "source": str(value["source"]) if value.get("source") else None,
        "source_part_id": (
            str(value["source_part_id"]) if value.get("source_part_id") else None
        ),
        "content_item_id": (
            str(value["content_item_id"]) if value.get("content_item_id") else None
        ),
        "page_number": page_number,
        "location": str(value["location"]) if value.get("location") else None,
    }


def _normalize_director_basis_refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized = []
    for item in value:
        if not isinstance(item, dict) or not item.get("source"):
            continue
        citation = item.get("citation")
        normalized.append({
            "source": str(item["source"]),
            "citation": _normalize_director_citation(citation)
            if isinstance(citation, dict)
            else None,
        })
    return normalized


def _normalize_semantic_progression(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    citation = value.get("citation")
    return {
        "targetNodeId": value.get("targetNodeId", value.get("target_node_id")),
        "fromNodeId": value.get("fromNodeId", value.get("from_node_id")),
        "citation": _normalize_director_citation(citation)
        if isinstance(citation, dict)
        else None,
        "rationale": value.get("rationale"),
    }


def _normalize_narrator_provider_result(
    raw: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    result = {
        key: value
        for key, value in raw.items()
        if key in NarrationResultDTO.model_fields and key != "action_id"
    }
    result["context_version"] = int(context.get("context_version") or 0)
    result["director_plan_digest"] = str(context.get("director_plan_digest") or "")
    if result.get("status") == "success":
        result["status"] = "completed"

    allowed_refs = _allowed_narration_fact_refs(context)
    fact_refs = result.get("fact_refs")
    if isinstance(fact_refs, list):
        candidate_refs = _non_empty_string_list(fact_refs)
        if candidate_refs and all(ref in allowed_refs for ref in candidate_refs):
            result["fact_refs"] = {
                field: candidate_refs
                for field in _NARRATION_FACT_REF_FIELDS
            }

    context_interactables = _non_empty_string_list(
        context.get("interactable_objects")
    )
    verified_interactable_refs = _fact_refs_for_texts(
        context,
        context_interactables,
    )
    fallback_target = context_interactables[0] if verified_interactable_refs else ""
    fallback_refs = verified_interactable_refs
    if not fallback_target:
        scene_ref = _scene_fact_ref(context)
        if scene_ref:
            fallback_target = "当前环境"
            fallback_refs = [scene_ref]
    fact_refs = _narrator_fact_refs_dict(result.get("fact_refs"))
    visible_changes = _non_empty_string_list(context.get("visible_state_changes"))
    visible_change_ref = (
        _fact_ref_for_visible_change(context, visible_changes[0])
        if visible_changes
        else ""
    )

    if not _has_valid_narration_fact_refs(
        fact_refs.get("narrative_text"),
        allowed_refs,
    ):
        if visible_changes and visible_change_ref:
            result["narrative_text"] = visible_changes[0]
            fact_refs["narrative_text"] = [visible_change_ref]
        elif fallback_refs:
            result["narrative_text"] = "你继续置身于当前可见场景。"
            fact_refs["narrative_text"] = [fallback_refs[0]]

    if (
        not _non_empty_string_list(result.get("environment_changes"))
        or not _has_valid_narration_fact_refs(
            fact_refs.get("environment_changes"),
            allowed_refs,
        )
    ) and visible_changes and visible_change_ref:
        result["environment_changes"] = visible_changes
        fact_refs["environment_changes"] = [visible_change_ref]

    if (
        not _non_empty_string_list(result.get("interactable_objects"))
        or not _has_valid_narration_fact_refs(
            fact_refs.get("interactable_objects"),
            allowed_refs,
        )
    ) and fallback_target and fallback_refs:
        result["interactable_objects"] = (
            context_interactables if verified_interactable_refs else [fallback_target]
        )
        fact_refs["interactable_objects"] = fallback_refs

    if (
        not str(result.get("open_question") or "").strip()
        or not _has_valid_narration_fact_refs(
            fact_refs.get("open_question"),
            allowed_refs,
        )
    ) and fallback_target and fallback_refs:
        result["open_question"] = f"你想如何继续观察{fallback_target}？"
        fact_refs["open_question"] = [fallback_refs[0]]

    result["fact_refs"] = {
        field: _non_empty_string_list(fact_refs.get(field))
        for field in _NARRATION_FACT_REF_FIELDS
    }
    return result


_NARRATION_FACT_REF_FIELDS = (
    "narrative_text",
    "environment_changes",
    "interactable_objects",
    "open_question",
)


def _narrator_fact_refs_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _allowed_narration_fact_refs(context: dict[str, Any]) -> set[str]:
    return {
        str(fact.get("fact_ref") or "").strip()
        for fact in context.get("allowed_facts") or []
        if isinstance(fact, dict) and str(fact.get("fact_ref") or "").strip()
    }


def _has_valid_narration_fact_refs(value: Any, allowed_refs: set[str]) -> bool:
    refs = _non_empty_string_list(value)
    return bool(refs) and all(ref in allowed_refs for ref in refs)


def _fact_refs_for_texts(context: dict[str, Any], texts: list[str]) -> list[str]:
    required = set(texts)
    if not required:
        return []
    refs_by_text = {
        str(fact.get("text") or "").strip(): str(fact.get("fact_ref") or "").strip()
        for fact in context.get("allowed_facts") or []
        if isinstance(fact, dict)
    }
    if any(not refs_by_text.get(text) for text in required):
        return []
    return [refs_by_text[text] for text in texts]


def _scene_fact_ref(context: dict[str, Any]) -> str:
    for fact in context.get("allowed_facts") or []:
        if not isinstance(fact, dict):
            continue
        fact_ref = str(fact.get("fact_ref") or "").strip()
        if fact_ref == "fact:scene-brief" or fact_ref.startswith("fact:scene"):
            return fact_ref
    return ""


def _non_empty_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _fact_ref_for_visible_change(context: dict[str, Any], change: str) -> str:
    for fact in context.get("allowed_facts") or []:
        if not isinstance(fact, dict):
            continue
        if str(fact.get("text") or "").strip() != change:
            continue
        fact_ref = str(fact.get("fact_ref") or "").strip()
        if fact_ref:
            return fact_ref
    return ""


_NARRATOR_PROVIDER_DENIED_KEYS = {
    "action_id",
    "actionId",
    "local_action_id",
    "localActionId",
    "room_id",
    "roomId",
    "character_id",
    "characterId",
    "truth",
    "ending",
    "endings",
    "raw_text",
    "rawText",
    "original_text",
    "originalText",
    "source_text",
    "full_text",
    "state_patch",
    "mutations",
}


def _scrub_narrator_provider_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _scrub_narrator_provider_payload(item)
            for key, item in value.items()
            if key not in _NARRATOR_PROVIDER_DENIED_KEYS
        }
    if isinstance(value, list):
        return [_scrub_narrator_provider_payload(item) for item in value]
    return value


def _is_worldbook_result(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("scenes"), list)
        and any(isinstance(scene, dict) for scene in value["scenes"])
    )
