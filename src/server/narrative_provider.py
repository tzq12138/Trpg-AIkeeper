"""NarrativeProvider — generates scene-round narrative from resolution results.

v1: DeepSeekNarrativeProvider (primary) + TemplateNarrativeProvider (fallback).
McpStdioNarrativeProvider reserved as interface boundary (not implemented yet).
"""
import json
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class NarrativeProvider(ABC):
    @abstractmethod
    async def generate(self, context: dict) -> str:
        """Generate narrative text from turn resolution context."""
        ...


class TemplateNarrativeProvider(NarrativeProvider):
    """Rule-based fallback — generates readable Chinese narrative without AI."""

    async def generate(self, context: dict) -> str:
        turn_index = context.get("turn_index", 1)
        actions = context.get("actions", [])
        parts = [f"--- 第 {turn_index} 轮 ---"]

        for act in actions:
            char_name = act.get("character_name", "调查员")
            intent = act.get("declared_intent", "进行了一次行动")
            result = act.get("result", {})
            success = result.get("is_success")
            mechanic = result.get("mechanic", "")
            narrative = result.get("narrative", "")

            if mechanic == "skill_check":
                skill = result.get("skill_name", "")
                roll = result.get("roll", "?")
                status = result.get("success_level", "failure")
                level_labels = {"critical": "大成功", "extreme": "极难成功", "hard": "困难成功",
                                "regular": "成功", "failure": "失败", "fumble": "大失败"}
                label = level_labels.get(status, status)
                parts.append(f"{char_name} 进行「{skill}」检定：掷出 {roll}，{label}。")

            if narrative:
                parts.append(narrative)
            elif not result.get("mechanic"):
                parts.append(f"{char_name} {intent}。")

        parts.append("（本轮结束）")
        return "\n".join(parts)


class DeepSeekNarrativeProvider(NarrativeProvider):
    """DeepSeek API-powered narrative generation."""

    def __init__(self, api_key: str = "", model: str = "deepseek-v4-pro"):
        self.api_key = api_key
        self.model = model

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def generate(self, context: dict) -> str:
        if not self.available:
            raise RuntimeError("DeepSeek API key not configured")

        turn_index = context.get("turn_index", 1)
        scenario_title = context.get("scenario_title", "")
        actions = context.get("actions", [])

        prompt = _build_prompt(turn_index, scenario_title, actions)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": "你是COC守秘人，根据调查员的行动结果生成200字以内的沉浸式叙事。用简体中文。"},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.8,
                        "max_tokens": 400,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception as e:
            logger.warning("DeepSeek narrative failed: %s", e)
            raise


def _build_prompt(turn_index: int, scenario_title: str, actions: list[dict]) -> str:
    lines = [f"剧本：{scenario_title or 'COC模组'}", f"第 {turn_index} 轮行动结果："]
    for act in actions:
        cname = act.get("character_name", "?")
        intent = act.get("declared_intent", "")
        result = act.get("result", {})
        lines.append(f"- {cname}：{intent}")
        if result.get("mechanic") == "skill_check":
            lines.append(f"  检定「{result.get('skill_name','')}」掷出{result.get('roll','?')}，{result.get('success_level','?')}")
        if result.get("narrative"):
            lines.append(f"  结果：{result['narrative']}")
    lines.append("请用200字以内的沉浸式COC叙事总结本轮所有人的行动和结果。")
    return "\n".join(lines)


class McpStdioNarrativeProvider(NarrativeProvider):
    """Reserved for future Hermes-agent MCP stdio integration."""
    async def generate(self, context: dict) -> str:
        raise NotImplementedError("MCP stdio provider not yet available")
