# Microsoft Azure FOCUS Export Guide

This guide shows you how to feed your Microsoft Azure cloud spend into OpenChargeback. Azure Cost Management can export your monthly cost and usage data **natively in FOCUS format** — the exact format OpenChargeback ingests. That makes Azure the simplest integration we have.

> **Don't panic.** Unlike the [Slurm](../slurm/) or Qumulo guides, **there is no preprocessor to write here.** Azure emits FOCUS 1.0+ on its own. Your whole job is three things: (1) put the right tags on your resources, (2) turn on a monthly FOCUS export, and (3) get that file to OpenChargeback. Most of this is point-and-click in the Azure portal. The [Using AI Assistance](#using-ai-assistance-for-implementation) section at the end can write any automation glue you want.

### Must-Read Sections

Before configuring anything, review these:

1. **[Tagging Your Resources (with Fall-Through)](#tagging-your-resources-with-fall-through)** — How attribution tags get onto your charges, and how a college-level default can fall through to a research group's override
2. **[Exporting the Monthly FOCUS Report](#exporting-the-monthly-focus-report)** — The Cost Management export that produces the file OpenChargeback reads
3. **[Delivering the Export to OpenChargeback](#delivering-the-export-to-openchargeback)** — Options for getting the file from Azure Storage to OCB
4. **[Using AI Assistance](#using-ai-assistance-for-implementation)** — How to use this doc with Copilot to generate any automation glue

Everything else is reference material for edge cases and troubleshooting.

---

## Overview

**Goal**: Get Azure cloud charges, correctly attributed to each PI / project / fund-org, into OpenChargeback every month.

**Data Source**: Azure Cost Management **Exports** — the built-in **Cost and usage details (FOCUS)** dataset.

**Billing Model**: Azure already calculates the costs. OpenChargeback reads them straight from the FOCUS file. You don't compute rates, prorate anything, or build a CSV by hand. The only thing you own is **attribution** — making sure each charge carries the tags that tell OCB whose budget it belongs to.

**No preprocessor needed.** Azure's FOCUS export already matches the columns OCB expects (`BilledCost`, `ListCost`, `ContractedCost`, `EffectiveCost`, `ResourceId`, `ResourceName`, `ServiceName`, `Tags`, the billing/charge period columns, and more). You point OCB at the file and ingest.

> **Account types matter.** FOCUS exports are available for **Enterprise Agreement (EA)**, **Microsoft Customer Agreement (MCA)**, and **Microsoft Partner Agreement (MPA)** accounts. Pay-as-you-go (MOSP) subscriptions don't support FOCUS exports. If you're on a university EA or MCA — which almost every institution is — you're fine.

---

## Tagging Your Resources (with Fall-Through)

This is the part that takes thought. Everything else is configuration.

OpenChargeback attributes each charge using the tags in the FOCUS `Tags` column. You decide the tag **names** — OCB maps them in its config — but you need the **values** to land on every billable charge. The hard part in a real institution is hierarchy: a **college owns an outer scope** (a management group, a subscription, or a resource group), but an individual **research group has its own fund-org** at their level. When the research group sets a tag, it should win. When they leave it blank, the charge should **fall through** to the college's default.

Azure gives you two complementary mechanisms to make that happen. Use both.

### The tags OpenChargeback needs

These come from the canonical [Tag Specification](../TAG-SPECIFICATION.md) — link there, don't memorize this:

| Tag | Status | Example value |
|-----|--------|---------------|
| `pi_email` | **Required** | `martinez.sofia@example.edu` |
| `fund_org` | **Required** | `BIOLOGY-GRANTS-2025` |
| `project_id` | Recommended | `climate-modeling` |
| `cost_center` | Recommended | `CC-12345` |
| `account_code` | Optional | `54100` |
| `end_date` | Optional | `2026-06-30` |
| `reconciliation_end` | Optional | `2026-09-30` |

The **tag key names are your institution's choice.** If your team already uses `PIEmail` and `FundOrg`, keep them — you map them to OCB's internal fields in `config.yaml`:

```yaml
tag_mapping:
  pi_email: "pi_email"        # ← left side is OCB's field, right side is your Azure tag key
  fund_org: "fund_org"
  project_id: "project_id"
  cost_center: "cost_center"
```

### Mechanism 1: Tag Inheritance (the fall-through engine)

Azure Cost Management has a setting called **Tag inheritance**. When enabled, it copies **subscription and resource-group tags onto each child resource's usage records** — the billing rows — so a resource doesn't need its own copy of every tag to be attributed correctly.

This is exactly the fall-through model you want, and the precedence rule is the key fact:

> **By default, if a resource has its own tag with the same key, the resource's tag wins. The inherited (outer-scope) tag only fills in where the resource left it blank.**

That's fall-through. The college sets `fund_org=COLLEGE-OF-SCIENCE-GENERAL` on the subscription; a research group sets `fund_org=BIOLOGY-GRANTS-2025` on their own resource group or resource; the research group's value overrides for their charges, and everything else inherits the college default.

**Important nuances:**

- **Inherited tags are applied to the usage records, not to the resources themselves.** The resources stay untouched; only the billing data gets the tag. That's perfect for chargeback — it means you can attribute charges without modifying anyone's infrastructure.
- The default precedence (resource tag wins) is what you want for fall-through. Azure *does* let you flip it so the inherited tag overrides the resource tag — the option is named **"Use the subscription or resource group tag"** (EA) or **"Use the inherited tag"** (MCA). **Leave it at the default** unless you specifically want the college to override the research groups.
- When a subscription tag and a resource-group tag both exist with the same key, and you've flipped to inherited-wins, the **subscription** tag is used.
- After you enable or change tag inheritance, it takes roughly **8–24 hours** to apply, and it applies to the **current month from the 1st** using the tags as they exist when the setting runs.

**How to turn it on** (Azure portal):

1. Search for **Cost Management** (the green hexagon — *not* "Cost Management + Billing").
2. Select your scope: **EA billing account**, **MCA billing profile**, or a **subscription**.
3. Left menu → **Settings** → **Configuration** (billing account) or **Manage subscription** / **Manage billing profile**.
4. Under **Tag inheritance**, select **Edit**.
5. Check **Automatically apply subscription and resource group tags to new data**.
6. Leave the precedence option at the default (resource tag wins) for fall-through.

> **Permissions:** You need **Cost Management Contributor** on a subscription, **Enterprise Administrator** on an EA billing account, or **Billing profile contributor** on an MCA billing profile to edit this setting.

### Mechanism 2: Azure Policy (require and/or auto-apply tags)

Tag inheritance handles fall-through *in the billing data*. **Azure Policy** is how you make sure the tags actually exist in the first place — either by **requiring** them, or by **auto-applying** them. You choose the enforcement posture; here are the sane options.

**Option A — Require tags (deny or audit).** Block (or just flag) any resource or resource group created without `pi_email` and `fund_org`. There are built-in policy definitions for "Require a tag on resources" and "Require a tag on resource groups." Use the **`deny`** effect for hard enforcement (no tag, no resource) or **`audit`** for a softer posture (resource is created, but shows as non-compliant). The Tag Specification already includes a sample deny policy — see [TAG-SPECIFICATION.md → Azure](../TAG-SPECIFICATION.md#azure).

**Option B — Auto-apply / inherit tags (modify).** Use the **`modify`** effect with `addOrReplace` (or `add`) to stamp a tag onto resources that are missing it, inheriting the value from the parent resource group or subscription. There are built-in definitions like "Inherit a tag from the resource group" and "Inherit a tag from the subscription." Pair this with a **remediation task** to backfill existing resources. This makes the tags real on the resources, which complements (and can substitute for) Cost Management tag inheritance.

**You choose the scope** Azure Policy is assigned at. This is where the college-vs-research-group hierarchy lives:

| Assign policy at... | Good when... |
|---------------------|--------------|
| **Management group** | The college (or central IT) wants one rule across many subscriptions. *Note: see the export caveat below — FOCUS exports don't run at management-group scope, but Policy still does.* |
| **Subscription** | One subscription per college/department; the subscription default is the fall-through value. |
| **Resource group** | A research group manages its own resource groups and sets its own overrides. |
| **Per-resource** | Fine-grained, rarely needed if inheritance is doing its job. |

A common institutional setup:

- **At the management group or subscription** (college level): a `modify`/inherit policy sets `fund_org` to the college's general fund-org, plus a `deny`-or-`audit` policy requiring `pi_email`.
- **At the research group's resource group**: the group sets their own `fund_org` and `pi_email`. Because resource/RG tags win by default, their values override the college default for their charges — fall-through achieved.

> **There is no single "right" enforcement level.** Start soft (`audit` + inheritance) so nothing breaks, watch the OCB review queue for unattributed charges, then tighten to `deny` on the tags you can't live without. OCB itself uses **soft enforcement** — charges with missing tags are flagged for review, not dropped — so you have a safety net either way.

### Quick win: tag a resource group directly

If you're not ready for Policy yet, you can set the fall-through defaults by hand on a resource group, and tag inheritance will carry them down:

```bash
# Conceptual example — college sets the fall-through default on a resource group
az group create \
  --name rg-climate-research \
  --location eastus \
  --tags \
    pi_email=martinez.sofia@example.edu \
    fund_org=BIOLOGY-GRANTS-2025 \
    project_id=climate-modeling \
    cost_center=CC-12345 \
    end_date=2026-06-30
```

Any resource in that group that doesn't set its own `fund_org` inherits `BIOLOGY-GRANTS-2025` on its usage records. A resource that *does* set `fund_org=NSF-ATM-2024` overrides it for its own charges.

---

## Exporting the Monthly FOCUS Report

Once tags are flowing, set up the export. This is the file OpenChargeback reads.

### Create the export

1. In the Azure portal, search for **Cost Management** and open it.
2. Select your **scope** — a **subscription**, **resource group**, **EA enrollment/department**, or **MCA billing account/profile/invoice section**.
   > **Caveat:** **Management group scope is *not* supported for FOCUS exports.** If a college spans several subscriptions, create one FOCUS export per subscription (or export at the EA billing-account / MCA billing-profile scope to capture them all at once).
3. Left menu → **Exports** → **+ Create**.
4. On the **Basics** tab, pick a template or choose **Create your own export**.
5. Set **Type of data** to **Cost and usage details (FOCUS)**.
6. Set **Dataset version** — see [Which FOCUS version](#which-focus-version) below.
7. Set **Frequency** to **Monthly export of last month's costs** (or **...last billing month's costs** for EA/MCA, which aligns to the invoice). This runs once a month and gives you the finalized prior month.
8. On the **Destination** tab:
   - **Storage type**: Azure blob storage (default).
   - Choose the **storage account**, **container**, and **directory** the file lands in. Note these down — you'll point your delivery automation here.
   - **Format**: **CSV**. (Parquet is also offered; OCB ingests CSV.)
   - **Compression**: **None** for the simplest path, or **Gzip** if you want smaller files and your delivery step can unzip.
9. **Review + create.** New exports are enabled by default. The first run can take up to 24 hours.

> **Permissions:** **Owner** or **Contributor** on the scope to create exports. Writing to a storage account behind a firewall needs extra rights at creation time — see the [export tutorial](https://learn.microsoft.com/azure/cost-management-billing/costs/tutorial-improved-exports).

### Where the file lands

Azure writes to a predictable path inside your container:

```
{container}/{directory}/{ExportName}/{YYYYMMDD-YYYYMMDD}/{RunID}/
    part_0_0001.csv      ← the data (may be split into part_0_0002.csv, etc.)
    _manifest.json       ← lists every partition file for that run
```

Two things to know:

- **File partitioning is always on and can't be disabled.** Large months get split into multiple `part_*.csv` files. Each partition has its own header row. To process a full month, read **every** partition listed in `_manifest.json` — don't hardcode `part_0_0001.csv`.
- For **monthly last-month exports**, each month lands in its own dated folder (e.g. `[20260501-20260531]`), so months don't clobber each other.

### Which FOCUS version

Azure lets you pick the FOCUS dataset version when you create the export. As of mid-2026, the choices are:

| Version | Notes |
|---------|-------|
| **1.0-preview(v1)** | Original preview. Don't use for new exports. |
| **1.0** | Stable FOCUS 1.0. Date columns omit seconds (`2026-05-01T00:00Z`). |
| **1.0r2** | **Recommended stable.** Same as 1.0 but date columns include seconds (`2026-05-01T00:00:00Z`) to match the FOCUS 1.0 spec exactly. |
| **1.2-preview** | Newest. Adds columns (capacity reservations, richer SKU price details, etc.). Use if you want the latest schema and can tolerate a preview. |

**Recommendation:** use **1.0r2** for a stable production feed, or **1.2-preview** if you want the newest schema. OpenChargeback only needs a small subset of columns (cost columns + `Tags`), so any 1.0+ version works. Pin one version and stay on it so your pipeline is predictable.

For the OCB-side column reference, see the [FOCUS File Format guide](../../user-guide/focus-format.md).

### What the file looks like

The Azure FOCUS file has ~50–100 columns. OCB reads the ones it needs and ignores the rest. The relevant slice looks like this (header trimmed for readability):

```csv
BillingPeriodStart,BillingPeriodEnd,ChargePeriodStart,ChargePeriodEnd,ServiceName,ResourceName,ResourceId,ListCost,ContractedCost,EffectiveCost,BilledCost,BillingCurrency,Tags
2026-05-01T00:00:00Z,2026-06-01T00:00:00Z,2026-05-14T00:00:00Z,2026-05-15T00:00:00Z,Virtual Machines,climate-sim-vm-03,/subscriptions/.../climate-sim-vm-03,42.1800,38.9200,38.9200,38.9200,USD,"{""pi_email"":""martinez.sofia@example.edu"",""fund_org"":""BIOLOGY-GRANTS-2025"",""project_id"":""climate-modeling"",""cost_center"":""CC-12345""}"
2026-05-01T00:00:00Z,2026-06-01T00:00:00Z,2026-05-14T00:00:00Z,2026-05-15T00:00:00Z,Storage,climatedata,/subscriptions/.../climatedata,8.5000,8.5000,8.5000,8.5000,USD,"{""pi_email"":""martinez.sofia@example.edu"",""fund_org"":""NSF-ATM-2024"",""project_id"":""climate-modeling""}"
```

Notice the `Tags` column is JSON, and the two rows carry **different** `fund_org` values — the second resource set its own override, the first inherited the college default. That's the fall-through showing up in the actual billing data.

### Discount transparency comes for free

OCB shows PIs both a list price and a billed price. Azure's FOCUS file populates the cost columns for you, so you don't compute anything:

| OCB concept | Azure FOCUS column |
|-------------|--------------------|
| List / retail price | `ListCost` |
| Contracted (EA/MCA negotiated) price | `ContractedCost` |
| Amount actually billed | `BilledCost` |
| Cost after credits/amortization | `EffectiveCost` |

If your institution subsidizes Azure spend for researchers, the difference between `ListCost` and `BilledCost` is the subsidy — and OCB will show it on the statement automatically. No work on your end.

---

## Delivering the Export to OpenChargeback

The export lands in an Azure Storage blob container. Getting it to OpenChargeback is the last step. **This is your org's choice** — here are three sane patterns, from least to most automated. Pick one.

> The front door is the blob container path you configured above:
> `{container}/{directory}/{ExportName}/{YYYYMMDD-YYYYMMDD}/{RunID}/`. Every option below starts there.

### Option A — Pull on a schedule (cron + azcopy)

Run a small monthly cron job on the host where OCB lives. It copies the newest run's CSV(s) down and ingests them.

```bash
# Conceptual example — monthly pull, runs after Azure's monthly export completes
# Find the most recent dated folder and sync just its CSVs locally
azcopy copy \
  "https://[YOUR_STORAGE_ACCOUNT].blob.core.windows.net/[CONTAINER]/[DIR]/[EXPORT_NAME]?[SAS_TOKEN]" \
  "/var/openchargeback/inbox/azure/" \
  --recursive --include-pattern "*.csv"

openchargeback ingest /var/openchargeback/inbox/azure/ --period 2026-05 --dry-run
```

Authenticate with a **SAS token** scoped to that container, or a **managed identity / service principal** if OCB runs in Azure. Simple, transparent, easy to debug.

### Option B — Push from Azure (Logic App or Function on blob-created)

Let Azure push instead of you pulling. A **Logic App** or **Azure Function** triggers when the new blob appears in the container, then forwards it:

- copy it to a **central institutional file share** OCB already watches (SFTP, SMB, or another blob/S3 bucket), **or**
- **email** the CSV to a designated intake address your billing process monitors.

Good when you'd rather not run a cron host, or when the OCB box can't reach Azure outbound but Azure can reach it.

### Option C — Email it to a designated address

Lowest-tech: a Logic App (or even a scheduled script) emails the monthly CSV to a billing inbox — e.g. `azure-billing@example.edu` — where your team drops it into OCB's import folder, or an OCB email-ingest rule picks it up. Fine for smaller volumes and a human-in-the-loop month-end.

> **Multiple subscriptions?** If a college has one FOCUS export per subscription, your delivery step just collects all of them into the same inbox. OCB ingests them together — the `Tags` on each row keep attribution straight regardless of which subscription the charge came from.

Whatever you choose, the OCB side is always the same:

```bash
openchargeback ingest /path/to/azure_focus_2026-05.csv --period 2026-05
```

---

## Troubleshooting

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| Charges land in OCB's review queue, unattributed | Tags missing on the resources, or tag inheritance not enabled | Enable Cost Management **Tag inheritance**; add an Azure Policy to require/inherit `pi_email` and `fund_org` |
| `fund_org` is the college default when it should be the research group's | Research group never set their own override tag | Set the tag on their resource group/resource — resource tags win over inherited by default |
| Research group's tag is being ignored, college default wins | Precedence flipped to inherited-wins | In Tag inheritance settings, switch back to the default ("Use the subscription or resource group tag" is the *override* — leave it off) |
| Tag changes don't show up in the export | Inheritance takes 8–24 hours and applies to the current month | Wait a day, re-run the export for the affected month |
| Export only has part of the month's rows | File partitioning split the data | Ingest **every** `part_*.csv` listed in `_manifest.json`, not just the first |
| No FOCUS dataset option when creating the export | Pay-as-you-go (MOSP) account, or you're at management-group scope | FOCUS needs EA/MCA/MPA; create the export at subscription, RG, or billing-account scope instead |
| "Unauthorized" creating the export to a firewalled storage account | Missing role-assignment permissions on the storage account | Use **Owner** on the storage account, or a custom role with `Microsoft.Authorization/roleAssignments/write` + `permissions/read`, during creation |
| `Tags` column empty for some rows | Purchases / resources that don't emit usage at subscription scope don't get inherited tags | Tag those resources directly, or resolve in OCB's review queue |

### Testing

Before relying on the monthly job:

1. Use **Export selected dates** in the portal to generate a single past month on demand (no waiting for the schedule).
2. Download the CSV(s) and confirm the `Tags` column is populated JSON with your `pi_email` and `fund_org`.
3. Test the OCB side: `openchargeback ingest azure_focus_2026-05.csv --period 2026-05 --dry-run`.
4. Check the dry-run summary for flagged/unattributed charges and fix tagging at the source.

---

## Using AI Assistance for Implementation

The tagging and export setup above is portal-driven — no code. But if you want to **automate delivery** (Option A/B/C) or write a script to **stitch partitioned exports together**, an AI coding assistant can do it. Paste this whole document in as context first.

### How to Use This Document with AI

1. **Paste this entire document** into your AI assistant (Copilot, ChatGPT, etc.) as context.
2. **Add the prompt below.**
3. **Answer the AI's clarifying questions** about your environment.
4. **Review the generated code** before deploying.

### Sample Prompt for AI Assistant

After pasting this entire document, add:

```
I need to automate delivery of an Azure Cost Management FOCUS export to
OpenChargeback. Azure already writes a monthly FOCUS CSV (one or more
partitioned files plus a _manifest.json) to an Azure Storage blob container.
I do NOT need to convert or reformat the data — Azure emits FOCUS natively.

**Environment:**
- Azure account type: [EA / MCA / MPA]
- Export scope: [subscription / resource group / billing account]
- Storage account + container + directory: [PLACEHOLDERS]
- OpenChargeback runs on: [Linux host / container / where]
- Auth available: [SAS token / managed identity / service principal]

**What I want:**
- A scheduled job that, once a month after the export completes:
  1. Finds the newest dated run folder in the container
  2. Reads _manifest.json and downloads ALL partition CSVs for that run
  3. Hands the file(s) to: openchargeback ingest <path> --period YYYY-MM
- Skip if the month was already ingested (idempotent)
- Log what it did; don't fail silently

**Constraints:**
- Don't hardcode partition filenames — always read them from _manifest.json
- Don't reformat the FOCUS columns — OCB reads them as-is
- Keep secrets out of the script (env vars / managed identity)

Before writing code, ask me clarifying questions about:
1. My auth method and whether the storage account is behind a firewall
2. Whether I want a pull (cron + azcopy) or push (Logic App / Function) model
3. CSV vs Gzip compression on my export
4. Where ingested files should be archived
5. Anything else you need
```

### Questions the AI Should Ask You

| Topic | What to decide |
|-------|----------------|
| Pull vs push | Cron+azcopy on the OCB host, or an Azure-side Logic App/Function |
| Authentication | SAS token, managed identity, or service principal |
| Partition handling | Confirm it reads `_manifest.json` rather than guessing filenames |
| Idempotency | How to detect a month already ingested |
| Archival | Where to move/keep files after ingest |

### Tips for Working with the AI

1. **Be specific about auth** — SAS vs managed identity changes the whole script.
2. **Insist on manifest-driven file discovery** — partitioning is always on; hardcoded names will eventually break.
3. **Ask it to explain trade-offs** — "Why pull over push for my setup?"
4. **Request idempotency** — "What happens if this runs twice for the same month?"
5. **Review before running** — have it explain any line you don't understand.

---

## Questions?

- **Tag definitions and validation**: [Cloud Resource Tag Specification](../TAG-SPECIFICATION.md)
- **FOCUS column reference (OCB side)**: [FOCUS File Format](../../user-guide/focus-format.md)
- **Azure export details**: [Microsoft — Create and manage Cost Management exports](https://learn.microsoft.com/azure/cost-management-billing/costs/tutorial-improved-exports)
- **Azure tag inheritance details**: [Microsoft — Group and allocate costs using tag inheritance](https://learn.microsoft.com/azure/cost-management-billing/costs/enable-tag-inheritance)

For anything else, contact your Research Computing billing administrator.
