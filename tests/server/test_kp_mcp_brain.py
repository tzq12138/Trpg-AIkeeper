import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kp_mcp_server.config import Config
from kp_mcp_server.kp_brain import KpBrain
from kp_mcp_server.server import build_server


@pytest.mark.asyncio
async def test_kp_brain_openai_provider_uses_responses_api():
    config = Config(
        provider="openai",
        api_key="sk-openai",
        model="gpt-5.4",
        api_base="https://api.openai.com/v1",
    )
    brain = KpBrain(config)

    response = MagicMock()
    response.output_text = json.dumps({
        "narrative": {"public": "煤油灯摇晃了一下，墙上的影子像被风惊动。"},
        "rollRequests": [],
        "stateMutations": [],
        "tacticalPrompts": [],
        "citations": [],
        "keeperNotes": "",
        "_error": None,
    }, ensure_ascii=False)

    with patch("kp_mcp_server.kp_brain.AsyncOpenAI") as mock_cls:
        client = MagicMock()
        client.responses.create = AsyncMock(return_value=response)
        mock_cls.return_value = client

        result = await brain._call_llm("请返回一段 JSON")

    assert result["narrative"]["public"] == "煤油灯摇晃了一下，墙上的影子像被风惊动。"
    mock_cls.assert_called_once()
    client.responses.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_narrative_default_prompt_requires_simplified_chinese():
    config = Config(
        provider="deepseek",
        api_key="sk-deepseek",
        model="deepseek-v4-pro",
        api_base="https://api.deepseek.com",
    )
    brain = KpBrain(config)
    brain._call_llm = AsyncMock(return_value={"narrative": {"public": "ok"}})

    await brain.generate_narrative({"declared_intent": "我敲了敲门"})

    assert brain._call_llm.await_count == 1
    kwargs = brain._call_llm.await_args.kwargs
    assert "简体中文" in kwargs["system_prompt"]
    assert "禁止切换成日文" in kwargs["system_prompt"]
    assert "不得自行引入未提及的地点" in kwargs["system_prompt"]


@pytest.mark.asyncio
async def test_analyze_director_action_uses_structured_plan_prompt_without_state_writes():
    brain = KpBrain(Config(provider="deepseek", api_key="sk-deepseek"))
    brain._call_llm = AsyncMock(return_value={"interpreted_intent": "观察门缝"})
    context = {
        "declared_intent": "我贴近门边，听听里面的动静",
        "context_version": 4,
        "user_message": '{"declared_intent":"我贴近门边，听听里面的动静"}',
    }

    result = await brain.analyze_director_action(context)

    assert result == {"interpreted_intent": "观察门缝"}
    args, kwargs = brain._call_llm.await_args
    assert args[0] == context["user_message"]
    assert "Director" in kwargs["system_prompt"]
    assert "must not mutate authoritative game state" in kwargs["system_prompt"]


@pytest.mark.asyncio
async def test_narrate_action_uses_verified_context_and_forbids_new_state():
    brain = KpBrain(Config(provider="deepseek", api_key="sk-deepseek"))
    brain._call_llm = AsyncMock(return_value={"narrative_text": "门后传来脚步声。"})
    context = {
        "context_version": 4,
        "user_message": '{"allowed_facts":["门后有脚步声"]}',
    }

    result = await brain.narrate_action(context)

    assert result == {"narrative_text": "门后传来脚步声。"}
    args, kwargs = brain._call_llm.await_args
    assert args[0] == context["user_message"]
    assert "Narrator" in kwargs["system_prompt"]
    assert "must not create state mutations" in kwargs["system_prompt"]


def _make_content_package(
    *,
    canonical_text: str = "Canonical text for structure_scenario.",
    image_urls: list[str] | None = None,
) -> dict:
    parts = [{"ordinal": 1, "kind": "text", "text": "Ignored source text."}]
    for index, image_url in enumerate(image_urls or [], start=2):
        parts.append({
            "ordinal": index,
            "kind": "image",
            "data_url": image_url,
            "source_ref": f"source-image:{index}",
        })
    return {
        "source_filename": "scenario.zip",
        "source_sha256": "abc123",
        "mime_type": "application/octet-stream",
        "parts": parts,
        "canonical_text": canonical_text,
        "requires_multimodal": True,
        "metadata": {},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "deepseek"])
