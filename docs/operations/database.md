# Database

OpenChargeback uses SQLite for data storage. This guide covers database management and maintenance.

## Location

Default: `instance/billing.db`

Configure in `config.yaml`:
```yaml
database:
  path: ./instance/billing.db
```

## Schema

| Table | Purpose |
|-------|---------|
| `billing_periods` | Period tracking with status and audit trail |
| `sources` | Data source metadata (aws, azure, hpc) |
| `charges` | Raw charge data from FOCUS files |
| `statements` | Generated statement records |
| `imports` | Import log tracking what was loaded |
| `email_logs` | Email delivery audit trail |
| `users` | Database-managed users (not config users) |
| `review_logs` | Charge review action audit trail |

## Backup

### Manual Backup

```bash
# Simple file copy (while app is stopped)
cp instance/billing.db instance/billing.db.backup

# With timestamp
cp instance/billing.db "instance/billing_$(date +%Y%m%d_%H%M%S).db"
```

### Automated Backup

```bash
#!/bin/bash
# backup-db.sh - Run via cron
BACKUP_DIR="/backups/openchargeback"
DATE=$(date +%Y%m%d)

cp instance/billing.db "$BACKUP_DIR/billing_$DATE.db"

# Keep last 30 days
find "$BACKUP_DIR" -name "billing_*.db" -mtime +30 -delete
```

Add to crontab:
```
0 2 * * * /path/to/backup-db.sh
```

## Recovery

### From Backup

```bash
# Stop the application first
systemctl stop openchargeback

# Restore
cp /backups/billing_20250101.db instance/billing.db

# Start application
systemctl start openchargeback
```

### Schema Reset

If the schema is corrupted or needs reset:

```bash
# Delete and let app recreate
rm instance/billing.db
focus-billing web  # Will create new database
```

> **Warning**: This deletes all data. Use only in development or after backup.

## Direct Access

For debugging or manual queries:

```bash
sqlite3 instance/billing.db
```

Common queries:

```sql
-- Count charges by period
SELECT billing_period, COUNT(*) FROM charges GROUP BY billing_period;

-- View flagged charges
SELECT * FROM charges WHERE flagged = 1;

-- Check import history
SELECT * FROM imports ORDER BY imported_at DESC LIMIT 10;

-- View period statuses
SELECT * FROM billing_periods;
```

## Data Reset (Dev Mode Only)

When `dev_mode: true`, you can selectively reset data via the Settings page in the web UI.

Or manually:

```sql
-- Clear all charges
DELETE FROM charges;

-- Clear imports
DELETE FROM imports;

-- Reset periods (careful - may affect charges via foreign keys)
DELETE FROM billing_periods;

-- Clear statements
DELETE FROM statements;
```

## Performance

For large deployments (>100k charges):

1. **Index optimization**: SQLite creates indexes automatically; no manual tuning needed
2. **Vacuum**: Run periodically to reclaim space:
   ```bash
   sqlite3 instance/billing.db "VACUUM;"
   ```
3. **Consider PostgreSQL**: For very large deployments, PostgreSQL may be more appropriate (not currently supported, but designed for easy migration)

## Migration

If you need to migrate to a new database:

```bash
# Export
sqlite3 instance/billing.db ".dump" > dump.sql

# Import to new database
sqlite3 new_billing.db < dump.sql
```
