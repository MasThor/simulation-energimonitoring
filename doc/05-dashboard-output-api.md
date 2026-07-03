# 05 — Dashboard Output & API Design

> **Scope:** Desain JSON output dari Node-RED untuk konsumsi frontend + optional Node-RED Dashboard.

---

## Output Strategy

Node-RED Tab 4 menghasilkan **dua jenis output** sekaligus:

```
1. JSON API  → Bisa dikonsumsi frontend manapun (React, Vue, dll)
2. Node-RED Dashboard → Visualisasi langsung di http://localhost:1880/ui
```

---

## JSON API Response Schema

### Endpoint: GET `/api/dashboard/energy`

Node-RED menyediakan endpoint ini via **HTTP In** node + **HTTP Response** node.

```json
{
  "generated_at": "2026-06-30T08:00:00Z",
  "realtime": {
    "total_power_kw": 51.3,
    "machines": [
      {
        "machine_id":   "machine_01",
        "location":     "produksi_a",
        "power_kw":     12.45,
        "voltage_v":    220.3,
        "current_a":    56.6,
        "power_factor": 0.95,
        "last_seen":    "2026-06-30T07:59:50Z"
      }
    ]
  },
  "line_chart": {
    "title":  "Konsumsi Energi Per Jam — Hari Ini",
    "labels": ["00:00", "01:00", "02:00", "..."],
    "datasets": [
      {
        "label": "machine_01",
        "data":  [10.2, 11.4, 9.8, "..."]
      },
      {
        "label": "machine_02",
        "data":  [8.5, 9.0, 8.2, "..."]
      }
    ]
  },
  "pie_chart": {
    "title":  "Distribusi Konsumsi Per Mesin — Hari Ini",
    "labels": ["machine_01", "machine_02", "machine_03", "machine_04", "machine_05"],
    "values": [245.3, 198.1, 412.7, 87.4, 63.2],
    "unit":   "kWh"
  }
}
```

---

## Query SQL per Section

### Section 1: Realtime (dari `energy_monitoring`)
```sql
-- Last known value per mesin (dalam 30 detik terakhir)
SELECT
    machine_id,
    location,
    LAST(power_kw)     AS power_kw,
    LAST(voltage_v)    AS voltage_v,
    LAST(current_a)    AS current_a,
    LAST(power_factor) AS power_factor,
    MAX(time)          AS last_seen
FROM energy_raw
WHERE time >= NOW() - INTERVAL '30 seconds'
GROUP BY machine_id, location
ORDER BY machine_id ASC
```

### Section 2: Line Chart Hourly (dari `energy_hour`)
```sql
-- Konsumsi per jam untuk hari ini, per mesin
SELECT
    DATE_BIN(INTERVAL '1 hour', time, TIMESTAMP '1970-01-01') AS hour_bucket,
    machine_id,
    SUM(sum_energy_kwh) AS energy_kwh
FROM energy_hour
WHERE time >= DATE_TRUNC('day', NOW())
  AND time <  DATE_TRUNC('day', NOW()) + INTERVAL '1 day'
GROUP BY hour_bucket, machine_id
ORDER BY hour_bucket ASC, machine_id ASC
```

### Section 3: Pie Chart Total (dari `energy_minutes`)
```sql
-- Total konsumsi per mesin hari ini
SELECT
    machine_id,
    SUM(sum_energy_kwh) AS total_kwh
FROM energy_minute
WHERE time >= DATE_TRUNC('day', NOW())
  AND time <  NOW()
GROUP BY machine_id
ORDER BY total_kwh DESC
```

---

## Node-RED Dashboard (Optional)

Gunakan **node-red-dashboard** (official, tersedia di Node-RED palette).

### Widget yang Digunakan

| Widget | Data Source | Konfigurasi |
|---|---|---|
| `ui_chart` | Line Chart — Hourly | Type: `line`, X axis: jam, Y axis: kWh |
| `ui_chart` | Pie/Doughnut Chart | Type: `pie`, data: distribusi per mesin |
| `ui_gauge` | Total Power saat ini | Min: 0, Max: 100 kW |
| `ui_text` | Last Update timestamp | Format: `{{msg.payload}}` |

### Dashboard URL
```
http://localhost:1880/ui
```

### Group Layout
```
[Tab: Energy Monitor Dashboard]
  ├── [Group: Realtime]
  │    ├── ui_gauge  : Total Power (kW)
  │    └── ui_text   : Last Update
  ├── [Group: Hourly Trend]
  │    └── ui_chart  : Line Chart — 24 jam
  └── [Group: Distribution]
       └── ui_chart  : Pie Chart — per mesin
```

---

## Refresh Interval

| Section | Refresh Rate | Alasan |
|---|---|---|
| Realtime (gauge, power) | 10 detik | Sync dengan interval simulator |
| Line Chart (hourly) | 60 detik | Data hourly tidak berubah sering |
| Pie Chart (daily total) | 60 detik | Data agregat, tidak kritis |

---

## Catatan Production

- Tambahkan **authentication** pada HTTP In node jika API diekspos ke luar
- Gunakan **`http-in` + `http-response`** (bukan link call) agar endpoint stateless
- Untuk frontend, gunakan CORS header jika dipanggil dari browser langsung
- Rate limit query ke InfluxDB: jangan query lebih dari 1x per 5 detik untuk dashboard bersama
