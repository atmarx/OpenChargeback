# Deployment Planning: The Decisions to Make First

Most of setting up OpenChargeback is not technical. The config file takes an afternoon. The decisions *behind* the config file — those are the ones that need a conversation with your finance office, your infosec office, and whoever owns your cloud and HPC accounts.

This page is the worksheet. Work through it before you touch `config.yaml`, and the configuration writes itself. Skip it, and you'll discover the open questions in production, one flagged charge at a time.

A note on philosophy: OpenChargeback does **not** make you build a roster of who you're going to charge. You never type a PI's name into a setup wizard. You tell the system which columns in your billing data carry ownership — and the roster assembles itself from the data on first import. That's the whole point of the [FOCUS standard](../user-guide/focus-format.md). So most of what follows is about getting the *tags* right at the source and getting the *accounting* right at the destination — not about data entry.

---

## 1. Posture & data governance — *decide this first; it changes everything else*

The single most important decision: **is OpenChargeback your system of record, or your recorder?**

- **Recorder.** If your research-accounting office will accept a monthly canonical export package (raw FOCUS inputs + the invoices sent + the journal entries, archived on their side) and take ownership of the record, then OpenChargeback steps down to analytics and historical trend. Your liability for maintaining it drops by an order of magnitude. The raw files are the source of truth, the PDFs are proof of notification, and the journal sheet is the automation that feeds your finance system.
- **System of record.** If finance won't take that handoff, then OpenChargeback **is** the ledger — and every retention, backup, and infosec decision below gets heavier.

This is institution-specific. Neither answer is wrong. But decide it consciously, because it sets the stakes for the rest of this list.

Then, with your infosec office:

- **Is this billing data protected business information?** Fund/org spend, PI attribution, and grant correlation may be classified at your institution.
- **Where is the database allowed to live?** Data residency, and whether it must sit on **central managed infrastructure with backups and lifecycle management** rather than an individual's workstation. (SQLite is a single file; it's easy to run somewhere it shouldn't be. If this data matters — and especially if you chose "system of record" above — it belongs on managed hardware that gets backed up, not a front-desk PC that gets wiped in the next refresh.)
- **Encryption at rest.** SQLite has none natively. If infosec requires it, plan for an encrypted volume (LUKS, BitLocker, cloud-managed disk encryption).
- **Backup policy.** Frequency, retention, encryption of the backups, and where they're stored. See [Operations: Database](../operations/database.md).
- **Retention.** How long you keep raw inputs, statements, journals, and the database. (Indefinite today; a `RETENTION_YEARS` roll-off is a planned future hook, not v1.)

---

## 2. Roles & operations

