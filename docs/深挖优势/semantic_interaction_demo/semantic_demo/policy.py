from __future__ import annotations

from .models import (
    Ambiguity,
    DiscourseAct,
    FrameType,
    Handling,
    RiskLevel,
    SemanticCandidate,
)


HIGH_RISK_FRAMES = {
    FrameType.TRANSFER_ITEM,
    FrameType.USE_ITEM,
}
MEDIUM_RISK_FRAMES = {
    FrameType.MOVE,
    FrameType.SEARCH,
    FrameType.OBSERVE,
    FrameType.CREATIVE_ACTION,
}


class SemanticRiskPolicy:
    def decide(
        self, candidate: SemanticCandidate, ambiguities: list[Ambiguity]
    ) -> tuple[RiskLevel, Handling]:
        if candidate.discourse_act in {
            DiscourseAct.PROPOSAL,
            DiscourseAct.RULE_QUERY,
            DiscourseAct.PRIVATE_NOTE,
            DiscourseAct.OOC,
        }:
            return RiskLevel.NONE, Handling.DISCUSSION_ONLY

        if ambiguities:
            return self._risk(candidate), Handling.NEEDS_CLARIFICATION

        risk = self._risk(candidate)
        if risk in {RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL}:
            return risk, Handling.REQUIRES_CONFIRMATION
        return risk, Handling.SAFE_AUTO_EXECUTE

    @staticmethod
    def _risk(candidate: SemanticCandidate) -> RiskLevel:
        frames = {step.frame for step in candidate.steps}
        if frames & HIGH_RISK_FRAMES:
            return RiskLevel.HIGH
        if frames & MEDIUM_RISK_FRAMES or len(candidate.steps) > 1:
            return RiskLevel.MEDIUM
        if not frames:
            return RiskLevel.NONE
        return RiskLevel.LOW
