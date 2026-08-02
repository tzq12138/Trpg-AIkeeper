from __future__ import annotations

import json
import re
from contextlib import nullcontext
from typing import Any


class SoloTransitionError(ValueError):
    pass


_SOLO_SKILL_CHECK_RE = re.compile(
    r"(?P<skill>力量|体质|敏捷|外貌|智力|意志|教育|幸运|"
    r"STR|CON|SIZ|DEX|APP|INT|POW|EDU|LUCK)[”\"']?\s*检定",
    re.IGNORECASE,
)
_SOLO_NAMED_SKILL_CHECK_RE = re.compile(
    r"进行(?:一次)?(?:\s*(?:常规|困难|极难)\s*(?:难度)?(?:的)?)?\s*"
    r"[「“\"](?P<skill>[^「」“”\"，,。；;\n]{1,40})[」”\"]\s*检定"
)
_SOLO_SANITY_CHECK_RE = re.compile(r"进行(?:一次)?\s*[「“\"]?理智[」”\"]?\s*检定")
_SOLO_DICE_RE = re.compile(r"(?P<dice>\d{1,2}\s*[dD]\s*\d{1,3})")
_SOLO_TRANSITION_RE = re.compile(r"转\s*到\s*(?P<target>\d+)")
_SOLO_CHECK_OUTCOMES_RE = re.compile(
    r"如果你\s*(?:通过了|成功通过|成功了?|成功)(?:[^。；\n]{0,80}?检定)?[，,。；;]?\s*转\s*到\s*(?P<success>\d+)"
    r".{0,240}?"
    r"(?:如果你\s*(?:没有通过|未通过|失败了?|失败)(?:[^。；\n]{0,80}?检定)?[，,。；;]?|否则\s*)转\s*到\s*(?P<failure>\d+)",
    re.DOTALL,
)
_SOLO_CHOICE_SKILL_OUTCOME_RE = re.compile(
    r"如果你在[「“\"]?(?P<skill>[^「」“”\"，,。；;]{1,40})[」”\"]?的检定"
    r"(?P<outcome>获得(?:困难|极难)成功|成功)[，,。；;]?\s*转到\s*(?P<target>\d+)",
    re.DOTALL,
)
_SOLO_CHOICE_FAILURE_RE = re.compile(
    r"如果你的检定(?:没有通过|未通过|失败了?|失败)[，,。；;]?\s*转到\s*(?P<failure>\d+)",
    re.DOTALL,
)
_SOLO_CHOICE_SKILL_INTENT_ALIASES = {
    "汽车驾驶": ("发动机", "检修"),
}
_SOLO_VISIBLE_CHOICE_RE = re.compile(
    r"(?P<label>[^。！？!?\n]{1,100}?)[，,;；]?\s*转\s*到\s*(?P<target>\d+)"
)
_SOLO_OTHERWISE_BRANCH_RE = re.compile(
    r"如果你\s*(?P<condition>[^。！？!?\n]{2,160}?)[，,;；]?\s*转\s*到\s*(?P<matched>\d+)"
    r"\s*[。；;]?\s*(?:否则|不然)[，,：:]?\s*转\s*到\s*(?P<otherwise>\d+)",
    re.DOTALL,
)
_SOLO_CONDITIONAL_CHOICE_MARKERS = (
    "检定", "成功", "失败", "通过", "不通过", "高于", "低于", "等于",
)
_SOLO_VISIBLE_CHOICE_CONCEPTS = (
    ("离开", "出村", "离村", "出发", "启程", "赶路"),
    ("会堂", "文特斯", "办公室", "档案室"),
    ("教堂", "墓地"),
    ("杂货店", "补给"),
    ("灯塔", "金属建筑"),
)
_SOLO_NEGATION_MARKERS = ("没有", "没", "未", "不", "并非", "不是", "无")
_SOLO_REFUSAL_CHOICE_MARKERS = ("拒绝", "放弃", "不要")
_SOLO_SILENCE_CHOICE_MARKERS = ("一言不发", "保持沉默")
_SOLO_SILENCE_INTENT_MARKERS = ("一言不发", "保持沉默", "装作若无其事", "不追问", "没有追问", "不提")
_SOLO_NAMED_ADDRESS_RE = re.compile(r"(?:和|向|跟|与)?[\u4e00-\u9fff]{2,4}(?:先生|女士|太太)")
_SOLO_FIXED_HEALING_RE = re.compile(
    r"(?:接受了急救|急救[^。！？!?]{0,80}?|睡过这一晚之后)(?:，|,)?\s*(?:可以)?回复\s*(?:"
    r"(?P<amount>\d{1,2})\s*点生命值|点生命值[。；;，,]*(?P<ocr_amount>\d{1,2})"
    r")"
)
_SOLO_FIXED_HP_LOSS_RE = re.compile(
    r"(?:损失|失去)(?:了)?(?:"
    r"(?P<amount>\d{1,2})点生命值|"
    r"点生命值[。；;，,]*在(?P<sheet_amount>\d{1,2})\(HP\)"
    r")"
)
_SOLO_FIXED_SANITY_LOSS_RE = re.compile(
    r"失去\s*(?P<dice>\d{1,2}\s*[dD]\s*\d{1,3})\s*点理智(?:值)?"
)
_SOLO_DAILY_PENALTY_DIE_RE = re.compile(
    r"今天你的技能检定获得(?:了)?一颗惩罚骰"
)
_SOLO_DAMAGE_BRANCH_RE = re.compile(
    r"受到.{0,180}?"
    r"(?P<dice>\d{1,2}[dD]\d{1,3})伤害的数值大于等于你最大生命值的一半，转到(?P<high>\d+)。"
    r"否则，转到(?P<low>\d+)",
    re.DOTALL,
)
_SOLO_DAMAGE_ENDS_ON_ZERO_RE = re.compile(
    r"受到.{0,260}?生命值(?:因此)?归零.{0,120}?(?:剧终|烧死).{0,160}?"
    r"否则[，,]?\s*转\s*到\s*(?P<target>\d+)",
    re.DOTALL,
)
_SOLO_HUNTING_KNIFE_OFFER_RE = re.compile(
    r"狩猎小刀.{0,80}?(?:如果想要.{0,40}?买下它|可以买下它)"
)
_SOLO_HUNTING_KNIFE_PURCHASE_RE = re.compile(
    r"(?:买|购买|买下).{0,40}?狩猎小刀|狩猎小刀.{0,40}?(?:买|购买|买下)"
)
_PLAYER_SOURCE_MARKER_RE = re.compile(
    r"(?:七宫涟(?:个人)?汉化?|七宫(?:涟)?个人汉化?|七宫(?=\s+)|火独行|向火|宫涟(?:个人)?汉化|宫涟|人汉化|个人汉|汉化)"
)
_PLAYER_SOLO_NAVIGATION_RE = re.compile(
    r"(?:请|再|然后|现在)?(?:转|翻|跳|前往|进入|见)\s*(?:到|至|去|向|往)?"
    r"(?:条目|段落)?\s*(?:第)?\s*\d+\s*[。．.!！?？]*"
)
_PLAYER_RULE_SENTENCE_MARKERS = (
    "检定",
    "技能",
    "方框",
    "骰",
    "伤害",
    "生命值",
    "敏捷",
    "规则",
)


