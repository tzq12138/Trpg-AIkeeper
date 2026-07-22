from __future__ import annotations

from copy import deepcopy

from .grounding import ViewerSafeGrounder
from .model_adapter import SemanticModel
from .models import (
    ActionCommand,
    ActionStep,
    CompileRequest,
    CompileResponse,
    ConfirmSemanticRequest,
    Handling,
    SemanticRecord,
)
from .policy import SemanticRiskPolicy


class SemanticCompiler:
    def __init__(self, model: SemanticModel) -> None:
        self.model = model
        self.grounder = ViewerSafeGrounder()
        self.policy = SemanticRiskPolicy()

    def compile(self, request: CompileRequest) -> CompileResponse:
        if request.utterance.room_id != request.context.room_id:
            raise ValueError("utterance room does not match semantic context room")
        if request.utterance.speaker_character_id != request.context.viewer_character_id:
            raise ValueError("speaker does not match viewer-safe semantic context")

        candidate = self.model.parse(request.utterance, request.context)
        grounded, ambiguities = self.grounder.ground(candidate, request.context)
        risk, handling = self.policy.decide(grounded, ambiguities)
        summary = self._build_player_summary(grounded, ambiguities, handling)

        record = SemanticRecord(
            utterance=request.utterance,
            candidate=grounded,
            ambiguities=ambiguities,
            risk_level=risk,
            handling=handling,
            player_summary=summary,
        )
        return CompileResponse(record=record)

    def confirm(self, request: ConfirmSemanticRequest) -> CompileResponse:
        record = deepcopy(request.record)
        if not request.confirmed:
            return CompileResponse(record=record, action=None)

        answer_by_path = {
            answer.field_path: answer.selected_entity_id
            for answer in request.clarification_answers
        }
        self._apply_clarifications(record, answer_by_path)

        unresolved = [
            ambiguity
            for ambiguity in record.ambiguities
            if ambiguity.field_path not in answer_by_path
        ]
        if unresolved:
            record.ambiguities = unresolved
            record.handling = Handling.NEEDS_CLARIFICATION
            record.player_summary = unresolved[0].question
            return CompileResponse(record=record, action=None)

        if record.handling == Handling.DISCUSSION_ONLY:
            # A proposal must be explicitly converted into a fresh action utterance.
            return CompileResponse(record=record, action=None)

        action = self._to_action(record)
        record.ambiguities = []
        record.handling = Handling.REQUIRES_CONFIRMATION
        return CompileResponse(record=record, action=action)

    @staticmethod
    def _apply_clarifications(
        record: SemanticRecord, answer_by_path: dict[str, str]
    ) -> None:
        for ambiguity in record.ambiguities:
            selected = answer_by_path.get(ambiguity.field_path)
            if selected is None:
                continue
            if ambiguity.candidate_entity_ids and selected not in ambiguity.candidate_entity_ids:
                raise ValueError(f"invalid clarification target for {ambiguity.field_path}")
            SemanticCompiler._set_bound_entity(record, ambiguity.field_path, selected)

    @staticmethod
    def _set_bound_entity(record: SemanticRecord, field_path: str, entity_id: str) -> None:
        parts = field_path.split(".")
        current = record.candidate
        for part in parts:
            if part.isdigit():
                current = current[int(part)]  # type: ignore[index]
            else:
                current = getattr(current, part)
        current.bound_entity_id = entity_id
        current.candidate_entity_ids = [entity_id]
        current.confidence = 1.0

    @staticmethod
    def _to_action(record: SemanticRecord) -> ActionCommand:
        steps: list[ActionStep] = []
        for step in record.candidate.steps:
            condition = None
            if step.condition:
                condition = {
                    "kind": step.condition.kind,
                    "subjectEntityId": step.condition.subject.bound_entity_id
                    if step.condition.subject
                    else None,
                    "predicate": step.condition.predicate,
                    "value": step.condition.value,
                }
            constraints = [
                {
                    "kind": constraint.kind,
                    "targetEntityId": constraint.target.bound_entity_id
                    if constraint.target
                    else None,
                    "value": constraint.value,
                }
                for constraint in step.constraints
            ]
            steps.append(
                ActionStep(
                    frame=step.frame,
                    actor_entity_id=step.actor_entity_id,
                    target_entity_id=step.target.bound_entity_id if step.target else None,
                    destination_entity_id=step.destination.bound_entity_id
                    if step.destination
                    else None,
                    item_entity_id=step.item.bound_entity_id if step.item else None,
                    receiver_entity_id=step.receiver.bound_entity_id
                    if step.receiver
                    else None,
                    condition=condition,
                    temporal_relation=step.temporal_relation,
                    constraints=constraints,
                )
            )

        return ActionCommand(
            idempotency_key=f"semantic:{record.utterance.utterance_id}",
            room_id=record.utterance.room_id,
            character_id=record.utterance.speaker_character_id,
            source_utterance_id=record.utterance.utterance_id,
            source_semantic_record_id=record.semantic_record_id,
            macro_goal=record.candidate.macro_goal,
            steps=steps,
        )

    @staticmethod
    def _build_player_summary(candidate, ambiguities, handling) -> str:
        if handling == Handling.DISCUSSION_ONLY:
            return (
                "我把这句话理解为队伍建议，不会执行行动。"
                f"计划内容：{candidate.macro_goal or '未提取'}。"
            )
        if ambiguities:
            return ambiguities[0].question

        parts = [candidate.macro_goal or "执行当前行动"]
        exclusions: list[str] = []
        for step in candidate.steps:
            for constraint in step.constraints:
                if constraint.target:
                    exclusions.append(constraint.target.surface)
        if exclusions:
            parts.append("不会互动：" + "、".join(exclusions))
        return "；".join(parts) + "。请确认后再执行。"
