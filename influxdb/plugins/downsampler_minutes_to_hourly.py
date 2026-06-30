"""
downsampler_minutes_to_hourly.py
─────────────────────────────────────────────────────────────────────────────
InfluxDB 3 Processing Engine Plugin
Role   : Aggregate energy_minute (1m) → energy_hour (1h)
Source : Database 'energy_minutes', measurement 'energy_minute'
Target : Database 'energy_hour',    measurement 'energy_hour'
Trigger: Scheduled — runs every 1 hour via cron "0 * * * *"

Install via CLI (inside InfluxDB container):
  influxdb3 create trigger \\
    --trigger-spec "every:1h" \\
    --plugin-filename "downsampler_minutes_to_hourly.py" \\
    --database energy_minutes \\
    --trigger-name minutes_to_hourly

Key aggregation rules:
  - SUM(sum_energy_kwh) → sum_energy_kwh  ← SUM of SUMs = total energy
  - AVG(avg_power_kw)   → avg_power_kw    ← AVG of AVGs = hourly avg demand
  - MIN(min_power_kw)   → min_power_kw    ← global minimum this hour
  - MAX(max_power_kw)   → max_power_kw    ← peak demand this hour
─────────────────────────────────────────────────────────────────────────────
"""

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
    source_db          = (args or {}).get("source_db",          "energy_minutes")
    source_measurement = (args or {}).get("source_measurement", "energy_minute")
    target_db          = (args or {}).get("target_db",          "energy_hour")
    target_measurement = (args or {}).get("target_measurement", "energy_hour")
    lookback_hours     = int((args or {}).get("lookback_hours", 2))

    # ── 2. Compute time window ────────────────────────────────────────────
    now     = datetime.now(timezone.utc)
    to_dt   = now.replace(minute=0, second=0, microsecond=0)            # floor to current hour
    from_dt = to_dt - timedelta(hours=lookback_hours)                   # look back N hours

    from_str = from_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    to_str   = to_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── 3. Query: aggregate minute data into 1-hour buckets ───────────────
    # IMPORTANT: SUM(sum_energy_kwh) — energy must be summed, not averaged.
    # AVG of AVGs is mathematically valid here because minute buckets are equal-length.
    sql = f"""
        SELECT
            DATE_BIN(INTERVAL '1 hour', time, TIMESTAMP '1970-01-01') AS bucket,
            machine_id,
            location,
            AVG(avg_power_kw)     AS avg_power_kw,
            SUM(sum_energy_kwh)   AS sum_energy_kwh,
            AVG(avg_voltage_v)    AS avg_voltage_v,
            AVG(avg_current_a)    AS avg_current_a,
            AVG(avg_power_factor) AS avg_power_factor,
            MIN(min_power_kw)     AS min_power_kw,
            MAX(max_power_kw)     AS max_power_kw,
            SUM(sample_count)     AS sample_count
        FROM {source_measurement}
        WHERE time >= TIMESTAMP '{from_str}'
          AND time <  TIMESTAMP '{to_str}'
        GROUP BY bucket, machine_id, location
        ORDER BY bucket ASC
    """

    try:
        reader = influxdb3_local.query(sql, database=source_db)
    except Exception as exc:
        print(f"[minutes_to_hourly] Query failed: {exc}")
        return

    # ── 4. Convert results to Line Protocol and write ─────────────────────
    rows_written = 0

    for batch in reader:
        for row in batch.to_pydict_list():
            bucket   = row.get("bucket")
            machine  = row.get("machine_id", "unknown")
            location = row.get("location",   "unknown")

            if bucket is None:
                continue

            # Convert timestamp to nanoseconds (InfluxDB Line Protocol)
            if hasattr(bucket, "timestamp"):
                ts_ns = int(bucket.timestamp() * 1_000_000_000)
            else:
                ts_ns = int(datetime.fromisoformat(str(bucket)).timestamp() * 1_000_000_000)

            # Build Line Protocol record
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
                print(f"[minutes_to_hourly] Write failed for {machine} @ {bucket}: {exc}")

    print(
        f"[minutes_to_hourly] Done — window [{from_str}, {to_str}] "
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
