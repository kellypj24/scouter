"""Schedules for recurring pipeline runs."""

from dagster import ScheduleDefinition

from pipeline.assets.ingestion import raw_market_data
from pipeline.assets.observability import observability_sync

daily_refresh = ScheduleDefinition(
    name="daily_market_data_refresh",
    cron_schedule="0 6 * * *",  # 06:00 UTC daily
    target=raw_market_data,
)

hourly_obs_sync = ScheduleDefinition(
    name="hourly_observability_sync",
    cron_schedule="0 * * * *",  # top of every hour
    target=observability_sync,
)
