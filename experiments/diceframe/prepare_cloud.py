"""<summary>从固定 Git 提交生成不含运行数据的 Diceframe 云部署包。</summary>"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile


# <summary>已通过候选版权限和短团验收的上游提交。</summary>
UPSTREAM_COMMIT = "297da1f06d1e177ade2324eb35d9eb8e1dff89cb"


def build_bundle(upstream: Path, destination: Path) -> Path:
    """<summary>导出固定源码、应用权限补丁并附上部署配置和对应源码。</summary>
    <param name="upstream">已检出固定提交的上游 Git 仓库。</param>
    <param name="destination">尚不存在的输出目录。</param>
    <returns>生成的部署目录。</returns>
    """
    upstream, destination = upstream.resolve(), destination.resolve()
    if destination.exists():
        raise FileExistsError(f"拒绝覆盖已有部署目录：{destination}")
    revision = subprocess.check_output(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True,
    ).strip()
    if revision != UPSTREAM_COMMIT:
        raise ValueError(f"上游基线不匹配：需要 {UPSTREAM_COMMIT}")

    # 1. Git archive 仅取提交内容，排除运行数据和工作区修改。
    destination.mkdir(parents=True)
    app = destination / "app"
    app.mkdir()
    archive_path = destination / "upstream.tar"
    subprocess.run([
        "git", "-C", str(upstream), "archive", "--format=tar",
        "--output", str(archive_path), UPSTREAM_COMMIT,
    ], check=True)
    with tarfile.open(archive_path) as archive:
        archive.extractall(app, filter="data")
    archive_path.unlink()

    # 2. 在导出目录应用补丁，不修改正在运行的本机候选源码。
    base = Path(__file__).resolve().parent
    patch = destination / "0001-bind-player-seats.patch"
    shutil.copyfile(base / "patches" / patch.name, patch)
    environment = os.environ.copy()
    environment.pop("GIT_DIR", None)
    environment.pop("GIT_WORK_TREE", None)
    environment["GIT_CEILING_DIRECTORIES"] = str(destination)
    for path in (base / "cloud").iterdir():
        if path.is_file():
            shutil.copyfile(path, destination / path.name)
    for patch_file in (patch, destination / "0002-cloud-runtime.patch"):
        for arguments in (["--check"], []):
            subprocess.run(["git", "apply", *arguments, str(patch_file)], cwd=app, env=environment, check=True)
    (destination / "release.json").write_text(json.dumps({
        "upstream": "https://github.com/diceframe/diceframe",
        "commit": UPSTREAM_COMMIT,
        "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
        "cloud_patch_sha256": hashlib.sha256((destination / "0002-cloud-runtime.patch").read_bytes()).hexdigest(),
        "self_update": False,
        "runtime_data_included": False,
    }, indent=2) + "\n", encoding="utf-8")

    # 3. 对应源码包只收录以上导出内容，不收录随后产生的 data 或凭据。
    files = sorted(path for path in destination.rglob("*") if path.is_file())
    (destination / "source").mkdir()
    with zipfile.ZipFile(destination / "source/diceframe-cloud-source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(destination).as_posix())
    return destination


def main() -> None:
    """<summary>解析部署包输出路径并执行准备。</summary><returns>无返回值。</returns>"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--upstream", type=Path, default=Path(".runtime/diceframe-candidate/app"))
    arguments = parser.parse_args()
    print(build_bundle(arguments.upstream, arguments.destination))


if __name__ == "__main__":
    main()
