from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_API_BASE = os.getenv("AIKEEPER_API_BASE", "http://127.0.0.1:3001")
DEFAULT_DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://aikeeper:aikeeper123@127.0.0.1:5432/aikeeper",
)
DEFAULT_OUTPUT_DIR = ROOT / "docs" / "loop_runs"
DEFAULT_CARDS = [
    ROOT / "data" / "test_assets" / "最小测试模块" / "tzq12138_01_记者.xlsx",
    ROOT / "data" / "test_assets" / "最小测试模块" / "tzq12138_02_私家侦探.xlsx",
    ROOT / "data" / "test_assets" / "最小测试模块" / "tzq12138_03_教授.xlsx",
    ROOT / "data" / "test_assets" / "最小测试模块" / "tzq12138_04_医生.xlsx",
]
DEFAULT_PLAYERS = [
    {"label": "P1", "username": "loop_p1", "password": "test123", "display_name": "Loop P1"},
    {"label": "P2", "username": "loop_p2", "password": "test123", "display_name": "Loop P2"},
    {"label": "P3", "username": "loop_p3", "password": "test123", "display_name": "Loop P3"},
    {"label": "P4", "username": "loop_p4", "password": "test123", "display_name": "Loop P4"},
]
DEFAULT_HOST = {
    "username": "loop_host",
    "password": "test123",
    "display_name": "Loop Host",
    "role": "host",
}
DEFAULT_ENDING = {
    "ending_type": "victory",
    "ending_name": "成功逃脱",
    "text": "调查员们趁仪式尚未完成前逃出烬头村，成功避开灯塔焚祭，带着伤痕与真相幸存离开。",
}
DEFAULT_TURNS = [
    [
        "我先观察旅店外的村民和道路，确认离开村子的路线。",
        "我低声询问老板和路人，打听今晚灯塔附近会发生什么。",
        "我检查桌上的旧报纸与笔记，寻找村庄与火祭相关的记录。",
        "我留意同伴的精神状态，并检查是否有人受伤或异常惊慌。",
    ]
]


class LoopError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 AI-Keeper 四玩家多人 loop 并导出测试文档。")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE, help="后端 API 基地址，例如 http://127.0.0.1:3001")
    parser.add_argument("--database-url", default=DEFAULT_DB_URL, help="本地开发数据库 DSN，仅 --ensure-accounts 时使用")
    parser.add_argument("--ensure-accounts", action="store_true", help="启动前直接写库确保 host/player 测试账号存在")
    parser.add_argument("--host-username", default=DEFAULT_HOST["username"])
    parser.add_argument("--host-password", default=DEFAULT_HOST["password"])
    parser.add_argument("--scenario-id", default="", help="指定剧本 scenario_id")
    parser.add_argument("--scenario-title", default="向火独行", help="未指定 scenario_id 时，按标题包含匹配可用剧本")
    parser.add_argument("--turn-script", default="", help="JSON 文件；支持 {'turns': [...], 'ending': {...}}")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--room-prefix", default="loop-yhdx")
    parser.add_argument("--turn-timeout", type=int, default=90, help="每轮等待自动结算的秒数")
    parser.add_argument("--ai-fallback-after", type=int, default=12, help="多少秒无进展后尝试手动 ai-turn")
    parser.add_argument("--ending-type", default=DEFAULT_ENDING["ending_type"])
    parser.add_argument("--ending-name", default=DEFAULT_ENDING["ending_name"])
    parser.add_argument("--ending-text", default=DEFAULT_ENDING["text"])
    return parser.parse_args()


def log(message: str) -> None:
    print(f"[loop] {message}", flush=True)


def request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    expected_status: int | None = None,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> Any:
    response = client.request(method, path, headers=headers, **kwargs)
    if expected_status is not None:
        if response.status_code != expected_status:
            raise LoopError(f"{method} {path} -> {response.status_code}: {response.text}")
    elif response.status_code >= 400:
        raise LoopError(f"{method} {path} -> {response.status_code}: {response.text}")
    if not response.content:
        return None
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return response.json()
    return response.text


def maybe_import_psycopg2():
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError as exc:
        raise LoopError("缺少 psycopg2，无法执行 --ensure-accounts") from exc
    return psycopg2, RealDictCursor