def render_player_safe_solo_narrative(scene: dict[str, Any]) -> str:
    """Return the visible scene fiction without source navigation or rule instructions."""
    text = _PLAYER_SOURCE_MARKER_RE.sub("", str(scene.get("text") or ""))
    sentences = re.split(r"(?<=[。！？!?])\s*", text)
    visible_sentences = []
    for sentence in sentences:
        normalized = re.sub(r"\s+", "", sentence).strip()
        if not normalized:
            continue
        if _PLAYER_SOLO_NAVIGATION_RE.search(normalized):
            continue
        if "条目" in normalized or re.search(r"第\s*\d+\s*轮", normalized):
            continue
        if any(marker in normalized for marker in _PLAYER_RULE_SENTENCE_MARKERS):
            continue
        visible_sentences.append(normalized)
    narration = "".join(visible_sentences).strip()
    if not narration:
        narration = "你已抵达新的可见场景。眼前的局势等待你的行动。"
    if not narration.endswith(("？", "?")):
        narration = f"{narration} 你准备怎么做？"
    return narration[:600]


def extract_solo_fixed_healing(scene: dict[str, Any]) -> dict[str, Any] | None:
    text = re.sub(r"\s+", "", str(scene.get("text") or ""))
    match = _SOLO_FIXED_HEALING_RE.search(text)
    if not match:
        return None
    allowed_targets = {str(item) for item in scene.get("target_node_ids") or []}
    target_node_id = next(
        (
            item.group("target")
            for item in reversed(list(_SOLO_TRANSITION_RE.finditer(text)))
            if item.group("target") in allowed_targets
        ),
        "",
    )
    if not target_node_id:
        return None
    return {
        "from_node_id": str(scene.get("node_id") or ""),
        "target_node_id": target_node_id,
        "amount": int(match.group("amount") or match.group("ocr_amount")),
        "citation": _json_object(scene.get("citation")),
    }


