# 04 — InfluxDB 3 Processing Engine

> **Scope:** Desain dan konfigurasi InfluxDB 3 Processing Engine sebagai pengganti Python APScheduler.  
> **Referensi:** https://docs.influxdata.com/influxdb3/core/process-data/

---

## Apa itu Processing Engine?

InfluxDB 3 Processing Engine adalah **Python Virtual Machine yang tertanam langsung di dalam InfluxDB**.  
Anda dapat menjalankan kode Python **tanpa service eksternal** dengan tiga jenis trigger:

| Trigger Type | Kapan Berjalan | Use Case |
|---|---|---|
| `scheduled` | Interval / cron schedule | Agregasi periodik (RAW→MINUTES, MINUTES→HOURLY) |
| `data_write` | Setiap ada data masuk | Real-time processing, alert |
| `http` | HTTP request ke endpoint khusus | Manual trigger, on-demand |

---

## Keputusan Desain

> **Kita menggunakan `scheduled` trigger untuk agregasi.**

**Alasan:**
- Agregasi berbasis waktu tidak perlu dijalankan setiap record masuk (terlalu mahal)
- Interval reguler lebih mudah di-debug dan diprediksi
- Selaras dengan pola checkpoint yang sudah ada

---

## Plugin 1: Raw → Minutes Aggregation

**File:** `downsampler_raw_to_minutes.py`  
**Trigger:** Setiap 60 detik (`schedule: 60s`)  
**Source DB:** `energy_monitoring` (measurement: `energy_raw`)  
**Target DB:** `energy_minutes` (measurement: `energy_minute`)

### Konfigurasi Plugin

```json
{
  "plugin_name":   "raw_to_minutes",
  "trigger_type":  "schedule",
  "trigger_arguments": {
    "schedule": "*/1 * * * *"
  },
  "plugin_arguments": {
    "source_db":          "energy_monitoring",
    "source_measurement": "energy_raw",
    "target_db":          "energy_minutes",
    "target_measurement": "energy_minute",
    "interval_minutes":   1,
    "lookback_minutes":   2
  }
}
```

### Logika Agregasi (Python)

```python
# Aggregasi yang dilakukan (per machine_id, per location, per 1-menit bucket):
# - AVG(power_kw)       → avg_power_kw
# - SUM(energy_kwh)     → sum_energy_kwh
# - AVG(voltage_v)      → avg_voltage_v
# - AVG(current_a)      → avg_current_a
# - AVG(power_factor)   → avg_power_factor
# - MIN(power_kw)       → min_power_kw
# - MAX(power_kw)       → max_power_kw

sql = """
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
        MAX(power_kw)       AS max_power_kw
    FROM energy_raw
    WHERE time >= TIMESTAMP '{from_time}'
      AND time <  TIMESTAMP '{to_time}'
    GROUP BY bucket, machine_id, location
    ORDER BY bucket ASC
"""
```

---

## Plugin 2: Minutes → Hourly Aggregation

**File:** `downsampler_minutes_to_hourly.py`  
**Trigger:** Setiap 3600 detik / 1 jam (`schedule: 0 * * * *`)  
**Source DB:** `energy_minutes` (measurement: `energy_minute`)  
**Target DB:** `energy_hour` (measurement: `energy_hour`)

### Logika Agregasi (Python)

```python
# Agregasi dari MINUTES ke HOURLY (per machine_id, per location, per 1-jam bucket):
# - AVG(avg_power_kw)    → avg_power_kw
# - SUM(sum_energy_kwh)  → sum_energy_kwh   ← PENTING: SUM dari SUM, bukan AVG
# - AVG(avg_voltage_v)   → avg_voltage_v
# - AVG(avg_current_a)   → avg_current_a
# - AVG(avg_power_factor)→ avg_power_factor
# - MIN(min_power_kw)    → min_power_kw
# - MAX(max_power_kw)    → max_power_kw

sql = """
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
        MAX(max_power_kw)     AS max_power_kw
    FROM energy_minute
    WHERE time >= TIMESTAMP '{from_time}'
      AND time <  TIMESTAMP '{to_time}'
    GROUP BY bucket, machine_id, location
    ORDER BY bucket ASC
"""
```

---

## Cara Install Plugin ke InfluxDB 3

Plugin diinstall via **InfluxDB 3 CLI** atau **HTTP API** — tidak perlu restart container.

### Via CLI (di dalam container):

```bash
# Masuk ke container
docker exec -it influxdb sh

# Install plugin RAW → MINUTES
influxdb3 install plugin \
  --plugin-file /path/to/downsampler_raw_to_minutes.py \
  --trigger-type schedule \
  --trigger-arguments "schedule=*/1 * * * *" \
  --plugin-arguments '{"source_db":"energy_monitoring",...}' \
  --name raw_to_minutes

# Install plugin MINUTES → HOURLY
influxdb3 install plugin \
  --plugin-file /path/to/downsampler_minutes_to_hourly.py \
  --trigger-type schedule \
  --trigger-arguments "schedule=0 * * * *" \
  --name minutes_to_hourly
```

### Via HTTP API:

```bash
curl -X POST http://localhost:8086/api/v3/configure/processing_engine/trigger \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "trigger_name": "raw_to_minutes",
    "trigger_type": "schedule",
    "trigger_arguments": {"schedule": "*/1 * * * *"},
    "plugin_filename": "downsampler_raw_to_minutes.py"
  }'
```

---

## Idempotency & Safety

| Skenario | Penanganan |
|---|---|
| Plugin berjalan ganda | Tidak terjadi — scheduler internal InfluxDB |
| Data sudah ada di target | Gunakan upsert/overwrite (Line Protocol selalu upsert) |
| InfluxDB restart | Plugin re-register otomatis dari konfigurasi |
| Window data kosong | Plugin return early tanpa error |

---

## Monitoring Plugin

```bash
# Lihat status semua plugin
influxdb3 list triggers

# Lihat log plugin
docker logs influxdb --tail 100 | grep "processing_engine"
```

---

## ⚠️ Catatan Penting

> **Processing Engine** tersedia di **InfluxDB 3 Core v3.10+**.  
> Pastikan image yang digunakan adalah `influxdb:3.10-core` atau lebih baru.  
> Plugin ini adalah fitur **official dari InfluxData** — bukan third-party.  
> Dokumentasi resmi: https://docs.influxdata.com/influxdb3/core/process-data/manage-plugins/
