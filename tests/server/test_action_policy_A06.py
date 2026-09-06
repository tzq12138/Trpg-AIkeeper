"""R6/A06 regression tests: equivalence proof must not treat absence as
equivalence, and must compare the full frozen consequence dimension set
(audience included)."""

from src.server.engine.action_policy import evaluate_action_policy

_LOW_RISK_CONTRACT = {
    "max_harm": "low",
    "irreversible_controls": [],
    "default_harm": "low",
}


def _candidate(label, interpreted, **consequences):
    candidate = {"label": label, "interpreted_intent": interpreted}
    if consequences:
        candidate["consequences"] = consequences
    return candidate


def _ambiguous_intent(candidates, **overrides):
    intent = {
        "intent_type": "skill_check",
        "declared_intent": "我检查它",
        "visibility": "public",
        "ambiguities": ["target", "skill", "risk"],
        "candidate_interpretations": candidates,
    }
    intent.update(overrides)
    return intent


def test_both_candidates_without_mechanic_never_prove_equivalence():
    """A06 counterexample #1: two candidates that BOTH omit the mechanism
    field must not route straight-through — absence on both sides is not a
    proof that the interpretations trigger identically."""
    candidates = [
        _candidate("检查目标 A", "inspect_a", target="a", difficulty="regular"),
        _candidate("检查目标 A 的另一表述", "inspect_a2", target="a", difficulty="regular"),
    ]
    decision = evaluate_action_policy(
        _ambiguous_intent(candidates),
        current_state={},
        risk_contract=_LOW_RISK_CONTRACT,
    )
    assert decision.outcome == "clarify"
    assert decision.reason_code == "material_intent_ambiguity"


def test_single_candidate_with_mechanic_against_one_without_is_not_equivalent():
    """A06 guard: mechanism present on one candidate and missing on the other
    is a material difference (pre-existing behaviour, kept explicit)."""
    candidates = [
        _candidate("检查目标 A", "inspect_a", target="a", mechanic="skill_check"),
        _candidate("检查目标 A 的另一表述", "inspect_a2", target="a"),
    ]
    decision = evaluate_action_policy(
        _ambiguous_intent(candidates),
        current_state={},
        risk_contract=_LOW_RISK_CONTRACT,
    )
    assert decision.outcome == "clarify"


def test_audience_difference_actor_vs_party_blocks_equivalence():
    """A06 counterexample #2: identical target and mechanic, but the audience
    differs (actor-only vs whole-party reveal). Audience is part of the frozen
    consequence set — the difference must surface to the player."""
    candidates = [
        _candidate(
            "检查同一目标", "inspect_target",
            target="a", mechanic="skill_check", audience="actor",
        ),
        _candidate(
            "检查同一目标的另一表述", "inspect_target_alt",
            target="a", mechanic="skill_check", audience="party",
        ),
    ]
    decision = evaluate_action_policy(
        _ambiguous_intent(candidates),
        current_state={},
        risk_contract=_LOW_RISK_CONTRACT,
    )
    assert decision.outcome == "clarify"
    assert decision.reason_code == "material_intent_ambiguity"


def test_equal_mechanic_and_audience_still_routes_straight_through():
    """Regression guard: once BOTH candidates prove the same mechanism AND the
    same audience, the straight-through route still fires (no over-block)."""
    candidates = [
        _candidate(
            "检查同一目标", "inspect_target",
            target="a", mechanic="skill_check", audience="actor",
        ),
        _candidate(
            "检查同一目标的另一表述", "inspect_target_alt",
            target="a", mechanic="skill_check", audience="actor",
        ),
    ]
    decision = evaluate_action_policy(
        _ambiguous_intent(candidates),
        current_state={},
        risk_contract=_LOW_RISK_CONTRACT,
    )
    assert decision.outcome == "allow"
    assert decision.reason_code == "consequences_equivalent"


def test_top_level_audience_participates_in_equivalence_proof():
    """A06 normalization guard: audience declared at the candidate TOP level
    (not inside the consequences block) still enters the comparison."""
    candidates = [
        {
            "label": "检查目标 A",
            "interpreted_intent": "inspect_a",
            "target": "a",
            "mechanic": "skill_check",
            "audience": "actor",
        },
        {
            "label": "检查目标 A 的另一表述",
            "interpreted_intent": "inspect_a2",
            "target": "a",
            "mechanic": "skill_check",
            "audience": "party",
        },
    ]
    decision = evaluate_action_policy(
        _ambiguous_intent(candidates),
        current_state={},
        risk_contract=_LOW_RISK_CONTRACT,
    )
    assert decision.outcome == "clarify"
