# Data Protection

This document describes how OpenChargeback handles and protects data.

## Data Classification

### Sensitive Data

| Data Type | Storage | Protection |
|-----------|---------|------------|
| User passwords | Database | bcrypt hash (never stored plaintext) |
| Session tokens | Server memory | Cryptographic random, short-lived |
| SMTP credentials | Config file | Environment variable substitution |
| Secret key | Config file | Environment variable substitution |
| PI email addresses | Database | Application access control |
| Fund/org codes | Database | Application access control |

### Billing Data

| Data Type | Storage | Sensitivity |
|-----------|---------|-------------|
| Charge amounts | Database | Internal (aggregated in statements) |
| Resource IDs | Database | Internal (cloud identifiers) |
| Service names | Database | Low (generic categories) |
| Project IDs | Database | Internal (may correlate to grants) |

## Data at Rest

### Database

SQLite database file (`instance/billing.db`):
- No built-in encryption
- File system permissions are primary control
- Recommend: Restrict to application user only

```bash
chmod 600 instance/billing.db
chown appuser:appgroup instance/billing.db
```

### Configuration Files

`instance/config.yaml` may contain:
- Password hashes (safe to store)
- References to environment variables for secrets

Never store plaintext secrets in config files. Use environment variables:

```yaml
# Good
smtp:
  password: ${SMTP_PASSWORD}
web:
  secret_key: ${WEB_SECRET_KEY}

# Bad - don't do this
smtp:
  password: "my-actual-password"
```

### Generated Files

| Directory | Contents | Sensitivity |
|-----------|----------|-------------|
| `output/pdfs/` | PDF statements | Contains PI charges - restrict access |
| `output/journals/` | Accounting exports | Contains billing data |
| `output/emails/` | Email files (dev mode) | Contains PI contact info |
| `logs/` | Application logs | May contain emails, amounts |

Recommend restricting access:
```bash
chmod 700 instance/output/
chmod 600 instance/output/*/*
```

## Data in Transit

### HTTPS

OpenChargeback doesn't handle TLS directly. Use a reverse proxy:

```nginx
server {
    listen 443 ssl;
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://127.0.0.1:8000;
    }
}
```

### SMTP

Email delivery uses TLS when configured:

```yaml
smtp:
  use_tls: true  # Enable STARTTLS
```

## Data Retention

### Automatic

No automatic data deletion. All data is retained until manually removed.

### Manual Cleanup

```sql
-- Remove old charges (example: keep last 2 years)
DELETE FROM charges WHERE billing_period < '2023-01';

-- Remove old statements
DELETE FROM statements WHERE period < '2023-01';

-- Remove old import logs
DELETE FROM imports WHERE imported_at < '2023-01-01';
```

### Finalized Periods

Finalized periods are immutable records. They cannot be modified or deleted through the application. Direct database access is required for removal (not recommended for audit compliance).

## Privacy Considerations

### PI Data

- Email addresses are stored for statement delivery
- Names may be stored for display purposes
- Fund/org codes may be institution-sensitive

### Minimization

Only required data is stored:
- No cloud credentials stored
- No full billing details beyond what's in FOCUS format
- No personal data beyond PI attribution

### Access Control

- Role-based permissions limit who sees what
- Viewer role provides read-only access
- All access is authenticated

## Backup Security

### Backup Contents

Database backups contain all application data including:
- User accounts (with hashed passwords)
- All billing data
- Import history

### Backup Protection

```bash
# Encrypt backups
gpg --symmetric --cipher-algo AES256 billing.db
# Creates billing.db.gpg

# Decrypt when needed
gpg --decrypt billing.db.gpg > billing.db
```

### Backup Retention

Consider regulatory requirements:
- Financial records: Often 7 years
- Grant-related: Duration of grant + closure period
- GDPR: Minimize retention, delete when no longer needed

## Incident Response

### Suspected Breach

1. **Contain**: Disable affected accounts, rotate secrets
2. **Assess**: Review audit logs for unauthorized access
3. **Notify**: Follow institutional incident response procedures
4. **Remediate**: Patch vulnerability, restore from clean backup if needed
5. **Document**: Record incident details and response

### Key Rotation

If `web.secret_key` is compromised:

1. Generate new secret:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

2. Update environment variable or config

3. Restart application (all sessions will be invalidated)

### Password Reset

If password hashes are exposed:

1. Force password reset for all users
2. Notify affected users
3. Review for unauthorized access in audit logs
