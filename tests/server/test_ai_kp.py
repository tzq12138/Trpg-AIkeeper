import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from src.server.ai_kp import AIKP, structure_scenario
from src.server.models import AIResponse
from src.server.spoiler_control import SpoilerController


def _make_batch():
    return {
        "batch_id": "batch-1",
        "room_id": "room-1",
        "actions": [
            {"action_id": "a1", "character_id": "char-1", "declared_intent": "调查书架"},
        ],
    }


def _make_scenario():
    return {
        "scenario_id": "sc-1",
        "title": "黑暗庄园",
        "raw_text": "一座古老的庄园。",
        "knowledge_graph": json.dumps({
            "scene_description": "昏暗走廊",
            "clues": [{"clue_id": "c1", "text": "血迹", "is_hidden": False}],
            "npcs": [],
            "truth_summary": "管家是凶手",
        }),
    }


async def test_mock_ai_generates_narrative():
    ai = AIKP(api_key="")
    batch = _make_batch()
    scenario = _make_scenario()

    response = await ai.process_batch("room-1", batch, scenario)

    assert isinstance(response, AIResponse)
    assert len(response.narrative) > 0
    assert "书架" in response.narrative or "调查" in response.narrative


async def test_mock_ai_generates_skill_check():
    ai = AIKP(api_key="")
    batch = _make_batch()
    scenario = _make_scenario()

    response = await ai.process_batch("room-1", batch, scenario)

    assert len(response.roll_requests) == 1
    assert response.roll_requests[0].skill_name == "侦查"
    assert response.roll_requests[0].difficulty == "regular"


async def test_mock_ai_dialogue_roll():
    ai = AIKP(api_key="")
    batch = {
        "batch_id": "batch-2",
        "room_id": "room-1",
        "actions": [
            {"action_id": "a1", "character_id": "char-1", "declared_intent": "与管家说话"},
        ],
    }
    scenario = _make_scenario()

    response = await ai.process_batch("room-1", batch, scenario)

    assert len(response.roll_requests) == 1
    assert response.roll_requests[0].skill_name == "话术"


async def test_mock_ai_move_no_roll():
    ai = AIKP(api_key="")
    batch = {
        "batch_id": "batch-3",
        "room_id": "room-1",
        "actions": [
            {"action_id": "a1", "character_id": "char-1", "declared_intent": "走向走廊尽头"},
        ],
    }
    scenario = _make_scenario()

    response = await ai.process_batch("room-1", batch, scenario)

    assert len(response.roll_requests) == 0
    assert "走廊" in response.narrative


async def test_batch_processing_flow(test_db):
    from src.server.batch import BatchCollector, BatchProcessor

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, spoiler_level) VALUES ('room-1', 'tok', 'standard')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES ('char-1', 'room-1', 'Alice', 'tok1')"
    )
    test_db.commit()

    ai = AIKP(api_key="")
    spoiler_ctrl = SpoilerController(test_db)
    ai.spoiler_controller = spoiler_ctrl

    collector = BatchCollector(window_seconds=0)
    processor = BatchProcessor(
        collector=collector,
        process_fn=ai.process_batch,
    )

    processor.add_action("room-1", {
        "action_id": "a1", "character_id": "char-1", "declared_intent": "查看房间",
    })

    scenario = _make_scenario()
    response = await processor.try_process("room-1", scenario)

    assert response is not None
    assert isinstance(response, AIResponse)
    assert processor.get_status("room-1")["batch_status"] == "completed"


async def test_ai_timeout_handling():
    ai = AIKP(api_key="fake-key", api_base="http://localhost:1")
    batch = _make_batch()
    scenario = _make_scenario()

    response = await ai.process_batch("room-1", batch, scenario)

    assert isinstance(response, AIResponse)
    assert "降级" in response.narrative or "停顿" in response.narrative
    assert ai.get_failure_count("room-1") == 1


