"""
influx_client.py — InfluxDB v3 client wrapper.

Uses the official `influxdb3-python` SDK.
Provides:
  - write_points()  : write line-protocol records
  - query_sql()     : run a SQL query, returns list of dicts
  - delete_old_data(): cleanup data beyond retention window
"""

import logging
from datetime import datetime, timezone
from typing import Any

import influxdb_client_3 as InfluxDBClient3
from influxdb_client_3 import InfluxDBClient3 as Client, Point

from config import cfg

logger = logging.getLogger(__name__)


def _get_client() -> Client:
    """Create a new InfluxDB v3 client (lightweight, reuse per call)."""
    return Client(
        host=cfg.INFLUX_HOST,
        token=cfg.INFLUX_TOKEN,
        database=cfg.INFLUX_DATABASE,
    )


def write_points(points: list[Point]) -> None:
    """Write a batch of Point objects to InfluxDB v3."""
    if not points:
        return
    with _get_client() as client:
        client.write(record=points)
    logger.debug("Wrote %d point(s) to InfluxDB", len(points))


def query_sql(sql: str, params: dict | None = None) -> list[dict[str, Any]]:
    """
    Execute a SQL query against InfluxDB v3.
    Returns a list of row dicts (column → value).
    """
    with _get_client() as client:
        table = client.query(sql, mode="pandas")
    if table is None or table.empty:
        return []
    return table.to_dict(orient="records")


def delete_old_raw(retention_days: int) -> None:
    """
    Delete raw measurements older than `retention_days`.
    InfluxDB v3 doesn't have native retention policies in Core edition,
    so we run a DELETE SQL periodically.
    """
    cutoff = datetime.now(timezone.utc).replace(
        microsecond=0
    ) - __import__("datetime").timedelta(days=retention_days)

    sql = f"""
        DELETE FROM {cfg.MEASUREMENT_RAW}
        WHERE time < TIMESTAMP '{cutoff.isoformat()}'
    """
    try:
        with _get_client() as client:
            client.query(sql)
        logger.info("Deleted raw data older than %d days (cutoff: %s)", retention_days, cutoff)
    except Exception as exc:
        logger.warning("delete_old_raw failed: %s", exc)


def delete_old_minute(retention_days: int) -> None:
    """Delete minute-level data beyond retention window."""
    cutoff = datetime.now(timezone.utc).replace(
        microsecond=0
    ) - __import__("datetime").timedelta(days=retention_days)

    sql = f"""
        DELETE FROM {cfg.MEASUREMENT_MINUTE}
        WHERE time < TIMESTAMP '{cutoff.isoformat()}'
    """
    try:
        with _get_client() as client:
            client.query(sql)
        logger.info("Deleted minute data older than %d days (cutoff: %s)", retention_days, cutoff)
    except Exception as exc:
        logger.warning("delete_old_minute failed: %s", exc)
