FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root system user for security hardening
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup appuser

# Copy application configuration and source code
COPY config/ ./config/
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Create data directory and set permissions
RUN mkdir -p /app/data && chown -R appuser:appgroup /app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

CMD ["sh", "-c", "mkdir -p /app/data && (chown -R appuser:appgroup /app/data 2>/dev/null || chmod 777 /app/data 2>/dev/null || true) && exec su -s /bin/sh appuser -c 'exec uvicorn backend.main:app --host 0.0.0.0 --port 8000'"]
