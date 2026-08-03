import json

import pytest

from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.engine.state_service import StateService
from src.server.models import ActionDraftDTO, MechanicCompileResult, PlayerIntent, ResolutionResult
from src.server.player import router_actions_v2
from src.server.player.action_service import submit_coc_followup_decision
from src.server.scenario.content_projection import ContentProjectionService
from src.server.scenario import solo_runtime
from src.server.scenario.solo_runtime import SoloAdventureRuntime, SoloTransitionError


def _setup_solo_room(conn) -> tuple[str, str]:
    scenario_id = "solo-runtime-scenario"
    scenario_version_id = "solo-runtime-version"
    room_id = "solo-runtime-room"
    graph = {
        "solo_adventure": {
            "root_node_id": "1",
            "integrity": {"is_valid": True},
            "nodes": [
                {
                    "node_id": "1",
                    "title": "条目 1",
                    "text": "车站。",
                    "target_node_ids": ["2"],
                    "citation": {"page_number": 1},
                },
                {
                    "node_id": "2",
                    "title": "条目 2",
                    "text": "长途车。",
                    "target_node_ids": ["3"],
                    "citation": {"page_number": 2},
                },
                {
                    "node_id": "3",
                    "title": "条目 3",
                    "text": "黑熊的敏捷为58，生命值为20。它会用爪击攻击，战斗持续三轮。",
                    "target_node_ids": ["4"],
                    "citation": {"page_number": 3},
                },
                {
                    "node_id": "4",
                    "title": "条目 4",
                    "text": "你成功逃离危险。\n【剧终】",
                    "target_node_ids": [],
                    "citation": {"page_number": 4},
                },
            ],
        }
    }
    conn.execute(
        "INSERT INTO scenarios (scenario_id, title, knowledge_graph) VALUES (%s, %s, %s)",
        (scenario_id, "运行时测试", json.dumps(graph)),
    )
    conn.execute(
        """
        INSERT INTO scenario_versions (
            scenario_version_id, scenario_id, version_number, status,
            knowledge_graph, quality_report, prep_package, created_by
        ) VALUES (%s, %s, 1, 'published', %s, %s, %s, 'test-admin')
        """,
        (scenario_version_id, scenario_id, json.dumps(graph), json.dumps({}), json.dumps({})),
    )
    conn.execute(
        "INSERT INTO rooms (room_id, scenario_id, scenario_version_id, owner_token) "
        "VALUES (%s, %s, %s, 'owner-token')",
        (room_id, scenario_id, scenario_version_id),
    )
    ContentProjectionService(conn).rebuild(
        scenario_version_id, graph, requested_by="test-admin"
    )
    return room_id, scenario_version_id


def test_runtime_initializes_root_and_applies_explicit_transition(test_db):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    runtime = SoloAdventureRuntime(test_db)

    initial = runtime.current(room_id)
    result = runtime.transition(room_id, from_node_id="1", target_node_id="2")
    current = runtime.current(room_id)

    assert initial["node_id"] == "1"
    assert initial["scenario_version_id"] == scenario_version_id
    assert result["from_node_id"] == "1"
    assert result["target_node_id"] == "2"
    assert result["citation"]["page_number"] == 1
    assert current["node_id"] == "2"
    state = test_db.execute(
        "SELECT current_scene, visited_scenes FROM room_scene_state WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    assert state["current_scene"] == "solo:2"
    assert state["visited_scenes"] == ["solo:1", "solo:2"]


def test_runtime_transition_merges_source_backed_scene_variables(test_db):
    room_id, _ = _setup_solo_room(test_db)
    runtime = SoloAdventureRuntime(test_db)

    runtime.transition(
        room_id,
        from_node_id="1",
        target_node_id="2",
        scene_variables={"solo_skill_bonus_dice": -1},
    )

    assert runtime.current(room_id)["scene_variables"] == {
        "solo_adventure_version": "solo-runtime-version",
        "solo_skill_bonus_dice": -1,
    }


def test_runtime_rejects_stale_or_non_explicit_transition(test_db):
    room_id, _ = _setup_solo_room(test_db)
    runtime = SoloAdventureRuntime(test_db)

    with pytest.raises(SoloTransitionError, match="solo_transition_not_allowed"):
        runtime.transition(room_id, from_node_id="1", target_node_id="9")
    runtime.transition(room_id, from_node_id="1", target_node_id="2")
    with pytest.raises(SoloTransitionError, match="solo_transition_stale"):
        runtime.transition(room_id, from_node_id="1", target_node_id="2")


def test_extracts_source_backed_hunting_knife_purchase():
    purchase = solo_runtime.extract_solo_item_purchase(
        {
            "node_id": "16",
            "text": "商店里没有武器，只有一把积满尘土的狩猎小刀，如果想要，你可以买下它。然后转到25。",
            "target_node_ids": ["25"],
            "citation": {"page_number": 7},
        },
        "我买下那把积满灰尘的狩猎小刀，把它收进旅行箱。",
    )

    assert purchase == {
        "from_node_id": "16",
        "target_node_id": "25",
        "name": "狩猎小刀",
        "description": "从剧本场景中购买的狩猎小刀。",
        "source": "scenario_purchase:16",
        "citation": {"page_number": 7},
    }


def test_extracts_visible_solo_skill_check_with_success_and_failure_targets():
    rule = solo_runtime.extract_solo_skill_check(
        {
            "node_id": "134",
            "text": (
                "现在你必须要进行一次敏捷检定。"
                "如果你通过了“敏捷”检定，转到261。"
                "如果你没有通过“敏捷”检定，转到59。"
            ),
            "citation": {"page_number": 28},
            "target_node_ids": ["261", "59"],
        }
    )

    assert rule == {
        "skill_name": "敏捷",
        "difficulty": "regular",
        "from_node_id": "134",
        "success_target_node_id": "261",
        "failure_target_node_id": "59",
        "citation": {"page_number": 28},
    }


def test_extracts_named_solo_skill_check_with_success_and_failure_targets():
    rule = solo_runtime.extract_solo_skill_check(
        {
            "node_id": "121",
            "text": (
                "要抓住你的目标，你必须进行一次「追踪」检定。"
                "如果你成功了，转到141。如果你失败了，转到130。"
            ),
            "citation": {"page_number": 26},
            "target_node_ids": ["141", "130"],
        },
        "我沿着脚印和泥迹追踪那个身影。",
    )

    assert rule == {
        "skill_name": "追踪",
        "difficulty": "regular",
        "from_node_id": "121",
        "success_target_node_id": "141",
        "failure_target_node_id": "130",
        "citation": {"page_number": 26},
    }


def test_extracts_named_solo_skill_check_with_else_failure_target():
    rule = solo_runtime.extract_solo_skill_check(
        {
            "node_id": "178",
            "text": (
                "进行一次「侦查」检定。"
                "如果你成功了，转\n到112。否则转\n到192。"
            ),
            "citation": {"page_number": 36},
            "target_node_ids": ["112", "192"],
        },
        "我查看悬崖下方是否留下可疑痕迹。",
    )

    assert rule == {
        "skill_name": "侦查",
        "difficulty": "regular",
        "from_node_id": "178",
        "success_target_node_id": "112",
        "failure_target_node_id": "192",
        "citation": {"page_number": 36},
    }


def test_solo_transition_narration_removes_lone_import_marker():
    narration = ResolutionPipeline._render_solo_scene_narrative(
        {
            "node_id": "192",
            "title": "条目 192",
            "text": "七宫\n你已经厌倦自己拖动沉重的行李了。",
            "target_node_ids": [],
        }
    )

    assert "七宫" not in narration


def test_solo_transition_narration_removes_inline_import_marker():
    narration = ResolutionPipeline._render_solo_scene_narrative(
        {
            "node_id": "192",
            "title": "条目 192",
            "text": "七宫涟个人汉 你已经厌倦自己拖动沉重的行李了。",
            "target_node_ids": [],
        }
    )

    assert "七宫" not in narration
    assert "个人汉" not in narration
    assert "你已经厌倦自己拖动沉重的行李了。" in narration


def test_solo_transition_narration_removes_inline_short_import_marker():
    narration = ResolutionPipeline._render_solo_scene_narrative(
        {
            "node_id": "5",
            "title": "条目 5",
            "text": "七宫 这些野兽成扇形面对你排开阵势。",
            "target_node_ids": [],
        }
    )

    assert "七宫" not in narration
    assert "这些野兽成扇形面对你排开阵势。" in narration


def test_player_safe_solo_narration_hides_rules_and_entry_navigation():
    narration = solo_runtime.render_player_safe_solo_narrative(
        {
            "node_id": "201",
            "text": (
                "熊退后几步，漆黑的眼珠直瞪着你。它从喉咙深处发出低沉的咕哝声，"
                "转头蹒跚返回了树林。你可以在你的「格斗（斗殴）」技能左边的小方框里打勾。"
                "如果熊击伤了你，还可以尝试进行一次「急救」检定。现在转到79。"
            ),
        }
    )

    assert "熊退后几步" in narration
    assert "方框" not in narration
    assert "急救" not in narration
    assert "79" not in narration
    assert "你准备怎么做？" in narration


def test_extracts_fixed_solo_healing_on_a_visible_transition():
    rule = solo_runtime.extract_solo_fixed_healing(
        {
            "node_id": "13",
            "text": "你在失去意识时接受了急救，可以回复1点生命值。现在转到64。",
            "target_node_ids": ["64"],
            "citation": {"page_number": 12},
        }
    )

    assert rule == {
        "from_node_id": "13",
        "target_node_id": "64",
        "amount": 1,
        "citation": {"page_number": 12},
    }


def test_extracts_sleep_recovery_when_ocr_places_amount_after_hp_label():
    rule = solo_runtime.extract_solo_fixed_healing(
        {
            "node_id": "154",
            "text": "你之前如果受过伤害，睡过这一晚之后可以回复点生命值。1现在转到166。",
            "target_node_ids": ["166"],
            "citation": {"page_number": 32},
        }
    )

    assert rule == {
        "from_node_id": "154",
        "target_node_id": "166",
        "amount": 1,
        "citation": {"page_number": 32},
    }


def test_extracts_daily_penalty_die_on_visible_transition():
    rule = solo_runtime.extract_solo_daily_penalty_die(
        {
            "node_id": "26",
            "text": (
                "今天你的技能检定获得一颗惩罚骰。额外投一颗十位骰，"
                "分别计算结果后取最高值。这不影响幸运、理智和伤害检定。现在转到64。"
            ),
            "target_node_ids": ["64"],
            "citation": {"page_number": 9},
        }
    )

    assert rule == {
        "from_node_id": "26",
        "target_node_id": "64",
        "bonus_dice": -1,
        "citation": {"page_number": 9},
    }


def test_extracts_fixed_solo_sanity_loss_on_a_visible_transition():
    rule = solo_runtime.extract_solo_fixed_sanity_loss(
        {
            "node_id": "5",
            "text": "浓烟让你透不过气。失去1D3点理智值。转到13。",
            "target_node_ids": ["13"],
            "citation": {"page_number": 5},
        }
    )

    assert rule == {
        "from_node_id": "5",
        "target_node_id": "13",
        "loss_dice": "1d3",
        "citation": {"page_number": 5},
    }


def test_extracts_solo_damage_transition_from_fixed_fall_consequence():
    rule = solo_runtime.extract_solo_damage_transition(
        {
            "node_id": "55",
            "text": (
                "你撞上地面时受到2D6点伤害。如果这次2D6伤害的数值大于等于"
                "你最大生命值的一半，转到67。否则，转到73。"
            ),
            "target_node_ids": ["67", "73"],
            "citation": {"page_number": 11},
        }
    )

    assert rule == {
        "from_node_id": "55",
        "high_damage_target_node_id": "67",
        "low_damage_target_node_id": "73",
        "damage_dice": "2d6",
        "citation": {"page_number": 11},
    }


def test_extracts_solo_damage_transition_that_ends_on_zero_hp():
    rule = solo_runtime.extract_solo_damage_transition(
        {
            "node_id": "93",
            "text": (
                "你因为火焰受到点生命值伤害。"
                "如果1D6你的生命值因此归零，你会被烈焰烧死！【剧终】。否则，转到137。"
            ),
            "target_node_ids": ["137"],
            "citation": {"page_number": 19},
        }
    )

    assert rule == {
        "from_node_id": "93",
        "target_node_id": "137",
        "damage_dice": "1d6",
        "damage_ends_on_zero": True,
        "citation": {"page_number": 19},
    }


def test_extracts_fixed_solo_hp_loss_before_a_single_transition():
    rule = solo_runtime.extract_solo_fixed_damage(
        {
            "node_id": "59",
            "text": (
                "你在这次事件中损失了 点生命值。在 1 (HP)"
                "你的调查员角色卡上标记出损失。现在转到71。"
            ),
            "target_node_ids": ["71"],
            "citation": {"page_number": 15},
        }
    )

    assert rule == {
        "from_node_id": "59",
        "target_node_id": "71",
        "amount": 1,
        "citation": {"page_number": 15},
    }


def test_infers_visible_solo_choice_from_natural_language_intent():
    target = solo_runtime.infer_visible_solo_target(
        {
            "target_node_ids": ["11", "28"],
            "text": (
                "如果你稍作准备出村去，转到28。"
                "如果你转而造访村会堂，转到11。"
            ),
        },
        "我先准备一点干粮，然后趁天色尚早离开烬头村。",
    )

    assert target == "28"


def test_infers_refusal_choice_when_player_negates_drinking():
    target = solo_runtime.infer_visible_solo_target(
        {
            "target_node_ids": ["104", "113"],
            "text": "要接受饮料，转到104。要拒绝，转到113。",
        },
        "我不喝她递来的饮料，扭头把杯子撞翻在地。",
    )

    assert target == "113"


def test_infers_silence_choice_when_player_declines_to_question_a_character():
    target = solo_runtime.infer_visible_solo_target(
        {
            "target_node_ids": ["22", "15", "9"],
            "text": (
                "如果你要问露丝她说的是什么意思，转到9。"
                "如果你要问梅露丝说的是什么意思，转到15。"
                "如果你一言不发，转到22。"
            ),
        },
        "我没有当着梅追问露丝的悄悄话，装作若无其事，接受邀请。",
    )

    assert target == "22"


def test_infers_specific_subject_over_shared_npc_name():
    target = solo_runtime.infer_visible_solo_target(
        {
            "target_node_ids": ["49", "56"],
            "text": "要立即询问电报的事，转到56。要先和文特斯先生先聊聊，转到49。",
        },
        "我注意到桌上的电报机，立刻询问文特斯先生它是否能联络外界。",
    )

    assert target == "56"


def test_ignores_unrelated_absence_when_matching_a_specific_location():
    target = solo_runtime.infer_visible_solo_target(
        {
            "target_node_ids": ["29", "83"],
            "text": "搜索梅·莱德贝特的卧室，转到83。窥探灯塔前的活动，转到29。",
        },
        "趁梅和露丝不在家，我谨慎地搜索梅·莱德贝特的卧室，寻找与灯塔有关的书信。",
    )

    assert target == "83"


def test_infers_otherwise_branch_when_player_negates_condition():
    target = solo_runtime.infer_otherwise_solo_target(
        {
            "target_node_ids": ["70", "78"],
            "text": "如果你昨天夜里卷入了一场战斗，并想进一步勘查其后果，转到70。否则，转到78。",
        },
        "我昨夜没有和人近战，也没有可回去勘查的战斗现场。",
    )

    assert target == "78"


def test_infers_wrapped_otherwise_branch_when_player_declines_investigation():
    target = solo_runtime.infer_otherwise_solo_target(
        {
            "target_node_ids": ["70", "78"],
            "text": "如果你昨天夜里卷入了一场战斗，并想进\n一步勘查其后果，转到70。否则，转到78。",
        },
        "我暂时不回头勘查昨夜的战斗，离开这里继续观察村庄。",
    )

    assert target == "78"


def test_infers_otherwise_branch_when_player_leaves_instead_of_optional_investigation():
    target = solo_runtime.infer_otherwise_solo_target(
        {
            "target_node_ids": ["178", "192"],
            "text": (
                "如果你昨晚曾在技能检定中成功过，并想进一步勘查后果，转到178。"
                "否则，转到192。"
            ),
        },
        "我告别梅，出门寻找长途车。",
    )

    assert target == "192"


def test_extracts_extreme_difficulty_from_named_solo_skill_check():
    rule = solo_runtime.extract_solo_skill_check(
        {
            "node_id": "110",
            "target_node_ids": ["143", "129", "149"],
            "citation": {"page_number": 22},
            "text": (
                "进行一次极难难度的「潜行」检定。"
                "如果你成功了，转到143。如果你失败了，转到129。"
                "如果你投出结果大于等于96，这是一次大失败：转到149。"
            ),
        },
        "我躲在树后观察熊。",
    )

    assert rule is not None
    assert rule["skill_name"] == "潜行"
    assert rule["difficulty"] == "extreme"


def test_extracts_difficult_named_skill_check_when_condition_wraps_lines():
    rule = solo_runtime.extract_solo_skill_check(
        {
            "node_id": "79",
            "target_node_ids": ["240", "234"],
            "citation": {"page_number": 19},
            "text": (
                "进行一次困难难度的「聆听」检定。如果你\n"
                "成功了，转到240。如果你失败了，转到234。"
            ),
        },
        "我停下来倾听树林里的声音。",
    )

    assert rule is not None
    assert rule["skill_name"] == "聆听"
    assert rule["difficulty"] == "hard"
    assert rule["success_target_node_id"] == "240"
    assert rule["failure_target_node_id"] == "234"


def test_extracts_sanity_check_without_explicit_loss_as_zero_loss():
    rule = solo_runtime.extract_solo_skill_check(
        {
            "node_id": "264",
            "target_node_ids": ["269", "5"],
            "citation": {"page_number": 52},
            "text": "进行一次“理智”检定。如果你成功了，转到269。如果你失败了，转到5。",
        },
        "我试着稳住心神。",
    )

    assert rule is not None
    assert rule["mechanic"] == "sanity_check"
    assert rule["success_target_node_id"] == "269"
    assert rule["failure_target_node_id"] == "5"
    assert rule["success_loss"] == "0"
    assert rule["failure_loss"] == "0"


def test_extracts_solo_sanity_check_with_failure_loss_and_single_target():
    rule = solo_runtime.extract_solo_skill_check(
        {
            "node_id": "141",
            "text": (
                "进行一次“理智”检定。如果你失败了，失去点理智值。"
                "你可以使用普通六面骰来投掷：1D2。"
                "你沿路返回莱德贝特的房子。转到63。"
            ),
            "citation": {"page_number": 29},
            "target_node_ids": ["63"],
        },
        "我强迫自己冷静下来，直视刚才的一幕，然后返回梅的家。",
    )

    assert rule == {
        "mechanic": "sanity_check",
        "skill_name": "理智",
        "difficulty": "regular",
        "from_node_id": "141",
        "target_node_id": "63",
        "success_loss": "0",
        "failure_loss": "1d2",
        "citation": {"page_number": 29},
    }


def test_visible_solo_sanity_check_creates_player_confirmation(test_db):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    graph = {
        "solo_adventure": {
            "root_node_id": "141",
            "integrity": {"is_valid": True},
            "nodes": [
                {
                    "node_id": "141",
                    "title": "悬崖",
                    "text": (
                        "进行一次“理智”检定。如果你失败了，失去点理智值。"
                        "你可以使用普通六面骰来投掷：1D2。"
                        "你沿路返回莱德贝特的房子。转到63。"
                    ),
                    "target_node_ids": ["63"],
                    "citation": {"page_number": 29},
                },
                {
                    "node_id": "63",
                    "title": "归来",
                    "text": "你回到屋里。",
                    "target_node_ids": [],
                    "citation": {"page_number": 30},
                },
            ],
        }
    }
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps(graph, ensure_ascii=False), scenario_version_id),
    )
    ContentProjectionService(test_db).rebuild(
        scenario_version_id, graph, requested_by="test-admin"
    )
    draft = ActionDraftDTO(
        intent_type="dialogue",
        declared_intent="我强迫自己冷静下来，直视刚才的一幕，然后返回梅的家。",
        understanding_summary="你想压下恐惧并返回屋里",
        risk="low",
        confidence=0.7,
        analysis_source="local_fallback",
        resolution_route="local",
    )

    result = router_actions_v2._apply_visible_solo_skill_check(
        test_db, {"room_id": room_id, "xlsx_data": {}}, draft
    )

    assert result.intent_type == "skill_check"
    assert result.suggested_skill == "理智"
    assert result.params["solo_adventure_check"] == {
        "mechanic": "sanity_check",
        "fromNodeId": "141",
        "targetNodeId": "63",
        "successLoss": "0",
        "failureLoss": "1d2",
        "citation": {"page_number": 29},
    }


