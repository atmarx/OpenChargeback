"""One rounding policy for every dollar this system prints.

The trust-killer for a chargeback tool is not a crash — it's a controller
finding the PDF, the journal, and the close package disagreeing by a cent
for the same month. That happens whenever artifacts aggregate raw float
costs at different grains and each round their own sums.

The fix is structural: round ONCE, at the finest grain any artifact groups
by — (pi_email, project, source, service, fund_org) — producing "money
atoms" of exact cents. Every artifact then sums the same atoms along its
own dimension: statement service lines, journal rows, GL debits and
credits are all partitions of one set of cents, so in == out, everywhere,
by construction.

Sub-cent input amounts (cloud bills have them) are preserved up to the
atom: raw costs accumulate in Decimal and are quantized half-up once per
atom, never per charge and never per artifact.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

CENT = Decimal("0.01")

# Labels for absent grouping values — shared by every consumer so atoms and
# display grouping always agree.
NO_PROJECT = "(no project)"
NO_SERVICE = "Other"


def to_decimal(value: Any) -> Decimal:
    """Convert a raw value to Decimal without rounding (None -> 0)."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def cents(value: Any) -> Decimal:
    """Quantize to exact cents, half-up (the accountant's rounding)."""
    return to_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, order=True)
class AtomKey:
    """The finest grain any artifact groups money by."""

    pi_email: str
    project_id: str  # normalized: NO_PROJECT when absent
    source_id: int
    service_name: str  # normalized: NO_SERVICE when absent
    fund_org: str  # '' when absent


@dataclass
class MoneyAtom:
    """An exact-cents quantum of one month's money."""

    key: AtomKey
    billed: Decimal  # quantized cents
    listed: Decimal  # quantized cents; list price with billed fallback
    charge_count: int
    account_code: str | None  # first account-code tag seen, for GL exports


def build_atoms(
    charges: list[Any],
    account_code_tag: str | None = None,
) -> list[MoneyAtom]:
    """Aggregate charges into money atoms — the single rounding point.

    Raw costs accumulate unrounded in Decimal per atom key; each atom is
    quantized to cents exactly once. Returned sorted by key so every
    consumer iterates deterministically.
    """
    raw: dict[AtomKey, dict[str, Any]] = {}
    for charge in charges:
        key = AtomKey(
            pi_email=charge.pi_email,
            project_id=charge.project_id or NO_PROJECT,
            source_id=charge.source_id,
            service_name=getattr(charge, "service_name", None) or NO_SERVICE,
            fund_org=charge.fund_org or "",
        )
        entry = raw.setdefault(
            key,
            {
                "billed": Decimal("0"),
                "listed": Decimal("0"),
                "count": 0,
                "account_code": None,
            },
        )
        entry["billed"] += to_decimal(charge.billed_cost)
        # No list price recorded means "list = billed" (no discount).
        list_cost = getattr(charge, "list_cost", None)
        entry["listed"] += to_decimal(
            list_cost if list_cost is not None else charge.billed_cost
        )
        entry["count"] += 1
        if (
            account_code_tag
            and entry["account_code"] is None
            and isinstance(charge.raw_tags, dict)
            and charge.raw_tags.get(account_code_tag)
        ):
            entry["account_code"] = str(charge.raw_tags[account_code_tag])

    return [
        MoneyAtom(
            key=key,
            billed=cents(entry["billed"]),
            listed=cents(entry["listed"]),
            charge_count=entry["count"],
            account_code=entry["account_code"],
        )
        for key, entry in sorted(raw.items(), key=lambda item: item[0])
    ]
