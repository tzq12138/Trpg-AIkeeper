"""
KP MCP Client — async wrapper for the MCP StreamableHTTP protocol.

Usage:
    client = KpMcpClient("http://127.0.0.1:9100/mcp")
    plan = await client.analyze_director_action({"declared_intent": "我查看门缝"})
    narration = await client.narrate_action({"allowed_facts": ["门后有脚步声"]})
    health = await client.health_check()

Session is reused across calls.  Call close() when done.
"""

import json
import logging
from typing import Any

from mcp.client.streamable_http import streamable_http_client, SessionMessage
from mcp.types import JSONRPCMessage, JSONRPCRequest

logger = logging.getLogger(__name__)


class KpMcpClient:
    def __init__(self, url: str = "http://127.0.0.1:9100/mcp", timeout: float = 60):
        self.url = url
        self.timeout = timeout
        self._read_stream = None
        self._write_stream = None
        self._get_session_id = None
        self._exit_stack = None
        self._next_id = 1

    async def _ensure_connected(self):
        if self._write_stream is not None:
            return
        import contextlib
        self._exit_stack = contextlib.AsyncExitStack()
        cm = streamable_http_client(self.url)
        streams = await self._exit_stack.enter_async_context(cm)
        self._read_stream, self._write_stream, self._get_session_id = streams

        # MCP handshake
        await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "ai-keeper-backend", "version": "1.0"},
        })
        resp = await self._read_response()
        server_name = resp.get("result", {}).get("serverInfo", {}).get("name", "?")
        logger.info("Connected to KP MCP server: %s", server_name)

    async def _send_request(self, method: str, params: dict | None = None):
        req_id = self._next_id
        self._next_id += 1
        msg = SessionMessage(JSONRPCMessage(JSONRPCRequest(
            jsonrpc="2.0", id=req_id, method=method, params=params or {},
        )))
        await self._write_stream.send(msg)
        return req_id

    async def _read_response(self) -> dict:
        resp = await self._read_stream.receive()
        if isinstance(resp, SessionMessage):
            root = resp.message.root
            if hasattr(root, "result"):
                return root.result
            if hasattr(root, "error"):
                raise RuntimeError(f"MCP error: {root.error}")
        elif isinstance(resp, Exception):
            raise resp
        return {}

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        await self._ensure_connected()
        await self._send_request("tools/call", {
            "name": tool_name, "arguments": arguments,
        })
        result = await self._read_response()
        content = result.get("content", [{}])[0].get("text", "{}")
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"_raw": content}

    async def health_check(self) -> dict:
        return await self.call_tool("kp_health_check", {})

    async def structure_scenario(self, raw_text: str, format: str = "full") -> dict:
        return await self.call_tool("kp_structure_scenario", {
            "rawText": raw_text, "format": format,
        })

    async def analyze_director_action(self, context: dict) -> dict:
        return await self.call_tool("kp_analyze_director_action", {"context": context})

    async def narrate_action(self, context: dict) -> dict:
        return await self.call_tool("kp_narrate_action", {"context": context})

    async def close(self):
        exit_stack = self._exit_stack
        self._read_stream = None
        self._write_stream = None
        self._exit_stack = None
        if exit_stack is not None:
            await exit_stack.aclose()
