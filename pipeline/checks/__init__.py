from pipeline.checks.freshness import market_data_freshness_check
from pipeline.checks.kpi_health import kpi_health_check

all_checks = [market_data_freshness_check, kpi_health_check]
