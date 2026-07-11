"""AiGateway — unified AI call entry point with per-task validation and provider chain."""

import json
import logging
import time
from typing import Any

from ..config import Settings
from .contracts import KpResponse, KnowledgeAnswer, NarrativePayload
from .providers import (
    BaseAiProvider,
    ConfiguredOpenAIProvider,
    DeepSeekProvider,
    KpMcpProvider,
    LocalFallbackProvider,
)
from ..scenario.content_package import ContentPackage

logger = logging.getLogger(__name__)

# Per-task expected return shapes for validation (fallback to raw dict if no schema)
TASK_SCHEMAS: dict[str, Any] = {
    "resolve_turn": KpResponse,
    "generate_narrative": None,
    "structure_scenario": None,        # validated by caller
    "compile_mechanic": None,           # validated by caller
    "generate_map": None,               # validated by caller
    "query_knowledge": KnowledgeAnswer,
    "resolve_sanity": KpResponse,
    "resolve_combat_round": KpResponse,
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

    async def structure_scenario(self, raw_text: str) -> dict:
        # Truncate to avoid 400 from DeepSeek (matches MCP-side 12000-char limit).
        # 59-page PDFs can easily exceed model context windows.
        truncated = raw_text[:12000]
        context = {"rawText": truncated, "format": "full",
                   "system_prompt": "你是TRPG剧本分析器。提取 scenes, npcs, clues, truth, endings。",
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
                "system_prompt": "你是TRPG剧本分析器。提取 scenes, npcs, clues, truth, endings。",
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


def _is_worldbook_result(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("scenes"), list)
