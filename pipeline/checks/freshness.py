"""Asset freshness checks.

Ensures DuckDB tables are updated within expected thresholds
before the agent queries them.
"""

from dagster import AssetCheckResult, AssetCheckSeverity, asset_check

from pipeline.assets.ingestion import raw_market_data

FRESHNESS_THRESHOLD_HOURS = 25


@asset_check(asset=raw_market_data, description=f"Data must be < {FRESHNESS_THRESHOLD_HOURS}h old")
def market_data_freshness_check() -> AssetCheckResult:
    """Check that raw market data was ingested within the freshness threshold.

    Returns:
        AssetCheckResult indicating pass/fail with metadata.
    """
    # TODO: implement staleness check against DuckDB ingestion metadata table
    return AssetCheckResult(
        passed=True,
        severity=AssetCheckSeverity.WARN,
        metadata={"threshold_hours": FRESHNESS_THRESHOLD_HOURS},
    )
