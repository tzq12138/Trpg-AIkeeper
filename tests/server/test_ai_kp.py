import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from src.server.ai.ai_kp import AIKP, structure_scenario
from src.server.models import AIResponse
from src.server.ai.spoiler_control import SpoilerController


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


class _NoRuleEvidenceRag:
    def search(self, *_args, **_kwargs):
        return [
            {
                "source_type": "scenario",
                "content": "公开场景：走廊里只有昏暗的灯光。",
            }
        ]


class _RuleEvidenceRag:
    def search(self, *_args, **_kwargs):
        return [
            {
                "source_type": "rule",
                "content": "规则证据：调查需要由主持人决定是否检定。",
            }
        ]


class _FailingRag:
    def search(self, *_args, **_kwargs):
        raise RuntimeError("RAG unavailable")


class _UnsafeNarrativeAIKP(AIKP):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.seen_contexts: list[dict] = []

    def _mock_response(self, _batch: dict, context: dict) -> AIResponse:
        self.seen_contexts.append(dict(context))
        return AIResponse(
            narrative=(
                "管理员身份 admin-42 使用 owner-secret；原始安全边界文本称"
                "管家是凶手，地下室藏着未揭示秘密。"
            )
        )


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
    from src.server.engine.batch import BatchCollector, BatchProcessor

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


async def test_ai_kp_persists_and_reuses_only_safe_current_room_adjudication(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, spoiler_level) "
        "VALUES ('room-adjudication', 'owner-secret', 'standard')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES ('char-adjudication', 'room-adjudication', 'Alice', 'player-secret')"
    )
    test_db.commit()
    batch = {
        "batch_id": "batch-adjudication",
        "room_id": "room-adjudication",
        "actions": [
            {
                "action_id": "action-adjudication",
                "character_id": "char-adjudication",
                "declared_intent": "调查书架",
            }
        ],
    }
    ai = _UnsafeNarrativeAIKP(
        api_key="",
        spoiler_controller=SpoilerController(test_db),
        rag_store=_NoRuleEvidenceRag(),
    )

    first_response = await ai.process_batch(
        "room-adjudication", batch, _make_scenario()
    )
    stored = test_db.execute(
        "SELECT summary, minimal_state FROM room_rule_adjudications "
        "WHERE room_id = 'room-adjudication'"
    ).fetchone()

    assert stored is not None
    stored_text = json.dumps(dict(stored), ensure_ascii=False)
    assert stored["minimal_state"] == {"scene": "昏暗走廊"}
    assert stored["summary"]
    assert stored["summary"] != first_response.narrative
    for forbidden in (
        "admin-42",
        "owner-secret",
        "player-secret",
        "原始安全边界文本",
        "管家是凶手",
        "地下室藏着未揭示秘密",
    ):
        assert forbidden not in stored_text

    await ai.process_batch("room-adjudication", batch, _make_scenario())

    adjudication = ai.seen_contexts[-1]["room_adjudication"]
    assert set(adjudication) == {"question_key", "summary", "minimal_state"}
    assert adjudication["question_key"] == "调查书架"
    assert adjudication["minimal_state"] == {"scene": "昏暗走廊"}
    prompt = ai._build_user_message(batch, ai.seen_contexts[-1])
    for forbidden in (
        "admin-42",
        "owner-secret",
        "player-secret",
        "原始安全边界文本",
        "管家是凶手",
        "地下室藏着未揭示秘密",
    ):
        assert forbidden not in prompt


async def test_ai_kp_does_not_store_adjudication_when_rule_evidence_exists(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, spoiler_level) "
        "VALUES ('room-with-rule', 'owner-rule', 'standard')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES ('char-with-rule', 'room-with-rule', 'Alice', 'player-rule')"
    )
    test_db.commit()
    batch = {
        "batch_id": "batch-with-rule",
        "room_id": "room-with-rule",
        "actions": [
            {
                "action_id": "action-with-rule",
                "character_id": "char-with-rule",
                "declared_intent": "调查书架",
            }
        ],
    }
    ai = _UnsafeNarrativeAIKP(
        api_key="",
        spoiler_controller=SpoilerController(test_db),
        rag_store=_RuleEvidenceRag(),
    )

    await ai.process_batch("room-with-rule", batch, _make_scenario())

    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM room_rule_adjudications "
        "WHERE room_id = 'room-with-rule'"
    ).fetchone()["count"] == 0
    assert "room_adjudication" not in ai.seen_contexts[-1]


async def test_ai_kp_does_not_store_adjudication_when_rule_search_fails(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, spoiler_level) "
        "VALUES ('room-rag-failure', 'owner-failure', 'standard')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES ('char-rag-failure', 'room-rag-failure', 'Alice', 'player-failure')"
    )
    test_db.commit()
    ai = _UnsafeNarrativeAIKP(
        api_key="",
        spoiler_controller=SpoilerController(test_db),
        rag_store=_FailingRag(),
    )

    await ai.process_batch("room-rag-failure", {
        "actions": [{"character_id": "char-rag-failure", "declared_intent": "调查书架"}],
    }, _make_scenario())

    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM room_rule_adjudications "
        "WHERE room_id = 'room-rag-failure'"
    ).fetchone()["count"] == 0
    assert "room_adjudication" not in ai.seen_contexts[-1]


async def test_ai_kp_does_not_copy_raw_scenario_fallback_into_adjudication(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, spoiler_level) "
        "VALUES ('room-no-structured-scene', 'owner-raw', 'standard')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES ('char-no-structured-scene', 'room-no-structured-scene', 'Alice', 'player-raw')"
    )
    test_db.commit()
    scenario = _make_scenario()
    scenario["raw_text"] = "不得写入的原始场景边界文本"
    scenario["knowledge_graph"] = json.dumps({"truth_summary": "不得写入的秘密"})
    ai = _UnsafeNarrativeAIKP(
        api_key="",
        spoiler_controller=SpoilerController(test_db),
        rag_store=_NoRuleEvidenceRag(),
    )

    await ai.process_batch("room-no-structured-scene", {
        "actions": [{"character_id": "char-no-structured-scene", "declared_intent": "调查书架"}],
    }, scenario)

    stored = test_db.execute(
        "SELECT minimal_state FROM room_rule_adjudications "
        "WHERE room_id = 'room-no-structured-scene'"
    ).fetchone()
    assert stored["minimal_state"] == {}


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

    with patch("src.server.ai.ai_kp.httpx.AsyncClient") as mock_client_cls:
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

    with patch("src.server.ai.ai_kp.httpx.AsyncClient") as mock_client_cls:
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
    from src.server.engine.batch import BatchCollector, BatchProcessor

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

    with patch("src.server.ai.ai_kp.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await structure_scenario("剧本原文", api_key="fake-key")

    assert result["scenes"][0]["name"] == "开场"
    assert result["npcs"][0]["name"] == "管家"
    assert result["truth"]["summary"] == "管家是凶手"
