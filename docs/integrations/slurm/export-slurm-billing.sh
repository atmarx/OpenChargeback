#!/bin/bash
#
# export-slurm-billing.sh - Export FOCUS-format billing data from Slurm
#
# Queries Slurm accounting database via sacct and generates FOCUS-compatible
# CSV for import into billing systems.
#
# Usage:
#   ./export-slurm-billing.sh --period 2025-01
#   ./export-slurm-billing.sh --period 2025-01 --whatif
#   ./export-slurm-billing.sh --period 2025-01 --config-dir /etc/slurm-billing
#
# Dependencies: jq, sacct (Slurm)
#

set -euo pipefail

#------------------------------------------------------------------------------
# Defaults
#------------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${SCRIPT_DIR}/config"
OUTPUT_DIR="${SCRIPT_DIR}/output"
PERIOD=""
WHATIF=false
VERBOSE=false

#------------------------------------------------------------------------------
# Usage
#------------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Export FOCUS-format billing data from Slurm.

Options:
  --period YYYY-MM    Billing period (required)
  --config-dir DIR    Config directory (default: ./config)
  --output-dir DIR    Output directory (default: ./output)
  --whatif            Dry run - output JSON analysis instead of CSV
  --verbose           Enable verbose output
  --help              Show this help message

Examples:
  $(basename "$0") --period 2025-01
  $(basename "$0") --period 2025-01 --whatif
  $(basename "$0") --period 2025-01 --config-dir /etc/slurm-billing
EOF
    exit 1
}

#------------------------------------------------------------------------------
# Logging
#------------------------------------------------------------------------------
log_info() {
    echo "[INFO] $*" >&2
}

log_warn() {
    echo "[WARN] $*" >&2
}

log_error() {
    echo "[ERROR] $*" >&2
}

log_verbose() {
    if [[ "$VERBOSE" == true ]]; then
        echo "[DEBUG] $*" >&2
    fi
}

#------------------------------------------------------------------------------
# Parse arguments
#------------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --period)
            PERIOD="$2"
            shift 2
            ;;
        --config-dir)
            CONFIG_DIR="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --whatif)
            WHATIF=true
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --help|-h)
            usage
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            ;;
    esac
done

#------------------------------------------------------------------------------
# Validate arguments
#------------------------------------------------------------------------------
if [[ -z "$PERIOD" ]]; then
    log_error "--period is required"
    usage
fi

if ! [[ "$PERIOD" =~ ^[0-9]{4}-[0-9]{2}$ ]]; then
    log_error "Period must be in YYYY-MM format"
    exit 1
fi

#------------------------------------------------------------------------------
# Check dependencies
#------------------------------------------------------------------------------
check_dependencies() {
    local missing=()

    if ! command -v jq &>/dev/null; then
        missing+=("jq")
    fi

    if ! command -v sacct &>/dev/null; then
        missing+=("sacct")
    fi

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing dependencies: ${missing[*]}"
        exit 1
    fi
}

#------------------------------------------------------------------------------
# Load configuration
#------------------------------------------------------------------------------
load_config() {
    local tiers_file="${CONFIG_DIR}/tiers.json"
    local accounts_file="${CONFIG_DIR}/accounts.json"

    if [[ ! -f "$tiers_file" ]]; then
        log_error "Tiers config not found: $tiers_file"
        exit 1
    fi

    if [[ ! -f "$accounts_file" ]]; then
        log_error "Accounts config not found: $accounts_file"
        exit 1
    fi

    # Validate JSON
    if ! jq empty "$tiers_file" 2>/dev/null; then
        log_error "Invalid JSON in $tiers_file"
        exit 1
    fi

    if ! jq empty "$accounts_file" 2>/dev/null; then
        log_error "Invalid JSON in $accounts_file"
        exit 1
    fi

    log_verbose "Loaded config from $CONFIG_DIR"
}

