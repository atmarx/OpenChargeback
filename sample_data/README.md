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
│   ├── storage_2025-01.csv
│   ├── openai-tokens_2026-01.csv   # converter OUTPUT — see openai-raw/
│   └── openai-raw/   # the step before FOCUS: raw OpenAI export, converter
│       │             # configs, and the emitted per-user showback
│       ├── openai-usage-export_2026-01.csv
│       ├── subsidies.json
│       ├── user-usage-feedback_2026-01.csv
│       └── README.md
│
└── outputs/          # Generated from inputs via generate-sample-outputs.sh
    ├── pdfs/         # Statement PDFs (one per PI/project)
    ├── journals/     # GL journal export CSV
    ├── emails/       # Email HTML files (dev mode output)
    └── packages/     # Forensic close packages — each month x {zip, pdf}
```

The 2025 months are hand-authored FOCUS files. The 2026-01 month starts one
step earlier: a raw OpenAI usage export converted via the directory API
(license → fund/org → Principal Invoicee), with a Provost subsidy split and a
per-user showback back to the CMDB — the whole chain from vendor export to
close package. See [inputs/openai-raw/README.md](inputs/openai-raw/README.md).

## Regenerating Outputs

```bash
./scripts/generate-sample-outputs.sh
```

This resets the database, ingests all input files, generates statements with emails, exports the journal, and copies everything to `outputs/`.

## Fictional Data

All names, email addresses, project titles, and grant numbers are entirely fictional—names like "Zorp Blinkman" and "Quib Flannister" were chosen to be obviously fake. The `@example.edu` domain is reserved for documentation per [RFC 2606](https://www.rfc-editor.org/rfc/rfc2606.html). The 2026-01 OpenAI month uses the fictional Northwinds University cast (`@northwinds.edu`) shared with the directory-API contract examples in `docs/integrations/openai-tokens/directory-api/`.
