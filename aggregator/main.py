import time
import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from jobs import aggregate_minute, aggregate_hour

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("aggregator")

if __name__ == "__main__":
    logger.info("Starting Energy Monitoring Aggregator Service...")

    # Run aggregation once at startup to process any backlog
    try:
        logger.info("Running initial backlog aggregation...")
        aggregate_minute()
        aggregate_hour()
    except Exception as e:
        logger.error(f"Failed to run initial backlog processing: {e}")

    # Set up APScheduler
    scheduler = BlockingScheduler()
    
    # Run minute aggregation every 1 minute (at second 0)
    scheduler.add_job(
        aggregate_minute, 
        'cron', 
        minute='*', 
        second='5',  # Offset by 5 seconds to allow raw data to settle
        id='minutely_agg'
    )
    
    # Run hourly aggregation every 1 hour (at minute 0, second 30)
    scheduler.add_job(
        aggregate_hour, 
        'cron', 
        hour='*', 
        minute='0', 
        second='30', # Offset to allow minute aggregations to finish
        id='hourly_agg'
    )
    
    logger.info("Scheduler initialized. Starting job loop...")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down aggregator service.")
