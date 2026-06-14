import copy
import json
import math
import os
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs

from aio_dashboard.db import (
    count_latest_telemetry_uids,
    count_telemetry_history_rows,
    latest_device_config_snapshot,
    latest_telemetry_for_uid,
    latest_telemetry_history,
    latest_telemetry_rows,
    list_device_config_snapshots,
    list_device_configs,
    replace_device_config_rows,
    save_telemetry,
    upsert_device_config,
    upsert_device_config_snapshot,
)


AIO_CONFIG_FILE_NAME = "customer"
_IST = timezone(timedelta(hours=5, minutes=30))


VALUE_COLUMNS = [
    ("uid", "UID Number"),
    ("observed_ts", "Last received data"),
    ("pv", "Value"),
    ("sh", "Status"),
    ("rssi", "RSSI"),
    ("alarm_state", "Alarm"),
    ("high_alarm", "High Alarm"),
    ("low_alarm", "Low Alarm"),
    ("hysteresis", "Hysteresis"),
    ("history", "History"),
]


CONFIG_COLUMNS = [
    ("uid", "UID Number"),
    ("channel", "Input"),
    ("lat", "Latitude"),
    ("long", "Longitude"),
    ("range_4ma", "Value Corresponds to 4 mA"),
    ("range_20ma", "Value Corresponds to 20 mA"),
    ("unit", "Unit"),
    ("calibration_offset_ma", "Adjust value +/-"),
    ("high_threshold", "High Alarm Value"),
    ("low_threshold", "Low Alarm Value"),
    ("hysteresis", "Hysteresis"),
    ("write", "Write Logger"),
]


def _html_escape(value):
    if value is None:
        return ""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _form_value(value, fallback=""):
    if value is None:
        return fallback
    return str(value)


def _to_number(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text) if "." in text or "e" in text.lower() else int(text)
    except ValueError:
        return value


def _format_time(value):
    if value in (None, "", 0):
        return "-"
    try:
        dt = datetime.fromtimestamp(int(value), tz=_IST)
        return dt.strftime("%H:%M:%S %d-%m-%Y IST")
    except (TypeError, ValueError, OSError):
        return str(value)


def _row_id(uid, channel):
    safe_uid = str(uid or "new").replace(" ", "_")
    safe_channel = str(channel or "AI1").replace(" ", "_")
    return "cfg-{}-{}".format(safe_uid, safe_channel)


def _query_string(params):
    return "&".join("{}={}".format(key, params[key]) for key in sorted(params))


def _page_count(total_rows, per_page):
    if per_page <= 0:
        return 1
    return max(1, int(math.ceil(float(total_rows) / float(per_page))))


def _page_controls(base_path, page, per_page, total_rows, extra_params=None):
    extra_params = dict(extra_params or {})
    total_pages = _page_count(total_rows, per_page)
    prev_page = max(1, page - 1)
    next_page = min(total_pages, page + 1)
    prev_params = dict(extra_params, page=prev_page, per_page=per_page)
    next_params = dict(extra_params, page=next_page, per_page=per_page)
    return (
        "<div class='pager'>"
        "<a href='{base}?{prev}'>Prev</a>"
        "<span>Page {page} of {total}</span>"
        "<a href='{base}?{next}'>Next</a>"
        "</div>"
    ).format(
        base=base_path,
        prev=_query_string(prev_params),
        page=page,
        total=total_pages,
        next=_query_string(next_params),
    )


def _build_channel_object(row):
    return {
        "id": row.get("channel", "") or row.get("id", "") or "",
        "name": row.get("name", "") or row.get("channel", "") or "",
        "publish_as": row.get("publish_as", "string") or "string",
        "string_format": row.get("string_format", "%.3f") or "%.3f",
        "range_4ma": _to_number(row.get("range_4ma")),
        "range_20ma": _to_number(row.get("range_20ma")),
        "calibration_offset_ma": _to_number(row.get("calibration_offset_ma")),
        "high_threshold": _to_number(row.get("high_threshold")),
        "low_threshold": _to_number(row.get("low_threshold")),
        "hysteresis": _to_number(row.get("hysteresis")),
        "unit": row.get("unit", "") or "",
        "sensor_health_threshold_ma": _to_number(row.get("sensor_health_threshold_ma")),
        "sensor_health_hysteresis_ma": _to_number(row.get("sensor_health_hysteresis_ma")),
        "poll_cron": row.get("poll_cron", "") or "",
    }