def ensure_accounts(database_url: str, host_username: str, host_password: str) -> None:
    psycopg2, cursor_cls = maybe_import_psycopg2()
    from src.server.router_auth import _hash_password

    roles = [
        {
            "username": host_username,
            "password": host_password,
            "display_name": DEFAULT_HOST["display_name"],
            "role": "host",
        },
        *[
            {
                "username": player["username"],
                "password": player["password"],
                "display_name": player["display_name"],
                "role": "player",
            }
            for player in DEFAULT_PLAYERS
        ],
    ]

    conn = psycopg2.connect(database_url)
    try:
        with conn:
            with conn.cursor(cursor_factory=cursor_cls) as cur:
                for account in roles:
                    cur.execute(
                        "SELECT account_id FROM accounts WHERE username = %s",
                        (account["username"],),
                    )
                    existing = cur.fetchone()
                    password_hash = _hash_password(account["password"])
                    if existing:
                        cur.execute(
                            "UPDATE accounts "
                            "SET password_hash = %s, display_name = %s, role = %s "
                            "WHERE username = %s",
                            (
                                password_hash,
                                account["display_name"],
                                account["role"],
                                account["username"],
                            ),
                        )
                    else:
                        cur.execute(
                            "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
                            "VALUES (%s, %s, %s, %s, %s)",
                            (
                                str(uuid.uuid4())[:8],
                                account["username"],
                                password_hash,
                                account["display_name"],
                                account["role"],
                            ),
                        )
    finally:
        conn.close()


def load_turn_spec(path: str) -> tuple[list[Any], dict[str, str]]:
    if not path:
        return DEFAULT_TURNS, dict(DEFAULT_ENDING)
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        turns = raw.get("turns", DEFAULT_TURNS)
        ending = raw.get("ending", dict(DEFAULT_ENDING))
    else:
        turns = raw
        ending = dict(DEFAULT_ENDING)
    if not isinstance(turns, list) or not turns:
        raise LoopError("turn-script 必须提供非空 turns 列表")
    return turns, {
        "ending_type": ending.get("ending_type", DEFAULT_ENDING["ending_type"]),
        "ending_name": ending.get("ending_name", DEFAULT_ENDING["ending_name"]),
        "text": ending.get("text", DEFAULT_ENDING["text"]),
    }


def login(client: httpx.Client, username: str, password: str) -> dict[str, Any]:
    return request_json(
        client,
        "POST",
        "/api/auth/login",
        json={"username": username, "password": password},
        expected_status=200,
    )


def resolve_scenario_id(
    client: httpx.Client,
    host_token: str,
    scenario_id: str,
    title_contains: str,
) -> tuple[str, str]:
    if scenario_id:
        scenarios = request_json(
            client,
            "GET",
            "/api/scenarios/available",
            headers={"Authorization": f"Bearer {host_token}"},
            expected_status=200,
        )
        for scenario in scenarios:
            if scenario["scenario_id"] == scenario_id:
                return scenario["scenario_id"], scenario.get("title", scenario_id)
        raise LoopError(f"未在可用剧本中找到 scenario_id={scenario_id}")

    scenarios = request_json(
        client,
        "GET",
        "/api/scenarios/available",
        headers={"Authorization": f"Bearer {host_token}"},
        expected_status=200,
    )
    title_contains = title_contains.strip()
    for scenario in scenarios:
        if title_contains and title_contains in scenario.get("title", ""):
            return scenario["scenario_id"], scenario.get("title", "")
    titles = ", ".join(sorted(s.get("title", "") for s in scenarios))
    raise LoopError(f"未找到标题包含“{title_contains}”的剧本。当前可用剧本：{titles}")


def create_room(client: httpx.Client, host_token: str, scenario_id: str) -> dict[str, Any]:
    return request_json(
        client,
        "POST",
        f"/api/scenarios/{scenario_id}/create-room",
        headers={"Authorization": f"Bearer {host_token}"},
        json={},
        expected_status=200,
    )


