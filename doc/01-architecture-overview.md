# 01 — Architecture Overview

> **Project:** Energy Monitoring Simulation  
> **Status:** Brainstorming / Pre-Implementation  
> **Last Updated:** 2026-06-30

---

## Tujuan Sistem

Simulasi sistem monitoring energi end-to-end berbasis MQTT sebagai backbone komunikasi.
Sistem ini dirancang sebagai proof-of-concept sebelum dihubungkan ke hardware nyata (Modbus, PLC, dll).

---

## Stack Teknologi

| Service | Image / Tool | Role | Port |
|---|---|---|---|
| **EMQX** | `emqx:5.7.0` | MQTT Broker — menerima & mendistribusikan pesan | 1883, 18083 |
| **InfluxDB v3** | `influxdb:3.10-core` | Time-Series Database — penyimpanan semua data energi | 8086 (→8181) |
| **Node-RED** | `nodered/node-red:latest` | Flow engine — simulator, subscriber, dashboard | 1880 |
| **Redis** | `redis:7-alpine` | State storage — digunakan jika diperlukan Node-RED | 6379 |
| **InfluxDB UI** | `influxdata/influxdb3-ui:1.8.0` | Query explorer & admin panel | 8888 |

> ⚠️ **Container `aggregator` (Python APScheduler) dinonaktifkan.**  
> Fungsi agregasi dipindahkan ke **InfluxDB 3 Processing Engine** (built-in Python VM).

---

## Arsitektur Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                        NODE-RED                                     │
│                                                                     │
│  [Tab 1: Migration/Seeders]                                         │
│   ├─ Buat database RAW, MINUTES, HOURLY (jika belum ada)            │
│   └─ Isi seed data historis ke ketiga database                      │
│                                                                     │
│  [Tab 2: Simulator / Publisher]                                     │
│   └─ Generate telemetry 3–5 mesin → Publish ke EMQX via MQTT        │
│                                                                     │
│  [Tab 3: Subscriber / Ingestion]                                    │
│   └─ Subscribe MQTT → Parse JSON → Write ke InfluxDB [RAW]          │
│                                                                     │
│  [Tab 4: Dashboard Output]                                          │
│   └─ Query InfluxDB → JSON endpoint + Node-RED Dashboard           │
└─────────────────────────────────────────────────────────────────────┘
          │ publish                    ▲ subscribe / query
          ▼                           │
┌─────────────────┐         ┌─────────────────────────────────────────┐
│   EMQX Broker   │         │           InfluxDB v3 Core              │
│   (MQTT)        │         │                                         │
│                 │         │  Database: energy_monitoring  [RAW]     │
│  Topic:         │         │  Database: energy_minutes     [MINUTES] │
│  energy/+/data  │         │  Database: energy_hour        [HOURLY]  │
└─────────────────┘         │                                         │
                            │  ┌──────────────────────────────────┐   │
                            │  │   Processing Engine (Python VM)  │   │
                            │  │   • RAW → MINUTES  (tiap 1 mnt)  │   │
                            │  │   • MINUTES → HOURLY (tiap 1 jam)│   │
                            │  └──────────────────────────────────┘   │
                            └─────────────────────────────────────────┘
```

---

## Database Layout

| Database (Bucket) | Measurement (Table) | Retensi | Isi |
|---|---|---|---|
| `energy_monitoring` | `energy_raw` | Permanen (dev) / 7–14 hari (prod) | Data mentah 10s interval |
| `energy_minutes` | `energy_minute` | 14 hari | Agregat per menit |
| `energy_hour` | `energy_hour` | Permanen | Agregat per jam |

---

## Non-Goals

- ❌ Tidak integrasi hardware/Modbus nyata
- ❌ Tidak deploy Grafana baru
- ❌ Tidak menggunakan plugin/node yang belum official/published
- ❌ Tidak multi-tenant / multi-site (satu simulasi saja)
