ACTION_STATUSES = {
    "analyzing",
    "awaiting_confirmation",
    "queued",
    "batched",
    "resolving",
    "awaiting_player_choice",
    "awaiting_host_exception",
    "completed",
    "rejected",
    "canceled",
    "timeout",
    "sync_required",
}

_TERMINAL_STATUSES = {"completed", "rejected", "canceled", "timeout"}
_TRANSITIONS = {
    "analyzing": {"awaiting_confirmation", "canceled", "timeout"},
    "awaiting_confirmation": {"queued", "canceled", "timeout", "sync_required"},
    "queued": {"batched", "resolving", "canceled", "rejected", "timeout", "sync_required"},
    "batched": {"resolving", "canceled", "rejected", "timeout", "sync_required"},
    "resolving": {
        "awaiting_player_choice",
        "awaiting_host_exception",
        "completed",
        "rejected",
        "timeout",
        "sync_required",
    },
    "awaiting_player_choice": {"resolving", "completed", "rejected", "timeout", "sync_required"},
    "awaiting_host_exception": {
        "resolving",
        "awaiting_player_choice",
        "completed",
        "rejected",
        "timeout",
        "sync_required",
    },
    "sync_required": {"awaiting_confirmation", "queued", "rejected", "timeout"},
    "completed": set(),
    "rejected": set(),
    "canceled": set(),
    "timeout": set(),
}


def is_allowed_transition(current: str, next_status: str) -> bool:
    return next_status in _TRANSITIONS.get(current, set())


def can_cancel_action(status: str) -> bool:
    return status in {"queued", "batched"}


def is_terminal_status(status: str) -> bool:
    return status in _TERMINAL_STATUSES
