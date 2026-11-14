"""Parsing the portal's results table into flat records.

The results table is a legacy grid: a *main* row carries the supplier and the
PO value, and *continuation* rows carry only the line items that belong to
the PO above them. Both shapes are folded into one flat record per line.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .config import COLUMNS, RESULT_TABLE_SELECTOR
from .normalize import clean_text, parse_amount, parse_date

#: A main row has at least this many cells; a continuation row has exactly 5.
MAIN_MIN_CELLS = 9
CONTINUATION_CELLS = 5

#: The PO search renders one cell like this:
#: "NER/22261096104124 dt. 05-NOV-2026 on M/s. SUJAN INDUSTRIES-PALGHAR"
PO_CELL_RE = re.compile(
    r"^(?P<ref>[A-Za-z0-9][A-Za-z0-9/\-]*)\s+dt\.\s+"
    r"(?P<date>\d{1,2}-[A-Za-z]{3}-\d{4})"
    r"(?:\s+on\s+(?P<supplier>.+))?$"
)

#: ...and an item description like "33500058 : Rubber Pad for bogies".
ITEM_CELL_RE = re.compile(r"^(?P<code>\d{2,})\s*:\s*(?P<desc>.*)$", re.S)


def _cell_text(cells, index: int) -> str:
    if index >= len(cells):
        return ""
    return clean_text(cells[index].get_text(" ", strip=True))


def _is_header(cells) -> bool:
    """True for the label row - the portal writes it as 'Sr.', not 'Sr'."""
    if not cells:
        return False
    first = clean_text(cells[0].get_text(" ", strip=True)).lower().rstrip(". ")
    return first in ("sr", "s no", "s.no", "s.no.", "sl no", "serial")


def _row_links(cells) -> list[str]:
    """Collect the links on a row - the detail page link usually lives here."""
    links: list[str] = []
    for cell in cells:
        for anchor in cell.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href or href.lower().startswith(("javascript:", "mailto:", "#")):
                continue
            links.append(href)
    return links


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


#: The label row the portal renders at the top of the results grid.
HEADER_LABELS = ["sr.", "supplier name", "po value", "item description",
                 "po sl", "consignee", "po qty/unit", "t.u.r.", "dely.dt"]


def _looks_like_header(cells) -> bool:
    """True when the cells are the results grid's own label row."""
    if len(cells) < MAIN_MIN_CELLS:
        return False
    labels = [clean_text(c.get_text(" ", strip=True)).lower() for c in cells[:MAIN_MIN_CELLS]]
    return labels[:4] == HEADER_LABELS[:4]


def find_results_table(html: str):
    """The results grid, and nothing else.

    The search page itself has tables that mention "PO Date" and such, so the
    table is only accepted when its first row really is the label row.
    """
    soup = _soup(html)
    table = soup.select_one(RESULT_TABLE_SELECTOR)
    if table is not None:
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if _looks_like_header(cells):
                return table
    # Fall back to any table that starts with the label row.
    for candidate in soup.find_all("table"):
        for row in candidate.find_all("tr"):
            cells = row.find_all("td")
            if _looks_like_header(cells):
                return candidate
    return None


def parse_results(html: str) -> list[dict]:
    """Turn the results page into a list of record dicts."""
    table = find_results_table(html)
    if table is None:
        return []

    records: list[dict] = []
    current: dict | None = None

    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        if _is_header(cells):
            continue

        if len(cells) >= MAIN_MIN_CELLS:
            current = {
                "Sr": _cell_text(cells, 0),
                "Supplier Name": _cell_text(cells, 1),
                "PO Value (text)": _cell_text(cells, 2),
                "Item Description": _cell_text(cells, 3),
                "PO Sl": _cell_text(cells, 4),
                "Consignee": _cell_text(cells, 5),
                "PO Qty/Unit": _cell_text(cells, 6),
                "T.U.R.": _cell_text(cells, 7),
                "Dely.Dt": _cell_text(cells, 8),
            }
            links = _row_links(cells)
            current["Detail URL"] = links[0] if links else ""
            current["_links"] = links
            records.append(_finalise(current))
            current = None
        elif len(cells) == CONTINUATION_CELLS and records:
            parent = records[-1]
            parent["Item Description"] = _join(
                parent["Item Description"], _cell_text(cells, 0)
            )
            parent["Consignee"] = _join(parent["Consignee"], _cell_text(cells, 1))
            parent["PO Qty/Unit"] = _join(parent["PO Qty/Unit"], _cell_text(cells, 2))
            parent["T.U.R."] = _join(parent["T.U.R."], _cell_text(cells, 3))
            parent["Dely.Dt"] = _join(parent["Dely.Dt"], _cell_text(cells, 4))

    return [r for r in records if any(r.get(c) for c in COLUMNS)]