def _rows_from_snapshot_object(snapshot_object, uid):
    if not snapshot_object:
        return []
    channels = snapshot_object.get("channels") or []
    root_uid = str(uid or snapshot_object.get("UID") or snapshot_object.get("uid") or "").strip()
    lat = snapshot_object.get("lat", "") or ""
    long = snapshot_object.get("long", "") or ""
    rows = []
    for index, channel in enumerate(channels):
        rows.append(
            {
                "uid": root_uid,
                "channel_index": index,
                "channel": channel.get("id") or channel.get("channel") or f"AI{index + 1}",
                "name": channel.get("name", "") or "",
                "device_imei": snapshot_object.get("device_imei", "") or "",
                "lat": lat,
                "long": long,
                "range_4ma": channel.get("range_4ma", ""),
                "range_20ma": channel.get("range_20ma", ""),
                "calibration_offset_ma": channel.get("calibration_offset_ma", ""),
                "high_threshold": channel.get("high_threshold", ""),
                "low_threshold": channel.get("low_threshold", ""),
                "hysteresis": channel.get("hysteresis", ""),
                "unit": channel.get("unit", ""),
                "publish_as": channel.get("publish_as", "string"),
                "string_format": channel.get("string_format", "%.3f"),
                "sensor_health_threshold_ma": channel.get("sensor_health_threshold_ma", ""),
                "sensor_health_hysteresis_ma": channel.get("sensor_health_hysteresis_ma", ""),
                "poll_cron": channel.get("poll_cron", ""),
            }
        )
    return rows


def build_device_config_object(uid, config_rows, snapshot_object=None):
    rows = list(config_rows or [])
    base_object = copy.deepcopy(snapshot_object or {})
    if not rows:
        rows = _rows_from_snapshot_object(base_object, uid)

    base_object["UID"] = str(uid)
    base_object["lat"] = (rows[0].get("lat") if rows else base_object.get("lat", "")) or ""
    base_object["long"] = (rows[0].get("long") if rows else base_object.get("long", "")) or ""
    base_object["aio_data_topic"] = base_object.get("aio_data_topic") or "devices/{UID}/telemetry"
    placeholders = dict(base_object.get("placeholders") or {})
    placeholders["UID"] = str(uid)
    base_object["placeholders"] = placeholders

    snapshot_channels = (snapshot_object or {}).get("channels") or []
    merged_channels = []
    for index, row in enumerate(rows):
        merged = dict(snapshot_channels[index]) if index < len(snapshot_channels) and isinstance(snapshot_channels[index], dict) else {}
        merged.update(_build_channel_object(row))
        merged["id"] = merged.get("id") or row.get("channel", f"AI{index + 1}")
        merged["name"] = merged.get("name") or row.get("name", "") or ""
        merged_channels.append(merged)
    if not merged_channels and snapshot_channels:
        merged_channels = [dict(channel) for channel in snapshot_channels]
    base_object["channels"] = merged_channels
    return base_object


def build_patch_config_payload(uid, values, request_id=4):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "patch_config",
        "params": {
            "name": AIO_CONFIG_FILE_NAME,
            "values": values,
        },
    }


def build_read_config_payload(request_id=2):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "read_file",
        "params": {"name": AIO_CONFIG_FILE_NAME},
    }


def build_apply_command_payload(uid, file_name, config_object):
    return build_patch_config_payload(uid, config_object)


def build_refresh_command_payload(file_name):
    return build_read_config_payload()


def _mqtt_settings_from_env():
    return {
        "host": os.environ.get("AIO_RPC_MQTT_HOST", os.environ.get("AIO_APPLY_MQTT_HOST", "mqtt.xnet-iot.com")),
        "port": os.environ.get("AIO_RPC_MQTT_PORT", os.environ.get("AIO_APPLY_MQTT_PORT", "1883")),
        "username": os.environ.get("AIO_RPC_MQTT_USERNAME", os.environ.get("AIO_APPLY_MQTT_USERNAME", "")),
        "password": os.environ.get("AIO_RPC_MQTT_PASSWORD", os.environ.get("AIO_APPLY_MQTT_PASSWORD", "")),
        "topic_template": os.environ.get("AIO_RPC_REQUEST_TOPIC", "device/{uid}/rpc/req"),
        "client_id": os.environ.get("AIO_RPC_MQTT_CLIENT_ID", os.environ.get("AIO_APPLY_MQTT_CLIENT_ID", "aio-dashboard-rpc")),
    }


def publish_rpc_request(payload, uid, settings):
    import paho.mqtt.client as mqtt

    host = settings.get("host", "mqtt.xnet-iot.com")
    port = int(settings.get("port", "1883"))
    username = settings.get("username", "")
    password = settings.get("password", "")
    topic_template = settings.get("topic_template", "device/{uid}/rpc/req")
    client_id = settings.get("client_id", "aio-dashboard-rpc")
    topic = topic_template.format(uid=uid)

    client = mqtt.Client(client_id=client_id)
    if username:
        client.username_pw_set(username, password)
    client.connect(host, port, 60)
    client.loop_start()
    try:
        message = json.dumps(payload, separators=(",", ":"))
        info = client.publish(topic, message, qos=1, retain=False)
        info.wait_for_publish()
    finally:
        client.disconnect()
        client.loop_stop()
    return topic


def publish_apply_command(payload, uid, imei, settings):
    return publish_rpc_request(payload, uid, settings)


def _config_cell_input(row, field_name, input_type="text", readonly=False):
    value = _html_escape(_form_value(row.get(field_name), ""))
    attrs = " type='{type}' name='{name}' value='{value}' form='{form}'".format(
        type=input_type,
        name=field_name,
        value=value,
        form=_row_id(row.get("uid"), row.get("channel")),
    )
    if input_type == "number":
        attrs += " step='any'"
    if readonly:
        attrs += " readonly"
    return "<input{}>".format(attrs)


