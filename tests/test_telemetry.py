import os
import tempfile
import unittest

from aio_dashboard.db import init_db, save_telemetry, latest_telemetry_for_uid
from aio_dashboard.parsing import parse_telemetry_payload
from aio_dashboard.web import render_dashboard_html


class TelemetryFlowTest(unittest.TestCase):
    def test_parse_store_and_fetch_latest_telemetry_by_uid(self):
        payload = {
            "UID": "5001491",
            "lat": "18.517368",
            "long": "073.774308",
            "rssi": "16",
            "time": "1718000000",
            "sh": "1",
            "data": [
                {
                    "time": "1771353000",
                    "pv": "16.000",
                    "ha": "1"
                }
            ]
        }

        sample = parse_telemetry_payload(payload)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "aio_dashboard.sqlite3")
            init_db(db_path)
            save_telemetry(db_path, sample)
            stored = latest_telemetry_for_uid(db_path, "5001491")

        self.assertEqual(stored["uid"], "5001491")
        self.assertEqual(stored["pv"], "16.000")
        self.assertEqual(stored["sh"], "1")
        self.assertEqual(stored["ha"], "1")
        self.assertIsNone(stored["la"])
        self.assertEqual(stored["rssi"], 16)
        self.assertEqual(stored["lat"], "18.517368")
        self.assertEqual(stored["long"], "073.774308")

    def test_render_dashboard_includes_uid_and_latest_value(self):
        payload = {
            "UID": "5001491",
            "lat": "18.517368",
            "long": "073.774308",
            "rssi": "16",
            "time": "1718000000",
            "sh": "0",
            "data": [
                {
                    "time": "1771353000",
                    "pv": "16.000",
                    "ha": "1"
                }
            ]
        }

        sample = parse_telemetry_payload(payload)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "aio_dashboard.sqlite3")
            init_db(db_path)
            save_telemetry(db_path, sample)
            html = render_dashboard_html(db_path)

        self.assertIn("5001491", html)
        self.assertIn("16.000", html)
        self.assertIn("18.517368", html)
        self.assertIn("IST", html)
        self.assertIn("alarm", html.lower())

    def test_telemetry_triggers_config_request_for_new_device(self):
        import json
        from unittest.mock import MagicMock
        from aio_dashboard.mqtt_ingest import check_and_trigger_config_request
        from aio_dashboard.parsing import TelemetrySample

        client = MagicMock()
        sample = TelemetrySample(
            uid="999999",
            lat="12.345",
            long="67.890",
            rssi=12,
            pv="10.0",
            ht=None,
            lt=None,
            device_ts=123456,
            raw_payload="{}"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "aio_dashboard_test.sqlite3")
            init_db(db_path)
            
            # Since no snapshot exists, this should trigger the request
            check_and_trigger_config_request(db_path, client, sample)
            
            # Verify client.publish was called
            client.publish.assert_called_once()
            args, kwargs = client.publish.call_args
            topic = args[0]
            payload = json.loads(args[1])
            self.assertIn("device/999999/rpc/req", topic)
            self.assertEqual(payload["jsonrpc"], "2.0")
            self.assertEqual(payload["method"], "read_file")
            self.assertEqual(payload["params"]["name"], "customer")


if __name__ == "__main__":
    unittest.main()
