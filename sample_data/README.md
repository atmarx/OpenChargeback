# Sample Data

This directory contains example FOCUS-format billing data for testing and demonstration.

## Structure

```
sample_data/
├── inputs/           # Source CSV files (FOCUS format)
│   ├── aws_2025-01.csv
│   ├── azure_2025-01.csv
│   ├── hpc_2025-01.csv
│   ├── it_storage_2025-01.csv
│   └── storage_2025-01.csv
│
└── outputs/          # Generated from inputs via generate-sample-outputs.sh
    ├── pdfs/         # Statement PDFs (one per PI/project)
    ├── journals/     # GL journal export CSV
    └── emails/       # Email HTML files (dev mode output)
```

## Regenerating Outputs

```bash
./scripts/generate-sample-outputs.sh
```

This resets the database, ingests all input files, generates statements with emails, exports the journal, and copies everything to `outputs/`.

## Fictional Data

All names, email addresses, project titles, and grant numbers are entirely fictional—names like "Zorp Blinkman" and "Quib Flannister" were chosen to be obviously fake. The `@example.edu` domain is reserved for documentation per [RFC 2606](https://www.rfc-editor.org/rfc/rfc2606.html).
