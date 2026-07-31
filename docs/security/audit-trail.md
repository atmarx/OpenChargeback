# Audit Trail

OpenChargeback maintains audit trails for compliance and troubleshooting.

## Audit Sources

### 1. Application Logs

Structured logs capture every action the application takes.  See
[Logging](../operations/logging.md) for **configuration** — formats, log
levels, file output, and forwarding to a remote syslog collector.  **This page
is the canonical list of event names**; `tests/test_audit_events.py` fails the
build if the code and this document disagree.

Audit events are emitted by `openchargeback.audit` as structured log lines.  Event
names are dotted, in the form `{event_type}.{action}` (e.g. `import.completed`,
`period.closed`).  Every event carries its event-specific fields plus a `user`
field where applicable (defaulting to `system` for CLI/unattended operations).

### 2. Database Tables

| Table | Audit Purpose |
|-------|---------------|
| `imports` | What was imported, when, into which period |
| `statements` | When statements were generated and sent |
| `email_logs` | Email delivery tracking (who sent, to whom, status) |
| `journal_exports` | Journal export history (format, row count, who exported) |
| `review_logs` | Charge approval/rejection history |
| `billing_periods` | Period status changes (closed/reopened/finalized, by whom) |

### 3. File System

Default paths (configurable under `output:` in config.yaml):

| Location | Audit Purpose |
|----------|---------------|
| `instance/output/pdfs/` | Generated statements (timestamped) |
| `instance/output/journals/` | Exported journals (timestamped) |
| `instance/output/emails/` | Email content (dev mode) |
| `instance/output/archive/` | Retained originals of uploaded source files (feeds the close package) |

## Auditable Events

These are the events actually emitted by `openchargeback.audit`:

### Data Import Events

| Event | Logged Data |
|-------|-------------|
| `import.completed` | filename, source, period, row_count, total_cost, flagged_count, user |

### Export Events

| Event | Logged Data |
|-------|-------------|
| `export.journal` | period, format, row_count, total_cost, include_flagged, user |
| `export.close_package` | period, filename, sha256, user |

### Review Events

| Event | Logged Data |
|-------|-------------|
| `charge.approved` | charge_id, period, pi_email, amount, note, user |
| `charge.rejected` | charge_id, period, pi_email, amount, reason, user |
| `charge.bulk_approved` | period, count, total_amount, user |

### Statement and Email Events

| Event | Logged Data |
|-------|-------------|
| `statement.generated` | period, pi_email, total_cost, charge_count, pdf_path |
| `statement.sent` | period, pi_email, total_cost, user |
| `email.success` | recipient, subject, status |
| `email.error` | recipient, subject, status, error |
| `email.dev_mode` | recipient, subject, status |

### Period Management Events

| Event | Logged Data |
|-------|-------------|
| `period.created` | period, user |
| `period.closed` | period, total_cost, charge_count, user |
| `period.reopened` | period, reason, user |
| `period.finalized` | period, total_cost, statement_count, user |

### User Management Events

| Event | Logged Data |
|-------|-------------|
| `user.created` | username, email, role, created_by |
| `user.updated` | username, changes, user |
| `user.deleted` | username, user |
| `user.password_reset` | username, user |
| `user.password_changed` | username |

### Authentication Events

| Event | Logged Data |
|-------|-------------|
| `auth.login` | username, role, method, source_ip, user |
| `auth.login_failed` | username, reason, source_ip, user |
| `auth.logout` | username, source_ip, user |
| `auth.session_invalidated` | username, reason, source_ip, user |
| `auth.password_change_failed` | username, reason, user |

`method` records which credential store answered: `database`, `config`, or
`recovery`.  A **recovery login bypasses the database entirely** and is the
single authentication event most worth alerting on.

`source_ip` is the peer address the application can see.  Behind a reverse
proxy that is the proxy's address — OCB does not trust `X-Forwarded-For`,
since any client can set it.  Treat the proxy's logs as authoritative for the
real client address.

### Settings Events

| Event | Logged Data |
|-------|-------------|
| `settings.changed` | setting, detail, user |
| `settings.data_reset` | tables, user |

