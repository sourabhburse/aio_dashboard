FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir gunicorn

# Copy application code into the 'aio_dashboard' package directory
COPY . /app/aio_dashboard

# Ensure Python can import 'aio_dashboard' from the parent directory /app
ENV PYTHONPATH=/app
# Run unbuffered Python output
ENV PYTHONUNBUFFERED=1

# Expose web server port
EXPOSE 8000

# Default command: starts the production WSGI server
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "4", "aio_dashboard.wsgi:application"]