def test_extracts_selected_skill_from_visible_choice_check():
    rule = solo_runtime.extract_solo_skill_check(
        {
            "node_id": "144",
            "text": (
                "你必须选择使用「汽车驾驶」或「心理学」进行一次检定。"
                "如果你在「汽车驾驶」的检定成功，转到174。"
                "如果你在「心理学」的检定获得困难成功，转到162。"
                "如果你的检定失败，转到194。"
            ),
            "target_node_ids": ["194", "162", "174"],
            "citation": {"page_number": 30},
        },
        "我使用心理学进行一次困难检定。",
    )

    assert rule == {
        "skill_name": "心理学",
        "difficulty": "hard",
        "from_node_id": "144",
        "success_target_node_id": "162",
        "failure_target_node_id": "194",
        "citation": {"page_number": 30},
    }


def test_extracts_vehicle_skill_from_natural_engine_inspection():
    rule = solo_runtime.extract_solo_skill_check(
        {
            "node_id": "144",
            "text": (
                "你必须选择使用「汽车驾驶」或「心理学」进行一次检定。"
                "如果你在「汽车驾驶」的检定成功，转到174。"
                "如果你在「心理学」的检定获得困难成功，转到162。"
                "如果你的检定失败，转到194。"
            ),
            "target_node_ids": ["194", "162", "174"],
            "citation": {"page_number": 30},
        },
        "我下车查看发动机，试着判断长途车究竟哪里出了故障。",
    )

    assert rule == {
        "skill_name": "汽车驾驶",
        "difficulty": "regular",
        "from_node_id": "144",
        "success_target_node_id": "174",
        "failure_target_node_id": "194",
        "citation": {"page_number": 30},
    }


def test_extracts_damage_before_skill_check_from_solo_scene():
    rule = solo_runtime.extract_solo_skill_check(
        {
            "node_id": "65",
            "text": (
                "你因为火焰受到1D6点生命值伤害。如果你的生命值归零，你会被烧死。"
                "否则，进行一次“力量”检定。如果你成功了，转到93。如果你失败了，转到77。"
            ),
            "target_node_ids": ["93", "77"],
            "citation": {"page_number": 40},
        },
        "我忍着火焰继续拉扯锁链。",
    )

    assert rule["damage_dice"] == "1d6"
    assert rule["damage_ends_on_zero"] is True


def test_solo_damage_is_added_to_skill_resolution(monkeypatch):
    resolution = ResolutionResult(
        actionId="fire-action",
        roomId="fire-room",
        characterId="fire-character",
        mechanic="skill_check",
        isSuccess=True,
        metadata={"skill_name": "力量"},
    )
    monkeypatch.setattr(
        "src.server.rules.coc_handlers.secure_randint",
        lambda *_args, **_kwargs: 4,
    )

    result = ResolutionPipeline._apply_solo_damage(
        resolution,
        {"xlsx_data": {"hp": 9}},
        "1d6",
    )

    assert result == {"damage": 4, "hp_before": 9, "hp_after": 5}
    assert resolution.mutations == [
        {"op": "replace", "path": "/character/hp", "value": 5}
    ]
    assert resolution.reveal_steps[0]["kind"] == "damage"


def test_solo_fixed_damage_updates_hp_without_a_dice_roll():
    resolution = ResolutionResult(
        actionId="fixed-damage-action",
        roomId="fixed-damage-room",
        characterId="fixed-damage-character",
        mechanic="move",
        isSuccess=True,
    )

    result = ResolutionPipeline._apply_solo_fixed_damage(
        resolution,
        {"xlsx_data": {"hp": 9}},
        1,
    )

    assert result == {"damage": 1, "hp_before": 9, "hp_after": 8}
    assert resolution.mutations == [
        {"op": "replace", "path": "/character/hp", "value": 8}
    ]
    assert resolution.reveal_steps == [{"kind": "damage", "amount": 1}]


def test_fixed_solo_damage_does_not_create_a_roll_receipt():
    resolution = ResolutionResult(
        actionId="fixed-damage-receipt",
        roomId="fixed-damage-room",
        characterId="fixed-damage-character",
        mechanic="move",
        isSuccess=True,
        revealSteps=[{"kind": "damage", "amount": 1}],
    )

    assert ResolutionPipeline._raw_rolls(resolution) == []


def test_visible_solo_skill_check_discloses_fire_damage(test_db):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    graph = {
        "solo_adventure": {
            "root_node_id": "65",
            "integrity": {"is_valid": True},
            "nodes": [
                {
                    "node_id": "65",
                    "title": "火焰",
                    "text": (
                        "你因为火焰受到1D6点生命值伤害。如果你的生命值归零，你会被烧死。"
                        "否则，进行一次“力量”检定。如果你成功了，转到93。如果你失败了，转到77。"
                    ),
                    "target_node_ids": ["93", "77"],
                    "citation": {"page_number": 40},
                },
                {"node_id": "93", "title": "脱困", "text": "成功。", "target_node_ids": []},
                {"node_id": "77", "title": "失败", "text": "失败。", "target_node_ids": []},
            ],
        }
    }
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps(graph, ensure_ascii=False), scenario_version_id),
    )
    ContentProjectionService(test_db).rebuild(
        scenario_version_id, graph, requested_by="test-admin"
    )
    draft = ActionDraftDTO(
        intent_type="action",
        declared_intent="我忍着剧痛继续拉扯锁链。",
        understanding_summary="继续挣脱",
        risk="medium",
        confidence=0.8,
        analysis_source="local_fallback",
    )

    result = router_actions_v2._apply_visible_solo_skill_check(
        test_db, {"room_id": room_id, "xlsx_data": {}}, draft
    )

    assert result.risk == "high"
    assert result.resource_impacts == [{"resource": "hp", "label": "生命", "dice": "1d6"}]
    assert result.confirmation_requirements == ["damage", "dice_roll", "state_change"]
    assert result.params["solo_adventure_check"]["damageDice"] == "1d6"
    rule, error = ResolutionPipeline(test_db)._validated_solo_skill_check(
        room_id,
        {
            "skillName": "力量",
            "difficulty": "regular",
            "solo_adventure_check": result.params["solo_adventure_check"],
        },
        "我忍着剧痛继续拉扯锁链。",
    )

    assert error is None
    assert rule["damage_ends_on_zero"] is True


