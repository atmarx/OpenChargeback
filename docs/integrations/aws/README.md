# AWS FOCUS Export Guide

This guide shows the billing manager how to get AWS cost data into OpenChargeback (OCB). AWS already speaks FOCUS natively, so there is no script to write and no preprocessor to maintain — you turn on a monthly export, make sure your resources carry the right tags, and arrange for the file to land where OCB can read it.

> **Don't panic.** Unlike the [Slurm](../slurm/) and Qumulo guides, there is **no custom exporter to build here**. AWS Data Exports emits FOCUS-format data for you. Your real work is tagging discipline and a small delivery step. If any part of the delivery automation needs a few lines of glue code, you can hand this document to your institutional AI assistant — see [Using AI Assistance](#using-ai-assistance-for-implementation) at the end.

### Must-Read Sections

Before you touch the console, review these:

1. **[Setting the Required Tags](#setting-the-required-tags)** — the tags OCB needs, and how to handle the college-owns-the-outer-scope, group-overrides-the-inner-scope problem with fall-through
2. **[Exporting the Monthly FOCUS Report](#exporting-the-monthly-focus-report)** — turning on AWS Data Exports with the FOCUS table
3. **[Automating Delivery to OCB](#automating-delivery-to-ocb)** — getting the file from S3 to OpenChargeback
4. **[Using AI Assistance](#using-ai-assistance-for-implementation)** — how to use this doc to generate any delivery glue you need

Everything else is reference for edge cases and troubleshooting.

---

## Overview

**Goal**: Deliver a monthly FOCUS-format cost file from AWS into OpenChargeback, with every charge attributed to the correct PI and fund/org.

**Data Source**: AWS Billing and Cost Management → **Data Exports**, using the **FOCUS 1.2 with AWS columns** table. This export is native FOCUS — AWS produces the standardized `ListCost`, `ContractedCost`, `BilledCost`, and `EffectiveCost` columns for you.

**Billing Model**: AWS calculates the costs. You do not compute rates or subsidies in a script. OCB reads the four cost columns directly. The discount transparency story (list vs. billed) is already handled by AWS — `ListCost` is the public on-demand price and `BilledCost`/`EffectiveCost` reflect your discounts, Savings Plans, and credits.

**What you actually do**:

1. Tag resources so `pi_email` and `fund_org` reach the FOCUS `Tags` column.
2. Activate those tag keys as cost allocation tags (there's a lag — read on).
3. Turn on the FOCUS Data Export.
4. Move the monthly file to where OCB ingests it.

> **No preprocessor needed.** AWS emits FOCUS natively, so OCB ingests the export directly. The one wrinkle is the **cost-allocation-tag activation lag** described below — tagging is not instantaneous in the cost data.

---

## Setting the Required Tags

OCB attributes each charge from the FOCUS `Tags` column. The canonical list of tags lives in **[TAG-SPECIFICATION.md](../TAG-SPECIFICATION.md)** — link to it, don't re-derive it. The short version:

| Tag | Status | Example |
|-----|--------|---------|
| `pi_email` | **Required** | `martinez.sofia@example.edu` |
| `fund_org` | **Required** | `BIOLOGY-GRANTS-2025` |
| `project_id` | Recommended | `climate-modeling` |
| `cost_center` | Recommended | `CC-12345` |
| `account_code` | Optional | `54100` |
| `end_date` | Optional | `2025-06-30` |
| `reconciliation_end` | Optional | `2025-09-30` |

**The tag key names are your institution's choice.** OCB maps whatever you use to its internal fields in `config.yaml` (`tag_mapping:`). If your AWS admins already standardized on `PIEmail` and `FundOrg`, map those — don't rename everything in AWS.

### Step 1: Put the tags on resources

The plain-CLI way (one resource):

```bash
# Conceptual example: tag an EC2 instance
aws ec2 create-tags \
  --resources i-0a1b2c3d4e5f67890 \
  --tags \
    Key=pi_email,Value=martinez.sofia@example.edu \
    Key=fund_org,Value=BIOLOGY-GRANTS-2025 \
    Key=project_id,Value=climate-modeling
```

In practice, push tags through Infrastructure as Code (CloudFormation/Terraform) so every resource is born tagged. Tagging by hand after the fact is how charges end up in OCB's review queue.

### Step 2: Activate the tags as cost allocation tags (mind the lag)

This is the step people forget. **A tag does not appear in your cost data just because it's on a resource.** You must activate it as a *user-defined cost allocation tag* in the Billing console:

1. Billing and Cost Management console → **Cost allocation tags**.
2. Select the tag keys (`pi_email`, `fund_org`, `project_id`, …).
3. Choose **Activate**.

**The activation lag, verified from current AWS docs:**

- After you first apply a tag to a resource, it can take **up to 24 hours** for that tag key to even show up on the Cost allocation tags page so you can activate it.
- After you activate it, it can take **up to another 24 hours** for the key to actually start flowing into your cost data.
- Activation is **not retroactive** — costs already recorded before activation won't suddenly grow the new tag column.

> **Plan ahead.** Activate `pi_email` and `fund_org` *before* the billing month you care about, not on the last day. A tag activated mid-month only attributes the rest of that month. Charges from before activation arrive in OCB untagged and land in the review queue.

### The hierarchy / fall-through problem (the important part)

Here's the real-world situation. A **college owns an outer scope** — an AWS Organizations OU, or a whole member account. Inside it, a **research group has their own `fund_org`** and wants to override the college default. But sometimes the group forgets to tag a resource, and when the inner tag is blank you want the charge to **fall through** to the college's outer default rather than land unattributed.

Be honest about how AWS works here, because it's a common trap:

> **AWS does not auto-inherit resource tags.** A tag on an OU or an account is **not** copied down onto the EC2 instances inside it. There is no native "tag inheritance" for resource tags. So you cannot rely on "tag the account and the instances inherit it." That mechanism does not exist.

What you actually have are three real tools. Pick the combination that fits how your org is structured:

#### Tool 1 — AWS Cost Categories (this is your fall-through engine)

**Cost Categories** is the right tool for "use the inner tag if present, otherwise fall back to the outer default." It groups line items by *rules*, and crucially:

- Rules are processed **in order, first match wins**.
- A rule of type **inherited value** can dynamically pull its value from a **tag key** (`DimensionName = TAG`) **or** from the **account name** (`DimensionName = LINKED_ACCOUNT_NAME`).
- You can set a **default value** for any line item that matches no rule.

That ordering is exactly the fall-through you want. Define a Cost Category called, say, `effective_fund_org`:

```
Rule 1 (inherited value, TAG):
    Inherit value from tag key "fund_org"
    → if the resource carries a fund_org tag, the group's override wins.

Rule 2 (inherited value, LINKED_ACCOUNT_NAME):
    Inherit value from the account name
    → e.g. the "Biology-College" account name carries the outer default.

Default value:
    "UNATTRIBUTED-REVIEW"
    → nothing matched at all; OCB flags it for review.
```

Because rule order is first-match-wins, a resource with its own `fund_org` tag never reaches Rule 2 — the group's override sticks. A resource with a blank `fund_org` skips Rule 1 and falls through to the account-level value in Rule 2. A resource in neither hits the default and shows up in OCB's review queue. That's precisely the "override at the inner level, fall back to the outer" behavior AWS otherwise won't give you.

Cost Categories values appear in the FOCUS export's AWS-specific columns (the `x_` columns, e.g. `x_CostCategories`). If you'd rather have the resolved value land directly in the OCB `fund_org` field, you have two clean options:

- Map the OCB `fund_org` field to the resource tag in `config.yaml` and accept that the fall-through only happens at review time, **or**
- Have your delivery step (or a tiny transform) copy the resolved Cost Category value into the `Tags` JSON before OCB ingests it. Most institutions just map the tag and let OCB's review queue catch the blanks — simpler, and the audit trail is cleaner.

#### Tool 2 — AWS Organizations tag policies (enforce that keys exist)

**Tag policies** standardize which tag keys must exist and how they're cased. You attach a policy at the **root, an OU, or a specific account** — so the org chooses the enforcement level. Tag policies have two modes:

- **Reporting mode** — flags non-compliant resources without blocking anything. Good first step; pairs naturally with OCB's soft enforcement (charges flagged for review, not rejected).
- **Enforcement mode** — can block tag operations that violate the policy, and can check IaC deployments (CloudFormation, Terraform, Pulumi) against required tag keys *before* resources are created.

A tag policy is how the college says "every resource in this OU must carry a `fund_org` key." It governs the *key*, not whether the *value* is right.

#### Tool 3 — Service Control Policies (hard-deny creation without tags)

If you want the strongest enforcement, an **SCP** at the OU or account level can deny resource-creating API calls unless a required tag key is present (e.g. deny `ec2:RunInstances` when `aws:RequestTag/fund_org` is absent). This is the hammer — use it where untagged spend is genuinely unacceptable. Test SCPs on a throwaway account first; a too-broad SCP can block people from creating resources they legitimately need.

#### Choosing the enforcement level — your call, not ours

There's no single right answer, and OCB doesn't require one. Sane options:

| If you want… | Use | Where you attach it |
|--------------|-----|---------------------|
| Catch mistakes after the fact, no blocking | Tag policy in **reporting mode** + OCB review queue | OU or account |
| Override-with-fall-through attribution | **Cost Categories** inherited-value rules | Organization-wide |
| Require the key, warn IaC pipelines | Tag policy in **enforcement mode** | OU |
| Hard-block untagged resource creation | **SCP** | OU or account |

Most research institutions start with Cost Categories for fall-through plus a tag policy in reporting mode, then tighten to enforcement once the tagging habit sticks. OCB's soft enforcement means an occasional blank tag is a review-queue item, not a catastrophe — so you don't have to lead with SCPs.

### Tag-to-FOCUS mapping

Activated cost allocation tags flow into the FOCUS `Tags` column as JSON. OCB then maps them:

```yaml
# config.yaml
tag_mapping:
  pi_email: "pi_email"        # Required
  fund_org: "fund_org"        # Required
  project_id: "project_id"    # Recommended
  cost_center: "cost_center"  # Recommended
  # Map your institution's real AWS tag key names on the right-hand side.
```

See **[TAG-SPECIFICATION.md](../TAG-SPECIFICATION.md)** for the full field reference and `fund_org` format patterns.

---

## Exporting the Monthly FOCUS Report

AWS produces FOCUS data through **Data Exports** in the Billing and Cost Management console. This is the modern path — it replaces the old Cost and Usage Report (CUR) workflow. (CUR 2.0 still exists as a separate table type; you do **not** need it for OCB. Pick the FOCUS table and skip CUR entirely.)

### Which FOCUS version

Verified against current AWS docs (June 2026):

- **FOCUS 1.2 with AWS columns** — generally available since **November 2025**. This is the one to choose. It adds invoice reconciliation (`InvoiceId`) and capacity-reservation columns on top of 1.0.
- **FOCUS 1.0 with AWS columns** — GA since November 2024. Still available; fine as a fallback if your tooling pinned to it. OCB reads either — it only needs the FOCUS-standard columns (`BillingPeriodStart`, `BilledCost`, `Tags`, plus the cost columns).

Use **FOCUS 1.2** unless you have a reason not to.

### Creating the export

1. Open the **Billing and Cost Management console** → **Data Exports**.
2. **Create export** → **Standard data export**.
3. **Export name**: e.g. `ocb-focus-monthly`.
4. **Data table**: select **FOCUS 1.2 with AWS columns**. (Note: the FOCUS table has **no table configurations** to fuss with — unlike CUR 2.0, there are no resource-ID or split-cost toggles. It just works.)
5. **Column selection**: select all columns (OCB ignores the ones it doesn't use; selecting all future-proofs you).
6. **Refresh cadence**: for billing/cost exports the only option is **Daily** — the export is refreshed up to once per day with the current month's running data. The file is **partitioned by billing period**, so each calendar month is its own partition. You ingest the completed month into OCB.
7. **File versioning**:
   - **Overwrite existing file** — each refresh overwrites within the billing-period partition. Cleaner S3, simplest for OCB. Recommended.
   - **Create new file** — keeps every refresh as a separate directory for change tracking. Only choose this if you need that history; it complicates "which file do I ingest."
8. **Compression / format**: choose **gzip – text/csv** so OCB ingests CSV directly. (Parquet is also offered, optimized for Athena/Redshift — only pick it if you have a Parquet step in your pipeline.)
9. **Storage settings**: choose an S3 bucket in **this account** (or another account if billing is centralized). Set an **S3 path prefix** like `ocb/focus/`.
10. **Create**.

### Where it lands in S3

The export writes under your bucket and prefix, organized by export name and **billing-period partition**. Roughly:

```
s3://your-bucket/ocb/focus/ocb-focus-monthly/
  data/
    BILLING_PERIOD=2025-05/
      ocb-focus-monthly-00001.csv.gz
    BILLING_PERIOD=2025-06/
      ocb-focus-monthly-00001.csv.gz
  metadata/
  manifest files...
```

The exact layout varies slightly with versioning and AWS updates, but the key idea holds: **one partition per billing month**, and you ingest the file(s) under the completed month's `BILLING_PERIOD=YYYY-MM/` folder. Because the current month refreshes daily, wait until the month closes (plus a day or two for AWS to finalize) before treating it as the bill.

### What OCB receives

The FOCUS export already carries the columns OCB needs — see **[../../user-guide/focus-format.md](../../user-guide/focus-format.md)** for the column-by-column reference. No transform, no preprocessor. The `Tags` column carries your activated `pi_email` / `fund_org` JSON; the cost columns carry list vs. billed for discount transparency.

---

## Automating Delivery to OCB

The export lands in S3. From there, getting it to OpenChargeback is the org's choice — OCB ingests a file, it doesn't reach into your AWS account. Point your pipeline at the **completed month's partition** and pick whichever of these fits your shop. Don't over-engineer it.

### Option A — Scheduled `aws s3 sync` (simplest)

A cron job on the OCB host (or a nearby box) pulls the month's file after the billing period closes:

```bash
# Conceptual example: cron, runs the 3rd of each month for the prior month
PERIOD=$(date -d "last month" +%Y-%m)
aws s3 sync \
  "s3://your-bucket/ocb/focus/ocb-focus-monthly/data/BILLING_PERIOD=${PERIOD}/" \
  "/srv/openchargeback/incoming/aws/${PERIOD}/"

openchargeback ingest \
  --source aws \
  --period "${PERIOD}" \
  "/srv/openchargeback/incoming/aws/${PERIOD}/"
```

This is the least moving parts and the easiest to debug. Recommended unless you have a reason to push instead of pull.

### Option B — S3 event → Lambda → central file share

If OCB ingests from a file share and you want delivery to be event-driven: an **S3 event notification** on the export prefix triggers a small **Lambda** that copies the new object to your central share (or to OCB's incoming bucket). Good when you want the file to arrive automatically the moment AWS finalizes the partition, with no cron to babysit.

### Option C — SES/Lambda email to a designated address

If your OCB intake is an email inbox (some institutions route monthly bills that way): a Lambda triggered on the S3 event reads the object and emails it via **Amazon SES** to a designated address like `billing-intake@example.edu`. Heaviest of the three, but it fits orgs whose billing workflow is mailbox-driven.

### Choosing

| If… | Use |
|-----|-----|
| OCB host can reach S3 with read creds | **Option A** (cron `s3 sync`) |
| You want push, file-share delivery | **Option B** (S3 event → Lambda) |
| Your intake is an email inbox | **Option C** (SES) |

All three are fine. Option A is what most people should start with.

---

## Troubleshooting

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| Charges import but `Tags` is empty / PI blank | Cost allocation tag keys never activated, or activated too late | Activate `pi_email`/`fund_org` in **Cost allocation tags**; remember the up-to-24h + up-to-24h lag and that it isn't retroactive |
| Tag is on the resource but not in the export | Activation lag, or tag applied after the charge was recorded | Wait up to 48h after activating; only charges *after* activation carry the tag |
| Some resources fall to the wrong fund/org | Cost Category rule order, or account-name mismatch | Remember first-match-wins; put the tag (inner override) rule **before** the account (outer default) rule |
| Everything lands in OCB's review queue | No fall-through configured and tags missing | Add a Cost Category default value and/or a tag policy in reporting mode to find the gaps |
| Export file is Parquet, OCB wants CSV | Chose Parquet/Athena integration | Recreate or edit the export with **gzip – text/csv** |
| Can't decide which month's file is "the bill" | Used **Create new file** versioning | Switch to **Overwrite**, or have your sync grab the latest object under the partition |
| `RunInstances` denied for a legit user | Over-broad SCP requiring a tag | Loosen the SCP or move it to a tag policy in reporting mode; test SCPs on a throwaway account first |

### Testing

Before you trust the monthly run:

1. Activate the tag keys and wait out the lag (up to 48h).
2. Tag one test resource with `pi_email` and `fund_org`, let a day of usage accrue.
3. Pull that month's partition and inspect the `Tags` column for your test values.
4. Dry-run the import: `openchargeback ingest --dry-run`.
5. Confirm totals and attribution, then schedule.

---

## Using AI Assistance for Implementation

Most of this guide is point-and-click in the AWS console — there's no exporter to write. The one place you might want code is the **delivery step** (Option B's Lambda, or a more elaborate sync). For that, an AI coding assistant (Copilot, ChatGPT, etc.) can generate it from this document.

### How to Use This Document with AI

1. **Paste this entire document** into your AI assistant as context.
2. **Add the prompt below** after the document.
3. **Answer the AI's clarifying questions** about your specific environment.
4. **Review the generated code** before deploying.

### Sample Prompt for AI Assistant

After pasting this entire specification document, add the following prompt:

```
I need to automate delivery of an AWS Data Exports FOCUS 1.2 file into
OpenChargeback each month. AWS already produces the FOCUS export — I do NOT
need a preprocessor or any FOCUS conversion. I only need the delivery glue.

**Environment:**
- FOCUS export name: ocb-focus-monthly
- Lands in: s3://[YOUR_BUCKET]/ocb/focus/ocb-focus-monthly/data/
- Partitioned by BILLING_PERIOD=YYYY-MM, gzip/CSV, overwrite versioning
- OpenChargeback host: [YOUR_OCB_HOST], ingests files from [YOUR_INTAKE_PATH]

**What I want:**
- Pick the month after it closes (prior calendar month), grab that partition's
  file(s), and place them where OpenChargeback ingests, then run:
  openchargeback ingest --source aws --period YYYY-MM <path>
- Delivery method: [cron aws s3 sync  /  S3 event -> Lambda  /  SES email]

**Constraints:**
- Wait until the billing period is finalized before treating it as the bill
- Idempotent — re-running the same month must not double-ingest
- Log success/failure; alert on failure to [YOUR_ALERT_CHANNEL]
- Least-privilege IAM (read-only on the export prefix)

Before writing code, ask me clarifying questions about:
1. Which delivery method (pull via cron vs. push via Lambda vs. SES email)
2. How OpenChargeback authenticates to S3 (instance role, access keys, profile)
3. The exact intake path / bucket OpenChargeback reads from
4. How I want to be alerted on failure
5. Whether I use "Overwrite" or "Create new file" versioning (affects which
   object to grab)
```

### Questions the AI Should Ask You

Be prepared to answer:

| Topic | What to Know |
|-------|--------------|
| Delivery method | Cron pull, S3-event Lambda push, or SES email — your call |
| S3 auth | Instance role vs. access keys vs. named profile on the OCB host |
| Intake location | The path or bucket OpenChargeback actually ingests from |
| Versioning | Overwrite (one file per month) vs. new-file (multiple) |
| Timing | How many days after month-end before AWS finalizes for you |
| Fund/org fall-through | Whether you resolved it via Cost Categories or rely on OCB's review queue |

### Tips for Working with the AI

1. **Be specific about your environment** — bucket name, prefix, OCB host, intake path.
2. **Tell it AWS already emits FOCUS** — so it doesn't waste effort writing a converter you don't need.
3. **Ask it to explain trade-offs** — "Why pull over push for my setup?"
4. **Request least-privilege IAM** — have it write the minimal S3 read policy for the export prefix.
5. **Insist on idempotency** — re-running a month must not double-ingest.
6. **Review before running** — have it explain any line you don't understand.

---

## Questions?

For questions about AWS tagging, the FOCUS export, or OCB ingestion, contact your Research Computing billing administrator. For the canonical tag list see **[TAG-SPECIFICATION.md](../TAG-SPECIFICATION.md)**; for the FOCUS column reference see **[focus-format.md](../../user-guide/focus-format.md)**.
