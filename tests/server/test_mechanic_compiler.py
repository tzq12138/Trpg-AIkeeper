import pytest

from src.server.mechanic_compiler import MechanicCompiler
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
