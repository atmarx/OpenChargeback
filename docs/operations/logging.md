# Logging

OpenChargeback produces structured logs suitable for log aggregation systems like Splunk, ELK, or Datadog.

## Configuration

```yaml
logging:
  enabled: true
  level: INFO                     # DEBUG, INFO, WARN, WARNING, ERROR
  format: splunk                  # "splunk" (key=value) or "json"
  file: ./instance/logs/openchargeback.log  # Optional file output
```

## Log Levels

| Level | Use Case |
|-------|----------|
| DEBUG | Development troubleshooting, verbose output |
| INFO | Normal operation, significant events |
| WARN | Recoverable issues, configuration problems |
| ERROR | Failures requiring attention |

## Log Formats

### Splunk Format (Default)

Human-readable key=value pairs:

```
2026-01-08T12:15:00Z INFO  ingest started source=aws file=billing.csv
2026-01-08T12:15:02Z INFO  charges imported count=89 period=2025-01 total_cost=12543.87
2026-01-08T12:15:02Z WARN  charges flagged count=2 reason=period_mismatch
2026-01-08T12:20:10Z ERROR email failed pi=smith@example.edu error="SMTP timeout"
```

### JSON Format

Machine-parseable JSON:

```json
{"timestamp":"2026-01-08T12:15:00Z","level":"INFO","event":"ingest_started","source":"aws","file":"billing.csv"}
{"timestamp":"2026-01-08T12:15:02Z","level":"INFO","event":"charges_imported","count":89,"period":"2025-01","total_cost":12543.87}
```

## Log Destinations

### Stderr (Default)

Always outputs to stderr, suitable for Docker and systemd capture.

### File Output

When `logging.file` is configured, logs are written to both stderr and the file:

```yaml
logging:
  file: ./instance/logs/openchargeback.log
```

The parent directory is created automatically if it doesn't exist.

### Log Rotation

For file-based logging, configure logrotate:

```
/path/to/instance/logs/openchargeback.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 www-data www-data
}
```

## Common Log Events

### Ingest Events

| Event | Level | Description |
|-------|-------|-------------|
| `ingest_started` | INFO | Import process beginning |
| `charges_imported` | INFO | Successful import completion |
| `charges_flagged` | WARN | Charges requiring review |
| `ingest_failed` | ERROR | Import failure |

### Statement Events

| Event | Level | Description |
|-------|-------|-------------|
| `statement_generated` | INFO | PDF created |
| `email_sent` | INFO | Email delivered |
| `email_failed` | ERROR | Email delivery failure |

### Auth Events

| Event | Level | Description |
|-------|-------|-------------|
| `login_success` | INFO | User authenticated |
| `login_failed` | WARN | Authentication failure |
| `session_expired` | INFO | Session timeout |

## Splunk Integration

### Index Configuration

Create a dedicated index for billing logs:

```
[openchargeback]
homePath = $SPLUNK_DB/openchargeback/db
coldPath = $SPLUNK_DB/openchargeback/colddb
thawedPath = $SPLUNK_DB/openchargeback/thaweddb
```

### Useful Queries

```spl
# All errors in last 24 hours
index=openchargeback level=ERROR earliest=-24h

# Import summary by source
index=openchargeback event=charges_imported | stats sum(count) by source

# Failed emails
index=openchargeback event=email_failed | table _time pi error

# Login attempts
index=openchargeback event IN (login_success, login_failed) | stats count by event, user
```

## Datadog Integration

For JSON format logs, use the Datadog agent log configuration:

```yaml
logs:
  - type: file
    path: /path/to/openchargeback.log
    service: openchargeback
    source: python
```

## Troubleshooting with Logs

### "Why wasn't this charge imported?"

```bash
grep "charge_id=ABC123" openchargeback.log
# Or search for the period
grep "period=2025-01" openchargeback.log | grep -E "(flagged|rejected)"
```

### "Why did this email fail?"

```bash
grep "email_failed" openchargeback.log | grep "smith@example.edu"
```

### "What happened during this import?"

```bash
grep "ingest" openchargeback.log | grep "2026-01-08T12:15"
```
