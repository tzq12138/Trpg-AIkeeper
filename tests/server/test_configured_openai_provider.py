import json

import pytest

from src.server.ai.gateway import AiGateway
from src.server.ai.providers import BaseAiProvider


def _provider_config(protocol: str = "responses") -> dict:
    return {
        "provider_config_id": "provider-1",
        "name": "Configured GPT",
        "api_base_url": "http://127.0.0.1:9999/v1",
        "protocol": protocol,
        "model": "gpt-5.4",
        "api_key": "sk-configured-secret",
        "supports_image": True,
    }


class _FakeResponse:
    def __init__(self, data: dict, status_code: int = 200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._data


class _RecordingClient:
    requests: list[dict] = []
    response: _FakeResponse | None = None

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, **kwargs):
        self.requests.append({"url": url, "client": self.kwargs, **kwargs})
        return self.response


@pytest.mark.asyncio
async def test_configured_provider_generates_base64_scene_image_without_following_redirects(monkeypatch):
    from src.server.ai.providers import ConfiguredOpenAIProvider

    _RecordingClient.requests = []
    _RecordingClient.response = _FakeResponse({
        "data": [{"b64_json": "AA=="}],
    })
    monkeypatch.setattr("src.server.ai.providers.httpx.AsyncClient", _RecordingClient)

    result = await ConfiguredOpenAIProvider(_provider_config()).generate_image(
        prompt="雾中的旧宅，画面中不要文字。",
        size="1024x1024",
    )

    request = _RecordingClient.requests[0]
    assert request["url"] == "http://127.0.0.1:9999/v1/images/generations"
    assert request["client"]["follow_redirects"] is False
    assert request["json"] == {
        "model": "gpt-5.4",
        "prompt": "雾中的旧宅，画面中不要文字。",
        "size": "1024x1024",
        "response_format": "b64_json",
    }
    assert result == {"data_url": "data:image/png;base64,AA==", "mime_type": "image/png"}


@pytest.mark.asyncio
async def test_responses_protocol_sends_text_and_image_content(monkeypatch):
    from src.server.ai.providers import ConfiguredOpenAIProvider

    _RecordingClient.requests = []
    _RecordingClient.response = _FakeResponse({
        "output_text": json.dumps({"scenes": [{"name": "钟楼"}]}, ensure_ascii=False),
    })
    monkeypatch.setattr("src.server.ai.providers.httpx.AsyncClient", _RecordingClient)
    provider = ConfiguredOpenAIProvider(_provider_config("responses"))

    result = await provider.call("structure_scenario", {
        "contentPackage": {
            "canonical_text": "钟楼中隐藏着一把钥匙。",
            "parts": [{
                "kind": "image",
                "source_ref": "scan.png#image=1",
                "data_url": "data:image/png;base64,AA==",
            }],
        },
        "system_prompt": "提取世界书。",
    })

    request = _RecordingClient.requests[0]
    user_content = request["json"]["input"][1]["content"]
    assert request["url"] == "http://127.0.0.1:9999/v1/responses"
    assert request["client"]["follow_redirects"] is False
    assert any(item["type"] == "input_image" for item in user_content)
    assert any("scan.png#image=1" in item.get("text", "") for item in user_content)
    assert result["scenes"][0]["name"] == "钟楼"


@pytest.mark.asyncio
async def test_chat_completions_protocol_sends_openai_image_url(monkeypatch):
    from src.server.ai.providers import ConfiguredOpenAIProvider

    _RecordingClient.requests = []
    _RecordingClient.response = _FakeResponse({
        "choices": [{"message": {"content": json.dumps({"scenes": []})}}],
    })
    monkeypatch.setattr("src.server.ai.providers.httpx.AsyncClient", _RecordingClient)
    provider = ConfiguredOpenAIProvider(_provider_config("chat_completions"))

    result = await provider.call("structure_scenario", {
        "contentPackage": {
            "canonical_text": "扫描剧本",
            "parts": [{
                "kind": "image",
                "source_ref": "page:1",
                "data_url": "data:image/png;base64,AA==",
            }],
        },
        "system_prompt": "提取世界书。",
    })

    request = _RecordingClient.requests[0]
    user_content = request["json"]["messages"][1]["content"]
    assert request["url"] == "http://127.0.0.1:9999/v1/chat/completions"
    assert any(item["type"] == "image_url" for item in user_content)
    assert result == {"scenes": []}


@pytest.mark.asyncio
async def test_structure_call_uses_bounded_extended_timeout(monkeypatch):
    from src.server.ai.providers import ConfiguredOpenAIProvider

    _RecordingClient.requests = []
    _RecordingClient.response = _FakeResponse({
        "choices": [{"message": {"content": json.dumps({"scenes": []})}}],
    })
    monkeypatch.setattr("src.server.ai.providers.httpx.AsyncClient", _RecordingClient)
    provider = ConfiguredOpenAIProvider(_provider_config("chat_completions"), timeout=30)

    await provider.call(
        "structure_scenario",
        {"user_message": "编译完整剧本", "timeout_seconds": 3600},
    )

    assert _RecordingClient.requests[0]["client"]["timeout"] == 900


@pytest.mark.asyncio
async def test_chat_completions_unwraps_nested_json_for_runtime_tasks(monkeypatch):
    from src.server.ai.providers import ConfiguredOpenAIProvider

    _RecordingClient.requests = []
    _RecordingClient.response = _FakeResponse({
        "choices": [{"message": {"content": json.dumps({
            "narrative": {
                "public": json.dumps({"narrative_text": "车门在身后关闭。"})
            }
        })}}],
    })
    monkeypatch.setattr("src.server.ai.providers.httpx.AsyncClient", _RecordingClient)

    result = await ConfiguredOpenAIProvider(_provider_config("chat_completions")).call(
        "narrate_action",
        {"user_message": "返回叙事 JSON。", "system_prompt": "JSON only"},
    )

    assert result == {"narrative_text": "车门在身后关闭。"}