def _render_config_row(row):
    row_id = _row_id(row.get("uid"), row.get("channel"))
    channel_index = row.get("channel_index", 0)
    parts = [
        "<form id='{0}' method='post' action='/config/apply'></form>".format(row_id),
        "<tr class='config-row' data-uid='{uid}' data-location='{location}'>".format(
            uid=_html_escape(_form_value(row.get("uid"), "")),
            location=_html_escape("{} {}".format(_form_value(row.get("lat"), ""), _form_value(row.get("long"), ""))),
        ),
        "<td><input type='hidden' name='uid' value='{uid}' form='{form}'>".format(
            uid=_html_escape(_form_value(row.get("uid"), "")),
            form=row_id,
        ),
        "<input type='hidden' name='channel_index' value='{0}' form='{1}'>".format(channel_index, row_id),
        "<input type='hidden' name='channel' value='{0}' form='{1}'>".format(_html_escape(_form_value(row.get("channel"), "")), row_id),
        "<input type='hidden' name='name' value='{0}' form='{1}'>".format(_html_escape(_form_value(row.get("name"), "")), row_id),
        "<input type='hidden' name='publish_as' value='{0}' form='{1}'>".format(_html_escape(_form_value(row.get("publish_as"), "string")), row_id),
        "<input type='hidden' name='string_format' value='{0}' form='{1}'>".format(_html_escape(_form_value(row.get("string_format"), "%.3f")), row_id),
        "<input type='hidden' name='poll_cron' value='{0}' form='{1}'>".format(_html_escape(_form_value(row.get("poll_cron"), "")), row_id),
        "<input type='hidden' name='sensor_health_threshold_ma' value='{0}' form='{1}'>".format(
            _html_escape(_form_value(row.get("sensor_health_threshold_ma"), "")),
            row_id,
        ),
        "<input type='hidden' name='sensor_health_hysteresis_ma' value='{0}' form='{1}'>".format(
            _html_escape(_form_value(row.get("sensor_health_hysteresis_ma"), "")),
            row_id,
        ),
        "</td>",
        "<td><strong>{}</strong></td>".format(_html_escape(_form_value(row.get("channel"), ""))),
        "<td>{}</td>".format(_config_cell_input(row, "lat")),
        "<td>{}</td>".format(_config_cell_input(row, "long")),
        "<td>{}</td>".format(_config_cell_input(row, "range_4ma", "number")),
        "<td>{}</td>".format(_config_cell_input(row, "range_20ma", "number")),
        "<td>{}</td>".format(_config_cell_input(row, "unit")),
        "<td>{}</td>".format(_config_cell_input(row, "calibration_offset_ma", "number")),
        "<td>{}</td>".format(_config_cell_input(row, "high_threshold", "number")),
        "<td>{}</td>".format(_config_cell_input(row, "low_threshold", "number")),
        "<td>{}</td>".format(_config_cell_input(row, "hysteresis", "number")),
        "<td><button class='apply-btn' type='submit' form='{0}'>Save</button><button class='read-btn' type='submit' form='{0}' formaction='/config/read'>Read</button></td>".format(row_id),
        "</tr>",
    ]
    return "".join(parts)


def _rows_from_config(db_path):
    rows = list_device_configs(db_path)
    if rows:
        return rows
    snapshots = list_device_config_snapshots(db_path, AIO_CONFIG_FILE_NAME)
    for snapshot_row in snapshots:
        try:
            snapshot_object = json.loads(snapshot_row.get("raw_json", "{}"))
        except (TypeError, ValueError):
            snapshot_object = {}
        rows.extend(_rows_from_snapshot_object(snapshot_object, snapshot_row.get("uid", "")))
    return rows


