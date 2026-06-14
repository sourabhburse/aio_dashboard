import sqlite3
import time
from contextlib import contextmanager


SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL,
    lat TEXT NOT NULL,
    long TEXT NOT NULL,
    rssi INTEGER NOT NULL,
    pv TEXT,
    sh TEXT,
    ha TEXT,
    la TEXT,
    device_ts INTEGER,
    observed_ts INTEGER NOT NULL,
    raw_payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_telemetry_uid_id ON telemetry(uid, id DESC);

CREATE TABLE IF NOT EXISTS device_config (
    uid TEXT NOT NULL,
    channel TEXT NOT NULL,
    name TEXT,
    device_imei TEXT,
    lat TEXT,
    long TEXT,
    range_4ma TEXT,
    range_20ma TEXT,
    calibration_offset_ma TEXT,
    high_threshold TEXT,
    low_threshold TEXT,
    hysteresis TEXT,
    unit TEXT,
    poll_cron TEXT,
    publish_as TEXT,
    string_format TEXT,
    sensor_health_threshold_ma TEXT,
    sensor_health_hysteresis_ma TEXT,
    value_format TEXT,
    updated_ts INTEGER NOT NULL,
    PRIMARY KEY (uid, channel)
);
CREATE INDEX IF NOT EXISTS idx_device_config_uid ON device_config(uid);

