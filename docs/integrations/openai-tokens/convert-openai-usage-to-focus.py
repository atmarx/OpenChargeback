#!/usr/bin/env python3
import json
import argparse
from calendar import monthrange
from datetime import datetime
from pathlib import Path

import pandas as pd

# -----------------------------
# Argument parsing
# -----------------------------
parser = argparse.ArgumentParser(
    description="Convert OpenAI EDU usage CSV to FOCUS-format CSV"
)
parser.add_argument(
    "--input",
    required=True,
    help="Path to OpenAI usage CSV file"
)
parser.add_argument(
    "--output",
    required=False,
    help="Path to output FOCUS CSV file"
)

args = parser.parse_args()

input_csv = Path(args.input)
df = pd.read_csv(input_csv)

# -----------------------------
# Determine output filename
# -----------------------------
if args.output:
    output_csv = Path(args.output)
else:
    # Validate that usage covers exactly one month
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
# Config paths (static for MVP)
# -----------------------------
PRICING_JSON = "pricing.json"
PROJECTS_JSON = "projects.json"

# -----------------------------
# Load pricing config
# -----------------------------
with open(PRICING_JSON) as f:
    pricing = json.load(f)

pool = pricing["credit_pools"][0]
unit_cost = pool["purchase_amount"] / pool["credits_purchased"]

print(f"INFO: Derived unit cost = ${unit_cost:.2f} per credit")

# -----------------------------
# Load project attribution
# -----------------------------
with open(PROJECTS_JSON) as f:
    projects_cfg = json.load(f)

user_to_project = {}
project_lookup = {}

for project in projects_cfg["projects"]:
    project_lookup[project["project_id"]] = project
    for user in project["users"]:
        user_to_project[user["email"]] = project["project_id"]

# -----------------------------
# Load usage CSV
# -----------------------------
df = pd.read_csv(input_csv)

focus_rows = []
warnings = 0

for _, row in df.iterrows():
    usage_date = pd.to_datetime(row["date_partition"])
    service_date = usage_date.date().isoformat()
    user_email = row["email"]
    usage_type = row["usage_type"]
    credits = float(row["usage_credits"])

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

    cost = round(credits * unit_cost, 2)

    tags = {
        "pi_email": pi_email,
        "project_id": project_id,
        "fund_org": fund_org,
        "usage_user": user_email
    }

    # Calculate last day of the billing month
    last_day = monthrange(usage_date.year, usage_date.month)[1]

    focus_rows.append({
        "BillingPeriodStart": usage_date.replace(day=1).date().isoformat(),
        "BillingPeriodEnd": usage_date.replace(day=last_day).date().isoformat(),
        "ChargePeriodStart": usage_date.date().isoformat(),
        "ChargePeriodEnd": usage_date.date().isoformat(),
        "ServiceName": "OpenAI",
        "ResourceName": f"OpenAI {usage_type} ({service_date}, user: {user_email})",
        "ListCost": cost,
        "BilledCost": cost,
        "ResourceId": f"openai:{usage_type}:{user_email}:{service_date}",
        "Tags": json.dumps(tags)
    })

# -----------------------------
# Write FOCUS CSV
# -----------------------------
focus_df = pd.DataFrame(focus_rows)
focus_df.to_csv(output_csv, index=False)

print(f"INFO: Wrote {len(focus_rows)} FOCUS rows to {output_csv}")
print(f"INFO: {warnings} warning(s) emitted")
