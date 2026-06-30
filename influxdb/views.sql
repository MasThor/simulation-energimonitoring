-- ============================================================
-- InfluxDB v3 — SQL Views for Energy Monitoring
-- ============================================================
-- Run these in the InfluxDB v3 UI (Data Explorer → SQL Editor)
-- or via the influx CLI:
--   influx query --file views.sql
--
-- InfluxDB v3 supports SQL via Apache Arrow Flight SQL.
-- Use the built-in Data Explorer at http://localhost:8086
-- ============================================================


-- ── View 1: Latest reading per machine (Real-Time Status) ───
-- Shows the most recent data point for each machine.
-- Useful for a "current status" dashboard tile.

SELECT
    machine_id,
    location,
    last(power_kw)      AS latest_power_kw,
    last(energy_kwh)    AS latest_energy_kwh,
    last(voltage_v)     AS latest_voltage_v,
    last(current_a)     AS latest_current_a,
    last(power_factor)  AS latest_power_factor,
    max(time)           AS last_seen
FROM energy_raw
WHERE time >= now() - INTERVAL '5 minutes'
GROUP BY machine_id, location
ORDER BY machine_id;


-- ── View 2: Minute trend — last 1 hour ──────────────────────
-- Use for real-time trend charts (last 60 data points per machine).

SELECT
    time                AS bucket,
    machine_id,
    location,
    avg_power_kw,
    sum_energy_kwh,
    avg_voltage_v,
    avg_power_factor,
    min_power_kw,
    max_power_kw
FROM energy_minute
WHERE time >= now() - INTERVAL '1 hour'
ORDER BY machine_id, time ASC;


-- ── View 3: Hourly energy consumption — last 7 days ─────────
-- For daily/weekly energy consumption reports.

SELECT
    time                AS hour_bucket,
    machine_id,
    location,
    sum_energy_kwh,
    avg_power_kw,
    max_power_kw,
    avg_power_factor,
    sample_count
FROM energy_hour
WHERE time >= now() - INTERVAL '7 days'
ORDER BY machine_id, time ASC;


-- ── View 4: Daily energy summary (from hour data) ───────────
-- Aggregate hourly → daily using SQL GROUP BY on date truncation.

SELECT
    DATE_BIN(INTERVAL '1 day', time, TIMESTAMP '1970-01-01') AS day,
    machine_id,
    location,
    SUM(sum_energy_kwh)     AS total_energy_kwh,
    AVG(avg_power_kw)       AS avg_power_kw,
    MAX(max_power_kw)       AS peak_power_kw,
    AVG(avg_power_factor)   AS avg_power_factor,
    SUM(sample_count)       AS total_samples
FROM energy_hour
WHERE time >= now() - INTERVAL '30 days'
GROUP BY day, machine_id, location
ORDER BY machine_id, day ASC;


-- ── View 5: Machine comparison — current hour ────────────────
-- Compare all machines side-by-side for the last completed hour.
-- Great for identifying high-consumption machines.

SELECT
    machine_id,
    location,
    SUM(sum_energy_kwh)   AS energy_kwh_this_hour,
    AVG(avg_power_kw)     AS avg_power_kw,
    MAX(max_power_kw)     AS peak_power_kw,
    MIN(min_power_kw)     AS min_power_kw,
    AVG(avg_power_factor) AS avg_pf
FROM energy_minute
WHERE time >= DATE_BIN(INTERVAL '1 hour', now(), TIMESTAMP '1970-01-01')
GROUP BY machine_id, location
ORDER BY energy_kwh_this_hour DESC;


-- ── View 6: Power factor alert — machines below 0.90 ────────
-- Identify machines with poor power factor for maintenance.

SELECT
    machine_id,
    location,
    AVG(avg_power_factor) AS avg_pf_last_hour,
    COUNT(*)              AS sample_count
FROM energy_minute
WHERE time >= now() - INTERVAL '1 hour'
GROUP BY machine_id, location
HAVING AVG(avg_power_factor) < 0.90
ORDER BY avg_pf_last_hour ASC;
