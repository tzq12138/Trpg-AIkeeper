"""Central event registry — single source of truth for all s2c_* event types.

All code that emits or filters events MUST reference this registry.
Hardcoded strings are deprecated; use ALL_EVENTS[name].type or the domain groups.
"""

from dataclasses import dataclass
from enum import Enum


class EventDomain(str, Enum):
    NARRATIVE = "narrative"
    ACTION = "action"
    STATE = "state"
    ROOM = "room"
    SYSTEM = "system"


@dataclass(frozen=True)
class EventDef:
    type: str
    domain: EventDomain
    audience: str  # host | player | party | system
    description: str


# ---- All 29 event types ----
ALL_EVENTS: dict[str, EventDef] = {
    # ── Narrative / reveal ──
    "s2c_reveal_transaction": EventDef(
        "s2c_reveal_transaction", EventDomain.NARRATIVE, "host",
        "KP 揭示交易（含 roll / status_delta / scene_transition / narrative_text 步骤）",
    ),
    "s2c_resume_transaction": EventDef(
        "s2c_resume_transaction", EventDomain.NARRATIVE, "host",
        "恢复被暂停的揭示交易",
    ),
    "s2c_cancel_transaction": EventDef(
        "s2c_cancel_transaction", EventDomain.NARRATIVE, "host",
        "取消当前揭示交易",
    ),
    "s2c_public_observation": EventDef(
        "s2c_public_observation", EventDomain.NARRATIVE, "party",
        "公开观察叙事——发给全队（host + player 各一份）",
    ),
    "s2c_chat_stream": EventDef(
        "s2c_chat_stream", EventDomain.NARRATIVE, "host",
        "AI 对话流式文本块",
    ),
    "s2c_scene_sync": EventDef(
        "s2c_scene_sync", EventDomain.NARRATIVE, "host",
        "场景切换同步（场景图片、描述等）",
    ),

    # ── Action lifecycle ──
    "s2c_action_queued": EventDef(
        "s2c_action_queued", EventDomain.ACTION, "player",
        "行动已入队，等待 Host / 批次触发结算",
    ),
    "s2c_action_batched": EventDef(
        "s2c_action_batched", EventDomain.ACTION, "player",
        "行动已进入批次收集器",
    ),
    "s2c_action_completed": EventDef(
        "s2c_action_completed", EventDomain.ACTION, "player",
        "行动已结算，含结果 payload",
    ),
    "s2c_action_deferred": EventDef(
        "s2c_action_deferred", EventDomain.ACTION, "player",
        "行动已进入 Host 异常队列，等待人工复核",
    ),
    "s2c_action_review_requested": EventDef(
        "s2c_action_review_requested", EventDomain.ACTION, "host",
        "玩家提交行动申诉，进入 Host 异常队列",
    ),
    "s2c_action_review_resolved": EventDef(
        "s2c_action_review_resolved", EventDomain.ACTION, "player",
        "Host 已裁决玩家行动申诉",
    ),
    "s2c_action_exception_requested": EventDef(
        "s2c_action_exception_requested", EventDomain.ACTION, "host",
        "AI 与本地链路无法安全裁决，进入 Host 异常队列",
    ),
    "s2c_action_choice_requested": EventDef(
        "s2c_action_choice_requested", EventDomain.ACTION, "player",
        "Host 异常裁决要求玩家补充选择",
    ),
    "s2c_safety_request": EventDef(
        "s2c_safety_request", EventDomain.ACTION, "host",
        "玩家安全边界请求（事件不含敏感正文）",
    ),
    "s2c_safety_state_changed": EventDef(
        "s2c_safety_state_changed", EventDomain.ACTION, "party",
        "匿名安全暂停状态发生变化",
    ),
    "s2c_tactical_prompt": EventDef(
        "s2c_tactical_prompt", EventDomain.ACTION, "player",
        "战术行动提示（AI 生成的快捷按钮）",
    ),
    "s2c_clarification_prompt": EventDef(
        "s2c_clarification_prompt", EventDomain.ACTION, "player",
        "要求玩家澄清行动意图",
    ),
    "s2c_clarification_result": EventDef(
        "s2c_clarification_result", EventDomain.ACTION, "player",
        "澄清流程结果（已采纳 / 已驳回）",
    ),

    # ── State sync ──
    "s2c_ai_stage_changed": EventDef(
        "s2c_ai_stage_changed", EventDomain.ACTION, "player",
        "Director / AI adjudication stage changed.",
    ),
    "s2c_player_clarification_required": EventDef(
        "s2c_player_clarification_required", EventDomain.ACTION, "player",
        "Director requires the player to clarify the intended action.",
    ),
    "s2c_director_plan_validated": EventDef(
        "s2c_director_plan_validated", EventDomain.ACTION, "host",
        "Director plan was validated and persisted for deterministic resolution.",
    ),
    "s2c_narration_completed": EventDef(
        "s2c_narration_completed", EventDomain.NARRATIVE, "party",
        "Narrator completed human-readable narration after deterministic resolution.",
    ),
    "s2c_ai_recovery_required": EventDef(
        "s2c_ai_recovery_required", EventDomain.ACTION, "player",
        "AI adjudication could not safely proceed and requires host recovery.",
    ),

    "s2c_state_patch": EventDef(
        "s2c_state_patch", EventDomain.STATE, "player",
        "状态增量更新（JSON Patch 格式）",
    ),
    "s2c_full_snapshot": EventDef(
        "s2c_full_snapshot", EventDomain.STATE, "player",
        "完整状态快照（断线重连用）",
    ),
    "s2c_host_snapshot": EventDef(
        "s2c_host_snapshot", EventDomain.STATE, "host",
        "Host HUD 完整快照",
    ),
    "s2c_engine_state": EventDef(
        "s2c_engine_state", EventDomain.STATE, "host",
        "引擎状态变更（idle / resolving / paused）",
    ),
    "s2c_private_notice": EventDef(
        "s2c_private_notice", EventDomain.STATE, "player",
        "仅对单个玩家可见的系统通知",
    ),
    "s2c_private_note_emergency_access": EventDef(
        "s2c_private_note_emergency_access", EventDomain.STATE, "player",
        "Host 通过二次认证紧急访问玩家私人笔记后的通知",
    ),

    # ── Room management ──
    "s2c_room_lobby_snapshot": EventDef(
        "s2c_room_lobby_snapshot", EventDomain.ROOM, "party",
        "房间大厅快照（玩家列表、就绪状态）——广播给 host 和所有 player",
    ),
    "s2c_ready_toggled": EventDef(
        "s2c_ready_toggled", EventDomain.ROOM, "party",
        "玩家就绪状态切换——广播给 host 和所有 player",
    ),
    "s2c_campaign_ended": EventDef(
        "s2c_campaign_ended", EventDomain.ROOM, "party",
        "团期结束通知",
    ),
    "s2c_turn_resolved": EventDef(
        "s2c_turn_resolved", EventDomain.ACTION, "party",
        "回合结算完成——广播给全队",
    ),
    "s2c_combat_round_locked": EventDef(
        "s2c_combat_round_locked", EventDomain.ACTION, "party",
        "战斗轮声明已锁定，进入统一结算",
    ),

    # ── Clue ──
    "s2c_clue_discovered": EventDef(
        "s2c_clue_discovered", EventDomain.ACTION, "player",
        "玩家发现新线索（仅拥有者可见）",
    ),
    "s2c_clue_shared": EventDef(
        "s2c_clue_shared", EventDomain.ACTION, "party",
        "玩家分享线索（公开版本）",
    ),
    "s2c_fact_revealed": EventDef(
        "s2c_fact_revealed", EventDomain.NARRATIVE, "party",
        "Engine 已验证并写入受众知识投影的事实揭示",
    ),
    "s2c_fact_corrected": EventDef(
        "s2c_fact_corrected", EventDomain.NARRATIVE, "party",
        "对既有事实揭示追加更正，不抹除历史可见记录",
    ),
    "s2c_fact_safety_event": EventDef(
        "s2c_fact_safety_event", EventDomain.SYSTEM, "party",
        "事实揭示被标记为安全事件（不携带安全原文）",
    ),

    # ── Checkpoint ──
    "s2c_checkpoint_created": EventDef(
        "s2c_checkpoint_created", EventDomain.SYSTEM, "system",
        "checkpoint 创建审计事件——系统可见，玩家重连时允许安全回放",
    ),
    "s2c_checkpoint_restored": EventDef(
        "s2c_checkpoint_restored", EventDomain.SYSTEM, "host",
        "checkpoint 恢复审计事件——仅 Host 可见",
    ),
    "s2c_runtime_integrity_changed": EventDef(
        "s2c_runtime_integrity_changed", EventDomain.SYSTEM, "party",
        "运行时完整性状态改变，通知参与者允许的后续操作",
    ),

    # ── Room pause / system recovery (R7 live notification contract) ──
    "s2c_room_pause_requested": EventDef(
        "s2c_room_pause_requested", EventDomain.ROOM, "system",
        "Owner 暂停请求已登记——审计行；Live 由 pause/settle 状态事件覆盖",
    ),
    "s2c_room_paused": EventDef(
        "s2c_room_paused", EventDomain.ROOM, "party",
        "房间暂停（owner 或 system integrity）——脱敏原因码，广播触发各方刷新",
    ),
    "s2c_room_resumed": EventDef(
        "s2c_room_resumed", EventDomain.ROOM, "system",
        "Owner 恢复房间——审计行（恢复后玩家经 snapshot/GET 刷新）",
    ),
    "s2c_system_recovery_proposed": EventDef(
        "s2c_system_recovery_proposed", EventDomain.ROOM, "host",
        "系统恢复方案已生成（携 proposal_id/hash）——Owner 控制台动作入口",
    ),
    "s2c_system_recovery_dry_run_verified": EventDef(
        "s2c_system_recovery_dry_run_verified", EventDomain.ROOM, "host",
        "恢复方案 dry-run 验证通过，Owner 可执行同一方案",
    ),
    "s2c_system_recovery_started": EventDef(
        "s2c_system_recovery_started", EventDomain.ROOM, "host",
        "恢复执行已开始（房间 recovering）",
    ),
    "s2c_system_recovery_completed": EventDef(
        "s2c_system_recovery_completed", EventDomain.ROOM, "party",
        "恢复完成，房间回到 running——广播触发玩家刷新原行动回执",
    ),
    "s2c_system_recovery_failed": EventDef(
        "s2c_system_recovery_failed", EventDomain.ROOM, "host",
        "恢复执行失败，房间保持/回到 paused_system（携 reason_code）",
    ),
    "s2c_review_projection_repair": EventDef(
        "s2c_review_projection_repair", EventDomain.ACTION, "system",
        "自动复核补发缺失受众通知的 DB 级 repair 行（catch-up 可见）",
    ),

    # ── System ──
    "s2c_atmosphere": EventDef(
        "s2c_atmosphere", EventDomain.SYSTEM, "host",
        "氛围控制指令（BGM / SFX / 视觉效果）",
    ),

    # ── Map ──
    "s2c_map_updated": EventDef(
        "s2c_map_updated", EventDomain.STATE, "party",
        "地图状态更新（探索节点、玩家位置变化）",
    ),
    "s2c_player_moved": EventDef(
        "s2c_player_moved", EventDomain.ACTION, "party",
        "玩家角色移动到新节点",
    ),
    "s2c_map_revealed": EventDef(
        "s2c_map_revealed", EventDomain.STATE, "party",
        "Host 手动揭示/隐藏地图节点",
    ),

    # ── Team Chat ──
    "s2c_team_message": EventDef(
        "s2c_team_message", EventDomain.ACTION, "party",
        "队伍频道消息（玩家文字/语音转写后发送）",
    ),

    # ── Encounter ──
    "s2c_encounter_suggested": EventDef(
        "s2c_encounter_suggested", EventDomain.STATE, "host",
        "AI 建议开启遭遇（战斗/追逐）",
    ),
    "s2c_encounter_started": EventDef(
        "s2c_encounter_started", EventDomain.STATE, "party",
        "遭遇已确认并开始",
    ),
    "s2c_encounter_updated": EventDef(
        "s2c_encounter_updated", EventDomain.STATE, "party",
        "遭遇状态更新（回合变化、参与者 HP/距离变化）",
    ),
    "s2c_solo_combat_reaction_requested": EventDef(
        "s2c_solo_combat_reaction_requested", EventDomain.ACTION, "player",
        "单人剧本敌方攻击要求玩家选择闪避或反击",
    ),
    "s2c_encounter_resolved": EventDef(
        "s2c_encounter_resolved", EventDomain.STATE, "party",
        "遭遇已结束",
    ),
}


# ---- Convenience accessors ----

def event_type(name: str) -> str:
    """Return the canonical event type string for the given name."""
    return ALL_EVENTS[name].type


def events_by_domain(domain: EventDomain) -> list[EventDef]:
    return [e for e in ALL_EVENTS.values() if e.domain == domain]


def host_events() -> list[str]:
    """Event types visible to host audience."""
    return [e.type for e in ALL_EVENTS.values() if e.audience in ("host", "party")]


def player_events() -> list[str]:
    """Event types visible to player audience."""
    return [e.type for e in ALL_EVENTS.values() if e.audience in ("player", "party")]
