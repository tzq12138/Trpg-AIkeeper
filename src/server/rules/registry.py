from .base import BaseRuleHandler
from .coc_handlers import (
    CocCombatHandler,
    CocLuckCheckHandler,
    CocHealingHandler,
    CocMoveHandler,
    CocOpposedCheckHandler,
    CocSanityAdvanceHandler,
    CocSanityCheckHandler,
    CocSkillCheckHandler,
    CocStatusHandler,
)
from .encounter_handlers import (
    CombatAttackHandler, CombatDodgeHandler, CombatDefendHandler,
    CombatAssistHandler, CombatFleeHandler, CombatWaitHandler,
    ChasePursueHandler, ChaseEscapeHandler, ChaseBlockHandler,
    ChaseCreateObstacleHandler, ChaseDetourHandler,
    ChaseAssistHandler, ChaseWaitHandler,
)

rule_registry: dict[str, BaseRuleHandler] = {
    "skill_check": CocSkillCheckHandler(),
    "sanity_check": CocSanityCheckHandler(),
    "sanity_advance": CocSanityAdvanceHandler(),
    "combat_damage": CocCombatHandler(),
    "luck_check": CocLuckCheckHandler(),
    "opposed_check": CocOpposedCheckHandler(),
    "healing": CocHealingHandler(),
    "status_change": CocStatusHandler(),
    "move": CocMoveHandler(),
    "combat_attack": CombatAttackHandler(),
    "combat_dodge": CombatDodgeHandler(),
    "combat_defend": CombatDefendHandler(),
    "combat_assist": CombatAssistHandler(),
    "combat_flee": CombatFleeHandler(),
    "combat_wait": CombatWaitHandler(),
    "chase_pursue": ChasePursueHandler(),
    "chase_escape": ChaseEscapeHandler(),
    "chase_block": ChaseBlockHandler(),
    "chase_create_obstacle": ChaseCreateObstacleHandler(),
    "chase_detour": ChaseDetourHandler(),
    "chase_assist": ChaseAssistHandler(),
    "chase_wait": ChaseWaitHandler(),
}


def register_rule(name: str, handler: BaseRuleHandler):
    rule_registry[name] = handler


def get_handler(name: str) -> BaseRuleHandler | None:
    return rule_registry.get(name)
