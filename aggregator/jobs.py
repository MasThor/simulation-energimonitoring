import logging
from datetime import datetime, timedelta, timezone
import redis
from influxdb3 import InfluxDBClient3
import pandas as pd
from config import settings

logger = logging.getLogger("aggregator")

# Initialize Redis client
r_client = redis.Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    password=settings.redis_password,
    decode_responses=True
)

# Initialize InfluxDB v3 Client
influx_client = InfluxDBClient3(
    host=settings.influx_host,
    token=settings.influx_token,
    org=settings.influx_org,
    database=settings.influx_database
)

def get_last_checkpoint(job_name: str, fallback_delta: timedelta) -> datetime:
    key = f"checkpoint:{job_name}"
    val = r_client.get(key)
    if val:
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            pass
    # Fallback to current time minus delta rounded to minute/hour
    now = datetime.now(timezone.utc)
    return (now - fallback_delta).replace(second=0, microsecond=0)

def save_checkpoint(job_name: str, ts: datetime):
    key = f"checkpoint:{job_name}"
    r_client.set(key, ts.isoformat())

def aggregate_minute():
    logger.info("Starting minutely aggregation job...")
    
    # We aggregate up to the last complete minute
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start_time = get_last_checkpoint("minute", timedelta(minutes=15))
    end_time = now
    
    if start_time >= end_time:
        logger.info("No new minute periods to aggregate.")
        return

    logger.info(f"Aggregating minute data from {start_time.isoformat()} to {end_time.isoformat()}")

    # InfluxDB v3 SQL query to downsample raw to minute
    query = f"""
    SELECT 
        date_trunc('minute', time) as time,
        machine_id,
        location,
        avg(power_kw) as avg_power_kw,
        sum(energy_kwh) as sum_energy_kwh,
        avg(voltage_v) as avg_voltage_v,
        avg(current_a) as avg_current_a,
        avg(power_factor) as avg_power_factor,
        min(power_kw) as min_power_kw,
        max(power_kw) as max_power_kw
    FROM energy_raw
    WHERE time >= '{start_time.strftime('%Y-%m-%dT%H:%M:%SZ')}' 
      AND time < '{end_time.strftime('%Y-%m-%dT%H:%M:%SZ')}'
    GROUP BY date_trunc('minute', time), machine_id, location
    """
    
    try:
        table = influx_client.query(query=query, language="sql")
        df = table.to_pandas()
        
        if df.empty:
            logger.info("No raw data found in the time range.")
            save_checkpoint("minute", end_time)
            return

        # Prepare write payload
        # InfluxDB v3 client accepts pandas Dataframe directly for writing
        # Define tags and fields
        df = df.set_index('time')
        
        # Write back to energy_minute
        influx_client.write(
            record=df,
            data_frame_measurement_name="energy_minute",
            data_frame_tag_columns=["machine_id", "location"]
        )
        
        logger.info(f"Successfully aggregated {len(df)} rows into energy_minute.")
        save_checkpoint("minute", end_time)
        
    except Exception as e:
        logger.error(f"Error during minute aggregation: {e}", exc_info=True)

def aggregate_hour():
    logger.info("Starting hourly aggregation job...")
    
    # We aggregate up to the last complete hour
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start_time = get_last_checkpoint("hour", timedelta(hours=4))
    end_time = now
    
    if start_time >= end_time:
        logger.info("No new hour periods to aggregate.")
        return

    logger.info(f"Aggregating hourly data from {start_time.isoformat()} to {end_time.isoformat()}")

    # Downsample from energy_minute to energy_hour to save compute resource
    query = f"""
    SELECT 
        date_trunc('hour', time) as time,
        machine_id,
        location,
        avg(avg_power_kw) as avg_power_kw,
        sum(sum_energy_kwh) as sum_energy_kwh,
        avg(avg_voltage_v) as avg_voltage_v,
        avg(avg_current_a) as avg_current_a,
        avg(avg_power_factor) as avg_power_factor,
        min(min_power_kw) as min_power_kw,
        max(max_power_kw) as max_power_kw
    FROM energy_minute
    WHERE time >= '{start_time.strftime('%Y-%m-%dT%H:%M:%SZ')}' 
      AND time < '{end_time.strftime('%Y-%m-%dT%H:%M:%SZ')}'
    GROUP BY date_trunc('hour', time), machine_id, location
    """
    
    try:
        table = influx_client.query(query=query, language="sql")
        df = table.to_pandas()
        
        if df.empty:
            logger.info("No minute data found in the time range.")
            save_checkpoint("hour", end_time)
            return

        df = df.set_index('time')
        
        # Write back to energy_hour
        influx_client.write(
            record=df,
            data_frame_measurement_name="energy_hour",
            data_frame_tag_columns=["machine_id", "location"]
        )
        
        logger.info(f"Successfully aggregated {len(df)} rows into energy_hour.")
        save_checkpoint("hour", end_time)
        
    except Exception as e:
        logger.error(f"Error during hour aggregation: {e}", exc_info=True)
