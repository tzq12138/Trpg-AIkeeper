"""<summary>把现有原创短团转换成供本地试用的 Diceframe 内容包。</summary>"""

import argparse
import hashlib
import json
from pathlib import Path


def _write_json(path: Path, value: object) -> None:
    """<summary>以 UTF-8 写出内容包资源。</summary>
    <param name="path">输出文件。</param><param name="value">JSON 数据。</param>
    <returns>无返回值。</returns>
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _entry(identity: str, name: str, content: object, keywords: list[str], *, public: bool = False, core: bool = False) -> dict:
    """<summary>构造明确声明可见范围的世界书条目。</summary>
    <param name="identity">稳定条目标识。</param><param name="name">条目名称。</param>
    <param name="content">正文或结构化资料。</param><param name="keywords">检索词。</param>
    <param name="public">是否属于开局公共常识。</param><param name="core">是否属于核心上下文。</param>
    <returns>Diceframe 世界书条目。</returns>
    """
    return {
        "id": identity, "name": name, "type": "lore",
        "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
        "keywords": keywords, "tier": "core" if core else "background",
        "visible_to": ["*"] if public else [], "unreliable": False,
    }


def build_pack(source: Path, destination: Path) -> Path:
    """<summary>生成保留原许可的玻璃雨夜试点包。</summary>
    <param name="source">黄金模组 JSON。</param>
    <param name="destination">尚不存在的内容包目录。</param>
    <returns>生成包的目录。</returns>
    """
    if destination.exists():
        raise FileExistsError(f"拒绝覆盖已有内容包：{destination}")
    module = json.loads(source.read_text(encoding="utf-8"))
    if module["manifest"]["module_id"] != "golden-team-glass-rain":
        raise ValueError("本转换器仅支持原创《玻璃雨夜》模组")
    if destination.name != "aikeeper-glass-rain":
        raise ValueError("输出目录名必须为 aikeeper-glass-rain，与插件 ID 一致")
    graph = module["knowledge_graph"]
    characters = module["character_templates"][:2]
    rule_id = "aikeeper_glass_rain_coc"
    world_id = "aikeeper_glass_rain"

    # 1. 只把开场与已知通路公开；未来场景的线索、NPC 底牌均交给 GM。
    opening = graph["scenes"][0]["description"]
    map_description = module["scenario_assets"]["text_map"]["player_description"]
    entries = [_entry("glass-public-map", "温室路线", map_description, ["路线", "地图", "温室"], public=True)]
    entries.append(_entry("glass-director", "玻璃雨夜主持说明", {
        "premise": "冰雨袭击市立温室。玩家在救援、调查和设备处置间合作，最终决定撤离或完成停机救援。",
        "boundaries": [
            "玩家不知道未调查场景、幕后真相或他人私人钩子，须随行动逐步发现。",
            "根据玩家行动及已有线索推进，失败有代价但不得把核心线索永久锁死。",
            "保持四个地点及既定人物。每轮给出可继续行动的局面，不替玩家作重大决定。",
            "倒计时是叙事压力，不把服务器真实时间当成游戏时钟。",
            "玩家提出停止或撤离时尊重其决定。结局在叙事中清楚收束，不声称旧引擎已生成战役档案。",
            "游戏中的数值检定与状态更新使用宿主规则；此内容包不执行原 AI-Keeper 状态机。",
        ],
        "truth": graph["truth"]["summary"],
        "endings": [{"name": item["name"], "description": item["description"]}
                    for item in graph["endings"] if item["type"] != "safe_abort"],
        "private_hooks": [{"character": card["name"], **card["backstory"]} for card in characters],
    }, ["玻璃雨夜", "G-17", "停机", "撤离"], core=True))
    for scene in graph["scenes"]:
        entries.append(_entry(scene["scene_id"], scene["name"], {
            key: scene[key] for key in ("name", "description", "exits", "clues_available")
        }, [scene["name"], *scene.get("clues_available", [])]))
    for npc in graph["npcs"]:
        entries.append(_entry(npc["npc_id"], npc["name"], {
            key: npc[key] for key in ("name", "public_description", "description", "personality", "motivation") if key in npc
        }, [npc["name"], npc.get("public_name", npc["name"])]))
    for clue in graph["clues"]:
        entries.append(_entry(clue["clue_id"], clue["name"], {
            key: clue[key] for key in ("name", "location", "description", "public_version", "private_version", "reveal_conditions")
        }, [clue["name"], clue["location"]]))
    world = {
        "world_id": world_id, "world_name": "玻璃雨夜 · 两人迁移试点",
        "description": "冰雨封闭了市立温室。两名调查员在救援与调查之间寻找出路。",
        "language": "zh-CN", "default_locale": "zh-CN", "suggested_difficulty": "标准",
        "default_rule": rule_id, "world_setting": opening + "\n" + map_description,
        "starter_scene": opening + "\n程雁与许遥站在急救台旁。你们准备如何分工？",
        "starter_lorebook": entries,
    }

    # 2. 声明式提高建卡点数上限以容纳原预设卡；继承原生 CoC 骰子规则。
    _write_json(destination / "content/rules/glass_rain_coc.json", {
        "extends": "freeform_coc", "rule_id": rule_id,
        "rule_name": "玻璃雨夜 · CoC 轻量预设", "attribute_points": 480,
        "description": "继承 Diceframe CoC 轻量规则；480 点上限仅用于保留原创预设角色属性。",
    })
    _write_json(destination / "content/worlds/glass_rain.json", world)
    for card in characters:
        _write_json(destination / "content/characters" / f"{card['template_id']}.json", {
            "id": card["template_id"], "character_name": card["name"], "race": "人类",
            "class": card["occupation"], "background": card["background"],
            "description": card["occupation"], "rule_id": rule_id, "world_id": world_id,
            "attributes": {key.lower(): value for key, value in card["attributes"].items()},
            "skills": [{"name": name, "value": value} for name, value in card["skills"].items()],
            "gold": 0, "equipment": [],
        })

    # 3. 包保持纯声明式，来源、许可及差异跟随本地生成物。
    _write_json(destination / "plugin.json", {
        "schema_version": 1, "id": "aikeeper-glass-rain", "name": "AI-Keeper · 玻璃雨夜",
        "version": "0.1.0", "min_app_version": "2.6.1", "plugin_type": "content-pack",
        "description": "原创双人调查短团的本地迁移试点；剧情条件为叙事指引。",
        "config_schema": "config.schema.json", "docs": "README_CN.md",
        "capabilities": ["content.rule", "content.world", "content.character-template"],
        "permissions": ["plugin.config", "content.read", "content.import"],
        "contributes": {"rules": ["content/rules/*.json"], "world_templates": ["content/worlds/*.json"], "character_templates": ["content/characters/*.json"]},
    })
    _write_json(destination / "config.schema.json", {
        "type": "object", "additionalProperties": False,
        "properties": {"enabled": {
            "type": "boolean", "title": "启用玻璃雨夜内容包", "default": False,
            "description": "注册试点规则、世界与两张角色卡。", "ui": {"control": "switch"},
        }},
    })
    _write_json(destination / "source.json", {
        "module_id": module["manifest"]["module_id"],
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "license": module["manifest"]["license"],
        "upstream": {"version": "2.6.1", "commit": "962fda45a68caa24bac38fd2313d92d66fa59a7a"},
    })
    (destination / "README_CN.md").write_text(
        "# 玻璃雨夜试点\n\n仅按 AI-Keeper-Original-Private-Use-1.0 私用，禁止公开再分发。\n\n"
        "提供一个世界、继承的 CoC 轻量规则和两张角色卡。私人钩子只在 GM 世界书中。\n\n"
        "节点条件、倒计时、自动 SAN 触发与结局互斥未迁移成程序规则；此包仅提供叙事指引。\n",
        encoding="utf-8",
    )
    return destination


def main() -> None:
    """<summary>从命令行生成本地试点内容包。</summary><returns>无返回值。</returns>"""
    parser = argparse.ArgumentParser(description="生成玻璃雨夜 Diceframe 本地私用内容包")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2] / "data/golden_modules/02-short-team-glass-rain/module.json")
    args = parser.parse_args()
    print(build_pack(args.source, args.destination))


if __name__ == "__main__":
    main()
