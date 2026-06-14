import os
from wsgiref.simple_server import make_server

from aio_dashboard.db import init_db
from aio_dashboard.web import create_wsgi_app


def main():
    db_path = os.environ.get("AIO_DB_PATH", "aio_dashboard.sqlite3")
    host = os.environ.get("AIO_WEB_HOST", "0.0.0.0")
    port = int(os.environ.get("AIO_WEB_PORT", "8000"))
    init_db(db_path)
    app = create_wsgi_app(db_path)
    with make_server(host, port, app) as httpd:
        print("Serving on http://{}:{}/".format(host, port))
        httpd.serve_forever()


if __name__ == "__main__":
    main()
