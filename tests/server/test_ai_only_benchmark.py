from dataclasses import replace

from src.server.scenario.ai_only_benchmark import (
    PERSONA_IDS,
    BenchmarkObservation,
    aggregate_benchmark,
)


def _healthy_observations():
    observations = []
    for index in range(30):
        player_count = 2 if index < 15 else 4
        observations.append(
            BenchmarkObservation(
                session_id=f"session-{index}",
                player_count=player_count,
                persona=PERSONA_IDS[index % len(PERSONA_IDS)],
                ending_type="victory" if index % 5 else "mixed",
                accepted_actions=10,
                clarification_count=1,
                unnecessary_check_count=0,
                player_correction_count=0,
                ordinary_action_latencies_ms=(1000, 2000, 3000),
                trace_actions=10,
                trace_complete_actions=10,
                real_browser_session_count=2 if index == 29 else 0,
                player_ratings=(4.2, 4.5, 3.9) if index == 29 else (),
            )
        )
    return observations


def test_benchmark_aggregates_sample_denominators_and_release_gate():
    report = aggregate_benchmark(_healthy_observations())

    assert report["sample"]["sessions"] == 30
    assert report["sample"]["two_player_sessions"] == 15
    assert report["sample"]["four_player_sessions"] == 15
    assert report["sample"]["scope"] == "fixed_seed_ai_only_sessions"
    assert report["metrics"]["clarification_ratio"] == {
        "numerator": 30,
        "denominator": 300,
        "value": 0.1,
        "scope": "accepted_player_actions",
    }
    assert report["hard_blockers"] == {}
    assert report["release_ready"] is True


def test_benchmark_does_not_treat_missing_denominators_as_zero_success():
    observation = BenchmarkObservation(
        session_id="empty-session",
        player_count=2,
        persona="silent",
        ending_type=None,
        accepted_actions=0,
        trace_actions=0,
        trace_complete_actions=0,
    )

    report = aggregate_benchmark([observation])

    assert report["metrics"]["clarification_ratio"]["value"] is None
    assert report["metrics"]["clarification_ratio"]["status"] == "not_measurable"
    assert report["release_ready"] is False
    assert "sample_size" in report["release_blockers"]


def test_benchmark_hard_blockers_and_observe_thresholds_are_separate():
    observations = [
        replace(item, ordinary_action_latencies_ms=(20000,))
        for item in _healthy_observations()
    ]
    observations[0] = replace(
        observations[0],
        host_adjudication_count=1,
        severe_spoiler_count=1,
        ordinary_action_latencies_ms=(20000,),
        clarification_count=20,
        trace_complete_actions=9,
    )
    report = aggregate_benchmark(observations)

    assert report["hard_blockers"] == {
        "host_adjudication_count": 1,
        "severe_spoiler_count": 1,
        "trace_incomplete_actions": 1,
    }
    assert report["metrics"]["clarification_ratio"]["value"] > 0.15
    assert report["metrics"]["ordinary_action_p95_ms"]["value"] == 20000
    assert "clarification_ratio" in report["observe_threshold_breaches"]
    assert "ordinary_action_p95_ms" in report["observe_threshold_breaches"]
    assert report["release_ready"] is False


def test_benchmark_d25_quality_gates_include_silent_misunderstanding_and_ratings():
    observations = _healthy_observations()
    report = aggregate_benchmark(observations)

    assert report["metrics"]["player_rating_average"]["value"] == 4.2
    assert "player_rating_average" not in report["observe_threshold_breaches"]
    assert "real_browser_evidence" not in report["release_blockers"]
    assert report["release_ready"] is True

    observations[1] = replace(
        observations[1],
        silent_misinterpretation_count=1,
        player_ratings=(3.2,),
    )
    report = aggregate_benchmark(observations)

    assert "silent_misinterpretation_count" in report["observe_threshold_breaches"]
    assert "player_rating_average" in report["observe_threshold_breaches"]
    assert report["release_ready"] is False


def test_benchmark_counts_every_authored_ending_as_valid():
    """Spec: 有效结局必须是被确定性触发并提交的作者结局，不限于 victory/mixed."""
    observations = _healthy_observations()
    observations[29] = replace(observations[29], ending_type="defeat")

    report = aggregate_benchmark(observations)

    assert report["metrics"]["valid_ending_rate"]["value"] == 1.0


def test_benchmark_requires_real_browser_evidence_minimum():
    report = aggregate_benchmark(_healthy_observations())
    assert "real_browser_evidence" not in report["release_blockers"]

    stripped = _healthy_observations()
    stripped[29] = replace(
        stripped[29],
        real_browser_session_count=0,
        player_ratings=(),
    )
    report = aggregate_benchmark(stripped)

    assert "real_browser_evidence" in report["release_blockers"]
    assert report["release_ready"] is False
