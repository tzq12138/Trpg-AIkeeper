from __future__ import annotations

from copy import deepcopy

from .models import (
    Ambiguity,
    EntityMention,
    SemanticCandidate,
    SemanticContextSchema,
    VisibleEntity,
)


class ViewerSafeGrounder:
    """Grounds mentions only against entities supplied by the safe context schema."""

    def ground(
        self, candidate: SemanticCandidate, context: SemanticContextSchema
    ) -> tuple[SemanticCandidate, list[Ambiguity]]:
        grounded = deepcopy(candidate)
        ambiguities: list[Ambiguity] = []

        for step_index, step in enumerate(grounded.steps):
            mention_fields = ["target", "destination", "item", "receiver"]
            for field_name in mention_fields:
                mention = getattr(step, field_name)
                if mention is None:
                    continue
                ambiguity = self._bind_mention(
                    mention, context.visible_entities, f"steps.{step_index}.{field_name}"
                )
                if ambiguity:
                    ambiguities.append(ambiguity)

            for constraint_index, constraint in enumerate(step.constraints):
                if constraint.target is None:
                    continue
                ambiguity = self._bind_mention(
                    constraint.target,
                    context.visible_entities,
                    f"steps.{step_index}.constraints.{constraint_index}.target",
                )
                if ambiguity:
                    ambiguities.append(ambiguity)

            if step.condition and step.condition.subject:
                ambiguity = self._bind_mention(
                    step.condition.subject,
                    context.visible_entities,
                    f"steps.{step_index}.condition.subject",
                )
                if ambiguity:
                    ambiguities.append(ambiguity)

        return grounded, ambiguities

    def _bind_mention(
        self,
        mention: EntityMention,
        entities: list[VisibleEntity],
        path: str,
    ) -> Ambiguity | None:
        candidates = [
            entity
            for entity in entities
            if entity.kind in mention.expected_kinds and self._matches(mention.surface, entity)
        ]

        if len(candidates) == 1:
            mention.bound_entity_id = candidates[0].entity_id
            mention.candidate_entity_ids = [candidates[0].entity_id]
            mention.confidence = max(mention.confidence, 0.96)
            return None

        if len(candidates) > 1:
            mention.candidate_entity_ids = [entity.entity_id for entity in candidates]
            labels = "、".join(entity.label for entity in candidates)
            return Ambiguity(
                field_path=path,
                surface=mention.surface,
                candidate_entity_ids=mention.candidate_entity_ids,
                question=f"“{mention.surface}”指的是{labels}中的哪一个？",
            )

        # Unknown descriptions may remain unresolved for CreativeAction/Observe,
        # but cannot become a concrete state mutation until later validation.
        mention.candidate_entity_ids = []
        return Ambiguity(
            field_path=path,
            surface=mention.surface,
            candidate_entity_ids=[],
            question=f"当前可见信息中无法确定“{mention.surface}”指什么，请补充说明。",
        )

    @staticmethod
    def _matches(surface: str, entity: VisibleEntity) -> bool:
        normalized = surface.strip().lower()
        if normalized in {name.lower() for name in entity.all_names}:
            return True
        if normalized in {pronoun.lower() for pronoun in entity.pronouns}:
            return True
        # Conservative partial match for descriptive phrases such as “桌上的信”.
        return any(name.lower() in normalized for name in entity.all_names if len(name) >= 2)
