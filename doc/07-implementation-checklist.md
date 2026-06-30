# 07 — Implementation Checklist

> **Scope:** Daftar langkah implementasi yang harus dilakukan secara berurutan.  
> **Status:** Menunggu konfirmasi desain dari user sebelum dimulai.

---

## Phase 1: Infrastructure Preparation

- [ ] 1.1 Verifikasi `influxdb:3.10-core` mendukung Processing Engine
  - Test: `curl http://localhost:8086/api/v3/configure/processing_engine/trigger`
  - Expected: 200 atau 401 (bukan 404)
- [ ] 1.2 Nonaktifkan container `aggregator` di `docker-compose.yaml`
- [ ] 1.3 Konfirmasi EMQX berjalan normal dan anonymous auth aktif
- [ ] 1.4 Restart stack untuk validasi state bersih

---

## Phase 2: Node-RED Tab 1 — Migration / Seeders

- [ ] 2.1 Update flow existing untuk create 3 database (RAW, MINUTES, HOURLY)
- [ ] 2.2 Tambah node untuk seed data RAW (24 jam, 5 mesin, 10s interval)
- [ ] 2.3 Tambah node seed data MINUTES (agregat dari seed RAW)
- [ ] 2.4 Tambah node seed data HOURLY (agregat dari seed MINUTES)
- [ ] 2.5 Tambah comment node di setiap step dengan format `[N] Nama — Keterangan`
- [ ] 2.6 Test: jalankan tab, verifikasi data di InfluxDB UI

---

## Phase 3: Node-RED Tab 2 — Simulator / Publisher

- [ ] 3.1 Buat tab baru "Simulator"
- [ ] 3.2 Buat inject node interval 10 detik (auto-start on deploy)
- [ ] 3.3 Buat function node generate data 5 mesin dengan variasi realistis
- [ ] 3.4 Buat split node + function node set MQTT topic
- [ ] 3.5 Buat mqtt-out node (connect ke EMQX `emqx:1883`)
- [ ] 3.6 Tambah comment node di setiap step
- [ ] 3.7 Test: verifikasi MQTT message sampai di EMQX dashboard

---

## Phase 4: Node-RED Tab 3 — Subscriber / Ingestion

- [ ] 4.1 Buat tab baru "Ingestion"
- [ ] 4.2 Buat mqtt-in node subscribe `energy/+/data`
- [ ] 4.3 Buat json node (parse payload)
- [ ] 4.4 Buat function node validate + sanitize fields
- [ ] 4.5 Buat function node convert ke InfluxDB Line Protocol
- [ ] 4.6 Buat http-request node write ke `energy_monitoring`
- [ ] 4.7 Buat switch node (204 = ok, else = error)
- [ ] 4.8 Buat catch node untuk error handling
- [ ] 4.9 Tambah comment node di setiap step
- [ ] 4.10 Test end-to-end: Simulator → EMQX → Ingestion → InfluxDB

---

## Phase 5: InfluxDB Processing Engine Plugins

- [ ] 5.1 Tulis file `downsampler_raw_to_minutes.py`
- [ ] 5.2 Tulis file `downsampler_minutes_to_hourly.py`
- [ ] 5.3 Mount file plugin ke container InfluxDB via volume
- [ ] 5.4 Install plugin via CLI atau HTTP API
- [ ] 5.5 Verifikasi trigger terdaftar: `influxdb3 list triggers`
- [ ] 5.6 Monitor log untuk pastikan plugin berjalan tanpa error
- [ ] 5.7 Test: tunggu 1 menit, query `energy_minutes` — harus ada data

---

## Phase 6: Node-RED Tab 4 — Dashboard Output

- [ ] 6.1 Buat tab baru "Dashboard Output"
- [ ] 6.2 Buat HTTP In node `GET /api/dashboard/energy`
- [ ] 6.3 Buat function node query SQL Realtime (dari RAW)
- [ ] 6.4 Buat function node query SQL Hourly Chart (dari HOURLY)
- [ ] 6.5 Buat function node query SQL Pie Chart (dari MINUTES)
- [ ] 6.6 Buat function node merge semua response ke 1 JSON
- [ ] 6.7 Buat HTTP Response node
- [ ] 6.8 (Optional) Install node-red-dashboard, buat UI tab
- [ ] 6.9 (Optional) Tambah ui_chart, ui_gauge widget
- [ ] 6.10 Test: `curl http://localhost:1880/api/dashboard/energy`

---

## Phase 7: Validation & Cleanup

- [ ] 7.1 End-to-end test: Seeder → Simulator → Ingestion → Processing → Dashboard
- [ ] 7.2 Verifikasi retensi database sudah benar (14d untuk MINUTES, permanent untuk HOURLY)
- [ ] 7.3 Verifikasi Processing Engine berjalan sesuai jadwal
- [ ] 7.4 Review semua comment node di Node-RED (format & kelengkapan)
- [ ] 7.5 Update README.md dengan arsitektur terbaru
- [ ] 7.6 Commit ke git dengan pesan yang deskriptif

---

## Risk & Mitigation

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Processing Engine tidak tersedia di versi yang dipakai | Medium | High | Fallback ke Python APScheduler (sudah ada) |
| Node-RED OOM saat generate seed 43k points | Low | Medium | Batch write per 500 points, bukan sekaligus |
| EMQX lose message (QoS 0) | Medium | Low | Acceptable untuk simulasi; upgrade QoS 1 untuk prod |
| Line Protocol format salah | Low | High | Validasi di function node sebelum write |
