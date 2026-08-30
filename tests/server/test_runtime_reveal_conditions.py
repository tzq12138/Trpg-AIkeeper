import json
from pathlib import Path


def _runtime_package():
    return {
        "semantic_scenes": [
            {
                "scene_id": "lost-property-counter",
                "name": "失物局柜台",
                "npcs_present": ["gao-clerk"],
            },
            {
                "scene_id": "night-market",
                "name": "夜市修表摊",
                "npcs_present": ["zhong-watchmaker"],
            },
            {
                "scene_id": "archive-reading-room",
                "name": "城市档案阅览室",
                "npcs_present": ["shi-archivist"],
            },
        ],
        "npc_states": [
            {
                "npc_id": "gao-clerk",
                "name": "高静川",
                "public_name": "高办事员",
            },
            {
                "npc_id": "zhong-watchmaker",
                "name": "钟序",
                "public_name": "钟师傅",
            },
        ],
        "character_and_items": {
            "items": [
                {
                    "item_id": "archive-index",
                    "name": "封存索引",
                    "public_name": "市政档案",
                }
            ]
        },
        "clue_dependencies": [
            {
                "clue_id": "brass-token",
                "name": "黄铜寄存牌 47",
                "description": "DESCRIPTION SECRET: 编号直接指向地下机器。",
                "public_version": "一枚会在午夜自行退回的黄铜寄存牌。",
                "private_version": "PRIVATE SECRET: 机器的完整停机顺序。",
                "location": "失物局柜台",
                "importance": "core",
                "reveal_conditions": [
                    {"kind": "inspect", "scene_id": "lost-property-counter"}
                ],
                "prerequisite_fact_refs": [],
                "failure_outcome": {"preserve_core": True},
            },
            {
                "clue_id": "altered-claim-log",
                "name": "涂改的取件簿",
                "public_version": "取件簿上有多处被同一笔迹涂改的签名。",
                "location": "失物局柜台",
                "importance": "supporting",
                "reveal_conditions": [
                    {"kind": "inspect", "scene_id": "lost-property-counter"}
                ],
                "prerequisite_fact_refs": [],
                "failure_outcome": {"preserve_core": True},
            },
            {
                "clue_id": "token-scratch",
                "name": "修复后的刻痕",
                "public_version": "修复的刻痕写着“先归还，再记忆”。",
                "location": "夜市修表摊",
                "importance": "supporting",
                "reveal_conditions": [
                    {"kind": "ask_npc", "npc_id": "zhong-watchmaker"}
                ],
                "prerequisite_fact_refs": ["brass-token"],
                "failure_outcome": {"preserve_core": True},
            },
            {
                "clue_id": "sealed-blueprint",
                "name": "封存地下蓝图",
                "public_version": "蓝图标出失物局与渡轮仓库之间的废弃通道。",
                "location": "城市档案阅览室",
                "importance": "core",
                "reveal_conditions": [
                    {
                        "kind": "research",
                        "scene_id": "archive-reading-room",
                        "item_id": "archive-index",
                    }
                ],
                "prerequisite_fact_refs": [],
                "failure_outcome": {"preserve_core": False},
            },
        ],
    }


def test_select_runtime_clue_discovers_public_text_without_clue_name():
    from src.server.engine.runtime_reveal_conditions import select_runtime_clue

    selection = select_runtime_clue(
        _runtime_package(),
        "lost-property-counter",
        "dialogue",
        "我仔细检查柜台上的寄存牌和取件簿。",
        set(),
    )

    assert selection.candidate is not None
    assert selection.candidate.canonical_id == "brass-token"
    assert selection.candidate.player_text == "一枚会在午夜自行退回的黄铜寄存牌。"
    assert "DESCRIPTION SECRET" not in selection.candidate.player_text
    assert "PRIVATE SECRET" not in selection.candidate.player_text


def test_select_runtime_clue_does_not_treat_movement_as_inspection():
    from src.server.engine.runtime_reveal_conditions import select_runtime_clue

    inspection = select_runtime_clue(
        _runtime_package(),
        "lost-property-counter",
        "move",
        "我前往失物局柜台调查寄存牌的来历。",
        set(),
    )
    research = select_runtime_clue(
        _runtime_package(),
        "archive-reading-room",
        "move",
        "我前往城市档案阅览室查阅市政档案。",
        set(),
    )

    assert inspection.candidate is None
    assert research.candidate is None


