from semantic_demo.compiler import SemanticCompiler
from semantic_demo.demo import build_context
from semantic_demo.model_adapter import DemoSemanticModel
from semantic_demo.models import (
    Channel,
    CompileRequest,
    ConfirmSemanticRequest,
    Handling,
    UtteranceEnvelope,
)


def request(text: str):
    context = build_context()
    return CompileRequest(
        utterance=UtteranceEnvelope(
            room_id=context.room_id,
            speaker_character_id=context.viewer_character_id,
            channel=Channel.PARTY,
            raw_text=text,
        ),
        context=context,
    )


def test_proposal_never_becomes_action() -> None:
    compiler = SemanticCompiler(DemoSemanticModel())
    result = compiler.compile(request("要不等守卫过去后，我从后门进去看看？"))
    assert result.record.handling == Handling.DISCUSSION_ONLY
    confirmed = compiler.confirm(ConfirmSemanticRequest(record=result.record))
    assert confirmed.action is None


def test_action_preserves_condition_and_negative_constraint() -> None:
    compiler = SemanticCompiler(DemoSemanticModel())
    draft = compiler.compile(
        request("我现在等守卫过去后，从后门进去看看，但不碰桌上的信。")
    )
    assert draft.record.handling == Handling.REQUIRES_CONFIRMATION
    assert not draft.record.ambiguities

    result = compiler.confirm(ConfirmSemanticRequest(record=draft.record))
    assert result.action is not None
    assert result.action.steps[0].condition["subjectEntityId"] == "npc_guard"
    assert result.action.steps[1].destination_entity_id == "loc_back_door"
    assert result.action.steps[2].constraints[0]["targetEntityId"] == "item_letter"


def test_ambiguous_pronoun_needs_clarification() -> None:
    compiler = SemanticCompiler(DemoSemanticModel())
    result = compiler.compile(request("我把钥匙给她。"))
    assert result.record.handling == Handling.NEEDS_CLARIFICATION
    ambiguity = result.record.ambiguities[0]
    assert set(ambiguity.candidate_entity_ids) == {"char_anna", "npc_nurse"}
    assert "安娜" in ambiguity.question
    assert "护士" in ambiguity.question


def test_hidden_entities_cannot_be_grounded() -> None:
    compiler = SemanticCompiler(DemoSemanticModel())
    context = build_context()
    context.visible_entities = [
        entity for entity in context.visible_entities if entity.entity_id != "loc_back_door"
    ]
    result = compiler.compile(
        CompileRequest(
            utterance=UtteranceEnvelope(
                room_id=context.room_id,
                speaker_character_id=context.viewer_character_id,
                channel=Channel.PARTY,
                raw_text="我现在等守卫过去后，从后门进去看看。",
            ),
            context=context,
        )
    )
    assert result.record.handling == Handling.NEEDS_CLARIFICATION
    assert any(item.surface == "后门" for item in result.record.ambiguities)
