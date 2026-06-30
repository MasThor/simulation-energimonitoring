"""
main.py — Aggregator service entry point.

Startup sequence:
  1. Wait for Redis and InfluxDB to be ready (with retry)
  2. Register APScheduler jobs:
     - minute_agg : every 60 seconds
     - hour_agg   : every 3600 seconds
     - retention  : every 24 hours
  3. Start scheduler and block forever

Logging:
  - All logs go to stdout (Docker picks up via json-file driver)
  - Format includes timestamp, level, and module name
"""

import logging
import sys
import time

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

import redis_client as rcache
from jobs.minute_agg import run_minute_aggregation
from jobs.hour_agg import run_hour_aggregation
from jobs.retention import run_retention_cleanup

# ── Logging setup ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("aggregator")


def wait_for_redis(retries: int = 30, delay: int = 5) -> None:
    """Block until Redis responds to ping (with timeout)."""
    for attempt in range(1, retries + 1):
        if rcache.ping():
            logger.info("Redis is ready ✓")
            return
        logger.warning("Redis not ready (attempt %d/%d) — retrying in %ds", attempt, retries, delay)
        time.sleep(delay)
    logger.critical("Redis did not become available. Exiting.")
    sys.exit(1)


def wait_for_influxdb(retries: int = 30, delay: int = 5) -> None:
    """Block until InfluxDB responds to a simple query."""
    import influx_client as influx
    for attempt in range(1, retries + 1):
        try:
            influx.query_sql("SELECT 1")
            logger.info("InfluxDB is ready ✓")
            return
        except Exception as exc:
            logger.warning("InfluxDB not ready (attempt %d/%d): %s", attempt, retries, exc)
            time.sleep(delay)
    logger.critical("InfluxDB did not become available. Exiting.")
    sys.exit(1)


def main() -> None:
    logger.info("=" * 60)
    logger.info("  Energy Monitoring Aggregator  starting up")
    logger.info("=" * 60)

    # ── 1. Health checks ──────────────────────────────────────
    wait_for_redis()
    wait_for_influxdb()

    # ── 2. Scheduler setup ────────────────────────────────────
    scheduler = BlockingScheduler(timezone="UTC")

    # Minute aggregation — runs every 60 seconds
    scheduler.add_job(
        func=run_minute_aggregation,
        trigger=IntervalTrigger(seconds=60),
        id="minute_agg",
        name="Raw → Minute aggregation",
        replace_existing=True,
        max_instances=1,          # prevent overlap if job runs slow
        misfire_grace_time=30,    # allow 30s late start before skipping
    )

    # Hour aggregation — runs every 3600 seconds
    scheduler.add_job(
        func=run_hour_aggregation,
        trigger=IntervalTrigger(seconds=3600),
        id="hour_agg",
        name="Minute → Hour aggregation",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # Retention cleanup — runs every 24 hours
    scheduler.add_job(
        func=run_retention_cleanup,
        trigger=IntervalTrigger(hours=24),
        id="retention",
        name="Data retention cleanup",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )

    logger.info("Scheduler configured with 3 jobs:")
    logger.info("  • minute_agg  — every 60s")
    logger.info("  • hour_agg    — every 3600s")
    logger.info("  • retention   — every 24h")

    # ── 3. Run first aggregation immediately on startup ───────
    # Catches up any gap from the last shutdown
    logger.info("Running initial aggregation pass...")
    run_minute_aggregation()
    run_hour_aggregation()

    # ── 4. Start blocking scheduler ───────────────────────────
    logger.info("Scheduler started. Running...")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Aggregator shut down gracefully.")


if __name__ == "__main__":
    main()
