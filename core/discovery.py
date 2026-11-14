"""Read the search page so the app follows the portal instead of guessing.

Nothing here hardcodes a field id. The page is parsed and the field names are
taken from whatever it actually contains, so a minor redesign degrades into a
clear error rather than a silent empty result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .config import BASE_URL

FORM_ACTION_RE = re.compile(r'<form[^>]*action="([^"]+)"')
CAPTCHA_IMG_RE = re.compile(r"([\"'])([^\"']*Captcha\.jpg[^\"']*)\1", re.I)


@dataclass
class SelectOption:
    value: str
    label: str


@dataclass
class CaptchaInfo:
    """The captcha (if any) guarding the search form."""

    kind: str = "none"           # "legacy" | "new" | "none"
    image_url: str = ""
    answer: str = ""             # server-issued value for the hidden 'ver' field
    input_name: str = "verification"


@dataclass
class SearchPageInfo:
    form_action: str = ""
    selects: dict[str, list[SelectOption]] = field(default_factory=dict)
    inputs: dict[str, str] = field(default_factory=dict)
    captcha: CaptchaInfo = field(default_factory=CaptchaInfo)
    total_count: int | None = None


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def find_form_action(html: str) -> str:
    match = FORM_ACTION_RE.search(html)
    if not match:
        raise LookupError("The IREPS search page has no recognisable form.")
    return match.group(1)


def select_options(soup: BeautifulSoup, name: str) -> list[SelectOption]:
    options: list[SelectOption] = []
    node = soup.find("select", attrs={"name": name})
    if node is None:
        return options
    for option in node.find_all("option"):
        value = option.get("value", "")
        label = option.get_text(strip=True)
        options.append(SelectOption(value=value, label=label))
    return options


def all_select_options(soup: BeautifulSoup) -> dict[str, list[SelectOption]]:
    result: dict[str, list[SelectOption]] = {}
    for node in soup.find_all("select"):
        name = node.get("name")
        if not name:
            continue
        result[name] = select_options(soup, name)
    return result


def input_fields(soup: BeautifulSoup) -> dict[str, str]:
    """Map field name -> its current value (empty string for most)."""
    fields: dict[str, str] = {}
    for node in soup.find_all("input"):
        name = node.get("name")
        if not name:
            continue
        fields[name] = node.get("value", "") or ""
    return fields


def find_captcha(soup: BeautifulSoup) -> CaptchaInfo:
    """Detect the search-page captcha and pull the image URL.

    The legacy mechanism serves ``Captcha.jpg?r=<hex>`` and the portal's own
    JavaScript fills the hidden field with the first six characters of that
    hex. The user still reads the image and types the answer; the structural
    value is only used for the hidden field.
    """
    for img in soup.find_all("img"):
        src = img.get("src") or ""
        if "captcha" in src.lower():
            match = CAPTCHA_IMG_RE.search(src)
            url = urljoin(BASE_URL + "/", match.group(2) if match else src)
            answer = ""
            query = url.split("r=", 1)
            if len(query) == 2:
                answer = query[1].split("&", 1)[0][:6]
            return CaptchaInfo(kind="legacy", image_url=url, answer=answer)

    node = soup.find("input", attrs={"name": "verification"})
    if node is not None:
        return CaptchaInfo(kind="new", image_url="", answer="")
    return CaptchaInfo(kind="none")


def find_total_count(soup: BeautifulSoup) -> int | None:
    """The portal prints the record total in a label block."""
    for cell in soup.find_all("td", class_="formLabel"):
        text = cell.get_text(" ", strip=True)
        if "Tender search results" in text or "search result" in text.lower():
            numbers = re.findall(r"[\d,]+", text)
            if numbers:
                try:
                    return int(numbers[-1].replace(",", ""))
                except ValueError:
                    continue
    match = re.search(r"(\d[\d,]*)\s+(?:tenders?|records?|results?)", soup.get_text(" ", strip=True), re.I)
    if match:
        try:
            return int(match.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def discover(html: str) -> SearchPageInfo:
    """Build a :class:`SearchPageInfo` from the search page HTML."""
    soup = _soup(html)
    info = SearchPageInfo()
    try:
        info.form_action = find_form_action(html)
    except LookupError:
        info.form_action = ""
    info.selects = all_select_options(soup)
    info.inputs = input_fields(soup)
    info.captcha = find_captcha(soup)
    info.total_count = find_total_count(soup)
    return info


# --- the tender page's dependent dropdowns ---------------------------------
# The portal fills the "Railway/PU" and "Unit" dropdowns over AJAX, so the
# page itself only carries the first, static list. These two helpers ask the
# portal for the same lists its own JavaScript asks for.
AJAX_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


def _parse_caret_list(text: str) -> list[SelectOption]:
    """The portal's AJAX answers are "value^Label^value^Label..."."""
    options: list[SelectOption] = []
    parts = [part.strip() for part in (text or "").split("^")]
    for index in range(0, len(parts) - 1, 2):
        value, label = parts[index], parts[index + 1]
        if value and label:
            options.append(SelectOption(value=value, label=label))
    return options


def fetch_tender_zones(client, organisation: str) -> list[SelectOption]:
    """The Railway/PU list for an organisation."""
    from .config import TENDER_ZONE_LIST_PATH

    url = BASE_URL + TENDER_ZONE_LIST_PATH + "?organization=" + (organisation or "-1")
    try:
        response = client.get(url, headers=AJAX_HEADERS)
        return _parse_caret_list(response.text)
    except Exception:  # noqa: BLE001 - a missing list must not break the app
        return []


def fetch_tender_units(client, division: str, zone: str,
                       work_area: str = "-1") -> list[SelectOption]:
    """The Unit list for a department, a zone and a work area."""
    from .config import TENDER_UNIT_LIST_PATH

    url = (BASE_URL + TENDER_UNIT_LIST_PATH
           + f"?department={division or '-1'}&zone={zone or '-1'}&workArea={work_area or '-1'}")
    try:
        response = client.post(url, data={}, headers=AJAX_HEADERS)
        return _parse_caret_list(response.text)
    except Exception:  # noqa: BLE001
        return []