def test_validates_selected_skill_choice_with_declared_intent(test_db):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    graph = {
        "solo_adventure": {
            "root_node_id": "144",
            "integrity": {"is_valid": True},
            "nodes": [
                {
                    "node_id": "144",
                    "title": "长途车故障",
                    "text": (
                        "你必须选择使用「汽车驾驶」或「心理学」进行一次检定。"
                        "如果你在「汽车驾驶」的检定成功，转到174。"
                        "如果你在「心理学」的检定获得困难成功，转到162。"
                        "如果你的检定失败，转到194。"
                    ),
                    "target_node_ids": ["194", "162", "174"],
                    "citation": {"page_number": 30},
                },
                {"node_id": "162", "title": "洞察", "text": "成功。", "target_node_ids": [], "citation": {"page_number": 31}},
                {"node_id": "174", "title": "修好", "text": "成功。", "target_node_ids": [], "citation": {"page_number": 31}},
                {"node_id": "194", "title": "失败", "text": "失败。", "target_node_ids": [], "citation": {"page_number": 31}},
            ],
        }
    }
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps(graph, ensure_ascii=False), scenario_version_id),
    )
    ContentProjectionService(test_db).rebuild(
        scenario_version_id, graph, requested_by="test-admin"
    )

    rule, error = ResolutionPipeline(test_db)._validated_solo_skill_check(
        room_id,
            {
                "skillName": "心理学",
                "difficulty": "hard",
                "solo_adventure_check": {
                "fromNodeId": "144",
                "successTargetNodeId": "162",
                "failureTargetNodeId": "194",
            },
        },
        "我使用心理学进行一次困难检定。",
    )

    assert error is None
    assert rule["skill_name"] == "心理学"
    assert rule["difficulty"] == "hard"


def test_visible_single_target_transition_keeps_returning_a_draft(test_db):
    room_id, _ = _setup_solo_room(test_db)
    draft = ActionDraftDTO(
        intent_type="dialogue",
        declared_intent="我准备继续前进。",
        understanding_summary="你想继续前进",
        risk="low",
        confidence=0.7,
        analysis_source="local_fallback",
        resolution_route="local",
    )

    result = router_actions_v2._apply_visible_solo_transition(
        test_db,
        {"room_id": room_id, "xlsx_data": {}},
        draft,
    )

    assert result.intent_type == "move"
    assert result.params["fromNodeId"] == "1"
    assert result.params["targetNodeId"] == "2"


def test_visible_solo_skill_check_creates_player_confirmation(test_db):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    graph = {
        "solo_adventure": {
            "root_node_id": "1",
            "integrity": {"is_valid": True},
            "nodes": [
                {
                    "node_id": "1",
                    "title": "急弯",
                    "text": (
                        "长途车突然急转弯。现在你必须要进行一次敏捷检定。"
                        "如果你通过了“敏捷”检定，转到2。"
                        "如果你没有通过“敏捷”检定，转到3。"
                    ),
                    "target_node_ids": ["2", "3"],
                    "citation": {"page_number": 1},
                },
                {
                    "node_id": "2",
                    "title": "站稳",
                    "text": "你稳住了身体。",
                    "target_node_ids": [],
                    "citation": {"page_number": 2},
                },
                {
                    "node_id": "3",
                    "title": "摔倒",
                    "text": "你失去平衡。",
                    "target_node_ids": [],
                    "citation": {"page_number": 3},
                },
            ],
        }
    }
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps(graph, ensure_ascii=False), scenario_version_id),
    )
    ContentProjectionService(test_db).rebuild(
        scenario_version_id, graph, requested_by="test-admin"
    )
    character = {
        "character_id": "solo-check-character",
        "room_id": room_id,
        "xlsx_data": {"attributes": {"dex": 60}},
    }
    draft = ActionDraftDTO(
        intent_type="dialogue",
        declared_intent="我抓紧扶手，压低重心稳住身体。",
        understanding_summary="你想在急弯中保持平衡",
        risk="low",
        confidence=0.7,
        analysis_source="local_fallback",
        resolution_route="local",
    )

    result = router_actions_v2._apply_visible_solo_skill_check(test_db, character, draft)

    assert result.intent_type == "skill_check"
    assert result.suggested_skill == "敏捷"
    assert result.requires_confirmation is True
    assert result.confirmation_requirements == ["dice_roll", "state_change"]
    assert result.params["solo_adventure_check"] == {
        "fromNodeId": "1",
        "successTargetNodeId": "2",
        "failureTargetNodeId": "3",
        "citation": {"page_number": 1},
    }


def test_visible_solo_skill_check_applies_active_source_penalty_die(test_db):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    graph = {
        "solo_adventure": {
            "root_node_id": "1",
            "integrity": {"is_valid": True},
            "nodes": [
                {
                    "node_id": "1",
                    "title": "阴影",
                    "text": (
                        "你听见墙角有响动。进行一次“侦查”检定。"
                        "如果你通过了“侦查”检定，转到2。"
                        "如果你没有通过“侦查”检定，转到3。"
                    ),
                    "target_node_ids": ["2", "3"],
                    "citation": {"page_number": 1},
                },
                {"node_id": "2", "title": "发现", "text": "你发现了异常。", "target_node_ids": []},
                {"node_id": "3", "title": "错过", "text": "响动消失了。", "target_node_ids": []},
            ],
        }
    }
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps(graph, ensure_ascii=False), scenario_version_id),
    )
    ContentProjectionService(test_db).rebuild(
        scenario_version_id, graph, requested_by="test-admin"
    )
    test_db.execute(
        "INSERT INTO room_scene_state (room_id, current_scene, visited_scenes, scene_variables, version) "
        "VALUES (%s, 'solo:1', '[]', %s, 1)",
        (room_id, json.dumps({"solo_skill_bonus_dice": -1})),
    )
    draft = ActionDraftDTO(
        intent_type="dialogue",
        declared_intent="我仔细搜索墙角，找出刚才发出响动的东西。",
        understanding_summary="你想找出响动的来源",
        risk="low",
        confidence=0.7,
        analysis_source="local_fallback",
        resolution_route="local",
    )

    result = router_actions_v2._apply_visible_solo_skill_check(
        test_db,
        {"room_id": room_id, "xlsx_data": {"skills": {"侦查": 60}}},
        draft,
    )

    assert result.params["bonusDice"] == -1
    assert "惩罚骰" in result.understanding_summary
    assert {"resource": "rule", "label": "惩罚骰 1 颗"} in result.resource_impacts


def test_visible_solo_skill_check_preserves_preselected_transition(test_db):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    graph = {
        "solo_adventure": {
            "root_node_id": "1",
            "integrity": {"is_valid": True},
            "nodes": [
                {
                    "node_id": "1",
                    "title": "急弯后",
                    "text": (
                        "现在你必须要进行一次敏捷检定。"
                        "如果你通过了“敏捷”检定，转到2。"
                        "如果你没有通过“敏捷”检定，转到3。"
                    ),
                    "target_node_ids": ["2", "3"],
                    "citation": {"page_number": 1},
                },
                {
                    "node_id": "2",
                    "title": "继续",
                    "text": "你继续前进。",
                    "target_node_ids": [],
                    "citation": {"page_number": 2},
                },
                {
                    "node_id": "3",
                    "title": "摔倒",
                    "text": "你失去平衡。",
                    "target_node_ids": [],
                    "citation": {"page_number": 3},
                },
            ],
        }
    }
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps(graph, ensure_ascii=False), scenario_version_id),
    )
    ContentProjectionService(test_db).rebuild(
        scenario_version_id, graph, requested_by="test-admin"
    )
    draft = ActionDraftDTO(
        intent_type="move",
        declared_intent="我重新坐稳并继续乘车。",
        understanding_summary="你想沿当前唯一可见方向继续",
        risk="medium",
        confidence=0.9,
        analysis_source="local_fallback",
        resolution_route="local",
        params={"fromNodeId": "1", "targetNodeId": "2"},
    )

    result = router_actions_v2._apply_visible_solo_skill_check(
        test_db,
        {"room_id": room_id, "xlsx_data": {}},
        draft,
    )

    assert result.intent_type == "move"
    assert result.params == {"fromNodeId": "1", "targetNodeId": "2"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("roll_values", "expected_target"),
    [([2, 4], "2"), ([9, 9], "3")],
)
async def test_solo_skill_check_uses_attribute_roll_to_choose_outcome_target(
    test_db,
    monkeypatch,
    roll_values,
    expected_target,
):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    graph = {
        "solo_adventure": {
            "root_node_id": "1",
            "integrity": {"is_valid": True},
            "nodes": [
                {
                    "node_id": "1",
                    "title": "急弯",
                    "text": (
                        "现在你必须要进行一次敏捷检定。"
                        "如果你通过了“敏捷”检定，转到2。"
                        "如果你没有通过“敏捷”检定，转到3。"
                    ),
                    "target_node_ids": ["2", "3"],
                    "citation": {"page_number": 1},
                },
                {
                    "node_id": "2",
                    "title": "站稳",
                    "text": "你稳住了身体。",
                    "target_node_ids": [],
                    "citation": {"page_number": 2},
                },
                {
                    "node_id": "3",
                    "title": "摔倒",
                    "text": "你失去平衡。",
                    "target_node_ids": [],
                    "citation": {"page_number": 3},
                },
            ],
        }
    }
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps(graph, ensure_ascii=False), scenario_version_id),
    )
    ContentProjectionService(test_db).rebuild(
        scenario_version_id, graph, requested_by="test-admin"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-check-character', %s, '玩家', 'solo-check-token', %s)",
        (room_id, json.dumps({"attributes": {"dex": 60}}, ensure_ascii=False)),
    )
    test_db.execute(
        """
        INSERT INTO actions (
            action_id, room_id, character_id, draft_id, intent_type,
            declared_intent, params, status
        ) VALUES (%s, %s, 'solo-check-character', 'solo-check-draft', 'skill_check', %s, %s, 'queued')
        """,
        (
            "solo-check-action",
            room_id,
            "我抓紧扶手，压低重心稳住身体。",
            json.dumps(
                {
                    "skillName": "敏捷",
                    "difficulty": "regular",
                    "solo_adventure_check": {
                        "fromNodeId": "1",
                        "successTargetNodeId": "2",
                        "failureTargetNodeId": "3",
                        "citation": {"page_number": 1},
                    },
                    "director_plan": {
                        "context_version": 0,
                        "preconditions": [],
                        "permissions": [],
                        "state_patch": [],
                        "state_patch_authority": "advisory_only",
                    },
                },
                ensure_ascii=False,
            ),
        ),
    )
    rolls = iter(roll_values)
    monkeypatch.setattr(
        "src.server.engine.skill_check.random.randint",
        lambda _low, _high: next(rolls),
    )

    pipeline = ResolutionPipeline(
        test_db, compiler=_AutoSuccessCompiler(), dispatcher=_RecordingDispatcher()
    )
    result = await pipeline.resolve_action("solo-check-action")

    if expected_target == "3":
        assert result["status"] == "awaiting_player_choice"
        submit_coc_followup_decision(
            test_db,
            "solo-check-character",
            "solo-check-action",
            "decline",
            "solo-check-decline",
        )
        result = await pipeline.resolve_action("solo-check-action")

    assert result["status"] == "completed"
    assert result["result"]["metadata"]["solo_adventure_transition"]["target_node_id"] == expected_target
    assert result["result"]["metadata"]["target"] == 60
    assert SoloAdventureRuntime(test_db).current(room_id)["node_id"] == expected_target


@pytest.mark.asyncio
async def test_solo_sanity_check_applies_failure_loss_and_transitions(test_db, monkeypatch):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    graph = {
        "solo_adventure": {
            "root_node_id": "141",
            "integrity": {"is_valid": True},
            "nodes": [
                {
                    "node_id": "141",
                    "title": "悬崖",
                    "text": (
                        "进行一次“理智”检定。如果你失败了，失去点理智值。"
                        "你可以使用普通六面骰来投掷：1D2。"
                        "你沿路返回莱德贝特的房子。转到63。"
                    ),
                    "target_node_ids": ["63"],
                    "citation": {"page_number": 29},
                },
                {
                    "node_id": "63",
                    "title": "归来",
                    "text": "你回到屋里。",
                    "target_node_ids": [],
                    "citation": {"page_number": 30},
                },
            ],
        }
    }
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps(graph, ensure_ascii=False), scenario_version_id),
    )
    ContentProjectionService(test_db).rebuild(
        scenario_version_id, graph, requested_by="test-admin"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-sanity-character', %s, '玩家', 'solo-sanity-token', %s)",
        (room_id, json.dumps({"san": 1}, ensure_ascii=False)),
    )
    test_db.execute(
        """
        INSERT INTO actions (
            action_id, room_id, character_id, draft_id, intent_type,
            declared_intent, params, status
        ) VALUES (%s, %s, 'solo-sanity-character', 'solo-sanity-draft', 'skill_check', %s, %s, 'queued')
        """,
        (
            "solo-sanity-action",
            room_id,
            "我强迫自己冷静下来，直视刚才的一幕，然后返回梅的家。",
            json.dumps(
                {
                    "skillName": "理智",
                    "difficulty": "regular",
                    "solo_adventure_check": {
                        "mechanic": "sanity_check",
                        "fromNodeId": "141",
                        "targetNodeId": "63",
                        "successLoss": "0",
                        "failureLoss": "1d2",
                        "citation": {"page_number": 29},
                    },
                    "director_plan": {
                        "context_version": 0,
                        "preconditions": [],
                        "permissions": [],
                        "state_patch": [],
                        "state_patch_authority": "advisory_only",
                    },
                },
                ensure_ascii=False,
            ),
        ),
    )
    rolls = iter([100, 2])
    monkeypatch.setattr(
        "src.server.rules.coc_handlers.secure_randint",
        lambda *_args, **_kwargs: next(rolls),
    )
    state_service = StateService(test_db)
    state_service.initialize_character_state("solo-sanity-character", room_id)

    result = await ResolutionPipeline(
        test_db,
        compiler=_RejectingCompiler(),
        dispatcher=_RecordingDispatcher(),
        state_service=state_service,
    ).resolve_action("solo-sanity-action")

    assert result["status"] == "completed"
    assert result["result"]["metadata"]["san_loss"] == 2
    assert SoloAdventureRuntime(test_db).current(room_id)["node_id"] == "63"
    assert state_service.get_runtime_state("solo-sanity-character", room_id)["san"] == 0
    receipt = test_db.execute(
        "SELECT receipt FROM actions WHERE action_id = 'solo-sanity-action'"
    ).fetchone()["receipt"]
    assert receipt["state_before"]["san"] == 1
    assert receipt["state_after"]["san"] == 0


