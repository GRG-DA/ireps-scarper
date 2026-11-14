"""Turning the portal's free text into typed, comparable values."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

NBSP = "\xa0"

#: Indian numbering short forms the portal prints for PO values.
UNITS = {
    "lakh": 100_000,
    "lakhs": 100_000,
    "lac": 100_000,
    "lacs": 100_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
    "cr": 10_000_000,
    "thousand": 1_000,
    "thousands": 1_000,
}


def clean_text(value: str | None) -> str:
    """Collapse whitespace (including &nbsp;) and strip."""
    if value is None:
        return ""
    text = str(value).replace(NBSP, " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_amount(value: str | None) -> float | None:
    """Parse a PO value such as '1,25,000', 'Rs. 1.25 Lakh' or 'Rs 2.50 Crore'.

    Returns ``None`` when the text cannot be understood, so that a bad value
    shows up as a blank cell instead of a misleading zero.
    """
    if value is None:
        return None
    text = clean_text(value)
    if not text:
        return None

    multiplier = 1.0
    for word, factor in UNITS.items():
        if re.search(rf"\b{word}\b", text, flags=re.I):
            multiplier = float(factor)
            break

    # Drop the unit words and any currency prefix, keep digits and separators.
    cleaned = re.sub(rf"\b({'|'.join(UNITS)})\b", " ", text, flags=re.I)
    cleaned = re.sub(r"(?i)\brs\.?|\binr\b|\u20b9", " ", cleaned)
    cleaned = re.sub(r"[^0-9.]", "", cleaned)
    if not cleaned or cleaned == ".":
        return None

    # A decimal only means rupees-and-paise when no Lakh/Crore unit is present
    # and one or two digits follow the point ("1,000.50" is one thousand fifty).
    if "." in cleaned:
        head, _, tail = cleaned.rpartition(".")
        if multiplier == 1.0 and len(tail) in (1, 2):
            try:
                return round(float(f"{head}.{tail}"), 2)
            except ValueError:
                return None
        if multiplier == 1.0:
            cleaned = cleaned.replace(".", "")

    try:
        return round(float(cleaned) * multiplier, 2)
    except ValueError:
        return None


DATE_PATTERNS = (
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y",
    "%d-%m-%Y %H:%M",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d %b %Y",
    "%d-%b-%Y",
    "%Y-%m-%d",
)


def parse_date(value: str | None) -> datetime | None:
    """Parse the portal's dd/mm/yyyy (and friends) into a datetime."""
    if value is None:
        return None
    text = clean_text(value)
    if not text:
        return None
    text = text.replace("  ", " ").strip()
    for pattern in DATE_PATTERNS:
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    # "12/09/2020 10:30 IST" and similar trailing noise
    trimmed = re.sub(r"\s*(IST|IST)$", "", text).strip()
    for pattern in DATE_PATTERNS:
        try:
            return datetime.strptime(trimmed, pattern)
        except ValueError:
            continue
    return None


def today_ist() -> datetime:
    """The portal runs on IST; the local box may not be on IST."""
    try:
        from datetime import timezone, timedelta as _td

        ist = _td(hours=5, minutes=30)
        return datetime.now(timezone.utc).astimezone(ist).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def date_window(days_back: int = 30) -> tuple[str, str]:
    """Return (from, to) as dd/mm/yyyy, ending today."""
    end = today_ist()
    start = end - timedelta(days=days_back)
    return start.strftime("%d/%m/%Y"), end.strftime("%d/%m/%Y")


def iso_now() -> str:
    return today_ist().strftime("%Y-%m-%d %H:%M:%S")
