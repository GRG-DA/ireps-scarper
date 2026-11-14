"""Static configuration: URLs, paths and the portal's option vocabularies."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "state"
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR = BASE_DIR / "logs"
CACHE_DIR = STATE_DIR / "detail_cache"

SESSION_FILE = STATE_DIR / "session.pkl"
CONFIG_FILE = BASE_DIR / "config.json"

for _d in (STATE_DIR, OUTPUT_DIR, LOG_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://www.ireps.gov.in"

#: The page the user asked for. Serves the guest login form until you authenticate.
GUEST_SEARCH_URL = f"{BASE_URL}/epsn/anonymSearchPO.do"

#: The Purchase Order / Supply Contract search, reached once authenticated.
PO_SEARCH_URL = f"{BASE_URL}/epsn/anonymSearchPO.do?searchParam=showPageSupply&language=en"

#: The tender search - the "Search Tender" page with its six tabs.
TENDER_SEARCH_URL = f"{BASE_URL}/epsn/anonymSearch.do"

#: The tender's own detail page. The portal posts an opaque id to it.
TENDER_DETAIL_PATH = "/epsn/nitViewAnonyms/rfq/nitPublish.do"

#: The AJAX endpoints the portal uses to fill the dependent dropdowns.
TENDER_UNIT_LIST_PATH = "/epsn/jsp/rfq/Search/getUnitLists.jsp"
TENDER_ZONE_LIST_PATH = "/epsn/jsp/rfq/Search/getOrgZonesList.jsp"

GUEST_LOGIN_PATH = "/epsn/guestLogin.do"
CAPTCHA_PATH = "/epsn/generateCaptchaAction.do"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# --- portal option vocabularies (values are what the server expects) --------
SEARCH_OPTIONS = {
    "Tender Number": "1",
    "Tender Title": "2",
    "PLNO (Item Code)": "3",
    "Item Description": "4",
}
MATCH_OPTIONS = {"Starting with": "0", "Equals": "1"}
DATE_BASIS = {"Tender Closing Date": "0", "Tender Uploading Date": "1"}
BIDDING_OPTIONS = {"All": "-1", "Single Bid System": "0", "Double Bid System": "1"}
TENDER_STAGE = {"Published": "1"}

# --- the tender search page (verified live on 11 Nov 2026) -------------------
#: The "Search Criteria" dropdown on the tender page.
TENDER_SEARCH_OPTIONS = {
    "Tender Number": "1",
    "Name Of Work": "2",
    "Item Code": "3",
    "Item Description": "4",
}

#: The "Starting with / Equals / Containing" dropdown. The portal builds it
#: in JavaScript, so it is empty in the HTML: numbers get "Equals", text gets
#: "Containing".
TENDER_MATCH_OPTIONS = {"Starting with": "0", "Equals": "1", "Containing": "2"}

#: Which match options the portal offers for a given search criterion.
TENDER_MATCH_BY_CRITERION = {
    "Tender Number": ("Starting with", "Equals"),
    "Item Code": ("Starting with", "Equals"),
    "Name Of Work": ("Starting with", "Containing"),
    "Item Description": ("Starting with", "Containing"),
}

#: The "Select Date" dropdown. These values are the ones the server wants.
TENDER_DATE_BASIS = {
    "Tender Closing Date": "TENDER_OPENING_DATE",
    "Tender Uploading Date": "TENDER_PUBLISHING_DATE",
}

TENDER_BIDDING_OPTIONS = {"All": "-1", "Single Packet": "0", "Two Packet": "1"}

TENDER_WORK_AREAS = {
    "All": "-1",
    "Works": "WT",
    "Goods & Services": "PT",
    "Earning / Leasing": "LT",
}

TENDER_TYPES = {
    "All": "-1",
    "Limited": "1",
    "Open": "2",
    "Special Limited": "3",
    "Single": "5",
}

#: The "Tender Status" dropdown.
TENDER_STATUS = {
    "All": "-1",
    "Published": "1",
    "Tender Box Open": "2",
    "Under Evaluation": "3",
    "PO Placed": "4",
    "Cancelled": "5",
    "Dropped": "7",
    "Tender Box Opened-Tabulation Pending": "8",
    "Retendered": "9",
    "TABULATION PENDING": "20",
}

#: The "Organization" dropdown on the tender page.
TENDER_ORGANISATIONS = {
    "Indian Railway": "01",
    "KRCL": "02",
    "DMRC": "03",
    "MRVC": "04",
    "CRIS": "05",
    "RITES Limited": "06",
    "RAILTEL": "07",
    "DFCCIL": "08",
    "KERALA RAIL DEVELOPMENT CORPORATION LTD": "09",
    "RAIL VIKAS NIGAM LIMITED": "10",
    "CONTAINER CORPORATION OF INDIA LTD": "11",
    "BRAITHWAITE AND CO. LIMITED": "12",
    "IRCON INTERNATIONAL LIMITED": "15",
    "INDIAN RAILWAY CATERING AND TOURISM CORPORATION LTD": "16",
    "INDIAN RAILWAY FINANCE CORPORATION": "17",
    "KOLKATA METRO RAIL CORPORATION LTD": "18",
}

#: The six tabs across the top of the tender page. The value is what the
#: portal puts in the hidden ``searchParam`` field when the tab is clicked;
#: the label is the button's value, which is what the server dispatches on.
TENDER_TABS = [
    ("Active Tenders Closing Today", "showPageClosed"),
    ("All Active Tenders", "showPageLive"),
    ("Recently Closed Tenders", "closedTender"),
    ("Custom Search", "custumSearch"),
    ("Live & Upcoming e-RA", "showPageLiveAuction"),
    ("Closed e-RA", "showPageClosedAuction"),
]

#: The tab whose value is the form the screenshot shows.
CUSTOM_SEARCH_TAB = "Custom Search"

COUNTRY_CODES = {"India (+91)": "91"}

#: Results table selector, as observed on the live portal. Both the PO grid and
#: the tender grid use the same border colour.
RESULT_TABLE_SELECTOR = "table[bordercolor='#4D817A']"

#: The PO search page refuses a date range wider than two years (the portal's
#: own dateRange() check alerts at 735 days).
MAX_DATE_SPAN_DAYS = 735

#: The tender search page refuses a date range of a year or more (the portal's
#: own dateDifferenceforSearch() check alerts at 366 days).
TENDER_MAX_DATE_SPAN_DAYS = 365

#: The tender grid's columns, in the order the portal renders them.
TENDER_COLUMNS = [
    "Dept/Rly Unit",
    "Tender No",
    "Tender Title",
    "Status",
    "Work Area",
    "Due Date/Time",
    "Due Days",
]

COLUMNS = [
    "Sr",
    "Supplier Name",
    "PO Value",
    "Item Description",
    "PO Sl",
    "Consignee",
    "PO Qty/Unit",
    "T.U.R.",
    "Dely.Dt",
]


@dataclass
class Settings:
    """Everything the app needs to know that is not part of a single search."""

    mobile: str = ""
    country_code: str = "91"
    min_interval: float = 3.0          # seconds between requests
    jitter: float = 1.5
    timeout: int = 45
    max_pages: int = 200
    max_detail_fetches: int = 2000
    output_dir: Path = OUTPUT_DIR
    fetch_details: bool = True

    def load(self) -> "Settings":
        """Load persisted preferences, ignoring anything unreadable."""
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return self
            for key in ("mobile", "country_code", "min_interval", "jitter",
                        "timeout", "max_pages", "max_detail_fetches", "fetch_details"):
                if key in data:
                    setattr(self, key, data[key])
        return self

    def save(self) -> None:
        data = {k: v for k, v in asdict(self).items() if k != "output_dir"}
        data["output_dir"] = str(self.output_dir)
        CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


@dataclass
class SearchCriteria:
    """A single search request. The GUI writes it, the CLI builds it, the
    engine reads it - one object, one code path.

    The portal has two different search forms, so the criteria carry both
    sets of fields and ``mode`` decides which ones are sent.
    """

    # --- shared by both forms --------------------------------------------
    date_from: str = ""                 # dd/mm/yyyy
    date_to: str = ""
    date_basis: str = "Tender Closing Date"
    search_text: str = ""
    mode: str = "po"                    # "po" | "tenders"
    fetch_details: bool = False
    #: Which of the tender page's six tabs the search belongs to. Only the
    #: "Custom Search" tab shows the form; the others are quick views.
    tender_tab: str = CUSTOM_SEARCH_TAB

    # --- purchase order form ---------------------------------------------
    search_option: str = "Tender Title"
    match_mode: str = "Starting with"
    po_value_from: str = "1"
    po_value_to: str = "99999"
    bidding: str = "All"
    tender_stage: str = "Published"

    # --- tender form ------------------------------------------------------
    tender_criteria: str = "Tender Number"
    tender_match: str = "Starting with"
    organisation: str = "-1"
    work_area: str = "All"
    railway_zone: str = "-1"
    division: str = "-1"
    unit: str = "-1"
    tender_status: str = "All"
    tender_type: str = "All"
    tender_bidding: str = "All"

    #: The visible labels, kept for the Filters sheet (the fields above hold
    #: the numeric values the portal actually expects).
    zone_label: str = ""
    division_label: str = ""
    unit_label: str = ""
    organisation_label: str = ""

    def to_payload(self) -> dict:
        """Translate into the field names the portal expects.

        The Purchase Order search page has its own, much smaller form than
        the tender search page. Verified live on 11 Nov 2026: the PO form is
        ``poSearchForm`` posting to ``/epsn/anonymSearchPO.do`` with
        ``plNumber``, ``poValueFrom``, ``poValueTo``, ``dateFrom``,
        ``dateTo``, ``firmAccountId``, ``searchOption`` and ``submit`` - and
        it carries no captcha.
        """
        if self.mode == "po":
            return {
                "plNumber": (self.search_text or "").strip(),
                "poValueFrom": self.po_value_from,
                "poValueTo": self.po_value_to,
                "dateFrom": self.date_from,
                "dateTo": self.date_to,
                "firmAccountId": "%",
                # The organisation/unit dropdown is called "railwayZone" on the
                # live PO search page and "searchOption" on the page the login
                # lands on. Send both and let the form trimming keep the one
                # this form actually has.
                "railwayZone": self.railway_zone,
                "searchOption": self.railway_zone,
                "searchParam": "",
                "submit": "Show Results",
            }
        return self.tender_payload()

    def tender_payload(self) -> dict:
        """The body the tender page expects, field for field.

        Verified live on 11 Nov 2026. Three things are easy to get wrong:

        * ``searchParam`` must be **empty**. The portal's own JavaScript
          writes the tab name into that field only while the tab button is
          being clicked; a custom search sends it blank and carries
          ``activity=submitCustumSearch`` instead.
        * ``activity`` is what tells the server to run the search.
        * ``submit`` must be "Show Results" - the server dispatches on it.

        The organisation dropdown has **no "All" entry** - the portal only
        knows the sixteen organisations it lists. Sending "-1" there makes
        the server answer with an empty result set, so an unset organisation
        falls back to Indian Railway.
        """
        organisation = _organisation_id(self.organisation)
        # The zone, department and unit are ids. A label slipped in by
        # mistake (the portal's own "---Select---" entry, say) would silently
        # empty the result set, so anything that is not an id becomes "All".
        zone = _id_or_all(self.railway_zone)
        division = _id_or_all(self.division)
        unit = _id_or_all(self.unit)
        return {
            "searchOption": TENDER_SEARCH_OPTIONS.get(self.tender_criteria, "1"),
            "searchOptorOption": TENDER_MATCH_OPTIONS.get(self.tender_match, "0"),
            "advancedSearch": (self.search_text or "").strip(),
            "organization": organisation,
            "workArea": TENDER_WORK_AREAS.get(self.work_area, "-1"),
            "changezone": "",
            "railwayZone": zone,
            "division": division,
            "unit": unit,
            "tenderStage": TENDER_STATUS.get(self.tender_status, "-1"),
            "tenderType": TENDER_TYPES.get(self.tender_type, "-1"),
            "bidding": TENDER_BIDDING_OPTIONS.get(self.tender_bidding, "-1"),
            "selectDate": TENDER_DATE_BASIS.get(self.date_basis, "TENDER_OPENING_DATE"),
            "direction": "P",
            "monthDay": "M",
            "noMonthDay": "",
            "radioDuration": "0",
            "dateFrom": self.date_from,
            "dateTo": self.date_to,
            "searchParam": "",
            "activity": "submitCustumSearch",
            "submit": "Show Results",
        }

    def tender_tab_payload(self) -> dict:
        """The body one of the portal's six tab buttons sends.

        A tab click posts the whole form with the tab's own button value and
        the tab's ``searchParam``; the server then shows that view.
        """
        payload = self.tender_payload()
        label, search_param = _tab_values(self.tender_tab)
        payload.update(
            {
                "searchParam": search_param,
                "activity": "",
                "submit": label,
            }
        )
        return payload

    def describe(self) -> list[tuple[str, str]]:
        """Human-readable pairs for the Filters sheet in the exported workbook."""
        if self.mode == "po":
            return [
                ("Target URL", PO_SEARCH_URL),
                ("Date from", self.date_from),
                ("Date to", self.date_to),
                ("Search by", self.date_basis),
                ("Search criteria", self.search_option),
                ("Search for", self.search_text),
                ("Match", self.match_mode),
                ("Railway zone", self.zone_label or self.railway_zone),
                ("Division", self.division_label or self.division),
                ("Unit", self.unit_label or self.unit),
                ("Organisation", self.organisation),
                ("PO value from", self.po_value_from),
                ("PO value to", self.po_value_to),
                ("Bidding system", self.bidding),
                ("Tender status", self.tender_stage),
                ("Fetch detail pages", "yes" if self.fetch_details else "no"),
            ]
        return [
            ("Target URL", TENDER_SEARCH_URL),
            ("Tab", self.tender_tab),
            ("Date from", self.date_from),
            ("Date to", self.date_to),
            ("Date range should be within one year", "yes"),
            ("Select date", self.date_basis),
            ("Search criteria", self.tender_criteria),
            ("Search for", self.search_text),
            ("Match", self.tender_match),
            ("Organization", self.organisation_label or self.organisation),
            ("Work area", self.work_area),
            ("Railway/PU", self.zone_label or self.railway_zone),
            ("Department", self.division_label or self.division),
            ("Unit", self.unit_label or self.unit),
            ("Tender status", self.tender_status),
            ("Tender type", self.tender_type),
            ("Bidding system", self.tender_bidding),
            ("Fetch detail pages", "yes" if self.fetch_details else "no"),
        ]


def _tab_values(tab: str) -> tuple[str, str]:
    """The button label and the ``searchParam`` for one of the six tabs."""
    for label, search_param in TENDER_TABS:
        if label == tab:
            return label, search_param
    return CUSTOM_SEARCH_TAB, "custumSearch"


def _id_or_all(value: str) -> str:
    """A dropdown id, or "-1" for "All" when the value is not one.

    The portal's dropdowns hold ids. A label that slipped in - its own
    "---Select---" entry, say - would make the server answer with an empty
    result set rather than an error.
    """
    text = (value or "").strip()
    if not text or text == "-1":
        return "-1"
    return text if text.lstrip("-").isdigit() else "-1"


def _organisation_id(value: str) -> str:
    """The organisation id, by name or by id.

    The portal's organisation dropdown has no "All" entry, and an
    organisation it does not know makes it answer with an **empty result
    set** rather than an error. So a name is looked up, and anything unknown
    falls back to Indian Railway.
    """
    text = (value or "").strip()
    if not text:
        return TENDER_ORGANISATIONS["Indian Railway"]
    if text.isdigit():
        return text.zfill(2)
    for name, organisation_id in TENDER_ORGANISATIONS.items():
        if name.lower() == text.lower():
            return organisation_id
    return TENDER_ORGANISATIONS["Indian Railway"]


@dataclass
class LogEntry:
    """One line of the run log that ends up in the exported workbook."""

    scope: str
    item: str
    status: str
    rows: int = 0
    http_status: int = 0
    detail: str = ""
    seconds: float = 0.0
    extra: dict = field(default_factory=dict)
