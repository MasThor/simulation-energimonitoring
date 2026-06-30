# 03 — Node-RED Flow Design

> **Scope:** Desain detail setiap tab Node-RED, urutan node, dan logic di setiap node.  
> **Prinsip:** Setiap node wajib memiliki comment di atasnya dengan nomor urut dan keterangan.

---

## Prinsip Desain Node-RED

1. **Satu tab = satu tanggung jawab** (Single Responsibility)
2. **Setiap node memiliki comment node** di atasnya dengan format: `[N] Nama — Keterangan singkat`
3. **Function node** hanya boleh berisi logic, bukan konfigurasi hardcode
4. **Environment variable** untuk semua konfigurasi (token, host, dsb)
5. **Error handling** di setiap flow dengan `catch` node

---

## Tab 1: Migration / Seeders

**Tujuan:** Inisialisasi database dan mengisi data historis. Dijalankan sekali saat startup atau manual.

```
[Trigger] inject (startup + manual)
    │
    ├─▶ [1] Comment: "1. Check & Create database energy_monitoring (RAW)"
    │       function → build HTTP request body
    │       http request → POST /api/v2/buckets
    │       switch → jika 201 (created) atau 422 (exist) → lanjut
    │
    ├─▶ [2] Comment: "2. Check & Create database energy_minutes (14 day retention)"
    │       function → build request body dengan retentionRules 1209600s
    │       http request → POST /api/v2/buckets
    │
    ├─▶ [3] Comment: "3. Check & Create database energy_hour (permanent retention)"
    │       function → build request body dengan retentionRules []
    │       http request → POST /api/v2/buckets
    │
    └─▶ [4] Comment: "4. Seed data historis 24 jam ke belakang"
            function → generate 24 jam × 5 mesin × 10s interval data
            http request → POST /api/v2/write?db=energy_monitoring (RAW)
            function → aggregate ke MINUTES format
            http request → POST /api/v2/write?db=energy_minutes
            function → aggregate ke HOURLY format
            http request → POST /api/v2/write?db=energy_hour
```

**Node List (dengan komentar):**
| # | Node Type | Label | Fungsi |
|---|---|---|---|
| 1 | inject | `Startup / Manual Trigger` | Jalankan seeder saat deploy atau klik manual |
| 2 | comment | `[1] Create RAW DB` | Dokumentasi inline |
| 3 | function | `Build RAW Bucket Request` | Buat body JSON untuk bucket `energy_monitoring` |
| 4 | http request | `POST Create Bucket RAW` | Kirim ke InfluxDB API |
| 5 | switch | `Check Response Code` | Skip jika 422 (already exists) |
| 6 | comment | `[2] Create MINUTES DB` | Dokumentasi inline |
| 7 | function | `Build MINUTES Bucket Request` | Bucket + retentionRules 14 hari |
| 8 | http request | `POST Create Bucket MINUTES` | Kirim ke InfluxDB API |
| 9 | comment | `[3] Create HOURLY DB` | Dokumentasi inline |
| 10 | function | `Build HOURLY Bucket Request` | Bucket + retentionRules permanent |
| 11 | http request | `POST Create Bucket HOURLY` | Kirim ke InfluxDB API |
| 12 | comment | `[4] Seed Historical Data` | Dokumentasi inline |
| 13 | function | `Generate 24h Seed Data` | Loop generate data 24 jam × 5 mesin |
| 14 | http request | `Write RAW Seed` | Batch write ke energy_monitoring |
| 15 | function | `Aggregate to MINUTES` | Hitung rata-rata per menit dari seed data |
| 16 | http request | `Write MINUTES Seed` | Batch write ke energy_minutes |
| 17 | function | `Aggregate to HOURLY` | Hitung rata-rata per jam |
| 18 | http request | `Write HOURLY Seed` | Batch write ke energy_hour |
| 19 | debug | `Seeder Status` | Tampilkan hasil di debug panel |
| 20 | catch | `Error Handler` | Tangkap error, log ke debug |

---

## Tab 2: Simulator / Publisher

**Tujuan:** Generate data simulasi secara periodik dan publish ke EMQX via MQTT.

```
[Trigger] inject (interval 10s, auto-start)
    │
    ├─▶ [1] Comment: "1. Generate telemetry data untuk semua mesin"
    │       function → loop 5 mesin, generate nilai acak realistis
    │                  setiap mesin menghasilkan 1 payload JSON
    │
    └─▶ [2] Comment: "2. Publish ke EMQX via MQTT"
            split → pisah array jadi individual message
            function → set topic ke "energy/{machine_id}/data"
            mqtt out → publish ke EMQX
```

**Logika Generate Data:**
```javascript
// Contoh logika di function node
const machines = [
  { id: "machine_01", location: "produksi_a", basePower: 12 },
  { id: "machine_02", location: "produksi_a", basePower: 10 },
  { id: "machine_03", location: "produksi_b", basePower: 22 },
  { id: "machine_04", location: "gudang",     basePower: 4  },
  { id: "machine_05", location: "office",     basePower: 3  },
];

// Setiap mesin: nilai dasar + variasi acak ±20%
const variance = (base, pct) => base * (1 + (Math.random() - 0.5) * 2 * pct);
```

