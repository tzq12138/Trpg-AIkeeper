def evaluate_triggers(triggers: list[dict], action_type: str, params: dict) -> list[dict]:
    matched = []
    for trigger in triggers:
        condition = trigger.get("condition", {})
        if _match_condition(condition, action_type, params):
            matched.extend(trigger.get("mechanics", []))
    return matched


def _match_condition(condition: dict, action_type: str, params: dict) -> bool:
    for key, expected in condition.items():
        actual = action_type if key == "$action" else params.get(key)
        if actual != expected:
            return False
    return True