def test_select_runtime_clue_requires_npc_alias_and_prerequisite():
    from src.server.engine.runtime_reveal_conditions import select_runtime_clue

    missing_prerequisite = select_runtime_clue(
        _runtime_package(),
        "night-market",
        "dialogue",
        "我向钟师傅追问寄存牌上的刻痕。",
        set(),
    )
    wrong_action = select_runtime_clue(
        _runtime_package(),
        "night-market",
        "dialogue",
        "我观察钟师傅的修表工具。",
        {"brass-token"},
    )
    discovered = select_runtime_clue(
        _runtime_package(),
        "night-market",
        "dialogue",
        "我向钟师傅追问寄存牌上的刻痕。",
        {"brass-token"},
    )

    assert missing_prerequisite.candidate is None
    assert wrong_action.candidate is None
    assert discovered.candidate is not None
    assert discovered.candidate.canonical_id == "token-scratch"


def test_select_runtime_clue_requires_public_item_for_research():
    from src.server.engine.runtime_reveal_conditions import select_runtime_clue

    missing_item = select_runtime_clue(
        _runtime_package(),
        "archive-reading-room",
        "dialogue",
        "我查阅这里的材料。",
        set(),
    )
    discovered = select_runtime_clue(
        _runtime_package(),
        "archive-reading-room",
        "dialogue",
        "我查阅市政档案里的封存索引。",
        set(),
    )

    assert missing_item.candidate is None
    assert discovered.candidate is not None
    assert discovered.candidate.canonical_id == "sealed-blueprint"


def test_select_runtime_clue_uses_core_priority_then_stable_order():
    from src.server.engine.runtime_reveal_conditions import select_runtime_clue

    first = select_runtime_clue(
        _runtime_package(),
        "lost-property-counter",
        "dialogue",
        "我检查柜台上的物件。",
        set(),
    )
    second = select_runtime_clue(
        _runtime_package(),
        "lost-property-counter",
        "dialogue",
        "我检查柜台上的物件。",
        {"brass-token"},
    )

    assert first.candidate is not None
    assert first.candidate.canonical_id == "brass-token"
    assert second.candidate is not None
    assert second.candidate.canonical_id == "altered-claim-log"


def test_select_runtime_clue_allows_preserved_failure_only_when_declared():
    from src.server.engine.runtime_reveal_conditions import select_runtime_clue

    preserved = select_runtime_clue(
        _runtime_package(),
        "lost-property-counter",
        "dialogue",
        "我检查柜台上的物件。",
        set(),
        allow_failure_preservation=True,
    )
    non_preserved = select_runtime_clue(
        _runtime_package(),
        "archive-reading-room",
        "dialogue",
        "我查阅市政档案里的封存索引。",
        set(),
        allow_failure_preservation=True,
    )

    assert preserved.candidate is not None
    assert preserved.candidate.canonical_id == "brass-token"
    assert non_preserved.candidate is None


def test_select_runtime_clue_rejects_unknown_condition_kind():
    from src.server.engine.runtime_reveal_conditions import select_runtime_clue

    runtime_package = _runtime_package()
    runtime_package["clue_dependencies"] = [
        {
            "clue_id": "unknown",
            "name": "未知条件线索",
            "public_version": "不会展示。",
            "location": "失物局柜台",
            "reveal_conditions": [
                {"kind": "unsupported_kind", "scene_id": "lost-property-counter"}
            ],
            "prerequisite_fact_refs": [],
        }
    ]

    selection = select_runtime_clue(
        runtime_package,
        "lost-property-counter",
        "dialogue",
        "我调查柜台。",
        set(),
    )

    assert selection.candidate is None
    assert selection.rejected_condition_kinds == ("unsupported_kind",)


def test_all_golden_module_reveal_condition_kinds_are_supported():
    from src.server.engine.runtime_reveal_conditions import (
        SUPPORTED_REVEAL_CONDITION_KINDS,
    )

    project_root = Path(__file__).resolve().parents[2]
    kinds = {
        str(condition.get("kind") or "")
        for path in (project_root / "data" / "golden_modules").glob("*/module.json")
        for clue in json.loads(path.read_text(encoding="utf-8"))["knowledge_graph"].get("clues", [])
        if isinstance(clue, dict)
        for condition in clue.get("reveal_conditions") or []
        if isinstance(condition, dict)
    }

    assert kinds
    assert kinds <= SUPPORTED_REVEAL_CONDITION_KINDS