def render_config_dashboard_html(db_path, message=""):
    config_rows = _rows_from_config(db_path)
    grouped_uids = []
    seen = set()
    for row in config_rows:
        uid = row.get("uid", "")
        if uid not in seen:
            seen.add(uid)
            grouped_uids.append(uid)
    refresh_uid = config_rows[0].get("uid", "") if config_rows else ""
    parts = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>AIO Configuration Dashboard</title>",
        "<style>",
        "body{margin:0;font-family:Arial,sans-serif;background:linear-gradient(180deg,#eef5ff 0%,#e4efff 100%);color:#16315b;}",
        ".shell{padding:22px 24px 36px;}",
        ".hero{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;}",
        ".hero h1{margin:0;font-size:28px;color:#1f4f9b;}",
        ".toolbar{display:flex;gap:16px;flex-wrap:wrap;margin:18px 0 20px;}",
        ".search-box{background:#fff;border:2px solid #2a4b8d;padding:10px 12px;min-width:280px;}",
        ".search-box label{display:block;font-size:14px;margin-bottom:6px;}",
        ".search-box input{width:100%;box-sizing:border-box;padding:8px 10px;border:1px solid #2a4b8d;background:#1ea7f2;color:#fff;}",
        ".summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px;}",
        ".tile{background:#fff;border:1px solid #bfd0f2;padding:12px 14px;}",
        ".label{font-size:12px;color:#4f6b9a;text-transform:uppercase;}",
        ".value{font-size:20px;font-weight:bold;margin-top:6px;color:#1f4f9b;}",
        ".config-table{width:100%;border-collapse:collapse;background:#fff;}",
        ".config-table th,.config-table td{border:1px solid #c7d4eb;padding:8px;vertical-align:top;font-size:13px;}",
        ".config-table th{background:#4e79d3;color:#fff;text-align:left;}",
        ".config-table input,.config-table select{width:100%;box-sizing:border-box;padding:7px 8px;border:1px solid #8ea8d4;}",
        ".config-row:nth-child(even){background:#f7faff;}",
        ".apply-btn,.read-btn{width:100%;border:0;padding:10px 12px;color:#fff;font-weight:bold;cursor:pointer;}",
        ".apply-btn{background:#204fcb;}",
        ".read-btn{background:#5b7cbc;margin-top:4px;}",
        ".note{margin-top:12px;color:#45608d;font-size:13px;}",
        ".overlay{display:none;position:fixed;inset:0;background:rgba(22,35,59,0.6);z-index:9999;justify-content:center;align-items:center;flex-direction:column;color:#fff;}",
        ".spinner{width:48px;height:48px;border:5px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin 1s linear infinite;margin-bottom:14px;}",
        "@keyframes spin{to{transform:rotate(360deg);}}",
        "</style>",
        "<script>",
        "function filterConfigRows(){",
        "  var uidTerm=(document.getElementById('uid-filter').value||'').toLowerCase();",
        "  var locTerm=(document.getElementById('location-filter').value||'').toLowerCase();",
        "  document.querySelectorAll('.config-row').forEach(function(row){",
        "    var uid=(row.getAttribute('data-uid')||'').toLowerCase();",
        "    var loc=(row.getAttribute('data-location')||'').toLowerCase();",
        "    row.style.display=(uid.indexOf(uidTerm) !== -1 && loc.indexOf(locTerm) !== -1) ? '' : 'none';",
        "  });",
        "}",
        "document.addEventListener('submit', function(e){",
        "  var form=e.target; var action=form.getAttribute('action')||''; var submitter=e.submitter||document.activeElement;",
        "  if(action.indexOf('/config/apply') !== -1 || action.indexOf('/config/read') !== -1){",
        "    e.preventDefault(); showSpinner('Processing...');",
        "    var formData=new FormData(form);",
        "    if(submitter && submitter.name){ formData.append(submitter.name, submitter.value); }",
        "    fetch(action,{method:'POST',body:new URLSearchParams(formData)}).then(function(res){",
        "      return res.text().then(function(text){ return {ok:res.ok, text:text}; });",
        "    }).then(function(result){",
        "      hideSpinner(); document.open(); document.write(result.text); document.close();",
        "    }).catch(function(err){ hideSpinner(); alert('Action failed: ' + err.message); });",
        "  }",
        "});",
        "function showSpinner(){ var overlay=document.getElementById('loading-overlay'); if(overlay){ overlay.style.display='flex'; } }",
        "function hideSpinner(){ var overlay=document.getElementById('loading-overlay'); if(overlay){ overlay.style.display='none'; } }",
        "</script>",
        "</head><body data-theme='blue'><div class='shell'>",
        "<div class='hero'><div><h1>AIO Configuration Dashboard</h1></div><a href='/' class='action-link'>Open values dashboard</a></div>",
        "<div class='summary'>",
        "<div class='tile'><div class='label'>UIDs</div><div class='value'>{}</div></div>".format(len(grouped_uids)),
        "<div class='tile'><div class='label'>Rows</div><div class='value'>{}</div></div>".format(len(config_rows)),
        "<div class='tile'><div class='label'>Config</div><div class='value'>{}</div></div>".format(_html_escape(AIO_CONFIG_FILE_NAME)),
        "</div>",
        "<div class='toolbar'>",
        "<div class='search-box'><label for='uid-filter'>Search UID</label><input id='uid-filter' oninput='filterConfigRows()' placeholder='5001491'></div>",
        "<div class='search-box'><label for='location-filter'>Search location</label><input id='location-filter' oninput='filterConfigRows()' placeholder='18.520 / 73.856'></div>",
        "</div>",
    ]
    if message:
        parts.append("<div class='note'>{}</div>".format(_html_escape(message)))
    parts.append(
        "<div class='note'>This page edits local config plus the JSON-RPC patch payload. Unit stays local and is not sent to the device.</div>"
    )
    parts.append("<table class='config-table'><thead><tr>")
    for field_name, label in CONFIG_COLUMNS:
        parts.append("<th>{}</th>".format(_html_escape(label)))
    parts.append("</tr></thead><tbody>")
    if not config_rows:
        config_rows = [
            {
                "uid": "",
                "channel": "AI1",
                "lat": "",
                "long": "",
                "range_4ma": "",
                "range_20ma": "",
                "unit": "",
                "calibration_offset_ma": "",
                "high_threshold": "",
                "low_threshold": "",
                "hysteresis": "",
                "publish_as": "string",
                "string_format": "%.3f",
                "poll_cron": "",
                "sensor_health_threshold_ma": "",
                "sensor_health_hysteresis_ma": "",
                "channel_index": 0,
            }
        ]
    for row in config_rows:
        parts.append(_render_config_row(row))
    parts.append("</tbody></table>")
    parts.append("<div id='loading-overlay' class='overlay'><div class='spinner'></div><div>Processing...</div></div>")
    parts.append("</div></body></html>")
    return "".join(parts)


