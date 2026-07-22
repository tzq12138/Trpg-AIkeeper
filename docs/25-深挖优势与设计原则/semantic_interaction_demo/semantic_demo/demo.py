from __future__ import annotations

import json

from .compiler import SemanticCompiler
from .model_adapter import DemoSemanticModel
from .models import (
    Channel,
    CompileRequest,
    ConfirmSemanticRequest,
    EntityKind,
    SemanticContextSchema,
    UtteranceEnvelope,
    VisibleEntity,
)


def build_context() -> SemanticContextSchema:
    return SemanticContextSchema(
        room_id="room_hospital",
        viewer_character_id="char_me",
        visible_entities=[
            VisibleEntity(
                entity_id="npc_guard",
                kind=EntityKind.NPC,
                label="守卫",
                aliases=["门卫"],
                pronouns=["他"],
            ),
            VisibleEntity(
                entity_id="loc_back_door",
                kind=EntityKind.LOCATION,
                label="后门",
                aliases=["后门里面"],
            ),
            VisibleEntity(
                entity_id="item_letter",
                kind=EntityKind.ITEM,
                label="信",
                aliases=["桌上的信"],
            ),
            VisibleEntity(
                entity_id="item_key",
                kind=EntityKind.ITEM,
                label="钥匙",
            ),
            VisibleEntity(
                entity_id="char_anna",
                kind=EntityKind.CHARACTER,
                label="安娜",
                pronouns=["她"],
            ),
            VisibleEntity(
                entity_id="npc_nurse",
                kind=EntityKind.NPC,
                label="护士",
                pronouns=["她"],
            ),
        ],
    )


def print_json(title: str, value) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(value.model_dump(mode="json"), ensure_ascii=False, indent=2))


def main() -> None:
    compiler = SemanticCompiler(DemoSemanticModel())
    context = build_context()

    # Example A: a suggestion is understood but not executed.
    proposal = CompileRequest(
        utterance=UtteranceEnvelope(
            room_id=context.room_id,
            speaker_character_id=context.viewer_character_id,
            channel=Channel.PARTY,
            raw_text="要不等守卫过去后，我从后门进去看看？",
        ),
        context=context,
    )
    print_json("A. 队伍建议：只理解，不执行", compiler.compile(proposal))

    # Example B: an executable action with a condition and a negative constraint.
    action_request = CompileRequest(
        utterance=UtteranceEnvelope(
            room_id=context.room_id,
            speaker_character_id=context.viewer_character_id,
            channel=Channel.PARTY,
            raw_text="我现在等守卫过去后，从后门进去看看，但不碰桌上的信。",
        ),
        context=context,
    )
    draft = compiler.compile(action_request)
    print_json("B1. 行动草稿：解析并等待确认", draft)
    confirmed = compiler.confirm(ConfirmSemanticRequest(record=draft.record))
    print_json("B2. 玩家确认后：生成 Transaction 命令", confirmed)

    # Example C: ambiguous pronoun generates the smallest possible question.
    ambiguous_request = CompileRequest(
        utterance=UtteranceEnvelope(
            room_id=context.room_id,
            speaker_character_id=context.viewer_character_id,
            channel=Channel.PARTY,
            raw_text="我把钥匙给她。",
        ),
        context=context,
    )
    print_json("C. 指代歧义：不执行，只问一个问题", compiler.compile(ambiguous_request))


if __name__ == "__main__":
    main()
