from pipeline.assets.ingestion import raw_market_data
from pipeline.assets.observability import observability_sync
from pipeline.assets.transformations import _dbt_assets_list

all_assets = [raw_market_data, observability_sync, *_dbt_assets_list]
