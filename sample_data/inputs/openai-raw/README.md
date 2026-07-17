# The OpenAI month, from vendor export to close package

The other sample inputs in `sample_data/inputs/` are already FOCUS files. This
folder holds the step **before** that for the 2026-01 OpenAI month: the raw
vendor export and the converter run that turns it into one — so the repo shows
the whole lifecycle end to end:

```
openai-usage-export_2026-01.csv          the raw ChatGPT Edu billing export
        │
        ▼   convert-openai-usage-to-focus-v2.py  (directory-API mode)
        │     lookup (1): license -> fund/org      ─ docs/…/directory-api/directory.example.json
        │     lookup (2): fund/org -> invoicee(s)  ─ docs/…/directory-api/fund-orgs.example.json
        │     subsidy:    Provost $500/fund/FY     ─ subsidies.json (this folder)
        │
        ├──►  ../openai-tokens_2026-01.csv         the FOCUS file OpenChargeback ingests
        └──►  user-usage-feedback_2026-01.csv      the per-user showback, back to the CMDB
```

From there, `scripts/generate-sample-outputs.sh` runs the month through the same
lifecycle as every other sample: ingest → review/approve → PDF statements +
emails → GL journal → period close → forensic close package (zip + pdf).

## The cast and the month

Twelve ChatGPT Edu seats from the fictional Northwinds directory, $0.05/credit,
$805.00 total — the same month as the worked example in
[`docs/integrations/openai-tokens/directory-api/`](../../../docs/integrations/openai-tokens/directory-api/README.md).
The showback emitted here is **byte-identical** to the committed contract
example (and a test pins the contract copy to converter output).

What the month demonstrates, on purpose:

- **The two invoicing cases.** CS department seats (Rensby, Catchpole, Thorbin)
  roll up to the dept head's fund; Dr. Transom's grad students (Wickstrand,
  Emberly, Hallowbry) roll up to his NSF award — itemized by user, invoiced to
  the Principal Invoicee, never to the users.
- **The master-fund catch.** `nix.prothero@northwinds.edu` has no license in
  the directory. His $40.00 lands on the master fund (Natterjack, Research
  Finance), flagged `routed_to_master` on his showback line.
- **The subsidy, three ways.** The Provost's AI Access Initiative covers the
  first $500/fund/FY. Small funds are fully covered (their GL lines bill $0.00
  and are therefore omitted from the journal — a zero moves nothing). Transom's
  fund blows through its cap mid-month: $500.00 covered, $80.00 billed — and
  the cap crosses **mid-charge** on Emberly's Jan 26 run ($35.00 list splits
  into $32.50 subsidy + $2.50 billed), so the partial two-row split is in the
  data, not just the docs.
- **The per-fund rollup.** Natterjack's statement shows the subsidy fund
  consuming $725.00 as one line per subsidized fund ($500.00 of Transom's
  grant, $47.50 of CS, …) — never per user, never per usage event.

The month reconciles by construction: $80.00 billed + $725.00 subsidized =
$805.00 used, to the cent, at every layer — FOCUS file, statements, GL,
close package.

## Regenerating

Don't edit `../openai-tokens_2026-01.csv` or `user-usage-feedback_2026-01.csv`
by hand — they are converter output. Edit the raw export (or the configs) and
rerun:

```bash
./scripts/generate-sample-outputs.sh
```

Subsidy state is deliberately throwaway per run (fresh fiscal year each
regeneration), so the outputs are deterministic.
