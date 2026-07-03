"""
jobs/retention.py — Data retention cleanup job.

Runs once per day (via APScheduler).
Deletes data beyond configured retention windows:
  - energy_raw    → 14 days (configurable via RETENTION_RAW_DAYS)
  - energy_minute → 30 days (configurable via RETENTION_MINUTE_DAYS)
  - energy_hour   → kept forever (no deletion)
"""

import logging

import influx_client as influx
from config import cfg

logger = logging.getLogger(__name__)


def run_retention_cleanup() -> None:
    """Delete old raw and minute data beyond retention windows."""
    logger.info("retention: starting cleanup (raw=%dd, minute=%dd)",
                cfg.RETENTION_RAW_DAYS, cfg.RETENTION_MINUTE_DAYS)

    influx.delete_old_raw(cfg.RETENTION_RAW_DAYS)
    influx.delete_old_minute(cfg.RETENTION_MINUTE_DAYS)

    logger.info("retention: cleanup complete")
