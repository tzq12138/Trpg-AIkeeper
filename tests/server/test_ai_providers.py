import json

import pytest

from src.server.ai.providers import (
    BaseAiProvider,
    DeepSeekProvider,
    KpMcpProvider,
    LocalFallbackProvider,
    _task_to_tool,
)


def test_task_to_tool_maps_generate_narrative():
    assert _task_to_tool("generate_narrative") == "kp_generate_narrative"


class DummyProvider(BaseAiProvider):
    async def call(self, task_type: str, context: dict):
        return None


def test_provider_capabilities_and_supports():
    assert DeepSeekProvider().capabilities == {"text"}
    assert LocalFallbackProvider().capabilities == {"text"}
    assert KpMcpProvider().capabilities == {"text", "image"}

    provider = DummyProvider("dummy")
    assert provider.capabilities == {"text"}
    assert provider.supports("text") is True
    assert provider.supports({"text"}) is True
    assert provider.supports("image") is False
    assert provider.supports({"text", "image"}) is False


@pytest.mark.asyncio
async def test_local_fallback_turn_narrative_uses_action_instead_of_generic_no_discovery():
    result = await LocalFallbackProvider().call(
        "resolve_turn",
        {
            "character": {"name": "菲利普"},
            "actions": [{"declared_intent": "仔细阅读桌上的旧报纸"}],
        },
    )

    narrative = result["narrative"]["public"]
    assert "旧报纸" in narrative
    assert "注意力" in narrative
    assert "暂时没有新的发现" not in narrative


@pytest.mark.asyncio
async def test_mcp_provider_wraps_generate_narrative_context(monkeypatch):
    recorded_requests: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = json.dumps({
            "result": {
                "content": [
                    {"text": json.dumps({"narrative": {"public": "ok"}}, ensure_ascii=False)}
                ]
            }
        }, ensure_ascii=False)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, _url, json=None):
            recorded_requests.append(json)
            return FakeResponse()

    async def fake_initialized(self):
        return True

    monkeypatch.setattr("src.server.ai.providers.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr(KpMcpProvider, "_ensure_initialized", fake_initialized)

    provider = KpMcpProvider()
    result = await provider.call("generate_narrative", {"declared_intent": "我敲了敲门"})

    assert result == {"narrative": {"public": "ok"}}
    assert recorded_requests[0]["params"]["arguments"] == {
        "context": {"declared_intent": "我敲了敲门"}
    }


@pytest.mark.asyncio
async def test_mcp_provider_forwards_structure_scenario_content_package(monkeypatch):
    recorded_requests: list[dict] = []
    content_package = {
        "source_filename": "scenario.pdf",
        "source_sha256": "abc123",
        "mime_type": "application/pdf",
        "parts": [{"ordinal": 1, "kind": "image", "data_url": "data:image/png;base64,AA=="}],
        "canonical_text": "",
        "requires_multimodal": True,
    }

    class FakeResponse:
        status_code = 200
        text = json.dumps({"result": {"content": [{"text": json.dumps({"ok": True})}]}}, ensure_ascii=False)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, _url, json=None):
            recorded_requests.append(json)
            return FakeResponse()

    async def fake_initialized(self):
        return True

    monkeypatch.setattr("src.server.ai.providers.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr(KpMcpProvider, "_ensure_initialized", fake_initialized)

    provider = KpMcpProvider()
    result = await provider.call("structure_scenario", {"contentPackage": content_package})

    assert result == {"ok": True}
    assert recorded_requests[0]["params"]["arguments"] == {"contentPackage": content_package}


@pytest.mark.asyncio
async def test_mcp_provider_rejects_tool_error_content(monkeypatch):
    class FakeResponse:
        status_code = 200
        text = json.dumps({
            "result": {
                "isError": True,
                "content": [{"text": json.dumps({
                    "narrative": {"public": "HTTP 400 from multimodal provider"}
                })}],
            }
        })

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, _url, json=None):
            return FakeResponse()

    async def fake_initialized(self):
        return True

    monkeypatch.setattr("src.server.ai.providers.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr(KpMcpProvider, "_ensure_initialized", fake_initialized)

    provider = KpMcpProvider()
    result = await provider.call(
        "structure_scenario",
        {"contentPackage": {"parts": [{"kind": "image"}]}},
    )

    assert result is None


@pytest.mark.asyncio
async def test_mcp_provider_keeps_legacy_structure_scenario_raw_text(monkeypatch):
    recorded_requests: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = json.dumps({"result": {"content": [{"text": json.dumps({"ok": True})}]}}, ensure_ascii=False)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, _url, json=None):
            recorded_requests.append(json)
            return FakeResponse()

    async def fake_initialized(self):
        return True

    monkeypatch.setattr("src.server.ai.providers.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr(KpMcpProvider, "_ensure_initialized", fake_initialized)

    provider = KpMcpProvider()
    result = await provider.call("structure_scenario", {"rawText": "旧文本", "format": "full"})

    assert result == {"ok": True}
    assert recorded_requests[0]["params"]["arguments"] == {"rawText": "旧文本", "format": "full"}


@pytest.mark.asyncio
async def test_mcp_provider_recovers_after_server_restarts(monkeypatch):
    requests: list[dict] = []

    class FakeResponse:
        def __init__(self, status_code: int, headers: dict | None = None):
            self.status_code = status_code
            self.headers = headers or {}

    class FakeClient:
        def __init__(self, *args, headers=None, **kwargs):
            self.headers = headers or {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, _url, json=None):
            requests.append({"headers": self.headers, "payload": json})
            if json["method"] == "initialize":
                return FakeResponse(200, {"mcp-session-id": "fresh-session"})
            if self.headers.get("Mcp-Session-Id") == "stale-session":
                return FakeResponse(404)
            return FakeResponse(200)

    monkeypatch.setattr("src.server.ai.providers.httpx.AsyncClient", FakeClient)

    provider = KpMcpProvider()
    provider._initialized = True
    provider._session_id = "stale-session"

    assert await provider.health_check() is True
    assert [request["payload"]["method"] for request in requests] == [
        "tools/call", "initialize", "tools/call",
    ]


@pytest.mark.asyncio
async def test_mcp_provider_retries_tool_call_after_session_expiry(monkeypatch):
    requests: list[dict] = []

    class FakeResponse:
        def __init__(self, status_code: int, text: str = "", headers: dict | None = None):
            self.status_code = status_code
            self.text = text
            self.headers = headers or {}

    class FakeClient:
        def __init__(self, *args, headers=None, **kwargs):
            self.headers = headers or {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, _url, json=None):
            requests.append({"headers": self.headers, "payload": json})
            if json["method"] == "initialize":
                return FakeResponse(200, headers={"mcp-session-id": "fresh-session"})
            if self.headers.get("Mcp-Session-Id") == "stale-session":
                return FakeResponse(404)
            return FakeResponse(200, json_module.dumps({
                "result": {"content": [{"text": json_module.dumps({"outcome": "ok"})}]}
            }))

    import json as json_module

    monkeypatch.setattr("src.server.ai.providers.httpx.AsyncClient", FakeClient)

    provider = KpMcpProvider()
    provider._initialized = True
    provider._session_id = "stale-session"

    assert await provider.call("resolve_turn", {"action": {}}) == {"outcome": "ok"}
    assert [request["payload"]["method"] for request in requests] == [
        "tools/call", "initialize", "tools/call",
    ]