@pytest.mark.asyncio
async def test_solo_sanity_check_uses_success_outcome_transition(test_db, monkeypatch):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    graph = {
        "solo_adventure": {
            "root_node_id": "264",
            "integrity": {"is_valid": True},
            "nodes": [
                {
                    "node_id": "264",
                    "title": "夜间遭遇",
                    "text": "进行一次“理智”检定。如果你成功了，转到269。如果你失败了，转到5。",
                    "target_node_ids": ["269", "5"],
                    "citation": {"page_number": 52},
                },
                {
                    "node_id": "269",
                    "title": "保持清醒",
                    "text": "你强迫自己继续前进。",
                    "target_node_ids": [],
                    "citation": {"page_number": 53},
                },
                {
                    "node_id": "5",
                    "title": "恐惧蔓延",
                    "text": "你陷入恐慌。",
                    "target_node_ids": [],
                    "citation": {"page_number": 54},
                },
            ],
        }
    }
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps(graph, ensure_ascii=False), scenario_version_id),
    )
    ContentProjectionService(test_db).rebuild(
        scenario_version_id, graph, requested_by="test-admin"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-sanity-success-character', %s, '玩家', 'solo-sanity-success-token', %s)",
        (room_id, json.dumps({"san": 50}, ensure_ascii=False)),
    )
    test_db.execute(
        """
        INSERT INTO actions (
            action_id, room_id, character_id, draft_id, intent_type,
            declared_intent, params, status
        ) VALUES (%s, %s, 'solo-sanity-success-character', 'solo-sanity-success-draft', 'skill_check', %s, %s, 'queued')
        """,
        (
            "solo-sanity-success-action",
            room_id,
            "我强迫自己保持清醒，观察眼前的异状。",
            json.dumps(
                {
                    "skillName": "理智",
                    "difficulty": "regular",
                    "solo_adventure_check": {
                        "mechanic": "sanity_check",
                        "fromNodeId": "264",
                        "successTargetNodeId": "269",
                        "failureTargetNodeId": "5",
                        "successLoss": "0",
                        "failureLoss": "0",
                        "citation": {"page_number": 52},
                    },
                    "director_plan": {
                        "context_version": 0,
                        "preconditions": [],
                        "permissions": [],
                        "state_patch": [],
                        "state_patch_authority": "advisory_only",
                    },
                },
                ensure_ascii=False,
            ),
        ),
    )
    monkeypatch.setattr(
        "src.server.rules.coc_handlers.secure_randint",
        lambda *_args, **_kwargs: 2,
    )
    state_service = StateService(test_db)
    state_service.initialize_character_state("solo-sanity-success-character", room_id)

    result = await ResolutionPipeline(
        test_db,
        compiler=_RejectingCompiler(),
        dispatcher=_RecordingDispatcher(),
        state_service=state_service,
    ).resolve_action("solo-sanity-success-action")

    assert result["status"] == "completed"
    assert result["result"]["metadata"]["solo_adventure_transition"]["target_node_id"] == "269"
    assert SoloAdventureRuntime(test_db).current(room_id)["node_id"] == "269"


class _AutoSuccessCompiler:
    async def compile(self, *_args, **_kwargs):
        return MechanicCompileResult(triggeredMechanic="auto_success")


class _RejectingCompiler:
    async def compile(self, *_args, **_kwargs):
        raise AssertionError("verified solo move must not call the remote compiler")


class _RecordingDispatcher:
    def __init__(self):
        self.events = []

    async def emit(self, room_id, event_type, audience, payload, character_id=None):
        self.events.append((room_id, event_type, audience, payload, character_id))


@pytest.mark.asyncio
async def test_confirmed_move_commits_solo_transition_with_action_completion(test_db):
    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data)
        VALUES ('solo-runtime-character', %s, '玩家', 'solo-runtime-token', %s)
        """,
        (room_id, json.dumps({"skills": {}})),
    )
    test_db.execute(
        """
        INSERT INTO actions (
            action_id, room_id, character_id, intent_type, declared_intent,
            params, status, draft_id, idempotency_key
        ) VALUES (%s, %s, %s, 'move', '我转到条目 2', %s, 'queued', 'solo-draft', 'solo-key')
        """,
        (
            "solo-runtime-action",
            room_id,
            "solo-runtime-character",
            json.dumps(
                {
                    "fromNodeId": "1",
                    "targetNodeId": "2",
                    "director_plan": {
                        "context_version": 0,
                        "preconditions": [],
                        "permissions": [],
                        "state_patch": [],
                        "state_patch_authority": "advisory_only",
                    },
                },
                ensure_ascii=False,
            ),
        ),
    )
    dispatcher = _RecordingDispatcher()
    result = await ResolutionPipeline(
        test_db, compiler=_AutoSuccessCompiler(), dispatcher=dispatcher
    ).resolve_action("solo-runtime-action")

    assert result["status"] == "completed"
    assert "长途车。" in result["result"]["narrative"]
    assert "条目" not in result["result"]["narrative"]
    assert "转到" not in result["result"]["narrative"]
    assert "你准备怎么做" in result["result"]["narrative"]
    assert SoloAdventureRuntime(test_db).current(room_id)["node_id"] == "2"
    action = test_db.execute(
        "SELECT status, result FROM actions WHERE action_id = 'solo-runtime-action'"
    ).fetchone()
    assert action["status"] == "completed"
    assert action["result"]["metadata"]["solo_adventure_transition"]["target_node_id"] == "2"
    assert any(event[1] == "s2c_scene_sync" for event in dispatcher.events)


@pytest.mark.asyncio
async def test_verified_solo_move_applies_fixed_healing_from_source(test_db):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    test_db.execute(
        "UPDATE content_items SET payload = %s WHERE scenario_version_id = %s AND logical_key = '1'",
        (
            json.dumps(
                {
                    "node_id": "1",
                    "title": "条目 1",
                    "text": "你在失去意识时接受了急救，可以回复1点生命值。现在转到2。",
                },
                ensure_ascii=False,
            ),
            scenario_version_id,
        ),
    )
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data)
        VALUES ('solo-healing-character', %s, '玩家', 'solo-healing-token', %s)
        """,
        (room_id, json.dumps({"hp": 4, "max_hp": 10, "skills": {}})),
    )
    test_db.execute(
        """
        INSERT INTO actions (
            action_id, room_id, character_id, draft_id, intent_type, declared_intent,
            params, status, idempotency_key
        ) VALUES (%s, %s, 'solo-healing-character', 'solo-healing-draft', 'move',
            '我休整后继续前行', %s, 'queued', 'solo-healing-key')
        """,
        (
            "solo-healing-action",
            room_id,
            json.dumps(
                {
                    "fromNodeId": "1",
                    "targetNodeId": "2",
                    "director_plan": {
                        "context_version": 0,
                        "preconditions": [],
                        "permissions": [],
                        "state_patch": [],
                        "state_patch_authority": "advisory_only",
                    },
                },
                ensure_ascii=False,
            ),
        ),
    )
    state_service = StateService(test_db)
    state_service.initialize_character_state("solo-healing-character", room_id)

    result = await ResolutionPipeline(
        test_db,
        compiler=_RejectingCompiler(),
        dispatcher=_RecordingDispatcher(),
        state_service=state_service,
    ).resolve_action("solo-healing-action")

    assert result["status"] == "completed"
    assert result["result"]["metadata"]["fixed_healing"] == 1
    assert state_service.get_runtime_state("solo-healing-character", room_id)["hp"] == 5


@pytest.mark.asyncio
async def test_verified_solo_move_persists_source_penalty_die_for_later_checks(test_db):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    test_db.execute(
        "UPDATE content_items SET payload = %s WHERE scenario_version_id = %s AND logical_key = '1'",
        (
            json.dumps(
                {
                    "node_id": "1",
                    "title": "条目 1",
                    "text": "今天你的技能检定获得一颗惩罚骰。现在转到2。",
                    "target_node_ids": ["2"],
                    "citation": {"page_number": 1},
                },
                ensure_ascii=False,
            ),
            scenario_version_id,
        ),
    )
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data)
        VALUES ('solo-penalty-character', %s, '玩家', 'solo-penalty-token', %s)
        """,
        (room_id, json.dumps({"skills": {}})),
    )
    test_db.execute(
        """
        INSERT INTO actions (
            action_id, room_id, character_id, draft_id, intent_type, declared_intent,
            params, status, idempotency_key
        ) VALUES (%s, %s, 'solo-penalty-character', 'solo-penalty-draft', 'move',
            '我记下这条规则后继续前行', %s, 'queued', 'solo-penalty-key')
        """,
        (
            "solo-penalty-action",
            room_id,
            json.dumps(
                {
                    "fromNodeId": "1",
                    "targetNodeId": "2",
                    "director_plan": {
                        "context_version": 0,
                        "preconditions": [],
                        "permissions": [],
                        "state_patch": [],
                        "state_patch_authority": "advisory_only",
                    },
                },
                ensure_ascii=False,
            ),
        ),
    )

    result = await ResolutionPipeline(
        test_db,
        compiler=_RejectingCompiler(),
        dispatcher=_RecordingDispatcher(),
    ).resolve_action("solo-penalty-action")

    assert result["status"] == "completed"
    assert result["result"]["metadata"]["solo_skill_bonus_dice"] == -1
    assert SoloAdventureRuntime(test_db).current(room_id)["scene_variables"]["solo_skill_bonus_dice"] == -1


@pytest.mark.asyncio
async def test_verified_solo_move_applies_fixed_sanity_loss_from_source(test_db, monkeypatch):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    test_db.execute(
        "UPDATE content_items SET payload = %s WHERE scenario_version_id = %s AND logical_key = '1'",
        (
            json.dumps(
                {
                    "node_id": "1",
                    "title": "条目 1",
                    "text": "浓烟让你透不过气。失去1D3点理智值。转到2。",
                    "target_node_ids": ["2"],
                    "citation": {"page_number": 1},
                },
                ensure_ascii=False,
            ),
            scenario_version_id,
        ),
    )
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data)
        VALUES ('solo-sanity-loss-character', %s, '玩家', 'solo-sanity-loss-token', %s)
        """,
        (room_id, json.dumps({"san": 10, "skills": {}}, ensure_ascii=False)),
    )
    test_db.execute(
        """
        INSERT INTO actions (
            action_id, room_id, character_id, draft_id, intent_type, declared_intent,
            params, status, idempotency_key
        ) VALUES (%s, %s, 'solo-sanity-loss-character', 'solo-sanity-loss-draft', 'move',
            '我忍住恐惧继续前行', %s, 'queued', 'solo-sanity-loss-key')
        """,
        (
            "solo-sanity-loss-action",
            room_id,
            json.dumps(
                {
                    "fromNodeId": "1",
                    "targetNodeId": "2",
                    "director_plan": {
                        "context_version": 0,
                        "preconditions": [],
                        "permissions": [],
                        "state_patch": [],
                        "state_patch_authority": "advisory_only",
                    },
                },
                ensure_ascii=False,
            ),
        ),
    )
    monkeypatch.setattr(
        "src.server.rules.coc_handlers.secure_randint",
        lambda *_args, **_kwargs: 2,
    )
    state_service = StateService(test_db)
    state_service.initialize_character_state("solo-sanity-loss-character", room_id)

    result = await ResolutionPipeline(
        test_db,
        compiler=_RejectingCompiler(),
        dispatcher=_RecordingDispatcher(),
        state_service=state_service,
    ).resolve_action("solo-sanity-loss-action")

    assert result["status"] == "completed"
    assert result["result"]["metadata"]["fixed_sanity_loss"] == 2
    assert state_service.get_runtime_state("solo-sanity-loss-character", room_id)["san"] == 8


