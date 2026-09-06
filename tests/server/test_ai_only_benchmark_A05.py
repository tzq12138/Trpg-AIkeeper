"""V2/A05 counterexample regression tests for aggregator hardening."""

from dataclasses import replace

from src.server.scenario.ai_only_benchmark import (
    BenchmarkObservation,
    aggregate_benchmark,
)


def _healthy_observations():
    return [
        BenchmarkObservation(
            session_id=f"session-{index}",
            player_count=2 if index < 15 else 4,
            persona=f"normal" if index % 9 == 0 else f"cautious",
            ending_type="victory" if index % 5 == 0 else "mixed",
            accepted_actions=10,
            clarification_count=1,
            unnecessary_check_count=0,
            player_correction_count=0,
            ordinary_action_latencies_ms=(1000, 2000, 3000),
            trace_actions=10,
            trace_complete_actions=10,
        )
        for index in range(30)
    ]


def _browser_observations():
    return [
        BenchmarkObservation(
            session_id="browser-1",
            player_count=2,
            persona="normal",
            ending_type="victory",
            accepted_actions=6,
            ordinary_action_latencies_ms=(1500, 2500),
            trace_actions=6,
            trace_complete_actions=6,
            player_ratings=(4.2, 4.5, 3.9),
        ),
        BenchmarkObservation(
            session_id="browser-2",
            player_count=4,
            persona="rules_lawyer",
            ending_type="mixed",
            accepted_actions=8,
            ordinary_action_latencies_ms=(2000,),
            trace_actions=8,
            trace_complete_actions=8,
            player_ratings=(4.0, 4.6),
        ),
    ]


def test_benchmark_duplicate_browser_session_ids_block_release():
    """V2/A05 counterexample: two real browser sessions sharing one session id
    must not aggregate as clean — the browser lane is as real as the sim lane."""
    browsers = _browser_observations()
    browsers[1] = replace(browsers[1], session_id="browser-1")
    report = aggregate_benchmark(
        _healthy_observations(),
        browser_observations=browsers,
    )
    assert "invalid_observation_values" in report["release_blockers"]
    assert report["release_ready"] is False


def test_benchmark_browser_hard_blocks_and_silent_misunderstanding_block_release():
    """V2/A05 counterexample: spoilers/illegal writes/repeated rolls and
    mechanically-influential silent misinterpretations in the real browser
    lane must become hard blockers, not clean zeros."""
    browsers = _browser_observations()
    browsers[0] = replace(
        browsers[0],
        severe_spoiler_count=2,
        illegal_state_mutation_count=1,
        duplicate_roll_count=1,
        silent_misinterpretation_count=1,
    )
    report = aggregate_benchmark(
        _healthy_observations(),
        browser_observations=browsers,
    )
    assert report["hard_blockers"]["severe_spoiler_count"] == 2
    assert report["hard_blockers"]["illegal_state_mutation_count"] == 1
    assert report["hard_blockers"]["duplicate_roll_count"] == 1
    assert "silent_misinterpretation_count" in report["observe_threshold_breaches"]
    assert "hard_blockers" in report["release_blockers"]
    assert report["release_ready"] is False


def test_benchmark_single_empty_session_claiming_ending_blocks_release():
    """V2/A05 counterexample: ONE simulation that keeps a declared victory but
    clears actions, trace and latency must reject — never a clean pass among
    otherwise healthy sessions."""
    observations = _healthy_observations()
    observations[7] = replace(
        observations[7],
        ending_type="victory",
        accepted_actions=0,
        trace_actions=0,
        trace_complete_actions=0,
        ordinary_action_latencies_ms=(),
    )
    report = aggregate_benchmark(
        observations,
        browser_observations=_browser_observations(),
    )
    assert "empty_session_claims_ending" in report["release_blockers"]
    assert report["release_ready"] is False


def test_benchmark_healthy_browser_lane_never_hits_new_blockers():
    """Regression guard: the healthy two-browser sample stays green after the
    V2/A05 hardening (no duplicate ids, no spoilers, all ratings present)."""
    report = aggregate_benchmark(
        _healthy_observations(),
        browser_observations=_browser_observations(),
    )
    assert "invalid_observation_values" not in report["release_blockers"]
    assert "empty_session_claims_ending" not in report["release_blockers"]
    assert "hard_blockers" not in report["release_blockers"]
    assert report["release_ready"] is True
