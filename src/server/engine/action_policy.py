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

# R6 — structured consequence comparison over 12 material dimensions. Two
# candidate interpretations of the SAME declared intent are only routed
# straight-through when every dimension they both claim is equal; a dimension
# present on one candidate and missing on another is a MATERIAL difference
# (a candidate without a mechanic field can never count as "equivalent").
_MATERIAL_DIMENSIONS = (
    "target",           # 目标/指代
    "mechanic",         # 触发机制
    "difficulty",       # 难度
    "reward",           # 奖励
    "penalty",          # 惩罚
    "risk",             # 风险
    "resource",         # 资源消耗
    "skill",            # 检定技能
    "other_player_impact",   # 影响其他玩家
    "secret_reveal",         # 秘密揭示
    "irreversible",          # 不可逆资源
    "scene_transition",      # 场景转移
)
# Engine/rules/scene-internal identifiers that must never surface inside a
# player-facing candidate label.
_INTERNAL_REFERENCE_RE = re.compile(
    r"(?:scene|node|clue|fact|npc|proposal|action)[-_][a-z0-9-]{4,}"
    r"|[0-9a-f]{8,}|_id\b|sha256:|hash\b"
)


def _consequences_of(candidate: dict[str, Any]) -> dict[str, Any]:
    value = candidate.get("consequences")
    return value if isinstance(value, dict) else {}


def _canonical_dimension(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower())


def _materially_equivalent(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """True when both candidates claim the same value on every dimension.

    A dimension that only one side claims makes the pair materially
    different — absence is never treated as equivalence.
    """
    a_dims = _consequences_of(a)
    b_dims = _consequences_of(b)
    for dimension in _MATERIAL_DIMENSIONS:
        a_has = dimension in a_dims and a_dims[dimension] not in (None, "")
        b_has = dimension in b_dims and b_dims[dimension] not in (None, "")
        if a_has != b_has:
            return False
        if a_has and _canonical_dimension(a_dims[dimension]) != _canonical_dimension(
            b_dims[dimension]
        ):
            return False
    return True


def _low_risk_reversible(risk_contract: Any) -> bool:
    """Fail-closed risk gate for the straight-through route.

    Requires an explicit declaration: maximum harm is low and no irreversible
    controls are declared. Anything else (missing dict, unknown harm level,
    declared irreversible resources) keeps the clarifying route.
    """
    if not isinstance(risk_contract, dict):
        return False
    if str(risk_contract.get("max_harm") or "") != "low":
        return False
    irreversible = risk_contract.get("irreversible_controls")
    if irreversible:
        if isinstance(irreversible, list) and not irreversible:
            return True
        return False
    return True


def _leaks_internal_reference(text: str) -> bool:
    return bool(_INTERNAL_REFERENCE_RE.search(text or ""))


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
        raw_candidates = intent.get("candidate_interpretations")
        candidates = _safe_candidates(raw_candidates)
        straight_through = _straight_through_disclosure(
            raw_candidates,
            risk_contract=risk_contract,
        )
        if straight_through is not None:
            return ActionPolicyDecision(
                outcome="allow",
                reason_code="consequences_equivalent",
                disclosures=[straight_through],
            )
        return ActionPolicyDecision(
            outcome="clarify",
            reason_code="material_intent_ambiguity",
            candidates=candidates,
        )

    return ActionPolicyDecision(outcome="allow")


def _straight_through_disclosure(
    raw_candidates: Any,
    *,
    risk_contract: Any,
) -> str | None:
    """Disclosure when every candidate is materially equivalent and low-risk.

    Only candidates that actually carry a structured consequences block can
    participate in the equivalence proof; the straight-through route requires
    at least two proven-equivalent interpretations AND an explicit
    low/reversible risk contract. Any material difference — including a
    dimension claimed by only one candidate, or the presence of a
    consequences-free cancel option — keeps the clarifying route.

    Args:
        raw_candidates: candidate_interpretations list from the intent.
        risk_contract: declared risk contract (fail-closed).
    Returns:
        The disclosure text when the straight-through route is provable,
        else None.
    """
    proven: list[dict[str, Any]] = []
    if isinstance(raw_candidates, list):
        for raw in raw_candidates:
            if isinstance(raw, dict) and _consequences_of(raw):
                proven.append(raw)
    if len(proven) < 2 or not _low_risk_reversible(risk_contract):
        return None
    first = proven[0]
    for other in proven[1:]:
        if not _materially_equivalent(first, other):
            return None
    # Every proven candidate equals the first along all 12 dimensions; a
    # consequences-free alternative (e.g. cancel_action) would have made the
    # proof fail above only when listed among candidates — require that every
    # supplied candidate is either proven or filtered earlier as unsafe.
    raw_list = raw_candidates if isinstance(raw_candidates, list) else []
    for raw in raw_list:
        if isinstance(raw, dict) and not _consequences_of(raw):
            label = str(raw.get("label") or "").strip()
            if label and not _leaks_internal_reference(label):
                return None
    chosen = first.get("label") or first.get("interpreted_intent") or ""
    return (
        "按首选解释推进：{0}。其余候选在 12 维机制后果上与首选等价，"
        "且风险契约声明低风险可逆，无需二次选择。".format(str(chosen)[:120])
    )


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
                or _leaks_internal_reference(label)
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
