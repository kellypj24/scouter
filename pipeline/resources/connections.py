"""Dagster resource definitions.

All secrets read from environment variables via EnvVar().
Nothing sensitive is stored in code.
"""

from pathlib import Path

from dagster import EnvVar
from dagster_dbt import DbtCliResource

DBT_PROJECT_DIR = str(Path(__file__).resolve().parents[2] / "dbt")

RESOURCES: dict = {
    "dbt": DbtCliResource(project_dir=DBT_PROJECT_DIR),
    "duckdb_path": EnvVar("DUCKDB_PATH"),
}
