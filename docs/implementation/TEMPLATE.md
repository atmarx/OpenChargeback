# Implementation Guide Writing Guide

This meta-guide defines the structure, tone, and patterns for writing FOCUS billing implementation guides. Use this when creating new guides for additional data sources.

---

## Purpose

Implementation guides help teams (internal or external) build scripts that export usage data in FOCUS CSV format. The guides should:

1. **Reduce anxiety** — Start with "Don't panic" and clear navigation
2. **Be complete** — Cover all edge cases so the AI assistant has full context
3. **Be actionable** — Provide enough detail that an AI can generate working code
4. **Defer specifics** — Leave environment-specific details (field names, rates, paths) as questions for the implementer to answer

---

## Document Structure

Every implementation guide should follow this structure:

```
# {Data Source} Export Guide

[Intro paragraph]

> **Don't panic.** [Reassurance + pointer to AI assistance section]

### Must-Read Sections
[4 numbered links to key sections]

---

## Overview
[Goal, Data Source, Billing Model summary]

---

## Data Collection
[Options for retrieving data - API, CLI, files, etc.]

---

## Metadata
[How billing info (PI, project, fund/org) is associated with resources]

---

## Output Format: FOCUS CSV
[Column reference table + Tags JSON structure]

---

## Example Output
[Concrete CSV examples with realistic data]

---

## Cost Calculation
[Formulas with worked examples]

---

## Implementation Guidelines
[Numbered sections: setup, scheduling, logging, validation]

---

## Troubleshooting
[Common issues table]

---

## File Delivery to Billing System
[Options for getting files to the billing system]

---

## Using AI Assistance for Implementation
[How to use the doc with Copilot/ChatGPT]

---

## Questions?
[Contact info]
```

---

## Section Templates

### Title and Intro

```markdown
# {Platform/System} {Resource Type} Export Guide

This guide provides instructions for generating FOCUS-format billing data from {system description}. The export {frequency} to {billing granularity description}.

> **Don't panic.** This document is detailed, but you don't need to write everything from scratch. After reviewing the key sections below, you can use your institutional AI assistant (Copilot) to generate the implementation. See [Using AI Assistance](#using-ai-assistance-for-implementation) at the end.

### Must-Read Sections

Before building anything, review these sections:

1. **[Output Format: FOCUS CSV](#output-format-focus-csv)** — The exact columns and format your script must produce
2. **[{Metadata Section Title}](#{anchor})** — {Brief description}
3. **[Cost Calculation](#cost-calculation)** — How {charges} are computed
4. **[Using AI Assistance](#using-ai-assistance-for-implementation)** — How to use this doc with Copilot to generate your script

Everything else is reference material for edge cases, troubleshooting, and implementation details.
```

### Overview

```markdown
## Overview

**Goal**: Generate {output description} for ingestion into the FOCUS billing system.

**Data Source**: {System/API/CLI description}

**Billing Model**: {Brief description of how costs are calculated}

**Recommended Language**: {Python/PowerShell/Bash} ({rationale})
```

### Data Collection Options

Always provide multiple approaches when available:

```markdown
## Data Collection: {System Name}

### Option A: {Preferred Method}

{Description and examples}

### Option B: {Alternative Method}

{Description and examples}

### Key Fields

| Field | Description |
|-------|-------------|
| `field_name` | What it represents |
```

### Metadata Section

```markdown
## {Resource} Metadata

Each {resource} must have billing metadata attached via {mechanism}.

### Option A: {Primary Method}

| Purpose | Required | Description |
|---------|----------|-------------|
| PI Email | Yes | PI's university email address |
| Project ID | Yes | Project identifier |
| Fund/Org | Yes | Fund/org code for journal entries |
| {Resource-specific fields} | {Yes/No} | {Description} |

The actual field/tag names are up to you—use whatever naming convention fits your environment.

### Option B: {Alternative Method}

{Description with examples}

### Validation Recommendations

Your script should verify:
- {Validation check 1}
- {Validation check 2}
- {etc.}
```

### Output Format

Use the standard FOCUS CSV table:

```markdown
## Output Format: FOCUS CSV

The billing system expects a CSV file with these columns:

| Column | Required | Description |
|--------|----------|-------------|
| `BillingPeriodStart` | Yes | First day of billing period (YYYY-MM-DD) |
| `BillingPeriodEnd` | Yes | Last day of billing period (YYYY-MM-DD) |
| `ChargePeriodStart` | Yes | Start of this specific charge |
| `ChargePeriodEnd` | Yes | End of this specific charge |
| `ListCost` | No | Retail/list price |
| `ContractedCost` | No | Contracted price |
| `BilledCost` | Yes | Actual amount to bill |
| `EffectiveCost` | No | Cost after credits/adjustments |
| `ResourceId` | No | Unique identifier |
| `ResourceName` | No | Human-readable name |
| `ServiceName` | Yes | Service category |
| `Tags` | Yes | JSON object with billing metadata |

### Tags JSON Structure

```json
{
  "pi_email": "user@example.edu",
  "project_id": "project-name",
  "fund_org": "FUND-CODE"
}
```
```

### Cost Calculation

Always show formulas with worked examples:

```markdown
## Cost Calculation

### {Rate Type} Formula

```
formula = variables * rate
```

### {Worked Example Title}

```
# Example: {scenario description}
result = {calculation}
```

### {Language} Example

```{language}
# Conceptual example
variable = value
result = calculation
```
```

