from .base import BaseRuleHandler
from .coc_handlers import (
    CocCombatHandler,
    CocLuckCheckHandler,
    CocSanityCheckHandler,
    CocSkillCheckHandler,
)

rule_registry: dict[str, BaseRuleHandler] = {
    "skill_check": CocSkillCheckHandler(),
    "sanity_check": CocSanityCheckHandler(),
    "combat_damage": CocCombatHandler(),
    "luck_check": CocLuckCheckHandler(),
}


def register_rule(name: str, handler: BaseRuleHandler):
    rule_registry[name] = handler


def get_handler(name: str) -> BaseRuleHandler | None:
    return rule_registry.get(name)
