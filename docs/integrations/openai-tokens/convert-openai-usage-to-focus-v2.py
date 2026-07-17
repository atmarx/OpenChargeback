#!/usr/bin/env python3
"""
Convert OpenAI EDU usage CSV to FOCUS-format CSV with subsidy support.

This preprocessor:
1. Loads usage from OpenAI's EDU billing export
2. Attributes charges to a fund/org and Principal Invoicee, one of two ways:
   - flat file (the original method): projects.json maps users to projects/PIs
   - directory API (--directory/--fund-orgs): license -> fund/org -> Principal
     Invoicee, with master_fund_org catching any user the directory doesn't know
3. Applies subsidy rules (e.g., "Provost covers first $500/fund/year")
4. Splits charges between subsidy fund_org and the PI's fund_org
5. Outputs FOCUS-format CSV for import into openchargeback
6. In directory mode, also emits a per-user showback CSV for the CMDB — each
   user's OWN monthly usage, a line for their license timeline, never a bill

Both attribution methods coexist; the flags pick one per run. The directory-API
contract (lookup shapes, master-fund fallback, showback columns) lives in
directory-api/README.md.

State is maintained in subsidy_state.json to track running totals across runs.
"""

import argparse
import csv
import json
import urllib.request
from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd


# -----------------------------
# Data classes
# -----------------------------
@dataclass
class SubsidyRule:
    name: str
    description: str
    fund_org: str
    type: str  # "per_project_cap"
    cap_amount: float
    period: str  # "fiscal_year" or "calendar_year"
    fiscal_year_start: str  # "07-01" for July 1
    applies_to_services: list[str]
    enabled: bool


@dataclass
class ChargeAllocation:
    """Result of applying subsidy rules to a charge."""
    subsidized_amount: float
    subsidized_fund_org: str | None
    subsidized_subsidy_name: str | None
    billable_amount: float
    billable_fund_org: str


@dataclass
class Attribution:
    """Where one user's usage lands: the fund, its invoicee, and how we got there."""
    username: str
    email: str
    fund_org: str
    pi_email: str  # the first Principal Invoicee — the statement addressee
    project_id: str
    principal_invoicees: str  # every invoicee email, ";"-joined
    routed_to_master: bool
    warning: str | None = None


# -----------------------------
# Directory API (license -> fund/org -> Principal Invoicee)
# -----------------------------
def load_json_source(source: str) -> dict:
    """Load a JSON lookup from a file path or an http(s) URL."""
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=30) as resp:
            return json.load(resp)
    with open(source) as f:
        return json.load(f)