### Troubleshooting Table

```markdown
## Troubleshooting

### Common Issues

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| {Error/symptom} | {Root cause} | {How to fix} |

### Testing

Before scheduling:
1. Run the script manually for a single {resource}
2. Verify the output CSV format
3. Test ingestion with `focus-billing ingest --dry-run`
4. Run for all {resources} and verify totals
```

### AI Assistance Section

```markdown
## Using AI Assistance for Implementation

You can use an AI coding assistant (Copilot, ChatGPT, etc.) to help build your implementation.

### How to Use This Document with AI

1. **Paste this entire document** into your AI assistant as context
2. **Add the prompt below** after the document
3. **Answer the AI's clarifying questions** about your specific environment
4. **Review the generated code** before deploying

### Sample Prompt for AI Assistant

After pasting this entire specification document, add the following prompt:

```
I need to write a {language} script that runs {frequency} to export {data type}
for billing purposes. Here are the requirements:

**Environment:**
- {System} at {placeholder}
- {Resource location/structure}
- Script will run {manually/scheduled}

**Metadata Location:**
- {Where metadata is stored}
- Required fields: {list}
- Optional: {list}

**Output Requirements:**
- CSV file with columns: BillingPeriodStart, BillingPeriodEnd,
  ChargePeriodStart, ChargePeriodEnd, ListCost, BilledCost, ResourceId,
  ResourceName, ServiceName, Tags
- Tags column must be JSON with pi_email, project_id, fund_org
- {Output granularity}
- {Cost formula}

**Cost Parameters:**
- {Rate placeholder}: $[YOUR_RATE]

**Error Handling:**
- Skip {resources} with missing/invalid metadata (log warning)
- Skip {resources} where active = false
- Log all errors but don't fail the entire export
- Write summary at end

Before writing code, ask me clarifying questions about:
1. {Environment-specific question}
2. {Authentication question}
3. {Metadata field names question}
4. {Logging/output location question}
5. Any other details you need
```

### Questions the AI Should Ask You

Be prepared to answer:

| Topic | What to Know |
|-------|--------------|
| {Topic 1} | {What they need to decide} |
| {Topic 2} | {What they need to decide} |

### Tips for Working with the AI

1. **Be specific about your environment** - {examples}
2. **Ask it to explain trade-offs** - "Why did you choose X over Y?"
3. **Request incremental builds** - "First show me just the {component}"
4. **Ask for error handling** - "What happens if {failure scenario}?"
5. **Request tests** - "How would I test this against a single {resource}?"
6. **Review before running** - Have it explain any line you don't understand
```

---

## Style Guidelines

### Tone

- **Reassuring**: Start with "Don't panic"
- **Direct**: Use active voice, imperative mood for instructions
- **Practical**: Focus on what to do, not theory

### Code Examples

- Label as "Conceptual example" — we're showing patterns, not production code
- Use realistic but obviously fake data (martinez.sofia@example.edu, climate-modeling, NSF-ATM-2024)
- Include comments explaining key lines
- For rates/paths/names, use placeholders like `$[YOUR_RATE]` or `[YOUR_CLUSTER]`

### Tables

Use tables for:
- Field/column references
- Permission matrices
- Troubleshooting symptom/cause/resolution
- Questions the AI should ask

### Language Choice

| Platform | Recommended | Rationale |
|----------|-------------|-----------|
| Windows-only (AD, Hyper-V, etc.) | PowerShell | Native, well-supported |
| Linux/cross-platform | Python | Readable, maintainable |
| Simple text processing | Bash | Ubiquitous, fast |

### Placeholder Conventions

| Placeholder | Use For |
|-------------|---------|
| `[YOUR_RATE]` | Cost rates |
| `[YOUR_CLUSTER]` | Server/cluster names |
| `{project_id}` | Variable substitution in paths |
| `$placeholder` | Environment variables |

---

## Checklist for New Guides

Before publishing a new implementation guide, verify:

- [ ] Title follows pattern: `{System} {Resource} Export Guide`
- [ ] "Don't panic" callout at top
- [ ] Must-Read Sections with 4 anchor links
- [ ] Overview with Goal, Data Source, Billing Model
- [ ] Multiple data collection options (when applicable)
- [ ] Metadata section with field names as "up to you"
- [ ] Standard FOCUS CSV output table
- [ ] Example output with realistic fake data
- [ ] Cost calculation with formulas AND worked examples
- [ ] Implementation guidelines (numbered sections)
- [ ] Troubleshooting table with common issues
- [ ] File delivery options
- [ ] AI assistance section with:
  - [ ] Paste-the-doc instructions
  - [ ] Sample prompt with placeholders
  - [ ] "Questions AI should ask" table
  - [ ] Tips for working with AI
- [ ] Contact section at end

---

## Example Guides

Reference these existing guides for patterns:

| Guide | Data Source | Language | Frequency |
|-------|-------------|----------|-----------|
| [qumulo-storage-export-guide.md](qumulo-storage-export-guide.md) | Qumulo file server | PowerShell | Nightly |
| [azure-local-vm-export-guide.md](azure-local-vm-export-guide.md) | Azure Local VMs | PowerShell | Monthly |
| [hpc-slurm-isilon-export-guide.md](hpc-slurm-isilon-export-guide.md) | Slurm + Isilon | Python | Monthly |
