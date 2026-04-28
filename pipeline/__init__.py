"""Scouter pipeline — Dagster Definitions entry point.

Manages data ingestion and dbt transformation assets only.
No LLM or agent logic lives here.
"""

from dagster import Definitions

from pipeline.assets import all_assets
from pipeline.checks import all_checks
from pipeline.resources import RESOURCES
from pipeline.schedules import all_schedules
from pipeline.sensors import all_sensors

defs = Definitions(
    assets=all_assets,
    asset_checks=all_checks,
    sensors=all_sensors,
    schedules=all_schedules,
    resources=RESOURCES,
)
