# Version Management

This project follows [Semantic Versioning](https://semver.org/) (SemVer):

- **MAJOR** (X.0.0): Breaking changes to CLI, config format, or database schema
- **MINOR** (0.X.0): New features, backward-compatible
- **PATCH** (0.0.X): Bug fixes, backward-compatible

## Version Locations

The version is defined in **three places** and must be updated together:

| File | Line | Format |
|------|------|--------|
| `pyproject.toml` | `version = "X.Y.Z"` | Package metadata |
| `src/focus_billing/__init__.py` | `__version__ = "X.Y.Z"` | Runtime version |
| `src/focus_billing/web/app.py` | `version="X.Y.Z"` | API/OpenAPI spec |

## Incrementing the Version

### 1. Update All Three Files

```bash
# Example: bumping from 0.2.0 to 0.3.0

# pyproject.toml
sed -i 's/version = "0.2.0"/version = "0.3.0"/' pyproject.toml

# __init__.py
sed -i 's/__version__ = "0.2.0"/__version__ = "0.3.0"/' src/focus_billing/__init__.py

# app.py
sed -i 's/version="0.2.0"/version="0.3.0"/' src/focus_billing/web/app.py
```

Or manually edit each file.

### 2. Verify Changes

```bash
grep -r "0.3.0" --include="*.py" --include="*.toml" .
```

Should show exactly three matches (plus any in `.venv/` which can be ignored).

### 3. Regenerate SBOM

```bash
source .venv/bin/activate
cyclonedx-py environment --output-format json -o sbom.json
```

### 4. Run Tests

```bash
python -m pytest tests/ -v
```

### 5. Commit and Tag

```bash
git add pyproject.toml src/focus_billing/__init__.py src/focus_billing/web/app.py sbom.json
git commit -m "Bump version to 0.3.0"
git tag v0.3.0
git push origin main --tags
```

## Checking Current Version

### From CLI

```bash
source .venv/bin/activate
python -c "from focus_billing import __version__; print(__version__)"
```

### From Package Metadata

```bash
pip show focus-billing | grep Version
```

### From Files

```bash
grep 'version' pyproject.toml | head -1
grep '__version__' src/focus_billing/__init__.py
grep 'version=' src/focus_billing/web/app.py
```

## Pre-release Versions

For pre-release versions, use suffixes:

- `0.3.0-alpha.1` - Alpha release
- `0.3.0-beta.1` - Beta release
- `0.3.0-rc.1` - Release candidate

Note: PEP 440 uses different syntax (`0.3.0a1`, `0.3.0b1`, `0.3.0rc1`), so for Python packaging, prefer:

```
0.3.0a1   # Alpha
0.3.0b1   # Beta
0.3.0rc1  # Release candidate
```

## Future Improvement

Consider using a tool like `bump2version` or `hatch version` to automate version updates across all files:

```bash
# With bump2version (not currently configured)
bump2version minor  # 0.2.0 -> 0.3.0
bump2version patch  # 0.2.0 -> 0.2.1
```