async def test_structure_scenario_prefers_content_package_and_builds_multimodal_payload(provider):
    config = Config(
        provider=provider,
        api_key=f"sk-{provider}",
        model=f"{provider}-model",
        api_base=f"https://{provider}.example.com/v1",
    )
    brain = KpBrain(config)
    content_package = _make_content_package(
        canonical_text="Scene summary here.",
        image_urls=[
            "data:image/png;base64,AAA=",
            "https://example.com/not-inline.png",
            "data:image/jpeg;base64,BBB=",
        ],
    )

    if provider == "openai":
        response = MagicMock()
        response.output_text = json.dumps(
            {
                "scenarioTitle": "t",
                "scenes": [],
                "npcs": [],
                "clues": [],
                "truth": {},
                "endings": [],
                "triggerMechanics": [],
            },
            ensure_ascii=False,
        )
        with patch("kp_mcp_server.kp_brain.AsyncOpenAI") as mock_cls:
            client = MagicMock()
            client.responses.create = AsyncMock(return_value=response)
            mock_cls.return_value = client

            result = await brain.structure_scenario({"rawText": "legacy text", "contentPackage": content_package})

        call_kwargs = client.responses.create.await_args.kwargs
        user_content = call_kwargs["input"][1]["content"]
        assert result["scenarioTitle"] == "t"
        assert [item["type"] for item in user_content] == ["input_text", "input_image", "input_image"]
        assert "Scene summary here." in user_content[0]["text"]
        assert "source-image:2" in user_content[0]["text"]
        assert "source_part_texts" in call_kwargs["input"][0]["content"]
        assert user_content[1]["image_url"] == "data:image/png;base64,AAA="
        assert user_content[2]["image_url"] == "data:image/jpeg;base64,BBB="
        assert call_kwargs["input"][0]["content"] != brain.system_prompt
    else:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "scenarioTitle": "t",
                "scenes": [],
                "npcs": [],
                "clues": [],
                "truth": {},
                "endings": [],
                "triggerMechanics": [],
            }, ensure_ascii=False)}}]
        }
        client = MagicMock()
        client.post = AsyncMock(return_value=response)
        async_client = MagicMock()
        async_client.__aenter__ = AsyncMock(return_value=client)
        async_client.__aexit__ = AsyncMock(return_value=None)

        with patch("kp_mcp_server.kp_brain.httpx.AsyncClient", return_value=async_client):
            result = await brain.structure_scenario({"rawText": "legacy text", "contentPackage": content_package})

        payload = client.post.await_args.kwargs["json"]
        user_message = payload["messages"][1]["content"]
        assert result["scenarioTitle"] == "t"
        assert [item["type"] for item in user_message] == ["text", "image_url", "image_url"]
        assert "Scene summary here." in user_message[0]["text"]
        assert "source-image:2" in user_message[0]["text"]
        assert user_message[1]["image_url"]["url"] == "data:image/png;base64,AAA="
        assert user_message[2]["image_url"]["url"] == "data:image/jpeg;base64,BBB="
        assert all(
            item.get("image_url", {}).get("url", "").startswith("data:image/")
            for item in user_message
            if item["type"] == "image_url"
        )
        assert "source_part_texts" in payload["messages"][0]["content"]


