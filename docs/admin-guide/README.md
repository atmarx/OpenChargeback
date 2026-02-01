# Admin Guide

This section covers administrative tasks for billing coordinators and IT staff who manage OpenChargeback.

## Contents

1. [Billing Workflow](billing-workflow.md) - End-to-end monthly billing process
2. [Review Process](review-process.md) - Handling flagged charges
3. [Journal Export](journal-export.md) - Exporting to accounting systems
4. [Templates](templates.md) - Customizing PDF, email, and journal templates

## Monthly Checklist

```
□ Import all source data (AWS, Azure, HPC, etc.)
□ Review and resolve flagged charges
□ Generate statements (dry run first)
□ Send statements to PIs
□ Export journal entries
□ Send journal to accounting
□ Close period
□ Finalize period (after accounting confirms receipt)
```

## Quick Reference

| Task | CLI | Web UI |
|------|-----|--------|
| Import data | `openchargeback ingest` | Dashboard → Import |
| Review charges | `openchargeback review list` | Review Queue |
| Generate statements | `openchargeback generate` | Statements → Generate |
| Export journal | `openchargeback export-journal` | Journal Export |
| Close period | `openchargeback periods close` | Periods → Close |
