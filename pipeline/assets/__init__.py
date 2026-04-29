from pipeline.assets.ingestion import raw_market_data
from pipeline.assets.transformations import _dbt_assets_list

all_assets = [raw_market_data, *_dbt_assets_list]
