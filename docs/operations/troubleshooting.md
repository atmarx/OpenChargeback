# Troubleshooting

Common issues and their solutions.

## Import Issues

### "No charges found for period"

**Symptoms**: Import succeeds but no charges appear for the period.

**Causes**:
1. Period doesn't exist yet
2. Charges have different `BillingPeriodStart` dates
3. All charges were flagged for review

**Solutions**:
```bash
# Check if period exists
openchargeback periods list

# Verify data has correct dates
head -5 billing.csv | cut -d, -f1  # Check BillingPeriodStart column

# Check for flagged charges
openchargeback review list --period 2025-01
```

### "Period is finalized"

**Symptoms**: Import rejected with "period is finalized" error.

**Cause**: Period was finalized and cannot accept new data.

**Solutions**:
1. Import to a different (open) period
2. If finalization was premature, there's no built-in undo (by design)
3. For emergencies, direct database modification is possible but not recommended

### "Missing pi_email tag"

**Symptoms**: Import summary reports many "Missing pi_email tag" errors; those rows are skipped (not imported, not flagged).

**Cause**: Source data doesn't include PI email in tags, or tag name doesn't match config.

**Solutions**:
1. Check tag mapping in config:
   ```yaml
   tag_mapping:
     pi_email: "your_actual_tag_name"
   ```
2. Verify source data includes the tag in JSON format:
   ```json
   {"pi_email": "smith@example.edu", ...}
   ```

---

## Statement Issues

### PDF Generation Fails

**Symptoms**: Error during statement generation, usually mentioning WeasyPrint.

**Causes**:
1. Missing WeasyPrint dependencies
2. Font issues
3. Invalid template HTML

**Solutions**:

Install WeasyPrint dependencies:
```bash
# Debian/Ubuntu
apt install libpango-1.0-0 libpangocairo-1.0-0

# Arch
pacman -S pango

# RHEL/Fedora
dnf install pango
```

Check fonts:
```bash
fc-list | grep -i arial  # Check if common fonts exist
```

Validate template:
```bash
# Try generating with default template
mv templates/statement.html templates/statement.html.bak
openchargeback generate --period 2025-01 --dry-run
```

### "Flagged charges not appearing in statements"

**Expected behavior**: Flagged charges are excluded by design.

**Solution**: Review and approve flagged charges before generating statements:
```bash
openchargeback review list --period 2025-01
openchargeback review approve --period 2025-01  # After verification
```

---

## Email Issues

### Emails Not Sending

**Symptoms**: `generate --send` completes but no emails received.

**Checks**:
1. Is `dev_mode: true`? Emails go to files instead of SMTP.
2. Are SMTP settings correct?
3. Check logs for SMTP errors.

```bash
# Check if dev_mode
grep dev_mode instance/config.yaml

# Check email output directory (dev mode)
ls instance/output/emails/

# Check logs
grep "email" instance/logs/openchargeback.log
```

### SMTP Connection Errors

**Symptoms**: `SMTP timeout` or `Connection refused` in logs.

**Solutions**:
1. Verify SMTP host and port:
   ```bash
   # Test connection
   nc -zv smtp.example.edu 587
   ```
2. Check TLS settings match server requirements
3. Verify credentials:
   ```bash
   # Test with environment variables
   echo $SMTP_USER
   echo $SMTP_PASSWORD  # Should be set
   ```

---

## Web Interface Issues

### Login Fails

**Symptoms**: "Invalid credentials" with correct password.

**Causes**:
1. Password hash mismatch
2. User not in config or database
3. Session expired

**Solutions**:

Regenerate password hash:
```python
import bcrypt
print(bcrypt.hashpw(b"your-password", bcrypt.gensalt()).decode())
```

Check user exists in config:
```yaml
web:
  users:
    admin:
      email: admin@example.edu
      password_hash: "$2b$12$..."
```

### Session Keeps Expiring

**Cause**: `session_lifetime_hours` too short.

**Solution**:
```yaml
web:
  session_lifetime_hours: 8  # Increase as needed
```

### Static Files Not Loading

**Symptoms**: Page loads but no CSS/JS styling.

**Causes**:
1. Running behind proxy without proper path forwarding
2. Incorrect Docker volume mount

**Solutions**:

