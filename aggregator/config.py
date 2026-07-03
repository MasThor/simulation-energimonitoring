"""
config.py — Centralized configuration loaded from environment variables.
All defaults are safe fallbacks for local development.
"""

import os


class Config:
    # ── Redis ─────────────────────────────────────────────────
    REDIS_HOST: str = os.environ.get("REDIS_HOST", "redis")
    REDIS_PORT: int = int(os.environ.get("REDIS_PORT", "6379"))
    REDIS_PASSWORD: str = os.environ.get("REDIS_PASSWORD", "redispass")
    REDIS_DB: int = 0

    # ── InfluxDB v3 ───────────────────────────────────────────
    INFLUX_HOST: str = os.environ.get("INFLUX_HOST", "http://influxdb:8086")
    INFLUX_TOKEN: str = os.environ.get("INFLUX_TOKEN", "")
    INFLUX_DATABASE: str = os.environ.get("INFLUX_DATABASE", "energy_monitoring")

    # ── Retention (days) ─────────────────────────────────────
    RETENTION_RAW_DAYS: int = int(os.environ.get("RETENTION_RAW_DAYS", "14"))
    RETENTION_MINUTE_DAYS: int = int(os.environ.get("RETENTION_MINUTE_DAYS", "30"))
    # Hour data is kept forever — no deletion job needed

    # ── Aggregation tuning ────────────────────────────────────
    # Offset (seconds) subtracted from "now" when querying,
    # to avoid race conditions where the latest second of a
    # window hasn't fully arrived yet.
    AGG_MINUTE_OFFSET_SEC: int = int(os.environ.get("AGG_MINUTE_OFFSET_SEC", "5"))
    AGG_HOUR_OFFSET_SEC: int = int(os.environ.get("AGG_HOUR_OFFSET_SEC", "30"))

    # ── Measurement names ─────────────────────────────────────
    MEASUREMENT_RAW: str = "energy_raw"
    MEASUREMENT_MINUTE: str = "energy_minute"
    MEASUREMENT_HOUR: str = "energy_hour"

    # ── Redis key prefixes ────────────────────────────────────
    REDIS_KEY_LAST_MINUTE_TS: str = "agg:last_minute_ts"
    REDIS_KEY_LAST_HOUR_TS: str = "agg:last_hour_ts"


cfg = Config()
