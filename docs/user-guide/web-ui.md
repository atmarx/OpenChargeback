# Web UI Guide

The web interface provides a dashboard for managing billing periods, reviewing charges, and generating statements without using the CLI.

## Starting the Web Server

```bash
# From CLI
openchargeback web

# Or with Docker
docker compose -f docker/docker-compose.yml up -d
```

The default URL is `http://localhost:8000`.

---

## Features

### Dashboard

The dashboard shows an overview of the current billing period:

- **Period stats**: Total charges, flagged items, generated statements
- **Quick actions**: Import data, review charges, generate statements
- **Recent activity**: Latest imports and generated statements

### Periods

Manage billing period lifecycle:

- **Create**: Open a new billing period
- **Close**: Lock period for statement generation (can be reopened)
- **Reopen**: Unlock a closed period to accept more imports
- **Finalize**: Permanently lock period (irreversible)

Period statuses are color-coded:
- **Green** - Open (accepting imports)
- **Yellow** - Closed (ready for statements)
- **Gray** - Finalized (locked)

### Charges

Browse and search all imported charges:

- Filter by period, source, PI, project, or fund/org
- View charge details including tags
- Export filtered results to CSV

### Review Queue

Approve or reject flagged charges:

- Bulk approve/reject with checkboxes
- Filter by flag reason
- View charge context before decision
- Charges remain flagged until action taken

Flagged charges are **excluded from statements** until approved.

### Statements

Generate PDF statements and send emails:

1. Select a period
2. Preview statement list
3. Generate PDFs (saved to `output/pdfs/`)
4. Send emails to PIs

In `dev_mode`, emails are saved to files instead of sent via SMTP.

### Journal Export

Export accounting data in multiple formats:

| Format | Description |
|--------|-------------|
| **Standard Detail** | One row per charge |
| **Summary by PI/Project** | Aggregated totals |
| **General Ledger** | Debit/credit format |
| **Custom Template** | Your Jinja2 template |

See [Admin Guide: Journal Export](../admin-guide/journal-export.md) for details.

### Imports

Upload FOCUS CSV files via drag-and-drop:

1. Click "Import" or drag files onto the page
2. Auto-detection fills in source and period
3. Adjust values if needed
4. Click "Upload" to import

Multiple files can be uploaded at once, each with independent settings.

### Settings

Configure review patterns and view system info:

- **Review patterns**: Regex patterns for auto-flagging
- **Fund/org patterns**: Valid fund/org format validation
- **System info**: Version, database path, config status

---

## Navigation

The sidebar provides quick access to all sections. The top bar shows:

- Current user
- Notifications (flagged charges, etc.)
- Logout

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `?` | Show keyboard shortcuts |
| `/` | Focus search |
| `g d` | Go to Dashboard |
| `g p` | Go to Periods |
| `g c` | Go to Charges |
| `g r` | Go to Review |

---

## User Roles

| Role | Permissions |
|------|-------------|
| **admin** | Full access, manage users, finalize periods |
| **reviewer** | Import, review, generate statements |
| **viewer** | Read-only access |

---

## Dev Mode

When `dev_mode: true` in config:

- Emails are saved to `output/emails/` instead of sent
- Additional debugging options available in Settings
- Database reset options enabled

---

## Mobile Support

The interface is responsive but optimized for desktop use. For best experience, use a screen width of 1024px or wider.
