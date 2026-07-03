"""Redis cache layer — cache-first with PG fallback.

Uses sync redis client (redis-py) to match the existing sync psycopg2 threading model.
When REDIS_URL is empty, all operations are transparent no-ops.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Lazy import — only loads if redis is available
_redis: Any = None


def _get_redis(url: str):
    """Lazy-init redis client. Returns None if no URL or import fails."""
    global _redis
    if _redis is not None:
        return _redis
    if not url:
        _redis = False  # Sentinel for "not configured"
        return None
    try:
        import redis as _r
        _redis = _r.from_url(url, decode_responses=False)
        _redis.ping()
        logger.info("Redis connected successfully")
    except Exception as e:
        logger.warning("Redis unavailable (%s), cache disabled", e)
        _redis = False
    return _redis if _redis is not False else None


def _r(url: str):
    return _get_redis(url)


class RedisCache:
    """Cache facade — all methods are no-ops when redis is unavailable."""

    def __init__(self, url: str = ""):
        self.url = url

    @property
    def available(self) -> bool:
        return _r(self.url) is not None

    # ── Event cache ──

    def cache_event(self, room_id: str, event_type: str, audience: str, payload: dict, sequence: int = 0):
        """Push event to per-room cache list (most recent 200)."""
        r = _r(self.url)
        if not r:
            return
        try:
            entry = json.dumps({
                "event_type": event_type,
                "audience": audience,
                "payload": payload,
                "sequence": sequence,
            }, ensure_ascii=False)
            key = f"room:{room_id}:events"
            r.lpush(key, entry)
            r.ltrim(key, 0, 199)
        except Exception as e:
            logger.debug("Redis cache_event failed: %s", e)

    def get_recent_events(self, room_id: str, since_sequence: int = 0, limit: int = 50) -> list[dict]:
        """Get recent events from cache. Returns [] on miss or unavailable."""
        r = _r(self.url)
        if not r:
            return []
        try:
            key = f"room:{room_id}:events"
            raw = r.lrange(key, 0, limit - 1)
            events = []
            for entry in raw:
                try:
                    ev = json.loads(entry)
                    if ev.get("sequence", 0) > since_sequence:
                        events.append(ev)
                except json.JSONDecodeError:
                    continue
            return list(reversed(events))  # chronological order
        except Exception as e:
            logger.debug("Redis get_recent_events failed: %s", e)
            return []

    # ── Room state cache ──

    def cache_hud(self, room_id: str, hud: dict, ttl: int = 60):
        """Cache HUD data with TTL."""
        r = _r(self.url)
        if not r:
            return
        try:
            key = f"room:{room_id}:hud"
            r.setex(key, ttl, json.dumps(hud, ensure_ascii=False))
        except Exception as e:
            logger.debug("Redis cache_hud failed: %s", e)

    def get_hud(self, room_id: str) -> dict | None:
        """Get cached HUD, None on miss."""
        r = _r(self.url)
        if not r:
            return None
        try:
            key = f"room:{room_id}:hud"
            raw = r.get(key)
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.debug("Redis get_hud failed: %s", e)
            return None

    def clear_room(self, room_id: str):
        """Clear all cached data for a room."""
        r = _r(self.url)
        if not r:
            return
        try:
            keys = r.keys(f"room:{room_id}:*")
            if keys:
                r.delete(*keys)
        except Exception as e:
            logger.debug("Redis clear_room failed: %s", e)


# Singleton convenience
_dflt: RedisCache | None = None


def get_cache(url: str = "") -> RedisCache:
    global _dflt
    if _dflt is None:
        _dflt = RedisCache(url)
    return _dflt