def extract_solo_daily_penalty_die(scene: dict[str, Any]) -> dict[str, Any] | None:
    text = re.sub(r"\s+", "", str(scene.get("text") or ""))
    if not _SOLO_DAILY_PENALTY_DIE_RE.search(text):
        return None
    allowed_targets = {str(item) for item in scene.get("target_node_ids") or []}
    target_node_id = next(
        (
            item.group("target")
            for item in reversed(list(_SOLO_TRANSITION_RE.finditer(text)))
            if item.group("target") in allowed_targets
        ),
        "",
    )
    if not target_node_id:
        return None
    return {
        "from_node_id": str(scene.get("node_id") or ""),
        "target_node_id": target_node_id,
        "bonus_dice": -1,
        "citation": _json_object(scene.get("citation")),
    }


def extract_solo_fixed_damage(scene: dict[str, Any]) -> dict[str, Any] | None:
    text = re.sub(r"\s+", "", str(scene.get("text") or ""))
    match = _SOLO_FIXED_HP_LOSS_RE.search(text)
    if not match:
        return None
    allowed_targets = {str(item) for item in scene.get("target_node_ids") or []}
    target_node_id = next(
        (
            item.group("target")
            for item in reversed(list(_SOLO_TRANSITION_RE.finditer(text)))
            if item.group("target") in allowed_targets
        ),
        "",
    )
    amount = match.group("amount") or match.group("sheet_amount")
    if not target_node_id or not amount:
        return None
    return {
        "from_node_id": str(scene.get("node_id") or ""),
        "target_node_id": target_node_id,
        "amount": int(amount),
        "citation": _json_object(scene.get("citation")),
    }


def extract_solo_fixed_sanity_loss(scene: dict[str, Any]) -> dict[str, Any] | None:
    text = re.sub(r"\s+", "", str(scene.get("text") or ""))
    match = _SOLO_FIXED_SANITY_LOSS_RE.search(text)
    allowed_targets = {str(item) for item in scene.get("target_node_ids") or []}
    target = next((item.group("target") for item in reversed(list(_SOLO_TRANSITION_RE.finditer(text))) if item.group("target") in allowed_targets), "")
    if not match or not target:
        return None
    return {"from_node_id": str(scene.get("node_id") or ""), "target_node_id": target, "loss_dice": re.sub(r"\s+", "", match.group("dice")).lower(), "citation": _json_object(scene.get("citation"))}


