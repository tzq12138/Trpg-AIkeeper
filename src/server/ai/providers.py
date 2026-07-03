"""AI Providers — DeepSeek, Hermes MCP, and Local fallback implementations."""

import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

from .contracts import KpResponse, KnowledgeAnswer

logger = logging.getLogger(__name__)


class BaseAiProvider(ABC):
    """Abstract provider — all AI providers implement this."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def call(self, task_type: str, context: dict) -> dict | None:
        """Call the provider with a task. Returns KpResponse dict or None on failure."""
        ...

    async def health_check(self) -> bool:
        """Quick health check. Default: returns True."""
        return True


# ══════════════════════════════════════════════
#  DeepSeek Provider
# ══════════════════════════════════════════════

class DeepSeekProvider(BaseAiProvider):
    """Direct DeepSeek API calls — uses existing AIKP patterns."""

    def __init__(self, api_key: str = "", model: str = "deepseek-v4-pro",
                 api_base: str = "https://api.deepseek.com"):
        super().__init__("deepseek")
        self.api_key = api_key
        self.model = model
        self.api_base = api_base

    async def call(self, task_type: str, context: dict) -> dict | None:
        if not self.api_key:
            return None
        try:
            result = await self._call_api(context.get("system_prompt", ""),
                                          context.get("user_message", ""))
            return result
        except Exception as e:
            logger.warning("DeepSeek provider failed for %s: %s", task_type, e)
            return None

    async def _call_api(self, system_prompt: str, user_message: str) -> dict:
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
                        {"role": "user", "content": user_message},
                    ],
                    "temperature": 0.8,
                },
            )
            if resp.status_code >= 400:
                body_preview = (resp.text or "")[:500]
                logger.warning(
                    "DeepSeek API error: status=%s model=%s body=%s",
                    resp.status_code, self.model, body_preview,
                )
            resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"narrative": {"public": content}, "rollRequests": [],
                    "stateMutations": [], "tacticalPrompts": [], "keeperNotes": ""}

    async def health_check(self) -> bool:
        if not self.api_key:
            return False
        return True


# ══════════════════════════════════════════════
#  Hermes MCP Provider
# ══════════════════════════════════════════════

class KpMcpProvider(BaseAiProvider):
    """Minimal JSON-RPC 2.0 MCP client for Hermes KP MCP Server."""

    # MCP StreamableHTTP requires both application/json and text/event-stream in
    # Accept for ALL requests.  Using only application/json results in 406.
    _INIT_HEADERS = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    _JSON_HEADERS = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    def __init__(self, server_url: str = "http://127.0.0.1:9100/mcp", timeout: int = 30):
        super().__init__("mcp")
        self.server_url = server_url
        self.timeout = timeout
        self._initialized = False
        self._session_id: str | None = None
        self._req_headers: dict | None = None  # built after initialize

    def _parse_response(self, text: str) -> dict | None:
        """Parse MCP response, handling both SSE and plain JSON."""
        if not text or not text.strip():
            return None
        # Try plain JSON first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try SSE: "event: message\ndata: {...}"
        for line in text.split("\n"):
            if line.startswith("data: "):
                try:
                    return json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
        return None

    @property
    def _headers(self) -> dict:
        if self._req_headers is None:
            h = dict(self._JSON_HEADERS)
            if self._session_id:
                h["Mcp-Session-Id"] = self._session_id
            self._req_headers = h
        return self._req_headers

    async def _ensure_initialized(self) -> bool:
        if self._initialized:
            return True
        try:
            async with httpx.AsyncClient(timeout=10, headers=self._INIT_HEADERS) as client:
                resp = await client.post(
                    self.server_url,
                    json={
                        "jsonrpc": "2.0",
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "aikeeper", "version": "0.1.0"},
                        },
                        "id": 1,
                    },
                )
                if resp.status_code == 200:
                    self._initialized = True
                    sid = resp.headers.get("mcp-session-id")
                    if sid:
                        self._session_id = sid
                    self._req_headers = None  # rebuild on next access
                    return True
        except Exception as e:
            logger.debug("MCP initialize failed: %s", e)
        return False

    async def call(self, task_type: str, context: dict) -> dict | None:
        if not await self._ensure_initialized():
            return None

        tool_name = _task_to_tool(task_type)
        if not tool_name:
            return None

        arguments = context.get("arguments", context)
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
                resp = await client.post(
                    self.server_url,
                    json={
                        "jsonrpc": "2.0",
                        "method": "tools/call",
                        "params": {"name": tool_name, "arguments": arguments},
                        "id": 2,
                    },
                )
                if resp.status_code != 200:
                    logger.warning("MCP call returned %d for %s", resp.status_code, task_type)
                    return None
                data = self._parse_response(resp.text)
                if data is None:
                    logger.warning("MCP empty response for %s", task_type)
                    return None
                if "error" in data:
                    logger.warning("MCP error for %s: %s", task_type, data["error"])
                    return None
                result = data.get("result", {})
                content = result.get("content", [])
                if content and isinstance(content, list):
                    text = content[0].get("text", "{}") if content else "{}"
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return {"narrative": {"public": text}, "keeperNotes": ""}
                return result
        except httpx.TimeoutException:
            logger.warning("MCP timeout for %s after %ds", task_type, self.timeout)
            return None
        except Exception as e:
            logger.warning("MCP call failed for %s: %s", task_type, e)
            return None

    async def health_check(self) -> bool:
        if not self.server_url:
            return False
        if not await self._ensure_initialized():
            return False
        try:
            async with httpx.AsyncClient(timeout=5, headers=self._headers) as client:
                resp = await client.post(
                    self.server_url,
                    json={"jsonrpc": "2.0", "method": "tools/call",
                          "params": {"name": "kp_health_check", "arguments": {}}, "id": 0},
                )
                return resp.status_code == 200
        except Exception:
            return False


def _task_to_tool(task_type: str) -> str | None:
    mapping = {
        "resolve_turn": "kp_resolve_turn",
        "resolve_sanity": "kp_resolve_sanity",
        "resolve_combat_round": "kp_resolve_combat_round",
        "structure_scenario": "kp_structure_scenario",
        "query_rules": "kp_query_rules",
        "query_knowledge": "kp_query_knowledge",
        "health_check": "kp_health_check",
    }
    return mapping.get(task_type)


# ══════════════════════════════════════════════
#  Local Fallback Provider
# ══════════════════════════════════════════════

class LocalFallbackProvider(BaseAiProvider):
    """Template-based fallback — always succeeds with simple narrative."""

    def __init__(self):
        super().__init__("local")

    async def call(self, task_type: str, context: dict) -> dict | None:
        actions = context.get("actions", [])
        action_text = actions[0].get("declared_intent", "") if actions else "进行了一次行动"
        char_name = context.get("character", {}).get("name",
                     actions[0].get("character_id", "调查员") if actions else "调查员")

        if task_type == "resolve_turn":
            return {
                "narrative": {"public": f"{char_name}{action_text}。空气中弥漫着不安的气息，但暂时没有新的发现。"},
                "rollRequests": [],
                "stateMutations": [],
                "tacticalPrompts": [],
                "keeperNotes": "LOCAL_FALLBACK",
            }
        elif task_type == "structure_scenario":
            return {"scenes": [], "npcs": [], "clues": [], "truth": {}, "endings": []}
        elif task_type == "compile_mechanic":
            return context.get("fallback", {"triggeredMechanic": "dialogue"})
        elif task_type == "query_knowledge":
            return {"answer": "暂无可用资料。请确认 Hermes 服务已启动后重试。", "citations": [], "confidence": "low"}
        elif task_type == "health_check":
            return {"status": "ok", "provider": "local"}
        return {
            "narrative": {"public": "KP 暂时陷入沉默。(AI 服务不可用)"},
            "rollRequests": [], "stateMutations": [], "tacticalPrompts": [],
            "keeperNotes": "LOCAL_FALLBACK", "error": {"type": "all_providers_failed", "task": task_type},
        }

    async def health_check(self) -> bool:
        return True
