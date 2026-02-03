# OpenChargeback Dockerfile
# Multi-stage build for smaller production image

FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy and install dependencies
COPY pyproject.toml .
COPY src/ src/
COPY README.md .

RUN pip install --no-cache-dir .

# Production image
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies for WeasyPrint (PDF generation)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/openchargeback /usr/local/bin/openchargeback
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn

# Copy application code (for templates and static files)
COPY src/openchargeback/web/templates /app/templates
COPY src/openchargeback/web/static /app/static

# Create directories for data
RUN mkdir -p /app/data /app/output/statements /app/output/journals

# Default config location
ENV CONFIG_PATH=/app/config.yaml

# Expose port (3000 for Caddy wildcard routing)
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:3000/login')" || exit 1

# Run the web server
CMD ["openchargeback", "serve", "--host", "0.0.0.0", "--port", "3000"]
