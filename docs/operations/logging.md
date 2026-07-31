# Logging

OpenChargeback produces structured logs suitable for log aggregation systems like Splunk, ELK, or Datadog.

## Configuration

```yaml
logging:
  enabled: true
  level: INFO                     # DEBUG, INFO, WARN, WARNING, ERROR
  format: splunk                  # "splunk" (key=value) or "json"
  file: ./instance/logs/openchargeback.log  # Optional file output
  syslog:                         # Optional remote collector
    host: syslog.example.edu
    port: 514
    protocol: udp                 # "udp" or "tcp"
    facility: local4
    ident: openchargeback
```

## What gets emitted, and who decides

OpenChargeback emits a log line for every action it takes.  It does not filter
for relevance, and that is deliberate.

An application cannot know which of its events matter to a security team, an
auditor, or an incident three months from now.  Deciding on their behalf means
guessing — and a guess that drops the wrong event is invisible until someone
needs it.  So OCB emits everything and forwards it to a collector that
somebody else runs.  Triage, retention, and promotion to an analytics tier
(Splunk, Cribl, Sentinel, whatever) happen there.

This mirrors the posture in [Data Protection](../security/data-protection.md):
OpenChargeback is a recorder, not a system of record.  It is not the system of
record for your accounting, and it is not the system of record for your logs.

If you are tempted to trim the event list because it looks noisy, that is the
tradeoff working as intended.  Volume is the collector's problem to price;
completeness is ours.

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
2026-01-08T12:15:00Z INFO  import.completed source=aws filename=billing.csv row_count=89 period=2025-01 total_cost=12543.87 flagged_count=2 user=system
2026-01-08T12:20:10Z INFO  email.error recipient=smith@example.edu subject="Cloud charges 2025-01" status=error error="SMTP timeout"
2026-01-08T12:22:41Z INFO  auth.login username=jdoe role=admin method=database source_ip=10.10.1.44 user=jdoe
```

### JSON Format

Machine-parseable JSON:

```json
{"timestamp":"2026-01-08T12:15:00Z","level":"INFO","event":"import.completed","event_type":"import","action":"completed","source":"aws","filename":"billing.csv","row_count":89,"period":"2025-01","total_cost":12543.87,"flagged_count":2,"user":"system"}
{"timestamp":"2026-01-08T12:22:41Z","level":"INFO","event":"auth.login","event_type":"auth","action":"login","username":"jdoe","role":"admin","method":"database","source_ip":"10.10.1.44","user":"jdoe"}
```

Every audit event carries `event_type` and `action` as separate fields in
addition to the dotted `event` name, so a collector can facet on either.

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

### Remote Syslog

Ships every line to a collector somebody else operates.  This is the intended
production setup: OCB forwards everything, and the collector's owners decide
what to keep, how long to keep it, and what gets promoted to an analytics tier.

```yaml
logging:
  syslog:
    host: syslog.example.edu
    port: 514
    protocol: udp        # or tcp
    facility: local4
    ident: openchargeback
```

Syslog is **added to** stderr and file output, not swapped for them — turning it
on does not cost you the local output you already had.

Two things worth knowing before you pick a protocol:

- **UDP cannot tell whether anything is listening.**  If the collector is
  decommissioned, moved, or firewalled off, OCB will transmit into the void
  indefinitely and report no error, because there is no error to report.  The
  logs look healthy from this end right up until someone goes looking for an
  event that was never delivered.
- **TCP fails at startup if the collector is unreachable**, and OCB says so
  loudly on stderr — then carries on running without remote logging.  A
  billing run is not aborted because a log collector is down.

Use TCP if you need to know the pipe works.  Use UDP if you would rather the
application never block on the collector, and you monitor delivery from the
collector side instead.

Either way, confirm events are arriving before you rely on them.  From the
collector:

```bash
# watch for openchargeback lines by ident
tail -f /var/log/syslog | grep openchargeback
```

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

## Audit Events

Event names are dotted — `{event_type}.{action}` — and are emitted by
`openchargeback.audit`.  [Audit Trail](../security/audit-trail.md) is the
canonical list; the table below is generated from the same source and is
verified against the code by `tests/test_audit_events.py`.

| Event | Description |
|-------|-------------|
| `import.completed` | A source file was imported (carries `flagged_count`) |
| `export.journal` | A journal was exported |
| `export.close_package` | A period close package was downloaded |
| `statement.generated` | A statement PDF was created |
| `statement.sent` | A statement was emailed |
| `email.success` | Email delivered |
| `email.dev_mode` | Email written to disk instead of sent (dev mode) |
| `email.error` | Email delivery failed |
| `charge.approved` | A flagged charge was approved |
| `charge.rejected` | A flagged charge was rejected |
| `charge.bulk_approved` | Charges approved in bulk |
| `period.created` | Billing period created |
| `period.closed` | Billing period closed |
| `period.finalized` | Billing period finalized (permanent) |
| `period.reopened` | Billing period reopened |
| `user.created` | User account created |
| `user.updated` | User account modified |
| `user.deleted` | User account deleted |
| `user.password_reset` | Admin reset a user's password |
| `user.password_changed` | User changed their own password |
| `auth.login` | Successful login (carries `method`, `source_ip`) |
| `auth.login_failed` | Failed login attempt |
| `auth.logout` | Explicit logout |
| `auth.session_invalidated` | Session discarded — its user no longer exists |
| `auth.password_change_failed` | Self-service password change rejected |
| `settings.changed` | Runtime settings modified |
| `settings.data_reset` | Dev-mode destructive data reset |

### Notes for whoever triages these

`auth.login` carries a `method` field: `database`, `config`, or `recovery`.
A **`recovery` login bypasses the database entirely** — it exists so an
institution can get back in when DB auth is broken.  If you alert on one
authentication event, alert on that one.

`source_ip` is the peer address OCB can actually see.  Behind a reverse proxy
that is the proxy, not the browser; the proxy's own logs are authoritative for
the real client address.  OCB deliberately does not trust `X-Forwarded-For`,
which any client can set.

There is **no session-expiry event.**  An expired session cookie is rejected by
the session middleware before the application is involved, so there is nothing
for OCB to observe or emit.  `auth.session_invalidated` is a different thing: a
still-valid session naming a user who has since been deleted.  If you need
true session-expiry accounting, it has to come from the proxy or SSO layer.

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
index=openchargeback event=import.completed | stats sum(row_count) by source

# Failed emails
index=openchargeback event=email.error | table _time recipient error

# Login attempts
index=openchargeback event IN ("auth.login", "auth.login_failed") | stats count by event, username

# Recovery logins - these bypass database auth entirely
index=openchargeback event=auth.login method=recovery | table _time username source_ip

# Anything destructive
index=openchargeback event IN ("settings.data_reset", "period.finalized", "user.deleted")
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
grep "email.error" openchargeback.log | grep "smith@example.edu"
```

### "What happened during this import?"

```bash
grep "import.completed" openchargeback.log | grep "2026-01-08T12:15"
```

### "Who logged in as the recovery account?"

```bash
grep "auth.login" openchargeback.log | grep "method=recovery"
```