def _alarm_state(row):
    if row.get("ha") not in (None, ""):
        return "HA"
    if row.get("la") not in (None, ""):
        return "LA"
    return "normal"


def _status_state(row):
    return "alarm" if str(row.get("sh", "")).strip() == "0" else "healthy"


def _config_map(db_path):
    config_rows = list_device_configs(db_path)
    by_uid = {}
    for row in config_rows:
        by_uid.setdefault(row.get("uid", ""), []).append(row)
    return by_uid


def _telemetry_rows(db_path, page, per_page):
    total = count_latest_telemetry_uids(db_path)
    offset = (page - 1) * per_page
    rows = latest_telemetry_rows(db_path, limit=per_page, offset=offset)
    return rows, total


def _history_rows(db_path, uid, page, per_page):
    total = count_telemetry_history_rows(db_path, uid)
    offset = (page - 1) * per_page
    rows = latest_telemetry_history(db_path, uid, limit=per_page, offset=offset)
    return rows, total


def _render_values_rows(rows, config_map):
    parts = []
    for row in rows:
        uid = row.get("uid", "")
        config_rows = config_map.get(uid, [])
        first_cfg = config_rows[0] if config_rows else {}
        parts.append("<tr class='value-row' data-uid='{uid}' data-location='{location}'>".format(
            uid=_html_escape(uid),
            location=_html_escape("{} {}".format(row.get("lat", ""), row.get("long", ""))),
        ))
        parts.append("<td><a href='/device/{0}'>{0}</a></td>".format(_html_escape(uid)))
        parts.append("<td>{}</td>".format(_html_escape(_format_time(row.get("observed_ts")))))
        parts.append("<td>{}</td>".format(_html_escape(_form_value(row.get("pv")))))
        parts.append("<td>{}</td>".format(_html_escape(_status_state(row))))
        parts.append("<td>{}</td>".format(_html_escape(_form_value(row.get("rssi")))))
        parts.append("<td>{}</td>".format(_html_escape(_alarm_state(row))))
        parts.append("<td>{}</td>".format(_html_escape(first_cfg.get("high_threshold", ""))))
        parts.append("<td>{}</td>".format(_html_escape(first_cfg.get("low_threshold", ""))))
        parts.append("<td>{}</td>".format(_html_escape(first_cfg.get("hysteresis", ""))))
        parts.append("<td><a href='/device/{0}?page=1'>History</a></td>".format(_html_escape(uid)))
        parts.append("</tr>")
    return "".join(parts)


def _render_history_rows(rows):
    parts = []
    for row in rows:
        parts.append("<tr class='history-row'>")
        parts.append("<td>{}</td>".format(_html_escape(_format_time(row.get("observed_ts")))))
        parts.append("<td>{}</td>".format(_html_escape(_format_time(row.get("device_ts")))))
        parts.append("<td>{}</td>".format(_html_escape(_form_value(row.get("pv")))))
        parts.append("<td>{}</td>".format(_html_escape(_form_value(row.get("rssi")))))
        parts.append("<td>{}</td>".format(_html_escape(_status_state(row))))
        parts.append("<td>{}</td>".format(_html_escape(_alarm_state(row))))
        parts.append("</tr>")
    return "".join(parts)


def _values_dashboard_script():
    return """
<script>
function refreshValues(){
  var params = new URLSearchParams(window.location.search);
  if(!params.get('page')) params.set('page','1');
  if(!params.get('per_page')) params.set('per_page','20');
  fetch('/api/telemetry/latest?' + params.toString()).then(function(res){ return res.json(); }).then(function(data){
    var tbody=document.getElementById('values-body');
    if(!tbody) return;
    tbody.innerHTML=data.html || '';
  }).catch(function(){});
}
setInterval(refreshValues, 10000);
</script>
"""


def _history_dashboard_script(uid):
    return """
<script>
function refreshHistory(){
  var params = new URLSearchParams(window.location.search);
  params.set('uid', '__UID__');
  if(!params.get('page')) params.set('page','1');
  if(!params.get('per_page')) params.set('per_page','25');
  fetch('/api/telemetry/history?' + params.toString()).then(function(res){ return res.json(); }).then(function(data){
    var tbody=document.getElementById('history-body');
    if(!tbody) return;
    tbody.innerHTML=data.html || '';
  }).catch(function(){});
}
setInterval(refreshHistory, 10000);
</script>
""".replace("__UID__", _html_escape(uid))


