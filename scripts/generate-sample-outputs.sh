#!/bin/bash
# Generate sample outputs from sample input data
# This script resets the database and generates a fresh set of outputs
# for demonstration purposes.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

CONFIG="config.example.yaml"
PERIOD="2025-01"

echo "=== OpenChargeback Sample Output Generator ==="
echo ""

# Activate virtual environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "ERROR: Virtual environment not found. Run 'python -m venv .venv && pip install -e .'"
    exit 1
fi

# Enable dev_mode so emails are written to files instead of sent via SMTP
# Save original value and restore at the end
ORIG_DEV_MODE=$(grep -E "^dev_mode:" "$CONFIG" | awk '{print $2}')
sed -i 's/^dev_mode: .*/dev_mode: true/' "$CONFIG"

# Cleanup function to restore config on exit
cleanup() {
    sed -i "s/^dev_mode: .*/dev_mode: $ORIG_DEV_MODE/" "$CONFIG"
}
trap cleanup EXIT

# Step 1: Reset database
echo "Step 1: Resetting database..."
rm -f instance/billing.db
rm -rf instance/output/emails
echo "  Database cleared."

# Step 2: Ingest all 2025-01 sample files
echo ""
echo "Step 2: Ingesting sample data for period $PERIOD..."
for f in sample_data/inputs/*_${PERIOD}.csv; do
    if [ -f "$f" ]; then
        # Extract source name from filename (e.g., aws_2025-01.csv -> aws)
        srcname=$(basename "$f" | sed "s/_${PERIOD}.csv//")
        echo "  Ingesting $srcname..."
        openchargeback ingest "$f" -s "$srcname" -p "$PERIOD" -c "$CONFIG" > /dev/null
    fi
done

# Step 3: Generate statements and send emails (dev_mode saves to files)
echo ""
echo "Step 3: Generating PDF statements and emails..."
openchargeback generate -p "$PERIOD" -c "$CONFIG" --send

# Step 4: Export journal
echo ""
echo "Step 4: Exporting journal (GL format)..."
openchargeback export-journal -p "$PERIOD" -f gl -c "$CONFIG"

# Step 5: Copy outputs to sample_data/outputs
echo ""
echo "Step 5: Copying outputs to sample_data/outputs/..."
rm -rf sample_data/outputs/pdfs sample_data/outputs/journals sample_data/outputs/emails
mkdir -p sample_data/outputs/pdfs sample_data/outputs/journals sample_data/outputs/emails

# Copy PDFs
if [ -d "instance/output/pdfs" ] && [ "$(ls -A instance/output/pdfs 2>/dev/null)" ]; then
    cp instance/output/pdfs/*.pdf sample_data/outputs/pdfs/ 2>/dev/null || true
    echo "  Copied $(ls sample_data/outputs/pdfs/*.pdf 2>/dev/null | wc -l) PDF files"
fi

# Copy journals
if [ -d "instance/output/journals" ] && [ "$(ls -A instance/output/journals 2>/dev/null)" ]; then
    cp instance/output/journals/*.csv sample_data/outputs/journals/ 2>/dev/null || true
    echo "  Copied $(ls sample_data/outputs/journals/*.csv 2>/dev/null | wc -l) journal files"
fi

# Copy emails
if [ -d "instance/output/emails" ] && [ "$(ls -A instance/output/emails 2>/dev/null)" ]; then
    cp instance/output/emails/*.html sample_data/outputs/emails/ 2>/dev/null || true
    echo "  Copied $(ls sample_data/outputs/emails/*.html 2>/dev/null | wc -l) email files"
fi

echo ""
echo "=== Done! ==="
echo ""
echo "Sample outputs are in sample_data/outputs/"
echo "  - pdfs/      : Statement PDFs for each PI/project"
echo "  - journals/  : GL journal export CSV"
echo "  - emails/    : Email HTML files (dev mode output)"