**Node List:**
| # | Node Type | Label | Fungsi |
|---|---|---|---|
| 1 | inject | `Interval 10s — Auto Start` | Trigger setiap 10 detik, start saat deploy |
| 2 | comment | `[1] Generate Machine Telemetry` | Dokumentasi |
| 3 | function | `Generate 5 Machine Data` | Generate payload JSON untuk semua mesin |
| 4 | split | `Split ke Individual Message` | Pecah array jadi 5 pesan terpisah |
| 5 | comment | `[2] Publish ke MQTT` | Dokumentasi |
| 6 | function | `Set MQTT Topic` | Set `msg.topic = "energy/" + msg.payload.machine_id + "/data"` |
| 7 | mqtt out | `Publish ke EMQX` | Kirim ke broker, QoS 0 |
| 8 | debug | `[DBG] Published Data` | Optional: lihat data di debug panel |

---

## Tab 3: Subscriber / Ingestion

**Tujuan:** Subscribe dari EMQX, validasi data, dan tulis ke InfluxDB `energy_monitoring` (RAW).

```
[mqtt in] subscribe "energy/+/data"
    │
    ├─▶ [1] Comment: "1. Parse JSON payload dari MQTT"
    │       json → parse string ke object
    │
    ├─▶ [2] Comment: "2. Validate & sanitize fields"
    │       function → cek semua required fields ada dan valid
    │                  reject jika ada null/NaN
    │
    ├─▶ [3] Comment: "3. Convert ke InfluxDB Line Protocol"
    │       function → bangun string line protocol:
    │                  measurement,tags fields timestamp
    │
    └─▶ [4] Comment: "4. Write ke InfluxDB energy_monitoring (RAW)"
            http request → POST /api/v2/write?db=energy_monitoring
            switch → handle response 204 (ok) vs error
            debug → log status write
```

**Node List:**
| # | Node Type | Label | Fungsi |
|---|---|---|---|
| 1 | mqtt in | `Subscribe energy/+/data` | Terima semua data mesin |
| 2 | comment | `[1] Parse JSON` | Dokumentasi |
| 3 | json | `Parse JSON Payload` | Convert string MQTT ke object |
| 4 | comment | `[2] Validate Fields` | Dokumentasi |
| 5 | function | `Validate & Sanitize` | Cek field wajib, buang data korup |
| 6 | comment | `[3] Build Line Protocol` | Dokumentasi |
| 7 | function | `Convert to Line Protocol` | Format data untuk InfluxDB write |
| 8 | comment | `[4] Write to InfluxDB RAW` | Dokumentasi |
| 9 | http request | `POST Write RAW` | Kirim ke InfluxDB API |
| 10 | switch | `Check Write Status` | 204 = sukses, lainnya = error |
| 11 | debug | `[DBG] Write Status` | Log hasil write |
| 12 | catch | `Error Handler` | Tangkap dan log error |

---

## Tab 4: Dashboard Output

**Tujuan:** Query data dari InfluxDB dan sajikan sebagai JSON endpoint + visual dashboard.

### Sub-flow A: JSON API Output (untuk frontend eksternal)

```
[inject] trigger per 30s (atau HTTP in node untuk on-demand)
    │
    ├─▶ [1] Query power konsumsi saat ini (REALTIME dari RAW)
    │       function → build SQL query
    │       http request → POST /api/v3/query?db=energy_monitoring
    │       function → format ke JSON response
    │
    ├─▶ [2] Query perbandingan konsumsi per jam hari ini (dari HOURLY)
    │       function → build SQL query (24 jam terakhir)
    │       http request → POST /api/v3/query?db=energy_hour
    │       function → format ke struktur line chart
    │
    ├─▶ [3] Query distribusi per mesin (untuk Pie Chart, dari MINUTES)
    │       function → build SQL query (SUM per machine_id)
    │       http request → POST /api/v3/query?db=energy_minutes
    │       function → format ke struktur pie chart
    │
    └─▶ [4] Merge semua hasil → output ke HTTP response / debug
```

### Sub-flow B: Node-RED Dashboard (optional visual)

```
[Hasil query dari sub-flow A]
    │
    ├─▶ ui_chart (line chart) → konsumsi per jam
    ├─▶ ui_chart (pie/doughnut) → distribusi per mesin
    └─▶ ui_gauge → daya total saat ini (kW)
```

**Node List:**
| # | Node Type | Label | Fungsi |
|---|---|---|---|
| 1 | inject | `Refresh Interval 30s` | Trigger query secara berkala |
| 2 | comment | `[1] Query Realtime Power` | Dokumentasi |
| 3 | function | `Build Realtime SQL` | SQL: SELECT last power per machine |
| 4 | http request | `Query RAW DB` | POST ke InfluxDB query API |
| 5 | function | `Format Realtime Response` | Ubah ke JSON yang bersih |
| 6 | comment | `[2] Query Hourly Comparison` | Dokumentasi |
| 7 | function | `Build Hourly SQL` | SQL: SELECT per jam 24 jam terakhir |
| 8 | http request | `Query HOURLY DB` | POST ke energy_hour |
| 9 | function | `Format Line Chart Data` | Ubah ke format `{labels, datasets}` |
| 10 | comment | `[3] Query Pie Chart Data` | Dokumentasi |
| 11 | function | `Build Pie Chart SQL` | SQL: SUM energy per machine_id |
| 12 | http request | `Query MINUTES DB` | POST ke energy_minutes |
| 13 | function | `Format Pie Chart Data` | Ubah ke format `{labels, values}` |
| 14 | comment | `[4] Output` | Dokumentasi |
| 15 | function | `Merge All Results` | Gabung semua response ke 1 JSON |
| 16 | http response | `JSON API Endpoint` | Response ke HTTP client |
| 17 | ui_chart | `Line Chart — Hourly` | Dashboard visual (optional) |
| 18 | ui_chart | `Pie Chart — Per Machine` | Dashboard visual (optional) |
| 19 | ui_gauge | `Total Power kW` | Dashboard visual (optional) |
