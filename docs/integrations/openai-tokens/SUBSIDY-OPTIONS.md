# OpenAI Subsidy Options: Weeks vs Months

## The Challenge

OpenAI's ChatGPT EDU quota system operates on **weekly cycles**, but our billing operates on **monthly periods**. When considering a Provost subsidy ("we'll cover the first $X"), we need to decide how these time boundaries interact.

This document outlines the options and tradeoffs to help inform policy decisions.

---

## Background: How OpenAI Quotas Work

- OpenAI uses **rolling window quotas** (not fixed calendar resets)
- Weekly limits (e.g., 200/week for GPT-5.1 Thinking) reset ~7 days from first usage
- Each user has their own reset timing (visible by hovering over model in picker)
- This is for **load balancing** - prevents traffic spikes from synchronized resets
- Usage reports are exported **monthly** (or on-demand)
- Credits are consumed per-request based on model and token count

**Key insight:** OpenAI's rolling quotas are about *rate limiting* (preventing runaway usage), not *billing*. They still charge for all usage regardless of quota boundaries. The rolling windows are orthogonal to our monthly billing periods.

**Current EDU limits (as of Feb 2026):**
| Model | Limit | Window |
|-------|-------|--------|
| GPT-5.1 Thinking | 200 | ~week (rolling) |
| o3 | 100 | ~week |
| GPT-4.1 | 500 | 3 hours (rolling) |
| o4-mini | 300 | day |

---

## Subsidy Model Options

### Option 1: Annual Cap (Simplest)

**"Provost covers the first $500 per project per fiscal year"**

```
Project: ai-strategy
FY2026 Cap: $500

July:    $50 used  → Provost pays $50,   Dept pays $0     (remaining: $450)
August:  $100 used → Provost pays $100,  Dept pays $0     (remaining: $350)
...
January: $200 used → Provost pays $150,  Dept pays $50    (cap hit!)
February: $75 used → Provost pays $0,    Dept pays $75    (cap exhausted)
```

**Pros:**
- Simple to understand and administer
- Predictable budget for Provost ($500 × N projects max)
- No weekly complexity
- Easy to explain to PIs: "You get $500/year free, then you pay"

**Cons:**
- Projects could burn through subsidy in first month if heavy users
- No built-in pacing/rate limiting from subsidy perspective

**Best for:** Trusted projects, mature users, predictable workloads

---

### Option 2: Monthly Cap

**"Provost covers up to $50 per project per month"**

```
Project: ai-strategy
Monthly Cap: $50

January:  $80 used  → Provost pays $50, Dept pays $30
February: $30 used  → Provost pays $30, Dept pays $0
March:    $120 used → Provost pays $50, Dept pays $70
```

**Pros:**
- Spreads subsidy across the year (max $600/year vs one-time $500)
- Encourages pacing - if you blow through $50 early, you pay the rest
- Aligns with billing periods
- Use-it-or-lose-it encourages consistent engagement

**Cons:**
- More complex to explain
- "Wasted" subsidy if project has light month
- Could feel punitive to projects with legitimate spiky usage

**Best for:** Encouraging steady adoption, budget predictability per month

---

### Option 3: Weekly Cap (Calendar Weeks)

**"Provost covers up to $15 per project per calendar week"**

```
Project: ai-strategy
Weekly Cap: $15

Week of Jan 6:  $25 used → Provost pays $15, Dept pays $10
Week of Jan 13: $8 used  → Provost pays $8,  Dept pays $0
Week of Jan 20: $40 used → Provost pays $15, Dept pays $25
Week of Jan 27: $5 used  → Provost pays $5,  Dept pays $0
```

**Pros:**
- Smoothest pacing - heavy week = pay more, light week = fully covered
- Natural rate limiting effect from subsidy perspective

**Cons:**
- Complex to explain and audit
- Billing statements show many small subsidy entries
- Week boundaries don't align with month boundaries (Jan has ~4.3 weeks)
- Requires weekly state tracking
- **Does NOT align with OpenAI's rolling windows** - their quotas reset per-user based on first usage, not calendar weeks

**Note:** OpenAI's "weekly" quotas use rolling 7-day windows per user, not fixed calendar weeks. Our subsidy weeks would use calendar weeks (Mon-Sun or Sun-Sat) for simplicity and auditability. These are separate concepts - OpenAI's quotas control *rate*, our subsidies control *cost allocation*.

