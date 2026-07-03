# 02 — MQTT & Data Schema

> **Scope:** Definisi topik MQTT, format payload, dan skema data yang mengalir antar service.

---

## MQTT Broker (EMQX)

| Parameter | Value |
|---|---|
| Host (internal Docker) | `emqx` |
| Port | `1883` |
| Auth (dev) | Anonymous diizinkan (`EMQX_ALLOW_ANONYMOUS=true`) |
| Auth (prod) | Wajib pakai username/password atau mTLS |
| Dashboard | http://localhost:18083 |

---

## Topic Structure

Gunakan hierarki topik yang bermakna untuk memudahkan filtering:

```
energy/{machine_id}/data
```

**Contoh:**
```
energy/machine_01/data
energy/machine_02/data
energy/machine_03/data
```

**Aturan:**
- `{machine_id}` harus konsisten antara publisher dan subscriber
- Subscribe wildcard: `energy/+/data` (untuk terima dari semua mesin)
- Tidak menggunakan retain flag pada data streaming (data bukan konfigurasi)

---

## Payload Format (JSON)

Setiap pesan MQTT yang dipublish oleh Node-RED Simulator menggunakan format JSON berikut:

```json
{
  "machine_id": "machine_01",
  "location":   "area_produksi_a",
  "timestamp":  "2026-06-30T08:00:00.000Z",
  "power_kw":   12.45,
  "voltage_v":  220.3,
  "current_a":  56.6,
  "energy_kwh": 0.034,
  "power_factor": 0.95
}
```

### Field Description

| Field | Type | Satuan | Keterangan |
|---|---|---|---|
| `machine_id` | `string` | — | ID unik mesin, digunakan sebagai MQTT tag & InfluxDB tag |
| `location` | `string` | — | Area/zona lokasi mesin |
| `timestamp` | `string` | ISO-8601 UTC | Waktu pengukuran |
| `power_kw` | `float` | kilowatt | Daya aktif sesaat |
| `voltage_v` | `float` | volt | Tegangan rata-rata (L-N atau L-L) |
| `current_a` | `float` | ampere | Arus total |
| `energy_kwh` | `float` | kWh | Delta energi sejak pengukuran sebelumnya |
| `power_factor` | `float` | — | Power factor (0.0–1.0) |

---

## Simulated Devices

| Machine ID | Location | Baseline Power (kW) | Variasi |
|---|---|---|---|
| `machine_01` | `produksi_a` | 10–15 kW | ±20% random |
| `machine_02` | `produksi_a` | 8–12 kW | ±15% random |
| `machine_03` | `produksi_b` | 20–25 kW | ±25% random |
| `machine_04` | `gudang` | 3–6 kW | ±10% random |
| `machine_05` | `office` | 2–4 kW | ±10% random |

**Interval publish:** 10 detik per mesin  
**QoS Level:** 0 (At most once) — cukup untuk simulasi, tidak critical  
**QoS Level (prod):** 1 (At least once) — untuk data yang tidak boleh hilang

---

## Data Flow: MQTT → InfluxDB

```
MQTT Payload (JSON)
    │
    ▼
Node-RED [Subscribe]
    │
    ├─ Parse JSON (json node)
    ├─ Validate fields (function node)
    ├─ Convert ke InfluxDB Line Protocol
    │    Format: measurement,tags fields timestamp
    │    Contoh:
    │    energy_raw,machine_id=machine_01,location=produksi_a \
    │      power_kw=12.45,voltage_v=220.3,current_a=56.6, \
    │      energy_kwh=0.034,power_factor=0.95 \
    │      1719734400000000000
    │
    └─ HTTP POST → InfluxDB /api/v2/write?db=energy_monitoring
```

---

## Catatan Keamanan (Production)

- Nonaktifkan anonymous auth di EMQX
- Buat user khusus per service (publisher, subscriber) dengan ACL ketat
- Gunakan TLS port 8883 untuk MQTT over SSL
- Token InfluxDB: buat token terpisah per operasi (write-only untuk ingestion, read-only untuk dashboard)
