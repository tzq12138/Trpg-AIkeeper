import pytest

from src.server.engine.action_state import (
    ACTION_STATUSES,
    RESOLUTION_OUTCOMES,
    ROOM_RUNTIME_STATUSES,
    can_cancel_action,
    is_allowed_transition,
    is_resolution_outcome,
    is_room_runtime_status,
    is_terminal_status,
)


def test_action_state_registry_matches_v2_contract():
    assert ACTION_STATUSES == {
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


@pytest.mark.parametrize(
    ("current", "next_status"),
    [
        ("analyzing", "awaiting_confirmation"),
        ("awaiting_confirmation", "queued"),
        ("awaiting_player_consent", "queued"),
        ("awaiting_player_consent", "rejected"),
        ("armed", "queued"),
        ("armed", "completed"),
        ("queued", "batched"),
        ("queued", "resolving"),
        ("batched", "resolving"),
        ("batched", "awaiting_host_exception"),
        ("resolving", "queued"),
        ("resolving", "awaiting_player_choice"),
        ("resolving", "awaiting_host_exception"),
        ("resolving", "completed"),
        ("awaiting_player_choice", "resolving"),
        ("awaiting_host_exception", "resolving"),
    ],
)
def test_allowed_state_transitions(current, next_status):
    assert is_allowed_transition(current, next_status) is True


@pytest.mark.parametrize("status", ["awaiting_player_consent", "armed", "queued", "batched"])
def test_action_can_be_canceled_only_before_resolving(status):
    assert can_cancel_action(status) is True


@pytest.mark.parametrize(
    "status",
    [
        "resolving",
        "awaiting_player_choice",
        "awaiting_host_exception",
        "completed",
        "rejected",
        "canceled",
        "timeout",
        "sync_required",
    ],
)
def test_action_cannot_be_canceled_after_resolving_or_terminal(status):
    assert can_cancel_action(status) is False


@pytest.mark.parametrize("status", ["completed", "rejected", "canceled", "timeout"])
def test_terminal_statuses_have_no_outgoing_transition(status):
    assert is_terminal_status(status) is True
    assert all(is_allowed_transition(status, target) is False for target in ACTION_STATUSES)


def test_unknown_status_is_rejected():
    assert is_allowed_transition("queued", "made_up") is False


def test_action_room_and_resolution_dimensions_are_distinct():
    # Frozen D04: room runtime statuses use `lobby`/`ended` (not `aborted`),
    # resolution outcomes use `partial_success`/`blocked`/`not_applicable`
    # (not `partial`/`rejected`).
    assert ROOM_RUNTIME_STATUSES == {
        "lobby",
        "running",
        "paused_by_owner",
        "paused_system",
        "recovering",
        "ended",
    }
    assert RESOLUTION_OUTCOMES == {
        "success",
        "failure",
        "partial_success",
        "no_check",
        "blocked",
        "not_applicable",
    }
    assert is_room_runtime_status("paused_system") is True
    assert is_room_runtime_status("ended") is True
    assert is_room_runtime_status("aborted") is False
    assert is_terminal_status("paused_system") is False
    assert is_resolution_outcome("failure") is True
    assert is_resolution_outcome("partial_success") is True
    assert is_resolution_outcome("blocked") is True
    assert is_resolution_outcome("rejected") is False
    assert is_allowed_transition("resolving", "paused_system") is False