def extract_solo_item_purchase(
    scene: dict[str, Any],
    declared_intent: str,
) -> dict[str, Any] | None:
    text = re.sub(r"\s+", "", str(scene.get("text") or ""))
    intent = re.sub(r"\s+", "", declared_intent)
    if not (
        _SOLO_HUNTING_KNIFE_OFFER_RE.search(text)
        and _SOLO_HUNTING_KNIFE_PURCHASE_RE.search(intent)
    ):
        return None
    allowed_targets = {str(item) for item in scene.get("target_node_ids") or []}
    target_node_id = next(
        (
            item.group("target")
            for item in reversed(list(_SOLO_TRANSITION_RE.finditer(text)))
            if item.group("target") in allowed_targets
        ),
        "",
    )
    if not target_node_id:
        return None
    node_id = str(scene.get("node_id") or "")
    return {
        "from_node_id": node_id,
        "target_node_id": target_node_id,
        "name": "狩猎小刀",
        "description": "从剧本场景中购买的狩猎小刀。",
        "source": f"scenario_purchase:{node_id}",
        "citation": _json_object(scene.get("citation")),
    }


def extract_solo_damage_transition(scene: dict[str, Any]) -> dict[str, Any] | None:
    text = re.sub(r"\s+", "", str(scene.get("text") or ""))
    ending_match = _SOLO_DAMAGE_ENDS_ON_ZERO_RE.search(text)
    allowed_targets = {str(item) for item in scene.get("target_node_ids") or []}
    ending_dice_match = _SOLO_DICE_RE.search(
        text[ending_match.start():ending_match.end()]
    ) if ending_match else None
    if ending_match and ending_dice_match and ending_match.group("target") in allowed_targets:
        return {
            "from_node_id": str(scene.get("node_id") or ""),
            "target_node_id": ending_match.group("target"),
            "damage_dice": re.sub(r"\s+", "", ending_dice_match.group("dice")).lower(),
            "damage_ends_on_zero": True,
            "citation": _json_object(scene.get("citation")),
        }
    match = _SOLO_DAMAGE_BRANCH_RE.search(text)
    if not match:
        return None
    high_target = match.group("high")
    low_target = match.group("low")
    if high_target not in allowed_targets or low_target not in allowed_targets:
        return None
    return {
        "from_node_id": str(scene.get("node_id") or ""),
        "high_damage_target_node_id": high_target,
        "low_damage_target_node_id": low_target,
        "damage_dice": match.group("dice").lower(),
        "citation": _json_object(scene.get("citation")),
    }


