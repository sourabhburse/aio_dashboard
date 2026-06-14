# AIO Dashboard RPC and Live Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the dashboard to speak the new JSON-RPC config contract, parse the new telemetry shape, and auto-refresh dashboard/history views with pagination.

**Architecture:** Keep the app as a small WSGI service with SQLite persistence. Move payload translation into `parsing.py`, persistence and schema migration into `db.py`, MQTT request/response handling into `mqtt_ingest.py`, and HTML/JSON rendering plus form handling into `dashboard.py`. Add lightweight JSON endpoints and client-side polling so the pages stay current without full refreshes.

**Tech Stack:** Python 3, SQLite, WSGI, `paho-mqtt`, standard-library JSON/HTML rendering, existing unittest-based tests.

---

### Task 1: Migrate telemetry and config persistence

**Files:**
- Modify: `db.py`
- Test: `tests/test_telemetry.py`
- Test: `tests/test_config_sync.py`

- [ ] **Step 1: Write the failing test**

```python
def test_init_db_adds_new_telemetry_and_config_columns():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "aio_dashboard.sqlite3")
        init_db(db_path)
        rows = list_device_configs(db_path)
        assert rows == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_telemetry.py tests/test_config_sync.py -v`
Expected: failure because the schema and query helpers do not yet match the new contract.

- [ ] **Step 3: Write minimal implementation**

```python
def init_db(db_path):
    # add sh/ha/la columns and new config columns via ALTER TABLE when missing
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_telemetry.py tests/test_config_sync.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add db.py tests/test_telemetry.py tests/test_config_sync.py
git commit -m "feat: migrate aio dashboard storage"
```

### Task 2: Parse new telemetry and JSON-RPC config payloads

**Files:**
- Modify: `parsing.py`
- Modify: `mqtt_ingest.py`
- Test: `tests/test_telemetry.py`
- Test: `tests/test_config_sync.py`

- [ ] **Step 1: Write the failing test**

```python
def test_parse_telemetry_payload_supports_root_sh_and_ha_la():
    payload = {"UID": "5001491", "time": "1718000000", "sh": "0", "data": [{"time": "1718000000", "pv": 12.345, "ha": "1"}]}
    sample = parse_telemetry_payload(payload)
    assert sample.sh == "0"
    assert sample.ha == "1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_telemetry.py::TelemetryFlowTest::test_parse_telemetry_payload_supports_root_sh_and_ha_la -v`
Expected: failure because the parser still reads `ht/lt` only.

- [ ] **Step 3: Write minimal implementation**

```python
def parse_telemetry_payload(payload):
    # accept root time, sh, and per-reading ha/la
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_telemetry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add parsing.py mqtt_ingest.py tests/test_telemetry.py tests/test_config_sync.py
git commit -m "feat: parse aio rpc telemetry"
```

### Task 3: Rework config apply/read to JSON-RPC

**Files:**
- Modify: `dashboard.py`
- Modify: `web.py`
- Test: `tests/test_dashboard_contract.py`

- [ ] **Step 1: Write the failing test**

```python
def test_build_patch_config_payload_uses_jsonrpc_patch_config():
    payload = build_patch_config_payload("5001491", {"channels.0.range_4ma": 0.0})
    assert payload["method"] == "patch_config"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dashboard_contract.py::DashboardContractTest::test_build_patch_config_payload_uses_jsonrpc_patch_config -v`
Expected: failure because the current code still emits `mqtt_config`.

- [ ] **Step 3: Write minimal implementation**

```python
def build_patch_config_payload(uid, values):
    return {"jsonrpc": "2.0", "id": 1, "method": "patch_config", "params": {"name": "customer", "values": values}}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dashboard_contract.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard.py web.py tests/test_dashboard_contract.py
git commit -m "feat: switch config ui to rpc patching"
```

### Task 4: Add live-refresh APIs and pagination

**Files:**
- Modify: `dashboard.py`
- Modify: `web.py`
- Test: `tests/test_dashboard_contract.py`
- Test: `tests/test_telemetry.py`

- [ ] **Step 1: Write the failing test**

```python
def test_render_values_dashboard_includes_polling_script_and_page_controls():
    html = render_values_dashboard_html(tmpdb, page=1, per_page=10)
    assert "setInterval" in html
    assert "page=" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dashboard_contract.py::DashboardContractTest::test_render_values_dashboard_uses_orange_layout_and_latest_readings -v`
Expected: failure until pagination and live refresh are added.

- [ ] **Step 3: Write minimal implementation**

```python
def render_values_dashboard_html(db_path, page=1, per_page=20, latest_rows=None):
    # render a paginated table and poll a JSON endpoint for live updates
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dashboard_contract.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dashboard.py web.py tests/test_dashboard_contract.py tests/test_telemetry.py
git commit -m "feat: add live dashboard pagination"
```
