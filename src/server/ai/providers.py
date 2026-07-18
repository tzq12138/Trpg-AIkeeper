"""AI Providers — DeepSeek, Hermes MCP, and Local fallback implementations."""

import json
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

import httpx

from .contracts import KpResponse, KnowledgeAnswer
from .provider_config import assert_api_target_safe

logger = logging.getLogger(__name__)


class BaseAiProvider(ABC):
    """Abstract provider — all AI providers implement this."""

    def __init__(self, name: str, capabilities: set[str] | None = None):
        self.name = name
        self.capabilities = set(capabilities or {"text"})

    @abstractmethod
    async def call(self, task_type: str, context: dict) -> dict | None:
        """Call the provider with a task. Returns KpResponse dict or None on failure."""
        ...

    def supports(self, required: str | Iterable[str] | None = None) -> bool:
        required_set = _normalize_capabilities(required)
        return required_set.issubset(self.capabilities)

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
        super().__init__("deepseek", {"text"})
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
        super().__init__("mcp", {"text", "image"})
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

    async def _reconnect(self) -> bool:
        self._initialized = False
        self._session_id = None
        self._req_headers = None
        return await self._ensure_initialized()

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

        if task_type == "structure_scenario" and "contentPackage" in context:
            arguments = {"contentPackage": context["contentPackage"]}
        elif task_type in {"analyze_director_action", "narrate_action"}:
            arguments = {"context": context.get("arguments", context)}
        else:
            arguments = context.get("arguments", context)
        try:
            for attempt in range(2):
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
                if resp.status_code == 404 and attempt == 0 and await self._reconnect():
                    continue
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
                if result.get("isError") is True:
                    logger.warning("MCP tool error for %s: %s", task_type, result)
                    return None
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
            for attempt in range(2):
                async with httpx.AsyncClient(timeout=5, headers=self._headers) as client:
                    resp = await client.post(
                        self.server_url,
                        json={"jsonrpc": "2.0", "method": "tools/call",
                              "params": {"name": "kp_health_check", "arguments": {}}, "id": 0},
                    )
                if resp.status_code == 404 and attempt == 0 and await self._reconnect():
                    continue
                return resp.status_code == 200
        except Exception:
            return False


def _task_to_tool(task_type: str) -> str | None:
    mapping = {
        "structure_scenario": "kp_structure_scenario",
        "analyze_director_action": "kp_analyze_director_action",
        "narrate_action": "kp_narrate_action",
        "health_check": "kp_health_check",
    }
    return mapping.get(task_type)


# ══════════════════════════════════════════════
#  Local Fallback Provider
# ══════════════════════════════════════════════