@pytest.mark.asyncio
async def test_connection_probe_tests_text_and_declared_image_capability(monkeypatch):
    from src.server.ai.providers import ConfiguredOpenAIProvider

    _RecordingClient.requests = []
    _RecordingClient.response = _FakeResponse({"output_text": '{"ok":true}'})
    monkeypatch.setattr("src.server.ai.providers.httpx.AsyncClient", _RecordingClient)

    result = await ConfiguredOpenAIProvider(_provider_config("responses")).test_connection()

    assert result["ok"] is True
    assert result["text"]["ok"] is True
    assert result["image"]["required"] is True
    assert result["image"]["ok"] is True
    assert len(_RecordingClient.requests) == 2


@pytest.mark.asyncio
async def test_connection_probe_maps_auth_failure_without_response_body(monkeypatch):
    from src.server.ai.providers import ConfiguredOpenAIProvider

    _RecordingClient.requests = []
    _RecordingClient.response = _FakeResponse(
        {"error": {"message": "secret upstream body"}},
        status_code=401,
    )
    monkeypatch.setattr("src.server.ai.providers.httpx.AsyncClient", _RecordingClient)

    result = await ConfiguredOpenAIProvider(_provider_config("responses")).test_connection()

    assert result["ok"] is False
    assert result["text"]["error_code"] == "auth_failed"
    assert "secret upstream body" not in str(result)


@pytest.mark.asyncio
async def test_connection_probe_rejects_empty_success_response(monkeypatch):
    from src.server.ai.providers import ConfiguredOpenAIProvider

    _RecordingClient.requests = []
    _RecordingClient.response = _FakeResponse({"output": []})
    monkeypatch.setattr("src.server.ai.providers.httpx.AsyncClient", _RecordingClient)

    result = await ConfiguredOpenAIProvider(_provider_config("responses")).test_connection()

    assert result["ok"] is False
    assert result["text"]["error_code"] == "invalid_response"


def test_configured_provider_revalidates_resolved_target(monkeypatch):
    from src.server.ai.provider_config import ProviderConfigValidationError, assert_api_target_safe

    monkeypatch.setattr(
        "src.server.ai.provider_config.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("169.254.169.254", 443))],
    )

    with pytest.raises(ProviderConfigValidationError):
        assert_api_target_safe("https://provider.internal/v1")


class _LegacyProvider(BaseAiProvider):
    def __init__(self):
        super().__init__("legacy", {"text", "image"})
        self.calls = []

    async def call(self, task_type: str, context: dict):
        self.calls.append((task_type, context))
        return {"scenes": [{"name": "legacy"}]}


def _create_active_config(test_db):
    from src.server.ai.provider_config import AiProviderConfigStore

    store = AiProviderConfigStore(test_db)
    created = store.create({
        "name": "Active",
        "api_base_url": "https://api.example.com/v1",
        "protocol": "responses",
        "model": "gpt-5.4",
        "api_key": "sk-active-secret",
        "supports_image": True,
    }, actor_id="admin-1")
    store.record_test(created["provider_config_id"], True, 20, actor_id="admin-1")
    store.activate(created["provider_config_id"], actor_id="admin-1")
    return created


def test_gateway_puts_active_configured_provider_before_legacy_chain(test_db):
    from src.server.ai.providers import ConfiguredOpenAIProvider

    _create_active_config(test_db)
    gateway = AiGateway(db_conn=test_db)
    legacy = _LegacyProvider()
    gateway._providers = {"legacy": legacy}
    gateway._provider_order = ["legacy"]

    providers = gateway._get_ordered_providers()

    assert isinstance(providers[0], ConfiguredOpenAIProvider)
    assert providers[1] is legacy


@pytest.mark.asyncio
async def test_gateway_generates_scene_image_through_active_configured_provider(test_db, monkeypatch):
    from src.server.ai.providers import ConfiguredOpenAIProvider

    _create_active_config(test_db)
    gateway = AiGateway(db_conn=test_db)
    calls = []

    async def generate_image(self, *, prompt, size):
        calls.append((prompt, size, self.provider_config_id))
        return {"data_url": "data:image/png;base64,AA==", "mime_type": "image/png"}

    monkeypatch.setattr(ConfiguredOpenAIProvider, "generate_image", generate_image)

    result = await gateway.generate_scene_image({
        "prompt": "雾中的旧宅",
        "size": "1024x1024",
    })

    assert result["mime_type"] == "image/png"
    assert len(calls) == 1
    assert calls[0][:2] == ("雾中的旧宅", "1024x1024")
    assert calls[0][2]


@pytest.mark.asyncio
async def test_gateway_falls_back_to_legacy_when_active_config_fails(test_db, monkeypatch):
    from src.server.ai.providers import ConfiguredOpenAIProvider

    _create_active_config(test_db)
    gateway = AiGateway(db_conn=test_db)
    legacy = _LegacyProvider()
    gateway._providers = {"legacy": legacy}
    gateway._provider_order = ["legacy"]

    async def fail_configured(self, task_type, context):
        return None

    monkeypatch.setattr(ConfiguredOpenAIProvider, "call", fail_configured)

    result = await gateway.structure_scenario("足够长的剧本文本")

    assert result["scenes"][0]["name"] == "legacy"
    assert legacy.calls[0][0] == "structure_scenario"