CREATE TABLE IF NOT EXISTS device_config_snapshot (
    uid TEXT NOT NULL,
    file_name TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    source_topic TEXT,
    fetched_ts INTEGER NOT NULL,
    PRIMARY KEY (uid, file_name)
);
CREATE INDEX IF NOT EXISTS idx_device_config_snapshot_uid ON device_config_snapshot(uid);
"""


@contextmanager
def _connect(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def _ensure_columns(conn, table_name, required_columns):
    rows = conn.execute("PRAGMA table_info({})".format(table_name)).fetchall()
    existing = {row[1] for row in rows}
    for column, column_type in required_columns.items():
        if column not in existing:
            conn.execute("ALTER TABLE {} ADD COLUMN {} {}".format(table_name, column, column_type))


def init_db(db_path):
    with _connect(db_path) as conn:
        conn.executescript(SCHEMA)
        _ensure_columns(
            conn,
            "telemetry",
            {
                "pv": "TEXT",
                "sh": "TEXT",
                "ha": "TEXT",
                "la": "TEXT",
            },
        )
        _ensure_columns(
            conn,
            "device_config",
            {
                "name": "TEXT",
                "device_imei": "TEXT",
                "range_4ma": "TEXT",
                "range_20ma": "TEXT",
                "calibration_offset_ma": "TEXT",
                "high_threshold": "TEXT",
                "low_threshold": "TEXT",
                "hysteresis": "TEXT",
                "unit": "TEXT",
                "poll_cron": "TEXT",
                "publish_as": "TEXT",
                "string_format": "TEXT",
                "sensor_health_threshold_ma": "TEXT",
                "sensor_health_hysteresis_ma": "TEXT",
                "value_format": "TEXT",
            },
        )


def save_telemetry(db_path, sample):
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO telemetry (
                uid, lat, long, rssi, pv, sh, ha, la, device_ts, observed_ts, raw_payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sample.uid,
                sample.lat,
                sample.long,
                sample.rssi,
                sample.pv,
                sample.sh,
                sample.ha,
                sample.la,
                sample.device_ts,
                int(time.time()),
                sample.raw_payload,
            ),
        )
        conn.commit()


def _normalize_config_row(uid, config_row):
    defaults = {
        "uid": uid or "",
        "channel": "",
        "name": "",
        "device_imei": "",
        "lat": "",
        "long": "",
        "range_4ma": "",
        "range_20ma": "",
        "calibration_offset_ma": "",
        "high_threshold": "",
        "low_threshold": "",
        "hysteresis": "",
        "unit": "",
        "poll_cron": "",
        "publish_as": "string",
        "string_format": "%.3f",
        "sensor_health_threshold_ma": "",
        "sensor_health_hysteresis_ma": "",
        "value_format": "string",
    }
    row = defaults.copy()
    row.update(config_row or {})
    row["uid"] = uid or row.get("uid", "")
    row["channel"] = str(row.get("channel", "") or "").strip()
    row["name"] = str(row.get("name", "") or "").strip()
    row["device_imei"] = str(row.get("device_imei", "") or "").strip()
    row["lat"] = str(row.get("lat", "") or "").strip()
    row["long"] = str(row.get("long", "") or "").strip()
    row["range_4ma"] = str(row.get("range_4ma", "") or "").strip()
    row["range_20ma"] = str(row.get("range_20ma", "") or "").strip()
    row["calibration_offset_ma"] = str(row.get("calibration_offset_ma", "") or "").strip()
    row["high_threshold"] = str(row.get("high_threshold", "") or "").strip()
    row["low_threshold"] = str(row.get("low_threshold", "") or "").strip()
    row["hysteresis"] = str(row.get("hysteresis", "") or "").strip()
    row["unit"] = str(row.get("unit", "") or "").strip()
    row["poll_cron"] = str(row.get("poll_cron", "") or "").strip()
    row["publish_as"] = str(row.get("publish_as", "string") or "string").strip() or "string"
    row["string_format"] = str(row.get("string_format", "%.3f") or "%.3f").strip() or "%.3f"
    row["sensor_health_threshold_ma"] = str(row.get("sensor_health_threshold_ma", "") or "").strip()
    row["sensor_health_hysteresis_ma"] = str(row.get("sensor_health_hysteresis_ma", "") or "").strip()
    row["value_format"] = str(row.get("value_format", "string") or "string").strip() or "string"
    row["updated_ts"] = int(time.time())
    return row


def upsert_device_config(db_path, config_row):
    row = _normalize_config_row(config_row.get("uid", ""), config_row)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO device_config (
                uid, channel, name, device_imei, lat, long,
                range_4ma, range_20ma, calibration_offset_ma,
                high_threshold, low_threshold, hysteresis, unit,
                poll_cron, publish_as, string_format,
                sensor_health_threshold_ma, sensor_health_hysteresis_ma,
                value_format, updated_ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["uid"],
                row["channel"],
                row["name"],
                row["device_imei"],
                row["lat"],
                row["long"],
                row["range_4ma"],
                row["range_20ma"],
                row["calibration_offset_ma"],
                row["high_threshold"],
                row["low_threshold"],
                row["hysteresis"],
                row["unit"],
                row["poll_cron"],
                row["publish_as"],
                row["string_format"],
                row["sensor_health_threshold_ma"],
                row["sensor_health_hysteresis_ma"],
                row["value_format"],
                row["updated_ts"],
            ),
        )
        conn.commit()


def replace_device_config_rows(db_path, uid, config_rows):
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM device_config WHERE uid = ?", (uid,))
        for row in config_rows or []:
            normalized = _normalize_config_row(uid, row)
            conn.execute(
                """
                INSERT OR REPLACE INTO device_config (
                    uid, channel, name, device_imei, lat, long,
                    range_4ma, range_20ma, calibration_offset_ma,
                    high_threshold, low_threshold, hysteresis, unit,
                    poll_cron, publish_as, string_format,
                    sensor_health_threshold_ma, sensor_health_hysteresis_ma,
                    value_format, updated_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized["uid"],
                    normalized["channel"],
                    normalized["name"],
                    normalized["device_imei"],
                    normalized["lat"],
                    normalized["long"],
                    normalized["range_4ma"],
                    normalized["range_20ma"],
                    normalized["calibration_offset_ma"],
                    normalized["high_threshold"],
                    normalized["low_threshold"],
                    normalized["hysteresis"],
                    normalized["unit"],
                    normalized["poll_cron"],
                    normalized["publish_as"],
                    normalized["string_format"],
                    normalized["sensor_health_threshold_ma"],
                    normalized["sensor_health_hysteresis_ma"],
                    normalized["value_format"],
                    normalized["updated_ts"],
                ),
            )
        conn.commit()


