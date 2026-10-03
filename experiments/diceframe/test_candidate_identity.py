"""<summary>在独立 Python 进程中执行候选 HTTP 回归，避免两个项目的 src 包冲突。</summary>"""

import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_candidate_http_identity_contract():
    """<summary>使用实际候选源码执行完整身份、认领和实时连接合同。</summary>
    <returns>无返回值。</returns>
    """
    root = Path(__file__).resolve().parents[2]
    upstream = Path(os.environ.get("DICEFRAME_ROOT", root / ".runtime/diceframe-candidate/app"))
    if not (upstream / "tests/test_share_gm_seat_guard.py").is_file():
        pytest.skip("需准备固定候选源码及依赖，见 CANDIDATE.md")
    checks = Path(__file__).resolve().parent / "checks"
    result = subprocess.run([
        sys.executable, "-X", "utf8", "-m", "pytest", str(checks / "identity_http.py"),
        "--rootdir=.", "--confcutdir=" + str(checks), "-c", "pyproject.toml", "-q", "--tb=short",
    ], cwd=upstream, capture_output=True, text=True, encoding="utf-8", timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
