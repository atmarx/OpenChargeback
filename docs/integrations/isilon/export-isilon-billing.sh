#!/bin/bash
#
# export-isilon-billing.sh - Export FOCUS-format billing data from Isilon storage
#
# Queries Isilon quota data and generates FOCUS-compatible CSV for import
# into billing systems.
#
# Usage:
#   ./export-isilon-billing.sh --period 2025-01
#   ./export-isilon-billing.sh --period 2025-01 --whatif
#   ./export-isilon-billing.sh --period 2025-01 --quota-file quotas.json
#
# Dependencies: jq
# Optional: isi CLI (if querying Isilon directly)
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
QUOTA_FILE=""  # Optional: read from file instead of isi command

#------------------------------------------------------------------------------
# Usage
#------------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Export FOCUS-format billing data from Isilon storage quotas.

Options:
  --period YYYY-MM    Billing period (required)
  --config-dir DIR    Config directory (default: ./config)
  --output-dir DIR    Output directory (default: ./output)
  --quota-file FILE   Read quota data from JSON file instead of isi command
  --whatif            Dry run - output JSON analysis instead of CSV
  --verbose           Enable verbose output
  --help              Show this help message

Examples:
  $(basename "$0") --period 2025-01
  $(basename "$0") --period 2025-01 --whatif
  $(basename "$0") --period 2025-01 --quota-file /tmp/quotas.json
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
        --quota-file)
            QUOTA_FILE="$2"
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
    if ! command -v jq &>/dev/null; then
        log_error "Missing dependency: jq"
        exit 1
    fi

    # Check for isi command only if not using quota file
    if [[ -z "$QUOTA_FILE" ]] && ! command -v isi &>/dev/null; then
        log_warn "isi command not found. Use --quota-file to provide quota data."
        log_error "Cannot proceed without isi command or quota file"
        exit 1
    fi
}

