"""Conservative routing policy for actions submitted while the Host is away."""

import json
from dataclasses import dataclass
from typing import Any, Literal


HostAutonomyPolicy = Literal["host_required", "conservative", "delegated"]
HostAutonomyRoute = Literal[
    "host_online",
    "offline_autonomy",
    "deferred_host_review",
    "engine_policy",
]

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
AI_ONLY_HOST_ADJUDICATION_DISABLED = "AI_ONLY_HOST_ADJUDICATION_DISABLED"


@dataclass(frozen=True)
class AiOnlyResolutionPolicy:
    """Explicit boundary for ordinary action resolution in an AI-only room."""

    session_mode: str | None = None

    @property
    def enabled(self) -> bool:
        return self.session_mode == "ai_only"

    def host_exception_reason(self, resolution_route: str | None) -> str | None:
        if self.enabled and resolution_route == "host_exception":
            return "ai_only_host_exception_forbidden"
        return None


def is_ai_only_room(conn, room_id: str) -> bool:
    """Return whether the bound runtime package explicitly opts into AI-only."""
    return AiOnlyResolutionPolicy(session_mode=room_session_mode(conn, room_id)).enabled


def host_adjudication_block_detail() -> dict[str, str]:
    """Stable, non-sensitive error payload for blocked Host adjudication APIs."""
    return {
        "code": AI_ONLY_HOST_ADJUDICATION_DISABLED,
        "reason": "纯 AI 房间不允许 Host 进行游戏内裁决",
    }


def room_session_mode(conn, room_id: str) -> str | None:
    row = conn.execute(
        "SELECT rooms.session_mode, packages.runtime_package "
        "FROM rooms "
        "LEFT JOIN runtime_package_versions AS packages "
        "ON packages.runtime_package_version_id = rooms.runtime_package_version_id "
        "WHERE rooms.room_id = %s",
        (room_id,),
    ).fetchone()
    persisted_mode = str(row.get("session_mode") or "").strip() if row else ""
    if persisted_mode:
        return persisted_mode
    runtime_package = row.get("runtime_package") if row else None
    if isinstance(runtime_package, str):
        try:
            runtime_package = json.loads(runtime_package)
        except json.JSONDecodeError:
            runtime_package = {}
    if not isinstance(runtime_package, dict):
        return None
    runtime_policy = runtime_package.get("runtime_policy")
    if not isinstance(runtime_policy, dict):
        return None
    value = runtime_policy.get("session_mode")
    return str(value) if value else None


@dataclass(frozen=True)
class HostAutonomyDecision:
    route: HostAutonomyRoute
    reason_code: str | None = None


def decide_host_autonomy(
    *,
    policy: str | None,
    session_mode: str | None = None,
    host_connected: bool,
    intent_type: str,
    params: dict[str, Any] | None,
) -> HostAutonomyDecision:
    """Classify an action without trusting client-supplied safety declarations."""
    analysis = _analysis(params)
    if AiOnlyResolutionPolicy(session_mode=session_mode).enabled:
        if _is_engine_resolvable(intent_type, params or {}, analysis):
            return HostAutonomyDecision(route="offline_autonomy")
        return HostAutonomyDecision(
            route="engine_policy",
            reason_code="ai_only_policy_required",
        )

    if host_connected:
        return HostAutonomyDecision(route="host_online")

    normalized_policy = policy if policy in _ALLOWED_POLICIES else "host_required"
    if normalized_policy == "host_required":
        return HostAutonomyDecision(
            route="deferred_host_review",
            reason_code="host_offline_policy",
        )

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


def _is_engine_resolvable(
    intent_type: str,
    params: dict[str, Any],
    analysis: dict[str, Any],
) -> bool:
    if intent_type not in _DELEGATED_INTENT_TYPES:
        return False
    if analysis.get("visibility", "public") != "public":
        return False
    if (
        bool(params.get("secretMove"))
        or bool(params.get("spendLuck"))
        or bool(params.get("pushed"))
    ):
        return False
    requirements = analysis.get("confirmation_requirements")
    if isinstance(requirements, list) and any(
        item in _BLOCKING_CONFIRMATIONS for item in requirements
    ):
        return False
    if intent_type == "move" and not str(params.get("targetNodeId") or "").strip():
        return False
    return True


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
