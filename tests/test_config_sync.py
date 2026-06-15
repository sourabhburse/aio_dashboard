import json
import tempfile
import unittest

from aio_dashboard.db import (
    init_db,
    list_device_configs,
    latest_device_config_snapshot,
    upsert_device_config,
    upsert_device_config_snapshot,
)
from aio_dashboard.mqtt_ingest import process_config_payload
from aio_dashboard.parsing import parse_device_config_response


class DeviceConfigSyncTest(unittest.TestCase):
    def test_parse_read_file_response_extracts_full_customer_config(self):
        payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "name": "customer",
                "size": 424,
                "content": json.dumps(
                    {
                        "UID": "5001491",
                        "lat": "18.520",
                        "long": "73.856",
                        "aio_data_topic": "devices/{UID}/telemetry",
                        "channels": [
                            {
                                "id": "AI1",
                                "name": "pv",
                                "publish_as": "string",
                                "string_format": "%.3f",
                                "range_4ma": 0.0,
                                "range_20ma": 10.0,
                                "calibration_offset_ma": 0.0,
                                "high_threshold": 15.0,
                                "low_threshold": 2.0,
                                "hysteresis": 0.5,
                                "sensor_health_threshold_ma": 3.8,
                                "sensor_health_hysteresis_ma": 0.2,
                                "poll_cron": "*/10 * * * * *"
                            }
                        ],
                        "placeholders": {"UID": "5001491"},
                    }
                ),
            },
        }

        snapshot = parse_device_config_response(payload, file_name="customer")

        self.assertEqual(snapshot["file_name"], "customer")
        self.assertEqual(snapshot["uid"], "5001491")
        self.assertEqual(snapshot["device"]["UID"], "5001491")
        self.assertEqual(snapshot["channels"][0]["name"], "pv")
        self.assertEqual(snapshot["channels"][0]["range_4ma"], 0.0)
        self.assertEqual(snapshot["channels"][0]["range_20ma"], 10.0)

    def test_process_config_payload_persists_latest_device_file(self):
        payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "name": "customer",
                "size": 424,
                "content": json.dumps(
                    {
                        "UID": "5001491",
                        "lat": "18.520",
                        "long": "73.856",
                        "channels": [
                            {
                                "id": "AI1",
                                "name": "pv",
                                "publish_as": "string",
                                "string_format": "%.3f",
                                "range_4ma": 0.0,
                                "range_20ma": 10.0,
                                "calibration_offset_ma": 0.0,
                                "high_threshold": 15.0,
                                "low_threshold": 2.0,
                                "hysteresis": 0.5,
                                "sensor_health_threshold_ma": 3.8,
                                "sensor_health_hysteresis_ma": 0.2,
                                "poll_cron": "*/10 * * * * *"
                            }
                        ],
                        "placeholders": {"UID": "5001491"},
                    }
                ),
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = tmpdir + "/dashboard.sqlite3"
            init_db(db_path)
            snapshot = process_config_payload(
                db_path,
                json.dumps(payload),
                topic="device/5001491/rpc/res",
                file_name="customer",
            )
            stored = latest_device_config_snapshot(db_path, "5001491", "customer")

        self.assertEqual(snapshot["file_name"], "customer")
        self.assertEqual(stored["file_name"], "customer")
        self.assertEqual(stored["uid"], "5001491")
        stored_json = json.loads(stored["raw_json"])
        self.assertEqual(stored_json["channels"][0]["name"], "pv")

    def test_snapshot_round_trip_persists_latest_device_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = tmpdir + "/dashboard.sqlite3"
            init_db(db_path)
            upsert_device_config_snapshot(
                db_path,
                {
                    "uid": "5001491",
                    "file_name": "customer",
                    "raw_json": '{"UID":"5001491","channels":[{"name":"pv"}]}',
                    "source_topic": "device/5001491/rpc/res",
                },
            )
            snapshot = latest_device_config_snapshot(db_path, "5001491", "customer")

        self.assertEqual(snapshot["file_name"], "customer")
        self.assertEqual(snapshot["uid"], "5001491")
        self.assertIn('"channels":[{"name":"pv"}]', snapshot["raw_json"])

    def test_process_config_payload_preserves_local_unit_when_device_response_omits_it(self):
        payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "name": "customer",
                "content": json.dumps(
                    {
                        "UID": "5001491",
                        "channels": [
                            {
                                "id": "AI1",
                                "name": "pv",
                                "range_4ma": 0.0,
                                "range_20ma": 10.0,
                            }
                        ],
                    }
                ),
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = tmpdir + "/dashboard.sqlite3"
            init_db(db_path)
            upsert_device_config(
                db_path,
                {
                    "uid": "5001491",
                    "channel": "AI1",
                    "name": "pv",
                    "unit": "Bar",
                    "range_4ma": "0",
                    "range_20ma": "10",
                },
            )
            process_config_payload(
                db_path,
                json.dumps(payload),
                topic="device/5001491/rpc/res",
                file_name="customer",
            )
            rows = list_device_configs(db_path, uid="5001491")

        self.assertEqual(rows[0]["unit"], "Bar")

    def test_process_config_payload_preserves_zero_values(self):
        payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "name": "customer",
                "content": json.dumps(
                    {
                        "UID": "5001491",
                        "channels": [
                            {
                                "id": "AI1",
                                "name": "pv",
                                "unit": "Bar",
                                "range_4ma": 0.0,
                                "range_20ma": 10.0,
                                "calibration_offset_ma": 0.0,
                                "high_threshold": 0.0,
                                "low_threshold": 0.0,
                                "hysteresis": 0.0,
                            }
                        ],
                    }
                ),
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = tmpdir + "/dashboard.sqlite3"
            init_db(db_path)
            process_config_payload(
                db_path,
                json.dumps(payload),
                topic="device/5001491/rpc/res",
                file_name="customer",
            )
            rows = list_device_configs(db_path, uid="5001491")

        self.assertEqual(rows[0]["range_4ma"], "0.0")
        self.assertEqual(rows[0]["calibration_offset_ma"], "0.0")
        self.assertEqual(rows[0]["high_threshold"], "0.0")
        self.assertEqual(rows[0]["low_threshold"], "0.0")
        self.assertEqual(rows[0]["hysteresis"], "0.0")


if __name__ == "__main__":
    unittest.main()