def render_values_dashboard_html(db_path, latest_rows=None, page=1, per_page=20, total_rows=None):
    rows = latest_rows if latest_rows is not None else latest_telemetry_rows(db_path, limit=per_page, offset=(page - 1) * per_page)
    if total_rows is None:
        total_rows = count_latest_telemetry_uids(db_path) if latest_rows is None else max(len(rows), len(latest_rows))
    config_map = _config_map(db_path)
    parts = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>AIO Values Dashboard</title>",
        "<style>",
        "body{margin:0;font-family:Arial,sans-serif;background:linear-gradient(180deg,#fff8f2 0%,#fff1e2 100%);color:#31210f;}",
        ".shell{padding:22px 24px 36px;}",
        ".hero{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;}",
        ".hero h1{margin:0;font-size:28px;color:#b45309;}",
        ".toolbar{display:flex;gap:16px;flex-wrap:wrap;margin:18px 0 20px;}",
        ".search-box{background:#fff;border:2px solid #9f4d10;padding:10px 12px;min-width:280px;}",
        ".search-box label{display:block;font-size:14px;margin-bottom:6px;}",
        ".search-box input{width:100%;box-sizing:border-box;padding:8px 10px;border:1px solid #c46d23;background:#f9a64d;color:#fff;}",
        ".summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px;}",
        ".tile{background:#fff;border:1px solid #f1c6a5;padding:12px 14px;}",
        ".label{font-size:12px;color:#af611f;text-transform:uppercase;}",
        ".value{font-size:20px;font-weight:bold;margin-top:6px;color:#a64910;}",
        ".value-table{width:100%;border-collapse:collapse;background:#fff;}",
        ".value-table th,.value-table td{border:1px solid #f1c6a5;padding:8px;vertical-align:top;font-size:13px;}",
        ".value-table th{background:#f07b24;color:#fff;text-align:left;}",
        ".value-row:nth-child(even){background:#fff7ef;}",
        ".pager{display:flex;justify-content:space-between;align-items:center;gap:10px;margin:12px 0;}",
        ".pager a{color:#a94d10;text-decoration:none;font-weight:bold;}",
        "</style>",
        _values_dashboard_script(),
        "</head><body data-theme='orange'><div class='shell'>",
        "<div class='hero'><div><h1>AIO Values Dashboard</h1></div><a href='/config'>Open configuration</a></div>",
        "<div class='toolbar'>",
        "<div class='search-box'><label for='uid-filter'>Search UID</label><input id='uid-filter' oninput='filterValueRows()' placeholder='5001491'></div>",
        "<div class='search-box'><label for='location-filter'>Search location</label><input id='location-filter' oninput='filterValueRows()' placeholder='18.520 / 73.856'></div>",
        "</div>",
        "<div class='summary'>",
        "<div class='tile'><div class='label'>Rows</div><div class='value'>{}</div></div>".format(len(rows)),
        "<div class='tile'><div class='label'>Page</div><div class='value'>{}</div></div>".format(page),
        "<div class='tile'><div class='label'>Live Refresh</div><div class='value'>on</div></div>",
        "</div>",
        _page_controls("/", page, per_page, total_rows),
        "<table class='value-table'><thead><tr>",
    ]
    for _, label in VALUE_COLUMNS:
        parts.append("<th>{}</th>".format(_html_escape(label)))
    parts.append("</tr></thead><tbody id='values-body'>")
    if not rows:
        parts.append("<tr><td colspan='10'>No telemetry received yet.</td></tr>")
    else:
        parts.append(_render_values_rows(rows, config_map))
    parts.append("</tbody></table>")
    parts.append(
        """
<script>
function filterValueRows(){
  var uidTerm=(document.getElementById('uid-filter').value||'').toLowerCase();
  var locTerm=(document.getElementById('location-filter').value||'').toLowerCase();
  document.querySelectorAll('.value-row').forEach(function(row){
    var uid=(row.getAttribute('data-uid')||'').toLowerCase();
    var loc=(row.getAttribute('data-location')||'').toLowerCase();
    row.style.display=(uid.indexOf(uidTerm) !== -1 && loc.indexOf(locTerm) !== -1) ? '' : 'none';
  });
}
</script>
"""
    )
    parts.append("</div></body></html>")
    return "".join(parts)


