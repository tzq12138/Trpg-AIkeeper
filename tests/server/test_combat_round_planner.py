from src.server.combat_round_planner import (
    apply_combat_round_suggestions,
    build_combat_round_ai_context,
    build_combat_round_plan,
    record_combat_round_public_fact,
)


def test_combat_round_plan_uses_dexterity_not_submission_order():
    plan = build_combat_round_plan(
        turn_id="combat-turn",
        encounter_id="combat-encounter",
        round_number=4,
        actions=[
            {
                "action_id": "late-fast",
                "character_id": "fast",
                "intent_type": "combat_action",
                "declared_intent": "我朝走廊中的人影开枪",
                "dex": 80,
            },
            {
                "action_id": "early-slow",
                "character_id": "slow",
                "intent_type": "combat_action",
                "declared_intent": "我掩护安娜后退",
                "dex": 40,
            },
        ],
    )

    assert [step["action_id"] for step in plan["steps"]] == ["late-fast", "early-slow"]
    assert [step["global_order"] for step in plan["steps"]] == [1, 2]
    assert plan["steps"][0]["rule_binding"] == "combat_action"
    assert plan["steps"][0]["visibility"] == "public"


def test_combat_round_plan_honors_confirmed_collaboration_dependencies_before_dexterity():
    plan = build_combat_round_plan(
        turn_id="combat-turn",
        encounter_id="combat-encounter",
        round_number=4,
        actions=[
            {
                "action_id": "fast-dependent",
                "character_id": "fast",
                "intent_type": "combat_action",
                "declared_intent": "I wait for the door to open before firing.",
                "params": {"depends_on_action_ids": ["slow-opener"]},
                "dex": 80,
            },
            {
                "action_id": "slow-opener",
                "character_id": "slow",
                "intent_type": "combat_action",
                "declared_intent": "I force the door open.",
                "dex": 40,
            },
        ],
    )

    assert [step["action_id"] for step in plan["steps"]] == [
        "slow-opener",
        "fast-dependent",
    ]
    assert plan["steps"][1]["depends_on"] == ["slow-opener"]


def test_combat_round_plan_keeps_only_two_declared_segments_and_never_invents_absent_actions():
    plan = build_combat_round_plan(
        turn_id="combat-turn",
        encounter_id="combat-encounter",
        round_number=4,
        actions=[
            {
                "action_id": "combo",
                "character_id": "investigator",
                "intent_type": "combat_action",
                "declared_intent": "我开枪、掩护安娜撤退、再冲去开门",
                "dex": 60,
            },
            {
                "action_id": "idle",
                "character_id": "absent-player",
                "intent_type": "system_skip",
                "declared_intent": "本回合跳过: idle",
                "dex": 70,
            },
        ],
    )

    combo = next(step for step in plan["steps"] if step["action_id"] == "combo")
    assert combo["segments"] == ["我开枪", "掩护安娜撤退"]
    assert plan["absent_policies"] == [
        {"character_id": "absent-player", "policy": "idle"}
    ]
    assert all(step["action_id"] != "idle" for step in plan["steps"])


def test_combat_round_plan_exposes_only_safe_public_observable_preparations():
    plan = build_combat_round_plan(
        turn_id="combat-turn",
        encounter_id="combat-encounter",
        round_number=4,
        actions=[
            {
                "action_id": "public-shot",
                "character_id": "ada",
                "player_name": "艾达",
                "intent_type": "combat_action",
                "declared_intent": "我朝黑暗中的人影开枪，并掩护安娜撤退。",
                "dex": 60,
            },
            {
                "action_id": "private-handoff",
                "character_id": "ben",
                "player_name": "本",
                "intent_type": "use_item",
                "declared_intent": "我偷偷把钥匙交给安娜。",
                "params": {"visibility": "private"},
                "dex": 50,
            },
        ],
    )

    assert plan["observable_preparations"] == ["艾达举起武器，保持警戒。"]
    public_payload = str(plan["observable_preparations"])
    assert "人影" not in public_payload
    assert "安娜" not in public_payload
    assert "钥匙" not in public_payload


def test_combat_round_plan_keeps_confirmed_prepared_actions_as_rule_constraints():
    plan = build_combat_round_plan(
        turn_id="combat-turn",
        encounter_id="combat-encounter",
        round_number=4,
        actions=[],
        prepared_actions=[
            {
                "action_id": "prepared-cover",
                "character_id": "ada",
                "player_name": "Ada",
                "trigger_kind": "enemy_public_attack_declared",
                "reaction_kind": "take_cover",
                "target_id": "hidden-ally-id",
                "declared_intent": "If the masked gunman attacks Ben, I take cover.",
            }
        ],
    )
    context = build_combat_round_ai_context(plan, [])

    assert plan["prepared_rule_actions"] == [
        {
            "character_id": "ada",
            "actor_name": "Ada",
            "trigger_kind": "enemy_public_attack_declared",
            "reaction_kind": "take_cover",
        }
    ]
    assert plan["observable_preparations"] == ["Ada 保持戒备，随时寻找掩护。"]
    assert context["public_prepared_actions"] == [
        {
            "actor_name": "Ada",
            "trigger_kind": "enemy_public_attack_declared",
            "reaction_kind": "take_cover",
        }
    ]
    safe_payload = str({"plan": plan, "context": context})
    assert "hidden-ally-id" not in safe_payload
    assert "masked gunman" not in safe_payload


