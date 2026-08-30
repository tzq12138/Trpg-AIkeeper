from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any


SUPPORTED_REVEAL_CONDITION_KINDS = frozenset({
    "inspect",
    "research",
    "ask_npc",
    "ask",
    "talk",
})

_INSPECT_WORDS = (
    "观察",
    "查看",
    "检查",
    "调查",
    "翻找",
    "搜索",
    "inspect",
    "look",
    "examine",
    "search",
)
_RESEARCH_WORDS = (
    "查阅",
    "研究",
    "检索",
    "翻阅",
    "阅读",
    "翻查",
    "research",
    "review",
    "read",
)
_DIALOGUE_WORDS = (
    "询问",
    "追问",
    "交谈",
    "交涉",
    "请教",
    "问",
    "ask",
    "talk",
    "speak",
    "question",
)
_DIALOGUE_INTENT_TYPES = {
    "dialogue",
    "voice_command",
    "skill_check",
    "show_item",
}


@dataclass(frozen=True)
class RuntimeClueCandidate:
    canonical_id: str
    name: str
    player_text: str
    importance: str
    declaration_index: int


@dataclass(frozen=True)
class RuntimeClueSelection:
    candidate: RuntimeClueCandidate | None
    rejected_condition_kinds: tuple[str, ...] = ()


@dataclass(frozen=True)
class _SceneContext:
    stable_ids: frozenset[str]
    display_aliases: frozenset[str]
    npc_ids: frozenset[str]


def select_runtime_clue(
    runtime_package: Mapping[str, Any],
    current_scene_id: str,
    intent_type: str,
    declared_intent: str,
    known_canonical_ids: Collection[str],
    *,
    allow_failure_preservation: bool = False,
) -> RuntimeClueSelection:
    """Select one eligible runtime clue without exposing unrevealed content."""
    scene = _scene_context(runtime_package, current_scene_id)
    if not scene.stable_ids:
        return RuntimeClueSelection(None)
    declared = _normalize(declared_intent)
    if not declared:
        return RuntimeClueSelection(None)
    known = {
        str(value).strip()
        for value in known_canonical_ids
        if str(value).strip()
    }
    eligible: list[RuntimeClueCandidate] = []
    rejected: list[str] = []
    dependencies = runtime_package.get("clue_dependencies")
    if not isinstance(dependencies, list):
        return RuntimeClueSelection(None)

    for index, dependency in enumerate(dependencies):
        if not isinstance(dependency, Mapping):
            continue
        canonical_id = _text(dependency.get("clue_id"))
        name = _text(dependency.get("name"))
        if not canonical_id or not name or canonical_id in known:
            continue
        if not _prerequisites_met(dependency, known):
            continue
        if allow_failure_preservation and not _preserves_core(dependency):
            continue
        if not _dependency_matches_scene(dependency, scene):
            continue
        matched, condition_rejections = _any_condition_matches(
            dependency,
            runtime_package,
            scene,
            intent_type,
            declared,
        )
        rejected.extend(condition_rejections)
        if not matched:
            continue
        player_text = _text(dependency.get("public_version")) or name
        eligible.append(
            RuntimeClueCandidate(
                canonical_id=canonical_id,
                name=name,
                player_text=player_text,
                importance=_text(dependency.get("importance")),
                declaration_index=index,
            )
        )

    candidate = min(eligible, key=_candidate_sort_key) if eligible else None
    return RuntimeClueSelection(candidate, tuple(dict.fromkeys(rejected)))


def _candidate_sort_key(candidate: RuntimeClueCandidate) -> tuple[bool, int]:
    return (candidate.importance.casefold() != "core", candidate.declaration_index)


def _any_condition_matches(
    dependency: Mapping[str, Any],
    runtime_package: Mapping[str, Any],
    scene: _SceneContext,
    intent_type: str,
    declared: str,
) -> tuple[bool, list[str]]:
    conditions = dependency.get("reveal_conditions")
    if not isinstance(conditions, list) or not conditions:
        return False, []
    rejected: list[str] = []
    for condition in conditions:
        if not isinstance(condition, Mapping):
            rejected.append("invalid_condition")
            continue
        kind = _text(condition.get("kind"))
        if kind not in SUPPORTED_REVEAL_CONDITION_KINDS:
            rejected.append(kind or "invalid_condition")
            continue
        if not _condition_matches_scene(condition, scene):
            continue
        if not _condition_item_matches(condition, runtime_package, declared):
            continue
        if kind == "inspect":
            if _contains_any(declared, _INSPECT_WORDS):
                return True, rejected
            continue
        if kind == "research":
            if _contains_any(declared, _RESEARCH_WORDS):
                return True, rejected
            continue
        if _npc_condition_matches(condition, runtime_package, scene, intent_type, declared):
            return True, rejected
    return False, rejected