def render_device_html(db_path, uid, page=1, per_page=25, history_rows=None, total_rows=None):
    latest = latest_telemetry_for_uid(db_path, uid)
    rows = history_rows if history_rows is not None else latest_telemetry_history(db_path, uid, limit=per_page, offset=(page - 1) * per_page)
    if total_rows is None:
        total_rows = count_telemetry_history_rows(db_path, uid) if history_rows is None else len(rows)
    parts = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>Device Details - {}</title>".format(_html_escape(uid)),
        "<style>",
        "body{margin:0;font-family:Arial,sans-serif;background:linear-gradient(180deg,#fff8f2 0%,#fff1e2 100%);color:#31210f;padding:22px 24px 36px;}",
        "a{color:#a94d10;text-decoration:none;font-weight:bold;}",
        ".back-btn{display:inline-block;margin-bottom:18px;padding:8px 14px;background:#e36c12;color:#fff;border-radius:2px;}",
        "h1{margin:0 0 16px 0;font-size:28px;color:#b45309;}",
        "h2{margin:22px 0 12px 0;font-size:20px;color:#b45309;}",
        ".summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:20px;}",
        ".tile{background:#fff;border:1px solid #f1c6a5;padding:12px 14px;}",
        ".label{font-size:12px;color:#af611f;text-transform:uppercase;}",
        ".value{font-size:20px;font-weight:bold;margin-top:6px;color:#a64910;}",
        ".value-table{width:100%;border-collapse:collapse;background:#fff;}",
        ".value-table th,.value-table td{border:1px solid #f1c6a5;padding:10px;vertical-align:top;font-size:13px;}",
        ".value-table th{background:#f07b24;color:#fff;text-align:left;}",
        ".history-row:nth-child(even){background:#fff7ef;}",
        ".pager{display:flex;justify-content:space-between;align-items:center;gap:10px;margin:12px 0;}",
        ".pager a{color:#a94d10;text-decoration:none;font-weight:bold;}",
        "</style>",
        _history_dashboard_script(uid),
        "</head><body data-theme='orange'>",
        "<a class='back-btn' href='/'>&larr; Back to Dashboard</a>",
        "<h1>Device Details: {}</h1>".format(_html_escape(uid)),
    ]
    if latest is None:
        parts.append("<p>No data for this UID.</p>")
    else:
        parts.append(
            "<div class='summary'>"
            "<div class='tile'><div class='label'>UID</div><div class='value'>{}</div></div>"
            "<div class='tile'><div class='label'>Value</div><div class='value'>{}</div></div>"
            "<div class='tile'><div class='label'>Status</div><div class='value'>{}</div></div>"
            "<div class='tile'><div class='label'>Location</div><div class='value' style='font-size:14px;word-break:break-all;'>{}<br>{}</div></div>"
            "</div>".format(
                _html_escape(latest.get("uid", "")),
                _html_escape(_form_value(latest.get("pv", ""))),
                _html_escape(_status_state(latest)),
                _html_escape(latest.get("lat", "") or "-"),
                _html_escape(latest.get("long", "") or "-"),
            )
        )
    parts.append(_page_controls("/device/{}".format(_html_escape(uid)), page, per_page, total_rows))
    parts.append("<h2>Recent Telemetry Samples</h2>")
    parts.append("<table class='value-table'><thead><tr>")
    for label in ["Observed Time", "Device Time", "Value", "RSSI", "Status", "Alarm"]:
        parts.append("<th>{}</th>".format(_html_escape(label)))
    parts.append("</tr></thead><tbody id='history-body'>")
    if not rows:
        parts.append("<tr><td colspan='6'>No history available.</td></tr>")
    else:
        parts.append(_render_history_rows(rows))
    parts.append("</tbody></table>")
    parts.append("</body></html>")
    return "".join(parts)


def _read_form_data(environ):
    content_length = int(environ.get("CONTENT_LENGTH") or "0")
    if content_length <= 0:
        return {}
    raw = environ["wsgi.input"].read(content_length).decode("utf-8", "ignore")
    parsed = parse_qs(raw, keep_blank_values=True)
    return {key: values[0] if values else "" for key, values in parsed.items()}


def _form_to_row(form):
    return {
        "uid": form.get("uid", "").strip(),
        "channel": form.get("channel", "").strip(),
        "name": form.get("name", "").strip(),
        "device_imei": form.get("device_imei", "").strip(),
        "lat": form.get("lat", "").strip(),
        "long": form.get("long", "").strip(),
        "range_4ma": form.get("range_4ma", "").strip(),
        "range_20ma": form.get("range_20ma", "").strip(),
        "calibration_offset_ma": form.get("calibration_offset_ma", "").strip(),
        "high_threshold": form.get("high_threshold", "").strip(),
        "low_threshold": form.get("low_threshold", "").strip(),
        "hysteresis": form.get("hysteresis", "").strip(),
        "unit": form.get("unit", "").strip(),
        "publish_as": form.get("publish_as", "string").strip() or "string",
        "string_format": form.get("string_format", "%.3f").strip() or "%.3f",
        "poll_cron": form.get("poll_cron", "").strip(),
        "sensor_health_threshold_ma": form.get("sensor_health_threshold_ma", "").strip(),
        "sensor_health_hysteresis_ma": form.get("sensor_health_hysteresis_ma", "").strip(),
    }


def _patch_values_from_form(form):
    index = form.get("channel_index", "0").strip() or "0"
    values = {
        "lat": form.get("lat", "").strip(),
        "long": form.get("long", "").strip(),
        f"channels.{index}.range_4ma": _to_number(form.get("range_4ma", "")),
        f"channels.{index}.range_20ma": _to_number(form.get("range_20ma", "")),
        f"channels.{index}.calibration_offset_ma": _to_number(form.get("calibration_offset_ma", "")),
        f"channels.{index}.high_threshold": _to_number(form.get("high_threshold", "")),
        f"channels.{index}.low_threshold": _to_number(form.get("low_threshold", "")),
        f"channels.{index}.hysteresis": _to_number(form.get("hysteresis", "")),
    }
    return {key: value for key, value in values.items() if value not in (None, "")}


def _snapshot_from_row(db_path, uid):
    snapshot_row = latest_device_config_snapshot(db_path, uid, AIO_CONFIG_FILE_NAME)
    if snapshot_row is None:
        return None
    try:
        return json.loads(snapshot_row.get("raw_json", "{}"))
    except (TypeError, ValueError):
        return None


