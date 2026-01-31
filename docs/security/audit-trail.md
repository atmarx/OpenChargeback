# Audit Trail

OpenChargeback maintains comprehensive audit trails for compliance and troubleshooting.

## Audit Sources

### 1. Application Logs

Structured logs capture all significant events. See [Logging](../operations/logging.md) for configuration.

### 2. Database Tables

| Table | Audit Purpose |
|-------|---------------|
| `imports` | Who imported what, when |
| `statements` | When statements were generated |
| `email_logs` | Email delivery tracking |
| `review_logs` | Charge approval/rejection history |
| `billing_periods` | Period status changes with notes |

### 3. File System

| Location | Audit Purpose |
|----------|---------------|
| `output/pdfs/` | Generated statements (timestamped) |
| `output/journals/` | Exported journals (timestamped) |
| `output/emails/` | Email content (dev mode) |

## Auditable Events

### Authentication Events

| Event | Logged Data |
|-------|-------------|
| `login_success` | User email, timestamp, IP (if configured) |
| `login_failed` | Attempted email, timestamp, failure reason |
| `logout` | User email, timestamp |
| `session_expired` | User email, timestamp |

### Data Import Events

| Event | Logged Data |
|-------|-------------|
| `import_started` | User, source, filename, timestamp |
| `import_completed` | Charge count, total amount, period |
| `import_failed` | Error message, partial data if any |
| `charges_flagged` | Count, reasons |

### Review Events

| Event | Logged Data |
|-------|-------------|
| `charge_approved` | Charge ID, user, timestamp |
| `charge_rejected` | Charge ID, user, timestamp, reason |
| `bulk_approve` | Period, count, user |

### Statement Events

| Event | Logged Data |
|-------|-------------|
| `statement_generated` | PI, period, filename, user |
| `email_sent` | Recipient, period, timestamp |
| `email_failed` | Recipient, error message |

### Period Management Events

| Event | Logged Data |
|-------|-------------|
| `period_created` | Period, user |
| `period_closed` | Period, user |
| `period_reopened` | Period, user |
| `period_finalized` | Period, user, notes |

### Administrative Events

| Event | Logged Data |
|-------|-------------|
| `user_created` | Email, role, created_by |
| `user_modified` | Email, changes, modified_by |
| `settings_changed` | Setting name, old/new values, user |

## Database Audit Tables

### imports Table

```sql
SELECT
    id,
    source_id,
    filename,
    billing_period,
    charge_count,
    total_cost,
    imported_at,
    imported_by
FROM imports
WHERE imported_at > '2025-01-01'
ORDER BY imported_at DESC;
```

### review_logs Table

```sql
SELECT
    charge_id,
    action,  -- 'approved' or 'rejected'
    user_email,
    timestamp,
    notes
FROM review_logs
WHERE timestamp > '2025-01-01'
ORDER BY timestamp DESC;
```

### billing_periods Table

Includes finalization notes:

```sql
SELECT
    period,
    status,
    finalized_at,
    finalized_by,
    finalization_notes
FROM billing_periods
WHERE status = 'finalized';
```

## Log Queries

### Recent Errors

```bash
grep "level=ERROR" focus-billing.log | tail -20
```

### Failed Logins (Past 24 Hours)

```bash
grep "login_failed" focus-billing.log | grep "$(date -d 'yesterday' +%Y-%m-%d)"
```

### Import History

```bash
grep "import_completed" focus-billing.log | grep "period=2025-01"
```

### Email Delivery Issues

```bash
grep "email_failed" focus-billing.log
```

## Splunk Queries

For Splunk-indexed logs:

```spl
# All activity by user
index=openchargeback user="admin@example.edu"
| table _time event action details

# Import summary by period
index=openchargeback event="import_completed"
| stats sum(charge_count) as charges, sum(total_cost) as cost by period

# Failed authentications
index=openchargeback event="login_failed"
| stats count by email
| sort -count

# Review activity
index=openchargeback event IN ("charge_approved", "charge_rejected")
| timechart count by event
```

## Compliance Considerations

### Financial Audits

For financial audits, provide:
1. Import logs showing data sources
2. Review logs showing approval workflow
3. Statement generation records
4. Journal export files

```sql
-- Comprehensive audit report for period
SELECT
    c.id as charge_id,
    c.billed_cost,
    c.pi_email,
    c.fund_org,
    i.filename as source_file,
    i.imported_at,
    CASE WHEN c.flagged THEN 'flagged' ELSE 'auto-approved' END as review_status,
    rl.action as review_action,
    rl.user_email as reviewed_by,
    rl.timestamp as reviewed_at
FROM charges c
LEFT JOIN imports i ON c.import_id = i.id
LEFT JOIN review_logs rl ON c.id = rl.charge_id
WHERE c.billing_period = '2025-01'
ORDER BY c.id;
```

### Data Retention

- Logs should be retained per institutional policy
- Database tables maintain full history
- Finalized periods are permanent records

### Access Audits

- All authenticated access goes through session system
- Login attempts are logged regardless of success
- No anonymous access to any data

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

- Weekly: Review failed login attempts
- Monthly: Review import activity
- Quarterly: Full audit trail review
- Annually: Compliance audit

### Backup Audit Data

Audit data should be included in regular backups:
- Database (includes all audit tables)
- Log files (separate backup recommended)
- Generated files (statements, journals)