class DirectoryResolver:
    """
    Attribution via the two directory-API lookups instead of projects.json:

      (1) license -> fund/org   (helpdesk/CMDB; keyed by the seat's email)
      (2) fund/org -> Principal Invoicee(s)   (research finance)

    Lookup (1) never answers empty: an unknown user, a license with no
    fund/org, or a fund/org finance doesn't recognize all land on the
    master_fund_org — one hop, so every charge reaches a fund with a human
    attached. "PI" = Principal Invoicee: the fund decides who pays, not the
    user. In this mode project_id IS the fund/org, which keys the subsidy
    state per fund/org — the cap and its rollup follow the fund, not the user.
    """

    def __init__(self, directory_cfg: dict, fund_orgs_cfg: dict):
        master = directory_cfg.get("master_fund_org")
        if not master:
            raise ValueError(
                "directory has no master_fund_org — the license lookup must never "
                "answer empty, so a catch-all fund/org is required"
            )
        self.master_fund_org = master
        self.licenses_by_email = {
            lic["email"]: lic for lic in directory_cfg.get("licenses", [])
        }
        self.funds = {f["fund_org"]: f for f in fund_orgs_cfg.get("fund_orgs", [])}
        master_fund = self.funds.get(master)
        if not master_fund or not master_fund.get("principal_invoicees"):
            raise ValueError(
                f"master fund/org {master} must be in the fund registry with at "
                "least one principal invoicee — it is where unroutable charges land"
            )

    def resolve_fund(self, fund_org: str, context: str) -> tuple[str, list[str], str | None]:
        """
        Resolve a fund/org to its invoicee emails; unknown or invoicee-less
        funds fall back to the master. Returns (fund_org, invoicees, warning).
        """
        fund = self.funds.get(fund_org)
        if fund and fund.get("principal_invoicees"):
            return fund_org, [p["email"] for p in fund["principal_invoicees"]], None
        reason = "is not in the fund registry" if fund is None else "has no principal invoicees"
        master = self.funds[self.master_fund_org]
        return (
            self.master_fund_org,
            [p["email"] for p in master["principal_invoicees"]],
            f"{context}: fund/org {fund_org} {reason}",
        )

    def resolve(self, email: str) -> Attribution:
        """License lookup by the seat's email; every miss routes to the master."""
        lic = self.licenses_by_email.get(email)
        if lic is None:
            # No license at all — the username is unknowable, so best-effort
            # echo the email's local part for the showback line.
            username = email.split("@", 1)[0]
            wanted = self.master_fund_org
            routed = True
            base_warning = f"no license found for user {email}"
        else:
            username = lic.get("username") or email.split("@", 1)[0]
            wanted = lic.get("fund_org") or ""
            if wanted:
                routed = False
                base_warning = None
            else:
                wanted = self.master_fund_org
                routed = True
                base_warning = f"license for {email} has no fund/org"

        fund_org, invoicees, fund_warning = self.resolve_fund(wanted, context=f"user {email}")
        if fund_warning:
            routed = True

        return Attribution(
            username=username,
            email=email,
            fund_org=fund_org,
            pi_email=invoicees[0],
            project_id=fund_org,
            principal_invoicees=";".join(invoicees),
            routed_to_master=routed,
            warning=base_warning or fund_warning,
        )


# -----------------------------
# Fiscal year helpers
# -----------------------------
def get_fiscal_year(date: datetime, fy_start: str) -> str:
    """
    Determine fiscal year for a given date.

    Args:
        date: The date to check
        fy_start: Fiscal year start as "MM-DD" (e.g., "07-01" for July 1)

    Returns:
        Fiscal year string like "FY2026" (the year the FY ends)
    """
    start_month, start_day = map(int, fy_start.split("-"))
    fy_start_this_year = datetime(date.year, start_month, start_day)

    if date >= fy_start_this_year:
        # We're in the FY that ends next calendar year
        return f"FY{date.year + 1}"
    else:
        # We're in the FY that ends this calendar year
        return f"FY{date.year}"


def get_calendar_year(date: datetime) -> str:
    """Get calendar year for a date."""
    return f"CY{date.year}"


# -----------------------------
# State management
# -----------------------------
class SubsidyState:
    """
    Tracks running totals for subsidy calculations.

    State structure:
    {
        "projects": {
            "ai-strategy": {
                "FY2026": {
                    "provost_ai_initiative": {
                        "used": 480.00,
                        "subsidized": 480.00,
                        "remaining": 20.00
                    }
                }
            }
        },
        "last_updated": "2026-01-15T10:30:00"
    }
    """

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.data = self._load()

    def _load(self) -> dict:
        if self.state_file.exists():
            with open(self.state_file) as f:
                return json.load(f)
        return {"projects": {}, "last_updated": None}

    def save(self):
        self.data["last_updated"] = datetime.now().isoformat()
        with open(self.state_file, "w") as f:
            json.dump(self.data, f, indent=2)

    def get_subsidy_remaining(
        self,
        project_id: str,
        period_key: str,
        subsidy_name: str,
        cap_amount: float
    ) -> float:
        """Get remaining subsidy amount for a project in a period."""
        projects = self.data.setdefault("projects", {})
        project = projects.setdefault(project_id, {})
        period = project.setdefault(period_key, {})
        subsidy = period.setdefault(subsidy_name, {
            "used": 0.0,
            "subsidized": 0.0,
            "remaining": cap_amount
        })
        return subsidy["remaining"]

    def apply_subsidy(
        self,
        project_id: str,
        period_key: str,
        subsidy_name: str,
        amount: float,
        cap_amount: float
    ) -> float:
        """
        Apply subsidy to an amount, updating state.

        Returns the subsidized amount (may be less than requested if cap hit).
        """
        remaining = self.get_subsidy_remaining(
            project_id, period_key, subsidy_name, cap_amount
        )

        subsidized = round(min(amount, remaining), 2)

        # Update state
        subsidy = self.data["projects"][project_id][period_key][subsidy_name]
        subsidy["used"] += amount
        subsidy["subsidized"] += subsidized
        subsidy["remaining"] = cap_amount - subsidy["subsidized"]

        return subsidized


