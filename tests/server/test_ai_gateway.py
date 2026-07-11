import pytest

from src.server.ai.contracts import KpResponse, NarrativePayload
from src.server.ai.gateway import AiGateway
from src.server.ai.providers import BaseAiProvider
from src.server.scenario.content_package import ContentPackage, ContentPart


class FakeProvider:
    def __init__(self, response):
        self.name = "fake"
        self.response = response

    async def call(self, task_type: str, context: dict):
        return self.response

    async def health_check(self) -> bool:
        return True


class EchoUserMessageProvider:
    name = "fake"

    async def call(self, task_type: str, context: dict):
        return {"narrative": {"public": context["user_message"]}}

    async def health_check(self) -> bool:
        return True


class RecordingProvider(BaseAiProvider):
    def __init__(self, name: str, response, capabilities: set[str] | None = None):
        super().__init__(name, capabilities=capabilities)
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def call(self, task_type: str, context: dict):
        self.calls.append((task_type, context))
        return self.response

    async def health_check(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_generate_map_requires_json_structured_provider_output_without_local_fallback():
    gateway = AiGateway()
    remote = RecordingProvider("remote", None)
    local = RecordingProvider("local", {"narrative": {"public": "不是地图"}})
    gateway._providers = {"remote": remote, "local": local}
    gateway._provider_order = ["remote", "local"]

    result = await gateway.generate_map([{"name": "大厅"}])

    assert result is None
    assert local.calls == []
    assert "JSON" in remote.calls[0][1]["system_prompt"]


@pytest.mark.asyncio
async def test_generate_narrative_unwraps_kp_response_shape():
    gateway = AiGateway()
    gateway._providers = {
        "fake": FakeProvider({
            "narrative": {"public": "烛火忽然晃动，墙上的影子拉长了一瞬。"},
            "keeperNotes": "internal",
        })
    }
    gateway._provider_order = ["fake"]

    result = await gateway.generate_narrative({"player_words": "我环顾四周"})

    assert isinstance(result, NarrativePayload)
    assert result.public == "烛火忽然晃动，墙上的影子拉长了一瞬。"


@pytest.mark.asyncio
async def test_ephemeral_action_analysis_does_not_create_ai_call_log(test_db):
    gateway = AiGateway(db_conn=test_db)
    gateway._providers = {
        "fake": FakeProvider(
            {
                "understanding_summary": "临时分析",
                "risk": "low",
                "intent_type": "dialogue",
                "confirmation_requirements": [],
                "confidence": 0.9,
            }
        )
    }
    gateway._provider_order = ["fake"]
    before = test_db.execute("SELECT COUNT(*) AS count FROM ai_call_logs").fetchone()["count"]

    await gateway.analyze_action_draft(
        {
            "declared_intent": "我看看桌面",
            "intent_type": "dialogue",
            "base_state_version": 0,
            "suppress_response_log": True,
        },
        room_id="room-ephemeral",
    )

    after = test_db.execute("SELECT COUNT(*) AS count FROM ai_call_logs").fetchone()["count"]
    assert after == before


@pytest.mark.asyncio
async def test_generate_narrative_accepts_full_kp_response_model():
    gateway = AiGateway()
    gateway._providers = {
        "fake": FakeProvider(
            KpResponse(
                narrative=NarrativePayload(public="空气里有股焦味，像有什么东西刚刚熄灭。")
            ).model_dump(by_alias=True)
        )
    }
    gateway._provider_order = ["fake"]

    result = await gateway.generate_narrative({"player_words": "我闻一闻空气"})

    assert isinstance(result, NarrativePayload)
    assert result.public == "空气里有股焦味，像有什么东西刚刚熄灭。"


@pytest.mark.asyncio
async def test_generate_narrative_builds_user_message_when_missing():
    gateway = AiGateway()
    gateway._providers = {"fake": EchoUserMessageProvider()}
    gateway._provider_order = ["fake"]

    result = await gateway.generate_narrative({
        "scenario_title": "向火独行",
        "investigator_name": "查尔斯·钱伯斯",
        "occupation": "记者",
        "background": "追踪异常新闻的调查记者",
        "player_words": "我压低声音问老板，今晚灯塔那边到底发生过什么。",
    })

    assert "查尔斯·钱伯斯" in result.public
    assert "记者" in result.public
    assert "今晚灯塔那边到底发生过什么" in result.public


@pytest.mark.asyncio
async def test_generate_narrative_preserves_retry_context_when_player_words_missing():
    gateway = AiGateway()
    gateway._providers = {"fake": EchoUserMessageProvider()}
    gateway._provider_order = ["fake"]

    result = await gateway.generate_narrative({
        "room_id": "room-1",
        "character_id": "char-1",
        "declared_intent": "我贴近门边偷听屋里的动静",
        "intent_type": "dialogue",
        "previous_narrative": "你刚刚的脚步声在走廊尽头荡开。",
        "spoiler_constraint": "不要提前说出凶手身份",
    })

    assert "我贴近门边偷听屋里的动静" in result.public
    assert "不要提前说出凶手身份" in result.public
    assert "上一版叙事" in result.public


@pytest.mark.asyncio
async def test_structure_content_package_text_uses_existing_chain():
    gateway = AiGateway()
    mcp = RecordingProvider("mcp", None, capabilities={"text", "image"})
    deepseek = RecordingProvider("deepseek", {"scenes": [{"name": "A"}]})
    local = RecordingProvider("local", {"scenes": [{"name": "local"}]})
    gateway._providers = {"mcp": mcp, "deepseek": deepseek, "local": local}
    gateway._provider_order = ["mcp", "deepseek", "local"]

    package = ContentPackage(
        source_filename="scenario.txt",
        source_sha256="sha",
        mime_type="text/plain",
        parts=[ContentPart(ordinal=1, kind="text", text="第一幕：调查开始")],
        canonical_text="第一幕：调查开始",
        requires_multimodal=False,
    )

    result = await gateway.structure_content_package(package)

    assert result == {"scenes": [{"name": "A"}]}
    assert [provider.calls[0][0] for provider in (mcp, deepseek)] == [
        "structure_scenario",
        "structure_scenario",
    ]
    assert "rawText" in mcp.calls[0][1]
    assert mcp.calls[0][1]["rawText"] == "第一幕：调查开始"
    assert local.calls == []


@pytest.mark.asyncio
async def test_structure_content_package_requires_image_provider():
    gateway = AiGateway()
    deepseek = RecordingProvider("deepseek", {"scenes": [{"name": "text"}]})
    local = RecordingProvider("local", {"scenes": [{"name": "local"}]})
    gateway._providers = {"deepseek": deepseek, "local": local}
    gateway._provider_order = ["deepseek", "local"]

    package = ContentPackage(
        source_filename="scan.pdf",
        source_sha256="sha",
        mime_type="application/pdf",
        parts=[ContentPart(ordinal=1, kind="image", mime_type="image/png", data_url="data:image/png;base64,AA==")],
        canonical_text="",
        requires_multimodal=True,
    )

    with pytest.raises(RuntimeError, match="multimodal_provider_unavailable"):
        await gateway.structure_content_package(package)

    assert deepseek.calls == []
    assert local.calls == []


@pytest.mark.asyncio
async def test_structure_content_package_rejects_narrative_shaped_image_result():
    gateway = AiGateway()
    mcp = RecordingProvider(
        "mcp",
        {"narrative": {"public": "provider error fallback"}},
        capabilities={"text", "image"},
    )
    gateway._providers = {"mcp": mcp}
    gateway._provider_order = ["mcp"]
    package = ContentPackage(
        source_filename="scan.pdf",
        source_sha256="sha",
        mime_type="application/pdf",
        parts=[ContentPart(
            ordinal=1,
            kind="image",
            mime_type="image/png",
            data_url="data:image/png;base64,AA==",
        )],
        canonical_text="",
        requires_multimodal=True,
    )

    with pytest.raises(RuntimeError, match="multimodal_provider_unavailable"):
        await gateway.structure_content_package(package)


@pytest.mark.asyncio
async def test_structure_content_package_falls_back_to_text_chain_when_canonical_text_is_long_enough():
    gateway = AiGateway()
    mcp = RecordingProvider("mcp", None, capabilities={"text", "image"})
    deepseek = RecordingProvider("deepseek", {"scenes": [{"name": "fallback"}]})
    local = RecordingProvider("local", {"scenes": [{"name": "local"}]})
    gateway._providers = {"mcp": mcp, "deepseek": deepseek, "local": local}
    gateway._provider_order = ["mcp", "deepseek", "local"]

    canonical_text = "这是一个足够长的纯文本摘要，用于在图像解析失败后回退到文本结构化链路。"
    canonical_text = canonical_text + "补充内容" * 10
    package = ContentPackage(
        source_filename="mixed.pdf",
        source_sha256="sha",
        mime_type="application/pdf",
        parts=[ContentPart(ordinal=1, kind="image", mime_type="image/png", data_url="data:image/png;base64,AA==")],
        canonical_text=canonical_text,
        requires_multimodal=True,
    )

    result = await gateway.structure_content_package(package)

    assert result == {"scenes": [{"name": "fallback"}]}
    assert len(mcp.calls) == 2
    assert mcp.calls[0][1]["contentPackage"]["requires_multimodal"] is True
    assert mcp.calls[1][1]["rawText"] == canonical_text
    assert deepseek.calls[0][1]["rawText"] == canonical_text
    assert local.calls == []
