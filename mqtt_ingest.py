import json
import os

from aio_dashboard.db import (
    init_db,
    replace_device_config_rows,
    save_telemetry,
    upsert_device_config_snapshot,
    latest_device_config_snapshot,
    list_device_configs,
)
from aio_dashboard.parsing import (
    parse_device_config_response,
    parse_telemetry_payload,
)


def _rpc_request_topic(uid):
    template = os.environ.get("AIO_RPC_REQUEST_TOPIC", "device/{uid}/rpc/req")
    return template.format(uid=uid)


def _rpc_response_topic():
    return os.environ.get("AIO_RPC_RESPONSE_TOPIC", "device/+/rpc/res")


def _uid_from_rpc_topic(topic):
    parts = str(topic or "").split("/")
    if len(parts) >= 4 and parts[0] == "device" and parts[2] == "rpc" and parts[3] == "res":
        return parts[1].strip()
    return ""


def _jsonrpc_request(method, params, request_id):
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    return payload


def _channel_row_from_snapshot(uid, channel, index, device):
    return {
        "uid": uid,
        "channel": str(channel.get("id") or channel.get("channel") or f"AI{index + 1}"),
        "name": str(channel.get("name", "") or ""),
        "device_imei": str(device.get("device_imei") or device.get("imei") or uid or ""),
        "lat": str(device.get("lat", "") or ""),
        "long": str(device.get("long", "") or ""),
        "range_4ma": channel.get("range_4ma", ""),
        "range_20ma": channel.get("range_20ma", ""),
        "calibration_offset_ma": channel.get("calibration_offset_ma", ""),
        "high_threshold": channel.get("high_threshold", ""),
        "low_threshold": channel.get("low_threshold", ""),
        "hysteresis": channel.get("hysteresis", ""),
        "unit": channel.get("unit", ""),
        "poll_cron": channel.get("poll_cron", ""),
        "publish_as": channel.get("publish_as", "string"),
        "string_format": channel.get("string_format", "%.3f"),
        "sensor_health_threshold_ma": channel.get("sensor_health_threshold_ma", ""),
        "sensor_health_hysteresis_ma": channel.get("sensor_health_hysteresis_ma", ""),
    }


def _local_units_by_channel(db_path, uid):
    existing_rows = list_device_configs(db_path, uid=uid)
    units = {}
    for row in existing_rows:
        channel = str(row.get("channel", "") or "").strip()
        unit = str(row.get("unit", "") or "").strip()
        if channel and unit:
            units[channel] = unit
    return units


def _assign_path(root, path, value):
    current = root
    parts = path.split(".")
    for index, part in enumerate(parts):
        is_last = index == len(parts) - 1
        if part.isdigit():
            list_index = int(part)
            if not isinstance(current, list):
                raise ValueError("cannot assign list index to non-list path")
            while len(current) <= list_index:
                current.append({})
            if is_last:
                current[list_index] = value
            else:
                if not isinstance(current[list_index], (dict, list)):
                    current[list_index] = {}
                current = current[list_index]
            continue

        if is_last:
            current[part] = value
            return

        next_part = parts[index + 1]
        if next_part.isdigit():
            if part not in current or not isinstance(current.get(part), list):
                current[part] = []
            current = current[part]
        else:
            if part not in current or not isinstance(current.get(part), dict):
                current[part] = {}
            current = current[part]


def _describe_result_to_config_object(result_keys):
    config_object = {"channels": [], "placeholders": {}}
    for dotted_key, meta in (result_keys or {}).items():
        value = meta.get("value") if isinstance(meta, dict) else meta
        if "." not in dotted_key:
            config_object[dotted_key] = value
            continue
        _assign_path(config_object, dotted_key, value)
    return config_object


def check_and_trigger_config_request(db_path, client, sample):
    try:
        snapshot = latest_device_config_snapshot(db_path, sample.uid, "customer")
        if snapshot is not None:
            return

        publish_config_read_request(client, sample.uid)
    except Exception as exc:
        print("Failed to auto-request configuration: {}".format(exc))


def publish_config_read_request(client, uid):
    payload = _jsonrpc_request("read_file", {"name": "customer"}, 2)
    topic = _rpc_request_topic(uid)
    client.publish(topic, json.dumps(payload, separators=(",", ":")), qos=1)
    return topic


