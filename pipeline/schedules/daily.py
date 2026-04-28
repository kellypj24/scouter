"""Schedules for recurring pipeline runs."""

from dagster import ScheduleDefinition

from pipeline.assets.ingestion import raw_market_data

daily_refresh = ScheduleDefinition(
    name="daily_market_data_refresh",
    cron_schedule="0 6 * * *",  # 06:00 UTC daily
    target=raw_market_data,
)
