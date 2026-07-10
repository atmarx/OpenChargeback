# Getting Started

This section covers installing and configuring OpenChargeback for first-time use.

## Contents

1. [Installation](installation.md) - System requirements, installation methods
2. [Deployment Planning](deployment-planning.md) - The institutional decisions to make *before* you configure
3. [Configuration](configuration.md) - Setting up `config.yaml`

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/your-org/openchargeback.git
cd openchargeback
python -m venv .venv
source .venv/bin/activate
pip install -e .

# 2. Create configuration
mkdir -p instance
cp config.example.yaml instance/config.yaml

# The example ships no session key and no working password (on purpose). For a
# quick local look, edit instance/config.yaml: set `dev_mode: true` (this
# auto-generates a session key), then set the admin password_hash to your own:
python -c "import bcrypt; print(bcrypt.hashpw(b'changeme', bcrypt.gensalt()).decode())"
# (paste the output as the admin user's password_hash)

# 3. Start the web interface
openchargeback serve

# 4. Open http://localhost:8000 and log in as username `admin` (the YAML key),
#    not the email address, with the password you hashed above.
```

For a production deployment (`dev_mode: false`) the app refuses to start until
you set a strong `web.secret_key` and replace the example admin hash — see
[Configuration](configuration.md).

## Next Steps

After installation:
- **CLI users**: See [CLI Reference](../user-guide/cli.md)
- **Web users**: See [Web UI Guide](../user-guide/web-ui.md)
- **Administrators**: See [Admin Guide](../admin-guide/)
