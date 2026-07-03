"""
jobs/hour_agg.py — Minute → Hour aggregation job.

Runs every 3600 seconds (1 hour) via APScheduler.

Key design decisions:
  - Reads from energy_MINUTE (NOT raw) — lighter query, already pre-aggregated
  - This is the "feature engineering cascade":
      Raw (10s) → Minute (1m) → Hour (1h)
  - Extra derived field: peak_hour_flag
      Set to 1 if max_power_kw in this hour exceeded 80% of a 30-day
      rolling average — helps detect peak demand periods.
      (Simplified: just include max_power_kw so operators can judge manually)

Feature engineering performed:
  - avg_power_kw      : average power over the hour
  - sum_energy_kwh    : total energy this hour (sum of minute sums)
  - avg_voltage_v     : hourly average voltage
  - avg_current_a     : hourly average current
  - avg_power_factor  : hourly average PF
  - min_power_kw      : minimum power in the hour
  - max_power_kw      : peak power in the hour
  - sample_count      : number of minute samples (quality indicator)
"""

import logging
import time
from datetime import datetime, timezone

from influxdb_client_3 import Point

import influx_client as influx
import redis_client as rcache
from config import cfg

logger = logging.getLogger(__name__)


def run_hour_aggregation() -> None:
    """
    Aggregate energy_minute → energy_hour for the last completed hour window.
    Called every 3600 seconds by APScheduler.
    """
    now_ts = int(time.time()) - cfg.AGG_HOUR_OFFSET_SEC
    last_ts = rcache.get_last_ts(cfg.REDIS_KEY_LAST_HOUR_TS, default_offset_sec=7200)

    if now_ts <= last_ts:
        logger.debug("hour_agg: no new data window (last=%d, now=%d)", last_ts, now_ts)
        return

    from_dt = datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    to_dt   = datetime.fromtimestamp(now_ts,  tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ──────────────────────────────────────────────────────────
    # SQL: Group minute data into 1-hour buckets per machine.
    # Source: energy_minute (NOT raw) — cascade aggregation.
    # ──────────────────────────────────────────────────────────
    sql = f"""
        SELECT
            DATE_BIN(INTERVAL '1 hour', time, TIMESTAMP '1970-01-01') AS bucket,
            machine_id,
            location,
            AVG(avg_power_kw)         AS avg_power_kw,
            SUM(sum_energy_kwh)       AS sum_energy_kwh,
            AVG(avg_voltage_v)        AS avg_voltage_v,
            AVG(avg_current_a)        AS avg_current_a,
            AVG(avg_power_factor)     AS avg_power_factor,
            MIN(min_power_kw)         AS min_power_kw,
            MAX(max_power_kw)         AS max_power_kw,
            COUNT(*)                  AS sample_count
        FROM {cfg.MEASUREMENT_MINUTE}
        WHERE time >= TIMESTAMP '{from_dt}'
          AND time <  TIMESTAMP '{to_dt}'
        GROUP BY bucket, machine_id, location
        ORDER BY bucket ASC
    """

    try:
        rows = influx.query_sql(sql)
    except Exception as exc:
        logger.error("hour_agg query failed: %s", exc)
        return

    if not rows:
        logger.info("hour_agg: no rows in [%s, %s]", from_dt, to_dt)
        rcache.set_last_ts(cfg.REDIS_KEY_LAST_HOUR_TS, now_ts)
        return

    # ── Build Point objects ───────────────────────────────────
    points: list[Point] = []
    for row in rows:
        bucket_time = row.get("bucket")
        if bucket_time is None:
            continue

        if hasattr(bucket_time, "to_pydatetime"):
            bucket_time = bucket_time.to_pydatetime()

        p = (
            Point(cfg.MEASUREMENT_HOUR)
            .tag("machine_id", row["machine_id"])
            .tag("location",   row["location"])
            .field("avg_power_kw",     _safe_float(row.get("avg_power_kw")))
            .field("sum_energy_kwh",   _safe_float(row.get("sum_energy_kwh")))
            .field("avg_voltage_v",    _safe_float(row.get("avg_voltage_v")))
            .field("avg_current_a",    _safe_float(row.get("avg_current_a")))
            .field("avg_power_factor", _safe_float(row.get("avg_power_factor")))
            .field("min_power_kw",     _safe_float(row.get("min_power_kw")))
            .field("max_power_kw",     _safe_float(row.get("max_power_kw")))
            .field("sample_count",     int(row.get("sample_count", 0)))
            .time(bucket_time)
        )
        points.append(p)

    try:
        influx.write_points(points)
        logger.info("hour_agg: wrote %d bucket(s) for window [%s, %s]",
                    len(points), from_dt, to_dt)
    except Exception as exc:
        logger.error("hour_agg write failed: %s", exc)
        return  # Don't advance checkpoint — retry next cycle

    rcache.set_last_ts(cfg.REDIS_KEY_LAST_HOUR_TS, now_ts)


def _safe_float(value) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0