def extract_solo_skill_check(
    scene: dict[str, Any],
    declared_intent: str = "",
) -> dict[str, Any] | None:
    text = str(scene.get("text") or "")
    outcome_match = _SOLO_CHECK_OUTCOMES_RE.search(text)
    allowed_targets = {str(item) for item in scene.get("target_node_ids") or []}
    sanity_match = _SOLO_SANITY_CHECK_RE.search(text)
    if sanity_match:
        success_target = outcome_match.group("success") if outcome_match else ""
        failure_target = outcome_match.group("failure") if outcome_match else ""
        target_node_id = next(
            (
                match.group("target")
                for match in reversed(list(_SOLO_TRANSITION_RE.finditer(text)))
                if match.group("target") in allowed_targets
            ),
            "",
        )
        dice_match = _SOLO_DICE_RE.search(text[sanity_match.end():])
        if target_node_id:
            failure_loss = (
                re.sub(r"\s+", "", dice_match.group("dice")).lower()
                if dice_match
                else "0"
            )
            rule = {
                "mechanic": "sanity_check",
                "skill_name": "理智",
                "difficulty": "regular",
                "from_node_id": str(scene.get("node_id") or ""),
                "success_loss": "0",
                "failure_loss": failure_loss,
                "citation": _json_object(scene.get("citation")),
            }
            if success_target in allowed_targets and failure_target in allowed_targets:
                rule["success_target_node_id"] = success_target
                rule["failure_target_node_id"] = failure_target
            else:
                rule["target_node_id"] = target_node_id
            return rule

    skill_match = _SOLO_SKILL_CHECK_RE.search(text) or _SOLO_NAMED_SKILL_CHECK_RE.search(text)
    if skill_match and outcome_match:
        success_target = outcome_match.group("success")
        failure_target = outcome_match.group("failure")
        if success_target in allowed_targets and failure_target in allowed_targets:
            rule = {
                "skill_name": skill_match.group("skill"),
                "difficulty": _solo_check_difficulty(text, skill_match),
                "from_node_id": str(scene.get("node_id") or ""),
                "success_target_node_id": success_target,
                "failure_target_node_id": failure_target,
                "citation": _json_object(scene.get("citation")),
            }
            damage_dice = _solo_damage_dice(text)
            if damage_dice:
                rule["damage_dice"] = damage_dice
                rule["damage_ends_on_zero"] = bool(
                    re.search(r"生命值(?:因此)?归零.{0,40}(?:剧终|烧死|失去意识)", re.sub(r"\s+", "", text))
                )
            return rule

    if "选择" not in text or "检定" not in text:
        return None
    failure_match = _SOLO_CHOICE_FAILURE_RE.search(text)
    if not failure_match:
        return None
    normalized_intent = re.sub(r"\s+", "", declared_intent)
    for choice in _SOLO_CHOICE_SKILL_OUTCOME_RE.finditer(text):
        skill_name = choice.group("skill").strip()
        aliases = _SOLO_CHOICE_SKILL_INTENT_ALIASES.get(skill_name, ())
        if not skill_name or (
            skill_name not in normalized_intent
            and not any(alias in normalized_intent for alias in aliases)
        ):
            continue
        success_target = choice.group("target")
        failure_target = failure_match.group("failure")
        if success_target not in allowed_targets or failure_target not in allowed_targets:
            continue
        outcome = choice.group("outcome")
        difficulty = "extreme" if "极难" in outcome else "hard" if "困难" in outcome else "regular"
        return {
            "skill_name": skill_name,
            "difficulty": difficulty,
            "from_node_id": str(scene.get("node_id") or ""),
            "success_target_node_id": success_target,
            "failure_target_node_id": failure_target,
            "citation": _json_object(scene.get("citation")),
        }
    return None


def _solo_check_difficulty(text: str, match: re.Match[str]) -> str:
    window = text[max(0, match.start() - 40):match.end() + 40]
    if "极难" in window:
        return "extreme"
    if "困难" in window:
        return "hard"
    return "regular"


def _solo_damage_dice(text: str) -> str | None:
    normalized = re.sub(r"\s+", "", text)
    if "伤害" not in normalized or "生命值" not in normalized:
        return None
    damage_index = normalized.find("伤害")
    candidates = list(_SOLO_DICE_RE.finditer(normalized))
    if not candidates:
        return None
    closest = min(candidates, key=lambda match: abs(match.start() - damage_index))
    if abs(closest.start() - damage_index) > 80:
        return None
    return re.sub(r"\s+", "", closest.group("dice")).lower()