- **Who is admin / reviewer / viewer?** Name actual people. The [permission matrix](../security/authentication.md#roles-and-permissions) defines what each can do — admin manages users and finalizes periods, reviewer imports and approves and generates, viewer is read-only.
- **Who runs the monthly close?** And who owns backups, and who holds the recovery account.
- **What's your monthly calendar?** When import / review / statements / journal / close / finalize each happen. The [Billing Workflow](../admin-guide/billing-workflow.md) has a suggested cadence.

---

## 3. The tag contract (attribution)

This is where ownership comes from. See the canonical [Tag Specification](../integrations/TAG-SPECIFICATION.md).

- **Who applies the tags?** Your cloud team, HPC admins, and storage admins — at resource creation, ideally via Infrastructure-as-Code.
- **Soft or hard enforcement?** Soft (untagged charges are flagged for review) is the recommended starting point; hard (cloud policy denies resource creation without tags) is the hammer for when untagged spend is genuinely unacceptable. The [Azure](../integrations/azure/) and [AWS](../integrations/aws/) guides show how to enforce — and how to handle hierarchical fall-through (an outer-scope default, overridden by an inner-scope tag).
- **The vocabulary.** Required: `pi_email`, `fund_org`. Recommended: `project_id`, `cost_center`. Optional: `account_code`, `end_date`, `reconciliation_end`, plus two custom `reference_1`/`reference_2` fields. The tag *key names* are yours — you map them to OpenChargeback's internal fields in `tag_mapping`.
- **PI identity.** The institutional email is the key. Decide whether you're attributing to individual PIs or to departmental invoice-ees.

---

## 4. Accounting integration — *the finance-office conversation*

Almost none of this can be guessed; it comes from your finance office. See [Journal Export](../admin-guide/journal-export.md).

- **GL account codes** per service category (e.g. cloud `54100`, HPC `54200`, storage `54300`).
- **Credit fund/org** per service — where the revenue side of each charge posts (the IT/service-provider side).
- **Your `fund_org` string format** — the validation regex (`review.fund_org_patterns`) and the regex that parses it into fund/org components for double-entry (`journal.fund_org_regex`).
- **Target ERP** — Banner, Workday, PeopleSoft — which drives a custom Jinja2 journal template. See [Templates](../admin-guide/templates.md).
- **Single-entry or double-entry GL?**
- **Resource splitting.** Today it's one cost center per resource. If you need a single resource split across two projects (say 75/25), that's a known gap, not a current feature — gather the edge cases before you count on it.

---

## 5. Rate & subsidy policy

OpenChargeback passes costs through as-is; it does not compute rates. Rates and subsidies are decided in policy and applied in your source exports/preprocessors.

- **Which services are subsidized, and by how much?** Even a 100%-subsidized service should carry its `ListCost` so the statement shows the true value (List Price $2,400 / Discount -$2,400 / Amount Due $0). Always populate `ListCost`.
- **Subsidy model.** Annual / monthly / weekly cap, tiered, applied per-project / per-user / per-PI / global pool. The OpenAI integration's [SUBSIDY-OPTIONS.md](../integrations/openai-tokens/SUBSIDY-OPTIONS.md) walks the tradeoffs.
- **The subsidy fund/org** — who's covering it (Provost, department, a grant).

---

## 6. Data sources & ingestion

- **Which sources?** AWS, Azure, GCP, Slurm/HPC, storage (Isilon, Qumulo), OpenAI, Azure Local. See [Integrations](../integrations/).
- **Native FOCUS or preprocessor?** [Azure](../integrations/azure/) and [AWS](../integrations/aws/) emit FOCUS natively — no preprocessor. HPC and storage need a small exporter; decide who owns it and on what schedule.
- **Filename conventions** so source and period auto-detect on import, and the `known_sources` config (name / pattern / credit fund_org / account_code per source).
- **What gets auto-flagged?** The `review.flag_patterns` regexes (e.g. GPU, training, test/sandbox). See [Review Process](../admin-guide/review-process.md).

---

## 7. Deployment & infrastructure

- **Where is it hosted?** Docker on a managed central VM, Azure App Service, or bare metal — ties straight back to your domain-1 governance answer. See [Operations: Docker](../operations/docker.md) and [Deployment](../deployment/azure-devops.md).
- HTTPS via reverse proxy, a real `secret_key`, secrets via environment variables, `dev_mode: false`, session lifetime, and password policy. See the [Security checklist](../security/README.md#quick-security-checklist).
- **Email delivery** — SMTP or Azure Communication Services — plus the domain plumbing (SPF/DKIM/DMARC).
- Backup automation + lifecycle, and logging/monitoring (Splunk/ELK/Datadog) with a log retention policy. See [Logging](../operations/logging.md).

---

## 8. Notification & branding

- **Email identity** — from-address, sender name, subject template.
- **Custom statement and email templates** — `statement.html` and `email_summary.html` for institutional branding (org name, contact email). See [Templates](../admin-guide/templates.md).
- **Who receives the statements** — PIs directly, or departmental administrators.

---

## 9. Lifecycle & corrections

- **Dispute handling.** The common case — "move this charge to a different project" — is handled by rejecting the charge and re-importing the corrected source file; the audit trail captures both sides. See [Review Process](../admin-guide/review-process.md).
- **Grant lifecycle.** `end_date` / `reconciliation_end` drive wind-down warnings on statements.
- **Close → finalize discipline.** Close prevents new imports but can be reopened; finalize is permanent. Finalize only after accounting confirms receipt of the journal entries.

---

## You're ready when…

You can answer, for your institution: who can log in, who applies the tags and at what level, what your fund/org format is, which GL accounts each service maps to, what's subsidized, where the database is allowed to live, and whether finance or OpenChargeback holds the record. Write those down, fill in [`config.yaml`](configuration.md), and import your first month — and watch the roster you never typed appear.
