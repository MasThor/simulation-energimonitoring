# 06 — Decision Log

> **Scope:** Semua keputusan desain yang diambil selama sesi brainstorming, beserta alternatif yang dipertimbangkan.

---

## DL-001: MQTT sebagai backbone komunikasi

| | |
|---|---|
| **Keputusan** | Semua data simulasi mengalir melalui EMQX MQTT broker |
| **Alternatif** | Direct HTTP POST ke InfluxDB dari Node-RED |
| **Alasan** | MQTT lebih scalable, decoupled, dan realistis untuk IoT production. Subscriber bisa bertambah tanpa mengubah publisher |
| **Trade-off** | Menambah satu hop (latency) — acceptable untuk simulasi 10s interval |

---

## DL-002: Node-RED sebagai publisher DAN subscriber MQTT

| | |
|---|---|
| **Keputusan** | Node-RED generate data simulasi (publisher) sekaligus subscribe dan write ke InfluxDB (subscriber) |
| **Alternatif** | Python script sebagai publisher, Node-RED hanya subscriber |
| **Alasan** | Satu tool = lebih sedikit komponen, lebih mudah di-maintain untuk simulasi |
| **Trade-off** | Node-RED bukan tool yang paling efisien untuk high-throughput publishing — cukup untuk 5 mesin × 10s |

---

## DL-003: Node-RED subscribe → langsung write ke InfluxDB RAW

| | |
|---|---|
| **Keputusan** | Node-RED yang menerima MQTT langsung menulis ke `energy_monitoring` (RAW) |
| **Alternatif** | Python Aggregator yang subscribe dan write, EMQX Rule Engine forward ke InfluxDB |
| **Alasan** | Menggunakan EMQX Rule Engine butuh konfigurasi terpisah yang sulit di-maintain via code. Node-RED lebih visual dan mudah di-debug |
| **Trade-off** | Jika Node-RED down, tidak ada data masuk ke InfluxDB — acceptable karena ini simulasi |

---

## DL-004: InfluxDB 3 Processing Engine menggantikan Python APScheduler

| | |
|---|---|
| **Keputusan** | Container `aggregator` Python (APScheduler + Redis checkpoint) dinonaktifkan, diganti dengan Processing Engine built-in InfluxDB 3 |
| **Alternatif** | A: Tetap gunakan Python APScheduler (sudah ada), B: Gunakan Node-RED sebagai aggregator |
| **Alasan** | Processing Engine: lebih sedikit service = lebih mudah maintenance. Tidak perlu Dockerfile, requirements.txt, Redis untuk checkpoint |
| **Trade-off** | Fitur relatif baru (InfluxDB 3.10+), dokumentasi masih berkembang. Jika ada bug di Processing Engine, sulit di-patch tanpa upgrade InfluxDB |
| **Risk mitigation** | Verifikasi ketersediaan Processing Engine saat startup. Jika tidak ada, fallback ke Python APScheduler |

---

## DL-005: Redis tetap di stack tapi tidak digunakan oleh aggregator

| | |
|---|---|
| **Keputusan** | Redis dipertahankan di docker-compose, namun tidak lagi digunakan sebagai checkpoint store agregasi |
| **Alternatif** | Hapus Redis dari stack |
| **Alasan** | Redis masih bisa berguna: session cache untuk dashboard, rate limiting, atau fitur masa depan. Cost-nya kecil (256MB) |
| **Trade-off** | Sedikit resource terbuang jika memang tidak digunakan |

---

## DL-006: Seeder di Tab Migration/Seeders Node-RED

| | |
|---|---|
| **Keputusan** | Data historis (seed) di-generate dan di-write dari Node-RED tab Migration/Seeders untuk ketiga database (RAW, MINUTES, HOURLY) |
| **Alternatif** | A: Python one-shot seeder script, B: Processing Engine plugin |
| **Alasan** | Tab Migration/Seeders sudah ada dan familiar. Node-RED memberikan kontrol visual (inject manual, debug node) tanpa tool tambahan |
| **Trade-off** | Seed data volume besar (24 jam × 5 mesin × 10s = ~43.200 points untuk RAW) bisa lambat via Node-RED loop. Akan dibatching |

---

## DL-007: Output dashboard — JSON API + Optional Node-RED Dashboard

| | |
|---|---|
| **Keputusan** | Node-RED menyediakan JSON endpoint (via HTTP In/Response) sebagai output utama, dengan optional Node-RED Dashboard sebagai visual |
| **Alternatif** | Grafana (service baru), custom React app |
| **Alasan** | JSON endpoint lebih fleksibel — bisa dikonsumsi frontend manapun. Node-RED Dashboard zero-setup karena sudah satu paket |
| **Trade-off** | Node-RED Dashboard kurang powerful dibanding Grafana untuk production analytics |

---

## DL-008: 5 device simulasi, interval 10 detik

| | |
|---|---|
| **Keputusan** | Simulasi 5 mesin dengan baseline power realistis, publish setiap 10 detik |
| **Alternatif** | 1 device (terlalu simpel), 10+ device (overkill untuk simulasi) |
| **Alasan** | 5 device cukup untuk validasi pipeline, cukup untuk melihat perbandingan antar zona di dashboard |
| **Trade-off** | Volume data: 5 × 6 × 60 × 24 = 43.200 points/hari — sangat ringan untuk InfluxDB |