# -----------------------------
# Subsidy application
# -----------------------------
def apply_subsidy_rules(
    cost: float,
    service_name: str,
    project_id: str,
    project_fund_org: str,
    charge_date: datetime,
    subsidies: list[SubsidyRule],
    state: SubsidyState
) -> ChargeAllocation:
    """
    Apply subsidy rules to determine charge allocation.

    Returns allocation showing how much goes to subsidy vs department.
    """
    # Find applicable subsidy
    applicable_subsidy = None
    for subsidy in subsidies:
        if not subsidy.enabled:
            continue
        if service_name not in subsidy.applies_to_services:
            continue
        # Could add more filters here (e.g., specific projects)
        applicable_subsidy = subsidy
        break

    if not applicable_subsidy:
        # No subsidy applies - full amount to department
        return ChargeAllocation(
            subsidized_amount=0.0,
            subsidized_fund_org=None,
            subsidized_subsidy_name=None,
            billable_amount=cost,
            billable_fund_org=project_fund_org
        )

    # Determine period key based on subsidy type
    if applicable_subsidy.period == "fiscal_year":
        period_key = get_fiscal_year(charge_date, applicable_subsidy.fiscal_year_start)
    else:
        period_key = get_calendar_year(charge_date)

    # Apply subsidy with state tracking
    subsidized_amount = state.apply_subsidy(
        project_id=project_id,
        period_key=period_key,
        subsidy_name=applicable_subsidy.name,
        amount=cost,
        cap_amount=applicable_subsidy.cap_amount
    )

    billable_amount = round(cost - subsidized_amount, 2)

    return ChargeAllocation(
        subsidized_amount=subsidized_amount,
        subsidized_fund_org=applicable_subsidy.fund_org if subsidized_amount > 0 else None,
        subsidized_subsidy_name=applicable_subsidy.name if subsidized_amount > 0 else None,
        billable_amount=billable_amount,
        billable_fund_org=project_fund_org
    )


# -----------------------------
# Showback (directory mode) — one line per user per month, back to the CMDB
# -----------------------------
def format_credits(credits: float) -> str:
    """Render credits without float fuzz: up to 3 decimals, trailing zeros trimmed."""
    text = f"{credits:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def write_showback_csv(path: Path, showback: dict) -> int:
    """
    Write the per-user showback CSV — each user's OWN usage for the month,
    for the CMDB to attach to their license timeline. Never a bill, never a
    multi-user rollup. amount_usd is gross (list) usage: what they used, not
    what their fund was billed after subsidies. Returns the line count.
    """
    fieldnames = [
        "username", "email", "period", "service",
        "credits", "amount_usd", "fund_org", "status",
    ]
    rows = sorted(showback.values(), key=lambda r: (r["period"], r["username"]))
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                **row,
                "credits": format_credits(row["credits"]),
                "amount_usd": f"{row['amount_usd']:.2f}",
            })
    return len(rows)


