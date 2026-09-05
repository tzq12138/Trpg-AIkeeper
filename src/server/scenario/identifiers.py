import hashlib
import re
import unicodedata
from typing import Any


def ensure_npc_ids(npcs: Any) -> list[dict[str, Any]]:
    """Assign stable, unique NPC identifiers without exposing setup work to importers."""
    if not isinstance(npcs, list):
        return []

    used_ids: dict[str, int] = {}
    normalized: list[dict[str, Any]] = []
    for npc in npcs:
        if not isinstance(npc, dict):
            continue
        item = dict(npc)
        base_id = str(item.get("npc_id") or "").strip()
        if not base_id:
            base_id = _slugify(_english_name(item)) or _fallback_id(item)
        sequence = used_ids.get(base_id, 0)
        used_ids[base_id] = sequence + 1
        item["npc_id"] = base_id if sequence == 0 else f"{base_id}-{sequence + 1}"
        normalized.append(item)
    return normalized


def _english_name(npc: dict[str, Any]) -> str:
    for key in ("english_name", "englishName", "name_en", "nameEn"):
        value = str(npc.get(key) or "").strip()
        if value:
            return value
    return str(npc.get("name") or "").strip()


def _slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


def _fallback_id(npc: dict[str, Any]) -> str:
    source = "|".join(str(npc.get(key) or "") for key in ("name", "role", "public_name"))
    return f"npc-{hashlib.sha256(source.encode('utf-8')).hexdigest()[:10]}"
