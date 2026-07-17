# Directory API — resolving OpenAI users to funds and invoicees

This is a **second, optional** way to answer the question the OpenAI integration has
always had to answer: *this person used ChatGPT Edu — whose fund pays, and who gets
the bill?*

The [flat-file method](../README.md) answers it from a static `projects.json` you edit
by hand. That stays exactly as it is — for a small group, an air-gapped setup, or
anyone who'd rather own a file than depend on a service, it's the better tool.

This method answers the same question from **live lookups** against systems the
institution already keeps — the helpdesk's asset/CMDB (where each OpenAI seat is a
"license") and Research Finance (who holds each fund). Pick whichever fits the group.
Same model underneath. Nothing here is written for a specific vendor; the JSON files
are the **contract and a worked example**, not the storage. Every name is from the
Northwinds directory so it reads like a real month.

---

## The model: License → Fund/Org → Principal Invoicee

- **License** — one person's OpenAI seat, tracked by the helpdesk. Each license names
  exactly **one** fund/org, because OpenAI's usage export carries no project or tag to
  split a person's usage by. One user, one fund. That's OpenAI's ceiling, not our choice.
- **Fund/Org** — the account the seat charges to: a department fund, a sponsored award,
  a gift.
- **Principal Invoicee** — the person(s) who hold the fund and get the bill.

That last term is the load-bearing one. **"PI" here means *Principal Invoicee*, not
*Principal Investigator.*** Sometimes they're the same human — a research PI whose
students charge to her award. Often not — a department head covering his faculty's AI
use isn't anyone's "investigator," but he's squarely the invoicee. Generalizing the P
and the I lets one field carry every case, and lets the **fund**, not the user, decide
who pays. **Users are never invoiced by OpenChargeback. Only Principal Invoicees are.**

---

## The flows — two lookups in, two things out

```
   OpenAI usage export (per user, per month)
                    │
                    ▼
  ┌──────────────────────────────────────────────────────────┐
  │  OpenChargeback import (in the converter)                 │
  │                                                            │
  │   for each user in the export:                            │
  │     (1) username ─► fund_org      ── directory API        │  ◄── helpdesk / CMDB
  │         (miss ─► master_fund_org — never empty)           │
  │     (2) fund_org ─► invoicee(s)   ── fund API             │  ◄── research finance
  │                                                            │
  │   aggregate by fund_org, itemize by user                  │
  └──────────────────────────────────────────────────────────┘
             │                                    │
             ▼                                    ▼
   INVOICE → Principal Invoicee(s)      SHOWBACK → back to the CMDB
   one PDF per fund/org,                one line per user, that user's
   itemized by each user on it,         OWN usage only (never a bill)
   forwardable to a funder
```

**(1) and (2) are the inbound lookups** that replace hand-editing a file. `(1)` is the
license → fund/org call (helpdesk); it **never answers empty** — an unrecognized user
resolves to the `master_fund_org` (see below). `(2)` is fund → invoicee (finance).

**The invoice** is the existing OpenChargeback statement path: **one PDF per fund/org**,
itemized by every user who charged to it, delivered to that fund's Principal Invoicee(s).
Per fund/org — not per PI — precisely so a PI holding three grants gets three separate,
self-contained PDFs, each forwardable to that grant's funder with an annual report.

**The showback** is the per-user piece: at the end of import, OpenChargeback writes
**one line per user, showing only that user's own usage**, handed back for the CMDB to
attach to the license's notes timeline. Each month adds a line like
`gildas.rensby@northwinds.edu — 2026-01 — 300 credits — $15.00`. Because a user can see
their own license, that's where they see their own month — a showback next to their
seat, no bill. A license timeline shows **only its own holder's usage — never a rollup,
not even for a PI.** Rensby's line is Rensby's 300 credits; the dept's aggregate shows
up on his *invoice*, not on anyone's license. Sample:
[`user-usage-feedback.example.csv`](user-usage-feedback.example.csv).

---

## The two cases, in Northwinds names

**Department-covered faculty/staff.** Dr. Gildas Rensby (CS head), Nim Catchpole (his
finance admin), and Vesla Thorbin (a lecturer) all charge to `110200-11045`, the CS
operating fund. Its Principal Invoicees are Rensby and Catchpole. One dept PDF,
itemized by the three of them, sent to both invoicees. Thorbin never sees a bill; she
sees her own 500-credit line on her license.

**Grad students under a research PI.** Pell Wickstrand, Doss Emberly, and Fain Hallowbry
are in Dr. Yev Transom's ML lab, all charging `210431-11045`, his NSF award. Transom
gets **one** PDF — his own usage plus his three students', itemized by name — forwardable
to NSF. The students are invoiced by nobody; each sees only their own line back in the
CMDB. Dr. Mirk Nonanda's systems group (gift fund) and Dr. Myrna Selwick's chemistry lab
(a second department) round it out.

---

## The master fund/org — one hop, in the API

A charge must always land on a real code. So the license API never answers empty: any
username it doesn't recognize resolves to the configured **`master_fund_org`**
(`110000-10000` in the example, held by Research Finance — Pomeline Natterjack). In the
sample month, Nix Prothero used ChatGPT but isn't in the directory yet; his usage lands
on the master fund, flagged `routed_to_master` on his showback line (with no license to
name him, the converter echoes his email's local part, `nix.prothero`, as the username),
and Natterjack journals it to the right place and prompts the helpdesk to map the license.

This is deliberately **one hop, not a chain.** We considered walking
fund → dept → college → central, gated on a fund's status — and cut it, because it's
theater: the converter has no way to know whether a *live* fund can actually take a
charge. That's only knowable when finance posts the journal, and even an "active" fund
can be overdrawn or restricted. So we don't route on postability. We guarantee a real
code; overdrafts and mis-postings are finance's to re-home downstream, the way they
always have been.

**Known limitation (accepted): no time dimension.** The lookup returns the fund/org
that's current when billing runs, and it takes the whole month. A mid-month reassignment
isn't pro-rated — the new code gets everything. There's no "what was it on the 12th"
query, so we don't build for one; finance re-homes anything that lands wrong.

---

## Subsidies

A subsidy (e.g. "the Provost covers the first $500/fund/year of AI") is expressed the
same way, and the machinery already exists in the converter. A subsidized charge of `$C`
with `$S` covered becomes **two FOCUS rows**:

- the **PI row** — `ListCost = C`, `BilledCost = C − S` (the subsidy shows as a discount),
  charged to the PI's fund;
- the **subsidy row** — `ListCost = BilledCost = S`, charged to the subsidy fund.

They partition the same usage: `(C − S) + S = C`, reconciling to the cent because
OpenChargeback rounds once at the atom grain (which includes fund_org) — a usage split
across two funds is just two atoms of one charge.

**The subsidy rollup is per fund/org — not per user, not per usage.** The subsidy cap is
per fund/org, so its consumption rolls up the same way: the subsidy owner's statement
shows one line per subsidized fund ("covered $500 of Transom's grant against its cap"),
not a line per student and certainly not per API call. Who ran up the usage is on that
PI's own fund invoice, one level down; the per-event trail is in the forensic close
package if a funder ever wants to drill in.

---

## Files in this folder

| File | The interface it stands in for | Owner |
|------|-------------------------------|-------|
| `API-SPEC.md` | **The build spec** — hand this to whoever implements the endpoints | Helpdesk + Finance |
| `directory.example.json` | **Lookup (1)** — license → fund/org, `master_fund_org` on a miss | Helpdesk / CMDB |
| `fund-orgs.example.json` | **Lookup (2)** — fund/org → Principal Invoicee(s) | Research Finance |
| `user-usage-feedback.example.csv` | **Showback** — per-user monthly usage, one line per user | OpenChargeback → CMDB |

The two `*.json` files are API **response shapes** (served live, not stored as files);
the `.csv` is what OpenChargeback **emits**. `fund_org` is the join key across all three.

### Mapping your CMDB to lookup (1)

| Directory field | Typical CMDB / asset field |
|-----------------|----------------------------|
| `username` | the login / AD account on the license CI (the join key) |
| `email` | the seat's OpenAI email |
| `fund_org` | the fund/org attribute on the license CI |
| `role` | faculty / staff / lecturer / grad_student — informational |
| `master_fund_org` | one global default the API returns when it doesn't recognize a user |

---

## Running it

The OpenChargeback side is built into the converter: it calls both lookups during the
conversion and emits the showback at the end. Each lookup flag takes a **file path or
an `http(s)` URL** — the worked examples in this folder run as-is:

```bash
python ../convert-openai-usage-to-focus-v2.py \
  --input openai-usage-2026-01.csv \
  --pricing ../pricing.json \
  --directory directory.example.json \
  --fund-orgs fund-orgs.example.json \
  --subsidies ../subsidies.json
```

Point `--directory` and `--fund-orgs` at the live endpoints instead of files once the
helpdesk and finance stand them up; the JSON shape is the same either way. URL sources
send `Authorization: Bearer <token>` when `OCB_DIRECTORY_API_TOKEN` is set in the
environment (an env var, not a flag, so the secret stays out of `ps` and shell
history). [`API-SPEC.md`](API-SPEC.md) is the build-ready spec for the two endpoints
and the showback capture — field tables, failure semantics, and an acceptance test. Out come two
files: the FOCUS CSV for `openchargeback ingest`, and the showback —
`user-usage-feedback_<YYYY-MM>.csv` — for the helpdesk to load into the CMDB.
`--subsidies` is optional and uses the same two-row mechanism as the flat method; in
directory mode the cap is tracked **per fund/org**, matching the rollup rule above.

Omitting `--directory`/`--fund-orgs` runs the flat `projects.json` method exactly as
before — nothing about it changed.

`tests/test_openai_converter.py` runs the converter against the example files in this
folder, so the contract and the code can't drift apart without a test noticing.