# -----------------------------
# FOCUS row generation
# -----------------------------
def create_focus_row(
    usage_date: datetime,
    user_email: str,
    usage_type: str,
    list_cost: float,
    billed_cost: float,
    pi_email: str,
    project_id: str,
    fund_org: str,
    charge_type: str,
    subsidy_name: str | None = None,
    extra_tags: dict[str, str] | None = None
) -> dict:
    """Create a single FOCUS-format row."""
    service_date = usage_date.date().isoformat()

    tags = {
        "pi_email": pi_email,
        "project_id": project_id,
        "fund_org": fund_org,
        "usage_user": user_email,
        "charge_type": charge_type
    }

    if subsidy_name:
        tags["subsidy_name"] = subsidy_name

    if extra_tags:
        tags.update(extra_tags)

    # Make ResourceId unique by including charge_type
    resource_id = f"openai:{usage_type}:{user_email}:{service_date}:{charge_type}"

    # Calculate last day of the billing month
    last_day = monthrange(usage_date.year, usage_date.month)[1]
    billing_period_end = usage_date.replace(day=last_day).date().isoformat()

    return {
        "BillingPeriodStart": usage_date.replace(day=1).date().isoformat(),
        "BillingPeriodEnd": billing_period_end,
        "ChargePeriodStart": service_date,
        "ChargePeriodEnd": service_date,
        "ServiceName": "OpenAI",
        "ResourceName": f"OpenAI {usage_type} (user: {user_email})",
        "ListCost": list_cost,
        "BilledCost": billed_cost,
        "ResourceId": resource_id,
        "Tags": json.dumps(tags)
    }