def _scene_context(
    runtime_package: Mapping[str, Any],
    current_scene_id: str,
) -> _SceneContext:
    current = _text(current_scene_id)
    if not current:
        return _SceneContext(frozenset(), frozenset(), frozenset())
    for scene in _dict_items(runtime_package.get("semantic_scenes")):
        stable_ids = _scene_stable_ids(scene)
        if current not in stable_ids:
            continue
        aliases = {
            _normalize(value)
            for value in (
                scene.get("name"),
                scene.get("title"),
                scene.get("public_name"),
                *_payload_values(scene, "name", "title", "public_name"),
            )
            if _normalize(value)
        }
        aliases.update(_normalize(value) for value in stable_ids if _normalize(value))
        return _SceneContext(
            frozenset(stable_ids),
            frozenset(aliases),
            frozenset(_scene_npc_ids(scene)),
        )
    normalized_current = _normalize(current)
    return _SceneContext(
        frozenset({current}),
        frozenset({normalized_current} if normalized_current else set()),
        frozenset(),
    )


def _scene_stable_ids(scene: Mapping[str, Any]) -> set[str]:
    values = {
        _text(scene.get(key))
        for key in ("scene_id", "logical_key", "id", "node_id")
    }
    values.update(_text(value) for value in _payload_values(
        scene,
        "scene_id",
        "logical_key",
        "id",
        "node_id",
    ))
    values.discard("")
    return values


def _scene_npc_ids(scene: Mapping[str, Any]) -> set[str]:
    npc_ids: set[str] = set()
    for item in scene.get("npcs_present") or []:
        if isinstance(item, Mapping):
            npc_ids.update(
                _text(item.get(key))
                for key in ("npc_id", "id", "logical_key")
            )
        else:
            npc_ids.add(_text(item))
    npc_ids.discard("")
    return npc_ids


def _dependency_matches_scene(
    dependency: Mapping[str, Any],
    scene: _SceneContext,
) -> bool:
    dependency_scene_id = _text(dependency.get("scene_id"))
    if dependency_scene_id and dependency_scene_id not in scene.stable_ids:
        return False
    location = _normalize(dependency.get("location"))
    return not location or location in scene.display_aliases


def _condition_matches_scene(
    condition: Mapping[str, Any],
    scene: _SceneContext,
) -> bool:
    scene_id = _text(condition.get("scene_id"))
    return not scene_id or scene_id in scene.stable_ids


def _condition_item_matches(
    condition: Mapping[str, Any],
    runtime_package: Mapping[str, Any],
    declared: str,
) -> bool:
    item_id = _text(condition.get("item_id"))
    if not item_id:
        return True
    aliases = _item_aliases(runtime_package, item_id)
    return bool(aliases and any(alias in declared for alias in aliases))


def _npc_condition_matches(
    condition: Mapping[str, Any],
    runtime_package: Mapping[str, Any],
    scene: _SceneContext,
    intent_type: str,
    declared: str,
) -> bool:
    if _text(intent_type) not in _DIALOGUE_INTENT_TYPES:
        return False
    if not _contains_any(declared, _DIALOGUE_WORDS):
        return False
    npc_id = _text(condition.get("npc_id"))
    if not npc_id or npc_id not in scene.npc_ids:
        return False
    aliases = _npc_aliases(runtime_package, npc_id)
    return bool(aliases and any(alias in declared for alias in aliases))


def _npc_aliases(runtime_package: Mapping[str, Any], npc_id: str) -> set[str]:
    for npc in _dict_items(runtime_package.get("npc_states")):
        identifiers = {
            _text(npc.get(key))
            for key in ("npc_id", "id", "logical_key")
        }
        if npc_id not in identifiers:
            continue
        return _public_aliases(npc)
    return set()


def _item_aliases(runtime_package: Mapping[str, Any], item_id: str) -> set[str]:
    assets = runtime_package.get("character_and_items")
    if not isinstance(assets, Mapping):
        return set()
    for item in _dict_items(assets.get("items")):
        identifiers = {
            _text(item.get(key))
            for key in ("item_id", "id", "logical_key")
        }
        if item_id in identifiers:
            return _public_aliases(item)
    return set()


def _public_aliases(item: Mapping[str, Any]) -> set[str]:
    aliases = {
        _normalize(item.get(key))
        for key in ("name", "public_name", "title")
    }
    aliases.discard("")
    return aliases


def _prerequisites_met(dependency: Mapping[str, Any], known: set[str]) -> bool:
    prerequisites = dependency.get("prerequisite_fact_refs") or []
    if not isinstance(prerequisites, list):
        return False
    required = {_text(value) for value in prerequisites}
    required.discard("")
    return required <= known


def _preserves_core(dependency: Mapping[str, Any]) -> bool:
    failure_outcome = dependency.get("failure_outcome")
    return isinstance(failure_outcome, Mapping) and bool(
        failure_outcome.get("preserve_core")
    )


def _dict_items(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _payload_values(item: Mapping[str, Any], *keys: str) -> list[Any]:
    payload = item.get("payload")
    if not isinstance(payload, Mapping):
        return []
    return [payload.get(key) for key in keys]


def _contains_any(declared: str, words: tuple[str, ...]) -> bool:
    return any(_normalize(word) in declared for word in words)


def _normalize(value: Any) -> str:
    return "".join(char.casefold() for char in str(value or "") if char.isalnum())


def _text(value: Any) -> str:
    return str(value or "").strip()