def _join(existing: str, addition: str) -> str:
    if not addition:
        return existing
    if not existing:
        return addition
    return f"{existing}; {addition}"


def _finalise(record: dict) -> dict:
    # The PO cell carries the PO reference, the PO date and the supplier all
    # in one string - split them apart so they land in their own columns.
    po_match = PO_CELL_RE.match(record.get("Supplier Name", "") or "")
    if po_match:
        record["PO Reference"] = po_match.group("ref")
        record["PO Date"] = parse_date(po_match.group("date"))
        supplier = (po_match.group("supplier") or "").strip()
        if supplier:
            record["Supplier Name"] = supplier
        else:
            record["Supplier Name"] = ""
    else:
        record["PO Reference"] = ""
        record["PO Date"] = None

    # The description cell starts with the material code.
    item_match = ITEM_CELL_RE.match(record.get("Item Description", "") or "")
    if item_match:
        record["Item Code / PLNO"] = item_match.group("code")
        record["Item Description"] = item_match.group("desc").strip()
    else:
        record["Item Code / PLNO"] = ""

    record["PO Value"] = parse_amount(record.get("PO Value (text)"))
    record["Delivery Date"] = parse_date(record.get("Dely.Dt"))
    record["Source URL"] = record.get("Detail URL", "")
    record["Zone / Rly Unit"] = ""
    return record


def parse_result_count(html: str) -> int | None:
    """The portal prints the record total right after 'Tender search results'."""
    match = re.search(r"Tender search results[\s\S]{0,200}?<B>\s*([\d,]+)\s*</B>", html, re.I)
    if not match:
        match = re.search(r"Tender search results[\s\S]{0,200}?([\d,]{2,})\s*<", html, re.I)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def page_links(html: str) -> list[str]:
    """The pagination links the portal renders under the results table."""
    from urllib.parse import urljoin

    from .config import BASE_URL

    soup = _soup(html)
    seen: set[str] = set()
    urls: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if "pageNo=" not in href and "page=" not in href:
            continue
        absolute = urljoin(BASE_URL + "/", href)
        if absolute in seen:
            continue
        seen.add(absolute)
        urls.append(absolute)
    return urls


def page_link_for(html: str, page_number: int) -> str | None:
    """The pagination link that points at a specific page, if the page has one."""
    import re

    for url in page_links(html):
        match = re.search(r"pageNo=(\d+)", url)
        if match and int(match.group(1)) == page_number:
            return url
    return None


# --- the tender search page ------------------------------------------------
#: The label row the tender results grid starts with.
TENDER_HEADER_LABELS = ["deptt./rly. unit", "tender no", "tender title", "status"]

#: The portal builds the page links with a JavaScript helper, so they live in
#: an onclick attribute rather than in an href.
POST_REQUEST_RE = re.compile(r"postRequest(?:NewWindow)?\(\s*'([^']+)'", re.I)

#: The opaque id the portal posts to a tender's detail page.
TENDER_OID_RE = re.compile(r"tenderAnonymsOid=([^&']+)", re.I)


def _looks_like_tender_header(cells) -> bool:
    """True when the cells are the tender grid's own label row."""
    if len(cells) < 4:
        return False
    labels = [clean_text(c.get_text(" ", strip=True)).lower() for c in cells[:4]]
    return labels[:4] == TENDER_HEADER_LABELS


def find_tender_results_table(html: str):
    """The tender results grid.

    The PO grid and the tender grid share the same border colour, so they are
    told apart by their label row rather than by their styling. The label row
    is looked up first and the table taken from its parent: the portal wraps
    the grid in several layout tables, and the first one that merely
    *contains* the label row would swallow the whole page.
    """
    soup = _soup(html)
    for row in soup.find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if _looks_like_tender_header(cells):
            return row.find_parent("table")
    return None


def _tender_detail_id(cells) -> str:
    """The opaque tender id carried by a row's "View Details" link."""
    for cell in cells:
        for anchor in cell.find_all("a"):
            onclick = anchor.get("onclick") or ""
            match = POST_REQUEST_RE.search(onclick)
            if not match:
                continue
            oid = TENDER_OID_RE.search(match.group(1))
            if oid:
                return oid.group(1)
    return ""


