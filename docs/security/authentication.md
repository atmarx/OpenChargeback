# Authentication

OpenChargeback uses session-based authentication with bcrypt password hashing.

## User Sources

Users can be defined in two places:

### 1. Configuration File Users

Defined in `config.yaml`, primarily for bootstrap and recovery:

```yaml
web:
  users:
    admin:
      email: admin@example.edu
      display_name: Admin User
      password_hash: "$2b$12$..."
      role: admin
      recovery: true  # Always uses config auth, bypasses DB
```

**Recovery mode**: When `recovery: true`, this user always authenticates against the config file, even if a database user with the same email exists. Use for emergency lockout recovery.

### 2. Database Users

Managed through the web interface (admin only). Stored in the `users` table with:
- Email (unique identifier)
- Display name
- bcrypt password hash
- Role
- Created/updated timestamps

Database users override config users (unless config user has `recovery: true`).

## Password Security

### Hashing

Passwords are hashed using bcrypt with automatic salt generation:

```python
import bcrypt
hash = bcrypt.hashpw(b"password", bcrypt.gensalt()).decode()
# Result: $2b$12$Fxu99zxFh4plt3a2FDyEnuFyg2Co/osXmQGGYw.HFl0/Id6V.Uvey
```

The `$2b$12$` prefix indicates:
- `$2b$` - bcrypt algorithm
- `$12$` - cost factor (2^12 iterations)

### Password Requirements

Configurable policy for database users:

```yaml
web:
  password_requirements:
    min_length: 8
    require_uppercase: false
    require_lowercase: false
    require_numbers: false
    require_special_chars: false
```

When requirements are tightened, existing users are prompted to update their passwords on next login if they don't meet the new policy.

## Session Management

### Session Lifecycle

1. User submits credentials
2. Server validates password against bcrypt hash
3. Session cookie is set with session ID
4. Session stored server-side (in-memory or database)
5. Cookie validated on each request
6. Session expires after `session_lifetime_hours`

### Configuration

```yaml
web:
  session_lifetime_hours: 8  # Session timeout
  secret_key: ${WEB_SECRET_KEY}  # For session signing
```

### Session Security

- Sessions are server-side (not JWT)
- Cookie is HTTP-only (not accessible to JavaScript)
- Cookie is Secure when served over HTTPS
- SameSite attribute prevents CSRF
- Session ID is cryptographically random

## Roles and Permissions

| Role | Permissions |
|------|-------------|
| `admin` | Full access: manage users, finalize periods, all operations |
| `reviewer` | Import data, review charges, generate statements, export journals |
| `viewer` | Read-only access to all data |

### Permission Matrix

| Action | admin | reviewer | viewer |
|--------|-------|----------|--------|
| View dashboard | ✓ | ✓ | ✓ |
| View charges | ✓ | ✓ | ✓ |
| Import data | ✓ | ✓ | ✗ |
| Review charges | ✓ | ✓ | ✗ |
| Generate statements | ✓ | ✓ | ✗ |
| Export journals | ✓ | ✓ | ✗ |
| Close periods | ✓ | ✓ | ✗ |
| Finalize periods | ✓ | ✗ | ✗ |
| Manage users | ✓ | ✗ | ✗ |
| Change settings | ✓ | ✗ | ✗ |

## Authentication Flow

```
┌─────────────────┐
│   Login Form    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│  Check Config   │────▶│  Recovery User? │
│     Users       │     │    (bypass DB)  │
└────────┬────────┘     └────────┬────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│  Check Database │     │ Validate bcrypt │
│     Users       │     │     Hash        │
└────────┬────────┘     └────────┬────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│ Validate bcrypt │────▶│ Create Session  │
│     Hash        │     │   Set Cookie    │
└─────────────────┘     └─────────────────┘
```

## Best Practices

### For Administrators

1. **Use strong passwords**: Minimum 12 characters, mix of types
2. **Rotate secret key**: If compromised, all sessions are invalidated
3. **Limit admin accounts**: Only those who need full access
4. **Review login logs**: Monitor for failed attempts
5. **Use recovery user sparingly**: Only for lockout recovery

### For Users

1. **Use unique passwords**: Don't reuse from other systems
2. **Log out when done**: Especially on shared computers
3. **Report suspicious activity**: Unexpected password prompts, etc.

## Lockout Recovery

If all admin accounts are locked out:

1. Add a recovery user to `config.yaml`:
   ```yaml
   web:
     users:
       recovery:
         email: recovery@example.edu
         display_name: Recovery Admin
         password_hash: "$2b$12$..."  # Generate fresh hash
         role: admin
         recovery: true
   ```

2. Restart the application

3. Log in with recovery account

4. Reset passwords or create new admin users

5. Remove or disable recovery user when done
