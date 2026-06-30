"""
jobs/minute_agg.py — Raw → Minute aggregation job.

Runs every 60 seconds via APScheduler.

Feature engineering performed:
  - avg_power_kw     : average power demand
  - sum_energy_kwh   : total energy consumed this minute
  - avg_voltage_v    : average voltage
  - avg_current_a    : average current
  - avg_power_factor : average power factor
  - min_power_kw     : min power (detect idle periods)
  - max_power_kw     : max power (detect peak demand)

Design:
  - Reads checkpoint from Redis (last processed window end)
  - Queries only the NEW window: [last_ts, now - offset]
  - Groups by machine_id + location + 1-minute bucket
  - Writes results to energy_minute measurement
  - Updates Redis checkpoint
  - No data is re-processed (idempotent by design)
"""

import logging
import time
from datetime import datetime, timezone

from influxdb_client_3 import Point

import influx_client as influx
import redis_client as rcache
from config import cfg

logger = logging.getLogger(__name__)


def run_minute_aggregation() -> None:
    """
    Aggregate energy_raw → energy_minute for the last completed minute window.
    Called every 60 seconds by APScheduler.
    """
    now_ts = int(time.time()) - cfg.AGG_MINUTE_OFFSET_SEC
    last_ts = rcache.get_last_ts(cfg.REDIS_KEY_LAST_MINUTE_TS, default_offset_sec=120)

    if now_ts <= last_ts:
        logger.debug("minute_agg: no new data window (last=%d, now=%d)", last_ts, now_ts)
        return

    # Convert Unix timestamps to ISO-8601 strings for SQL
    from_dt = datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    to_dt   = datetime.fromtimestamp(now_ts,  tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ──────────────────────────────────────────────────────────
    # SQL: Group raw data into 1-minute buckets per machine.
    # DATE_BIN is InfluxDB v3 / DuckDB style time bucketing.
    # ──────────────────────────────────────────────────────────
    sql = f"""
        SELECT
            DATE_BIN(INTERVAL '1 minute', time, TIMESTAMP '1970-01-01') AS bucket,
            machine_id,
            location,
            AVG(power_kw)     AS avg_power_kw,
            SUM(energy_kwh)   AS sum_energy_kwh,
            AVG(voltage_v)    AS avg_voltage_v,
            AVG(current_a)    AS avg_current_a,
            AVG(power_factor) AS avg_power_factor,
            MIN(power_kw)     AS min_power_kw,
            MAX(power_kw)     AS max_power_kw
        FROM {cfg.MEASUREMENT_RAW}
        WHERE time >= TIMESTAMP '{from_dt}'
          AND time <  TIMESTAMP '{to_dt}'
        GROUP BY bucket, machine_id, location
        ORDER BY bucket ASC
    """

    try:
        rows = influx.query_sql(sql)
    except Exception as exc:
        logger.error("minute_agg query failed: %s", exc)
        return

    if not rows:
        logger.info("minute_agg: no rows in [%s, %s]", from_dt, to_dt)
        rcache.set_last_ts(cfg.REDIS_KEY_LAST_MINUTE_TS, now_ts)
        return

    # ── Build Point objects for batch write ───────────────────
    points: list[Point] = []
    for row in rows:
        bucket_time = row.get("bucket")
        if bucket_time is None:
            continue

        # Convert pandas Timestamp → Python datetime if needed
        if hasattr(bucket_time, "to_pydatetime"):
            bucket_time = bucket_time.to_pydatetime()

        p = (
            Point(cfg.MEASUREMENT_MINUTE)
            .tag("machine_id", row["machine_id"])
            .tag("location",   row["location"])
            .field("avg_power_kw",     _safe_float(row.get("avg_power_kw")))
            .field("sum_energy_kwh",   _safe_float(row.get("sum_energy_kwh")))
            .field("avg_voltage_v",    _safe_float(row.get("avg_voltage_v")))
            .field("avg_current_a",    _safe_float(row.get("avg_current_a")))
            .field("avg_power_factor", _safe_float(row.get("avg_power_factor")))
            .field("min_power_kw",     _safe_float(row.get("min_power_kw")))
            .field("max_power_kw",     _safe_float(row.get("max_power_kw")))
            .time(bucket_time)
        )
        points.append(p)

    # ── Write batch ───────────────────────────────────────────
    try:
        influx.write_points(points)
        logger.info("minute_agg: wrote %d bucket(s) for window [%s, %s]",
                    len(points), from_dt, to_dt)
    except Exception as exc:
        logger.error("minute_agg write failed: %s", exc)
        return  # Don't advance checkpoint — retry next cycle

    # ── Advance checkpoint only on success ────────────────────
    rcache.set_last_ts(cfg.REDIS_KEY_LAST_MINUTE_TS, now_ts)


def _safe_float(value) -> float:
    """Return float or 0.0 for None/NaN values."""
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0