def parse_tender_results(html: str) -> list[dict]:
    """Turn a tender results page into a list of record dicts.

    The grid has eight columns: Deptt./Rly. Unit, Tender No, Tender Title,
    Status, Work Area, Due Date/Time, Due Days and Actions. The last one
    holds the "View Details" link, from which the tender's opaque id is
    taken.
    """
    table = find_tender_results_table(html)
    if table is None:
        return []

    records: list[dict] = []
    for row in table.find_all("tr", recursive=False):
        cells = row.find_all("td", recursive=False)
        if not cells or _looks_like_tender_header(cells):
            continue
        if len(cells) < 7:
            continue
        record = {
            "Sr": str(len(records) + 1),
            "Dept/Rly Unit": _cell_text(cells, 0),
            "Tender No": _cell_text(cells, 1),
            "Tender Title": _cell_text(cells, 2),
            "Status": _cell_text(cells, 3),
            "Work Area": _cell_text(cells, 4),
            "Due Date/Time": _cell_text(cells, 5),
            "Due Days": _cell_text(cells, 6),
        }
        record["Tender ID"] = _tender_detail_id(cells)
        record["Due Date"] = parse_date(record["Due Date/Time"])
        record["Source URL"] = _tender_detail_url(record["Tender ID"])
        records.append(record)
    return records


def _tender_detail_url(tender_id: str) -> str:
    """A readable address for a tender's detail page.

    The portal serves that page only by POST, so this link is a reference
    rather than something a browser can follow.
    """
    if not tender_id:
        return ""
    from .config import BASE_URL, TENDER_DETAIL_PATH

    return (f"{BASE_URL}{TENDER_DETAIL_PATH}"
            f"?tenderAnonymsOid={tender_id}&activity=viewNIT")


def tender_page_urls(html: str) -> list[str]:
    """Every results-page link the portal renders under the tender grid."""
    soup = _soup(html)
    urls: list[str] = []
    for anchor in soup.find_all("a"):
        onclick = anchor.get("onclick") or ""
        match = POST_REQUEST_RE.search(onclick)
        if not match:
            continue
        url = match.group(1)
        if "pageNo=" in url and url not in urls:
            urls.append(url)
    return urls


def split_query(query: str) -> dict[str, str]:
    """The portal's own query string, read the way its JavaScript reads it.

    ``postRequest`` splits every pair on "=" and keeps the second part, so a
    value that itself contains "=" loses its tail. Doing the same keeps the
    scraper byte-for-byte compatible with the browser.
    """
    params: dict[str, str] = {}
    for pair in query.split("&"):
        if not pair:
            continue
        parts = pair.split("=")
        params[parts[0]] = parts[1] if len(parts) > 1 else ""
    return params


def tender_page_body(html: str, count: int | None = None,
                     payload: dict | None = None) -> dict[str, str]:
    """The parameters a results page is fetched with.

    The portal links its pages with a query string that carries the search
    criteria; the app posts the very same parameters, which is what the
    portal's own JavaScript does. The criteria themselves stay the source of
    truth - the portal's link drops a couple of them - and only the page
    bookkeeping (``linkVal`` and ``count``) is taken from the link.
    """
    params = dict(payload or {})
    # The page links carry no button value and no activity: they ask for a
    # page of the search that is already running, not for a new search.
    params.pop("submit", None)
    params.pop("activity", None)

    for url in tender_page_urls(html):
        _, _, query = url.partition("?")
        link = split_query(query)
        params.setdefault("linkVal", link.get("linkVal", "department"))
        if count is not None:
            params["count"] = str(count)
        elif "count" in link:
            params["count"] = link["count"]
        break
    return params


def tender_detail_payload(tender_id: str) -> dict[str, str]:
    """The body the portal posts to a tender's detail page.

    The id is the value the "View Details" link carries. The portal's own
    JavaScript truncates it at the first "=", which strips the base64
    padding - and the server only accepts the truncated form.
    """
    return {
        "tenderAnonymsOid": tender_id.split("=")[0],
        "activity": "viewNIT",
    }


def dedupe(records: list[dict]) -> list[dict]:
    """Drop repeats, which pagination and re-runs both produce."""
    seen: set[tuple] = set()
    unique: list[dict] = []
    for record in records:
        if record.get("Tender No"):
            key = ("tender", record.get("Tender No", ""), record.get("Dept/Rly Unit", ""))
        else:
            key = (
                record.get("PO Reference", ""),
                record.get("PO Sl", ""),
                record.get("Supplier Name", ""),
                record.get("Dely.Dt", ""),
                record.get("Item Description", "")[:60],
            )
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique
