# Directory API — build spec (v1.0)

**Audience:** the team exposing the license lookup from the CMDB (helpdesk),
and whoever owns the fund/org → invoicee data (research finance — may be served
through the same gateway). Vendor-neutral: nothing here assumes TDX or any
other product, only that you can serve two JSON documents over HTTPS and
import one CSV a month.

**What OpenChargeback needs from you, in total:**

| # | Interface | Direction | Owner | Format |
|---|-----------|-----------|-------|--------|
| 1 | `GET <base>/openai-licenses` | OCB pulls, once per billing run | Helpdesk / CMDB | JSON |
| 2 | `GET <base>/fund-orgs` | OCB pulls, once per billing run | Research Finance | JSON |
| 3 | `user-usage-feedback_<YYYY-MM>.csv` | OCB produces, once per month | OCB → CMDB import | CSV |

That's the whole build. Billing runs monthly; each run makes **one** call to
each endpoint. The example files in this folder are **normative samples** of
all three interfaces — `directory.example.json`, `fund-orgs.example.json`, and
`user-usage-feedback.example.csv` (the last is byte-identical real converter
output, pinned by an automated test).

---

## General requirements (both endpoints)

- **HTTPS, JSON, UTF-8.** Response `Content-Type: application/json`.
- **Auth:** a static bearer token. OpenChargeback sends
  `Authorization: Bearer <token>`, read from the `OCB_DIRECTORY_API_TOKEN`
  environment variable at conversion time. If your gateway needs something
  fancier than a long-lived token, front it with something that doesn't —
  the billing client will not do OAuth dances.
- **Full dumps, not per-user queries.** Resolution happens per user *inside*
  the converter; transport is one document. Do **not** build per-user GETs,
  date-range queries, or history endpoints for v1 — nothing will call them.
- **No time dimension (accepted limitation).** Each dump reflects assignments
  *as of the moment billing runs*, and the current fund/org takes the whole
  month. Mid-month reassignments are not pro-rated; finance re-homes anything
  that lands wrong. Don't build effective-dating for us.
- **Failure aborts, nothing partial.** Any non-200, a timeout (30 s), or a
  schema violation (e.g. missing `master_fund_org`) aborts the entire import.
  We never bill a month against a half-answered directory.
- **Forward compatibility:** unknown extra fields are ignored. Add fields
  freely; renaming or removing the ones below is a coordinated change (bump
  `schema_version`).
- **Sizing:** hundreds to a few thousand records, monthly cadence, idempotent
  reads. This is the least demanding API client you will ever meet.

---

## Endpoint 1 — the license lookup (helpdesk)

`GET <base>/openai-licenses` → the full set of ChatGPT Edu seats.

```json
{
  "schema_version": "1.0",
  "as_of": "2026-01-31",
  "master_fund_org": "110000-10000",
  "licenses": [
    {
      "username": "grensby",
      "email": "gildas.rensby@northwinds.edu",
      "display_name": "Dr. Gildas Rensby",
      "department": "Computer Science",
      "role": "faculty",
      "fund_org": "110200-11045"
    }
  ]
}
```

| Field | Required | Meaning |
|-------|----------|---------|
| `schema_version` | yes | `"1.0"` |
| `as_of` | recommended | when the dump was cut (audit breadcrumb) |
| `master_fund_org` | **yes, non-empty** | the catch-all fund/org. **Must** exist in endpoint 2 with ≥ 1 invoicee, or the import aborts — this is the code that guarantees no charge is ever orphaned |
| `licenses[].email` | **yes, unique** | the seat's OpenAI email — **the join key** to the usage export |
| `licenses[].username` | yes | the CMDB login on the license CI — keys the showback line back to the license timeline |
| `licenses[].fund_org` | no | the fund/org that pays for this seat. Empty or missing → the charge routes to `master_fund_org` and the user's showback line is flagged `routed_to_master` |
| `display_name`, `department`, `role` | no | informational only; nothing routes on them |

**Resolution rules (implemented in the converter — for your reference, don't
build them):** usage email not in `licenses[]` → master fund, username echoed
as the email's local part. License present but no `fund_org` → master fund.
`fund_org` present but unknown to endpoint 2 (or has no invoicees) → master
fund, with a warning. A license that deliberately points *at* the master fund
is a normal charge, not a fallback.

---

## Endpoint 2 — the fund/org registry (finance)

`GET <base>/fund-orgs` → every billable fund/org and who gets its bill.

