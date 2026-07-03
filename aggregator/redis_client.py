"""
redis_client.py — Redis checkpoint helper.

Responsibilities:
  - Store and retrieve last-aggregation timestamps (Unix seconds).
  - These checkpoints ensure aggregation jobs are idempotent:
    if the service restarts, it picks up exactly where it left off.
"""

import logging
import time

import redis

from config import cfg

logger = logging.getLogger(__name__)

# Module-level connection pool (reused across all calls)
_pool = redis.ConnectionPool(
    host=cfg.REDIS_HOST,
    port=cfg.REDIS_PORT,
    password=cfg.REDIS_PASSWORD,
    db=cfg.REDIS_DB,
    decode_responses=True,
    max_connections=5,
)


def _conn() -> redis.Redis:
    return redis.Redis(connection_pool=_pool)


def get_last_ts(key: str, default_offset_sec: int = 60) -> int:
    """
    Retrieve the last-aggregation Unix timestamp from Redis.

    If no checkpoint exists (first run), returns `now - default_offset_sec`
    so the first job processes the most recent completed window.
    """
    value = _conn().get(key)
    if value is None:
        ts = int(time.time()) - default_offset_sec
        logger.info("No checkpoint for '%s'. Starting from %d seconds ago.", key, default_offset_sec)
        return ts
    return int(value)


def set_last_ts(key: str, ts: int) -> None:
    """Persist the last-aggregation timestamp for a given job key."""
    _conn().set(key, str(ts))
    logger.debug("Checkpoint '%s' updated to %d", key, ts)


def ping() -> bool:
    """Health-check: return True if Redis responds."""
    try:
        return _conn().ping()
    except redis.RedisError as exc:
        logger.error("Redis ping failed: %s", exc)
        return False
