from __future__ import annotations

import re
from typing import Any


_NODE_PATTERN = re.compile(r"(?<!\d)(?P<node_id>\d{1,3})#")
_TARGET_PATTERN = re.compile(
    r"(?:转|翻)\s*(?:\d+\s*(?:[dD]\s*\d+)?\s*)*"
    r"(?:到|至)\s*(?:个|条目|第)?\s*(?P<node_id>\d{1,3})(?:\s*#)?"
)


def extract_solo_adventure(parts: list[dict[str, Any]]) -> dict[str, Any]:
    text, anchors = _merge_text_parts(parts)
    matches = list(_NODE_PATTERN.finditer(text))
    nodes = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end].strip()
        target_node_ids = _unique_ids(
            target.group("node_id") for target in _TARGET_PATTERN.finditer(body)
        )
        nodes.append({
            "node_id": match.group("node_id"),
            "title": f"条目 {match.group('node_id')}",
            "text": body,
            "target_node_ids": target_node_ids,
            "citation": _citation_for_offset(anchors, match.start()),
        })

    node_ids = [node["node_id"] for node in nodes]
    known_node_ids = set(node_ids)
    duplicates = _duplicates(node_ids)
    missing_targets = _unique_ids(
        target
        for node in nodes
        for target in node["target_node_ids"]
        if target not in known_node_ids
    )
    root_node_id = "1" if "1" in known_node_ids else ""
    terminal_node_ids = [
        node["node_id"] for node in nodes if not node["target_node_ids"]
    ]
    unreachable = _unreachable_node_ids(nodes, root_node_id)
    integrity = {
        "node_count": len(nodes),
        "edge_count": sum(len(node["target_node_ids"]) for node in nodes),
        "duplicate_node_ids": _sort_ids(duplicates),
        "missing_target_node_ids": _sort_ids(missing_targets),
        "unreachable_node_ids": _sort_ids(unreachable),
        "terminal_node_ids": _sort_ids(terminal_node_ids),
        "is_valid": bool(nodes) and bool(root_node_id) and not duplicates and not missing_targets,
    }
    return {
        "detected": bool(nodes),
        "root_node_id": root_node_id,
        "nodes": nodes,
        "integrity": integrity,
    }


def _merge_text_parts(parts: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    fragments: list[str] = []
    anchors: list[dict[str, Any]] = []
    offset = 0
    for part in parts:
        text = str(part.get("text_content") or part.get("text") or "").strip()
        if not text:
            continue
        if fragments:
            fragments.append("\n")
            offset += 1
        start = offset
        fragments.append(text)
        offset += len(text)
        anchors.append({
            "start": start,
            "end": offset,
            "citation": {
                "source_part_id": str(part.get("source_part_id") or ""),
                "source_ref": str(part.get("source_ref") or ""),
                "page_number": part.get("page_number"),
            },
        })
    return "".join(fragments), anchors


def _citation_for_offset(anchors: list[dict[str, Any]], offset: int) -> dict[str, Any]:
    for anchor in anchors:
        if anchor["start"] <= offset < anchor["end"]:
            return {
                key: value
                for key, value in anchor["citation"].items()
                if value not in (None, "")
            }
    return {}


def _unreachable_node_ids(nodes: list[dict[str, Any]], root_node_id: str) -> list[str]:
    if not root_node_id:
        return [node["node_id"] for node in nodes]
    graph = {node["node_id"]: node["target_node_ids"] for node in nodes}
    reachable = {root_node_id}
    pending = [root_node_id]
    while pending:
        current = pending.pop()
        for target in graph.get(current, []):
            if target in graph and target not in reachable:
                reachable.add(target)
                pending.append(target)
    return [node_id for node_id in graph if node_id not in reachable]


def _duplicates(values: list[str]) -> list[str]:
    seen = set()
    duplicate = set()
    for value in values:
        if value in seen:
            duplicate.add(value)
        seen.add(value)
    return list(duplicate)


def _unique_ids(values) -> list[str]:
    result = []
    seen = set()
    for value in values:
        normalized = str(value).strip()
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result


def _sort_ids(values: list[str]) -> list[str]:
    return sorted(values, key=lambda value: (int(value) if value.isdigit() else 10**9, value))
