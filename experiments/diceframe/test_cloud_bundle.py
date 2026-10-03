"""<summary>验证云部署包的版本和数据边界。</summary>"""

from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from experiments.diceframe import prepare_cloud


def test_refuses_existing_destination(tmp_path):
    """<summary>既有目录中的数据必须保留。</summary>
    <param name="tmp_path">隔离的临时目录。</param><returns>无返回值。</returns>
    """
    destination = tmp_path / "existing"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        prepare_cloud.build_bundle(tmp_path / "missing", destination)
    assert marker.read_text(encoding="utf-8") == "keep"


def test_rejects_different_revision(tmp_path):
    """<summary>错误基线不能生成看似可部署的目录。</summary>
    <param name="tmp_path">隔离的临时目录。</param><returns>无返回值。</returns>
    """
    source = tmp_path / "source"
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run([
        "git", "-C", str(source), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-q", "--allow-empty", "-m", "fixture",
    ], check=True)
    with pytest.raises(ValueError, match="基线"):
        prepare_cloud.build_bundle(source, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_exports_commit_and_patch_without_local_private_files(tmp_path):
    """<summary>真实候选源码的私有工作文件不进入镜像上下文或源码下载。</summary>
    <param name="tmp_path">隔离的临时目录。</param>
    <returns>无返回值。</returns>
    """
    root = Path(__file__).resolve().parents[2]
    original = root / ".runtime/diceframe-candidate/app"
    assert (original / ".git").exists(), "请先按 CANDIDATE.md 准备候选源码"
    source = tmp_path / "upstream"
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(original), str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "checkout", "-q", "--detach", prepare_cloud.UPSTREAM_COMMIT], check=True)
    (source / "data").mkdir()
    (source / "data/secrets.json").write_text('{"key":"PRIVATE-CANARY"}', encoding="utf-8")
    (source / "web_server.py").write_text("PRIVATE-CANARY", encoding="utf-8")
    output = prepare_cloud.build_bundle(source, tmp_path / "output")
    assert "PRIVATE-CANARY" not in (output / "app/web_server.py").read_text(encoding="utf-8")
    assert "game_users" in (output / "app/src/webui/session.py").read_text(encoding="utf-8")
    assert not (output / "app/data").exists()
    assert not (output / "app/.git").exists()
    assert (output / "compose.yaml").is_file()
    with zipfile.ZipFile(output / "source/diceframe-cloud-source.zip") as archive:
        assert "app/LICENSE" in archive.namelist()
        assert "0001-bind-player-seats.patch" in archive.namelist()
        assert not any("secrets.json" in name or "/.git/" in name for name in archive.namelist())
        assert b"PRIVATE-CANARY" not in archive.read("app/web_server.py")
    result = subprocess.run([sys.executable, "-c", """
import asyncio, contextlib, io, tempfile
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from pathlib import Path
from src.webui.host_credentials import HostCredentials
from src.webui.access_password import verify_access_password
from src.webui.session import SessionManager, session_middleware
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    state = {}
    output = io.StringIO()
    credentials = HostCredentials(state=state, data_dir=path,
        access_token_file=path / 'access_token.txt', environ={}, save_config=lambda: None)
    with contextlib.redirect_stdout(output):
        credentials.generate_initial_access_password()
    password = (path / 'access_token.txt').read_text().strip()
    assert password and verify_access_password(password, state['access_token'])
    assert password not in output.getvalue(), 'initial password leaked to stdout'
    app = web.Application()
    app['session_manager'] = SessionManager(path)
    async def handler(request):
        '''<summary>返回健康探测响应。</summary><param name="request">测试请求。</param><returns>正常响应。</returns>'''
        return web.json_response({'ok': True})
    for _ in range(3):
        request = make_mocked_request('GET', '/api/system/update/health', app=app)
        response = asyncio.run(session_middleware(request, handler))
        assert response.status == 200 and not response.cookies
    assert not (path / 'sessions.json').exists(), 'health probe persisted a session'
"""], cwd=output / "app", capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
