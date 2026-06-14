import json
import tempfile
import unittest

from aio_dashboard.db import init_db, upsert_device_config_snapshot
from aio_dashboard.dashboard import (
    build_patch_config_payload,
    build_device_config_object,
    render_config_dashboard_html,
    render_values_dashboard_html,
    render_device_html,
)


class DashboardContractTest(unittest.TestCase):
    def test_build_patch_config_payload_uses_jsonrpc_rpc_contract(self):
        payload = build_patch_config_payload(
            uid="5001491",
            values={"channels.0.range_4ma": 0.0, "channels.0.range_20ma": 25.0},
        )

        self.assertEqual(payload["jsonrpc"], "2.0")
        self.assertEqual(payload["method"], "patch_config")
        self.assertEqual(payload["params"]["name"], "customer")
        self.assertEqual(payload["params"]["values"]["channels.0.range_20ma"], 25.0)

    def test_build_device_config_object_preserves_device_snapshot_and_all_channels(self):
        snapshot_object = {
            "UID": "5001491",
            "lat": "18.517368",
            "long": "073.774308",
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
                    "sensor_health_threshold_ma": 3.6,
                    "sensor_health_hysteresis_ma": 0.25,
                },
                {
                    "id": "AI2",
                    "name": "temperature",
                    "publish_as": "number",
                    "string_format": "%.3f",
                    "range_4ma": 0.0,
                    "range_20ma": 100.0,
                    "calibration_offset_ma": 0.0,
                    "high_threshold": 80.0,
                    "low_threshold": 10.0,
                    "hysteresis": 1.0,
                    "sensor_health_threshold_ma": 3.6,
                    "sensor_health_hysteresis_ma": 0.25,
                },
            ],
        }
        rows = [
            {
                "uid": "5001491",
                "channel": "AI1",
                "lat": "18.517368",
                "long": "073.774308",
                "range_4ma": 0.0,
                "range_20ma": 10.0,
                "calibration_offset_ma": 0.0,
                "high_threshold": 15.0,
                "low_threshold": 2.0,
                "hysteresis": 0.5,
                "sensor_health_threshold_ma": 3.6,
                "sensor_health_hysteresis_ma": 0.25,
                "unit": "Bar",
            },
            {
                "uid": "5001491",
                "channel": "AI2",
                "lat": "18.517368",
                "long": "073.774308",
                "range_4ma": 0.0,
                "range_20ma": 100.0,
                "calibration_offset_ma": 0.0,
                "high_threshold": 80.0,
                "low_threshold": 10.0,
                "hysteresis": 1.0,
                "sensor_health_threshold_ma": 3.6,
                "sensor_health_hysteresis_ma": 0.25,
                "unit": "C",
            },
        ]

        config_object = build_device_config_object("5001491", rows, snapshot_object=snapshot_object)

        self.assertEqual(config_object["UID"], "5001491")
        self.assertEqual(config_object["lat"], "18.517368")
        self.assertEqual(config_object["channels"][0]["range_20ma"], 10.0)
        self.assertEqual(config_object["channels"][1]["unit"], "C")

    def test_render_config_dashboard_has_blue_layout_and_editable_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = tmpdir + "/dashboard.sqlite3"
            init_db(db_path)
            upsert_device_config_snapshot(
                db_path,
                {
                    "uid": "5001491",
                    "file_name": "customer",
                    "raw_json": json.dumps(
                        {
                            "UID": "5001491",
                            "lat": "18.517368",
                            "long": "073.774308",
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
                                    "sensor_health_threshold_ma": 3.6,
                                    "sensor_health_hysteresis_ma": 0.25,
                                    "unit": "Bar",
                                },
                                {
                                    "id": "AI2",
                                    "name": "temperature",
                                    "publish_as": "number",
                                    "string_format": "%.3f",
                                    "range_4ma": 0.0,
                                    "range_20ma": 100.0,
                                    "calibration_offset_ma": 0.0,
                                    "high_threshold": 80.0,
                                    "low_threshold": 10.0,
                                    "hysteresis": 1.0,
                                    "sensor_health_threshold_ma": 3.6,
                                    "sensor_health_hysteresis_ma": 0.25,
                                    "unit": "C",
                                },
                            ],
                        },
                        separators=(",", ":"),
                    ),
                },
            )
            html = render_config_dashboard_html(db_path)

        self.assertIn("Search UID", html)
        self.assertIn("blue", html.lower())
        self.assertIn("AI1", html)
        self.assertIn("AI2", html)
        self.assertIn("range_4ma", html)
        self.assertIn("range_20ma", html)
        self.assertIn("unit", html)
        self.assertIn("customer", html)
        self.assertIn("<strong>5001491</strong>", html)
        self.assertIn("name='range_4ma' value='0'", html)
        self.assertNotIn("UIDs", html)
        self.assertNotIn("Rows", html)
        self.assertNotIn("Config</div>", html)
        self.assertNotIn("This page edits local config plus the JSON-RPC patch payload", html)
        self.assertNotIn("Saved and published to ", html)

    def test_render_values_dashboard_uses_orange_layout_and_latest_readings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = tmpdir + "/dashboard.sqlite3"
            init_db(db_path)
            html = render_values_dashboard_html(
                db_path,
                latest_rows=[
                    {
                        "uid": "5001491",
                        "lat": "18.517368",
                        "long": "073.774308",
                        "rssi": 16,
                        "pv": "16.000",
                        "sh": "1",
                        "ha": "1",
                        "la": None,
                        "device_ts": 1771353000,
                        "observed_ts": 1771353001,
                    }
                ],
            )

        self.assertIn("orange", html.lower())
        self.assertIn("5001491", html)
        self.assertIn("16.000", html)
        self.assertIn("setInterval", html)
        self.assertIn("page=", html)
        self.assertNotIn("Live Refresh", html)
        self.assertNotIn("<div class='tile'><div class='label'>Rows</div>", html)
        self.assertTrue(html.rfind("pager") > html.rfind("</table>"))

    def test_render_device_history_uses_pagination_and_live_refresh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = tmpdir + "/dashboard.sqlite3"
            init_db(db_path)
            html = render_device_html(db_path, "5001491")

        self.assertIn("history", html.lower())
        self.assertIn("setInterval", html)
        self.assertIn("page=", html)


if __name__ == "__main__":
    unittest.main()
