# Getting Started

This section covers installing and configuring OpenChargeback for first-time use.

## Contents

1. [Installation](installation.md) - System requirements, installation methods
2. [Configuration](configuration.md) - Setting up `config.yaml`

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/your-org/openchargeback.git
cd openchargeback
python -m venv .venv
source .venv/bin/activate
pip install -e .

# 2. Create configuration
cp config.example.yaml instance/config.yaml
# Edit instance/config.yaml with your settings

# 3. Start the web interface
focus-billing web

# 4. Open http://localhost:8000 and log in
```

## Next Steps

After installation:
- **CLI users**: See [CLI Reference](../user-guide/cli.md)
- **Web users**: See [Web UI Guide](../user-guide/web-ui.md)
- **Administrators**: See [Admin Guide](../admin-guide/)
