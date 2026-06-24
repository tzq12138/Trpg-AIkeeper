from dataclasses import dataclass, field


@dataclass
class RuleResult:
    is_success: bool
    metadata: dict = field(default_factory=dict)
    mutations: list[dict] = field(default_factory=list)
    reveal_steps: list[dict] = field(default_factory=list)
    cascading_state_changes: list[str] = field(default_factory=list)


@dataclass
class GameState:
    character: dict
    scene: dict = field(default_factory=dict)
    inventory: list = field(default_factory=list)


class BaseRuleHandler:
    async def execute(self, state: GameState, params: dict) -> RuleResult:
        raise NotImplementedError