@pytest.mark.asyncio
async def test_verified_solo_purchase_adds_source_backed_item_once(test_db):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    test_db.execute(
        "UPDATE content_items SET payload = %s WHERE scenario_version_id = %s AND logical_key = '1'",
        (
            json.dumps(
                {
                    "node_id": "1",
                    "title": "条目 1",
                    "text": "商店里没有武器，只有一把积满尘土的狩猎小刀，如果想要，你可以买下它。然后转到2。",
                },
                ensure_ascii=False,
            ),
            scenario_version_id,
        ),
    )
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data)
        VALUES ('solo-purchase-character', %s, '玩家', 'solo-purchase-token', %s)
        """,
        (room_id, json.dumps({"skills": {}})),
    )
    test_db.execute(
        """
        INSERT INTO actions (
            action_id, room_id, character_id, draft_id, intent_type, declared_intent,
            params, status, idempotency_key
        ) VALUES (%s, %s, 'solo-purchase-character', 'solo-purchase-draft', 'move',
            '我买下那把积满灰尘的狩猎小刀，把它收进旅行箱。', %s, 'queued', 'solo-purchase-key')
        """,
        (
            "solo-purchase-action",
            room_id,
            json.dumps(
                {
                    "fromNodeId": "1",
                    "targetNodeId": "2",
                    "solo_adventure": True,
                    "director_plan": {
                        "context_version": 0,
                        "preconditions": [],
                        "permissions": [],
                        "state_patch": [],
                        "state_patch_authority": "advisory_only",
                    },
                },
                ensure_ascii=False,
            ),
        ),
    )
    state_service = StateService(test_db)
    state_service.initialize_character_state("solo-purchase-character", room_id)
    pipeline = ResolutionPipeline(
        test_db,
        compiler=_RejectingCompiler(),
        dispatcher=_RecordingDispatcher(),
        state_service=state_service,
    )

    first_result = await pipeline.resolve_action("solo-purchase-action")
    second_result = await pipeline.resolve_action("solo-purchase-action")

    assert first_result["status"] == "completed"
    assert second_result["status"] == "completed"
    assert first_result["result"]["metadata"]["solo_item_purchase"] == {
        "name": "狩猎小刀",
        "source": "scenario_purchase:1",
        "citation": {"page_number": 1},
    }
    items = test_db.execute(
        "SELECT name, description, quantity, source FROM inventory WHERE character_id = 'solo-purchase-character'"
    ).fetchall()
    assert [dict(item) for item in items] == [
        {
            "name": "狩猎小刀",
            "description": "从剧本场景中购买的狩猎小刀。",
            "quantity": 1,
            "source": "scenario_purchase:1",
        }
    ]


@pytest.mark.asyncio
async def test_solo_state_and_scene_roll_back_when_resolution_bundle_fails(
    test_db,
    monkeypatch,
):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    test_db.execute(
        "UPDATE content_items SET payload = %s "
        "WHERE scenario_version_id = %s AND logical_key = '1'",
        (
            json.dumps(
                {
                    "node_id": "1",
                    "title": "条目 1",
                    "text": (
                        "商店里没有武器，只有一把积满尘土的狩猎小刀，"
                        "如果想要，你可以买下它。然后转到2。"
                    ),
                },
                ensure_ascii=False,
            ),
            scenario_version_id,
        ),
    )
    test_db.execute(
        "INSERT INTO characters "
        "(character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-atomic-character', %s, '玩家', 'solo-atomic-token', %s)",
        (room_id, json.dumps({"skills": {}})),
    )
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, draft_id, intent_type, declared_intent, "
        "params, status, idempotency_key) VALUES "
        "('solo-atomic-action', %s, 'solo-atomic-character', "
        "'solo-atomic-draft', 'move', '我买下狩猎小刀并继续前进', %s, "
        "'queued', 'solo-atomic-key')",
        (
            room_id,
            json.dumps(
                {
                    "fromNodeId": "1",
                    "targetNodeId": "2",
                    "solo_adventure": True,
                    "director_plan": {
                        "context_version": 0,
                        "preconditions": [],
                        "permissions": [],
                        "state_patch": [],
                        "state_patch_authority": "advisory_only",
                    },
                },
                ensure_ascii=False,
            ),
        ),
    )
    state_service = StateService(test_db)
    state_service.initialize_character_state("solo-atomic-character", room_id)
    pipeline = ResolutionPipeline(
        test_db,
        compiler=_RejectingCompiler(),
        dispatcher=_RecordingDispatcher(),
        state_service=state_service,
    )

    def fail_bundle(*_args, **_kwargs):
        raise RuntimeError("forced-solo-bundle-crash")

    monkeypatch.setattr(pipeline, "_persist_resolution_bundle", fail_bundle)

    outcome = await pipeline.resolve_action("solo-atomic-action")

    assert SoloAdventureRuntime(test_db).current(room_id)["node_id"] == "1"
    assert test_db.execute(
        "SELECT 1 FROM inventory WHERE character_id = 'solo-atomic-character'"
    ).fetchone() is None
    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = 'solo-atomic-action'"
    ).fetchone()["status"] == "awaiting_host_exception"
    assert outcome == {
        "status": "awaiting_host_exception",
        "action_id": "solo-atomic-action",
        "reason": "state_persistence_failed",
    }


@pytest.mark.asyncio
async def test_verified_solo_damage_transition_rolls_damage_and_selects_branch(test_db, monkeypatch):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    graph = test_db.execute(
        "SELECT knowledge_graph FROM scenario_versions WHERE scenario_version_id = %s",
        (scenario_version_id,),
    ).fetchone()["knowledge_graph"]
    graph["solo_adventure"]["nodes"][0].update(
        {
            "text": (
                "你撞上地面时受到2D6点伤害。如果这次2D6伤害的数值大于等于"
                "你最大生命值的一半，转到2。否则，转到3。"
            ),
            "target_node_ids": ["2", "3"],
        }
    )
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps(graph, ensure_ascii=False), scenario_version_id),
    )
    ContentProjectionService(test_db).rebuild(
        scenario_version_id, graph, requested_by="test-admin"
    )
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data)
        VALUES ('solo-fall-character', %s, '玩家', 'solo-fall-token', %s)
        """,
        (room_id, json.dumps({"hp": 10, "max_hp": 10, "skills": {}})),
    )
    test_db.execute(
        """
        INSERT INTO actions (
            action_id, room_id, character_id, draft_id, intent_type, declared_intent,
            params, status, idempotency_key
        ) VALUES (%s, %s, 'solo-fall-character', 'solo-fall-draft', 'move',
            '我承受坠落冲击', %s, 'queued', 'solo-fall-key')
        """,
        (
            "solo-fall-action",
            room_id,
            json.dumps(
                {
                    "fromNodeId": "1",
                    "solo_adventure_damage": True,
                    "director_plan": {
                        "context_version": 0,
                        "preconditions": [],
                        "permissions": [],
                        "state_patch": [],
                        "state_patch_authority": "advisory_only",
                    },
                },
                ensure_ascii=False,
            ),
        ),
    )
    monkeypatch.setattr(
        "src.server.rules.coc_handlers.secure_randint",
        lambda *_args, **_kwargs: 1,
    )
    state_service = StateService(test_db)
    state_service.initialize_character_state("solo-fall-character", room_id)

    result = await ResolutionPipeline(
        test_db,
        compiler=_RejectingCompiler(),
        dispatcher=_RecordingDispatcher(),
        state_service=state_service,
    ).resolve_action("solo-fall-action")

    assert result["status"] == "completed"
    assert result["result"]["metadata"]["damage"] == 2
    assert SoloAdventureRuntime(test_db).current(room_id)["node_id"] == "3"
    assert state_service.get_runtime_state("solo-fall-character", room_id)["hp"] == 8


@pytest.mark.asyncio
async def test_terminal_solo_damage_completes_when_narrator_is_unavailable(test_db, monkeypatch):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    graph = test_db.execute(
        "SELECT knowledge_graph FROM scenario_versions WHERE scenario_version_id = %s",
        (scenario_version_id,),
    ).fetchone()["knowledge_graph"]
    graph["solo_adventure"]["nodes"][0].update(
        {
            "text": (
                "你因为火焰受到1D6点生命值伤害。"
                "如果你的生命值因此归零，你会被烈焰烧死！【剧终】。否则，转到2。"
            ),
            "target_node_ids": ["2"],
        }
    )
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps(graph, ensure_ascii=False), scenario_version_id),
    )
    ContentProjectionService(test_db).rebuild(
        scenario_version_id, graph, requested_by="test-admin"
    )
    test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room_id,))
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data)
        VALUES ('solo-terminal-character', %s, '玩家', 'solo-terminal-token', %s)
        """,
        (room_id, json.dumps({"hp": 1, "max_hp": 1, "skills": {}})),
    )
    test_db.execute(
        """
        INSERT INTO actions (
            action_id, room_id, character_id, draft_id, intent_type, declared_intent,
            params, status, idempotency_key
        ) VALUES (%s, %s, 'solo-terminal-character', 'solo-terminal-draft', 'move',
            '我忍着火焰继续前进', %s, 'queued', 'solo-terminal-key')
        """,
        (
            "solo-terminal-action",
            room_id,
            json.dumps(
                {
                    "fromNodeId": "1",
                    "solo_adventure_damage": True,
                    "director_plan": {
                        "context_version": 0,
                        "preconditions": [],
                        "permissions": [],
                        "state_patch": [],
                        "state_patch_authority": "advisory_only",
                    },
                },
                ensure_ascii=False,
            ),
        ),
    )
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('solo-terminal-pending', %s, 'solo-terminal-character', "
        "'dialogue', '结局后不应继续', 'queued')",
        (room_id,),
    )
    monkeypatch.setattr(
        "src.server.rules.coc_handlers.secure_randint",
        lambda *_args, **_kwargs: 1,
    )
    state_service = StateService(test_db)
    state_service.initialize_character_state("solo-terminal-character", room_id)

    class FailingNarratorGateway:
        async def narrate_action(self, *_args, **_kwargs):
            raise AssertionError("终局伤害不应依赖 AI 叙事服务")

    result = await ResolutionPipeline(
        test_db,
        compiler=_RejectingCompiler(),
        dispatcher=_RecordingDispatcher(),
        gateway=FailingNarratorGateway(),
        state_service=state_service,
    ).resolve_action("solo-terminal-action")

    assert result["status"] == "completed"
    assert result["result"]["metadata"]["solo_adventure_terminal"]["reason"] == "hp_zero"
    assert state_service.get_runtime_state("solo-terminal-character", room_id)["hp"] == 0
    assert test_db.execute(
        "SELECT status FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()["status"] == "completed"
    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = 'solo-terminal-action'"
    ).fetchone()["status"] == "completed"
    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = 'solo-terminal-pending'"
    ).fetchone()["status"] == "canceled"
    assert test_db.execute(
        "SELECT ending_type FROM campaign_archives WHERE room_id = %s",
        (room_id,),
    ).fetchone()["ending_type"] == "defeat"


@pytest.mark.asyncio
async def test_verified_solo_move_skips_remote_mechanic_compiler(test_db):
    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data)
        VALUES ('solo-local-move-character', %s, '玩家', 'solo-local-move-token', %s)
        """,
        (room_id, json.dumps({"skills": {}})),
    )
    test_db.execute(
        """
        INSERT INTO actions (
            action_id, room_id, character_id, draft_id, intent_type, declared_intent,
            params, status, idempotency_key
        ) VALUES (%s, %s, 'solo-local-move-character', 'solo-local-move-draft', 'move',
            '我坐上长途车继续旅程', %s, 'queued', 'solo-local-move-key')
        """,
        (
            "solo-local-move-action",
            room_id,
            json.dumps(
                {
                    "fromNodeId": "1",
                    "targetNodeId": "2",
                    "director_plan": {
                        "context_version": 0,
                        "preconditions": [],
                        "permissions": [],
                        "state_patch": [],
                        "state_patch_authority": "advisory_only",
                    },
                },
                ensure_ascii=False,
            ),
        ),
    )

    result = await ResolutionPipeline(
        test_db,
        compiler=_RejectingCompiler(),
        dispatcher=_RecordingDispatcher(),
    ).resolve_action("solo-local-move-action")

    assert result["status"] == "completed"
    assert SoloAdventureRuntime(test_db).current(room_id)["node_id"] == "2"


@pytest.mark.asyncio
async def test_verified_solo_terminal_move_uses_atomic_campaign_finalizer(test_db):
    room_id, _ = _setup_solo_room(test_db)
    runtime = SoloAdventureRuntime(test_db)
    runtime.transition(room_id, from_node_id="1", target_node_id="2")
    runtime.transition(room_id, from_node_id="2", target_node_id="3")
    context_version = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["state_version"]
    test_db.execute(
        "INSERT INTO characters "
        "(character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-ending-character', %s, '玩家', 'solo-ending-token', '{}')",
        (room_id,),
    )
    params = json.dumps(
        {
            "fromNodeId": "3",
            "targetNodeId": "4",
            "director_plan": {
                "context_version": context_version,
                "preconditions": [],
                "permissions": [],
                "state_patch": [],
                "state_patch_authority": "advisory_only",
            },
        },
        ensure_ascii=False,
    )
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, draft_id, intent_type, "
        "declared_intent, params, status, idempotency_key) VALUES "
        "('solo-ending-action', %s, 'solo-ending-character', "
        "'solo-ending-draft', 'move', '我逃离危险', %s, 'queued', "
        "'solo-ending-key'), "
        "('solo-ending-pending', %s, 'solo-ending-character', "
        "'solo-ending-pending-draft', 'dialogue', '不应继续', '{}', 'queued', "
        "'solo-ending-pending-key')",
        (room_id, params, room_id),
    )

    result = await ResolutionPipeline(
        test_db,
        compiler=_RejectingCompiler(),
        dispatcher=_RecordingDispatcher(),
    ).resolve_action("solo-ending-action")

    assert result["status"] == "completed"
    assert result["result"]["metadata"]["verified_ending"]["ending_type"] == "mixed"
    assert SoloAdventureRuntime(test_db).current(room_id)["node_id"] == "4"
    assert test_db.execute(
        "SELECT status FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["status"] == "completed"
    statuses = test_db.execute(
        "SELECT action_id, status FROM actions "
        "WHERE room_id = %s ORDER BY action_id",
        (room_id,),
    ).fetchall()
    assert {row["action_id"]: row["status"] for row in statuses} == {
        "solo-ending-action": "completed",
        "solo-ending-pending": "canceled",
    }
    assert test_db.execute(
        "SELECT ending_type FROM campaign_archives WHERE room_id = %s",
        (room_id,),
    ).fetchone()["ending_type"] == "mixed"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM events "
        "WHERE room_id = %s AND event_type = 's2c_campaign_ended'",
        (room_id,),
    ).fetchone()["count"] == 1


