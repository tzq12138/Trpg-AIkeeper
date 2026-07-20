"""Conservative routing policy for actions submitted while the Host is away."""

from dataclasses import dataclass
from typing import Any, Literal


HostAutonomyPolicy = Literal["host_required", "conservative", "delegated"]
HostAutonomyRoute = Literal["host_online", "offline_autonomy", "deferred_host_review"]

_ALLOWED_POLICIES = {"host_required", "conservative", "delegated"}
_BLOCKING_CONFIRMATIONS = {
    "attack",
    "irreversible_consequence",
    "luck_spend",
    "pushed_roll",
    "secret_action",
    "visibility_change",
}
_DELEGATED_INTENT_TYPES = {"dialogue", "move", "skill_check", "use_item"}


@dataclass(frozen=True)
class HostAutonomyDecision:
    route: HostAutonomyRoute
    reason_code: str | None = None


def decide_host_autonomy(
    *,
    policy: str | None,
    host_connected: bool,
    intent_type: str,
    params: dict[str, Any] | None,
) -> HostAutonomyDecision:
    """Classify an action without trusting client-supplied safety declarations."""
    if host_connected:
        return HostAutonomyDecision(route="host_online")

    normalized_policy = policy if policy in _ALLOWED_POLICIES else "host_required"
    if normalized_policy == "host_required":
        return HostAutonomyDecision(
            route="deferred_host_review",
            reason_code="host_offline_policy",
        )

    analysis = _analysis(params)
    if not _is_public_and_compensable(intent_type, params or {}, analysis):
        return HostAutonomyDecision(
            route="deferred_host_review",
            reason_code="host_offline_policy",
        )

    if normalized_policy == "conservative":
        if intent_type != "dialogue" or analysis.get("risk") != "low":
            return HostAutonomyDecision(
                route="deferred_host_review",
                reason_code="host_offline_policy",
            )

    return HostAutonomyDecision(route="offline_autonomy")


def _analysis(params: dict[str, Any] | None) -> dict[str, Any]:
    value = params.get("analysis") if isinstance(params, dict) else None
    return value if isinstance(value, dict) else {}


def _is_public_and_compensable(
    intent_type: str,
    params: dict[str, Any],
    analysis: dict[str, Any],
) -> bool:
    if intent_type not in _DELEGATED_INTENT_TYPES:
        return False
    if analysis.get("risk") not in {"low", "medium"}:
        return False
    if analysis.get("visibility", "public") != "public":
        return False
    if bool(params.get("secretMove")) or bool(params.get("spendLuck")) or bool(params.get("pushed")):
        return False
    requirements = analysis.get("confirmation_requirements")
    if isinstance(requirements, list) and any(
        item in _BLOCKING_CONFIRMATIONS for item in requirements
    ):
        return False
    if intent_type == "move" and not str(params.get("targetNodeId") or "").strip():
        return False
    return True
