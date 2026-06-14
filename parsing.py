import json
from typing import Any, Mapping


class TelemetrySample:
    def __init__(self, uid, lat, long, rssi, pv, sh=None, ha=None, la=None, device_ts=None, raw_payload="", **kwargs):
        if ha is None and "ht" in kwargs:
            ha = kwargs.pop("ht")
        if la is None and "lt" in kwargs:
            la = kwargs.pop("lt")
        self.uid = uid
        self.lat = lat
        self.long = long
        self.rssi = rssi
        self.pv = pv
        self.sh = sh
        self.ha = ha
        self.la = la
        self.device_ts = device_ts
        self.raw_payload = raw_payload


def _as_payload_dict(payload: Any) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return payload
    raise TypeError("payload must be a mapping")


def _first_reading(data: Mapping[str, Any]) -> Mapping[str, Any]:
    readings = data.get("data") or []
    if not isinstance(readings, list) or not readings:
        return {}
    first = readings[0]
    return first if isinstance(first, Mapping) else {}


def parse_telemetry_payload(payload: Any) -> TelemetrySample:
    data = _as_payload_dict(payload)
    reading = _first_reading(data)

    root_time = str(data.get("time", "")).strip()
    reading_time = str(reading.get("time", "")).strip()
    time_value = root_time or reading_time

    pv_value = reading.get("pv", "")
    if pv_value is None:
        pv_value = ""

    return TelemetrySample(
        uid=str(data.get("UID", "")).strip(),
        lat=str(data.get("lat", "")).strip(),
        long=str(data.get("long", "")).strip(),
        rssi=int(str(data.get("rssi", "0")).strip() or 0),
        pv=str(pv_value).strip(),
        sh=str(data.get("sh", "")).strip() or None,
        ha=str(reading.get("ha", "")).strip() or None,
        la=str(reading.get("la", "")).strip() or None,
        device_ts=int(time_value) if time_value else None,
        raw_payload=json.dumps(data, separators=(",", ":")),
    )


def _extract_raw_config_json(response_payload: Any) -> str:
    if isinstance(response_payload, list):
        if not response_payload:
            raise ValueError("response payload is empty")
        raw_value = response_payload[0]
    else:
        raw_value = response_payload

    if isinstance(raw_value, bytes):
        raw_value = raw_value.decode("utf-8", "ignore")

    if isinstance(raw_value, (dict, list)):
        return json.dumps(raw_value, separators=(",", ":"))

    raw_text = str(raw_value).strip()
    if not raw_text:
        raise ValueError("response payload is empty")
    return raw_text


def _content_from_jsonrpc(payload: Mapping[str, Any]) -> str:
    result = payload.get("result") or {}
    if "content" in result:
        return _extract_raw_config_json(result.get("content"))
    if "config" in result:
        return _extract_raw_config_json(result.get("config"))
    raise ValueError("response does not contain config content")


def _assign_path(root, path, value):
    current = root
    parts = path.split(".")
    for index, part in enumerate(parts):
        is_last = index == len(parts) - 1
        if part.isdigit():
            position = int(part)
            if not isinstance(current, list):
                raise ValueError("cannot assign list index to non-list path")
            while len(current) <= position:
                current.append({})
            if is_last:
                current[position] = value
            else:
                if not isinstance(current[position], (dict, list)):
                    current[position] = {}
                current = current[position]
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


def _config_object_from_keys(result_keys):
    config_object = {"channels": [], "placeholders": {}}
    for dotted_key, meta in (result_keys or {}).items():
        value = meta.get("value") if isinstance(meta, dict) else meta
        if "." not in dotted_key:
            config_object[dotted_key] = value
        else:
            _assign_path(config_object, dotted_key, value)
    return config_object


def parse_device_config_response(payload: Any, file_name="customer", source_topic=""):
    data = _as_payload_dict(payload)
    result = data.get("result") or {}
    if isinstance(result, Mapping) and "keys" in result:
        config_object = _config_object_from_keys(result.get("keys") or {})
        raw_json = json.dumps(config_object, separators=(",", ":"))
    else:
        raw_json = _content_from_jsonrpc(data)
        config_object = json.loads(raw_json)
    uid = str(
        config_object.get("UID")
        or config_object.get("uid")
        or (config_object.get("placeholders") or {}).get("UID")
        or ""
    ).strip()
    return {
        "uid": uid,
        "file_name": file_name,
        "raw_json": raw_json,
        "source_topic": source_topic,
        "device": config_object,
        "channels": config_object.get("channels") or [],
        "config_object": config_object,
        "payload": data,
    }
