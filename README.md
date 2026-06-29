# Real-Time Manufacturing Energy Monitoring Architecture

Arsitektur monitoring energi real-time skala industri untuk manufaktur menggunakan **Node-RED** (Simulator/Collector), **EMQX MQTT Broker 5.x**, **Redis** (Persistent State Store), dan **InfluxDB v3 OSS** (Time-Series Database dengan SQL query support).

---

## 🏗️ Desain Arsitektur

```
[Node-RED Simulator] 
       │ (Publish MQTT JSON to factory/line_a/machine_001/energy)
       ▼
  [EMQX Broker] ──(Rule Engine / HTTP Action)──► [InfluxDB v3 (raw table)]
                                                        ▲
                                             (SQL aggregation query)
                                                        │
                                            [Python Aggregator Service]
                                                        │ (Write back min/hour)
                                                        ▼
                                            [InfluxDB v3 (minute & hour)]
                                                        │
                                            [Redis Checkpoint Cache]
```

## ⚙️ Komponen Utama & Teknologi

1. **EMQX 5.7.0 (MQTT Broker)**: Handler message MQTT berkinerja tinggi. Dilengkapi Rule Engine untuk meneruskan JSON raw payload langsung ke HTTP Endpoint InfluxDB v3.
2. **InfluxDB v3 (3.0.2 OSS)**: Penyimpanan data time-series berbasis Apache Arrow/DataFusion. Mendukung full SQL standard.
3. **Redis 7**: Digunakan oleh Python service untuk menyimpan checkpoint timestamp terakhir (`last_processed_timestamp`) agar agregasi bersifat idempotent dan tahan jika restart terjadi.
4. **Python Aggregator Service**: Service mandiri berbasis Python 3.12, APScheduler, dan Pandas untuk memproses agregasi secara efisien tanpa membebani database (raw -> menit -> jam).
5. **Node-RED**: Collector/Simulator data energi.

---

## ⚡ Langkah-Langkah Menjalankan

### 1. Inisiasi Kontainer Docker
Jalankan perintah berikut pada direktori utama:
```bash
docker compose up -d
```
Pastikan seluruh service (`emqx`, `influxdb`, `redis`, `nodered`, `energy_aggregator`) berjalan dengan lancar.

### 2. Setup EMQX Rule Engine (MQTT to InfluxDB HTTP)
Untuk mengalirkan data otomatis dari MQTT ke tabel `energy_raw` di InfluxDB v3:
1. Buka dashboard EMQX di [http://localhost:18083](http://localhost:18083) (Username: `admin`, Password: `public`).
2. Masuk ke menu **Integration -> Rules** dan klik **Create**.
3. Gunakan SQL berikut untuk parsing JSON payload:
   ```sql
   SELECT
     payload.machine_id as machine_id,
     payload.location as location,
     payload.timestamp as timestamp,
     payload.power_kw as power_kw,
     payload.energy_kwh as energy_kwh,
     payload.voltage_v as voltage_v,
     payload.current_a as current_a,
     payload.power_factor as power_factor
   FROM
     "factory/+/+/energy"
   ```
4. Tambahkan **Action (Data Bridge)**:
   - **Type**: HTTP Server / Webhook
   - **Method**: `POST`
   - **URL**: `http://influxdb:8086/api/v2/write?org=manufacturing&bucket=energy_monitoring&precision=ms`
   - **Headers**:
     - `Authorization`: `Token my-super-secret-admin-token-12345`
     - `Content-Type`: `text/plain; charset=utf-8`
   - **Body Template**:
     ```text
     energy_raw,machine_id=${machine_id},location=${location} power_kw=${power_kw},energy_kwh=${energy_kwh},voltage_v=${voltage_v},current_a=${current_a},power_factor=${power_factor} ${timestamp}
     ```

### 3. Import Flow Node-RED
1. Buka Node-RED di [http://localhost:1880](http://localhost:1880).
2. Klik menu di pojok kanan atas, pilih **Import**.
3. Salin isi file `nodered/flows.json` dan klik **Import**.
4. Klik **Deploy** di Node-RED untuk mulai mensimulasikan data parameter energi setiap 10 detik.

---

## 📊 SQL View (Melihat Data di InfluxDB v3)

Gunakan dashboard/SQL query editor bawaan InfluxDB v3 di [http://localhost:8086](http://localhost:8086) dengan token admin `my-super-secret-admin-token-12345` untuk menjalankan query-query berikut:

### 1. View Data Raw (Maksimum Retensi: 2 Minggu)
```sql
SELECT time, machine_id, power_kw, energy_kwh, voltage_v, current_a 
FROM energy_raw 
ORDER BY time DESC 
LIMIT 10;
```

### 2. View Data Per Menit (Maksimum Retensi: 1 Bulan)
```sql
SELECT time, machine_id, avg_power_kw, sum_energy_kwh, min_power_kw, max_power_kw
FROM energy_minute 
ORDER BY time DESC 
LIMIT 10;
```

### 3. View Data Per Jam (Retensi: Selamanya)
```sql
SELECT time, machine_id, avg_power_kw, sum_energy_kwh, min_power_kw, max_power_kw
FROM energy_hour 
ORDER BY time DESC 
LIMIT 10;
```

---

## 🛡️ Kebijakan Retensi Data (Data Retention)
Konfigurasi retensi data dikelola di level InfluxDB database/bucket:
- **Tabel `energy_raw`**: 14 Hari (`2w`)
- **Tabel `energy_minute`**: 30 Hari (`30d`)
- **Tabel `energy_hour`**: Tidak terbatas (selamanya)