**Best for:** If you want fine-grained pacing regardless of OpenAI's rate limit behavior

---

### Option 4: Tiered/Graduated

**"First $200/year at 100% subsidy, next $300 at 50% subsidy, then 0%"**

```
Project: ai-strategy
Tier 1: $0-$200     → 100% subsidized
Tier 2: $200-$500   → 50% subsidized
Tier 3: $500+       → 0% subsidized

January: $150 used → Provost pays $150, Dept pays $0 (in Tier 1)
February: $200 used → Provost pays $125, Dept pays $75
  - First $50 at 100% (finishing Tier 1)
  - Next $150 at 50% (Tier 2)
```

**Pros:**
- Gradual transition from "free" to "you pay"
- Encourages exploration (Tier 1) while limiting exposure
- Projects "feel" the cost gradually

**Cons:**
- Complex to explain
- Complex to implement
- Harder to predict budgets

**Best for:** Behavioral nudging, encouraging exploration while limiting risk

---

### Option 5: Per-User vs Per-Project

All above options can be applied at different levels:

| Level | Example | Use Case |
|-------|---------|----------|
| **Per-project** | "ai-strategy gets $500/year" | Project-based budgeting |
| **Per-user** | "Each user gets $100/year" | Individual exploration/learning |
| **Per-PI** | "Each PI gets $500 to distribute" | PI discretion over allocation |
| **Global pool** | "First $10,000 across all projects" | First-come-first-served |

---

## Recommendation Matrix

| Scenario | Recommended Option |
|----------|-------------------|
| Pilot program, want simplicity | **Annual cap per project** |
| Ongoing program, want pacing | **Monthly cap per project** |
| Want to mirror OpenAI's behavior | **Weekly cap per project** |
| Want to encourage exploration | **Tiered (high free tier)** |
| Individual learning focus | **Annual cap per user** |
| Limited budget, many projects | **Global pool** |

---

## Implementation Considerations

### What the PI Sees (in our billing system)

Regardless of subsidy model, PIs will see their full usage with discounts:

```
Statement for: Dr. Smith (ai-strategy)
Period: January 2026

Service          Usage      Discount    Billed
─────────────────────────────────────────────────
OpenAI codex     $150.00    100%        $0.00
OpenAI chat      $50.00     60%         $20.00
─────────────────────────────────────────────────
Total            $200.00                $20.00

Note: $180.00 covered by Provost AI Initiative
```

### What Provost Sees

Separate statement showing all subsidized charges across projects:

```
Provost AI Initiative - January 2026

Project          PI           Subsidized
────────────────────────────────────────
ai-strategy      Dr. Smith    $180.00
data-science     Dr. Jones    $50.00
ml-research      Dr. Lee      $45.00
────────────────────────────────────────
Total                         $275.00
```

### Audit Trail

Both views trace back to the same underlying charges. IT can reconcile:
- Total paid to OpenAI: $475
- Recovered from Provost: $275
- Recovered from departments: $200

---

## Questions for Decision Makers

1. **Cap level:** Per-project? Per-user? Per-PI?

2. **Cap period:** Annual? Monthly? Weekly?

3. **Cap amount:** What dollar amount per period?

4. **Rollover:** If unused, does it roll over? (Usually: no)

5. **Eligibility:** All projects? Only approved projects? Only certain colleges?

6. **Reporting:** How often should Provost see subsidy utilization?

7. **Adjustments:** Can caps be increased mid-year for high-value projects?

---

## Next Steps

Once policy decisions are made, the preprocessing system can be configured to implement any of these models. The billing application itself requires no changes—it just processes whatever the preprocessor outputs.

Configuration is done in `subsidies.json`:

```json
{
  "subsidies": [{
    "name": "provost_ai_initiative",
    "fund_org": "PROVOST-AI-2026",
    "type": "per_project_cap",      // or "per_user_cap", "tiered", etc.
    "cap_amount": 500.00,
    "period": "fiscal_year",         // or "month", "week"
    "fiscal_year_start": "07-01",
    "applies_to_services": ["OpenAI"],
    "eligible_projects": ["*"],      // or specific project IDs
    "enabled": true
  }]
}
```
