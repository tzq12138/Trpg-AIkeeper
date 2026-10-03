"""<summary>核对试点内容转换的秘密边界、角色数值及非覆盖行为。</summary>"""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_public_content_excludes_unrevealed_clues_and_private_hooks(tmp_path):
    """<summary>公共内容不能因转换丢失秘密边界。</summary>
    <param name="tmp_path">隔离的输出目录。</param><returns>无返回值。</returns>
    """
    from build_glass_rain import build_pack

    source = Path(__file__).resolve().parents[2] / "data/golden_modules/02-short-team-glass-rain/module.json"
    pack = build_pack(source, tmp_path / "aikeeper-glass-rain")
    world = json.loads((pack / "content/worlds/glass_rain.json").read_text(encoding="utf-8"))
    public = json.dumps({
        "setting": world["world_setting"], "opening": world["starter_scene"],
        "entries": [entry for entry in world["starter_lorebook"] if entry["visible_to"]],
        "cards": [json.loads(path.read_text(encoding="utf-8")) for path in (pack / "content/characters").glob("*.json")],
    }, ensure_ascii=False)
    private = json.dumps([entry for entry in world["starter_lorebook"] if not entry["visible_to"]], ensure_ascii=False)
    assert "入口的玻璃顶" in public
    for secret in ("必须先关闭回灌阀，再断开控制室电源", "韩岑隐瞒旧测试", "模糊录像", "G-17 测试表"):
        assert secret not in public
        assert secret in private


def test_presets_keep_original_values_and_private_use_license(tmp_path):
    """<summary>转换保留角色数值及原许可，声明兼容的建卡上限。</summary>
    <param name="tmp_path">隔离的输出目录。</param><returns>无返回值。</returns>
    """
    from build_glass_rain import build_pack

    source = Path(__file__).resolve().parents[2] / "data/golden_modules/02-short-team-glass-rain/module.json"
    pack = build_pack(source, tmp_path / "aikeeper-glass-rain")
    card = json.loads((pack / "content/characters/glass-reporter.json").read_text(encoding="utf-8"))
    rule = json.loads((pack / "content/rules/glass_rain_coc.json").read_text(encoding="utf-8"))
    assert card["character_name"] == "程雁"
    assert card["attributes"]["pow"] == 55
    assert {skill["name"]: skill["value"] for skill in card["skills"]}["侦查"] == 65
    assert len(list((pack / "content/characters").glob("*.json"))) == 2
    assert rule["extends"] == "freeform_coc"
    assert rule["attribute_points"] == 480
    provenance = json.loads((pack / "source.json").read_text(encoding="utf-8"))
    assert provenance["license"]["public_redistribution_allowed"] is False
    assert provenance["license"]["license_id"] == "AI-Keeper-Original-Private-Use-1.0"


def test_existing_destination_is_not_overwritten(tmp_path):
    """<summary>拒绝覆盖已有内容包，保留用户的手工修改。</summary>
    <param name="tmp_path">隔离的输出目录。</param><returns>无返回值。</returns>
    """
    from build_glass_rain import build_pack

    destination = tmp_path / "aikeeper-glass-rain"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("user edits", encoding="utf-8")
    source = Path(__file__).resolve().parents[2] / "data/golden_modules/02-short-team-glass-rain/module.json"
    with pytest.raises(FileExistsError):
        build_pack(source, destination)
    assert marker.read_text(encoding="utf-8") == "user edits"


def test_pack_can_be_enabled_by_diceframe_host(tmp_path):
    """<summary>通过真实宿主配置接口启用内容包，防止空 schema 吞掉开关。</summary>
    <param name="tmp_path">隔离的插件及配置目录。</param><returns>无返回值。</returns>
    """
    from build_glass_rain import build_pack

    root = Path(__file__).resolve().parents[2]
    upstream = Path(os.environ.get("DICEFRAME_ROOT", root / ".runtime/diceframe-pilot/app"))
    if not (upstream / "src/plugin_host").is_dir():
        pytest.skip("设置 DICEFRAME_ROOT 指向固定版本 Diceframe 可运行真实宿主验证")
    build_pack(root / "data/golden_modules/02-short-team-glass-rain/module.json", tmp_path / "plugins/aikeeper-glass-rain")
    result = subprocess.run([
        sys.executable, "-X", "utf8", "-c",
        "import asyncio, json, sys; from pathlib import Path; from src.plugin_host import PluginHost; "
        "from src.rules.rule_system import RuleSystem; "
        "root = Path(sys.argv[1]); host = PluginHost(root / 'plugins', root / 'data'); host.discover(); "
        "detail = asyncio.run(host.update_config('aikeeper-glass-rain', {'enabled': True})); "
        "assert detail['enabled'], detail; assert detail['status'] == 'active', detail; "
        "assert host.load_world_template('aikeeper_glass_rain'); "
        "assert len(host.contributions.list('character_template')) == 2; "
        "pack = root / 'plugins/aikeeper-glass-rain/content'; "
        "rule = RuleSystem.load(pack / 'rules/glass_rain_coc.json'); "
        "assert rule.dice_system == 'd100'; "
        "errors = [rule.validate_character(json.loads(p.read_text(encoding='utf-8'))) for p in (pack / 'characters').glob('*.json')]; "
        "assert not any(errors), errors",
        str(tmp_path),
    ], cwd=upstream, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