def infer_visible_solo_target(scene: dict[str, Any], declared_intent: str) -> str | None:
    allowed_targets = {str(item) for item in scene.get("target_node_ids") or []}
    intent = _normalize_choice_text(declared_intent)
    if not allowed_targets or not intent:
        return None
    matches: list[tuple[int, str]] = []
    for choice in _SOLO_VISIBLE_CHOICE_RE.finditer(str(scene.get("text") or "")):
        target = choice.group("target")
        label = _normalize_choice_text(choice.group("label"))
        if target not in allowed_targets or not label:
            continue
        if any(marker in label for marker in _SOLO_CONDITIONAL_CHOICE_MARKERS):
            continue
        named_address_bigrams = {
            bigram
            for named_address in _SOLO_NAMED_ADDRESS_RE.findall(label)
            for bigram in _choice_bigrams(named_address)
        }
        shared_bigrams = (_choice_bigrams(label) & _choice_bigrams(intent)) - named_address_bigrams
        if shared_bigrams and _intent_negates_terms(intent, shared_bigrams):
            continue
        score = 2 * len(shared_bigrams)
        if shared_bigrams:
            for concept in _SOLO_VISIBLE_CHOICE_CONCEPTS:
                if any(term in label for term in concept) and any(term in intent for term in concept):
                    score += 4
        if (
            any(marker in label for marker in _SOLO_REFUSAL_CHOICE_MARKERS)
            and any(marker in intent for marker in _SOLO_NEGATION_MARKERS)
        ):
            score += 4
        if (
            any(marker in label for marker in _SOLO_SILENCE_CHOICE_MARKERS)
            and any(marker in intent for marker in _SOLO_SILENCE_INTENT_MARKERS)
        ):
            score += 6
        if score:
            matches.append((score, target))
    if not matches:
        return None
    highest_score = max(score for score, _ in matches)
    top_targets = {target for score, target in matches if score == highest_score}
    return next(iter(top_targets)) if highest_score >= 2 and len(top_targets) == 1 else None


def infer_otherwise_solo_target(scene: dict[str, Any], declared_intent: str) -> str | None:
    allowed_targets = {str(item) for item in scene.get("target_node_ids") or []}
    intent = _normalize_choice_text(declared_intent)
    if not allowed_targets or not intent:
        return None
    source_text = re.sub(r"\s+", "", str(scene.get("text") or ""))
    for branch in _SOLO_OTHERWISE_BRANCH_RE.finditer(source_text):
        matched_target = branch.group("matched")
        otherwise_target = branch.group("otherwise")
        if matched_target not in allowed_targets or otherwise_target not in allowed_targets:
            continue
        condition = _normalize_choice_text(branch.group("condition"))
        condition_terms = _choice_bigrams(condition)
        shared_terms = {term for term in condition_terms if term in _choice_bigrams(intent)}
        if not shared_terms:
            if (
                "昨晚" in condition
                and "勘查" in condition
                and any(marker in intent for marker in ("告别", "离开", "出门", "出发", "启程"))
            ):
                return otherwise_target
            continue
        if _intent_negates_terms(intent, shared_terms):
            return otherwise_target
        return matched_target
    return None


def _intent_negates_terms(intent: str, terms: set[str]) -> bool:
    for term in terms:
        start = intent.find(term)
        while start >= 0:
            prefix = intent[max(0, start - 8):start]
            if re.search(r"(?:没有|没|未|并非|不是).{0,6}$", prefix):
                return True
            if re.search(r"不(?:回头|想|要|再|会|能|愿|可|肯|打算)?$", prefix):
                return True
            start = intent.find(term, start + len(term))
    return False


def _normalize_choice_text(value: Any) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", str(value or ""))


def _choice_bigrams(value: str) -> set[str]:
    return {value[index:index + 2] for index in range(len(value) - 1)}


