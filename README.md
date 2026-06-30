# ⚡ Manufacturing Energy Monitoring System

Real-time energy monitoring stack for industrial environments using MQTT, time-series storage, and cascading aggregation.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   MANUFACTURING FLOOR                       │
│         [Machine 1]  [Machine 2]  ...  [Machine N]          │
│               │           │                │                 │
│               └───────────┴────────────────┘                │
│                      Modbus / OPC-UA                        │
└──────────────────────────┬──────────────────────────────────┘
                           │
                 ┌─────────▼──────────┐
                 │     Node-RED       │  Publish JSON @ 10s
                 │  (Data Collector)  │  QoS 1
                 └─────────┬──────────┘
                           │  MQTT   topic: factory/{loc}/{id}/energy
                 ┌─────────▼──────────────────────┐
                 │         EMQX 5.x               │
                 │   MQTT Broker + Rule Engine     │
                 └──────┬──────────────────────────┘
                        │ Line Protocol (HTTP POST)
                 ┌──────▼───────────┐
                 │   InfluxDB v3    │
                 │  ┌─────────────┐ │     ┌──────────────────────┐
                 │  │ energy_raw  │ │◄────│ Python Aggregator     │
                 │  │  (14 days)  │ │     │  APScheduler          │
                 │  ├─────────────┤ │     │  every 60s  → minute  │
                 │  │energy_minute│◄│─────│  every 3600s → hour   │
                 │  │  (30 days)  │ │     │  every 24h  → cleanup │
                 │  ├─────────────┤ │     └──────────┬───────────┘
                 │  │ energy_hour │ │                │ checkpoint
                 │  │  (forever)  │ │          ┌─────▼──────┐
                 │  └─────────────┘ │          │   Redis 7  │
                 │   SQL View UI    │          │  (state)   │
                 └──────────────────┘          └────────────┘
```

### Data Flow & Feature Engineering Cascade

```
Raw (every ~10s)
  └─► energy_raw           → stored as-is
         │
         │ [every 60s] Python reads raw window
         │  DATE_BIN 1min GROUP BY machine
         │  AVG, SUM, MIN, MAX of each field
         ▼
  energy_minute             → pre-aggregated per minute
         │
         │ [every 3600s] Python reads minute window
         │  DATE_BIN 1hour GROUP BY machine
         │  AVG, SUM, MIN, MAX — from minute (NOT raw)
         ▼
  energy_hour               → fully aggregated per hour
```

> **Why cascade?** Aggregating hour from *minutes* instead of *raw* means the query scans 60 rows instead of potentially 360+ raw points. This keeps the hourly job fast and consistent.

---

## Services

| Service | Image | Port | Role |
|---|---|---|---|
| `redis` | `redis:7-alpine` | 6379 | Checkpoint storage |
| `emqx` | `emqx:5.7.0` | 1883, 18083 | MQTT Broker + Rule Engine |
| `influxdb` | `influxdb:3-core` | 8086 | Time-series database + UI |
| `nodered` | `nodered/node-red:3.1-minimal` | 1880 | Data collector |
| `aggregator` | `./aggregator` | — | Feature engineering service |

---

## Quick Start

### 1. Configure environment

```bash
# Clone and enter project
cd energy-monitoring

# Copy environment file and set your credentials
cp .env .env.local   # or edit .env directly
```

Edit `.env` — at minimum, change the token and passwords:

```bash
INFLUX_TOKEN=your-secure-token-here
REDIS_PASSWORD=your-redis-password
EMQX_DASHBOARD_PASS=your-dashboard-password
```

### 2. Start the stack

```bash
docker compose up -d
```

### 3. Configure EMQX Rule Engine

Open the dashboard at **http://localhost:18083** (admin / `EMQX_DASHBOARD_PASS`).

**Create MQTT user** (for Node-RED):
> Access Control → Authentication → Built-in Database → Add User
> - Username: `iot_user`
> - Password: `MQTT_PASS` from `.env`

**Create HTTP Connector** (for InfluxDB write):
> Integration → Connectors → Create → HTTP
> - Name: `influxdb_v3`
> - URL: `http://influxdb:8086`
> - Headers:
>   - `Authorization`: `Token <your INFLUX_TOKEN>`
>   - `Content-Type`: `text/plain; charset=utf-8`

**Create Rule**:
> Integration → Rules → Create
>
> **SQL Filter:**
> ```sql
> SELECT
>   payload.machine_id   AS machine_id,
>   payload.location     AS location,
>   payload.power_kw     AS power_kw,
>   payload.energy_kwh   AS energy_kwh,
>   payload.voltage_v    AS voltage_v,
>   payload.current_a    AS current_a,
>   payload.power_factor AS power_factor,
>   payload.timestamp    AS ts_ms
> FROM "factory/+/+/energy"
> ```
>
> **Action** (HTTP Request via connector):
> - Method: `POST`
> - Path: `/api/v3/write_lp?db=energy_monitoring&precision=ms`
> - Body:
> ```
> energy_raw,machine_id=${machine_id},location=${location} power_kw=${power_kw},energy_kwh=${energy_kwh},voltage_v=${voltage_v},current_a=${current_a},power_factor=${power_factor} ${ts_ms}
> ```

See [`emqx/rule_engine.conf`](./emqx/rule_engine.conf) for full details.

### 4. Verify aggregator is running

```bash
docker logs energy_aggregator -f
```

Expected output on startup:
```
2024-01-01T10:00:00  INFO      aggregator  Redis is ready ✓
2024-01-01T10:00:01  INFO      aggregator  InfluxDB is ready ✓
2024-01-01T10:00:01  INFO      aggregator  Scheduler started. Running...
```