def test_player_map_projects_text_scene_without_raw_solo_targets(client, test_db):
    from src.server.router_map import _sanitize_player_scene_text

    assert _sanitize_player_scene_text("车站。转到263。") == "车站。"
    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data)
        VALUES ('solo-map-character', %s, '玩家', 'solo-map-token', %s)
        """,
        (room_id, json.dumps({})),
    )

    response = client.get(
        f"/api/maps/{room_id}", headers={"X-Room-Token": "solo-map-token"}
    )

    assert response.status_code == 200
    scene = response.json()["textScene"]
    assert scene["name"] == "当前场景"
    assert scene["description"] == "请根据 AI KP 的叙事、当前目标与已公开线索行动。"
    assert "条目 1" not in response.text
    assert "soloAdventure" not in scene
    assert "target_node_ids" not in response.text
    assert "source_ref" not in response.text
    assert "车站。" not in response.text
    assert "长途车" not in response.text


def test_player_map_uses_semantic_projection_when_image_map_is_active(client, test_db):
    from src.server.map_persistence import init_room_map_state, set_character_position

    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data)
        VALUES ('solo-image-map-character', %s, '玩家', 'solo-image-map-token', %s)
        """,
        (room_id, json.dumps({})),
    )
    test_db.execute(
        "INSERT INTO scenario_maps "
        "(map_id, scenario_id, status, map_type, base_asset, nodes, edges) "
        "VALUES ('solo-image-map', 'solo-runtime-scenario', 'confirmed', 'image', %s, %s, %s)",
        (
            json.dumps({"assetId": "solo-map-image"}),
            json.dumps([{"nodeId": "station", "name": "车站", "isStart": True}]),
            json.dumps([]),
        ),
    )
    test_db.execute(
        "INSERT INTO scenario_assets "
        "(asset_id, scenario_id, filename, original_name, mime_type, file_size, relative_path, visibility) "
        "VALUES ('solo-map-image', 'solo-runtime-scenario', 'map.png', '地图.png', 'image/png', 1, "
        "'data/scenario_assets/solo-runtime-scenario/map.png', 'host_only')"
    )
    test_db.execute(
        "INSERT INTO scenario_asset_bindings "
        "(binding_id, scenario_version_id, asset_id, target_type, target_key, confidence, status) "
        "VALUES ('solo-map-binding', 'solo-runtime-version', 'solo-map-image', 'map', 'map', 1, 'confirmed')"
    )
    test_db.commit()
    init_room_map_state(test_db, room_id, "solo-image-map")
    set_character_position(test_db, "solo-image-map-character", room_id, "station")

    response = client.get(
        f"/api/maps/{room_id}", headers={"X-Room-Token": "solo-image-map-token"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mapType"] == "image"
    assert payload["baseAsset"] == {"assetId": "solo-map-image"}
    assert "knownLocations" in payload
    assert "knownConnections" in payload
    assert "partyPosition" in payload
    assert "fogOfWar" in payload
    assert "soloAdventure" not in response.text
    assert "targetNodeId" not in response.text
    assert "cluesAvailable" not in response.text


def test_player_map_hides_unconfirmed_host_only_base_asset(client, test_db):
    from src.server.map_persistence import init_room_map_state, set_character_position

    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-hidden-map-character', %s, '玩家', 'solo-hidden-map-token', %s)",
        (room_id, json.dumps({})),
    )
    test_db.execute(
        "INSERT INTO scenario_assets "
        "(asset_id, scenario_id, filename, original_name, mime_type, file_size, relative_path, visibility) "
        "VALUES ('solo-hidden-map-image', 'solo-runtime-scenario', 'hidden-map.png', '隐藏地图.png', 'image/png', 1, "
        "'data/scenario_assets/solo-runtime-scenario/hidden-map.png', 'host_only')"
    )
    test_db.execute(
        "INSERT INTO scenario_maps "
        "(map_id, scenario_id, status, map_type, base_asset, nodes, edges) "
        "VALUES ('solo-hidden-map', 'solo-runtime-scenario', 'confirmed', 'image', %s, %s, %s)",
        (
            json.dumps({"assetId": "solo-hidden-map-image"}),
            json.dumps([{"nodeId": "station", "name": "车站", "isStart": True}]),
            json.dumps([]),
        ),
    )
    test_db.commit()
    init_room_map_state(test_db, room_id, "solo-hidden-map")
    set_character_position(test_db, "solo-hidden-map-character", room_id, "station")

    response = client.get(
        f"/api/maps/{room_id}", headers={"X-Room-Token": "solo-hidden-map-token"}
    )

    assert response.status_code == 200
    assert response.json()["baseAsset"] == {}


def test_v2_map_move_returns_410_use_action_draft(client, test_db):
    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data)
        VALUES ('solo-move-character', %s, '玩家', 'solo-move-token', %s)
        """,
        (room_id, json.dumps({})),
    )

    response = client.post(
        f"/api/map/{room_id}/move",
        headers={"X-Room-Token": "solo-move-token"},
        json={"fromNodeId": "1", "targetNodeId": "2"},
    )

    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "use_action_draft"


def test_shared_contract_models_use_redacted_citations():
    from pydantic import ValidationError
    from src.server.models import (
        ActionDraftDTO,
        AiStageProgress,
        HostDirectorSnapshotDTO,
        NarrationResultDTO,
        RedactedCitation,
        RuleExplanationDTO,
        SemanticMapProjectionDTO,
    )

    citation = RedactedCitation(label="场景依据", page=2, scene="车站")
    assert citation.model_dump() == {
        "label": "场景依据",
        "page": 2,
        "scene": "车站",
        "verified": True,
    }
    with pytest.raises(ValidationError):
        RedactedCitation(label="泄露", source_ref="secret.pdf#page=2")

    draft = ActionDraftDTO(
        intent_type="dialogue",
        declared_intent="检查窗户",
        understanding_summary="你想检查窗户。",
        risk="low",
        citations=[citation],
        analysis_source="local_fallback",
    )
    assert draft.citations[0].label == "场景依据"

    rule = RuleExplanationDTO(rule_set_version="coc7-v1", citations=[citation])
    assert rule.citations[0].page == 2

    narration = NarrationResultDTO(
        action_id="a1",
        context_version=1,
        director_plan_digest="digest",
        narrative_text="雾变浓了。",
        environment_changes=["灯暗了"],
        interactable_objects=["窗户"],
        open_question="你怎么做？",
        fact_refs={
            "narrative_text": ["fact-1"],
            "environment_changes": ["fact-2"],
            "interactable_objects": ["fact-3"],
            "open_question": ["fact-4"],
        },
        redacted_citations=[citation],
        style_pack_version="v1",
        provider_source="local_fallback",
    )
    assert narration.redacted_citations[0].scene == "车站"

    stage = AiStageProgress(stage="validating_rules", status="active")
    assert stage.stage == "validating_rules"

    projection = SemanticMapProjectionDTO(
        room_id="room-1",
        known_locations=[{"nodeId": "station", "label": "车站"}],
        known_connections=[],
        party_position={"nodeId": "station", "label": "车站"},
        fog_of_war=[],
    )
    assert projection.model_dump(by_alias=True)["knownLocations"][0]["label"] == "车站"

    snapshot = HostDirectorSnapshotDTO(
        current_scene="车站",
        confirmed_facts=["灯亮着"],
        pending_triggers=[],
        ai_evidence=[citation],
        stage="completed",
        risks=[],
        exception_queue=[],
    )
    assert snapshot.ai_evidence[0].label == "场景依据"


def test_natural_language_progression_resolves_the_only_visible_solo_choice(client, test_db):
    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data)
        VALUES ('solo-natural-character', %s, '玩家', 'solo-natural-token', %s)
        """,
        (room_id, json.dumps({})),
    )
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = None
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": "solo-natural-token"},
            json={"declared_intent": "车来了，我提起行李上车，继续出发。"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["intent_type"] == "move"
    assert draft["params"] == {"fromNodeId": "1", "targetNodeId": "2"}
    assert draft["movement_target"] == "下一场景"
    assert "条目 2" not in response.text
    assert draft["confirmation_requirements"] == ["movement", "state_change"]


def test_solo_fixed_damage_uses_local_preview_without_ai(client, test_db):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    graph = test_db.execute(
        "SELECT knowledge_graph FROM scenario_versions WHERE scenario_version_id = %s",
        (scenario_version_id,),
    ).fetchone()["knowledge_graph"]
    graph["solo_adventure"]["nodes"][0].update(
        {
            "text": (
                "你撞上地面时受到2D6点伤害。如果这次2D6伤害的数值大于等于"
                "你最大生命值的一半，转到2。否则，转到3。"
            ),
            "target_node_ids": ["2", "3"],
        }
    )
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps(graph, ensure_ascii=False), scenario_version_id),
    )
    ContentProjectionService(test_db).rebuild(
        scenario_version_id, graph, requested_by="test-admin"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-fall-local-character', %s, '玩家', 'solo-fall-local-token', %s)",
        (room_id, json.dumps({"hp": 10, "max_hp": 10})),
    )

    class FailingGateway:
        async def analyze_director_action(self, *_args, **_kwargs):
            raise AssertionError("固定伤害不应调用 AI")

    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = FailingGateway()
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": "solo-fall-local-token"},
            json={"declared_intent": "我重重摔向地面，尽量护住要害。"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["intent_type"] == "move"
    assert draft["params"]["solo_adventure_damage"]["damage_dice"] == "2d6"
    assert draft["params"]["director_plan"]["state_patch_authority"] == "advisory_only"
    assert draft["resolution_route"] == "local"
    assert draft["risk"] == "high"


def test_solo_fixed_hp_loss_uses_local_preview_without_ai(client, test_db):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    graph = test_db.execute(
        "SELECT knowledge_graph FROM scenario_versions WHERE scenario_version_id = %s",
        (scenario_version_id,),
    ).fetchone()["knowledge_graph"]
    graph["solo_adventure"]["nodes"][0].update(
        {
            "text": (
                "你在这次事件中损失了 点生命值。在 1 (HP)"
                "你的调查员角色卡上标记出损失。现在转到2。"
            ),
            "target_node_ids": ["2"],
        }
    )
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps(graph, ensure_ascii=False), scenario_version_id),
    )
    ContentProjectionService(test_db).rebuild(
        scenario_version_id, graph, requested_by="test-admin"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-fixed-hp-character', %s, '玩家', 'solo-fixed-hp-token', %s)",
        (room_id, json.dumps({"hp": 9, "max_hp": 9})),
    )

    class FailingGateway:
        async def analyze_director_action(self, *_args, **_kwargs):
            raise AssertionError("固定生命损失不应调用 AI")

    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = FailingGateway()
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": "solo-fixed-hp-token"},
            json={"declared_intent": "我承受撞击的伤势，继续前进。"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["params"]["solo_fixed_damage"]["amount"] == 1
    assert draft["confirmation_requirements"] == ["damage", "state_change"]
    assert draft["resolution_route"] == "local"


def test_solo_damage_and_skill_check_uses_local_preview_without_ai(client, test_db):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    graph = test_db.execute(
        "SELECT knowledge_graph FROM scenario_versions WHERE scenario_version_id = %s",
        (scenario_version_id,),
    ).fetchone()["knowledge_graph"]
    graph["solo_adventure"]["nodes"][0].update(
        {
            "text": (
                "你因为火焰受到1D6点生命值伤害。如果你的生命值归零，你会被烧死。"
                "否则，进行一次“力量”检定。如果你成功了，转到2。如果你失败了，转到3。"
            ),
            "target_node_ids": ["2", "3"],
        }
    )
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps(graph, ensure_ascii=False), scenario_version_id),
    )
    ContentProjectionService(test_db).rebuild(
        scenario_version_id, graph, requested_by="test-admin"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-fire-local-character', %s, '玩家', 'solo-fire-local-token', %s)",
        (room_id, json.dumps({"hp": 9, "max_hp": 9})),
    )

    class FailingGateway:
        async def analyze_director_action(self, *_args, **_kwargs):
            raise AssertionError("剧本确定性组合检定不应调用 AI")

    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = FailingGateway()
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": "solo-fire-local-token"},
            json={"declared_intent": "我忍住火焰灼痛，用尽力气拉扯锁链。"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["intent_type"] == "skill_check"
    assert draft["params"]["solo_adventure_check"]["damageDice"] == "1d6"
    assert draft["params"]["director_plan"]["state_patch_authority"] == "advisory_only"
    assert draft["resolution_route"] == "local"
    assert draft["requires_confirmation"] is True


def test_solo_black_bear_attack_uses_local_rule_preview_without_ai(client, test_db):
    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-bear-local-character', %s, '玩家', 'solo-bear-local-token', %s)",
        (room_id, json.dumps({"skills": {"格斗（斗殴）": 40}})),
    )
    runtime = SoloAdventureRuntime(test_db)
    runtime.transition(room_id, from_node_id="1", target_node_id="2")
    runtime.transition(room_id, from_node_id="2", target_node_id="3")

    class FailingGateway:
        async def analyze_director_action(self, *_args, **_kwargs):
            raise AssertionError("黑熊确定性战斗不应调用 AI")

    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = FailingGateway()
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": "solo-bear-local-token"},
            json={"declared_intent": "我拔出小刀，正面攻击黑熊。"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["intent_type"] == "combat_action"
    assert draft["params"]["actionKind"] == "attack"
    assert draft["params"]["solo_black_bear_combat"] is True
    assert draft["params"]["director_plan"]["state_patch_authority"] == "advisory_only"
    assert draft["resolution_route"] == "local"
    assert draft["risk"] == "high"
    assert draft["suggested_skill"] == "格斗（斗殴）"


@pytest.mark.asyncio
async def test_solo_bear_scene_bootstraps_an_active_encounter_without_host(test_db):
    from src.server.encounter_persistence import get_encounter, get_participants

    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-combat-character', %s, '玩家', 'solo-combat-token', %s)",
        (
            room_id,
            json.dumps({
                "name": "调查员",
                "hp": 10,
                "max_hp": 10,
                "san": 60,
                "max_san": 60,
                "attributes": {"dex": 65},
                "skills": {"格斗（斗殴）": 40},
            }, ensure_ascii=False),
        ),
    )
    runtime = SoloAdventureRuntime(test_db)
    runtime.transition(room_id, from_node_id="1", target_node_id="2")
    runtime.transition(room_id, from_node_id="2", target_node_id="3")
    intent = PlayerIntent(
        intent_type="combat_action",
        declared_intent="我用小刀攻击黑熊",
        params={},
    )
    error = await ResolutionPipeline(test_db)._validate_encounter_action(
        {"room_id": room_id, "character_id": "solo-combat-character"},
        intent,
    )

    assert error is None
    encounter = get_encounter(test_db, intent.params["encounterId"])
    assert encounter["status"] == "active"
    assert intent.params["combatStarted"] == encounter["encounter_id"]
    participants = get_participants(test_db, encounter["encounter_id"])
    enemy = next(item for item in participants if item["side"] == "enemy")
    assert enemy["display_name"] == "黑熊"
    assert enemy["hp"] == 20
    assert intent.params["targetId"] == enemy["character_id"]
    assert intent.params["actionKind"] == "attack"


