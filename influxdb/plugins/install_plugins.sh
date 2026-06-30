#!/bin/bash
# install_plugins.sh
# ─────────────────────────────────────────────────────────────────────────────
# Install InfluxDB 3 Processing Engine triggers (plugins).
# Correct CLI syntax: trigger name is POSITIONAL (last argument), not --trigger-name flag.
#
# Jalankan setelah stack up:
#   docker exec influxdb sh /var/lib/influxdb3/plugins/install_plugins.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

# Baca token dari environment variable jika tersedia, fallback ke hardcoded
TOKEN="${INFLUXDB3_AUTH_TOKEN:-apiv3_ds_pESsacfI0_vXWdSHp49SZaXPbODKnd8gaSQopgUOV-ijAiLEeqLy3IiyXhp0bQtGmN1pHOHS83CJfKWqP7w}"
INFLUX_HOST="http://localhost:8181"

echo "=============================================="
echo " Installing InfluxDB 3 Processing Engine Plugins"
echo "=============================================="
echo " Host : $INFLUX_HOST"
echo " Token: ${TOKEN:0:20}..."
echo "=============================================="

# ── Plugin 1: RAW → MINUTES (every 1 minute) ──────────────────────────────
echo ""
echo "[1/2] Installing trigger: raw_to_minutes ..."
echo "      Spec   : every:1m"
echo "      Plugin : downsampler_raw_to_minutes.py"
echo "      DB     : energy_monitoring"

influxdb3 create trigger \
  --host "$INFLUX_HOST" \
  --token "$TOKEN" \
  --trigger-spec "every:1m" \
  --plugin-filename "downsampler_raw_to_minutes.py" \
  --database energy_monitoring \
  raw_to_minutes \
  2>&1 && echo "    ✓ raw_to_minutes installed" || echo "    ⚠  May already exist or error above (check output)"

# ── Plugin 2: MINUTES → HOURLY (every 1 hour) ─────────────────────────────
echo ""
echo "[2/2] Installing trigger: minutes_to_hourly ..."
echo "      Spec   : every:1h"
echo "      Plugin : downsampler_minutes_to_hourly.py"
echo "      DB     : energy_minutes"

influxdb3 create trigger \
  --host "$INFLUX_HOST" \
  --token "$TOKEN" \
  --trigger-spec "every:1h" \
  --plugin-filename "downsampler_minutes_to_hourly.py" \
  --database energy_minutes \
  minutes_to_hourly \
  2>&1 && echo "    ✓ minutes_to_hourly installed" || echo "    ⚠  May already exist or error above (check output)"

# ── Verify via HTTP API ────────────────────────────────────────────────────
echo ""
echo "Verifying via HTTP API..."
curl -s -X GET "$INFLUX_HOST/api/v3/configure/trigger" \
  -H "Authorization: Bearer $TOKEN" \
  2>/dev/null | head -c 500 || echo "  (HTTP verify not available)"

echo ""
echo "=============================================="
echo " Done!"
echo "=============================================="
