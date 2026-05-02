from pipeline.sensors.data_freshness import data_freshness_sensor
from pipeline.sensors.dbt_tests import dbt_test_after_ingest
from pipeline.sensors.observability import obs_log_sensor

all_sensors = [data_freshness_sensor, obs_log_sensor, dbt_test_after_ingest]
