# Upgrade Guides

Guides for upgrading OpenChargeback and its dependencies.

## Contents

| Guide | Description |
|-------|-------------|
| [Dependencies](dependencies.md) | Upgrading Python packages, vendored JavaScript, and Python versions |
| [Versioning](versioning.md) | Incrementing the project version for releases |

## Quick Reference

### Upgrade Dependencies

```bash
source .venv/bin/activate
pip-compile --generate-hashes --upgrade --output-file=requirements.lock pyproject.toml
pip install -r requirements.lock --require-hashes
python -m pytest tests/ -v
```

### Release New Version

```bash
# Update version in all three locations (see versioning.md)
# Then commit and tag:
git add -A
git commit -m "Bump version to X.Y.Z"
git tag vX.Y.Z
git push origin main --tags
```