async def test_invalid_ai_response_handling():
    ai = AIKP(api_key="fake-key")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "not valid json {{"}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("src.server.ai_kp.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        batch = _make_batch()
        scenario = _make_scenario()
        response = await ai.process_batch("room-1", batch, scenario)

    assert isinstance(response, AIResponse)
    assert ai.get_failure_count("room-1") == 1


async def test_deepseek_success():
    ai = AIKP(api_key="fake-key")

    ai_data = {
        "narrative": "你仔细检查了书架，发现了一本与众不同的书。",
        "stateSuggestions": [{"type": "clue", "target": "char-1", "value": "c1", "reason": "发现线索"}],
        "rollRequests": [{"skillName": "图书馆使用", "difficulty": "hard", "reason": "深入研究"}],
        "tacticalPrompts": [{"text": "你可以翻开这本书。", "actions": []}],
        "cluesToRelease": ["c1"],
        "keeperNotes": "释放线索c1",
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": json.dumps(ai_data)}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("src.server.ai_kp.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        batch = _make_batch()
        scenario = _make_scenario()
        response = await ai.process_batch("room-1", batch, scenario)

    assert response.narrative == "你仔细检查了书架，发现了一本与众不同的书。"
    assert len(response.roll_requests) == 1
    assert response.roll_requests[0].skill_name == "图书馆使用"
    assert response.roll_requests[0].difficulty == "hard"
    assert len(response.state_suggestions) == 1
    assert response.state_suggestions[0].type == "clue"
    assert response.clues_to_release == ["c1"]
    assert ai.get_failure_count("room-1") == 0


async def test_consecutive_failures_escalation():
    ai = AIKP(api_key="fake-key", api_base="http://localhost:1")
    batch = _make_batch()
    scenario = _make_scenario()

    for _ in range(3):
        await ai.process_batch("room-1", batch, scenario)

    response = await ai.process_batch("room-1", batch, scenario)
    assert "连续处理失败" in response.narrative or "降级" in response.narrative
    assert ai.get_failure_count("room-1") == 4


def test_is_mock_property():
    assert AIKP(api_key="").is_mock is True
    assert AIKP(api_key="some-key").is_mock is False


async def test_tactical_prompts_generated():
    ai = AIKP(api_key="")
    batch = _make_batch()
    scenario = _make_scenario()

    response = await ai.process_batch("room-1", batch, scenario)

    assert len(response.tactical_prompts) >= 1
    assert len(response.tactical_prompts[0].text) > 0


async def test_batch_processor_no_scenario():
    from src.server.batch import BatchCollector, BatchProcessor

    collector = BatchCollector(window_seconds=0)
    processor = BatchProcessor(collector=collector)

    processor.add_action("room-1", {"action_id": "a1", "character_id": "c1", "declared_intent": "look"})
    response = await processor.try_process("room-1", None)

    assert response is not None


async def test_structure_scenario_mock():
    raw_text = "第一章：黑暗降临\n\n这是一个恐怖的庄园。\n\nNPC：张三\n线索：血迹"
    result = await structure_scenario(raw_text)

    assert "scenes" in result
    assert "npcs" in result
    assert "clues" in result
    assert len(result["scenes"]) >= 1


async def test_structure_scenario_with_ai():
    ai_response = {
        "scenes": [{"name": "开场", "description": "庄园入口", "order": 1}],
        "npcs": [{"name": "管家", "role": "反派", "description": "可疑人物"}],
        "clues": [{"name": "血迹", "description": "地板上的血迹", "location": "走廊"}],
        "truth": {"summary": "管家是凶手"},
        "endings": [{"name": "真相大白", "description": "揭露管家", "type": "victory"}],
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": json.dumps(ai_response)}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("src.server.ai_kp.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await structure_scenario("剧本原文", api_key="fake-key")

    assert result["scenes"][0]["name"] == "开场"
    assert result["npcs"][0]["name"] == "管家"
    assert result["truth"]["summary"] == "管家是凶手"
