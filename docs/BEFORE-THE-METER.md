# Before the Meter: Budget Guardrails Upstream of OpenChargeback

## How an account actually goes negative

The Friday before spring break, Pell Wickstrand — a grad student in Dr. Yev
Transom's lab — launches a hyperparameter sweep on a four-GPU cloud node and
goes home. Nobody looks at it for ten days. The node costs about $25 an hour;
by the time anyone logs back in, the sweep has burned roughly $6,100. The
grant had $1,800 of available balance.

Now walk the calendar. The usage happens in March. The provider bills at
month-end. The chargeback system attributes it, generates the statement, and
exports the journal in early April. Finance posts the journal around April
10th — and the fund goes negative. **Five weeks after the first dollar
burned, the first funds check in the entire chain finally ran. And failed.**

Nobody did anything wrong, exactly. The account went negative because of
*sequencing*: every control ran after the spend. NSF — "not sufficient
funds" — isn't a chargeback bug or a researcher behavior problem. It's a
check that ran too late to matter.

This document is the pitch for moving the check to the front.

## Where OpenChargeback ends

One boundary first, because it shapes everything after it.

[OpenChargeback](EXECSUMMARY.md) is the **register**: it takes the usage that
*did* happen, splits it to the right funds, invoices the right Principal
Invoicees, and hands finance a balanced journal that reconciles to the cent.
It is deliberately, permanently post-hoc. It does not approve spending,
enforce budgets, or stop anyone — and it never will, because a register that
also decides what you're allowed to buy is two systems wearing one audit
trail.

The pre-usage problem is real and it deserves a real solution. It's just a
*different* solution, owned upstream. Everything below describes that
upstream system — the **gate** and the **governor** that sit in front of the
register. Build it, buy it, or phase it in over years: OpenChargeback ingests
tagged FOCUS data regardless, and the bill still reconciles either way.

## The physics: three facts you can't wish away

Every honest design starts from three constraints. Any vendor or architecture
that seems to violate one of these is describing a reactive system with good
marketing.

**1. No public cloud offers a true real-time hard stop on a postpaid
account.** Cost data lags — hours on a good day, a day or more on a bad one.
Native "budgets" in both Azure and AWS are fundamentally *alerting*
constructs that can trigger *reactions*. The reaction is fast, but it is
never instantaneous, and money moves during the gap.

**2. The only place a check can run truly *before* usage is at provisioning
time.** When someone asks for a cloud project — an account, a subscription, a
resource group — that's a human-speed, synchronous moment. A funds check fits
there naturally. Once resources exist, you're governing, not gating.

**3. What you *can* bound in real time is the burn rate.** Service quotas are
enforced synchronously by the provider — a project with quota for one
four-GPU node physically cannot spend like a project with quota for forty.
Which yields the only honest guarantee in this space:

> **Maximum exposure = worst-case burn rate (set by quota) × detection-and-response lag.**

Both factors are knobs you control. Wickstrand's runaway weekend is at worst
`$25/hr × 240 hours ≈ $6,100` under a one-node quota — and at worst about
$600 if the governor reacts within 24 hours. Finance doesn't have to hope
overruns are small; it can *choose* how small they're allowed to be.

So the shape of the solution is fixed by the physics: **check at the gate,
govern the rate, settle at the register.**

## The frame finance already owns: this is a card program

Here's the reframe that makes the whole conversation easier: the institution
already runs a system that hands spending power to hundreds of people,
tolerates a detection lag, and almost never produces an NSF. It's the p-card
program. Nobody demands the p-card office guarantee zero misuse. They demand
limits, declines, statements, and consequences — and it works.

Cloud spending maps onto it almost embarrassingly well:

| The card program | The cloud equivalent |
|---|---|
| Card application + credit check | Project request + funds check at approval |
| Monthly card limit | Budget on the account / subscription / resource group |
| Single-transaction limit | Service quotas (the burn-rate ceiling) |
| Merchant category restrictions | Allowed-services policy (SCPs, Azure Policy) |
| Fraud alerts | Cost anomaly detection |
| The declined transaction | Deny-new-provisioning at 100% of budget |
| Monthly statement + reconciliation | OpenChargeback |
| Cardholder agreement | Terms accepted on the request form |

