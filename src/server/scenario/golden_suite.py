from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GoldenModuleSpec:
    slug: str
    title: str
    source_paths: tuple[Path, ...]
    source_mode: str


_GOLDEN_MODULES = (
    ("CN_向火独行", "cn-into-the-flames", "向火独行", "scenario"),
    ("CN_众神的霓虹", "cn-neon-gods", "众神的霓虹：接触", "scenario_with_assets"),
    ("CN_猩红文档", "cn-scarlet-document", "猩红文档", "scenario"),
    ("CN_常暗之厢", "cn-the-dark-box", "常暗之厢", "legacy_scanned"),
    (
        "EN_Alone-Against-the-Flames",
        "en-alone-against-the-flames",
        "Alone Against the Flames",
        "scenario",
    ),
    ("EN_Doors-to-Darkness", "en-doors-to-darkness", "Doors to Darkness", "materials_only"),
    ("EN_Gateways-to-Terror", "en-gateways-to-terror", "Gateways to Terror", "materials_only"),
    ("EN_The-Lightless-Beacon", "en-lightless-beacon", "The Lightless Beacon", "scenario_with_assets"),
    ("EN_Mansions-of-Madness", "en-mansions-of-madness", "Mansions of Madness", "materials_only"),
)

_SOURCE_SUFFIXES = {".pdf", ".doc", ".docx"}


def iter_golden_module_specs(root: Path) -> list[GoldenModuleSpec]:
    module_root = root / "模组库"
    if not module_root.is_dir():
        raise FileNotFoundError(f"黄金样本缺少模组库目录: {module_root}")

    specs: list[GoldenModuleSpec] = []
    for directory, slug, title, source_mode in _GOLDEN_MODULES:
        source_dir = module_root / directory
        if not source_dir.is_dir():
            raise FileNotFoundError(f"黄金样本缺少模组目录: {source_dir}")
        source_paths = tuple(
            sorted(
                (
                    path for path in source_dir.iterdir()
                    if path.is_file() and path.suffix.lower() in _SOURCE_SUFFIXES
                ),
                key=lambda path: path.name.lower(),
            )
        )
        if not source_paths:
            raise FileNotFoundError(f"黄金模组没有可导入来源文件: {source_dir}")
        specs.append(GoldenModuleSpec(
            slug=slug,
            title=title,
            source_paths=source_paths,
            source_mode=source_mode,
        ))
    return sorted(specs, key=lambda spec: spec.slug)
