# Security

This section documents OpenChargeback's security model for auditors, security teams, and administrators.

## Contents

1. [Authentication](authentication.md) - User authentication and session management
2. [Data Protection](data-protection.md) - Data handling, encryption, and privacy
3. [Audit Trail](audit-trail.md) - Activity logging and compliance
4. [Supply Chain](supply-chain.md) - SBOM, dependency pinning, vulnerability scanning

## Security Summary

| Area | Implementation |
|------|----------------|
| **Authentication** | bcrypt password hashing, session-based auth |
| **Session Management** | Configurable timeout, secure cookies |
| **Data at Rest** | SQLite database, file-based storage |
| **Data in Transit** | HTTPS (via reverse proxy) |
| **Audit Logging** | Structured logs for all significant events |
| **Access Control** | Role-based (admin, reviewer, viewer) |
| **Supply Chain** | SBOM, pinned dependencies with hashes, pip-audit |

## Quick Security Checklist

### Production Deployment

- [ ] Use HTTPS via reverse proxy (nginx, Caddy, etc.)
- [ ] Set strong `web.secret_key` (32+ random bytes)
- [ ] Use environment variables for secrets (not in config file)
- [ ] Configure `session_lifetime_hours` appropriately
- [ ] Enable log file output for audit trail
- [ ] Restrict file permissions on `instance/` directory
- [ ] Use strong passwords for all users
- [ ] Set `dev_mode: false`

### Network Security

- [ ] Bind to localhost only (`host: 127.0.0.1`) if using reverse proxy
- [ ] Configure firewall rules
- [ ] Use TLS 1.2+ for SMTP connections
- [ ] Consider VPN or IP restrictions for admin access

## Threat Model

### Assumed Threats

| Threat | Mitigation |
|--------|------------|
| Credential theft | bcrypt hashing, session timeout |
| Session hijacking | Secure cookies, HTTPS |
| SQL injection | Parameterized queries (SQLAlchemy) |
| XSS | Template escaping (Jinja2) |
| CSRF | Session-based auth, SameSite cookies |
| Unauthorized access | Role-based permissions |

### Out of Scope

- Physical server access
- Compromised administrator accounts
- Denial of service attacks

## Reporting Security Issues

If you discover a security vulnerability, please report it privately to the maintainers rather than opening a public issue.
