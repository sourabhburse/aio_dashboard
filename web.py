from aio_dashboard.dashboard import (
    build_patch_config_payload,
    create_wsgi_app,
    render_config_dashboard_html,
    render_device_html,
    render_values_dashboard_html,
)


def render_dashboard_html(db_path, page=1, per_page=20):
    return render_values_dashboard_html(db_path, page=page, per_page=per_page)
