from __future__ import annotations

from typing import Protocol

from .models import (
    Commitment,
    ConditionCandidate,
    ConstraintCandidate,
    DiscourseAct,
    EntityKind,
    EntityMention,
    FrameType,
    SemanticCandidate,
    SemanticContextSchema,
    SemanticStep,
    UtteranceEnvelope,
)


class SemanticModel(Protocol):
    """Production implementation should call AiGateway with strict schema output."""

    def parse(
        self, utterance: UtteranceEnvelope, context: SemanticContextSchema
    ) -> SemanticCandidate: ...


class DemoSemanticModel:
    """A deterministic demo parser.

    It exists only so the example can run without an external model. In production,
    replace this class with an AiGateway adapter that returns SemanticCandidate JSON.
    """

    def parse(
        self, utterance: UtteranceEnvelope, context: SemanticContextSchema
    ) -> SemanticCandidate:
        text = utterance.raw_text.strip()
        actor = utterance.speaker_character_id

        if text.startswith("要不") or "要不要" in text:
            return self._parse_guard_plan(text, actor, proposal=True)

        if "等守卫" in text and "后门" in text:
            return self._parse_guard_plan(text, actor, proposal=False)

        if "钥匙" in text and ("给她" in text or "交给她" in text):
            return SemanticCandidate(
                discourse_act=DiscourseAct.ACTION,
                commitment=Commitment.CONFIRMED_CANDIDATE,
                macro_goal="把钥匙交给一名女性对象",
                steps=[
                    SemanticStep(
                        frame=FrameType.TRANSFER_ITEM,
                        actor_entity_id=actor,
                        item=EntityMention(
                            surface="钥匙",
                            role="item",
                            expected_kinds=[EntityKind.ITEM],
                            confidence=0.98,
                        ),
                        receiver=EntityMention(
                            surface="她",
                            role="receiver",
                            expected_kinds=[EntityKind.CHARACTER, EntityKind.NPC],
                            confidence=0.42,
                        ),
                        confidence=0.90,
                    )
                ],
                parser_confidence=0.90,
            )

        return SemanticCandidate(
            discourse_act=DiscourseAct.ACTION,
            commitment=Commitment.INTENDED,
            macro_goal=text,
            steps=[
                SemanticStep(
                    frame=FrameType.CREATIVE_ACTION,
                    actor_entity_id=actor,
                    confidence=0.55,
                )
            ],
            assumptions=["无法映射到专用框架，保留为开放创造性行动"],
            parser_confidence=0.55,
        )

    @staticmethod
    def _parse_guard_plan(
        text: str, actor: str, *, proposal: bool
    ) -> SemanticCandidate:
        wait = SemanticStep(
            frame=FrameType.WAIT,
            actor_entity_id=actor,
            condition=ConditionCandidate(
                kind="entity_action",
                subject=EntityMention(
                    surface="守卫",
                    role="condition_subject",
                    expected_kinds=[EntityKind.NPC],
                    confidence=0.96,
                ),
                predicate="pass_by",
            ),
            confidence=0.95,
        )
        move = SemanticStep(
            frame=FrameType.MOVE,
            actor_entity_id=actor,
            destination=EntityMention(
                surface="后门",
                role="destination",
                expected_kinds=[EntityKind.LOCATION, EntityKind.OBJECT],
                confidence=0.97,
            ),
            temporal_relation=f"after:{wait.step_id}",
            confidence=0.96,
        )
        observe = SemanticStep(
            frame=FrameType.OBSERVE,
            actor_entity_id=actor,
            target=EntityMention(
                surface="后门里面",
                role="target",
                expected_kinds=[EntityKind.LOCATION],
                confidence=0.72,
            ),
            temporal_relation=f"after:{move.step_id}",
            confidence=0.84,
        )
        if "不碰" in text and "信" in text:
            observe.constraints.append(
                ConstraintCandidate(
                    kind="exclude_interaction",
                    target=EntityMention(
                        surface="桌上的信",
                        role="excluded_target",
                        expected_kinds=[EntityKind.ITEM],
                        confidence=0.95,
                    ),
                )
            )

        return SemanticCandidate(
            discourse_act=DiscourseAct.PROPOSAL if proposal else DiscourseAct.ACTION,
            commitment=Commitment.PROPOSAL
            if proposal
            else Commitment.CONFIRMED_CANDIDATE,
            macro_goal="等待守卫经过后，从后门进入并观察内部",
            steps=[wait, move, observe],
            assumptions=["守卫经过后，后门仍可接近"],
            parser_confidence=0.93,
        )
