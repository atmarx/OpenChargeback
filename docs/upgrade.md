# Dependency Upgrade Guide

This project uses locked dependencies to ensure reproducible builds. This guide explains how to upgrade dependencies safely.

## Files Involved

| File | Purpose |
|------|---------|
| `pyproject.toml` | Source of truth for dependency requirements (with major version bounds) |
| `requirements.lock` | Pinned versions with SHA256 hashes for all packages |
| `src/focus_billing/web/static/js/htmx.min.js` | Vendored htmx library (v1.9.10) |

## Upgrading Python Dependencies

### 1. Check for Available Updates

```bash
source .venv/bin/activate
pip list --outdated
```

### 2. Update the Lock File

To upgrade all packages within their allowed bounds:

```bash
pip-compile --generate-hashes --upgrade --output-file=requirements.lock pyproject.toml
```

To upgrade a specific package:

```bash
pip-compile --generate-hashes --upgrade-package pandas --output-file=requirements.lock pyproject.toml
```

### 3. Install Updated Dependencies

```bash
pip install -r requirements.lock --require-hashes
```

### 4. Run Tests

```bash
python -m pytest tests/ -v
```

### 5. Commit Changes

If tests pass, commit the updated lock file:

```bash
git add requirements.lock
git commit -m "chore: upgrade dependencies"
```

## Upgrading Major Versions

Major version upgrades require changing the bounds in `pyproject.toml`.

### Example: Upgrading pandas from 2.x to 3.x

1. Edit `pyproject.toml`:
   ```diff
   - "pandas>=2.0.0,<3",
   + "pandas>=3.0.0,<4",
   ```

2. Regenerate the lock file:
   ```bash
   pip-compile --generate-hashes --output-file=requirements.lock pyproject.toml
   ```

3. Install and test thoroughly:
   ```bash
   pip install -r requirements.lock --require-hashes
   python -m pytest tests/ -v
   ```

4. Check for breaking changes in the package's changelog before committing.

## Upgrading htmx (Vendored JavaScript)

htmx is served locally from `src/focus_billing/web/static/js/htmx.min.js`.

### Steps to Upgrade

1. Check current version:
   ```bash
   head -1 src/focus_billing/web/static/js/htmx.min.js
   ```

2. Download new version (check https://htmx.org for latest):
   ```bash
   curl -o src/focus_billing/web/static/js/htmx.min.js \
     https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js
   ```

3. Test the web interface manually:
   - Login/logout
   - File upload modal
   - Review page (htmx-powered approve/reject)
   - Any other htmx-powered features

4. Commit the change:
   ```bash
   git add src/focus_billing/web/static/js/htmx.min.js
   git commit -m "chore: upgrade htmx to 1.9.12"
   ```

## Security Updates

For security patches, upgrade immediately:

```bash
# Check for known vulnerabilities
pip-audit

# Upgrade the affected package
pip-compile --generate-hashes --upgrade-package <package-name> --output-file=requirements.lock pyproject.toml

# Install and test
pip install -r requirements.lock --require-hashes
python -m pytest tests/ -v
```

## Fresh Install from Lock File

To install exact pinned versions (e.g., on a new machine or in CI):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock --require-hashes
pip install -e .
```

## Troubleshooting

### Hash Mismatch Errors

If you see hash verification errors, the package may have been republished (rare but happens). Regenerate the lock file:

```bash
pip-compile --generate-hashes --output-file=requirements.lock pyproject.toml
```

### Conflicting Dependencies

If pip-compile fails with conflicts, check which packages have incompatible requirements:

```bash
pip-compile --verbose pyproject.toml
```

You may need to adjust bounds in `pyproject.toml` to resolve conflicts.

### Platform-Specific Packages

The lock file is generated for the current platform. If deploying to a different OS/architecture, regenerate on that platform or use `--allow-unsafe` with caution.