#------------------------------------------------------------------------------
# Load configuration
#------------------------------------------------------------------------------
load_config() {
    local rates_file="${CONFIG_DIR}/rates.json"
    local projects_file="${CONFIG_DIR}/projects.json"

    if [[ ! -f "$rates_file" ]]; then
        log_error "Rates config not found: $rates_file"
        exit 1
    fi

    if [[ ! -f "$projects_file" ]]; then
        log_error "Projects config not found: $projects_file"
        exit 1
    fi

    # Validate JSON
    if ! jq empty "$rates_file" 2>/dev/null; then
        log_error "Invalid JSON in $rates_file"
        exit 1
    fi

    if ! jq empty "$projects_file" 2>/dev/null; then
        log_error "Invalid JSON in $projects_file"
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

    # Calculate end of month
    if [[ "$month" == "12" ]]; then
        PERIOD_END_DISPLAY="${year}-12-31"
    else
        local next_month
        next_month=$(printf "%02d" $((10#$month + 1)))
        local period_end="${year}-${next_month}-01"
        PERIOD_END_DISPLAY=$(date -d "${period_end} - 1 day" +%Y-%m-%d 2>/dev/null || \
                            date -v-1d -j -f "%Y-%m-%d" "${period_end}" +%Y-%m-%d 2>/dev/null)
    fi

    log_verbose "Billing period: $PERIOD_START to $PERIOD_END_DISPLAY"
}

#------------------------------------------------------------------------------
# Get quota data
#------------------------------------------------------------------------------
get_quota_data() {
    if [[ -n "$QUOTA_FILE" ]]; then
        if [[ ! -f "$QUOTA_FILE" ]]; then
            log_error "Quota file not found: $QUOTA_FILE"
            exit 1
        fi
        cat "$QUOTA_FILE"
    else
        # Query Isilon directly
        log_info "Querying Isilon quotas..."
        isi quota quotas list --format=json 2>/dev/null
    fi
}

#------------------------------------------------------------------------------
# Process quotas and calculate billing
#------------------------------------------------------------------------------
process_quotas() {
    local rates_file="${CONFIG_DIR}/rates.json"
    local projects_file="${CONFIG_DIR}/projects.json"

    local service_name
    service_name=$(jq -r '.serviceName // "HPC Storage - Project"' "$rates_file")

    local rate_per_tb
    rate_per_tb=$(jq -r '.ratePerTBMonth // 10.00' "$rates_file")

    local free_gb
    free_gb=$(jq -r '.freeGBPerProject // 500' "$rates_file")

    log_info "Processing storage quotas..."
    log_verbose "Rate: \$${rate_per_tb}/TB/month, Free tier: ${free_gb} GB"

    local quota_data
    quota_data=$(get_quota_data)

    local records=()
    local total_list_cost=0
    local total_billed_cost=0
    local unknown_paths=()
    local processed_count=0
    local skipped_count=0

    # Process each quota
    # Isilon JSON format: {"quotas": [{"path": "/ifs/...", "usage": {...}, ...}]}
    local quota_count
    quota_count=$(echo "$quota_data" | jq '.quotas | length')

    for ((i=0; i<quota_count; i++)); do
        local quota
        quota=$(echo "$quota_data" | jq ".quotas[$i]")

        local path
        path=$(echo "$quota" | jq -r '.path')

        # Get usage in bytes (Isilon stores in usage.logical or usage.physical)
        local usage_bytes
        usage_bytes=$(echo "$quota" | jq -r '.usage.logical // .usage.physical // .usage // 0')

        # Skip if no usage
        if [[ "$usage_bytes" == "0" || "$usage_bytes" == "null" ]]; then
            ((skipped_count++))
            continue
        fi

        # Look up project metadata
        local pi_email project_id fund_org
        pi_email=$(jq -r --arg p "$path" '.projects[$p].piEmail // ""' "$projects_file")
        project_id=$(jq -r --arg p "$path" '.projects[$p].projectId // ""' "$projects_file")
        fund_org=$(jq -r --arg p "$path" '.projects[$p].fundOrg // ""' "$projects_file")

        # Check if path exists in config
        if [[ -z "$pi_email" || -z "$project_id" ]]; then
            unknown_paths+=("$path")
            log_warn "Path '$path' not found in projects.json"
            # Try to derive project_id from path
            project_id="${project_id:-$(basename "$path")}"
            ((skipped_count++))
            continue
        fi

        ((processed_count++))

        # Convert bytes to GB and TB
        local usage_gb
        usage_gb=$(echo "scale=6; $usage_bytes / 1073741824" | bc)  # 1024^3

        local usage_tb
        usage_tb=$(echo "scale=6; $usage_bytes / 1099511627776" | bc)  # 1024^4

        # Calculate list cost (full price for all storage)
        local list_cost
        list_cost=$(echo "scale=2; $usage_tb * $rate_per_tb" | bc)

        # Calculate billable storage (after free tier)
        local billable_gb
        billable_gb=$(echo "scale=6; if ($usage_gb > $free_gb) $usage_gb - $free_gb else 0" | bc)

        local billable_tb
        billable_tb=$(echo "scale=6; $billable_gb / 1024" | bc)

        # Calculate billed cost
        local billed_cost
        billed_cost=$(echo "scale=2; $billable_tb * $rate_per_tb" | bc)

        # Round to 2 decimal places and ensure non-negative
        list_cost=$(printf "%.2f" "$list_cost")
        billed_cost=$(printf "%.2f" "$billed_cost")

        # Accumulate totals
        total_list_cost=$(echo "scale=2; $total_list_cost + $list_cost" | bc)
        total_billed_cost=$(echo "scale=2; $total_billed_cost + $billed_cost" | bc)

        # Build Tags JSON
        local tags
        tags=$(jq -n \
            --arg pi "$pi_email" \
            --arg proj "$project_id" \
            --arg fund "$fund_org" \
            '{pi_email: $pi, project_id: $proj, fund_org: $fund}')

        # Build resource ID and name
        local resource_id="${project_id}-storage"
        local resource_name="${project_id} Storage"

        # Store record
        records+=("$(jq -n \
            --arg period_start "$PERIOD_START" \
            --arg period_end "$PERIOD_END_DISPLAY" \
            --arg list_cost "$list_cost" \
            --arg billed_cost "$billed_cost" \
            --arg resource_id "$resource_id" \
            --arg resource_name "$resource_name" \
            --arg service_name "$service_name" \
            --argjson tags "$tags" \
            --arg path "$path" \
            --arg usage_gb "$usage_gb" \
            --arg billable_gb "$billable_gb" \
            --arg free_gb "$free_gb" \
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
                    path: $path,
                    usageGB: ($usage_gb | tonumber),
                    billableGB: ($billable_gb | tonumber),
                    freeGB: ($free_gb | tonumber)
                }
            }')")
    done

    log_info "Processed $processed_count quotas, skipped $skipped_count"

    # Output results
    if [[ "$WHATIF" == true ]]; then
        output_whatif "$processed_count" "$skipped_count" "$total_list_cost" "$total_billed_cost" "${records[@]}" "${unknown_paths[@]}"
    else
        output_csv "${records[@]}"
    fi

    # Summary
    local total_subsidy
    total_subsidy=$(echo "scale=2; $total_list_cost - $total_billed_cost" | bc)

    log_info "Summary:"
    log_info "  Total List Cost: \$$total_list_cost"
    log_info "  Total Billed Cost: \$$total_billed_cost"
    log_info "  Total Subsidy (free tier): \$$total_subsidy"
    log_info "  Records: ${#records[@]}"
}

#------------------------------------------------------------------------------
# Output CSV
#------------------------------------------------------------------------------
output_csv() {
    local records=("$@")

    mkdir -p "$OUTPUT_DIR"
    local output_file="${OUTPUT_DIR}/isilon_${PERIOD}.csv"

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
    local processed_count="$1"
    local skipped_count="$2"
    local total_list_cost="$3"
    local total_billed_cost="$4"
    shift 4

    # Collect records and unknown paths
    local records=()
    local unknown_paths=()
    local in_unknown=false

    # Simple approach: all JSON objects are records, strings are unknown paths
    for arg in "$@"; do
        if echo "$arg" | jq -e '.' &>/dev/null 2>&1; then
            records+=("$arg")
        else
            unknown_paths+=("$arg")
        fi
    done

    mkdir -p "$OUTPUT_DIR"
    local output_file="${OUTPUT_DIR}/isilon_${PERIOD}_whatif.json"

    # Build JSON output
    {
        echo "{"
        echo "  \"metadata\": {"
        echo "    \"generatedAt\": \"$(date -Iseconds)\","
        echo "    \"billingPeriod\": \"$PERIOD\","
        echo "    \"mode\": \"WhatIf\","
        echo "    \"quotasProcessed\": $processed_count,"
        echo "    \"quotasSkipped\": $skipped_count,"
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
        echo "  \"unknownPaths\": $(printf '%s\n' "${unknown_paths[@]:-}" | jq -R . | jq -s . 2>/dev/null || echo '[]'),"
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
    log_info "Starting Isilon billing export for period $PERIOD"

    check_dependencies
    load_config
    calculate_period_dates
    process_quotas

    log_info "Export complete"
}

main
