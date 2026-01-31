# Docker Deployment

OpenChargeback can be deployed using Docker for production environments.

## Quick Start

```bash
# Build and run with Docker Compose
docker compose -f docker/docker-compose.yml up -d

# Check status
docker compose -f docker/docker-compose.yml ps

# View logs
docker compose -f docker/docker-compose.yml logs -f
```

The web interface will be available at `http://localhost:8000`.

## Using the Service Script

The `scripts/service.sh` helper simplifies common operations:

```bash
# Start in production mode
scripts/service.sh --start --env prod

# Start in development mode
scripts/service.sh --start --env dev

# Stop
scripts/service.sh --stop

# Restart
scripts/service.sh --restart

# View status
scripts/service.sh --status
```

## Docker Compose Configuration

```yaml
# docker/docker-compose.yml
version: '3.8'

services:
  openchargeback:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - ../instance:/app/instance
      - ../templates:/app/templates:ro
    environment:
      - WEB_SECRET_KEY=${WEB_SECRET_KEY}
      - SMTP_USER=${SMTP_USER}
      - SMTP_PASSWORD=${SMTP_PASSWORD}
    restart: unless-stopped
```

## Environment Variables

Create a `.env` file for sensitive values:

```bash
# docker/.env
WEB_SECRET_KEY=your-secret-key-here
SMTP_USER=smtp-username
SMTP_PASSWORD=smtp-password
```

Generate a secret key:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Volume Mounts

| Mount | Purpose |
|-------|---------|
| `./instance:/app/instance` | Database, config, and output files |
| `./templates:/app/templates:ro` | Custom template overrides (read-only) |

## Production Considerations

### Reverse Proxy

For production, put OpenChargeback behind a reverse proxy (nginx, Caddy, Traefik):

```nginx
# nginx configuration
server {
    listen 443 ssl;
    server_name billing.example.edu;

    ssl_certificate /etc/ssl/certs/billing.crt;
    ssl_certificate_key /etc/ssl/private/billing.key;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Health Checks

Add a health check to your Docker Compose:

```yaml
services:
  openchargeback:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### Resource Limits

```yaml
services:
  openchargeback:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 1G
        reservations:
          cpus: '0.5'
          memory: 256M
```

## Building the Image

```bash
# Build
docker build -t openchargeback:latest -f docker/Dockerfile .

# Build with specific tag
docker build -t openchargeback:v0.3.1 -f docker/Dockerfile .
```

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker compose -f docker/docker-compose.yml logs openchargeback

# Check if port is in use
ss -tlnp | grep 8000
```

### Permission Issues

Ensure the `instance/` directory is writable by the container:

```bash
chmod -R 755 instance/
```

### Database Locked

If you see "database is locked" errors, ensure only one instance is running:

```bash
docker compose -f docker/docker-compose.yml down
docker compose -f docker/docker-compose.yml up -d
```

## Updating

```bash
# Pull latest code
git pull

# Rebuild and restart
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml up -d
```