Today, cloud is a credit card with no limit, no credit check, and a statement
that arrives five weeks late. The proposal is not to invent financial
controls — it's to extend the card program the institution already trusts to
a merchant it can't yet see.

And the posture question answers itself the same way: finance doesn't need
**zero** risk. It needs **bounded, priced, assigned** risk — a worst-case
number per project, a policy for who eats an overage, and a paper trail. The
p-card office has never promised more than that.

## The three control points

### 1. At approval — the credit check (the only true "before")

A cloud project starts life as a **helpdesk request**, because it already
does — the helpdesk is where intake, approval routing, and asset records
live. The request form carries: requester, Principal Invoicee, fund/org,
monthly budget, expected duration, provider, and a plain-language
justification.

The gate service receives that request and runs the funds check against the
**finance system of record** — the same available-balance test the ERP
already runs on every purchase requisition:

```
available = budget − actuals − encumbrances   →   approve | decline | escalate
```

That check is the load-bearing move. Banner runs NSF checking on
requisitions today; Workday and PeopleSoft have their equivalents. Nobody has
to invent an approval workflow or teach finance a new trust model — **treat a
cloud project like a standing purchase order and ride the rails that already
exist.** A nightly extract of fund status and available balance is plenty;
this is an approval-grade check, not a penny-grade one. The authoritative
reservation happens in the ERP itself (next section), so the extract only
needs to be fresh enough to keep obviously-dead funds from getting through.

Two design rules from the [directory API](integrations/openai-tokens/directory-api/API-SPEC.md)
apply verbatim:

- **Vendor-neutral contract, thin shim per product.** The helpdesk interface
  is a JSON document in and a status write-back out. TDX today, ServiceNow or
  a Google Form tomorrow — the contract outlives the tool.
- **A failed check declines loudly.** No silent partial approvals, no
  provisioning against an unanswered finance system.

### 2. During the month — the limit (yes, this is programmable)

The direct answer to "could we programmatically set budgets in Azure and
AWS": yes, both, with real APIs, and with one honest asterisk each.

**AWS.** Give each project its own account under Organizations (the
AWS-native isolation boundary). [AWS Budgets](integrations/aws/) attach per
account, and **Budget Actions** go beyond alerting: at a threshold they can
apply a deny IAM policy, attach a Service Control Policy, or outright stop
EC2/RDS instances — auto-executed or held for human approval. Service Quotas
(vCPU ceilings per instance family) bound the burn rate synchronously.
Anomaly detection watches for shape changes.

**Azure.** Scope is a subscription or resource group.
[Cost Management budgets](integrations/azure/) are natively alert-only — the
asterisk — but budget notifications fire **action groups**, which trigger
automation: assign a deny policy, strip a deployment role, deallocate
compute, or move the subscription into a quarantine management group.
Per-family vCPU quotas bound the rate, same as AWS. (Azure's true hard
spending caps exist only on credit-based subscriptions — sponsorship,
students — which is really the prepaid rung of the ladder below.)

*(GCP, for completeness: budgets publish to Pub/Sub, and the documented
pattern is a function that disables billing on the project — a kill switch,
not a governor. Nuclear, but it exists.)*

Three cross-cutting points matter more than the per-cloud trivia:

- **All of it is infrastructure-as-code.** Budgets, quotas, policies, and
  tags are all Terraform-able. The gate provisions them *from the approved
  request* — so the number on the ticket, the number encumbered in the ERP,
  and the number enforced in the cloud are written by one actor from one
  approval. They cannot drift apart, because nobody ever types them twice.
- **Tags do double duty.** The gate stamps the same attribution tags the
  register requires ([TAG-SPECIFICATION.md](integrations/TAG-SPECIFICATION.md))
  — one attribution scheme, two consumers. And since both clouds now export
  FOCUS natively, the governor's mid-month meter and the register's month-end
  bill read the same format from the same source. There is no "the dashboard
  said X but the bill said Y" gap to reconcile, because there's only one
  meter.
