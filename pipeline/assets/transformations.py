"""dbt transformation assets.

Wraps the dbt project as Dagster assets so transformations
are observable, schedulable, and dependency-tracked.
"""

from pathlib import Path

from dagster_dbt import DbtCliResource, dbt_assets

DBT_PROJECT_DIR = Path(__file__).resolve().parents[2] / "dbt"
DBT_MANIFEST = DBT_PROJECT_DIR / "target" / "manifest.json"


@dbt_assets(manifest=DBT_MANIFEST)
def scouter_dbt_assets(context, dbt: DbtCliResource):  # type: ignore[no-untyped-def]
    """Run all dbt models in the Scouter project.

    Args:
        context: Dagster asset execution context.
        dbt: Injected DbtCliResource.
    """
    yield from dbt.cli(["build"], context=context).stream()
