"""Deterministic aggregation and release gates for AI-only benchmark runs.

This module deliberately does not fabricate sessions. Callers provide one
observation per fixed-seed session; the resulting report keeps denominators,
scope, hard blockers, and observation thresholds separate.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Iterable


# Any ending the Engine deterministically submits from the frozen runtime
# package counts as a valid authored ending (spec: 有效结局必须是作者结局被
# 确定性触发并提交); never restrict the numerator to victory/mixed only.
_AUTHORED_ENDING_TYPES = {"victory", "mixed", "defeat", "safe_abort"}

PERSONA_IDS = (
    "normal",
    "cautious",
    "aggressive",
    "divergent",
    "rules_lawyer",
    "silent",
    "high_frequency",
    "spoiler_probe",
    "conflict",
)

_OBSERVE_THRESHOLDS = {
    "clarification_ratio": 0.15,
    "player_correction_ratio": 0.05,
    "unnecessary_check_ratio": 0.10,
    "valid_ending_rate": 0.80,
    "ordinary_action_p95_ms": 15000,
    "player_rating_average": 4.0,
}


@dataclass(frozen=True, slots=True)
class BenchmarkObservation:
    session_id: str
    player_count: int
    persona: str
    ending_type: str | None = None
    accepted_actions: int = 0
    clarification_count: int = 0
    unnecessary_check_count: int = 0
    player_correction_count: int = 0
    ordinary_action_latencies_ms: tuple[int, ...] = ()
    host_adjudication_count: int = 0
    ai_only_host_exception_count: int = 0
    severe_spoiler_count: int = 0
    illegal_state_mutation_count: int = 0
    duplicate_roll_count: int = 0
    duplicate_submission_count: int = 0
    deadlock_count: int = 0
    trace_actions: int = 0
    trace_complete_actions: int = 0
    silent_misinterpretation_count: int = 0
    real_browser_session_count: int = 0
    player_ratings: tuple[float, ...] = ()


def aggregate_benchmark(
    observations: Iterable[BenchmarkObservation],
    *,
    browser_observations: Iterable[BenchmarkObservation] = (),
) -> dict:
    """Aggregate fixed-seed AI-only sessions into a release report.

    Args:
        observations: simulation sessions only (never fabricate sessions).
        browser_observations: real browser sessions, counted independently
            (V2); each item is one real session and contributes its ratings.
    Returns:
        Report dict with sample/metrics/hard_blockers/release_blockers.
    """
    sessions = list(observations)
    browser_sessions = list(browser_observations)
    accepted_actions = sum(max(0, item.accepted_actions) for item in sessions)
    clarification_count = sum(max(0, item.clarification_count) for item in sessions)
    correction_count = sum(max(0, item.player_correction_count) for item in sessions)
    unnecessary_check_count = sum(
        max(0, item.unnecessary_check_count) for item in sessions
    )
    ending_count = sum(
        item.ending_type in _AUTHORED_ENDING_TYPES for item in sessions
    )
    raw_latencies = [
        float(value)
        for item in sessions
        for value in item.ordinary_action_latencies_ms
    ]
    # Non-finite values are rejected by validation below; keep them out of the
    # p95 computation so int() never crashes on NaN/Inf.
    latencies = [
        int(value) for value in raw_latencies if _finite_positive(value)
    ]
    player_ratings = [
        max(0.0, float(value))
        for item in browser_sessions
        for value in item.player_ratings
    ]
    real_browser_sessions = len(browser_sessions)
    silent_misunderstanding_total = sum(
        max(0, item.silent_misinterpretation_count) for item in sessions
    )
    session_ids = [str(item.session_id) for item in sessions]
    invalid_values: list[str] = []
    if len(session_ids) != len(set(session_ids)):
        invalid_values.append("duplicate_session_ids")
    for item in sessions:
        for latency in item.ordinary_action_latencies_ms:
            if not _finite_positive(latency, integer=True):
                invalid_values.append("non_finite_or_negative_latency")
        for rating in item.player_ratings:
            if not _finite_range(rating, 1.0, 5.0):
                invalid_values.append("rating_out_of_range")
        for count_field in (
            "accepted_actions",
            "clarification_count",
            "unnecessary_check_count",
            "player_correction_count",
            "host_adjudication_count",
            "ai_only_host_exception_count",
            "severe_spoiler_count",
            "illegal_state_mutation_count",
            "duplicate_roll_count",
            "duplicate_submission_count",
            "deadlock_count",
            "trace_actions",
            "trace_complete_actions",
            "silent_misinterpretation_count",
        ):
            if getattr(item, count_field, 0) is not None and int(
                getattr(item, count_field) or 0
            ) < 0:
                invalid_values.append("negative_count")
        if int(item.trace_complete_actions or 0) > int(item.trace_actions or 0):
            invalid_values.append("trace_complete_exceeds_total")

    metrics = {
        "clarification_ratio": _ratio_metric(
            clarification_count,
            accepted_actions,
            "accepted_player_actions",
        ),
        "player_correction_ratio": _ratio_metric(
            correction_count,
            accepted_actions,
            "accepted_player_actions",
        ),
        "unnecessary_check_ratio": _ratio_metric(
            unnecessary_check_count,
            accepted_actions,
            "accepted_player_actions",
        ),
        "valid_ending_rate": _ratio_metric(
            ending_count,
            len(sessions),
            "benchmark_sessions",
        ),
        "ordinary_action_p95_ms": _latency_metric(latencies),
        "silent_misinterpretation_count": _count_metric(
            silent_misunderstanding_total,
            len(sessions),
            "benchmark_sessions",
        ),
        "player_rating_average": _rating_metric(player_ratings),
    }

    hard_blockers = {
        key: total
        for key, total in {
            "host_adjudication_count": sum(
                max(0, item.host_adjudication_count) for item in sessions
            ),
            "ai_only_host_exception_count": sum(
                max(0, item.ai_only_host_exception_count) for item in sessions
            ),
            "severe_spoiler_count": sum(
                max(0, item.severe_spoiler_count) for item in sessions
            ),
            "illegal_state_mutation_count": sum(
                max(0, item.illegal_state_mutation_count) for item in sessions
            ),
            "duplicate_roll_count": sum(
                max(0, item.duplicate_roll_count) for item in sessions
            ),
            "duplicate_submission_count": sum(
                max(0, item.duplicate_submission_count) for item in sessions
            ),
            "deadlock_count": sum(
                max(0, item.deadlock_count) for item in sessions
            ),
            "trace_incomplete_actions": sum(
                max(0, item.trace_actions - item.trace_complete_actions)
                for item in sessions
            ),
        }.items()
        if total
    }

    observe_threshold_breaches: list[str] = []
    for key in (
        "clarification_ratio",
        "player_correction_ratio",
        "unnecessary_check_ratio",
    ):
        value = metrics[key]["value"]
        if value is not None and value > _OBSERVE_THRESHOLDS[key]:
            observe_threshold_breaches.append(key)
    ending_rate = metrics["valid_ending_rate"]["value"]
    if ending_rate is not None and ending_rate < _OBSERVE_THRESHOLDS["valid_ending_rate"]:
        observe_threshold_breaches.append("valid_ending_rate")
    p95 = metrics["ordinary_action_p95_ms"]["value"]
    if p95 is not None and p95 > _OBSERVE_THRESHOLDS["ordinary_action_p95_ms"]:
        observe_threshold_breaches.append("ordinary_action_p95_ms")
    # D25 quality gate: mechanically influential silent misinterpretations must be zero.
    if silent_misunderstanding_total > 0:
        observe_threshold_breaches.append("silent_misinterpretation_count")
    rating_average = metrics["player_rating_average"]["value"]
    if rating_average is not None and rating_average < _OBSERVE_THRESHOLDS["player_rating_average"]:
        observe_threshold_breaches.append("player_rating_average")

    two_player_sessions = sum(item.player_count == 2 for item in sessions)
    four_player_sessions = sum(item.player_count == 4 for item in sessions)
    release_blockers: list[str] = []
    if len(sessions) < 30:
        release_blockers.append("sample_size")
    if two_player_sessions < 15:
        release_blockers.append("two_player_sample")
    if four_player_sessions < 15:
        release_blockers.append("four_player_sample")
    if real_browser_sessions < 2:
        release_blockers.append("real_browser_evidence")
    if hard_blockers:
        release_blockers.append("hard_blockers")
    if invalid_values:
        release_blockers.append("invalid_observation_values")
    # Missing evidence is an independent blocker even at full sample size:
    # required ratios/latency/ratings denominators of zero and actions that
    # never entered the pipeline must never read as clean zeros (V2).
    metric_evidence_missing = (
        accepted_actions == 0
        or not latencies
        or not player_ratings
        or real_browser_sessions == 0
    )
    if metric_evidence_missing:
        release_blockers.append("missing_metric_evidence")
    trace_evidence_missing = (
        sum(max(0, item.trace_actions) for item in sessions) == 0
        or any(
            int(item.trace_actions or 0) > 0
            and int(item.trace_complete_actions or 0) == 0
            for item in sessions
        )
    )
    if trace_evidence_missing:
        release_blockers.append("missing_trace_evidence")
    if browser_sessions and not any(
        item.player_ratings for item in browser_sessions
    ):
        release_blockers.append("browser_evidence_invalid")
    release_blockers.extend(observe_threshold_breaches)

    return {
        "sample": {
            "sessions": len(sessions),
            "two_player_sessions": two_player_sessions,
            "four_player_sessions": four_player_sessions,
            "personas": sorted({item.persona for item in sessions}),
            "scope": "fixed_seed_ai_only_sessions",
        },
        "metrics": metrics,
        "hard_blockers": hard_blockers,
        "observe_threshold_breaches": observe_threshold_breaches,
        "release_blockers": release_blockers,
        "release_ready": not release_blockers,
    }


def _ratio_metric(numerator: int, denominator: int, scope: str) -> dict:
    if denominator <= 0:
        return {
            "numerator": numerator,
            "denominator": denominator,
            "value": None,
            "scope": scope,
            "status": "not_measurable",
        }
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": round(numerator / denominator, 4),
        "scope": scope,
    }


def _latency_metric(values: list[int]) -> dict:
    if not values:
        return {
            "numerator": 0,
            "denominator": 0,
            "value": None,
            "scope": "ordinary_player_actions_with_resolution_latency",
            "status": "not_measurable",
        }
    ordered = sorted(values)
    rank = max(1, ceil(len(ordered) * 0.95))
    return {
        "numerator": rank,
        "denominator": len(ordered),
        "value": ordered[rank - 1],
        "scope": "ordinary_player_actions_with_resolution_latency",
    }


def _count_metric(numerator: int, denominator: int, scope: str) -> dict:
    if denominator <= 0:
        return {
            "numerator": numerator,
            "denominator": denominator,
            "value": None,
            "scope": scope,
            "status": "not_measurable",
        }
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator,
        "scope": scope,
    }


def _rating_metric(values: list[float]) -> dict:
    if not values:
        return {
            "numerator": 0,
            "denominator": 0,
            "value": None,
            "scope": "real_browser_player_ratings",
            "status": "not_measurable",
        }
    average = round(sum(values) / len(values), 2)
    return {
        "numerator": average,
        "denominator": len(values),
        "value": average,
        "scope": "real_browser_player_ratings",
    }


def _finite_positive(value, *, integer: bool = False) -> bool:
    """True when value is a finite, non-negative number (int check optional)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    if number < 0 or number != number or number in (float("inf"), float("-inf")):
        return False
    if integer and int(number) != number:
        return False
    return True


def _finite_range(value, low: float, high: float) -> bool:
    """True when value is finite and inside [low, high]."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number == number and low <= number <= high