For reverse proxy, ensure static paths are forwarded:
```nginx
location /static/ {
    proxy_pass http://localhost:8000/static/;
}
```

---

## Database Issues

### "Database is locked"

**Cause**: Multiple processes accessing SQLite simultaneously.

**Solutions**:
1. Ensure only one instance of the application is running
2. Check for zombie processes:
   ```bash
   ps aux | grep openchargeback
   ```
3. Restart the application:
   ```bash
   docker compose restart
   # or
   systemctl restart openchargeback
   ```

### Schema Mismatch

**Symptoms**: Errors about missing columns or tables after upgrade.

**Solution**: For development, reset the database:
```bash
rm instance/billing.db
openchargeback serve  # Recreates schema
```

For production, migrations would be needed (not currently implemented).

---

## Journal Export Issues

### "Fund/org doesn't parse"

**Cause**: `fund_org_regex` doesn't match your fund/org format.

**Solution**: Test and fix your regex:
```python
import re
pattern = r"^(?P<orgn>[^-]+)-(?P<fund>.+)$"
match = re.match(pattern, "YOUR-FUNDORG-HERE")
if match:
    print(match.groupdict())
else:
    print("No match - adjust pattern")
```

### Journal Doesn't Balance

**Cause**: Missing credit fund_org for one or more sources.

**Solution**: Ensure all sources have `fund_org` configured:
```yaml
imports:
  known_sources:
    - name: AWS
      fund_org: IT-CLOUD-AWS  # Required for credits
```

---

## Performance Issues

### Slow Imports

Rough shape on ordinary hardware: a 15 MB FOCUS export is about 72,000 rows and
imports in **10-20 seconds**. Roughly half is parsing the CSV, half is the
upsert. If you are seeing minutes rather than seconds, the cause is usually one
of these:

1. **Many small imports rather than one large one.** Each import re-opens the
   database and re-parses headers. One file per source per month is the
   intended shape.
2. **Database on network storage.** The upsert reads before it writes, so an
   NFS-mounted `billing.db` pays the round trip twice per row. Keep it on
   local disk.
3. **A period with a very large history.** The natural-key lookup is indexed,
   but the index still grows. Finalize and archive old periods.

Note that SQLite itself is rarely the constraint — on a 72k-row import the
database accounts for a couple of seconds of the total.

---

### Large import returns a server error

**Symptoms**: Uploading a large CSV (10 MB or more) shows *"Server error (502)"*
or *"Server error (504)"* in the import dialog rather than an import summary.
Smaller files from the same export work fine.

**Cause**: The response never came back as JSON, which means the app did not
answer — the proxy in front of it did. Either the upload was larger than the
proxy's body limit, or the request outlived a timeout somewhere in the chain.

**Solutions**:
1. Check whether the file is over the configured ceiling. Past
   `imports.max_upload_mb` (64 MB by default) the app answers with a `413` and
   a message naming the limit — if you are getting that message rather than a
   `502`, the bound is working and the file genuinely needs splitting.
2. Check the reverse proxy's body limit. It must be at least
   `imports.max_upload_mb`, or the proxy refuses the upload before the app ever
   sees it. See [Configuration → Import bounds](../getting-started/configuration.md#import-bounds).
3. Split the export by month or by source. This is usually the better answer
   than raising limits: each import becomes its own audit-trail entry, and a
   bad file costs you one source to redo rather than the whole month.
4. Import from the CLI instead, which has no HTTP timeout in the way:
   ```bash
   openchargeback ingest path/to/large-export.csv --source AWS --period 2026-08
   ```
   The CLI runs the same ingester and writes the same audit-trail entry and
   archived input, so a month imported this way is not second-class.

### Slow Web Interface

1. Check database size:
   ```bash
   ls -lh instance/billing.db
   ```
2. For very large databases, consider archiving old periods
3. Vacuum the database:
   ```bash
   sqlite3 instance/billing.db "VACUUM;"
   ```

---

## Getting Help

If these solutions don't resolve your issue:

1. Check the logs: `instance/logs/openchargeback.log`
2. Enable DEBUG logging: `logging.level: DEBUG`
3. File an issue with:
   - Error message and stack trace
   - Relevant configuration (redact secrets)
   - Steps to reproduce
