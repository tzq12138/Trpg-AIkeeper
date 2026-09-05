from pathlib import Path


PROMPTS = Path(__file__).parents[2] / "kp_mcp_server" / "prompts"


def test_ai_only_prompt_contract_keeps_engine_and_consent_boundaries_explicit():
    soul = (PROMPTS / "soul.md").read_text(encoding="utf-8")
    rules = (PROMPTS / "rules.md").read_text(encoding="utf-8")
    contract = (PROMPTS / "contract.md").read_text(encoding="utf-8")

    assert "引擎权威原则" in soul
    assert "RiskContract" in soul
    assert "ActionConsent" in soul
    assert "Provider 失败时用空对象" in soul
    assert "runtime_eligible=true" in rules
    assert "authoritative_mechanic_plan" in rules
    assert "RollReceipt" in rules
    assert "ProviderFailure" in rules
    assert "resolutionId" in contract
    assert "proposal_only" in contract
    assert "SpoilerGuard" in contract
    assert "ProjectionDispatcher" in contract
    assert "resolutionOutcome" in contract