def join_player(
    client: httpx.Client,
    room_id: str,
    account_token: str,
    player_label: str,
    card_path: Path,
) -> dict[str, Any]:
    if not card_path.exists():
        raise LoopError(f"缺少角色卡：{card_path}")
    files = {
        "file": (
            card_path.name,
            card_path.read_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    data = {"player_name": player_label}
    result = request_json(
        client,
        "POST",
        f"/api/player/rooms/{room_id}/join-with-character",
        headers={"Authorization": f"Bearer {account_token}"},
        data=data,
        files=files,
        expected_status=200,
    )
    return {
        "label": player_label,
        "token": result["player_token"],
        "character_id": result["character_id"],
        "player_name": result["player_name"],
        "investigator_name": result.get("investigator_name", ""),
        "join_result": result,
    }


def submit_ready(client: httpx.Client, player_token: str) -> Any:
    return request_json(
        client,
        "POST",
        "/api/player/intent",
        headers={"X-Room-Token": player_token},
        json={
            "action_id": str(uuid.uuid4()),
            "intent_type": "ready_toggle",
            "declared_intent": "切换准备状态",
        },
        expected_status=202,
    )


def start_room(client: httpx.Client, room_id: str, owner_token: str) -> dict[str, Any]:
    return request_json(
        client,
        "POST",
        f"/api/rooms/{room_id}/start",
        headers={"X-Owner-Token": owner_token},
        json={},
        expected_status=200,
    )


def normalize_turn_actions(turn_spec: Any, players: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
    if isinstance(turn_spec, list):
        if len(turn_spec) != len(players):
            raise LoopError(f"turn 动作数 {len(turn_spec)} 与玩家数 {len(players)} 不一致")
        return [(player, str(action)) for player, action in zip(players, turn_spec, strict=True)]

    if isinstance(turn_spec, dict):
        pairs = []
        for player in players:
            keys = [
                player["label"],
                player.get("player_name", ""),
                player.get("investigator_name", ""),
            ]
            action = None
            for key in keys:
                if key and key in turn_spec:
                    action = str(turn_spec[key])
                    break
            if action is None:
                raise LoopError(f"turn 字典缺少玩家 {player['label']} / {player.get('investigator_name', '')} 的动作")
            pairs.append((player, action))
        return pairs

    raise LoopError("turn-script 每轮必须是 list 或 dict")


def submit_turn(
    client: httpx.Client,
    players: list[dict[str, Any]],
    actions: list[tuple[dict[str, Any], str]],
) -> list[dict[str, Any]]:
    results = []
    for player, text in actions:
        action_id = str(uuid.uuid4())
        result = request_json(
            client,
            "POST",
            "/api/player/intent",
            headers={"X-Room-Token": player["token"]},
            json={
                "action_id": action_id,
                "intent_type": "dialogue",
                "declared_intent": text,
            },
            expected_status=202,
        )
        results.append(
            {
                "label": player["label"],
                "investigator_name": player.get("investigator_name", ""),
                "player_token": player["token"],
                "action_id": action_id,
                "declared_intent": text,
                "submit_result": result,
            }
        )
    return results


def get_turn_snapshot(client: httpx.Client, room_id: str, owner_token: str) -> dict[str, Any]:
    return request_json(
        client,
        "GET",
        f"/api/rooms/{room_id}/turns/current",
        headers={"X-Owner-Token": owner_token},
        expected_status=200,
    )


def maybe_trigger_ai_turn(client: httpx.Client, room_id: str, owner_token: str) -> bool:
    try:
        response = client.post(
            f"/api/rooms/{room_id}/ai-turn",
            headers={"X-Owner-Token": owner_token},
        )
    except httpx.TimeoutException:
        log("ai-turn 兜底请求超时，继续轮询已有行动")
        return False
    if response.status_code == 200:
        return True
    if response.status_code == 400 and "No pending actions to process" in response.text:
        return False
    raise LoopError(f"POST /api/rooms/{room_id}/ai-turn -> {response.status_code}: {response.text}")


def get_action_status(client: httpx.Client, player_token: str, action_id: str) -> dict[str, Any]:
    return request_json(
        client,
        "GET",
        f"/api/player/actions/{action_id}",
        headers={"X-Room-Token": player_token},
        expected_status=200,
    )


def wait_for_actions_resolution(
    client: httpx.Client,
    room_id: str,
    owner_token: str,
    submitted_actions: list[dict[str, Any]],
    timeout_seconds: int,
    ai_fallback_after: int,
) -> dict[str, Any]:
    start = time.monotonic()
    fallback_triggered = False
    fallback_attempted = False
    last_statuses: list[dict[str, Any]] = []

    while time.monotonic() - start <= timeout_seconds:
        last_statuses = [
            {
                **action,
                "status_result": get_action_status(client, action["player_token"], action["action_id"]),
            }
            for action in submitted_actions
        ]
        statuses = [item["status_result"].get("status", "") for item in last_statuses]
        if all(status not in {"queued", "batched", "resolving"} for status in statuses):
            return {
                "actions": last_statuses,
                "_fallback_triggered": fallback_triggered,
            }
        if (
            not fallback_attempted
            and "resolving" not in statuses
            and time.monotonic() - start >= ai_fallback_after
        ):
            fallback_attempted = True
            fallback_triggered = maybe_trigger_ai_turn(client, room_id, owner_token) or fallback_triggered
        time.sleep(1.0)

    raise LoopError(
        "等待动作结算超时。最后状态："
        f"{json.dumps(last_statuses, ensure_ascii=False)}"
    )


def end_campaign(
    client: httpx.Client,
    room_id: str,
    owner_token: str,
    ending: dict[str, str],
) -> dict[str, Any]:
    return request_json(
        client,
        "POST",
        f"/api/rooms/{room_id}/end",
        headers={"X-Owner-Token": owner_token},
        json=ending,
        expected_status=200,
    )


def capture_room(
    client: httpx.Client,
    room_id: str,
    owner_token: str,
    players: list[dict[str, Any]],
) -> dict[str, Any]:
    campaign = request_json(
        client,
        "GET",
        f"/api/rooms/{room_id}/campaign",
        headers={"X-Owner-Token": owner_token},
        params={"scope": "full"},
        expected_status=200,
    )
    timeline = request_json(
        client,
        "GET",
        f"/api/rooms/{room_id}/timeline",
        headers={"X-Owner-Token": owner_token},
        params={"since_sequence": 0, "limit": 500},
        expected_status=200,
    )
    export_markdown = request_json(
        client,
        "GET",
        f"/api/rooms/{room_id}/export",
        headers={"X-Owner-Token": owner_token},
        params={"format": "markdown", "scope": "full"},
        expected_status=200,
    )
    player_captures = []
    for player in players:
        headers = {"X-Room-Token": player["token"]}
        player_captures.append(
            {
                "label": player["label"],
                "investigator": player.get("investigator_name", ""),
                "token": player["token"],
                "character": player["character_id"],
                "archive_actions": request_json(
                    client,
                    "GET",
                    "/api/player/archive/actions",
                    headers=headers,
                    expected_status=200,
                ),
                "archive_clues": request_json(
                    client,
                    "GET",
                    "/api/player/archive/clues",
                    headers=headers,
                    expected_status=200,
                ),
                "archive_skill_checks": request_json(
                    client,
                    "GET",
                    "/api/player/archive/skill-checks",
                    headers=headers,
                    expected_status=200,
                ),
                "archive_all": request_json(
                    client,
                    "GET",
                    "/api/player/archive",
                    headers=headers,
                    expected_status=200,
                ),
            }
        )

    return {
        "room_id": room_id,
        "players": player_captures,
        "campaign": campaign,
        "timeline": timeline,
        "export_markdown": export_markdown,
    }


def render_player_log(player_capture: dict[str, Any]) -> str:
    lines = [
        f"# {player_capture['label']} - {player_capture.get('investigator', '')}",
        "",
        f"- `character_id`: `{player_capture['character']}`",
        f"- `archive_total`: `{player_capture.get('archive_all', {}).get('total', 0)}`",
        "",
        "## 动作",
    ]
    actions = player_capture.get("archive_actions", {}).get("actions", [])
    if not actions:
        lines.append("- 无动作记录")
    else:
        for action in actions:
            narrative = (
                (action.get("result") or {}).get("narrative")
                or (action.get("result") or {}).get("text")
                or ""
            )
            lines.extend(
                [
                    f"- `{action.get('created_at', '')}` `{action.get('intent_type', '')}`",
                    f"  - 声明：{action.get('declared_intent', '')}",
                    f"  - 结果：{narrative}",
                ]
            )

    clues = player_capture.get("archive_clues", {}).get("clues", [])
    lines.append("")
    lines.append("## 线索")
    if not clues:
        lines.append("- 无线索")
    else:
        for clue in clues:
            clue_text = clue.get("text") or clue.get("data", {}).get("text") or ""
            lines.append(f"- `{clue.get('sequence', '')}` {clue_text}")

    entries = player_capture.get("archive_all", {}).get("entries", [])
    lines.append("")
    lines.append("## 事件摘录")
    if not entries:
        lines.append("- 无事件")
    else:
        for entry in entries[:12]:
            payload = entry.get("data", {})
            text = payload.get("text") or payload.get("actionId") or json.dumps(payload, ensure_ascii=False)
            lines.append(f"- `#{entry.get('sequence', '')}` `{entry.get('type', '')}` {text}")
    lines.append("")
    return "\n".join(lines)


def _find_campaign_end_payload(capture: dict[str, Any]) -> dict[str, Any]:
    for event in reversed(capture.get("timeline", {}).get("events", [])):
        if event.get("event_type") == "s2c_campaign_ended":
            return event.get("payload", {}) or {}
    return {}


def render_report(
    run_meta: dict[str, Any],
    capture: dict[str, Any],
    turn_results: list[dict[str, Any]],
    player_log_paths: list[Path],
    json_path: Path,
) -> str:
    campaign = capture["campaign"]
    ending = campaign.get("ending", {}) or {}
    ending_payload = _find_campaign_end_payload(capture)
    key_events = campaign.get("key_events", []) or []
    export_block = capture.get("export_markdown", {})
    export_content = export_block.get("content", "") if isinstance(export_block, dict) else str(export_block)
    ending_name = (
        ending.get("ending_name")
        or ending.get("endingName")
        or ending_payload.get("endingName")
        or ending_payload.get("endingPhase")
        or ""
    )

    lines = [
        f"# AI-Keeper {len(capture['players'])} 玩家多人 Loop 测试报告",
        "",
        "## 概览",
        f"- 运行时间：`{run_meta['started_at']}`",
        f"- API 基址：`{run_meta['api_base']}`",
        f"- 房间：`{run_meta['room_id']}`",
        f"- 剧本：`{run_meta['scenario_title']}` (`{run_meta['scenario_id']}`)",
        f"- 结局：`{ending.get('ending_type', '')}` / `{ending_name}`",
        f"- 总动作数：`{campaign.get('total_actions', 0)}`",
        f"- 结局触发方式：`显式调用 /api/rooms/{{room_id}}/end`",
        "",
        "## 覆盖链路",
        "- Host 登录 → 选择剧本 → 开房",
        f"- {len(capture['players'])} 个玩家账号登录 → 上传 xlsx 角色卡 → 入房",
        f"- {len(capture['players'])} 个玩家 ready → Host 开局",
        f"- 同回合 {len(capture['players'])} 条行动提交 → 自动结算",
        "- Host 战役总结 / Timeline / Export",
        "- Player 个人 Archive / Actions / Clues / Skill Checks",
        "",
        "## Loop 健壮性",
        f"- 自动回合数：`{len(turn_results)}`",
        f"- AI fallback 调用：`{sum(1 for item in turn_results if item.get('fallback_triggered'))}` 次",
        "- 可通过 `--api-base` 切换到新的后端实例",
        "- 可通过 `--turn-script` 替换动作脚本与结局文案",
        "- 可通过 `--ensure-accounts` 在本地开发库中自动补齐 host/player 测试账号",
        "",
        "## 本次提交动作",
    ]
    for index, turn in enumerate(turn_results, start=1):
        lines.append(f"- Turn {index}:")
        for action in turn["actions"]:
            lines.append(
                f"  - `{action['label']}` / `{action['investigator_name']}`：{action['declared_intent']}"
            )

    lines.extend(
        [
            "",
            "## 关键事件",
        ]
    )
    if not key_events:
        lines.append("- 无关键事件")
    else:
        for event in key_events:
            lines.append(
                f"- `#{event.get('sequence', '')}` `{event.get('event_type') or event.get('type', '')}` at `{event.get('issued_at') or event.get('timestamp', '')}`"
            )

    lines.extend(
        [
            "",
            "## 玩家日志文件",
        ]
    )
    for path in player_log_paths:
        lines.append(f"- `{path}`")

    lines.extend(
        [
            "",
            "## 导出摘要",
            "```markdown",
            export_content[:1200].strip(),
            "```",
            "",
            "## 产物",
            f"- JSON 捕获：`{json_path}`",
            f"- Markdown 报告：`{run_meta['report_path']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    turns, ending = load_turn_spec(args.turn_script)
    ending["ending_type"] = args.ending_type or ending["ending_type"]
    ending["ending_name"] = args.ending_name or ending["ending_name"]
    ending["text"] = args.ending_text or ending["text"]

    if args.ensure_accounts:
        log("确保本地测试账号存在")
        ensure_accounts(args.database_url, args.host_username, args.host_password)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(base_url=args.api_base.rstrip("/"), timeout=30.0, follow_redirects=True) as client:
        host_auth = login(client, args.host_username, args.host_password)
        log(f"Host 登录成功：{args.host_username}")

        scenario_id, scenario_title = resolve_scenario_id(
            client,
            host_auth["token"],
            args.scenario_id,
            args.scenario_title,
        )
        log(f"使用剧本：{scenario_title} ({scenario_id})")

        room = create_room(client, host_auth["token"], scenario_id)
        room_id = room["room_id"]
        owner_token = room["owner_token"]
        log(f"已创建房间：{room_id}")

        players: list[dict[str, Any]] = []
        for template, card_path in zip(DEFAULT_PLAYERS, DEFAULT_CARDS, strict=True):
            player_auth = login(client, template["username"], template["password"])
            joined = join_player(
                client,
                room_id,
                player_auth["token"],
                template["label"],
                card_path,
            )
            players.append(
                {
                    **template,
                    **joined,
                    "account_token": player_auth["token"],
                }
            )
            log(
                f"{template['label']} 入房成功：{joined.get('investigator_name', '')} / {joined['character_id']}"
            )

        for player in players:
            submit_ready(client, player["token"])
        log(f"{len(players)} 名玩家均已 ready")

        started = start_room(client, room_id, owner_token)
        current_turn_index = started["turn_index"]
        log(f"房间已开局，当前 turn={current_turn_index}")

        turn_results = []
        for turn_number, turn_spec in enumerate(turns, start=1):
            actions = normalize_turn_actions(turn_spec, players)
            submitted = submit_turn(client, players, actions)
            resolved = wait_for_actions_resolution(
                client,
                room_id,
                owner_token,
                submitted,
                args.turn_timeout,
                args.ai_fallback_after,
            )
            turn_results.append(
                {
                    "turn_index": turn_number,
                    "actions": submitted,
                    "resolved_actions": resolved["actions"],
                    "fallback_triggered": bool(resolved.get("_fallback_triggered")),
                }
            )
            log(f"turn {turn_number} 的 {len(submitted)} 条动作已全部结算")

        ended = end_campaign(client, room_id, owner_token, ending)
        log(
            f"战役已结束：{ended.get('ending_type', '')} / {ended.get('ending_name', '') or ended.get('endingName', '')}"
        )

        capture = capture_room(client, room_id, owner_token, players)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    run_prefix = f"{timestamp}-{room_id}"
    json_path = output_dir / f"{run_prefix}.json"
    json_path.write_text(json.dumps(capture, ensure_ascii=False, indent=2), encoding="utf-8")

    player_log_paths = []
    for player_capture in capture["players"]:
        safe_label = player_capture["label"].lower()
        player_log_path = output_dir / f"{run_prefix}-{safe_label}.md"
        player_log_path.write_text(render_player_log(player_capture), encoding="utf-8")
        player_log_paths.append(player_log_path)

    report_path = output_dir / f"{run_prefix}.md"
    report_path.write_text(
        render_report(
            {
                "started_at": timestamp,
                "api_base": args.api_base,
                "room_id": room_id,
                "scenario_id": scenario_id,
                "scenario_title": scenario_title,
                "report_path": report_path,
            },
            capture,
            turn_results,
            player_log_paths,
            json_path,
        ),
        encoding="utf-8",
    )

    summary = {
        "room_id": room_id,
        "scenario_id": scenario_id,
        "scenario_title": scenario_title,
        "json_path": str(json_path),
        "report_path": str(report_path),
        "player_logs": [str(path) for path in player_log_paths],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
