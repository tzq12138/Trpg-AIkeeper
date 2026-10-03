"""<summary>固定候选版的真实 HTTP 席位隔离与认领回归。</summary>"""

import asyncio
from copy import deepcopy
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

# <summary>显式加载固定候选源码及其真实集成夹具。</summary>
UPSTREAM = Path(os.environ.get("DICEFRAME_ROOT", Path(__file__).resolve().parents[3] / ".runtime/diceframe-candidate/app"))
if not (UPSTREAM / "tests/test_share_gm_seat_guard.py").exists():
    pytest.skip("需要固定候选源码及依赖，见 CANDIDATE.md", allow_module_level=True)
sys.path[:0] = [str(UPSTREAM), str(UPSTREAM / "tests")]

from test_share_gm_seat_guard import share_env, _cookie, _share_url
from test_game_query_routes_http import play_env, _owner_password, _owner, _make_app
from src.engine.player_control import set_control
from src.webui.session import SessionManager, session_middleware
from src.webui.routes.sse import register_sse
from src.webui.sse_ticket import SseTicketStore
from src.webui.connection_pool import ConnectionPool
from webapi_harness import web_api


@pytest.fixture
def real_stream_routes(share_env):
    """<summary>为权限用例装配实际 SSE 路由和票据存储。</summary>
    <param name="share_env">真实 HTTP 夹具。</param><returns>无返回值。</returns>
    """
    register_sse(share_env.app)
    share_env.app["sse_tickets"] = SseTicketStore()
    share_env.app["connection_pool"] = ConnectionPool()


@pytest.mark.asyncio
@pytest.mark.parametrize("path,method", [("private-log", "get"), ("action", "post"), ("sse-ticket", "post"), ("sse", "get")])
async def test_other_seat_query_is_denied_without_mutation(share_env, real_stream_routes, path, method):
    """<summary>拒绝 URL 冒用，且不改角色、私信或会话。</summary>
    <param name="share_env">真实 HTTP 夹具。</param><param name="real_stream_routes">实际实时路由。</param><param name="path">接口。</param>
    <param name="method">HTTP 方法。</param><returns>无返回值。</returns>
    """
    env = share_env
    before = deepcopy((env.instance.players, env.instance.private_log, env.sessions._sessions))
    async with TestClient(TestServer(env.app)) as client:
        response = await getattr(client, method)(_share_url(env, path, "p2"), headers=_cookie(env.token), **({"json": {"text": "观察现场"}} if method == "post" else {}))
        response.close()
        assert response.status == 403
    assert (env.instance.players, env.instance.private_log, env.sessions._sessions) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("identity_path", ["cookie", "query"])
async def test_existing_member_cannot_claim_other_human_seat(share_env, identity_path):
    """<summary>拒绝借入座接口把自己的会话换绑到他人。</summary>
    <param name="share_env">真实 HTTP 夹具。</param><param name="identity_path">身份入口。</param>
    <returns>无返回值。</returns>
    """
    env = share_env
    before = deepcopy(env.instance.players)
    async with TestClient(TestServer(env.app)) as client:
        response = await client.post(_share_url(env, "players", "p2" if identity_path == "query" else None), headers=_cookie(env.token), json={"user_id": "p2"})
        assert response.status == 403
    assert env.sessions._sessions[env.token]["user_id"] == "p1"
    assert env.instance.players == before


@pytest.mark.asyncio
async def test_unclaimed_invitation_can_be_claimed_once_then_reconnected(share_env):
    """<summary>原生邀请允许首次认领，同会话恢复，阻止第二人冒领。</summary>
    <param name="share_env">真实 HTTP 夹具。</param><returns>无返回值。</returns>
    """
    env = share_env
    set_control(env.instance, "p2", "unclaimed")
    first_token, _ = env.sessions.get_or_create(None)
    second_token, second_uid = env.sessions.get_or_create(None)
    async with TestClient(TestServer(env.app)) as client:
        detail = await client.get(f"/api/games/{env.key}?share=1&user=p2", headers=_cookie(first_token))
        assert detail.status == 200
        assert "B private" not in await detail.text()
        first = await client.post(_share_url(env, "players", "p2"), headers=_cookie(first_token), json={"user_id": "p2"})
        assert first.status == 200
        assert (await first.json())["ok"] is True
        own = await client.get(_share_url(env, "private-log", "p2"), headers=_cookie(first_token))
        assert own.status == 200
        assert [item["text"] for item in (await own.json())["messages"]] == ["B private"]
        second = await client.post(_share_url(env, "players"), headers=_cookie(second_token), json={"user_id": "p2"})
        assert second.status == 403
        again = await client.post(_share_url(env, "players"), headers=_cookie(first_token), json={"user_id": "p2"})
        assert again.status == 200
    assert SessionManager(env.sessions._path.parent).get_or_create(first_token)[1] == "p2"
    assert env.sessions._sessions[second_token]["user_id"] == second_uid


@pytest.mark.asyncio
async def test_claim_stays_private_after_ai_takeover(share_env):
    """<summary>AI 托管只改变控制方式，不能释放已认领的身份。</summary>
    <param name="share_env">真实 HTTP 夹具。</param><returns>无返回值。</returns>
    """
    env = share_env
    set_control(env.instance, "p2", "unclaimed")
    first_token, _ = env.sessions.get_or_create(None)
    other_token, _ = env.sessions.get_or_create(None)
    async with TestClient(TestServer(env.app)) as client:
        response = await client.post(_share_url(env, "players"), headers=_cookie(first_token), json={"user_id": "p2"})
        assert response.status == 200
        reloaded = await env.app["subsystems"].registry.load(env.instance.game_key)
        assert reloaded is not None
        env.instance.players = reloaded.players
        set_control(env.instance, "p2", "ai")
        stolen = await client.post(_share_url(env, "players"), headers=_cookie(other_token), json={"user_id": "p2"})
        assert stolen.status == 403


