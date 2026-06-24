def evaluate_triggers(triggers: list[dict], action_type: str, params: dict) -> list[dict]:
    matched = []
    for trigger in triggers:
        condition = trigger.get("condition", {})
        if _match_condition(condition, action_type, params):
            matched.extend(trigger.get("mechanics", []))
    return matched


def _match_condition(condition: dict, action_type: str, params: dict) -> bool:
    if condition.get("$action") and condition["$action"] != action_type:
        return False
    if condition.get("itemId") and condition["itemId"] != params.get("itemId"):
        return False
    return True