# -----------------------------
# Main conversion
# -----------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Convert OpenAI EDU usage CSV to FOCUS-format CSV with subsidy support"
    )
    parser.add_argument("--input", required=True, help="Path to OpenAI usage CSV file")
    parser.add_argument("--output", required=False, help="Path to output FOCUS CSV file")
    parser.add_argument("--pricing", default="pricing.json", help="Path to pricing config")
    parser.add_argument("--projects", default="projects.json", help="Path to projects config")
    parser.add_argument("--subsidies", default="subsidies.json", help="Path to subsidies config")
    parser.add_argument("--state", default="subsidy_state.json", help="Path to state file")
    parser.add_argument("--dry-run", action="store_true", help="Don't update state file")
    parser.add_argument(
        "--directory",
        help="Directory lookup (license -> fund/org): file path or http(s) URL. "
             "Enables directory-API mode; projects.json is not used. "
             "See directory-api/README.md"
    )
    parser.add_argument(
        "--fund-orgs",
        help="Fund/org registry (fund/org -> Principal Invoicees): file path or "
             "http(s) URL. Required with --directory"
    )
    parser.add_argument(
        "--showback",
        help="Per-user showback CSV path (directory mode; default: "
             "user-usage-feedback_<YYYY-MM>.csv beside the output)"
    )

    args = parser.parse_args()

    if bool(args.directory) != bool(args.fund_orgs):
        parser.error(
            "--directory and --fund-orgs go together: license -> fund/org -> "
            "Principal Invoicee needs both lookups"
        )

    input_csv = Path(args.input)
    df = pd.read_csv(input_csv)

    # -----------------------------
    # Determine output filenames
    # -----------------------------
    usage_dates = pd.to_datetime(df["date_partition"])
    year_months = usage_dates.dt.to_period("M").unique()

    def single_month(flag: str) -> str:
        if len(year_months) != 1:
            raise ValueError(
                f"ERROR: Input file contains multiple months "
                f"({', '.join(str(m) for m in sorted(year_months))}); "
                f"pass {flag} explicitly."
            )
        return year_months[0].strftime("%Y-%m")

    if args.output:
        output_csv = Path(args.output)
    else:
        output_csv = Path(f"openai-tokens_{single_month('--output')}.csv")

    showback_csv: Path | None = None
    if args.directory:
        if args.showback:
            showback_csv = Path(args.showback)
        else:
            showback_csv = output_csv.parent / (
                f"user-usage-feedback_{single_month('--showback')}.csv"
            )

    # -----------------------------
    # Load configs
    # -----------------------------
    with open(args.pricing) as f:
        pricing = json.load(f)

    pool = pricing["credit_pools"][0]
    unit_cost = pool["purchase_amount"] / pool["credits_purchased"]
    print(f"INFO: Derived unit cost = ${unit_cost:.4f} per credit")

    # Attribution source: the directory API or the flat projects.json.
    # Both methods coexist; the flags pick one per run.
    resolver: DirectoryResolver | None = None
    user_to_project: dict = {}
    project_lookup: dict = {}
    if args.directory:
        resolver = DirectoryResolver(
            load_json_source(args.directory),
            load_json_source(args.fund_orgs),
        )
        print(
            f"INFO: Directory mode — {len(resolver.licenses_by_email)} license(s), "
            f"{len(resolver.funds)} fund/org(s), master fund/org {resolver.master_fund_org}"
        )
    else:
        with open(args.projects) as f:
            projects_cfg = json.load(f)

        for project in projects_cfg["projects"]:
            project_lookup[project["project_id"]] = project
            for user in project["users"]:
                user_to_project[user["email"]] = project["project_id"]

    # Load subsidies (optional)
    subsidies = []
    subsidies_path = Path(args.subsidies)
    if subsidies_path.exists():
        with open(subsidies_path) as f:
            subsidies_cfg = json.load(f)
        for s in subsidies_cfg.get("subsidies", []):
            subsidies.append(SubsidyRule(**s))
        print(f"INFO: Loaded {len(subsidies)} subsidy rule(s)")
    else:
        print("INFO: No subsidies.json found, proceeding without subsidies")

    # Load state
    state = SubsidyState(Path(args.state))

    # -----------------------------
    # Process usage rows
    # -----------------------------
    focus_rows = []
    showback: dict[tuple[str, str], dict] = {}
    warnings = 0
    stats = {
        "total_usage": 0.0,
        "subsidized": 0.0,
        "billable": 0.0,
        "rows_generated": 0
    }

    for _, row in df.iterrows():
        usage_date = pd.to_datetime(row["date_partition"])
        user_email = row["email"]
        usage_type = row["usage_type"]
        credits = float(row["usage_credits"])
        cost = round(credits * unit_cost, 2)

        stats["total_usage"] += cost

        # Attribution — directory mode resolves license -> fund -> invoicee;
        # flat mode keeps the original projects.json behavior.
        extra_tags = None
        if resolver is not None:
            att = resolver.resolve(user_email)
            if att.warning:
                warnings += 1
                print(
                    f"WARNING: {att.warning}; "
                    f"routed to master fund/org {resolver.master_fund_org}"
                )
            pi_email = att.pi_email
            project_id = att.project_id  # the fund/org — subsidy caps key on it
            fund_org = att.fund_org
            extra_tags = {"principal_invoicees": att.principal_invoicees}

            # Accumulate this user's own usage for the showback line. Gross
            # (list) cost on purpose: it shows what they used, not what their
            # fund was billed after subsidies.
            period = usage_date.strftime("%Y-%m")
            line = showback.setdefault((user_email, period), {
                "username": att.username,
                "email": user_email,
                "period": period,
                "service": "OpenAI",
                "credits": 0.0,
                "amount_usd": 0.0,
                "fund_org": att.fund_org,
                "status": "routed_to_master" if att.routed_to_master else "charged",
            })
            line["credits"] += credits
            line["amount_usd"] += cost
        else:
            project_id = user_to_project.get(user_email, "unassigned")

            if project_id == "unassigned":
                warnings += 1
                print(f"WARNING: No project mapping for user {user_email}")
                pi_email = "unassigned"
                fund_org = "unassigned"
            else:
                project = project_lookup[project_id]
                pi_email = project["pi_email"]
                fund_org = project["fund_org"]

        # Apply subsidy rules
        allocation = apply_subsidy_rules(
            cost=cost,
            service_name="OpenAI",
            project_id=project_id,
            project_fund_org=fund_org,
            charge_date=usage_date.to_pydatetime(),
            subsidies=subsidies,
            state=state
        )

        # Generate FOCUS rows based on allocation
        # Always emit a PI row showing full usage with any subsidy as discount
        # PI row: ListCost = full usage, BilledCost = what PI owes (after subsidy)
        focus_rows.append(create_focus_row(
            usage_date=usage_date,
            user_email=user_email,
            usage_type=usage_type,
            list_cost=cost,  # Full usage amount
            billed_cost=allocation.billable_amount,  # What PI actually owes
            pi_email=pi_email,
            project_id=project_id,
            fund_org=allocation.billable_fund_org,  # PI's department
            charge_type="usage",
            subsidy_name=allocation.subsidized_subsidy_name if allocation.subsidized_amount > 0 else None,
            extra_tags=extra_tags
        ))
        stats["rows_generated"] += 1

        # If there's a subsidy, emit a separate row billing the subsidy provider
        # Provost row: ListCost = BilledCost = subsidized amount
        if allocation.subsidized_amount > 0:
            subsidy_fund_org = allocation.subsidized_fund_org
            subsidy_pi_email = pi_email  # flat mode: attribute to PI for reporting
            subsidy_extra = extra_tags
            if resolver is not None:
                # The fund decides who pays — including the subsidy fund. Its
                # own invoicee gets the subsidy statement; project_id stays the
                # SUBSIDIZED fund, so their statement rolls up one line per
                # fund whose cap the subsidy absorbed (never per user/usage).
                subsidy_fund_org, sub_invoicees, sub_warning = resolver.resolve_fund(
                    allocation.subsidized_fund_org,
                    context=f"subsidy '{allocation.subsidized_subsidy_name}'",
                )
                if sub_warning:
                    warnings += 1
                    print(
                        f"WARNING: {sub_warning}; "
                        f"routed to master fund/org {resolver.master_fund_org}"
                    )
                subsidy_pi_email = sub_invoicees[0]
                subsidy_extra = {"principal_invoicees": ";".join(sub_invoicees)}

            focus_rows.append(create_focus_row(
                usage_date=usage_date,
                user_email=user_email,
                usage_type=usage_type,
                list_cost=allocation.subsidized_amount,
                billed_cost=allocation.subsidized_amount,
                pi_email=subsidy_pi_email,
                project_id=project_id,
                fund_org=subsidy_fund_org,  # the subsidy provider's fund_org
                charge_type="subsidy",
                subsidy_name=allocation.subsidized_subsidy_name,
                extra_tags=subsidy_extra
            ))
            stats["rows_generated"] += 1

        stats["subsidized"] += allocation.subsidized_amount
        stats["billable"] += allocation.billable_amount

    # -----------------------------
    # Write output
    # -----------------------------
    focus_df = pd.DataFrame(focus_rows)
    focus_df.to_csv(output_csv, index=False)

    showback_count = 0
    if showback_csv is not None:
        showback_count = write_showback_csv(showback_csv, showback)

    if not args.dry_run:
        state.save()
        print(f"INFO: State saved to {args.state}")
    else:
        print("INFO: Dry run - state not saved")

    # -----------------------------
    # Summary
    # -----------------------------
    print(f"\n{'='*50}")
    print("CONVERSION SUMMARY")
    print(f"{'='*50}")
    print(f"Input rows:      {len(df)}")
    print(f"Output rows:     {stats['rows_generated']}")
    print(f"Total usage:     ${stats['total_usage']:.2f}")
    print(f"  Subsidized:    ${stats['subsidized']:.2f}")
    print(f"  Billable:      ${stats['billable']:.2f}")
    print(f"Warnings:        {warnings}")
    print(f"Output file:     {output_csv}")
    if showback_csv is not None:
        routed = sum(
            1 for line in showback.values() if line["status"] == "routed_to_master"
        )
        print(f"Showback:        {showback_count} user-month line(s) -> {showback_csv}")
        print(f"Routed to master: {routed} user-month line(s)")
    print(f"{'='*50}\n")

    # Show subsidy state for affected projects
    if subsidies:
        print("SUBSIDY STATUS BY PROJECT:")
        for project_id, periods in state.data.get("projects", {}).items():
            for period_key, subs in periods.items():
                for sub_name, sub_state in subs.items():
                    print(f"  {project_id} ({period_key}, {sub_name}):")
                    print(f"    Used:       ${sub_state['used']:.2f}")
                    print(f"    Subsidized: ${sub_state['subsidized']:.2f}")
                    print(f"    Remaining:  ${sub_state['remaining']:.2f}")


if __name__ == "__main__":
    main()