@pytest.mark.asyncio
async def test_encounter_damage_mutation_updates_the_target_not_the_actor(test_db):
    from src.server.encounter_persistence import (
        add_participant,
        create_encounter,
        get_participant,
    )

    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-damage-character', %s, '玩家', 'solo-damage-token', %s)",
        (room_id, json.dumps({"hp": 10, "max_hp": 10})),
    )
    create_encounter(test_db, "solo-damage-encounter", room_id, status="active")
    add_participant(
        test_db, "solo-damage-encounter", "solo-damage-character",
        side="player", hp=10, hp_max=10,
    )
    add_participant(
        test_db, "solo-damage-encounter", "npc:bear",
        side="enemy", hp=20, hp_max=20, display_name="黑熊",
    )
    resolution = ResolutionResult(
        actionId="combat-action",
        roomId=room_id,
        characterId="solo-damage-character",
        mechanic="combat_attack",
        isSuccess=True,
        mutations=[{
            "op": "replace",
            "path": "/encounter/solo-damage-encounter/participants/npc:bear/hp_delta",
            "value": -4,
        }],
    )
    dispatcher = _RecordingDispatcher()
    await ResolutionPipeline(test_db, dispatcher=dispatcher)._apply_encounter_result(
        {"room_id": room_id, "character_id": "solo-damage-character"},
        PlayerIntent(
            intent_type="combat_action",
            params={"encounterId": "solo-damage-encounter"},
        ),
        resolution,
    )

    enemy = get_participant(test_db, "solo-damage-encounter", "npc:bear")
    assert enemy["hp"] == 16
    assert enemy["public_visibility"] == "visible"
    assert enemy["public_label"] == "敌对身影 1"
    assert get_participant(
        test_db, "solo-damage-encounter", "solo-damage-character"
    )["hp"] == 10
    party_update = next(
        item for item in dispatcher.events
        if item[1] == "s2c_encounter_updated" and item[2] == "party"
    )
    assert party_update[3]["publicUnits"] == [
        {
            "label": "调查员",
            "kind": "investigator",
            "healthSegments": 8,
            "condition": "情况稳定",
            "distanceBand": "medium",
        },
        {
            "label": "敌对身影 1",
            "kind": "observed_enemy",
            "healthSegments": 6,
            "condition": "情况稳定",
            "distanceBand": "medium",
        },
    ]
    assert "participants" not in party_update[3]
    host_update = next(
        item for item in dispatcher.events
        if item[1] == "s2c_encounter_updated" and item[2] == "host"
    )
    host_enemy = next(
        participant
        for participant in host_update[3]["participants"]
        if participant["character_id"] == "npc:bear"
    )
    assert host_enemy["display_name"] == "黑熊"
    assert host_enemy["hp"] == 16


@pytest.mark.asyncio
async def test_observed_enemy_becomes_lost_after_rule_moves_it_out_of_sight(test_db):
    from src.server.encounter_persistence import (
        add_participant,
        create_encounter,
        get_participant,
    )

    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-chase-character', %s, '玩家', 'solo-chase-token', %s)",
        (room_id, json.dumps({"hp": 10, "max_hp": 10})),
    )
    create_encounter(test_db, "solo-chase-encounter", room_id, enc_type="chase", status="active")
    add_participant(
        test_db, "solo-chase-encounter", "solo-chase-character",
        side="player", hp=10, hp_max=10,
    )
    add_participant(
        test_db, "solo-chase-encounter", "npc:gunner",
        side="enemy", hp=12, hp_max=12, display_name="理查德·卡特",
        distance_band="medium", public_visibility="visible", public_label="走廊中的人影",
    )
    add_participant(
        test_db, "solo-chase-encounter", "npc:watcher",
        side="enemy", hp=12, hp_max=12, display_name="暗中的观察者",
        distance_band="medium", public_visibility="hidden",
    )
    resolution = ResolutionResult(
        actionId="chase-action",
        roomId=room_id,
        characterId="solo-chase-character",
        mechanic="chase_escape",
        isSuccess=True,
        mutations=[{
            "op": "replace",
            "path": "/encounter/solo-chase-encounter/participants/npc:gunner/distance_band_delta",
            "value": 9,
        }, {
            "op": "replace",
            "path": "/encounter/solo-chase-encounter/participants/npc:watcher/distance_band_delta",
            "value": 9,
        }],
    )
    dispatcher = _RecordingDispatcher()

    await ResolutionPipeline(test_db, dispatcher=dispatcher)._apply_encounter_result(
        {"room_id": room_id, "character_id": "solo-chase-character"},
        PlayerIntent(
            intent_type="chase_action",
            params={"encounterId": "solo-chase-encounter"},
        ),
        resolution,
    )

    enemy = get_participant(test_db, "solo-chase-encounter", "npc:gunner")
    assert enemy["public_visibility"] == "lost"
    assert enemy["last_observed_position"] == "中距离"
    assert get_participant(
        test_db, "solo-chase-encounter", "npc:watcher"
    )["public_visibility"] == "hidden"
    party_update = next(
        item for item in dispatcher.events
        if item[1] == "s2c_encounter_updated" and item[2] == "party"
    )
    assert party_update[3]["publicUnits"] == [
        {
            "label": "调查员",
            "kind": "investigator",
            "healthSegments": 8,
            "condition": "情况稳定",
            "distanceBand": "medium",
        },
        {
            "label": "走廊中的人影",
            "kind": "observed_enemy",
            "condition": "失去踪迹",
            "lastObservedAt": "中距离",
        },
    ]
    assert "理查德·卡特" not in str(party_update[3])
    assert "hp" not in str(party_update[3])


@pytest.mark.asyncio
async def test_solo_bear_attack_queues_a_persistent_player_reaction(test_db):
    from src.server.encounter_persistence import get_encounter
    from src.server.engine.solo_combat_reactions import get_pending_reaction

    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-reaction-character', %s, '玩家', 'solo-reaction-token', %s)",
        (
            room_id,
            json.dumps({
                "name": "调查员",
                "hp": 10,
                "max_hp": 10,
                "attributes": {"dex": 65},
                "skills": {"格斗（斗殴）": 40, "闪避": 30},
            }, ensure_ascii=False),
        ),
    )
    runtime = SoloAdventureRuntime(test_db)
    runtime.transition(room_id, from_node_id="1", target_node_id="2")
    runtime.transition(room_id, from_node_id="2", target_node_id="3")
    intent = PlayerIntent(
        intent_type="combat_action",
        declared_intent="我用小刀攻击黑熊",
        params={},
    )
    dispatcher = _RecordingDispatcher()
    pipeline = ResolutionPipeline(test_db, dispatcher=dispatcher)
    assert await pipeline._validate_encounter_action(
        {"room_id": room_id, "character_id": "solo-reaction-character"},
        intent,
    ) is None
    encounter_id = intent.params["encounterId"]

    await pipeline._apply_encounter_result(
        {
            "action_id": "solo-reaction-action",
            "room_id": room_id,
            "character_id": "solo-reaction-character",
        },
        intent,
        ResolutionResult(
            actionId="solo-reaction-action",
            roomId=room_id,
            characterId="solo-reaction-character",
            mechanic="combat_attack",
            isSuccess=False,
        ),
    )

    reaction = get_pending_reaction(
        test_db, "solo-reaction-character", room_id=room_id,
    )
    assert reaction is not None
    assert reaction["encounter_id"] == encounter_id
    assert reaction["round_number"] == 1
    assert reaction["attack_index"] == 1
    assert reaction["attack_name"] == "爪击"
    assert reaction["status"] == "pending"
    assert get_encounter(test_db, encounter_id)["status"] == "active"
    event = next(
        item for item in dispatcher.events
        if item[1] == "s2c_solo_combat_reaction_requested"
    )
    assert event[3]["reaction"]["roundNumber"] == 1
    assert event[3]["reaction"]["attackName"] == "爪击"
    party_update = next(
        item for item in dispatcher.events
        if item[1] == "s2c_encounter_updated" and item[2] == "party"
    )
    assert party_update[3]["publicUnits"] == [
        {
            "label": "调查员",
            "kind": "investigator",
            "healthSegments": 8,
            "condition": "情况稳定",
            "distanceBand": "medium",
        },
        {
            "label": "黑熊",
            "kind": "observed_enemy",
            "healthSegments": 8,
            "condition": "情况稳定",
            "distanceBand": "medium",
        },
    ]
    assert "participants" not in party_update[3]
    host_update = next(
        item for item in dispatcher.events
        if item[1] == "s2c_encounter_updated" and item[2] == "host"
    )
    assert len(host_update[3]["participants"]) == 2


@pytest.mark.asyncio
async def test_solo_bear_reaction_applies_damage_once_and_queues_the_second_claw(
    test_db, monkeypatch,
):
    from src.server.encounter_persistence import get_participant
    from src.server.engine import solo_combat_reactions

    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-reaction-resolve-character', %s, '玩家', 'solo-reaction-resolve-token', %s)",
        (
            room_id,
            json.dumps({
                "name": "调查员",
                "hp": 10,
                "max_hp": 10,
                "attributes": {"dex": 65},
                "skills": {"格斗（斗殴）": 40, "闪避": 30},
            }, ensure_ascii=False),
        ),
    )
    runtime = SoloAdventureRuntime(test_db)
    runtime.transition(room_id, from_node_id="1", target_node_id="2")
    runtime.transition(room_id, from_node_id="2", target_node_id="3")
    intent = PlayerIntent(
        intent_type="combat_action",
        declared_intent="我用小刀攻击黑熊",
        params={},
    )
    pipeline = ResolutionPipeline(test_db)
    assert await pipeline._validate_encounter_action(
        {"room_id": room_id, "character_id": "solo-reaction-resolve-character"},
        intent,
    ) is None
    reaction = solo_combat_reactions.queue_black_bear_reaction(
        test_db,
        room_id=room_id,
        encounter_id=intent.params["encounterId"],
        character_id="solo-reaction-resolve-character",
        source_action_id="solo-reaction-resolve-action",
    )
    assert reaction is not None

    checks = iter([
        {"roll": 20, "skill_value": 40, "is_success": True, "success_level": "regular"},
        {"roll": 90, "skill_value": 30, "is_success": False, "success_level": "failure"},
    ])
    monkeypatch.setattr(solo_combat_reactions, "roll_skill_check", lambda _skill: next(checks))
    monkeypatch.setattr(solo_combat_reactions, "roll_dice", lambda _dice: (5, [2, 3], 0))

    resolved = solo_combat_reactions.resolve_pending_reaction(
        test_db,
        reaction_id=reaction["reaction_id"],
        character_id="solo-reaction-resolve-character",
        choice="dodge",
    )

    assert resolved["result"]["damageToPlayer"] == 5
    assert resolved["next_reaction"]["attack_index"] == 2
    participant = get_participant(
        test_db, intent.params["encounterId"], "solo-reaction-resolve-character",
    )
    runtime_state = StateService(test_db).get_runtime_state(
        "solo-reaction-resolve-character", room_id,
    )
    assert participant["hp"] == 5
    assert runtime_state["hp"] == 5

    replay = solo_combat_reactions.resolve_pending_reaction(
        test_db,
        reaction_id=reaction["reaction_id"],
        character_id="solo-reaction-resolve-character",
        choice="dodge",
    )
    assert replay["idempotent"] is True
    assert get_participant(
        test_db, intent.params["encounterId"], "solo-reaction-resolve-character",
    )["hp"] == 5


def test_combat_rule_explanation_uses_skill_value_as_target_when_missing(test_db):
    explanation = ResolutionPipeline(test_db)._build_rule_explanation(
        {
            "action_id": "combat-target-action",
            "intent_type": "combat_action",
            "declared_intent": "我用小刀攻击黑熊",
            "params": {},
        },
        {"xlsx_data": {}},
        ResolutionResult(
            actionId="combat-target-action",
            roomId="combat-target-room",
            characterId="combat-target-character",
            mechanic="combat_attack",
            isSuccess=True,
            metadata={
                "skill_name": "格斗（斗殴）",
                "skill_value": 75,
                "difficulty": "regular",
                "success_level": "hard",
            },
            reveal_steps=[{"kind": "roll", "dice": "d100", "result": 31}],
        ),
    )

    assert explanation["authoritative_inputs"]["target"] == 75
    assert explanation["formula"] == "d100 <= 75"


def test_solo_bear_pending_reaction_is_available_from_player_api(client, test_db):
    from src.server.encounter_persistence import add_participant, create_encounter
    from src.server.engine.solo_combat_reactions import queue_black_bear_reaction

    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-reaction-api-character', %s, '玩家', 'solo-reaction-api-token', %s)",
        (room_id, json.dumps({"hp": 10, "max_hp": 10})),
    )
    create_encounter(test_db, "solo-reaction-api-encounter", room_id, status="active")
    test_db.execute(
        "UPDATE encounters SET current_round = 1 WHERE encounter_id = 'solo-reaction-api-encounter'"
    )
    add_participant(
        test_db, "solo-reaction-api-encounter", "solo-reaction-api-character",
        side="player", hp=10, hp_max=10,
    )
    add_participant(
        test_db, "solo-reaction-api-encounter", "npc:bear:api",
        side="enemy", hp=20, hp_max=20, weapon_name="爪击", damage_expression="2d6",
        notes="厚皮每轮吸收前3点伤害；", display_name="黑熊",
    )
    queued = queue_black_bear_reaction(
        test_db,
        room_id=room_id,
        encounter_id="solo-reaction-api-encounter",
        character_id="solo-reaction-api-character",
        source_action_id="solo-reaction-api-action",
    )
    assert queued is not None

    response = client.get(
        "/api/player/encounter-reactions/pending",
        headers={"X-Room-Token": "solo-reaction-api-token"},
    )

    assert response.status_code == 200
    assert response.json()["reaction"]["reactionId"] == queued["reaction_id"]
    assert response.json()["reaction"]["choices"] == ["dodge", "counterattack"]