@pytest.mark.asyncio
async def test_structure_scenario_caps_images_and_skips_oversized_or_non_data_urls():
    config = Config(provider="openai", api_key="sk-openai", model="gpt-5.4")
    brain = KpBrain(config)
    oversized_data_url = "data:image/png;base64," + ("A" * (8 * 1024 * 1024 + 1))
    image_urls = ["data:image/png;base64,AAA=" for _ in range(21)] + [
        oversized_data_url,
        "https://example.com/skip.png",
    ]
    content_package = _make_content_package(image_urls=image_urls)

    response = MagicMock()
    response.output_text = json.dumps(
        {
            "scenarioTitle": "t",
            "scenes": [],
            "npcs": [],
            "clues": [],
            "truth": {},
            "endings": [],
            "triggerMechanics": [],
        },
        ensure_ascii=False,
    )
    with patch("kp_mcp_server.kp_brain.AsyncOpenAI") as mock_cls:
        client = MagicMock()
        client.responses.create = AsyncMock(return_value=response)
        mock_cls.return_value = client

        await brain.structure_scenario({"contentPackage": content_package})

    user_content = client.responses.create.await_args.kwargs["input"][1]["content"]
    image_items = [item for item in user_content if item["type"] == "input_image"]
    assert len(image_items) == 20
    assert all(item["image_url"].startswith("data:image/") for item in image_items)


@pytest.mark.asyncio
async def test_structure_scenario_mock_mode_returns_valid_kg():
    brain = KpBrain(Config(provider="deepseek", api_key="", model="mock"))

    result = await brain.structure_scenario({"contentPackage": _make_content_package()})

    assert result == {
        "scenarioTitle": "mock",
        "scenes": [],
        "npcs": [],
        "clues": [],
        "branches": [],
        "truth": {},
        "endings": [],
        "triggerMechanics": [],
    }


@pytest.mark.asyncio
async def test_kp_structure_scenario_tool_accepts_optional_content_package():
    config = Config(provider="deepseek", api_key="sk-deepseek", model="deepseek-v4-pro")
    with patch("kp_mcp_server.server.KpBrain") as mock_brain_cls:
        brain = MagicMock()
        brain.structure_scenario = AsyncMock(return_value={"scenarioTitle": "ok"})
        mock_brain_cls.return_value = brain

        mcp = build_server(config)
        await mcp.call_tool(
            "kp_structure_scenario",
            {"contentPackage": _make_content_package(canonical_text="Scene summary here.")},
        )

    brain.structure_scenario.assert_awaited_once()
    passed_args = brain.structure_scenario.await_args.args[0]
    assert passed_args["contentPackage"]["canonical_text"] == "Scene summary here."
    assert passed_args["rawText"] == ""


@pytest.mark.asyncio
async def test_minimal_mcp_runtime_tools_forward_director_and_narrator_context():
    config = Config(provider="deepseek", api_key="sk-deepseek", model="deepseek-v4-pro")
    with patch("kp_mcp_server.server.KpBrain") as mock_brain_cls:
        brain = MagicMock()
        brain.analyze_director_action = AsyncMock(return_value={"interpreted_intent": "倾听"})
        brain.narrate_action = AsyncMock(return_value={"narrative_text": "木门微微颤动。"})
        mock_brain_cls.return_value = brain

        mcp = build_server(config)
        await mcp.call_tool(
            "kp_analyze_director_action",
            {"context": {"declared_intent": "我听门后的声音"}},
        )
        await mcp.call_tool(
            "kp_narrate_action",
            {"context": {"allowed_facts": ["门后有人"]}},
        )

    brain.analyze_director_action.assert_awaited_once_with(
        {"declared_intent": "我听门后的声音"}
    )
    brain.narrate_action.assert_awaited_once_with(
        {"allowed_facts": ["门后有人"]}
    )


@pytest.mark.asyncio
async def test_structure_scenario_rejects_explicit_empty_content_package():
    brain = KpBrain(Config(provider="deepseek", api_key="sk-deepseek"))
    brain._call_llm = AsyncMock(return_value={"scenarioTitle": "unexpected"})

    with pytest.raises(ValueError, match="content_package_empty"):
        await brain.structure_scenario({
            "rawText": "legacy text must not bypass an explicit package",
            "contentPackage": {"canonical_text": "", "parts": []},
        })

    brain._call_llm.assert_not_awaited()
