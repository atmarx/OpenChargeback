# Licensing and Commercialization Discussion

*Captured from development session - January 2026*

## Copyright and Licensing Strategy

### Retaining Copyright

Since this tool is being developed on personal time using personal equipment, the author retains full copyright. Even when working at a university, work created outside of employment duties belongs to the creator.

**Recommended approach:**
1. Keep copyright in your name
2. License to the university under MIT (or similar permissive license)
3. Release as open source for the community

### Why MIT License?

MIT is ideal for this project because:
- **Maximum adoption**: No friction for other universities to use and contribute
- **Commercial-friendly**: Allows future SaaS commercialization
- **Simple**: Easy to understand, widely accepted
- **Compatible**: Works with almost any other license

### Dual Licensing for Commercial Use

Once released under MIT, you can:
- Continue developing the open source version
- Build a commercial SaaS product based on the same codebase
- Offer enterprise features, support, and hosting as a paid service

**Important considerations:**
- Contributions from others are also MIT-licensed, so you can use them commercially
- Consider a Contributor License Agreement (CLA) if you want explicit permission
- The "open core" model works well: free CLI tool, paid hosted platform

---

## SaaS Commercialization Path

### Market Opportunity

This tool addresses a common pain point for research computing centers:
- Every university with HPC/cloud resources faces the same chargeback challenges
- Current solutions are either expensive enterprise platforms or homegrown scripts
- A lightweight, focused tool fills a gap in the market

### Competitive Landscape

**Kion.io** (formerly cloudtamer.io):
- Full cloud management platform
- Enterprise pricing, complex implementation
- Overkill for many research computing centers

**FOCUS Billing positioning:**
- Lightweight alternative focused specifically on research computing
- FOCUS-native (industry standard format)
- Self-hosted option for compliance-sensitive institutions
- Lower cost, simpler implementation

### Architecture Recommendations

**Backend:**
- **FastAPI** (Python) - Natural fit given existing Python codebase
- Async support for handling large imports
- Easy to add REST API layer to existing CLI

**Frontend:**
- **Nuxt 4** - Modern Vue.js framework, excellent DX
- SSR for initial load, SPA for interactions
- Good ecosystem for dashboards and data visualization

**Database:**
- **PostgreSQL** - Upgrade from SQLite for production
- Row-level security for multi-tenancy
- JSONB for flexible tag storage
- Proven scale for SaaS workloads

### Migration Path

```
Phase 1: CLI Tool (Current)
├── SQLite database
├── Local PDF generation
└── Manual CSV exports

Phase 2: Self-Hosted Web
├── PostgreSQL database
├── FastAPI REST API
├── Basic web dashboard
└── Same deployment model

Phase 3: SaaS Platform
├── Multi-tenant PostgreSQL
├── User authentication
├── Automated imports (cloud APIs)
├── Subscription billing
└── Enterprise features
```

---

## Compliance Requirements for Higher Ed SaaS

### SOC 2 Type II

Required for handling financial/billing data:
- Security controls documentation
- Annual audits by third party
- Continuous monitoring requirements

**Estimated timeline:** 6-12 months, $20-50K for initial audit

### HECVAT (Higher Education Community Vendor Assessment Toolkit)

Standard questionnaire for higher ed vendors:
- Security practices
- Data handling
- Privacy controls
- Incident response

**Advantage:** Self-hosted option can shift compliance burden to institution

### SBOM (Software Bill of Materials)

Increasingly required for government-funded institutions:
- List all dependencies and versions
- Automated generation via tools like `syft` or `cyclonedx`
- Include in release artifacts

### FedRAMP (If Targeting Federal Research)

Only needed for federal agencies/labs:
- Significant investment ($500K+)
- Consider later if demand warrants

### Compliance Strategy

**Recommended approach:**
1. Offer **self-hosted** option for institutions that can't use SaaS
2. Complete **HECVAT** early (low cost, high value for higher ed sales)
3. Pursue **SOC 2** when revenue justifies the investment
4. Generate **SBOMs** from day one (easy, good practice)

---

## Data Transforms Feature

### Use Case

Incoming FOCUS data often needs normalization:
- Email addresses in different cases (`Smith@edu` vs `smith@edu`)
- Project IDs with varying formats
- Service names that need mapping

### Implementation Options

**Option A: CLI Flags (Simple)**
```bash
focus-billing ingest data.csv --lowercase-emails --map-services ./mapping.csv
```

**Option B: Config-based Rules**
```yaml
transforms:
  - field: pi_email
    type: lowercase
  - field: project_id
    type: regex
    pattern: "^proj-"
    replacement: ""
```

**Option C: Web UI (SaaS Feature)**
- Visual rule builder
- Preview transformations before applying
- Save as reusable profiles per data source

### Recommendation

Keep CLI simple with basic transforms. Save complex rule building for the SaaS web interface where visual feedback makes it practical.

*Added to Future Roadmap in README.md*

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| License | MIT | Maximum adoption, commercial-friendly |
| Copyright | Personal | Work done on personal time |
| Web Framework | FastAPI + Nuxt 4 | Python backend matches CLI, modern frontend |
| Database | PostgreSQL | Multi-tenant ready, proven scale |
| Compliance Priority | HECVAT first | Low cost, high value for higher ed |
| Self-hosted | Yes | Compliance advantage, trust builder |

---

## Resources

- [FOCUS Specification](https://focus.finops.org/)
- [Kion Platform](https://kion.io/platform/) (competitor reference)
- [HECVAT](https://library.educause.edu/resources/2020/4/higher-education-community-vendor-assessment-toolkit)
- [SOC 2 Overview](https://www.aicpa.org/soc-for-service-organizations)