def test_solo_bear_reaction_api_resolves_once(client, test_db, monkeypatch):
    from src.server.encounter_persistence import add_participant, create_encounter, get_participant
    from src.server.engine import solo_combat_reactions

    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-reaction-api-resolve-character', %s, '玩家', 'solo-reaction-api-resolve-token', %s)",
        (room_id, json.dumps({"hp": 10, "max_hp": 10, "skills": {"闪避": 30}})),
    )
    create_encounter(test_db, "solo-reaction-api-resolve-encounter", room_id, status="active")
    test_db.execute(
        "UPDATE encounters SET current_round = 1 WHERE encounter_id = 'solo-reaction-api-resolve-encounter'"
    )
    add_participant(
        test_db, "solo-reaction-api-resolve-encounter", "solo-reaction-api-resolve-character",
        side="player", hp=10, hp_max=10,
    )
    add_participant(
        test_db, "solo-reaction-api-resolve-encounter", "npc:bear:api-resolve",
        side="enemy", hp=20, hp_max=20, weapon_name="爪击", damage_expression="2d6",
        notes="厚皮每轮吸收前3点伤害；", display_name="黑熊",
    )
    queued = solo_combat_reactions.queue_black_bear_reaction(
        test_db,
        room_id=room_id,
        encounter_id="solo-reaction-api-resolve-encounter",
        character_id="solo-reaction-api-resolve-character",
        source_action_id="solo-reaction-api-resolve-action",
    )
    assert queued is not None
    checks = iter([
        {"roll": 20, "skill_value": 40, "is_success": True, "success_level": "regular"},
        {"roll": 90, "skill_value": 30, "is_success": False, "success_level": "failure"},
    ])
    monkeypatch.setattr(solo_combat_reactions, "roll_skill_check", lambda _skill: next(checks))
    monkeypatch.setattr(solo_combat_reactions, "roll_dice", lambda _dice: (4, [1, 3], 0))

    response = client.post(
        f"/api/player/encounter-reactions/{queued['reaction_id']}/resolve",
        headers={"X-Room-Token": "solo-reaction-api-resolve-token"},
        json={"choice": "dodge"},
    )

    assert response.status_code == 200
    assert response.json()["result"]["damageToPlayer"] == 4
    assert response.json()["nextReaction"]["attackIndex"] == 2
    assert get_participant(
        test_db, "solo-reaction-api-resolve-encounter", "solo-reaction-api-resolve-character",
    )["hp"] == 6


def test_solo_bear_reaction_uses_scripted_claw_and_bite_stats(test_db, monkeypatch):
    from src.server.encounter_persistence import add_participant, create_encounter
    from src.server.engine import solo_combat_reactions

    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-bear-stats-character', %s, '玩家', 'solo-bear-stats-token', %s)",
        (room_id, json.dumps({"hp": 10, "max_hp": 10, "skills": {"闪避": 30}})),
    )
    create_encounter(test_db, "solo-bear-stats-encounter", room_id, status="active")
    test_db.execute(
        "UPDATE encounters SET current_round = 2 WHERE encounter_id = 'solo-bear-stats-encounter'"
    )
    add_participant(test_db, "solo-bear-stats-encounter", "solo-bear-stats-character", side="player", hp=10, hp_max=10)
    add_participant(
        test_db, "solo-bear-stats-encounter", "npc:bear:stats", side="enemy", hp=20, hp_max=20,
        weapon_name="爪击", damage_expression="2d6", display_name="黑熊",
    )
    first = solo_combat_reactions.queue_black_bear_reaction(
        test_db,
        room_id=room_id,
        encounter_id="solo-bear-stats-encounter",
        character_id="solo-bear-stats-character",
        source_action_id="solo-bear-stats-action",
    )
    assert first is not None
    assert first["attack_name"] == "爪击"
    assert first["damage_expression"] == "2d6"

    skill_values: list[int] = []
    checks = iter([
        {"roll": 80, "skill_value": 35, "is_success": False, "success_level": "failure"},
        {"roll": 90, "skill_value": 30, "is_success": False, "success_level": "failure"},
    ])
    def fake_check(skill_value: int):
        skill_values.append(skill_value)
        return next(checks)
    monkeypatch.setattr(solo_combat_reactions, "roll_skill_check", fake_check)

    result = solo_combat_reactions.resolve_pending_reaction(
        test_db,
        reaction_id=first["reaction_id"],
        character_id="solo-bear-stats-character",
        choice="dodge",
    )

    assert skill_values == [35, 30]
    assert result["next_reaction"]["attack_name"] == "啃咬"
    assert result["next_reaction"]["damage_expression"] == "1d8"


def test_solo_bear_third_round_survival_transitions_to_scripted_outcome(test_db, monkeypatch):
    from src.server.encounter_persistence import add_participant, create_encounter, get_encounter
    from src.server.engine import solo_combat_reactions

    room_id, scenario_version_id = _setup_solo_room(test_db)
    graph = {
        "solo_adventure": {
            "root_node_id": "173",
            "integrity": {"is_valid": True},
            "nodes": [
                {
                    "node_id": "173",
                    "title": "条目 173",
                    "text": "黑熊的敏捷为58，生命值为20。它会用爪击攻击，战斗持续三轮。",
                    "target_node_ids": ["193", "201"],
                    "citation": {"page_number": 173},
                },
                {
                    "node_id": "193",
                    "title": "条目 193",
                    "text": "你失去意识。【剧终】",
                    "target_node_ids": [],
                    "citation": {"page_number": 193},
                },
                {
                    "node_id": "201",
                    "title": "条目 201",
                    "text": "黑熊退回树林。转到79。",
                    "target_node_ids": ["79"],
                    "citation": {"page_number": 201},
                },
                {
                    "node_id": "79",
                    "title": "条目 79",
                    "text": "你继续赶路。",
                    "target_node_ids": [],
                    "citation": {"page_number": 79},
                },
            ],
        },
    }
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps(graph, ensure_ascii=False), scenario_version_id),
    )
    ContentProjectionService(test_db).rebuild(
        scenario_version_id, graph, requested_by="test-admin",
    )
    test_db.execute(
        "INSERT INTO room_scene_state (room_id, current_scene, visited_scenes, scene_variables, version) "
        "VALUES (%s, 'solo:173', '[]', '{}', 1)",
        (room_id,),
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-bear-outcome-character', %s, '玩家', 'solo-bear-outcome-token', %s)",
        (room_id, json.dumps({"hp": 10, "max_hp": 10, "attributes": {"con": 60}, "skills": {"闪避": 30}})),
    )
    create_encounter(test_db, "solo-bear-outcome-encounter", room_id, status="active")
    test_db.execute(
        "UPDATE encounters SET current_round = 3 WHERE encounter_id = 'solo-bear-outcome-encounter'"
    )
    add_participant(test_db, "solo-bear-outcome-encounter", "solo-bear-outcome-character", side="player", hp=10, hp_max=10)
    add_participant(
        test_db, "solo-bear-outcome-encounter", "npc:bear:outcome", side="enemy", hp=20, hp_max=20,
        weapon_name="爪击", damage_expression="2d6", display_name="黑熊",
    )
    first = solo_combat_reactions.queue_black_bear_reaction(
        test_db,
        room_id=room_id,
        encounter_id="solo-bear-outcome-encounter",
        character_id="solo-bear-outcome-character",
        source_action_id="solo-bear-outcome-action",
    )
    assert first is not None
    checks = iter([
        {"roll": 80, "skill_value": 35, "is_success": False, "success_level": "failure"},
        {"roll": 90, "skill_value": 30, "is_success": False, "success_level": "failure"},
        {"roll": 80, "skill_value": 35, "is_success": False, "success_level": "failure"},
        {"roll": 90, "skill_value": 30, "is_success": False, "success_level": "failure"},
    ])
    monkeypatch.setattr(solo_combat_reactions, "roll_skill_check", lambda _skill: next(checks))

    first_result = solo_combat_reactions.resolve_pending_reaction(
        test_db, reaction_id=first["reaction_id"], character_id="solo-bear-outcome-character", choice="dodge",
    )
    final_result = solo_combat_reactions.resolve_pending_reaction(
        test_db,
        reaction_id=first_result["next_reaction"]["reaction_id"],
        character_id="solo-bear-outcome-character",
        choice="dodge",
    )

    assert final_result["solo_transition"]["target_node_id"] == "201"
    assert SoloAdventureRuntime(test_db).current(room_id)["node_id"] == "201"
    assert get_encounter(test_db, "solo-bear-outcome-encounter")["status"] == "resolved"


def test_solo_ending_transition_completes_the_room(test_db):
    from src.server.encounter_persistence import create_encounter

    room_id, _ = _setup_solo_room(test_db)
    create_encounter(test_db, "ending-encounter", room_id, status="active")
    test_db.execute(
        "INSERT INTO characters "
        "(character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('ending-character', %s, '玩家', 'ending-token', '{}')",
        (room_id,),
    )
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('ending-pending-action', %s, 'ending-character', "
        "'dialogue', 'pending after ending', 'queued')",
        (room_id,),
    )
    test_db.commit()
    runtime = SoloAdventureRuntime(test_db)
    runtime.transition(room_id, from_node_id="1", target_node_id="2")
    runtime.transition(room_id, from_node_id="2", target_node_id="3")

    result = runtime.transition(room_id, from_node_id="3", target_node_id="4")

    room = test_db.execute(
        "SELECT status FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()
    encounter = test_db.execute(
        "SELECT status FROM encounters WHERE encounter_id = 'ending-encounter'"
    ).fetchone()
    assert result["is_ending"] is True
    assert room["status"] == "completed"
    assert encounter["status"] == "resolved"
    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = 'ending-pending-action'"
    ).fetchone()["status"] == "canceled"
    assert test_db.execute(
        "SELECT ending_type FROM campaign_archives WHERE room_id = %s",
        (room_id,),
    ).fetchone()["ending_type"] == "mixed"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM events "
        "WHERE room_id = %s AND event_type = 's2c_campaign_ended'",
        (room_id,),
    ).fetchone()["count"] == 1


def test_solo_ending_transition_rolls_back_scene_and_encounter_when_archive_fails(
    test_db,
    monkeypatch,
):
    import src.server.campaign_archive as archive_module
    from src.server.encounter_persistence import create_encounter

    room_id, _ = _setup_solo_room(test_db)
    create_encounter(test_db, "ending-rollback-encounter", room_id, status="active")
    runtime = SoloAdventureRuntime(test_db)
    runtime.transition(room_id, from_node_id="1", target_node_id="2")
    runtime.transition(room_id, from_node_id="2", target_node_id="3")

    def fail_archive(*_args, **_kwargs):
        raise RuntimeError("injected-solo-archive-failure")

    monkeypatch.setattr(archive_module, "_insert_minimal_archive", fail_archive)

    with pytest.raises(RuntimeError, match="injected-solo-archive-failure"):
        runtime.transition(room_id, from_node_id="3", target_node_id="4")

    assert runtime.current(room_id)["node_id"] == "3"
    assert test_db.execute(
        "SELECT status FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["status"] == "lobby"
    assert test_db.execute(
        "SELECT status FROM encounters WHERE encounter_id = 'ending-rollback-encounter'"
    ).fetchone()["status"] == "active"
    assert test_db.execute(
        "SELECT 1 FROM campaign_archives WHERE room_id = %s",
        (room_id,),
    ).fetchone() is None
    assert test_db.execute(
        "SELECT 1 FROM events "
        "WHERE room_id = %s AND event_type = 's2c_campaign_ended'",
        (room_id,),
    ).fetchone() is None


def test_conditional_ending_marker_with_successor_does_not_complete_room(test_db):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    test_db.execute(
        """
        UPDATE content_items
        SET payload = %s
        WHERE scenario_version_id = %s
          AND item_type = 'branch_node'
          AND logical_key = '3'
        """,
        (
            json.dumps(
                {
                    "node_id": "3",
                    "title": "条目 3",
                    "text": "火焰造成伤害。若生命归零，你会烧死。【剧终】否则，转到4。",
                    "target_node_ids": ["4"],
                },
                ensure_ascii=False,
            ),
            scenario_version_id,
        ),
    )
    runtime = SoloAdventureRuntime(test_db)
    runtime.transition(room_id, from_node_id="1", target_node_id="2")

    result = runtime.transition(room_id, from_node_id="2", target_node_id="3")

    room = test_db.execute(
        "SELECT status FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()
    assert result["is_ending"] is False
    assert room["status"] == "lobby"
    assert runtime.current(room_id)["node_id"] == "3"


def test_reconnect_restores_solo_scene_snapshot(client, test_db):
    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data)
        VALUES ('solo-reconnect-character', %s, '玩家', 'solo-reconnect-token', %s)
        """,
        (room_id, json.dumps({})),
    )
    SoloAdventureRuntime(test_db).transition(
        room_id, from_node_id="1", target_node_id="2"
    )

    response = client.get(
        "/api/player/reconnect", headers={"X-Room-Token": "solo-reconnect-token"}
    )

    assert response.status_code == 200
    assert response.json()["sceneState"] == {
        "currentScene": "solo:2",
        "visitedScenes": ["solo:1", "solo:2"],
        "version": 1,
    }