#------------------------------------------------------------------------------
# Calculate billing period dates
#------------------------------------------------------------------------------
calculate_period_dates() {
    local year="${PERIOD:0:4}"
    local month="${PERIOD:5:2}"

    PERIOD_START="${year}-${month}-01"

    # Calculate end of month (first day of next month)
    if [[ "$month" == "12" ]]; then
        PERIOD_END="$((year + 1))-01-01"
        PERIOD_END_DISPLAY="${year}-12-31"
    else
        local next_month
        next_month=$(printf "%02d" $((10#$month + 1)))
        PERIOD_END="${year}-${next_month}-01"
        # Calculate last day of current month
        PERIOD_END_DISPLAY=$(date -d "${PERIOD_END} - 1 day" +%Y-%m-%d 2>/dev/null || \
                            date -v-1d -j -f "%Y-%m-%d" "${PERIOD_END}" +%Y-%m-%d 2>/dev/null)
    fi

    log_verbose "Billing period: $PERIOD_START to $PERIOD_END_DISPLAY"
}

#------------------------------------------------------------------------------
# Parse elapsed time to hours
# Formats: MM:SS, HH:MM:SS, D-HH:MM:SS
#------------------------------------------------------------------------------
parse_elapsed_to_hours() {
    local elapsed="$1"
    local days=0
    local hours=0
    local minutes=0
    local seconds=0

    # Handle D-HH:MM:SS format
    if [[ "$elapsed" =~ ^([0-9]+)-(.+)$ ]]; then
        days="${BASH_REMATCH[1]}"
        elapsed="${BASH_REMATCH[2]}"
    fi

    # Split remaining time
    IFS=':' read -ra parts <<< "$elapsed"

    case ${#parts[@]} in
        2)
            minutes="${parts[0]}"
            seconds="${parts[1]}"
            ;;
        3)
            hours="${parts[0]}"
            minutes="${parts[1]}"
            seconds="${parts[2]}"
            ;;
        *)
            echo "0"
            return
            ;;
    esac

    # Remove leading zeros for arithmetic
    days=$((10#$days))
    hours=$((10#$hours))
    minutes=$((10#$minutes))
    seconds=$((10#$seconds))

    # Calculate total hours with decimal precision
    local total_hours
    total_hours=$(echo "scale=6; $days * 24 + $hours + $minutes / 60 + $seconds / 3600" | bc)
    echo "$total_hours"
}

#------------------------------------------------------------------------------
# Query sacct for job data
#------------------------------------------------------------------------------
query_sacct() {
    local tiers_file="${CONFIG_DIR}/tiers.json"

    # Get billable states from config
    local billable_states
    billable_states=$(jq -r '.billableStates | join(",")' "$tiers_file")

    log_info "Querying Slurm accounting for period $PERIOD..."
    log_verbose "Billable states: $billable_states"

    # Query sacct
    # Format: JobID|Account|Partition|AllocCPUS|Elapsed|State
    sacct \
        --starttime="${PERIOD_START}" \
        --endtime="${PERIOD_END}" \
        --format=JobID,Account,Partition,AllocCPUS,Elapsed,State \
        --allocations \
        --parsable2 \
        --noheader \
        --state="$billable_states" \
        2>/dev/null || true
}

#------------------------------------------------------------------------------
# Process jobs and calculate billing
#------------------------------------------------------------------------------
process_jobs() {
    local tiers_file="${CONFIG_DIR}/tiers.json"
    local accounts_file="${CONFIG_DIR}/accounts.json"

    local service_name
    service_name=$(jq -r '.serviceName // "HPC Compute"' "$tiers_file")

    local su_rate
    su_rate=$(jq -r '.rates.suRate // 0.01' "$tiers_file")

    # Get exclude accounts as array
    local exclude_accounts
    exclude_accounts=$(jq -r '.excludeAccounts // [] | .[]' "$tiers_file")

    # Build associative arrays for aggregation
    declare -A account_partition_su
    declare -A account_partition_cpuhours
    declare -A account_partition_jobs

    local total_jobs=0
    local skipped_jobs=0
    local warnings=()

    # Read sacct output
    while IFS='|' read -r jobid account partition alloc_cpus elapsed state; do
        # Skip empty lines
        [[ -z "$jobid" ]] && continue

        # Skip excluded accounts
        local skip=false
        for exc in $exclude_accounts; do
            if [[ "$account" == "$exc" ]]; then
                skip=true
                break
            fi
        done
        if [[ "$skip" == true ]]; then
            ((skipped_jobs++))
            continue
        fi

        ((total_jobs++))

        # Parse elapsed time to hours
        local hours
        hours=$(parse_elapsed_to_hours "$elapsed")

        # Get partition config
        local su_multiplier
        su_multiplier=$(jq -r --arg p "$partition" '.partitions[$p].suMultiplier // 1' "$tiers_file")

        # Check if partition exists in config
        local partition_exists
        partition_exists=$(jq -r --arg p "$partition" 'has("partitions") and (.partitions | has($p))' "$tiers_file")
        if [[ "$partition_exists" != "true" ]]; then
            warnings+=("Unknown partition '$partition' for job $jobid, using default multiplier")
        fi

        # Calculate SU for this job
        local job_su
        job_su=$(echo "scale=6; $alloc_cpus * $hours * $su_multiplier" | bc)

        # Calculate CPU-hours
        local cpu_hours
        cpu_hours=$(echo "scale=6; $alloc_cpus * $hours" | bc)

        # Aggregate by account+partition
        local key="${account}|${partition}"
        local current_su="${account_partition_su[$key]:-0}"
        local current_cpuhours="${account_partition_cpuhours[$key]:-0}"
        local current_jobs="${account_partition_jobs[$key]:-0}"

        account_partition_su[$key]=$(echo "scale=6; $current_su + $job_su" | bc)
        account_partition_cpuhours[$key]=$(echo "scale=6; $current_cpuhours + $cpu_hours" | bc)
        account_partition_jobs[$key]=$((current_jobs + 1))

    done < <(query_sacct)

    log_info "Processed $total_jobs jobs, skipped $skipped_jobs excluded accounts"

    # Output warnings
    for warn in "${warnings[@]:-}"; do
        [[ -n "$warn" ]] && log_warn "$warn"
    done

    # Generate billing records
    local records=()
    local total_list_cost=0
    local total_billed_cost=0
    local unknown_accounts=()

    for key in "${!account_partition_su[@]}"; do
        IFS='|' read -r account partition <<< "$key"

        local su="${account_partition_su[$key]}"
        local cpu_hours="${account_partition_cpuhours[$key]}"
        local job_count="${account_partition_jobs[$key]}"

        # Get partition subsidy
        local subsidy_percent
        subsidy_percent=$(jq -r --arg p "$partition" '.partitions[$p].subsidyPercent // 0' "$tiers_file")

        # Calculate costs
        local list_cost
        list_cost=$(echo "scale=2; $su * $su_rate" | bc)

        local billed_cost
        billed_cost=$(echo "scale=2; $list_cost * (1 - $subsidy_percent / 100)" | bc)

        # Round to 2 decimal places
        list_cost=$(printf "%.2f" "$list_cost")
        billed_cost=$(printf "%.2f" "$billed_cost")

        # Get account metadata
        local pi_email project_id fund_org
        pi_email=$(jq -r --arg a "$account" '.accounts[$a].piEmail // ""' "$accounts_file")
        project_id=$(jq -r --arg a "$account" '.accounts[$a].projectId // ""' "$accounts_file")
        fund_org=$(jq -r --arg a "$account" '.accounts[$a].fundOrg // ""' "$accounts_file")

        # Check for missing metadata
        if [[ -z "$pi_email" || -z "$project_id" ]]; then
            unknown_accounts+=("$account")
            log_warn "Account '$account' not found in accounts.json, using account name as project_id"
            project_id="${project_id:-$account}"
        fi

        # Build Tags JSON
        local tags
        tags=$(jq -n \
            --arg pi "$pi_email" \
            --arg proj "$project_id" \
            --arg fund "$fund_org" \
            '{pi_email: $pi, project_id: $proj, fund_org: $fund}')

        # Build resource ID and name
        local resource_id="${account}-${partition}"
        local resource_name="${account} (${partition})"

        # Partition description for service name suffix
        local partition_desc
        partition_desc=$(jq -r --arg p "$partition" '.partitions[$p].description // $p' "$tiers_file")
        local full_service_name="${service_name} - ${partition_desc}"

        # Accumulate totals
        total_list_cost=$(echo "scale=2; $total_list_cost + $list_cost" | bc)
        total_billed_cost=$(echo "scale=2; $total_billed_cost + $billed_cost" | bc)

        # Store record
        records+=("$(jq -n \
            --arg period_start "$PERIOD_START" \
            --arg period_end "$PERIOD_END_DISPLAY" \
            --arg list_cost "$list_cost" \
            --arg billed_cost "$billed_cost" \
            --arg resource_id "$resource_id" \
            --arg resource_name "$resource_name" \
            --arg service_name "$full_service_name" \
            --argjson tags "$tags" \
            --arg account "$account" \
            --arg partition "$partition" \
            --arg su "$su" \
            --arg cpu_hours "$cpu_hours" \
            --arg job_count "$job_count" \
            --arg subsidy_percent "$subsidy_percent" \
            '{
                BillingPeriodStart: $period_start,
                BillingPeriodEnd: $period_end,
                ChargePeriodStart: $period_start,
                ChargePeriodEnd: $period_end,
                ListCost: ($list_cost | tonumber),
                BilledCost: ($billed_cost | tonumber),
                ResourceId: $resource_id,
                ResourceName: $resource_name,
                ServiceName: $service_name,
                Tags: $tags,
                _meta: {
                    account: $account,
                    partition: $partition,
                    totalSU: ($su | tonumber),
                    cpuHours: ($cpu_hours | tonumber),
                    jobCount: ($job_count | tonumber),
                    subsidyPercent: ($subsidy_percent | tonumber)
                }
            }')")
    done

    # Output results
    if [[ "$WHATIF" == true ]]; then
        output_whatif "${records[@]}" "$total_jobs" "$skipped_jobs" "$total_list_cost" "$total_billed_cost" "${unknown_accounts[@]}"
    else
        output_csv "${records[@]}"
    fi

    # Summary
    local total_subsidy
    total_subsidy=$(echo "scale=2; $total_list_cost - $total_billed_cost" | bc)

    log_info "Summary:"
    log_info "  Total List Cost: \$$total_list_cost"
    log_info "  Total Billed Cost: \$$total_billed_cost"
    log_info "  Total Subsidy: \$$total_subsidy"
    log_info "  Records: ${#records[@]}"
}

#------------------------------------------------------------------------------
# Output CSV
#------------------------------------------------------------------------------
output_csv() {
    local records=("$@")

    mkdir -p "$OUTPUT_DIR"
    local output_file="${OUTPUT_DIR}/slurm_${PERIOD}.csv"

    # Write header
    echo "BillingPeriodStart,BillingPeriodEnd,ChargePeriodStart,ChargePeriodEnd,ListCost,BilledCost,ResourceId,ResourceName,ServiceName,Tags" > "$output_file"

    # Write records
    for record in "${records[@]}"; do
        local period_start period_end list_cost billed_cost resource_id resource_name service_name tags
        period_start=$(echo "$record" | jq -r '.BillingPeriodStart')
        period_end=$(echo "$record" | jq -r '.BillingPeriodEnd')
        list_cost=$(echo "$record" | jq -r '.ListCost')
        billed_cost=$(echo "$record" | jq -r '.BilledCost')
        resource_id=$(echo "$record" | jq -r '.ResourceId')
        resource_name=$(echo "$record" | jq -r '.ResourceName')
        service_name=$(echo "$record" | jq -r '.ServiceName')
        tags=$(echo "$record" | jq -c '.Tags')

        # Escape fields for CSV
        resource_name="${resource_name//\"/\"\"}"
        service_name="${service_name//\"/\"\"}"
        tags="${tags//\"/\"\"}"

        echo "${period_start},${period_end},${period_start},${period_end},${list_cost},${billed_cost},\"${resource_id}\",\"${resource_name}\",\"${service_name}\",\"${tags}\""
    done >> "$output_file"

    log_info "Output written to: $output_file"
}

#------------------------------------------------------------------------------
# Output WhatIf JSON
#------------------------------------------------------------------------------
output_whatif() {
    local total_jobs="$1"
    local skipped_jobs="$2"
    local total_list_cost="$3"
    local total_billed_cost="$4"
    shift 4

    # Remaining args before -- are records, after are unknown accounts
    local records=()
    local unknown_accounts=()
    local in_unknown=false

    for arg in "$@"; do
        if [[ "$arg" == "--" ]]; then
            in_unknown=true
            continue
        fi
        if [[ "$in_unknown" == true ]]; then
            unknown_accounts+=("$arg")
        else
            records+=("$arg")
        fi
    done

    mkdir -p "$OUTPUT_DIR"
    local output_file="${OUTPUT_DIR}/slurm_${PERIOD}_whatif.json"

    # Build JSON output
    {
        echo "{"
        echo "  \"metadata\": {"
        echo "    \"generatedAt\": \"$(date -Iseconds)\","
        echo "    \"billingPeriod\": \"$PERIOD\","
        echo "    \"mode\": \"WhatIf\","
        echo "    \"totalJobs\": $total_jobs,"
        echo "    \"skippedJobs\": $skipped_jobs,"
        echo "    \"recordCount\": ${#records[@]}"
        echo "  },"
        echo "  \"records\": ["

        local first=true
        for record in "${records[@]}"; do
            if [[ "$first" != true ]]; then
                echo ","
            fi
            echo -n "    $record"
            first=false
        done

        echo ""
        echo "  ],"
        echo "  \"unknownAccounts\": $(printf '%s\n' "${unknown_accounts[@]:-}" | jq -R . | jq -s .),"
        echo "  \"totals\": {"
        echo "    \"listCost\": $total_list_cost,"
        echo "    \"billedCost\": $total_billed_cost,"
        echo "    \"subsidyAmount\": $(echo "scale=2; $total_list_cost - $total_billed_cost" | bc)"
        echo "  }"
        echo "}"
    } > "$output_file"

    log_info "WhatIf output written to: $output_file"
}

#------------------------------------------------------------------------------
# Main
#------------------------------------------------------------------------------
main() {
    log_info "Starting Slurm billing export for period $PERIOD"

    check_dependencies
    load_config
    calculate_period_dates
    process_jobs

    log_info "Export complete"
}

main