def test_ai_round_suggestions_only_enrich_known_public_steps_without_changing_rule_order():
    actions = [
        {
            "action_id": "fast-public",
            "character_id": "fast",
            "intent_type": "combat_action",
            "declared_intent": "I fire at the doorway.",
            "dex": 80,
        },
        {
            "action_id": "slow-private",
            "character_id": "slow",
            "intent_type": "combat_action",
            "declared_intent": "I secretly take the evidence.",
            "dex": 40,
            "params": {"visibility": "private"},
        },
    ]
    plan = build_combat_round_plan(
        turn_id="combat-turn",
        encounter_id="combat-encounter",
        round_number=4,
        actions=actions,
    )

    context = build_combat_round_ai_context(plan, actions)
    enriched = apply_combat_round_suggestions(
        plan,
        {
            "clusters": [
                {
                    "actionIds": ["fast-public", "slow-private", "unknown-action"],
                    "publicTitle": "Doorway exchange",
                }
            ],
            "dependencies": [
                {
                    "actionId": "fast-public",
                    "dependsOnActionIds": ["slow-private", "unknown-action"],
                }
            ],
            "replacementOrder": ["slow-private", "fast-public"],
        },
    )

    assert [item["action_id"] for item in context["public_actions"]] == ["fast-public"]
    assert "I secretly take the evidence." not in str(context)
    assert [step["action_id"] for step in enriched["steps"]] == ["fast-public", "slow-private"]
    assert [step["global_order"] for step in enriched["steps"]] == [1, 2]
    assert enriched["steps"][0]["depends_on"] == []
    assert enriched["steps"][0]["advisory_depends_on"] == []
    assert enriched["presentation_clusters"] == [
        {
            "cluster_id": enriched["steps"][0]["cluster_id"],
            "public_title": "Doorway exchange",
            "action_ids": ["fast-public"],
            "completed_public_facts": [],
        }
    ]


def test_recorded_round_facts_keep_rule_order_and_exclude_private_actions():
    plan = build_combat_round_plan(
        turn_id="combat-turn",
        encounter_id="combat-encounter",
        round_number=4,
        actions=[
            {
                "action_id": "public-fast",
                "character_id": "ada",
                "intent_type": "combat_action",
                "declared_intent": "I fire at the doorway.",
                "dex": 80,
            },
            {
                "action_id": "private-slow",
                "character_id": "ben",
                "intent_type": "combat_action",
                "declared_intent": "I secretly take the evidence.",
                "params": {"visibility": "private"},
                "dex": 40,
            },
        ],
    )

    after_public = record_combat_round_public_fact(
        plan,
        action_id="public-fast",
        narrative_text="The doorway splinters under Ada's shot.",
    )
    after_private = record_combat_round_public_fact(
        after_public,
        action_id="private-slow",
        narrative_text="Ben finds the hidden evidence.",
    )

    assert [step["action_id"] for step in after_private["steps"]] == [
        "public-fast",
        "private-slow",
    ]
    assert after_private["resolved_public_facts"] == [
        {
            "action_id": "public-fast",
            "text": "The doorway splinters under Ada's shot.",
        }
    ]
    assert "hidden evidence" not in str(after_private)


def test_follow_up_replan_sees_only_remaining_public_actions_and_verified_facts():
    plan = build_combat_round_plan(
        turn_id="combat-turn",
        encounter_id="combat-encounter",
        round_number=4,
        actions=[
            {
                "action_id": "open-door",
                "character_id": "ada",
                "intent_type": "combat_action",
                "declared_intent": "I force the door open.",
                "dex": 80,
            },
            {
                "action_id": "cover-retreat",
                "character_id": "ben",
                "intent_type": "combat_action",
                "declared_intent": "I cover the retreat after the door opens.",
                "params": {"depends_on_action_ids": ["open-door"]},
                "dex": 40,
            },
        ],
    )
    plan = record_combat_round_public_fact(
        plan,
        action_id="open-door",
        narrative_text="The door gives way and the north exit is open.",
    )

    context = build_combat_round_ai_context(
        plan,
        [
            {
                "action_id": "cover-retreat",
                "intent_type": "combat_action",
                "declared_intent": "I cover the retreat after the door opens.",
            },
        ],
        replan_after_resolution=True,
    )
    replanned = apply_combat_round_suggestions(
        plan,
        {
            "clusters": [
                {
                    "actionIds": ["open-door", "cover-retreat"],
                    "publicTitle": "Open exit retreat",
                }
            ],
        },
        eligible_action_ids={"cover-retreat"},
    )

    assert context["replan_after_resolution"] is True
    assert context["completed_public_facts"] == [
        {"action_id": "open-door", "text": "The door gives way and the north exit is open."}
    ]
    assert context["public_actions"] == [
        {
            "action_id": "cover-retreat",
            "global_order": 2,
            "rule_binding": "combat_action",
            "declared_intent": "I cover the retreat after the door opens.",
        }
    ]
    assert [step["action_id"] for step in replanned["steps"]] == ["open-door", "cover-retreat"]
    assert replanned["presentation_clusters"][0]["action_ids"] == ["cover-retreat"]
    completed_cluster = next(
        cluster
        for cluster in replanned["presentation_clusters"]
        if cluster["action_ids"] == ["open-door"]
    )
    assert completed_cluster["public_title"] != "Open exit retreat"
