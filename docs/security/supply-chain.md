# Supply Chain Security

This document describes OpenChargeback's approach to software supply chain security, including dependency management, vulnerability scanning, and software bill of materials (SBOM).

## Overview

| Control | Implementation |
|---------|----------------|
| **Dependency Pinning** | `requirements.lock` with SHA256 hashes |
| **SBOM** | CycloneDX 1.6 format (`sbom.json`) |
| **Vulnerability Scanning** | pip-audit, Dependabot/Renovate |
| **Vendored Dependencies** | htmx.min.js served locally |

## Software Bill of Materials (SBOM)

An SBOM is a machine-readable inventory of all software components. OpenChargeback provides an SBOM in [CycloneDX 1.6](https://cyclonedx.org/) format.

### Location

```
sbom.json
```

### Regenerating the SBOM

The SBOM should be regenerated whenever dependencies change:

```bash
source .venv/bin/activate
pip install cyclonedx-bom
cyclonedx-py environment --output-format json -o sbom.json
```

This is included in the [version release process](../upgrades/versioning.md).

### Using the SBOM

Security teams can use the SBOM to:
- Track all transitive dependencies
- Cross-reference against vulnerability databases (NVD, OSV)
- Meet compliance requirements (NIST, executive orders)
- Integrate with security scanning tools

## Dependency Pinning

All Python dependencies are pinned with cryptographic hashes to prevent:
- Dependency confusion attacks
- Compromised package versions
- Non-reproducible builds

### Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Dependency bounds (e.g., `pandas>=2.0,<3`) |
| `requirements.lock` | Exact versions + SHA256 hashes |

### Installation with Hash Verification

```bash
pip install -r requirements.lock --require-hashes
```

pip will refuse to install if hashes don't match, preventing tampered packages.

### Updating Dependencies

See [Dependency Upgrade Guide](../upgrades/dependencies.md) for detailed procedures.

```bash
# Check for updates
pip list --outdated

# Regenerate lock file
pip-compile --generate-hashes --upgrade --output-file=requirements.lock pyproject.toml

# Verify and test
pip install -r requirements.lock --require-hashes
python -m pytest tests/ -v
```

## Vulnerability Scanning

### Manual Scanning with pip-audit

```bash
pip install pip-audit
pip-audit
```

This checks installed packages against the Python Packaging Advisory Database and OSV.

### Automated Scanning

CI pipelines should include vulnerability scanning:

**GitHub Actions** (via Dependabot or workflow):
```yaml
- name: Security audit
  run: |
    pip install pip-audit
    pip-audit --require-hashes -r requirements.lock
```

**Azure DevOps**:
```yaml
- script: |
    pip install pip-audit
    pip-audit --require-hashes -r requirements.lock
  displayName: 'Security audit'
```

### Automated Dependency Updates

Configure [Renovate](https://docs.renovatebot.com/) or [Dependabot](https://docs.github.com/en/code-security/dependabot) to:
- Monitor for new versions
- Open PRs for updates
- Flag security vulnerabilities

See `renovate.json` in the repository root for configuration.

## Vendored JavaScript

htmx is served from a local copy rather than a CDN to:
- Avoid external runtime dependencies
- Ensure availability during network issues
- Prevent CDN compromise attacks

Location: `src/openchargeback/web/static/js/htmx.min.js`

Update procedure: See [Dependency Upgrade Guide](../upgrades/dependencies.md#upgrading-htmx-vendored-javascript).

## Security Checklist for Dependencies

### Before Adding a New Dependency

- [ ] Is the package actively maintained?
- [ ] Does it have known vulnerabilities? (`pip-audit`)
- [ ] Is it from a trusted source (PyPI, verified publisher)?
- [ ] What transitive dependencies does it bring?
- [ ] Is there a simpler alternative in the standard library?

### Regular Maintenance

- [ ] Run `pip-audit` weekly or on each release
- [ ] Review Renovate/Dependabot PRs promptly
- [ ] Regenerate SBOM on dependency changes
- [ ] Update `requirements.lock` monthly or on security advisories

## Incident Response

If a dependency vulnerability is discovered:

1. **Assess impact**: Does the vulnerable code path affect OpenChargeback?
2. **Check for patches**: Is an updated version available?
3. **Upgrade immediately**:
   ```bash
   pip-compile --generate-hashes --upgrade-package <package> -o requirements.lock pyproject.toml
   ```
4. **Test thoroughly**: Run full test suite
5. **Deploy**: Release patch version if in production
6. **Document**: Note the CVE and remediation in release notes

## Compliance

The SBOM and dependency controls support compliance with:

- **NIST SP 800-218** (Secure Software Development Framework)
- **Executive Order 14028** (Improving the Nation's Cybersecurity)
- **ISO 27001** (Information Security Management)
- **SOC 2** (Security controls)

For audit purposes, provide:
- `sbom.json` - Complete dependency inventory
- `requirements.lock` - Pinned versions with hashes
- CI logs showing vulnerability scans pass