```json
{
  "schema_version": "1.0",
  "as_of": "2026-01-31",
  "fund_orgs": [
    {
      "fund_org": "210431-11045",
      "name": "NSF #2431109 — Transom (Foundation Models for Scientific Reasoning)",
      "type": "sponsored_project",
      "principal_invoicees": [
        { "email": "yev.transom@northwinds.edu", "name": "Dr. Yev Transom", "role": "research_pi" }
      ]
    }
  ]
}
```

| Field | Required | Meaning |
|-------|----------|---------|
| `fund_orgs[].fund_org` | **yes, unique** | the code — join key across all three interfaces |
| `fund_orgs[].principal_invoicees` | **yes, ≥ 1 entry** | who holds the fund and gets the bill ("PI" = Principal Invoicee, not necessarily an Investigator). A fund with an empty list is treated as unknown → master + warning |
| `principal_invoicees[].email` | **yes** | first entry is the statement addressee; all entries are delivery recipients |
| `principal_invoicees[].name`, `.role` | no | informational |
| `name`, `type` | no | informational; we do **not** route on `type` or fund status — postability is finance's call at journal time |

Every `fund_org` referenced by a license should exist here; the
`master_fund_org` **must**.

---

## Interface 3 — the showback (what OpenChargeback hands back)

At the end of each import, OCB writes one CSV: **one line per user per month,
that user's OWN usage only.** It's a showback for the license timeline —
never a bill, never a multi-user rollup (rollups live on the invoicee's
statement). Users are never invoiced; this is how they see their own month.

```csv
username,email,period,service,credits,amount_usd,fund_org,status
grensby,gildas.rensby@northwinds.edu,2026-01,OpenAI,300,15.00,110200-11045,charged
nix.prothero,nix.prothero@northwinds.edu,2026-01,OpenAI,800,40.00,110000-10000,routed_to_master
```

| Column | Type | Semantics |
|--------|------|-----------|
| `username` | string | from the license record. **For a user with no license it's the email's local part** — match by `email` if the username doesn't resolve |
| `email` | string | the seat's OpenAI email |
| `period` | `YYYY-MM` | the billing month |
| `service` | string | `OpenAI` |
| `credits` | decimal, ≤ 3 dp | usage credits, trailing zeros trimmed (`300`, `217.535`) |
| `amount_usd` | decimal, 2 dp | **gross (list) usage** — what they used, not what their fund was billed after subsidies |
| `fund_org` | string | where the charge landed (the master fund if routed) |
| `status` | enum | `charged` \| `routed_to_master` |

File facts: header row always present, CRLF line endings, sorted by
(`period`, `username`), deterministic — same inputs, same bytes.

**What to do with it:** attach each line to that license's notes/timeline so
the holder sees their own month next to their seat. A `routed_to_master` line
is your cue to map the license (and finance's cue to journal the already-billed
amount to the right home).

**Delivery, v1:** file handoff — we run the converter, you import the CSV.

**Optional v1.1 — push capture (not yet emitted; say the word and we wire it):**
if you'd rather receive it than import it, expose
`POST <base>/usage-feedback` accepting a JSON array of objects with exactly the
eight fields above, idempotent on (`period`, `username`, `service`) so a rerun
upserts instead of duplicating. Same bearer token. We'd add a
`--showback-post <url>` to the converter; the CSV remains the audit copy either
way.

---

## How OpenChargeback calls it

```bash
export OCB_DIRECTORY_API_TOKEN=…   # from your gateway

python convert-openai-usage-to-focus-v2.py \
  --input openai-usage-2026-01.csv \
  --pricing pricing.json \
  --directory https://cmdb.example.edu/api/openai-licenses \
  --fund-orgs  https://cmdb.example.edu/api/fund-orgs \
  --subsidies subsidies.json
```

Until the endpoints exist, the same flags take file paths — which is exactly
how the worked example in this folder and the automated tests run. Build to
the shapes above and the switch from file to URL is a flag change, nothing
more.

## Acceptance

You're done when this holds: serve the two example JSONs from your endpoints
verbatim, run the converter against the committed sample month
(`sample_data/inputs/openai-raw/openai-usage-export_2026-01.csv`), and the
showback you receive is byte-identical to
[`user-usage-feedback.example.csv`](user-usage-feedback.example.csv) — a $805.00
month, twelve lines, one `routed_to_master`. That file is already pinned to
converter output by `tests/test_openai_converter.py`, so the target can't
drift while you build.