- **Default posture: deny new, don't kill running.** At 100% of budget, block
  *new* resources and page a human — don't deallocate a three-week training
  job at 100.4% of budget, because the re-run costs more than the overage.
  Killing running work is reserved for the anomaly class (the Wickstrand
  weekend), and even then it's a policy knob finance sets per fund type, not
  something IT hardcodes.

### 3. At settlement — the register, plus the loop

Month-end proceeds exactly as it does today: FOCUS export → OpenChargeback →
statements to Principal Invoicees → balanced journal to finance. The
guardrail adds one thing the register was already built to feed: **the
write-back.**

Every cloud project traces to a helpdesk ticket and an asset/CI record. So
budget tracking goes *back to where the request lives*, the same pattern as
the [per-user showback](integrations/openai-tokens/directory-api/README.md)
in the OpenAI integration:

- a monthly actuals line on the project's CI ("2026-03: $1,847 of $2,000"),
- threshold events as ticket activity ("75% consumed on day 18 — projecting
  $2,340 against $2,000" — a neutral note, not an accusation),
- and at period end, the closed loop: actuals liquidate the reservation,
  next month's budget adjusts, underspend releases.

The helpdesk sees the whole lifecycle in the tool it already lives in.
Finance sees reservations and liquidations in the ERP it already trusts. The
PI gets warned at 50/75/90 before anything declines. Nobody gets a surprise.

## How the money moves

"How do we account for all of this?" — by giving each phase exactly one
owner and one instrument, so a dollar is never in two places:

| Phase | Owner | Instrument |
|---|---|---|
| Request | Helpdesk | Ticket (fund/org, budget, invoicee, duration) |
| Check | Finance system of record | Available-balance test (the NSF check, run *early*) |
| Reserve | Finance system of record | Encumbrance / commitment (see ladder below) |
| Enable | The gate (IT glue) | Account/RG + tags + budget + quota + policy, from the approval |
| Meter | Cloud provider | FOCUS cost data |
| Govern | The governor (IT glue) | Warn → deny-new → respond; anomaly watch |
| Bill | OpenChargeback | Statements per Principal Invoicee × fund/org |
| Settle | Finance | Journal posts; the encumbrance liquidates |
| Report back | The governor → helpdesk | CI timeline, ticket events, projections |
| Sunset | Helpdesk + gate | Resources reaped, residual reservation released |

The reserve step is where finance chooses how strong a guarantee it wants.
There are exactly three rungs, and they trade friction for certainty:

**Rung 1 — advisory check.** Approve only if the balance covers the
commitment; reserve nothing. Kills the dumbest NSFs (dead fund, empty fund)
with zero new accounting. But the fund can still be drained by *other*
spending between approval and billing — the check decays as the month ages.

**Rung 2 — encumbrance.** At approval, post a reservation in the ERP — the
same instrument as a standing purchase order, rolled monthly or quarterly so
a year of budget isn't tied up at once. The monthly journal *liquidates* the
encumbrance, so the charge lands on money that was already spoken for. NSF
becomes structurally rare: the funds check ran at reservation time, which is
the only time it can succeed. Overage beyond the reservation is bounded by
the exposure formula and handled as a change order — a workflow finance
already has. Underspend releases at period end, visibly, which finance likes
almost as much as the reservation. **This is the rung to pitch.** It uses no
new machinery, speaks fluent Banner, and makes "negative number" a
before-lunch escalation instead of a month-end discovery.

**Rung 3 — prepaid.** Money moves first; the balance *is* the cap; NSF is
impossible by construction — a debit card instead of a credit card. This is
exactly how credit-based cloud subscriptions and OpenAI seat credits already
work — worth noticing that **the service that started this conversation is
already on rung 3.** The costs: the float sits with IT (which makes you a
recharge center, with recharge-center rules — in the US, break-even
discipline under 2 CFR 200.468), and top-ups add real friction to research.
Use it where overrun tolerance is genuinely zero, not everywhere.

Different fund types deserve different rungs — that's a policy table finance
owns, not an architecture question:

| Fund type | Check | Reservation | In-month posture |
|---|---|---|---|
| Sponsored award (near end date) | Hard | Encumbrance, monthly | Deny-new at 100%, tight quota |
| Sponsored award (healthy) | Hard | Encumbrance, quarterly | Deny-new at 100% |
| Department operating | Advisory | Optional | Warn-only, generous quota |
| Prepaid credit blocks | None needed | The balance itself | Hard by construction |
| Master fund (catch-all) | n/a | Central float | Quota-bounded; a routed charge is a cue to map it, same as the register's routing rule |

## Are we re-inventing Kion?

Partly — and it's worth being precise about which part, because the answer
decides what to buy versus what to build.

**Kion** (né cloudtamer.io) is the closest commercial fit: automated account
provisioning, "funding source" and spend-plan enforcement with real actions
(including freezing accounts), and continuous compliance, across AWS, Azure,
and GCP. Several universities run it for exactly this problem. If the middle
of the diagram — the per-cloud enforcement plumbing — needs to cover hundreds
of accounts with compliance attestation, buying it is defensible and this
document becomes its requirements page.

But notice what Kion does *not* know: your ERP's encumbrances, your
helpdesk's forms, your fund/org semantics, or SaaS seat meters like OpenAI
licenses — it governs cloud *accounts*, not vendor *seats*. The two ends of
the pipeline — the finance contract and the helpdesk contract — are custom
glue in every scenario, bought or built. And that glue is where all the
institutional meaning lives; the cloud-side enforcement is the
best-documented, most commoditized part of the whole design.

So the honest decision rule is: **count the accounts.** At dozens of cloud
projects, native primitives (Budgets + Actions + SCPs on AWS, budgets +
automation + Policy on Azure) driven by the gate's Terraform are entirely
adequate, and free. At hundreds, with auditors asking for attestation, buy
the middle. Either way the contract-first glue is the same work — small,
boring, JSON-shaped work, the [directory-API](integrations/openai-tokens/directory-api/API-SPEC.md)
kind — and either way, the register downstream doesn't change at all.

(The FinOps visibility tier — Cloudability, CloudCheckr, and kin — solves a
different problem: seeing, not gating. Useful, but no amount of dashboard
prevents an NSF.)

## What each office owns

- **Finance** owns the policy: which rung per fund type, quota tiers,
  warning thresholds, the overrun workflow, and the encumbrance mechanics.
  The knobs are theirs; the system just makes the knobs real.
- **The helpdesk** owns intake and the asset record: the request form, the
  CI timeline that accumulates budget history, and acting on the "map this
  license / re-home this charge" cues.
- **IT** owns the glue and the defaults: the gate service, the enforcement
  profiles per cloud, the tag stamping, and the Terraform that makes
  ticket = encumbrance = budget by construction.
- **The researcher** gets a promise worth stating out loud: *you'll know
  your limit before you start, you'll be warned at 50, 75, and 90 before
  anything declines, a decline blocks new resources but never silently kills
  running work, and you will never get a surprise bill.* Guardrails that
  researchers experience as protection get adopted; guardrails they
  experience as ambush get circumvented.

## What this is not

It is not part of OpenChargeback, and it shouldn't be. The register ingests
tagged FOCUS data and reconciles to the cent whether the upstream is rung 1,
rung 3, Kion, or nothing at all. That independence is the point: the
institution can phase in guardrails fund-type by fund-type, change vendors,
or change its mind — and billing never skips a month.

Finance hates negative numbers. Fair. But a negative number is a sequencing
bug: the check ran after the spend. Put the check at the gate, bound the
burn with quotas, let the governor decline like a card at its limit — and
the register at the end of the line stops being the place bad news is
discovered. It goes back to being what a register should be: the place where
the receipts live.