class SoloAdventureRuntime:
    def __init__(self, conn):
        self.conn = conn

    def current(self, room_id: str) -> dict[str, Any] | None:
        context = self._context(room_id)
        if not context:
            return None
        state = self.conn.execute(
            "SELECT current_scene, visited_scenes, scene_variables, version FROM room_scene_state WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        node_id = _scene_node_id(state.get("current_scene") if state else "")
        if node_id not in context["nodes"]:
            node_id = context["root_node_id"]
        node = context["nodes"][node_id]
        return {
            "scenario_version_id": context["scenario_version_id"],
            "node_id": node_id,
            "title": node["title"],
            "text": _json_object(node.get("payload")).get("text", ""),
            "citation": _json_object(node.get("citation")),
            "target_node_ids": context["targets"].get(node_id, []),
            "scene_variables": _json_object(state.get("scene_variables") if state else {}),
            "scene_version": int(state.get("version") or 0) if state else 0,
        }

    def validate_transition(
        self, room_id: str, *, from_node_id: str, target_node_id: str
    ) -> str | None:
        context = self._context(room_id)
        if not context:
            return None
        current = self.current(room_id)
        if not current:
            return "solo_runtime_unavailable"
        if from_node_id and from_node_id != current["node_id"]:
            return "solo_transition_stale"
        if target_node_id not in context["targets"].get(current["node_id"], []):
            return "solo_transition_not_allowed"
        return ""

    def transition(
        self,
        room_id: str,
        *,
        from_node_id: str,
        target_node_id: str,
        scene_variables: dict[str, Any] | None = None,
        transaction=None,
        finalize_terminal: bool = True,
        ending_type: str | None = None,
    ) -> dict[str, Any]:
        transaction_scope = (
            nullcontext(transaction) if transaction is not None else self.conn.transaction()
        )
        with transaction_scope as tx:
            context = self._context(room_id, connection=tx)
            if not context:
                raise SoloTransitionError("solo_adventure_not_enabled")
            state = tx.execute(
                "SELECT current_scene, visited_scenes FROM room_scene_state "
                "WHERE room_id = %s FOR UPDATE",
                (room_id,),
            ).fetchone()
            current_node_id = _scene_node_id(state.get("current_scene") if state else "")
            if current_node_id not in context["nodes"]:
                current_node_id = context["root_node_id"]
            if from_node_id and from_node_id != current_node_id:
                raise SoloTransitionError("solo_transition_stale")
            if target_node_id not in context["targets"].get(current_node_id, []):
                raise SoloTransitionError("solo_transition_not_allowed")
            visited = _json_list(state.get("visited_scenes") if state else [])
            for node_id in (current_node_id, target_node_id):
                scene_id = f"solo:{node_id}"
                if scene_id not in visited:
                    visited.append(scene_id)
            updated_scene_variables = {"solo_adventure_version": context["scenario_version_id"]}
            if scene_variables:
                updated_scene_variables.update(scene_variables)
            tx.execute(
                """
                INSERT INTO room_scene_state (room_id, current_scene, visited_scenes, scene_variables, version)
                VALUES (%s, %s, %s, %s, 1)
                ON CONFLICT (room_id) DO UPDATE SET
                    current_scene = EXCLUDED.current_scene,
                    visited_scenes = EXCLUDED.visited_scenes,
                    scene_variables = room_scene_state.scene_variables || EXCLUDED.scene_variables,
                    version = room_scene_state.version + 1,
                    updated_at = NOW()
                """,
                (
                    room_id,
                    f"solo:{target_node_id}",
                    json.dumps(visited, ensure_ascii=False),
                    json.dumps(updated_scene_variables, ensure_ascii=False),
                ),
            )
            target_node = context["nodes"][target_node_id]
            target_payload = _json_object(target_node.get("payload"))
            target_text = str(target_payload.get("text") or "")
            is_ending = (
                "【剧终】" in target_text
                and not context["targets"].get(target_node_id, [])
            )
            room = tx.execute(
                "UPDATE rooms SET state_version = state_version + 1 WHERE room_id = %s "
                "RETURNING state_version",
                (room_id,),
            ).fetchone()
            if is_ending:
                tx.execute(
                    "UPDATE encounters SET status = 'resolved', resolved_at = NOW(), "
                    "summary = COALESCE(summary, '') || ' [solo adventure ended]' "
                    "WHERE room_id = %s AND status IN ('suggested', 'active')",
                    (room_id,),
                )
            edge = context["edges"][(current_node_id, target_node_id)]
            resolved_ending_type = str(
                ending_type or target_payload.get("ending_type") or "mixed"
            ).strip()
            if resolved_ending_type not in {"victory", "defeat", "mixed"}:
                resolved_ending_type = "mixed"
            ending_event_sequence = None
            if is_ending and finalize_terminal:
                from ..campaign_archive import finalize_campaign

                ending_citation = _json_object(target_node.get("citation")) or _json_object(
                    edge.get("citation")
                )
                finalized = finalize_campaign(
                    self.conn,
                    room_id,
                    ending_type=resolved_ending_type,
                    summary="单人冒险已到达已编译的终局节点。",
                    highlights=[target_text] if target_text else [],
                    expected_room_statuses=("lobby", "suggested", "active", "paused"),
                    ending_event_payload={
                        "ending_id": f"solo_terminal_{target_node_id}",
                        "ending_type": resolved_ending_type,
                        "citation": ending_citation,
                        "completion_source": "solo_terminal_node",
                    },
                    transaction=tx,
                )
                if finalized is None:
                    raise SoloTransitionError("solo_campaign_already_completed")
                ending_event_sequence = finalized.ending_event_sequence
                room = {"state_version": finalized.state_version}
        return {
            "scenario_version_id": context["scenario_version_id"],
            "from_node_id": current_node_id,
            "target_node_id": target_node_id,
            "current_scene": f"solo:{target_node_id}",
            "citation": _json_object(edge.get("citation")),
            "state_version": int(room.get("state_version") or 0) if room else 0,
            "is_ending": is_ending,
            "ending_type": resolved_ending_type if is_ending else None,
            "ending_citation": (
                _json_object(target_node.get("citation"))
                if is_ending
                else {}
            ),
            "ending_event_sequence": ending_event_sequence,
        }

    def _context(self, room_id: str, *, connection=None) -> dict[str, Any] | None:
        connection = connection or self.conn
        room = connection.execute(
            """
            SELECT r.scenario_version_id, sv.knowledge_graph
            FROM rooms r
            JOIN scenario_versions sv ON sv.scenario_version_id = r.scenario_version_id
            WHERE r.room_id = %s
            """,
            (room_id,),
        ).fetchone()
        if not room:
            return None
        graph = _json_object(room.get("knowledge_graph"))
        solo = _json_object(graph.get("solo_adventure"))
        integrity = _json_object(solo.get("integrity"))
        root_node_id = str(solo.get("root_node_id") or "")
        if not root_node_id or not integrity.get("is_valid", False):
            return None
        rows = connection.execute(
            """
            SELECT content_item_id, logical_key, title, payload, citation
            FROM content_items
            WHERE scenario_version_id = %s AND item_type = 'branch_node'
            ORDER BY ordinal, logical_key
            """,
            (room["scenario_version_id"],),
        ).fetchall()
        nodes = {str(row["logical_key"]): dict(row) for row in rows}
        if root_node_id not in nodes:
            return None
        edges = connection.execute(
            """
            SELECT source.logical_key AS from_node_id, target.logical_key AS target_node_id,
                   edge.citation
            FROM content_item_edges edge
            JOIN content_items source ON source.content_item_id = edge.from_content_item_id
            JOIN content_items target ON target.content_item_id = edge.to_content_item_id
            WHERE edge.scenario_version_id = %s
              AND source.item_type = 'branch_node'
              AND target.item_type = 'branch_node'
              AND edge.relation_type = 'transitions_to'
            """,
            (room["scenario_version_id"],),
        ).fetchall()
        targets: dict[str, list[str]] = {node_id: [] for node_id in nodes}
        edge_map = {}
        for edge in edges:
            from_node_id = str(edge["from_node_id"])
            target_node_id = str(edge["target_node_id"])
            targets.setdefault(from_node_id, []).append(target_node_id)
            edge_map[(from_node_id, target_node_id)] = dict(edge)
        return {
            "scenario_version_id": room["scenario_version_id"],
            "root_node_id": root_node_id,
            "nodes": nodes,
            "targets": targets,
            "edges": edge_map,
        }


def _scene_node_id(current_scene: str) -> str:
    value = str(current_scene or "")
    return value[5:] if value.startswith("solo:") else ""


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []
    return []
