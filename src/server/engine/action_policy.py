from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal


PolicyOutcome = Literal["allow", "clarify", "reject", "timeout_safe_effect"]

_MECHANICAL_INTENTS = {
    "move",
    "skill_check",
    "use_item",
    "combat_action",
    "chase_action",
    "prepared_action",
    "retroactive_item_claim",
}
_FACT_CLAIM_RE = re.compile(
    r"(?:已经|早就|本来就|原本就).{0,20}(?:拿到|获得|找到|发现|拥有|知道)"
)
_UNSAFE_CANDIDATE_MARKERS = (
    "已经成功",
    "自动成功",
    "获得秘密",
    "直接得到",
    "确认世界事实",
)
_MATERIAL_AMBIGUITIES = {
    "target",
    "目标",
    "目标指代不明确",
    "resource",
    "资源",
    "skill",
    "检定",
    "risk",
    "风险",
    "safety",
    "安全解释",
    "method",
    "方法",
}


@dataclass(frozen=True)
class ActionPolicyDecision:
    outcome: PolicyOutcome
    reason_code: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    safe_effect: dict[str, Any] | None = None
    disclosures: list[str] = field(default_factory=list)


def evaluate_action_policy(
    intent: dict[str, Any],
    *,
    current_state: dict[str, Any],
    risk_contract: dict[str, Any],
    timed_out: bool = False,
) -> ActionPolicyDecision:
    del risk_contract
    intent_type = str(intent.get("intent_type") or "dialogue")
    declared_intent = str(intent.get("declared_intent") or "").strip()
    visibility = str(intent.get("visibility") or "public")
    params = intent.get("params") if isinstance(intent.get("params"), dict) else {}

    if timed_out:
        phase = str(current_state.get("phase") or "")
        if phase == "combat" or intent_type in {"combat_action", "chase_action"}:
            choice = str(params.get("timeoutChoice") or "defend")
            if choice not in {"defend", "hold", "withdraw"}:
                choice = "defend"
            return ActionPolicyDecision(
                outcome="timeout_safe_effect",
                reason_code="combat_action_timeout",
                safe_effect={
                    "effect": choice,
                    "mechanical_delta": [],
                    "rng_draws": [],
                },
            )
        return ActionPolicyDecision(
            outcome="timeout_safe_effect",
            reason_code="investigation_action_timeout",
            safe_effect={
                "effect": "cancel",
                "mechanical_delta": [],
                "rng_draws": [],
            },
        )

    if visibility == "private" and intent_type in _MECHANICAL_INTENTS:
        target = str(intent.get("target") or "目标").strip() or "目标"
        return ActionPolicyDecision(
            outcome="reject",
            reason_code="private_mechanical_action_forbidden",
            candidates=[
                {
                    "label": f"公开提出前往{target}" if intent_type == "move" else "公开重提这项行动",
                    "interpreted_intent": "public_reproposal",
                    "visibility": "public",
                },
                {
                    "label": "取消行动，不产生任何效果",
                    "interpreted_intent": "cancel_action",
                    "visibility": "private",
                },
            ],
        )

    if _FACT_CLAIM_RE.search(declared_intent):
        return ActionPolicyDecision(
            outcome="clarify",
            reason_code="player_asserted_world_fact",
            candidates=[
                {
                    "label": "尝试取得该物品或线索",
                    "interpreted_intent": "attempt_to_acquire",
                },
                {
                    "label": "询问当前是否持有该物品或线索",
                    "interpreted_intent": "ask_about_possession",
                },
                {
                    "label": "取消行动，不产生任何效果",
                    "interpreted_intent": "cancel_action",
                },
            ],
        )

    ambiguities = {
        str(item).strip()
        for item in intent.get("ambiguities") or []
        if str(item).strip()
    }
    if ambiguities and str(intent.get("ambiguity_scope") or "") == "decorative":
        return ActionPolicyDecision(
            outcome="allow",
            disclosures=["按可逆装饰性解释处理；不会改变资源、线索或规则状态"],
        )
    if ambiguities & _MATERIAL_AMBIGUITIES:
        candidates = _safe_candidates(intent.get("candidate_interpretations"))
        return ActionPolicyDecision(
            outcome="clarify",
            reason_code="material_intent_ambiguity",
            candidates=candidates,
        )

    return ActionPolicyDecision(outcome="allow")


def _safe_candidates(value: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if isinstance(value, list):
        for raw in value:
            if not isinstance(raw, dict):
                continue
            label = str(raw.get("label") or "").strip()[:160]
            interpreted = str(raw.get("interpreted_intent") or "").strip()[:80]
            if (
                not label
                or not interpreted
                or interpreted.startswith("assert_")
                or any(marker in label for marker in _UNSAFE_CANDIDATE_MARKERS)
            ):
                continue
            candidate = {"label": label, "interpreted_intent": interpreted}
            visibility = raw.get("visibility")
            if visibility in {"public", "party", "private"}:
                candidate["visibility"] = visibility
            if candidate not in candidates:
                candidates.append(candidate)
            if len(candidates) == 3:
                break
    fallbacks = [
        {
            "label": "补充具体目标、方法和愿意承担的风险",
            "interpreted_intent": "clarify_action",
        },
        {
            "label": "取消行动，不产生任何效果",
            "interpreted_intent": "cancel_action",
        },
    ]
    for fallback in fallbacks:
        if len(candidates) >= 2:
            break
        if fallback not in candidates:
            candidates.append(fallback)
    return candidates[:3]
