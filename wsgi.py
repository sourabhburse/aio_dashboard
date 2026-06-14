import os
from aio_dashboard.db import init_db
from aio_dashboard.web import create_wsgi_app

# Initialize database and WSGI application using environment configurations
db_path = os.environ.get("AIO_DB_PATH", "aio_dashboard.sqlite3")
init_db(db_path)
application = create_wsgi_app(db_path)
