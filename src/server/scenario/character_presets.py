import os
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Cache: (st_mtime_ns, st_size) → parsed dict
_cache: dict[tuple, dict] = {}


def list_presets(preset_dir: Path, occupied_ids: set[str]) -> list[dict]:
    if not preset_dir.exists():
        return []
    presets = []
    for f in sorted(preset_dir.glob("*.xlsx")):
        preset_id = f.stem
        try:
            parsed = _parse_cached(f)
            preview = character_preview(parsed)
            presets.append({
                **preview,
                "preset_id": preset_id,
                "file_name": f.name,
                "occupied": preset_id in occupied_ids,
            })
        except Exception as e:
            logger.warning("Failed to parse preset %s: %s", f.name, e)
    return presets


def find_preset(preset_dir: Path, preset_id: str) -> Path | None:
    for f in preset_dir.glob("*.xlsx"):
        if f.stem.lower() == preset_id.lower():
            return f
    return None


def character_preview(parsed: dict) -> dict:
    skills = parsed.get("skills", {})
    top = sorted(skills.items(), key=lambda kv: kv[1], reverse=True)[:8]
    return {
        "name": parsed.get("name", ""),
        "occupation": parsed.get("occupation", ""),
        "hp": parsed.get("hp", 0),
        "max_hp": parsed.get("max_hp", 0),
        "san": parsed.get("san", 0),
        "max_san": parsed.get("max_san", 0),
        "mp": parsed.get("mp", 0),
        "max_mp": parsed.get("max_mp", 0),
        "luck": parsed.get("luck", 0),
        "skill_count": len(skills),
        "top_skills": [{"name": n, "value": v} for n, v in top],
    }


def preset_dir_from_app(app) -> Path:
    if hasattr(app.state, "character_preset_dir"):
        return Path(app.state.character_preset_dir)
    env_dir = os.getenv("AI_KEEPER_CHARACTER_PRESET_DIR", "")
    if env_dir:
        return Path(env_dir)
    return Path(os.path.dirname(__file__)).parent.parent.parent / "data" / "character_presets"


def _parse_cached(path: Path) -> dict:
    key = (path.stat().st_mtime_ns, path.stat().st_size)
    if key in _cache:
        return _cache[key]
    from .xlsx_parser import parse_xlsx_character
    parsed = parse_xlsx_character(str(path))
    _cache[key] = parsed
    return parsed
