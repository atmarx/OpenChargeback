#!/bin/bash
# Generate sample outputs from sample input data.
#
# Walks the full lifecycle for every sample month so the git repo shows, end to
# end, how FOCUS-format input files become the delivered outputs: PDF statements,
# the GL journal, and the forensic close package in BOTH wrappers (zip and pdf).
#
# The result is a 2x2 under sample_data/outputs/packages/: two months, two
# wrappers, identical facts inside each pair. These are committed as reference
# samples. They are deterministic — same input data + same toolchain produces
# the same bytes and the same sha256 (recorded in SHA256SUMS.txt).

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

CONFIG="config.example.yaml"
PERIODS=("2025-01" "2025-12")

echo "=== OpenChargeback Sample Output Generator ==="
echo ""

# Activate virtual environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "ERROR: Virtual environment not found. Run 'python -m venv .venv && pip install -e .'"
    exit 1
fi

# Enable dev_mode so emails are written to files instead of sent via SMTP.
# Save the original value and restore it on exit.
ORIG_DEV_MODE=$(grep -E "^dev_mode:" "$CONFIG" | awk '{print $2}')
sed -i 's/^dev_mode: .*/dev_mode: true/' "$CONFIG"
cleanup() {
    sed -i "s/^dev_mode: .*/dev_mode: $ORIG_DEV_MODE/" "$CONFIG"
}
trap cleanup EXIT

# Step 1: Reset database and clear prior sample outputs
echo "Step 1: Resetting database and output dirs..."
rm -f instance/billing.db
rm -rf instance/output/emails
rm -rf sample_data/outputs/pdfs sample_data/outputs/journals \
       sample_data/outputs/emails sample_data/outputs/packages
mkdir -p sample_data/outputs/pdfs sample_data/outputs/journals \
         sample_data/outputs/emails sample_data/outputs/packages
echo "  Cleared."

# Step 2: Walk every sample month through the full lifecycle
for PERIOD in "${PERIODS[@]}"; do
    echo ""
    echo "=== Period $PERIOD ==="

    echo "  Ingesting sample inputs (originals archived verbatim)..."
    for f in sample_data/inputs/*_${PERIOD}.csv; do
        [ -f "$f" ] || continue
        # Source name is the filename minus the _<period>.csv suffix, so
        # multi-word sources like it_storage stay whole.
        srcname=$(basename "$f" | sed "s/_${PERIOD}.csv//")
        echo "    - $srcname"
        openchargeback ingest "$f" -s "$srcname" -p "$PERIOD" -c "$CONFIG" > /dev/null
    done

    echo "  Approving charges (a clean, complete month)..."
    openchargeback review approve -p "$PERIOD" -c "$CONFIG" > /dev/null || true

    echo "  Generating PDF statements + emails..."
    openchargeback generate -p "$PERIOD" -c "$CONFIG" --send > /dev/null

    echo "  Exporting GL journal..."
    openchargeback export-journal -p "$PERIOD" -f gl -c "$CONFIG" > /dev/null

    echo "  Closing period (pins the package timestamps)..."
    openchargeback periods close "$PERIOD" -c "$CONFIG" > /dev/null

    echo "  Building close packages (zip + pdf portfolio)..."
    openchargeback export-package -p "$PERIOD" -f zip \
        -o sample_data/outputs/packages -c "$CONFIG" > /dev/null
    openchargeback export-package -p "$PERIOD" -f pdf \
        -o sample_data/outputs/packages -c "$CONFIG" > /dev/null
done

# Step 3: Collect the delivered per-PI outputs into sample_data/outputs/
echo ""
echo "Step 3: Collecting statements, journals and emails..."
if [ -d "instance/output/pdfs" ]; then
    cp instance/output/pdfs/*.pdf sample_data/outputs/pdfs/ 2>/dev/null || true
    echo "  $(ls sample_data/outputs/pdfs/*.pdf 2>/dev/null | wc -l) statement PDFs"
fi
if [ -d "instance/output/journals" ]; then
    cp instance/output/journals/*.csv sample_data/outputs/journals/ 2>/dev/null || true
    echo "  $(ls sample_data/outputs/journals/*.csv 2>/dev/null | wc -l) journal exports"
fi
if [ -d "instance/output/emails" ]; then
    cp instance/output/emails/*.html sample_data/outputs/emails/ 2>/dev/null || true
    echo "  $(ls sample_data/outputs/emails/*.html 2>/dev/null | wc -l) email files"
fi

# Step 4: Record the package hashes + a short guide
echo ""
echo "Step 4: Recording package hashes..."
( cd sample_data/outputs/packages && sha256sum -- *.zip *.pdf > SHA256SUMS.txt )
cat > sample_data/outputs/packages/README.md <<'EOF'
# Sample close packages

Two months, two wrappers — the forensic monthly close package as OpenChargeback
delivers it. Each `.zip` and its matching `.pdf` for the same month carry
**byte-identical members**: the wrapper an org picks never changes a number.

| Month   | ZIP                              | PDF portfolio                    |
|---------|----------------------------------|----------------------------------|
| 2025-01 | `openchargeback-close-2025-01-*.zip` | `openchargeback-close-2025-01-*.pdf` |
| 2025-12 | `openchargeback-close-2025-12-*.zip` | `openchargeback-close-2025-12-*.pdf` |

The 6-character suffix in each filename is the last 6 chars of the file's
sha256. `SHA256SUMS.txt` records the full hashes — verify with:

    sha256sum -c SHA256SUMS.txt

Regenerated by `scripts/generate-sample-outputs.sh` and committed as a fixed
snapshot. The *wrapping* is byte-deterministic — the same member files always pack
to the same bytes, and CI proves it. The bundled statement PDFs carry the timestamp
of when they were rendered, so regenerating the whole sample produces fresh
statements and therefore fresh package hashes. In production, statements are frozen
once and copied verbatim, so a given month's package stays stable. `SHA256SUMS.txt`
pins this snapshot — `sha256sum -c SHA256SUMS.txt` confirms these files are intact.
EOF
echo "  Wrote SHA256SUMS.txt + README.md"

echo ""
echo "=== Done! ==="
echo ""
echo "Sample outputs are in sample_data/outputs/"
echo "  - pdfs/      : Statement PDFs for each PI/project"
echo "  - journals/  : GL journal export CSVs"
echo "  - emails/    : Email HTML files (dev mode output)"
echo "  - packages/  : Forensic close packages — 2 months x {zip, pdf}"