def list_device_configs(db_path, uid=None):
    query = """
        SELECT uid, channel, name, device_imei, lat, long,
               range_4ma, range_20ma, calibration_offset_ma,
               high_threshold, low_threshold, hysteresis, unit,
               poll_cron, publish_as, string_format,
               sensor_health_threshold_ma, sensor_health_hysteresis_ma,
               value_format, updated_ts
        FROM device_config
    """
    params = ()
    if uid:
        query += " WHERE uid = ?"
        params = (uid,)
    query += " ORDER BY uid, channel"
    with _connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def upsert_device_config_snapshot(db_path, snapshot):
    defaults = {
        "uid": "",
        "file_name": "customer",
        "raw_json": "{}",
        "source_topic": "",
    }
    row = defaults.copy()
    row.update(snapshot or {})
    row["uid"] = str(row.get("uid", "") or "").strip()
    row["file_name"] = str(row.get("file_name", "customer") or "").strip() or "customer"
    row["raw_json"] = str(row.get("raw_json", "{}") or "{}")
    row["source_topic"] = str(row.get("source_topic", "") or "")
    row["fetched_ts"] = int(time.time())

    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO device_config_snapshot (
                uid, file_name, raw_json, source_topic, fetched_ts
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                row["uid"],
                row["file_name"],
                row["raw_json"],
                row["source_topic"],
                row["fetched_ts"],
            ),
        )
        conn.commit()


def latest_device_config_snapshot(db_path, uid, file_name="customer"):
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT uid, file_name, raw_json, source_topic, fetched_ts
            FROM device_config_snapshot
            WHERE uid = ? AND file_name = ?
            ORDER BY fetched_ts DESC
            LIMIT 1
            """,
            (uid, file_name),
        ).fetchone()
        return _row_to_dict(row)


def list_device_config_snapshots(db_path, file_name="customer"):
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT uid, file_name, raw_json, source_topic, fetched_ts
            FROM device_config_snapshot
            WHERE file_name = ?
            ORDER BY uid, fetched_ts DESC
            """,
            (file_name,),
        ).fetchall()
        return [dict(row) for row in rows]


def latest_telemetry_for_uid(db_path, uid):
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT uid, lat, long, rssi, pv, sh, ha, la, device_ts, observed_ts
            FROM telemetry
            WHERE uid = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (uid,),
        ).fetchone()
        return _row_to_dict(row)


def count_latest_telemetry_uids(db_path):
    with _connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(DISTINCT uid) AS total FROM telemetry").fetchone()
        return int(row["total"] if row else 0)


def latest_telemetry_rows(db_path, limit=20, offset=0):
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT t.uid, t.lat, t.long, t.rssi, t.pv, t.sh, t.ha, t.la,
                   t.device_ts, t.observed_ts
            FROM telemetry t
            INNER JOIN (
                SELECT uid, MAX(id) AS max_id
                FROM telemetry
                GROUP BY uid
            ) latest
            ON latest.uid = t.uid AND latest.max_id = t.id
            ORDER BY t.observed_ts DESC, t.uid
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [dict(row) for row in rows]


def count_telemetry_history_rows(db_path, uid):
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM telemetry WHERE uid = ?",
            (uid,),
        ).fetchone()
        return int(row["total"] if row else 0)


def latest_telemetry_history(db_path, uid, limit=25, offset=0):
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT uid, lat, long, rssi, pv, sh, ha, la, device_ts, observed_ts
            FROM telemetry
            WHERE uid = ?
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (uid, limit, offset),
        ).fetchall()
        return [dict(row) for row in rows]
