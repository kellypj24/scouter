from pipeline.assets.dbt_tests import dbt_test_runner
from pipeline.assets.ingestion import raw_market_data
from pipeline.assets.observability import observability_sync
from pipeline.assets.pattern_promotion import pattern_promotion
from pipeline.assets.schema_context import dbt_docs_generate
from pipeline.assets.transformations import _dbt_assets_list

all_assets = [
    raw_market_data,
    observability_sync,
    dbt_test_runner,
    dbt_docs_generate,
    pattern_promotion,
    *_dbt_assets_list,
]