### 5. View data in InfluxDB

Open **http://localhost:8086** → Data Explorer → SQL Mode.

Copy queries from [`influxdb/views.sql`](./influxdb/views.sql).

**Quick check — latest readings:**
```sql
SELECT machine_id, last(power_kw) AS power_kw, max(time) AS last_seen
FROM energy_raw
WHERE time >= now() - INTERVAL '5 minutes'
GROUP BY machine_id
```

---

## MQTT Payload Format

Node-RED publishes to topic: `factory/{location}/{machine_id}/energy`

```json
{
  "machine_id":   "machine_001",
  "location":     "line_a",
  "timestamp":    1719652800000,
  "power_kw":     15.32,
  "energy_kwh":   1205.67,
  "voltage_v":    220.1,
  "current_a":    39.6,
  "power_factor": 0.97
}
```

---

## Database Schema

### `energy_raw` — Raw readings (retention: 14 days)

| Column | Type | Description |
|---|---|---|
| `time` | TIMESTAMP | Measurement time (from device) |
| `machine_id` | TAG | Machine identifier |
| `location` | TAG | Physical line/area |
| `power_kw` | FLOAT | Instantaneous power (kW) |
| `energy_kwh` | FLOAT | Cumulative energy meter (kWh) |
| `voltage_v` | FLOAT | Line voltage (V) |
| `current_a` | FLOAT | Line current (A) |
| `power_factor` | FLOAT | Power factor (0–1) |

### `energy_minute` — Minute aggregates (retention: 30 days)

| Column | Type | Description |
|---|---|---|
| `time` | TIMESTAMP | Minute bucket start |
| `machine_id` | TAG | Machine identifier |
| `location` | TAG | Physical line/area |
| `avg_power_kw` | FLOAT | Average power this minute |
| `sum_energy_kwh` | FLOAT | Energy consumed this minute |
| `avg_voltage_v` | FLOAT | Average voltage |
| `avg_current_a` | FLOAT | Average current |
| `avg_power_factor` | FLOAT | Average power factor |
| `min_power_kw` | FLOAT | Minimum power (idle detection) |
| `max_power_kw` | FLOAT | Maximum power (peak detection) |

### `energy_hour` — Hourly aggregates (retention: forever)

Same fields as `energy_minute` plus:

| Column | Type | Description |
|---|---|---|
| `sample_count` | INTEGER | Number of minute samples (data quality) |

---

## Aggregation Logic

The Python aggregator uses **Redis checkpoints** to ensure correctness:

```
Job starts
  ├─ Read last_ts from Redis  (default: now - 2min on first run)
  ├─ Compute window: [last_ts, now - offset]
  ├─ Query InfluxDB with DATE_BIN SQL
  ├─ Write results as Points
  └─ Update Redis checkpoint  ← only on successful write
```

If the service crashes mid-job, the checkpoint is NOT updated, so the next run will **re-process the same window** — safe because InfluxDB v3 deduplicates writes to the same timestamp.

---

## Project Structure

```
energy-monitoring/
├── docker-compose.yaml         # All services
├── .env                        # Secrets & config (don't commit!)
├── README.md                   # This file
│
├── aggregator/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                 # Entry point + scheduler setup
│   ├── config.py               # Centralized env config
│   ├── influx_client.py        # InfluxDB v3 wrapper
│   ├── redis_client.py         # Redis checkpoint helper
│   └── jobs/
│       ├── minute_agg.py       # Raw → Minute job
│       ├── hour_agg.py         # Minute → Hour job
│       └── retention.py        # Data cleanup job
│
├── nodered/
│   └── flows.json              # Sample publisher flow
│
├── emqx/
│   └── rule_engine.conf        # Rule Engine setup guide
│
└── influxdb/
    └── views.sql               # Ready-to-use SQL queries
```

---

## Troubleshooting

**Aggregator can't connect to InfluxDB:**
```bash
docker logs energy_aggregator | grep "not ready"
# Wait 30–60s for InfluxDB to fully initialize on first boot
```

**No data in energy_raw:**
1. Check Node-RED flow is deployed and inject node is active
2. Verify EMQX rule is enabled (Dashboard → Rules → Status = Running)
3. Check EMQX rule metrics — should show matched/passed counts

**energy_minute is empty after 2 minutes:**
```bash
docker logs energy_aggregator | grep "minute_agg"
# Should see: "wrote N bucket(s) for window [...]"
```

**Reset aggregation checkpoints (re-process from beginning):**
```bash
docker exec redis redis-cli -a <REDIS_PASSWORD> DEL agg:last_minute_ts agg:last_hour_ts
docker restart energy_aggregator
```

---

## Production Checklist

- [ ] Change all default passwords in `.env`
- [ ] Set `EMQX_ALLOW_ANONYMOUS=false` (already default)
- [ ] Create dedicated MQTT user in EMQX dashboard
- [ ] Configure Node-RED MQTT node with credentials
- [ ] Enable Redis `appendonly yes` for persistence after restart
- [ ] Set up external backup for `influxdb_data` volume
- [ ] Monitor aggregator logs for write errors
- [ ] Replace Node-RED simulation with real Modbus/OPC-UA reads

---

## Dependencies

All packages are published on PyPI with stable release versions:

| Package | Version | Purpose |
|---|---|---|
| `influxdb3-python` | ≥0.7.0 | Official InfluxDB v3 SDK |
| `apscheduler` | ≥3.10.4 | Job scheduler |
| `redis` | ≥5.0.1 | Redis client |
| `python-dotenv` | ≥1.0.0 | Env file loader |
