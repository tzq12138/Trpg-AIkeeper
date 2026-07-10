import pytest

from src.server.ai.mechanic_compiler import MechanicCompiler
from src.server.models import PlayerIntent


@pytest.mark.asyncio
async def test_python_compiler_maps_investigation_text_to_skill_check():
    compiler = MechanicCompiler(api_key="")
    intent = PlayerIntent(intent_type="dialogue", declared_intent="我仔细侦查这个房间")

    result = await compiler.compile(intent, scenario={}, character={})

    assert result.triggered_mechanic == "skill_check"
    assert result.skill_name == "侦查"
    assert result.difficulty == "regular"
    assert result.item_consumed is False


@pytest.mark.asyncio
async def test_python_compiler_keeps_plain_dialogue_as_dialogue():
    compiler = MechanicCompiler(api_key="")
    intent = PlayerIntent(intent_type="dialogue", declared_intent="我问老板昨晚看到了什么")

    result = await compiler.compile(intent, scenario={}, character={})

    assert result.triggered_mechanic == "dialogue"
    assert result.skill_name is None


@pytest.mark.asyncio
async def test_compiler_falls_back_to_python_when_deepseek_fails(monkeypatch):
    async def fail_call(*args, **kwargs):
        raise RuntimeError("bad json")

    compiler = MechanicCompiler(api_key="test-key")
    monkeypatch.setattr(compiler, "_call_deepseek", fail_call)
    intent = PlayerIntent(intent_type="dialogue", declared_intent="我搜索抽屉")

    result = await compiler.compile(intent, scenario={}, character={})

    assert result.triggered_mechanic == "skill_check"
    assert result.skill_name == "侦查"


@pytest.mark.parametrize("raw_mechanic", ["observation", "技能检定", "check"])
def test_compiler_normalizes_common_skill_check_aliases(raw_mechanic):
    compiler = MechanicCompiler()

    result = compiler._normalize_raw_result({"triggeredMechanic": raw_mechanic})

    assert result["triggeredMechanic"] == "skill_check"


@pytest.mark.parametrize(
    ("raw_skill", "skills", "expected"),
    [
        ("侦察", {"侦查": 65}, "侦查"),
        ("交涉", {"话术": 26, "说服": 10}, "话术"),
        ("Spot Hidden", {"侦查": 65}, "侦查"),
        ("打听", {"话术": 26, "说服": 10}, "话术"),
        ("心理分析", {"心理学": 10}, "心理学"),
    ],
)
def test_compiler_normalizes_ai_skill_aliases_to_character_skills(raw_skill, skills, expected):
    compiler = MechanicCompiler()

    result = compiler._normalize_raw_result(
        {"triggeredMechanic": "skill_check", "skillName": raw_skill},
        {"xlsx_data": {"skills": skills}},
    )

    assert result["skillName"] == expected


def test_compiler_downgrades_unknown_ai_skill_to_dialogue_for_known_character():
    compiler = MechanicCompiler()

    result = compiler._normalize_raw_result(
        {"triggeredMechanic": "skill_check", "skillName": "未知异能"},
        {"xlsx_data": {"skills": {"侦查": 65}}},
        "我随口问候老板。",
    )

    assert result["triggeredMechanic"] == "dialogue"
    assert "skillName" not in result
