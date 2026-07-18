from pathlib import Path

import pytest

from src.server.scenario.golden_suite import iter_golden_module_specs


def _write_module(root: Path, name: str, filenames: list[str]) -> None:
    module_dir = root / "模组库" / name
    module_dir.mkdir(parents=True)
    for filename in filenames:
        (module_dir / filename).write_bytes(b"fixture")


def test_iter_golden_module_specs_classifies_all_nine_module_directories(tmp_path):
    _write_module(tmp_path, "EN_Alone-Against-the-Flames", ["01_Alone.pdf"])
    _write_module(tmp_path, "EN_The-Lightless-Beacon", ["08_Beacon.pdf", "14_Handouts.pdf"])
    _write_module(tmp_path, "EN_Gateways-to-Terror", ["09_Handouts.pdf", "10_PreGens.pdf"])
    _write_module(tmp_path, "EN_Doors-to-Darkness", ["11_Handouts.pdf", "13_PreGens.pdf"])
    _write_module(tmp_path, "EN_Mansions-of-Madness", ["Handouts.pdf", "PreGens.pdf"])
    _write_module(tmp_path, "CN_向火独行", ["向火独行.pdf"])
    _write_module(tmp_path, "CN_猩红文档", ["猩红文档.pdf"])
    _write_module(tmp_path, "CN_常暗之厢", ["常暗之厢.doc"])
    _write_module(tmp_path, "CN_众神的霓虹", ["COC7扩展.docx", "接触.docx"])

    specs = iter_golden_module_specs(tmp_path)

    assert [spec.slug for spec in specs] == [
        "cn-into-the-flames",
        "cn-neon-gods",
        "cn-scarlet-document",
        "cn-the-dark-box",
        "en-alone-against-the-flames",
        "en-doors-to-darkness",
        "en-gateways-to-terror",
        "en-lightless-beacon",
        "en-mansions-of-madness",
    ]
    assert {
        spec.slug: spec.source_mode for spec in specs
    }["en-gateways-to-terror"] == "materials_only"
    assert {
        spec.slug: spec.source_mode for spec in specs
    }["en-doors-to-darkness"] == "materials_only"
    assert {
        spec.slug: spec.source_mode for spec in specs
    }["en-mansions-of-madness"] == "materials_only"
    assert {
        spec.slug: spec.source_mode for spec in specs
    }["cn-the-dark-box"] == "legacy_scanned"


def test_iter_golden_module_specs_requires_module_library(tmp_path):
    with pytest.raises(FileNotFoundError, match="模组库"):
        iter_golden_module_specs(tmp_path)
