# AIO Dashboard Demo

Simple telemetry dashboard for the AIO telemetry and JSON-RPC config contract.

## What it does

- Subscribes to `devices/+/telemetry`
- Stores each payload in SQLite keyed by `UID`
- Serves a blue configuration dashboard and an orange values dashboard
- Publishes JSON-RPC `patch_config` requests to `device/{UID}/rpc/req`

## Run

Start the dashboard:

```bash
python -m aio_dashboard.server
```

Start the MQTT ingest worker:

```bash
python -m aio_dashboard.mqtt_ingest
```

## Configure

Copy `.env.example` and set:

- `AIO_DB_PATH`
- `AIO_WEB_HOST`
- `AIO_WEB_PORT`
- `AIO_MQTT_HOST`
- `AIO_MQTT_PORT`
- `AIO_MQTT_TOPIC`
- `AIO_MQTT_USERNAME`
- `AIO_MQTT_PASSWORD`
- `AIO_MQTT_CLIENT_ID`
- `AIO_APPLY_MQTT_HOST`
- `AIO_APPLY_MQTT_PORT`
- `AIO_APPLY_MQTT_USERNAME`
- `AIO_APPLY_MQTT_PASSWORD`
- `AIO_APPLY_MQTT_TOPIC`
- `AIO_APPLY_MQTT_CLIENT_ID`

## Pages

- `/` - configuration dashboard
- `/values` - latest telemetry dashboard
- `/device/<uid>` - per-UID history page
- `/health` - health check

## Apply flow

The save/apply button publishes this firmware contract:

```json
{
  "command": "mqtt_config",
  "param": [
    {
      "file_name": "aio_config_<uid>.json",
      "config": "{...json string...}"
    }
  ]
}
```

The dashboard now uses:

- `read_file` to load `customer`
- `patch_config` to update `customer`
- `device/{UID}/rpc/req` for requests
- `device/{UID}/rpc/res` for responses

Telemetry payloads are expected to include:

- root `UID`, `lat`, `long`, `time`, `rssi`, `sh`
- `data[0].pv`
- `data[0].ha` / `data[0].la` only when an alarm is active

The dashboard converts UTC epoch timestamps to IST before rendering.