def handle_config_apply(db_path, form):
    row = _form_to_row(form)
    uid = row.get("uid", "")
    if not uid:
        return {"ok": False, "message": "UID is required"}

    upsert_device_config(db_path, row)
    existing = _snapshot_from_row(db_path, uid) or {}
    config_rows = list_device_configs(db_path, uid=uid)
    config_object = build_device_config_object(uid, config_rows, snapshot_object=existing)
    patch_values = _patch_values_from_form(form)

    try:
        topic = publish_rpc_request(build_patch_config_payload(uid, patch_values), uid, _mqtt_settings_from_env())
    except Exception as exc:
        return {"ok": False, "message": "Config saved locally, but MQTT publish failed: {}".format(exc)}

    upsert_device_config_snapshot(
        db_path,
        {
            "uid": uid,
            "file_name": AIO_CONFIG_FILE_NAME,
            "raw_json": json.dumps(config_object, separators=(",", ":")),
            "source_topic": topic,
        },
    )
    replace_device_config_rows(db_path, uid, config_rows)
    return {"ok": True, "message": "Saved and published to {}".format(topic)}


def handle_config_read(form):
    uid = form.get("uid", "").strip()
    if not uid:
        return {"ok": False, "message": "UID is required"}
    try:
        topic = publish_rpc_request(build_read_config_payload(), uid, _mqtt_settings_from_env())
    except Exception as exc:
        return {"ok": False, "message": "Failed to publish read request: {}".format(exc)}
    return {"ok": True, "message": "Read command sent to topic {}".format(topic)}


def telemetry_latest_json(db_path, page=1, per_page=20):
    rows, total = _telemetry_rows(db_path, page, per_page)
    config_map = _config_map(db_path)
    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "html": _render_values_rows(rows, config_map),
    }


def telemetry_history_json(db_path, uid, page=1, per_page=25):
    rows, total = _history_rows(db_path, uid, page, per_page)
    return {
        "uid": uid,
        "page": page,
        "per_page": per_page,
        "total": total,
        "html": _render_history_rows(rows),
    }


def _read_query_params(environ):
    parsed = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
    return {key: values[0] if values else "" for key, values in parsed.items()}


def _json_response(payload):
    return json.dumps(payload).encode("utf-8")


def create_wsgi_app(db_path):
    def app(environ, start_response):
        path = environ.get("PATH_INFO", "/")
        method = environ.get("REQUEST_METHOD", "GET").upper()
        query = _read_query_params(environ)

        if path == "/health":
            start_response("200 OK", [("Content-Type", "application/json")])
            return [_json_response({"status": "ok"})]

        if method == "GET" and path == "/api/telemetry/latest":
            page = int(query.get("page", "1") or "1")
            per_page = int(query.get("per_page", "20") or "20")
            payload = telemetry_latest_json(db_path, page=page, per_page=per_page)
            start_response("200 OK", [("Content-Type", "application/json")])
            return [_json_response(payload)]

        if method == "GET" and path == "/api/telemetry/history":
            uid = query.get("uid", "").strip()
            page = int(query.get("page", "1") or "1")
            per_page = int(query.get("per_page", "25") or "25")
            payload = telemetry_history_json(db_path, uid, page=page, per_page=per_page)
            start_response("200 OK", [("Content-Type", "application/json")])
            return [_json_response(payload)]

        if method == "POST" and path == "/config/apply":
            form = _read_form_data(environ)
            result = handle_config_apply(db_path, form)
            status = "200 OK" if result["ok"] else "400 Bad Request"
            body = render_config_dashboard_html(db_path, message=result["message"])
            start_response(status, [("Content-Type", "text/html; charset=utf-8")])
            return [body.encode("utf-8")]

        if method == "POST" and path == "/config/read":
            form = _read_form_data(environ)
            result = handle_config_read(form)
            status = "200 OK" if result["ok"] else "400 Bad Request"
            body = render_config_dashboard_html(db_path, message=result["message"])
            start_response(status, [("Content-Type", "text/html; charset=utf-8")])
            return [body.encode("utf-8")]

        if path == "/" or path == "":
            page = int(query.get("page", "1") or "1")
            per_page = int(query.get("per_page", "20") or "20")
            body = render_values_dashboard_html(db_path, page=page, per_page=per_page)
            start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
            return [body.encode("utf-8")]

        if path == "/config":
            body = render_config_dashboard_html(db_path)
            start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
            return [body.encode("utf-8")]

        if path == "/values":
            page = int(query.get("page", "1") or "1")
            per_page = int(query.get("per_page", "20") or "20")
            body = render_values_dashboard_html(db_path, page=page, per_page=per_page)
            start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
            return [body.encode("utf-8")]

        if path.startswith("/device/"):
            uid = path.split("/", 2)[2]
            page = int(query.get("page", "1") or "1")
            per_page = int(query.get("per_page", "25") or "25")
            body = render_device_html(db_path, uid, page=page, per_page=per_page)
            start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
            return [body.encode("utf-8")]

        start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"Not Found"]

    return app
