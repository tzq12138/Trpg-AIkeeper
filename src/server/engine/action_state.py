ACTION_STATUSES = {
    "analyzing",
    "awaiting_confirmation",
    "awaiting_player_consent",
    "armed",
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

# These dimensions are deliberately separate from ACTION_STATUSES.  A room can
# be paused or ended while an individual action remains resolving, and an
# action can complete with a failure outcome.
# Frozen P0-1-D04: `aborted` belongs to ending_status (owner termination),
# not to room runtime status; resolution outcomes use partial_success and
# never reuse action lifecycle terms like `rejected`.
ROOM_RUNTIME_STATUSES = {
    "lobby",
    "running",
    "paused_by_owner",
    "paused_system",
    "recovering",
    "ended",
}
RESOLUTION_OUTCOMES = {
    "success",
    "failure",
    "partial_success",
    "no_check",
    "blocked",
    "not_applicable",
}

_TERMINAL_STATUSES = {"completed", "rejected", "canceled", "timeout"}
_TRANSITIONS = {
    "analyzing": {"awaiting_confirmation", "canceled", "timeout"},
    "awaiting_confirmation": {"queued", "canceled", "timeout", "sync_required"},
    "awaiting_player_consent": {"queued", "rejected", "canceled", "timeout"},
    "armed": {"queued", "completed", "canceled", "timeout"},
    "queued": {"batched", "resolving", "canceled", "rejected", "timeout", "sync_required"},
    "batched": {"resolving", "awaiting_host_exception", "canceled", "rejected", "timeout", "sync_required"},
    "resolving": {
        "queued",  # owner pause before the first roll; no authority effect exists yet
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
    return status in {"awaiting_player_consent", "queued", "batched", "armed"}


def is_terminal_status(status: str) -> bool:
    return status in _TERMINAL_STATUSES


def is_room_runtime_status(status: str) -> bool:
    return status in ROOM_RUNTIME_STATUSES


def is_resolution_outcome(outcome: str) -> bool:
    return outcome in RESOLUTION_OUTCOMES