@pytest.mark.asyncio
async def test_concurrent_claim_has_one_winner(share_env):
    """<summary>并发初次认领必须只有一个会话取得席位。</summary>
    <param name="share_env">真实 HTTP 夹具。</param><returns>无返回值。</returns>
    """
    env = share_env
    set_control(env.instance, "p2", "unclaimed")
    tokens = [env.sessions.get_or_create(None)[0] for _ in range(2)]
    async with TestClient(TestServer(env.app)) as client:
        responses = await asyncio.gather(*(client.post(_share_url(env, "players"), headers=_cookie(token), json={"user_id": "p2"}) for token in tokens))
        assert sorted(response.status for response in responses) == [200, 403]
    assert sum(env.sessions._sessions[token]["user_id"] == "p2" for token in tokens) == 1


@pytest.mark.asyncio
async def test_owner_preview_remains_isolated_and_does_not_rebind(share_env):
    """<summary>房主可预览目标席位，但不会混入另一席位私信。</summary>
    <param name="share_env">真实 HTTP 夹具。</param><returns>无返回值。</returns>
    """
    env = share_env
    async with TestClient(TestServer(env.app)) as client:
        response = await client.get(_share_url(env, "private-log", "p2"), headers={**_cookie(env.gm_token), **_owner()})
        assert response.status == 200
        assert [item["text"] for item in (await response.json())["messages"]] == ["B private"]
    assert env.sessions._sessions[env.gm_token]["user_id"] == env.instance.gm_uid


@pytest.mark.asyncio
async def test_own_sse_ticket_cannot_be_switched_to_other_actor(share_env, real_stream_routes):
    """<summary>实时票据绑定本人，即使连接附上他人 UID 也保持本人。</summary>
    <param name="share_env">真实 HTTP 夹具。</param><param name="real_stream_routes">实际实时路由。</param><returns>无返回值。</returns>
    """
    env = share_env
    async with TestClient(TestServer(env.app)) as client:
        response = await client.post(_share_url(env, "sse-ticket"), headers=_cookie(env.token))
        assert response.status == 200
        ticket = (await response.json())["ticket"]
        stream = await client.get(_share_url(env, "sse", "p2") + "&ticket=" + ticket, headers=_cookie(env.token))
        assert stream.status == 200
        await stream.content.readline()
        assert "p1" in env.app["connection_pool"]._conns[env.key]
        assert "p2" not in env.app["connection_pool"]._conns[env.key]
        stream.close()
        replay = await client.get(_share_url(env, "sse") + "&ticket=" + ticket, headers=_cookie(env.token))
        assert replay.status == 401


@pytest.mark.asyncio
async def test_real_game_creation_keeps_unclaimed_seat_available(web_api, tmp_path):
    """<summary>真实建团预设的未认领卡应可首次加入，而非被提前锁死。</summary>
    <param name="tmp_path">隔离会话目录。</param><param name="web_api">真实创建与持久化服务。</param>
    <returns>无返回值。</returns>
    """
    api, _, registry, _, _ = web_api
    created = await api.create_game("template_world", "Claimable", solo=False, gm_uid="host", room_password="", players=[{"character_name": "Host"}, {"character_name": "Guest"}], unclaimed_control_default="unclaimed")
    assert created["ok"] is True
    instance = registry.get(api._parse_key(created["game_key"]))
    assert instance.gm_uid == "host"
    assert "host" not in instance.players
    guest = next(uid for uid in instance.players if uid != "host")
    app = _make_app(SimpleNamespace(api=api, registry=registry))
    sessions = SessionManager(tmp_path / "sessions")
    app["session_manager"] = sessions
    app.middlewares.insert(0, session_middleware)
    token, _ = sessions.get_or_create(None)
    async with TestClient(TestServer(app)) as client:
        response = await client.post(f"/api/games/{created['game_key']}/players?share=1&user={guest}", headers=_cookie(token), json={"user_id": guest})
        assert response.status == 200
        assert (await response.json())["ok"] is True
    assert sessions._sessions[token]["user_id"] == guest


@pytest.mark.asyncio
async def test_independent_host_can_subscribe_without_a_player_seat(share_env, real_stream_routes):
    """<summary>房主不占角色卡时仍收到实时桌面状态。</summary>
    <param name="share_env">HTTP 会话夹具。</param><param name="real_stream_routes">实际实时路由。</param>
    <returns>无返回值。</returns>
    """
    env = share_env
    env.instance.players.pop(env.instance.gm_uid)
    async with TestClient(TestServer(env.app)) as client:
        response = await client.post(_share_url(env, "sse-ticket"), headers={**_cookie(env.gm_token), **_owner()})
        assert response.status == 200
        ticket = (await response.json())["ticket"]
        stream = await client.get(f"/api/games/{env.key}/sse?ticket={ticket}")
        assert stream.status == 200
        await stream.content.readline()
        assert env.instance.gm_uid in env.app["connection_pool"]._conns[env.key]
        stream.close()
