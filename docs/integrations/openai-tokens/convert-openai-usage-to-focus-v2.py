#!/usr/bin/env python3
"""
Convert OpenAI EDU usage CSV to FOCUS-format CSV with subsidy support.

This preprocessor:
1. Loads usage from OpenAI's EDU billing export
2. Attributes charges to projects/PIs
3. Applies subsidy rules (e.g., "Provost covers first $500/project/year")
4. Splits charges between subsidy fund_org and department fund_org
5. Outputs FOCUS-format CSV for import into openchargeback

State is maintained in subsidy_state.json to track running totals across runs.
"""

import json
import argparse
from calendar import monthrange
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass

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
    subsidy_name: str | None = None
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

    args = parser.parse_args()

    input_csv = Path(args.input)
    df = pd.read_csv(input_csv)

    # -----------------------------
    # Determine output filename
    # -----------------------------
    if args.output:
        output_csv = Path(args.output)
    else:
        usage_dates = pd.to_datetime(df["date_partition"])
        year_months = usage_dates.dt.to_period("M").unique()

        if len(year_months) != 1:
            raise ValueError(
                f"ERROR: Input file contains multiple months: "
                f"{', '.join(str(m) for m in year_months)}"
            )

        year_month = year_months[0].strftime("%Y-%m")
        output_csv = Path(f"openai-tokens_{year_month}.csv")

    # -----------------------------
    # Load configs
    # -----------------------------
    with open(args.pricing) as f:
        pricing = json.load(f)

    pool = pricing["credit_pools"][0]
    unit_cost = pool["purchase_amount"] / pool["credits_purchased"]
    print(f"INFO: Derived unit cost = ${unit_cost:.4f} per credit")

    with open(args.projects) as f:
        projects_cfg = json.load(f)

    user_to_project = {}
    project_lookup = {}
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

        # Attribution
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
            subsidy_name=allocation.subsidized_subsidy_name if allocation.subsidized_amount > 0 else None
        ))
        stats["rows_generated"] += 1

        # If there's a subsidy, emit a separate row billing the subsidy provider
        # Provost row: ListCost = BilledCost = subsidized amount
        if allocation.subsidized_amount > 0:
            focus_rows.append(create_focus_row(
                usage_date=usage_date,
                user_email=user_email,
                usage_type=usage_type,
                list_cost=allocation.subsidized_amount,
                billed_cost=allocation.subsidized_amount,
                pi_email=pi_email,  # Still attribute to PI for reporting
                project_id=project_id,
                fund_org=allocation.subsidized_fund_org,  # Provost's fund_org
                charge_type="subsidy",
                subsidy_name=allocation.subsidized_subsidy_name
            ))
            stats["rows_generated"] += 1

        stats["subsidized"] += allocation.subsidized_amount
        stats["billable"] += allocation.billable_amount

    # -----------------------------
    # Write output
    # -----------------------------
    focus_df = pd.DataFrame(focus_rows)
    focus_df.to_csv(output_csv, index=False)

    if not args.dry_run:
        state.save()
        print(f"INFO: State saved to {args.state}")
    else:
        print("INFO: Dry run - state not saved")

    # -----------------------------
    # Summary
    # -----------------------------
    print(f"\n{'='*50}")
    print(f"CONVERSION SUMMARY")
    print(f"{'='*50}")
    print(f"Input rows:      {len(df)}")
    print(f"Output rows:     {stats['rows_generated']}")
    print(f"Total usage:     ${stats['total_usage']:.2f}")
    print(f"  Subsidized:    ${stats['subsidized']:.2f}")
    print(f"  Billable:      ${stats['billable']:.2f}")
    print(f"Warnings:        {warnings}")
    print(f"Output file:     {output_csv}")
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