`settings.data_reset` is destructive and dev-mode only.  It should never appear
in a production index.

### Not Emitted

The following are **not** emitted, for structural reasons rather than as a
backlog item.  Do not build compliance reporting on them:

- **Session expiry.**  An expired session cookie is rejected by the session
  middleware before the application sees the request, so there is no moment at
  which OCB could observe it.  `auth.session_invalidated` is a different event
  — a still-valid session whose user has since been deleted.  True session
  expiry has to come from the proxy or SSO layer.
- **A separate "import started" / "charges flagged" event.**  Flag counts ride
  on `import.completed` instead.

## Database Audit Tables

Column names below match the real schema (`src/openchargeback/db/tables.py`).

### imports Table

```sql
SELECT
    id,
    source_id,
    filename,
    billing_period_id,
    row_count,
    flagged_rows,
    total_cost,
    imported_at
FROM imports
WHERE imported_at > '2025-01-01'
ORDER BY imported_at DESC;
```

### journal_exports Table

```sql
SELECT
    billing_period_id,
    format,
    include_flagged,
    row_count,
    total_cost,
    exported_at,
    exported_by,
    filename
FROM journal_exports
ORDER BY exported_at DESC;
```

### review_logs Table

```sql
SELECT
    charge_id,
    action,  -- 'approved' or 'rejected'
    performed_by,
    performed_at,
    note
FROM review_logs
WHERE performed_at > '2025-01-01'
ORDER BY performed_at DESC;
```

### billing_periods Table

Includes who closed/finalized each period and any notes:

```sql
SELECT
    period,
    status,
    closed_at,
    closed_by,
    finalized_at,
    finalized_by,
    notes
FROM billing_periods
WHERE status = 'finalized';
```

## Log Queries

### Recent Errors

```bash
grep "level=ERROR" openchargeback.log | tail -20
```

### Import History

```bash
grep "import.completed" openchargeback.log | grep "period=2025-01"
```

### Email Delivery Issues

```bash
grep "email.error" openchargeback.log
```

## Splunk Queries

For Splunk-indexed logs:

```spl
# All activity by user
index=openchargeback user="admin@example.edu"
| table _time event_type action

# Import summary by period
index=openchargeback event_type="import" action="completed"
| stats sum(row_count) as rows, sum(total_cost) as cost by period

# Review activity
index=openchargeback event_type="charge" action IN ("approved", "rejected")
| timechart count by action
```

## Compliance Considerations

### Financial Audits

For financial audits, provide:
1. Import logs showing data sources
2. Review logs showing approval workflow
3. Statement generation records
4. Journal export files
5. The period close package (hashed archive of all of the above)

```sql
-- Comprehensive audit report for period
SELECT
    c.id as charge_id,
    c.billed_cost,
    c.pi_email,
    c.fund_org,
    CASE WHEN c.needs_review THEN 'flagged' ELSE 'auto-approved' END as review_status,
    rl.action as review_action,
    rl.performed_by as reviewed_by,
    rl.performed_at as reviewed_at
FROM charges c
JOIN billing_periods bp ON c.billing_period_id = bp.id
LEFT JOIN review_logs rl ON c.id = rl.charge_id
WHERE bp.period = '2025-01'
ORDER BY c.id;
```

Note: charges are not linked row-by-row to a specific import record; use the
`imports` table (filtered by `billing_period_id` and `source_id`) to show which
files fed a period.

### Data Retention

- Logs should be retained per institutional policy
- Database tables maintain full history
- Finalized periods are permanent records

## Best Practices

### Log Retention

```bash
# Keep logs for at least 2 years
# Configure logrotate appropriately
/path/to/logs/*.log {
    yearly
    rotate 2
    compress
    dateext
}
```

### Regular Reviews

- Monthly: Review import activity
- Quarterly: Full audit trail review
- Annually: Compliance audit

### Backup Audit Data

Audit data should be included in regular backups:
- Database (includes all audit tables)
- Log files (separate backup recommended)
- Generated files (statements, journals, close packages)