class LocalFallbackProvider(BaseAiProvider):
    """Template-based fallback — always succeeds with simple narrative."""

    def __init__(self):
        super().__init__("local", {"text"})

    async def call(self, task_type: str, context: dict) -> dict | None:
        actions = context.get("actions", [])
        action_text = actions[0].get("declared_intent", "") if actions else "进行了一次行动"
        char_name = context.get("character", {}).get("name",
                     actions[0].get("character_id", "调查员") if actions else "调查员")

        if task_type == "resolve_turn":
            from ..engine.fallback_narrative import render_action_aware_fallback

            return {
                "narrative": {
                    "public": render_action_aware_fallback(
                        action_text,
                        character_name=char_name,
                    )
                },
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


class ConfiguredOpenAIProvider(BaseAiProvider):
    """Administrator-configured OpenAI-compatible text and image provider."""

    def __init__(self, config: dict, timeout: int = 30):
        capabilities = {"text"}
        if config.get("supports_image"):
            capabilities.add("image")
        provider_id = str(config.get("provider_config_id") or "")
        super().__init__(f"configured:{provider_id[:8]}", capabilities)
        self.provider_config_id = provider_id
        self.api_base_url = str(config.get("api_base_url") or "").rstrip("/")
        self.protocol = str(config.get("protocol") or "responses")
        self.model = str(config.get("model") or "gpt-5.4")
        self.api_key = str(config.get("api_key") or "")
        self.timeout = timeout

    async def call(self, task_type: str, context: dict) -> dict | None:
        if not self.api_key:
            return None
        try:
            assert_api_target_safe(self.api_base_url)
            system_prompt = str(context.get("system_prompt") or "")
            user_content = _configured_user_content(context, self.protocol)
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            endpoint, payload = self._request_payload(system_prompt, user_content)
            async with httpx.AsyncClient(
                timeout=self._request_timeout(task_type, context),
                follow_redirects=False,
            ) as client:
                response = await client.post(endpoint, headers=headers, json=payload)
            if response.status_code >= 400:
                logger.warning(
                    "Configured provider returned status=%s task=%s provider=%s",
                    response.status_code,
                    task_type,
                    self.provider_config_id,
                )
            response.raise_for_status()
            parsed = _parse_configured_response(response.json(), self.protocol)
            return _unwrap_runtime_json_envelope(task_type, parsed) or None
        except Exception as exc:
            logger.warning(
                "Configured provider failed task=%s provider=%s error=%s",
                task_type,
                self.provider_config_id,
                type(exc).__name__,
            )
            return None

    def _request_timeout(self, task_type: str, context: dict) -> int:
        if task_type != "structure_scenario":
            return self.timeout
        try:
            requested = int(context.get("timeout_seconds", self.timeout))
        except (TypeError, ValueError):
            return self.timeout
        return max(self.timeout, min(requested, 900))

    async def test_connection(self) -> dict:
        started = time.monotonic()
        text_result = await self._probe(
            [{"type": "input_text", "text": '返回 JSON：{"ok": true}'}],
            probe_kind="text",
        )
        image_result = {"required": bool("image" in self.capabilities), "ok": True}
        if text_result["ok"] and image_result["required"]:
            image_result = await self._probe(
                [
                    {"type": "input_text", "text": '识别这张测试图片并返回 JSON：{"ok": true}'},
                    {
                        "type": "input_image",
                        "image_url": (
                            "data:image/png;base64,"
                            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
                            "AAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                        ),
                    },
                ],
                probe_kind="image",
            )
            image_result["required"] = True
        total_latency = int((time.monotonic() - started) * 1000)
        return {
            "ok": bool(text_result["ok"] and image_result["ok"]),
            "protocol": self.protocol,
            "model": self.model,
            "latency_ms": total_latency,
            "text": text_result,
            "image": image_result,
        }

    async def _probe(self, user_content: list[dict], probe_kind: str) -> dict:
        started = time.monotonic()
        try:
            assert_api_target_safe(self.api_base_url)
            endpoint, payload = self._request_payload(
                "你是 API 连接测试器，只返回要求的 JSON。",
                user_content,
            )
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            if response.status_code >= 400:
                return {
                    "ok": False,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "error_code": _provider_test_error_code(
                        response.status_code,
                        probe_kind,
                    ),
                }
            parsed = _parse_configured_response(response.json(), self.protocol)
            if not parsed:
                raise ValueError("empty provider response")
            return {
                "ok": True,
                "latency_ms": int((time.monotonic() - started) * 1000),
            }
        except httpx.TimeoutException:
            error_code = "timeout"
        except Exception:
            error_code = "invalid_response"
        return {
            "ok": False,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error_code": error_code,
        }

    def _request_payload(self, system_prompt: str, user_content: list[dict]) -> tuple[str, dict]:
        if self.protocol == "responses":
            return (
                f"{self.api_base_url}/responses",
                {
                    "model": self.model,
                    "input": [
                        {
                            "role": "system",
                            "content": [{"type": "input_text", "text": system_prompt}],
                        },
                        {"role": "user", "content": user_content},
                    ],
                    "text": {"format": {"type": "json_object"}},
                },
            )
        chat_content = []
        for item in user_content:
            if item["type"] == "input_image":
                chat_content.append({
                    "type": "image_url",
                    "image_url": {"url": item["image_url"]},
                })
            else:
                chat_content.append({"type": "text", "text": item.get("text", "")})
        return (
            f"{self.api_base_url}/chat/completions",
            {
                "model": self.model,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": chat_content},
                ],
            },
        )


def _normalize_capabilities(required: str | Iterable[str] | None) -> set[str]:
    if required is None:
        return set()
    if isinstance(required, str):
        return {required}
    return {item for item in required if item}


def _configured_user_content(context: dict, protocol: str) -> list[dict]:
    package = context.get("contentPackage")
    content: list[dict] = []
    if isinstance(package, dict):
        canonical_text = str(package.get("canonical_text") or "").strip()
        if canonical_text:
            content.append({"type": "input_text", "text": canonical_text})
        for part in package.get("parts") or []:
            if not isinstance(part, dict):
                continue
            source_ref = str(part.get("source_ref") or f"part:{part.get('ordinal', '')}")
            text = str(part.get("text") or "").strip()
            if text:
                content.append({"type": "input_text", "text": f"[{source_ref}]\n{text}"})
            data_url = str(part.get("data_url") or "")
            if data_url:
                content.append({"type": "input_text", "text": f"图像来源：{source_ref}"})
                content.append({"type": "input_image", "image_url": data_url})
    else:
        message = context.get("user_message")
        if not message:
            message = json.dumps(context, ensure_ascii=False, default=str)
        content.append({"type": "input_text", "text": str(message)})
    if not content:
        content.append({"type": "input_text", "text": "请返回 JSON 结果。"})
    return content


def _parse_configured_response(data: dict, protocol: str) -> dict:
    if protocol == "responses":
        text = str(data.get("output_text") or "")
        if not text:
            for output in data.get("output") or []:
                for item in output.get("content") or []:
                    if item.get("type") in {"output_text", "text"} and item.get("text"):
                        text = str(item["text"])
                        break
                if text:
                    break
    else:
        text = str(
            (data.get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
        )
    if not text.strip():
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    except json.JSONDecodeError:
        return {"narrative": {"public": text}, "keeperNotes": ""}


def _unwrap_runtime_json_envelope(task_type: str, value: dict) -> dict:
    if task_type not in {"analyze_director_action", "narrate_action"}:
        return value
    narrative = value.get("narrative") if isinstance(value, dict) else None
    public = narrative.get("public") if isinstance(narrative, dict) else None
    if not isinstance(public, str):
        return value
    try:
        unwrapped = json.loads(public)
    except json.JSONDecodeError:
        return value
    return unwrapped if isinstance(unwrapped, dict) else value


def _provider_test_error_code(status_code: int, probe_kind: str) -> str:
    if status_code in {401, 403}:
        return "auth_failed"
    if status_code == 404:
        return "model_not_found"
    if status_code == 429:
        return "rate_limited"
    if status_code == 400:
        return "image_unsupported" if probe_kind == "image" else "text_unsupported"
    return "invalid_response"
