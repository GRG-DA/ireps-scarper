"""Fetching and parsing the per-record detail page.

The detail pages are the least predictable surface on the portal: the layout
changes from zone to zone. So rather than assume a fixed grid, every
label/value pair on the page is captured, a set of known labels is mapped onto
named columns, and everything else is kept in ``Detail_Extra`` rather than
being thrown away.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

from .config import CACHE_DIR

#: Labels that map onto a named column in the exported workbook.
LABEL_ALIASES = {
    "po date": "PO Date",
    "purchase order date": "PO Date",
    "order date": "PO Date",
    "po no": "PO Reference",
    "purchase order no": "PO Reference",
    "po number": "PO Reference",
    "item code": "Item Code / PLNO",
    "item code/plno": "Item Code / PLNO",
    "plno": "Item Code / PLNO",
    "material code": "Item Code / PLNO",
    "supplier name": "Supplier Name",
    "vendor name": "Supplier Name",
    "supplier gstin": "Supplier GSTIN",
    "gstin": "Supplier GSTIN",
    "gstin no": "Supplier GSTIN",
    "supplier address": "Supplier Address",
    "address": "Supplier Address",
    "consignee": "Consignee",
    "consignee address": "Consignee",
    "quantity": "PO Qty/Unit",
    "qty": "PO Qty/Unit",
    "unit rate": "Unit Rate",
    "rate": "Unit Rate",
    "unit price": "Unit Rate",
    "total value": "PO Value (text)",
    "order no": "Order / Contract No",
    "order number": "Order / Contract No",
    "contract no": "Order / Contract No",
    "gem order no": "Order / Contract No",
    "contact person": "Contact Person / Email",
    "contact": "Contact Person / Email",
    "email": "Contact Person / Email",
    "delivery date": "Delivery Date",
    "delivery date/time": "Delivery Date",
    "due date": "Delivery Date",
    "item description": "Item Description",
    "description": "Item Description",
    "t.u.r": "T.U.R.",
    "tur": "T.U.R.",
    # --- the tender detail page -----------------------------------------
    "tender no": "Tender No",
    "tender number": "Tender No",
    "dept/rly": "Dept/Rly Unit",
    "dept./rly. unit": "Dept/Rly Unit",
    "dept/rly unit": "Dept/Rly Unit",
    "closing date/time": "Due Date/Time",
    "due date/time": "Due Date/Time",
    "tender title": "Tender Title",
    "tender type": "Tender Type",
    "tender status": "Tender Status",
    "work area": "Work Area",
    "due days": "Due Days",
}

KNOWN_COLUMNS = [
    "PO Date",
    "PO Reference",
    "Item Code / PLNO",
    "Supplier Name",
    "Supplier GSTIN",
    "Supplier Address",
    "Consignee",
    "PO Qty/Unit",
    "Unit Rate",
    "Order / Contract No",
    "Contact Person / Email",
    "Delivery Date",
    "Item Description",
    "T.U.R.",
]


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def _normalise_label(text: str) -> str:
    label = re.sub(r"\s+", " ", text).strip().strip(":").strip()
    return label.lower()


def extract_pairs(html: str) -> dict[str, str]:
    """Collect every label/value pair visible on a detail page.

    The cells of a row are read **directly**, never through a nested table:
    the tender page wraps its whole notice in layout tables, and a recursive
    lookup would hand back one cell holding the entire line of text.
    """
    soup = _soup(html)
    pairs: dict[str, str] = {}

    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"], recursive=False)
        if len(cells) < 2 or len(cells) % 2:
            continue
        # A label/value row alternates label, value, label, value. The PO
        # pages use two cells per row, the tender pages up to six.
        for index in range(0, len(cells), 2):
            label = _normalise_label(cells[index].get_text(" ", strip=True))
            value = re.sub(r"\s+", " ", cells[index + 1].get_text(" ", strip=True)).strip()
            if label and value and len(label) <= 80:
                pairs.setdefault(label, value)

    # Some rows put the label and the value in one cell, separated by a colon.
    for node in soup.find_all(["td", "span", "div", "b", "strong"]):
        text = node.get_text(" ", strip=True)
        if ":" not in text or len(text) > 200:
            continue
        label, _, value = text.partition(":")
        label = _normalise_label(label)
        value = value.strip()
        if label and value and len(label) <= 60:
            pairs.setdefault(label, value)

    return pairs


def map_pairs(pairs: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Split the pairs into named columns and leftovers."""
    known: dict[str, str] = {}
    extra: dict[str, str] = {}
    for label, value in pairs.items():
        target = LABEL_ALIASES.get(label)
        if target and target not in known:
            known[target] = value
        elif target:
            extra[label] = value
        else:
            extra[label] = value
    return known, extra


def parse_detail(html: str) -> dict:
    """Return ``{known columns..., "Detail_Extra": json}`` for one record."""
    pairs = extract_pairs(html)
    known, extra = map_pairs(pairs)
    known["Detail_Extra"] = json.dumps(extra, ensure_ascii=False, sort_keys=True)
    known["Detail_Labels"] = " | ".join(sorted(pairs.keys()))
    return known


def cache_path(key: str) -> Path:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.html"


def read_cache(key: str) -> str | None:
    path = cache_path(key)
    if path.exists():
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    return None


def write_cache(key: str, html: str) -> None:
    path = cache_path(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8", errors="replace")
    except OSError:
        pass
