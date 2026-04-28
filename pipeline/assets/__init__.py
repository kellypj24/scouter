from pipeline.assets.ingestion import raw_market_data
from pipeline.assets.transformations import scouter_dbt_assets

all_assets = [raw_market_data, *scouter_dbt_assets]