def process_payload(db_path, payload_text):
    payload = json.loads(payload_text)
    sample = parse_telemetry_payload(payload)
    save_telemetry(db_path, sample)
    return sample


def process_config_payload(db_path, payload_text, topic="", file_name="customer"):
    try:
        payload = json.loads(payload_text)
        if not isinstance(payload, dict):
            return None

        config_object = None
        result = payload.get("result") or {}
        if isinstance(result, dict) and "content" in result:
            snapshot = parse_device_config_response(payload, file_name=file_name, source_topic=topic)
            config_object = snapshot.get("config_object") or {}
        elif isinstance(result, dict) and "config" in result:
            snapshot = parse_device_config_response(payload, file_name=file_name, source_topic=topic)
            config_object = snapshot.get("config_object") or {}
        elif isinstance(result, dict) and "keys" in result:
            config_object = _describe_result_to_config_object(result.get("keys") or {})
            snapshot = {
                "uid": str(config_object.get("UID") or config_object.get("uid") or "").strip(),
                "file_name": file_name,
                "raw_json": json.dumps(config_object, separators=(",", ":")),
                "source_topic": topic,
                "device": config_object,
                "channels": config_object.get("channels") or [],
                "config_object": config_object,
                "payload": payload,
            }
        else:
            return None

        uid = snapshot.get("uid")
        if not uid:
            uid = str(config_object.get("UID") or config_object.get("uid") or "").strip()
            snapshot["uid"] = uid
        if not uid:
            return None

        local_units = _local_units_by_channel(db_path, uid)
        upsert_device_config_snapshot(db_path, snapshot)

        device = config_object or {}
        channels = device.get("channels") or []
        rows = []
        for index, channel in enumerate(channels):
            row = _channel_row_from_snapshot(uid, channel or {}, index, device)
            channel_id = row.get("channel", "")
            if not row.get("unit") and local_units.get(channel_id):
                row["unit"] = local_units[channel_id]
            rows.append(row)
        if rows:
            replace_device_config_rows(db_path, uid, rows)
        return snapshot
    except Exception as exc:
        print("Failed to process config payload: {}".format(exc))
        return None


def _should_refresh_config_from_patch(payload):
    result = payload.get("result") or {}
    return isinstance(result, dict) and bool(result.get("patched")) and bool(result.get("reloaded"))


def start_mqtt_ingest(db_path=None):
    if db_path is None:
        db_path = os.environ.get("AIO_DB_PATH", "aio_dashboard.sqlite3")

    init_db(db_path)

    import paho.mqtt.client as mqtt

    host = os.environ.get("AIO_MQTT_HOST", "127.0.0.1")
    port = int(os.environ.get("AIO_MQTT_PORT", "1883"))
    topic = os.environ.get("AIO_MQTT_TOPIC", "devices/+/telemetry")
    response_topic = _rpc_response_topic()
    username = os.environ.get("AIO_MQTT_USERNAME", "")
    password = os.environ.get("AIO_MQTT_PASSWORD", "")
    client_id = os.environ.get("AIO_MQTT_CLIENT_ID", "aio-dashboard-ingest")

    client = mqtt.Client(client_id=client_id)
    if username:
        client.username_pw_set(username, password)

    def on_connect(client, userdata, flags, rc):
        client.subscribe(topic, qos=1)
        client.subscribe(response_topic, qos=1)
        print("Subscribed to telemetry topic: {} and config response topic: {}".format(topic, response_topic))

    def on_message(client, userdata, msg):
        payload_text = msg.payload.decode("utf-8", errors="ignore")
        if mqtt.topic_matches_sub(response_topic, msg.topic):
            payload = None
            try:
                payload = json.loads(payload_text)
            except Exception:
                payload = None

            if payload and _should_refresh_config_from_patch(payload):
                uid = _uid_from_rpc_topic(msg.topic)
                if uid:
                    publish_config_read_request(client, uid)

            process_config_payload(db_path, payload_text, topic=msg.topic, file_name="customer")
            return
        try:
            sample = process_payload(db_path, payload_text)
            check_and_trigger_config_request(db_path, client, sample)
        except Exception as exc:
            print("Failed to process telemetry payload: {}".format(exc))

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(host, port, 60)
    client.loop_forever()


if __name__ == "__main__":
    start_mqtt_ingest()
