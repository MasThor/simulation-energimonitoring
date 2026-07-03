"""
downsampler_raw_to_minutes.py
─────────────────────────────────────────────────────────────────────────────
InfluxDB 3 Processing Engine Plugin
Role   : Aggregate energy_raw (10s) → energy_minute (1m)
Source : Database 'energy_monitoring', measurement 'energy_raw'
Target : Database 'energy_minutes',   measurement 'energy_minute'
Trigger: Scheduled — runs every 1 minute via cron "*/1 * * * *"

Install via CLI (inside InfluxDB container):
  influxdb3 create trigger \\
    --trigger-spec "every:1m" \\
    --plugin-filename "downsampler_raw_to_minutes.py" \\
    --database energy_monitoring \\
    --trigger-name raw_to_minutes

Design principles:
  - Lookback window: last 2 minutes to catch any late-arriving data
  - Idempotent: InfluxDB upserts on same timestamp+tags
  - Safe: skips window if no rows found (no error)
  - Clean: all aggregations are semantically correct
─────────────────────────────────────────────────────────────────────────────
"""

import json
from datetime import datetime, timezone, timedelta


def process(influxdb3_local, query_parameters, args=None):
    """
    Entry point called by InfluxDB 3 Processing Engine.

    Args:
        influxdb3_local : InfluxDB API object (query + write methods)
        query_parameters: Dict of trigger parameters
        args            : Optional dict from plugin_arguments
    """

    # ── 1. Configuration ──────────────────────────────────────────────────
    source_db          = (args or {}).get("source_db",          "energy_monitoring")
    source_measurement = (args or {}).get("source_measurement", "energy_raw")
    target_db          = (args or {}).get("target_db",          "energy_minutes")
    target_measurement = (args or {}).get("target_measurement", "energy_minute")
    lookback_minutes   = int((args or {}).get("lookback_minutes", 2))

    # ── 2. Compute time window ────────────────────────────────────────────
    now     = datetime.now(timezone.utc)
    to_dt   = now.replace(second=0, microsecond=0)                      # floor to current minute
    from_dt = to_dt - timedelta(minutes=lookback_minutes)               # look back N minutes

    from_str = from_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    to_str   = to_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── 3. Query: aggregate raw data into 1-minute buckets ────────────────
    sql = f"""
        SELECT
            DATE_BIN(INTERVAL '1 minute', time, TIMESTAMP '1970-01-01') AS bucket,
            machine_id,
            location,
            AVG(power_kw)       AS avg_power_kw,
            SUM(energy_kwh)     AS sum_energy_kwh,
            AVG(voltage_v)      AS avg_voltage_v,
            AVG(current_a)      AS avg_current_a,
            AVG(power_factor)   AS avg_power_factor,
            MIN(power_kw)       AS min_power_kw,
            MAX(power_kw)       AS max_power_kw,
            COUNT(*)            AS sample_count
        FROM {source_measurement}
        WHERE time >= TIMESTAMP '{from_str}'
          AND time <  TIMESTAMP '{to_str}'
        GROUP BY bucket, machine_id, location
        ORDER BY bucket ASC
    """

    try:
        reader = influxdb3_local.query(sql, database=source_db)
    except Exception as exc:
        print(f"[raw_to_minutes] Query failed: {exc}")
        return

    # ── 4. Convert results to Line Protocol and write ─────────────────────
    rows_written = 0

    for batch in reader:
        for row in batch.to_pydict_list():
            bucket    = row.get("bucket")
            machine   = row.get("machine_id", "unknown")
            location  = row.get("location",   "unknown")

            if bucket is None:
                continue

            # Convert timestamp to nanoseconds (InfluxDB Line Protocol)
            if hasattr(bucket, "timestamp"):
                ts_ns = int(bucket.timestamp() * 1_000_000_000)
            else:
                ts_ns = int(datetime.fromisoformat(str(bucket)).timestamp() * 1_000_000_000)

            # Build Line Protocol record
            # Format: measurement,tag1=v1,tag2=v2 field1=v1,field2=v2 timestamp
            line = (
                f"{target_measurement}"
                f",machine_id={_escape_tag(machine)}"
                f",location={_escape_tag(location)}"
                f" "
                f"avg_power_kw={_safe_float(row.get('avg_power_kw'))},"
                f"sum_energy_kwh={_safe_float(row.get('sum_energy_kwh'))},"
                f"avg_voltage_v={_safe_float(row.get('avg_voltage_v'))},"
                f"avg_current_a={_safe_float(row.get('avg_current_a'))},"
                f"avg_power_factor={_safe_float(row.get('avg_power_factor'))},"
                f"min_power_kw={_safe_float(row.get('min_power_kw'))},"
                f"max_power_kw={_safe_float(row.get('max_power_kw'))},"
                f"sample_count={int(row.get('sample_count', 0))}i"
                f" {ts_ns}"
            )

            try:
                influxdb3_local.write(
                    line_protocol=line,
                    database=target_db,
                )
                rows_written += 1
            except Exception as exc:
                print(f"[raw_to_minutes] Write failed for {machine} @ {bucket}: {exc}")

    print(
        f"[raw_to_minutes] Done — window [{from_str}, {to_str}] "
        f"→ {rows_written} bucket(s) written to '{target_db}'.'{target_measurement}'"
    )


# ── Helpers ───────────────────────────────────────────────────────────────

def _safe_float(value) -> float:
    """Return float or 0.0 for None/NaN values."""
    try:
        v = float(value)
        return 0.0 if v != v else v  # NaN check: NaN != NaN
    except (TypeError, ValueError):
        return 0.0


def _escape_tag(value: str) -> str:
    """Escape spaces and commas in tag values for InfluxDB Line Protocol."""
    return str(value).replace(" ", r"\ ").replace(",", r"\,").replace("=", r"\=")
