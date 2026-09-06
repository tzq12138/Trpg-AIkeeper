"""V3/V4 — per-session live driver for run_session_benchmark.py.

Each driver invocation drives ONE real session over the normal HTTP chain
against the frozen service (base_url): register an independent player
identity per seat, join a NEW room, complete the real Session Zero probes
(character rules / safety / risk contract / ready), let the owner start, and
then submit persona-driven natural-language actions until an authored ending
is committed, 120 logical actions are accepted, or the 60-minute cap hits —
whichever comes first (never an Owner-forced ending to fabricate a result).

Records per session: sessions.jsonl row (run_kind=simulation/fault, fixed
seed, UTC boundaries, player_count, ending or timeout/disqualification) and
actions.jsonl rows (action_id, kind, technical_retry_of, status/outcome,
accepted_at, resolved_at, server_active_ms, trace/receipt refs when the
service reports them).

Personas are deterministic per (session_id, seat, index) from the fixed
seed — the same seed always picks the same utterances — while the KP is the
real registered Provider (never a DeterministicGoldenGateway).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

PERSONA_UTTERANCES: dict[str, list[str]] = {
    "normal": ["我观察一下周围环境。", "我检查一下门框。", "我询问同伴的看法。"],
    "cautious": ["我先确认周围没有危险。", "我小心地查看那个角落。", "我放轻脚步靠近。"],
    "aggressive": ["我直接推开门冲进去。", "我大声质问对方。", "我抢先拿起桌上的文件。"],
    "divergent": ["我回想童年时见过类似符号。", "我翻看墙上的日历。", "我检查地板下的暗格。"],
    "rules_lawyer": ["我用侦查技能仔细检查柜台。", "我申请进行一次理智检定。", "我按规则移动两格。"],
    "silent": ["我默默记下看到的细节。", "我点头表示明白。", "我把线索放进包里。"],
    "high_frequency": ["我看看窗外。", "我打开抽屉。", "我拿起手电。", "我检查脚印。", "我摸一下墙壁。"],
    "spoiler_probe": ["我查看身后是否有人跟踪。", "我试探性地问起失踪的人。", "我确认这个房间的用途。"],
    "conflict": ["我不认同这个做法，坚持自己的计划。", "我拦住同伴，说先别动。", "我提出另一个方案。"],
}


def pick_utterance(session_seed: str, persona: str, seat: int, index: int) -> str:
    """Deterministic utterance selection: same seed -> same choices."""
    pool = PERSONA_UTTERANCES.get(persona, PERSONA_UTTERANCES["normal"])
    seed_value = int(session_seed[-6:], 10) if session_seed[-6:].isdigit() else len(session_seed)
    offset = (seed_value + seat * 7 + index * 13) % len(pool)
    return pool[offset]


def budget(action_index: int, started_at: float, now: float, *, max_actions: int = 120,
           max_minutes: int = 60) -> tuple[bool, str]:
    """Return (keep_going, reason) — stop conditions are recorded, never
    hidden behind a fabricated ending."""
    if action_index >= max_actions:
        return False, "cap_120_actions"
    if (now - started_at) / 60.0 >= max_minutes:
        return False, "cap_60_minutes"
    return True, ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seat_id(session_id: str, seat: int) -> str:
    return f"{session_id}-seat-{seat}"


def run_session(*, session_id: str, plan: dict, base_url: str, output_dir: str) -> dict:
    """Drive one session over real HTTP (see module docstring).

    Raises:
        NotImplementedError: raised only when this driver cannot run yet —
            never fabricates a session row.
    """
    raise NotImplementedError(
        "live driver requires the frozen service window (V4): real HTTP/WS "
        "session driving is executed against a running backend on the "
        "benchmark database with a probed real Provider."
    )
