"""Headless command line interface.

Runs exactly the same core as the GUI, so a scheduled job and an interactive
run produce identical output. The only difference is that the CLI never
prompts: it uses the cached session and fails loudly if the session is gone.

Both of the portal's searches are available:

* ``--mode po``      the purchase-order (PO) / supply-contract search
* ``--mode tenders`` the "Search Tender" page, which paginates 25 rows a page
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.auth import GuestAuth, LoginError  # noqa: E402
from core.client import IrepsClient, RateLimiter  # noqa: E402
from core.config import (  # noqa: E402
    BIDDING_OPTIONS,
    CUSTOM_SEARCH_TAB,
    DATE_BASIS,
    MATCH_OPTIONS,
    MAX_DATE_SPAN_DAYS,
    OUTPUT_DIR,
    PO_SEARCH_URL,
    SEARCH_OPTIONS,
    TENDER_BIDDING_OPTIONS,
    TENDER_DATE_BASIS,
    TENDER_MATCH_BY_CRITERION,
    TENDER_MATCH_OPTIONS,
    TENDER_MAX_DATE_SPAN_DAYS,
    TENDER_ORGANISATIONS,
    TENDER_SEARCH_OPTIONS,
    TENDER_SEARCH_URL,
    TENDER_STATUS,
    TENDER_STAGE,
    TENDER_TABS,
    TENDER_TYPES,
    TENDER_WORK_AREAS,
    SearchCriteria,
    Settings,
)
from core.engine import ScrapeEngine  # noqa: E402
from core.normalize import date_window  # noqa: E402
from excel.exporter import export  # noqa: E402

#: The tender grid renders this many rows on a page.
TENDER_ROWS_PER_PAGE = 25

#: Both date vocabularies, so --date-basis works in either mode.
DATE_BASIS_CHOICES = list(DATE_BASIS) + [
    name for name in TENDER_DATE_BASIS if name not in DATE_BASIS
]

#: The six tab labels across the top of the tender page.
TENDER_TAB_LABELS = [label for label, _search_param in TENDER_TABS]


def _open_image(path: Path) -> None:
    """Show the captcha image so it can be typed in by hand."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))
        elif sys.platform == "darwin":
            webbrowser.open(path.as_uri())
        else:
            os.system(f"xdg-open '{path}' >/dev/null 2>&1 &")
    except Exception:
        print(f"Open this file and type what you see: {path}")


def _captcha_prompt(info) -> str:
    """Ask the operator to read the captcha image and type the answer."""
    image_url = getattr(info, "image_url", "")
    if image_url:
        import tempfile

        import requests

        target = Path(tempfile.gettempdir()) / "ireps_captcha.jpg"
        try:
            response = requests.get(image_url, timeout=30)
            target.write_bytes(response.content)
            _open_image(target)
            print(f"Verification code image: {target}")
        except Exception as exc:  # noqa: BLE001
            print(f"Could not download the captcha image ({exc}).")
    answer = input("Type the characters from the verification code: ").strip()
    return answer


# --- name / id resolution ---------------------------------------------------
#
# The portal's dropdowns are addressed by id, but a person reads them by name.
# The CLI accepts either and turns the name into the id the portal wants.


def _is_plain_id(value: str) -> bool:
    """True for '-1', 'all' or a numeric id - no dropdown lookup needed."""
    text = (value or "").strip()
    if not text or text.lower() == "all":
        return True
    return text.lstrip("-").isdigit()


def _match_option(options, text: str) -> str | None:
    """The value of the option whose label matches, ignoring case."""
    wanted = (text or "").strip().lower()
    for option in options:
        if option.label.strip().lower() == wanted:
            return option.value
    return None


def _label_of(options, value: str) -> str:
    """The label of the option with this value (the value itself if unknown)."""
    for option in options:
        if option.value == value:
            return option.label
    return value


def _resolve_organisation(value: str) -> tuple[str, str]:
    """Turn an organisation name (or id) into the value the portal wants.

    Returns ``(value, label)``.
    """
    text = (value or "").strip()
    if not text or text.lower() == "all":
        return "-1", "All"
    for name, organisation_id in TENDER_ORGANISATIONS.items():
        if text.lower() == name.lower():
            return organisation_id, name
    if text.isdigit():
        return text.zfill(2), text
    return text, text


def _tender_selects(client) -> dict:
    """The tender page's own dropdowns, read live from the portal."""
    from core.discovery import discover

    try:
        return discover(client.get(TENDER_SEARCH_URL).text).selects
    except Exception as exc:  # noqa: BLE001 - reported to the user below
        print(f"Could not read the tender page: {exc}")
        return {}


def _resolve_option(value: str, options) -> tuple[str, str]:
    """Resolve a dropdown value given as a name or as an id.

    Returns ``(value, label)``. An empty value means the name was not found.
    """
    text = (value or "").strip()
    if not text or text.lower() == "all":
        return "-1", "All"
    if text.lstrip("-").isdigit():
        return text, text
    found = _match_option(options, text)
    if found is None:
        return "", ""
    return found, _label_of(options, found)


def _resolve_zone(client, value: str, organisation: str, selects: dict) -> tuple[str, str]:
    """Resolve the Railway/PU, by name or by id."""
    text = (value or "").strip()
    if not text or text.lower() == "all":
        return "-1", "All"
    if text.lstrip("-").isdigit():
        return text, text
    options = list(selects.get("railwayZone") or [])
    found = _match_option(options, text)
    if found is None:
        # The page only carries the first, static list; the portal fills the
        # rest over AJAX, exactly as its own JavaScript does.
        from core.discovery import fetch_tender_zones

        options = options + list(fetch_tender_zones(client, organisation))
        found = _match_option(options, text)
    if found is None:
        return "", ""
    return found, _label_of(options, found)


def _resolve_unit(client, value: str, division: str, zone: str, work_area: str,
                  selects: dict) -> tuple[str, str]:
    """Resolve the unit, by name or by id."""
    text = (value or "").strip()
    if not text or text.lower() == "all":
        return "-1", "All"
    if text.lstrip("-").isdigit():
        return text, text
    options = list(selects.get("unit") or [])
    found = _match_option(options, text)
    if found is None:
        from core.discovery import fetch_tender_units

        options = options + list(fetch_tender_units(client, division, zone, work_area))
        found = _match_option(options, text)
    if found is None:
        return "", ""
    return found, _label_of(options, found)


# --- the two searches --------------------------------------------------------


def _build_po_criteria(args, date_from: str, date_to: str, date_basis: str) -> SearchCriteria:
    """Build the purchase-order search criteria."""
    criteria = SearchCriteria(
        date_from=date_from,
        date_to=date_to,
        date_basis=date_basis,
        search_option=args.criteria,
        search_text=args.text,
        match_mode=args.match,
        railway_zone=args.zone,
        division="All",
        unit="All",
        po_value_from=args.po_min,
        po_value_to=args.po_max,
        bidding=args.bidding,
        tender_stage=args.status,
        mode="po",
    )
    criteria.fetch_details = bool(args.details)
    criteria.zone_label = args.zone
    return criteria


def _build_tender_criteria(args, client, date_from: str, date_to: str,
                            date_basis: str) -> SearchCriteria | None:
    """Build the tender search criteria, resolving every name given.

    Returns ``None`` when a name could not be resolved, after explaining why.
    """
    organisation, organisation_label = _resolve_organisation(args.organisation)

    # The live page is only needed when a name (not an id) was given.
    selects = {}
    if not all(_is_plain_id(value) for value in (args.zone, args.department, args.unit)):
        selects = _tender_selects(client)

    zone, zone_label = _resolve_zone(client, args.zone, organisation, selects)
    if not zone:
        print(f"Unknown Railway/PU: {args.zone!r}. "
              "Run with --list-units to see the names the portal offers.")
        return None

    division, division_label = _resolve_option(args.department,
                                                list(selects.get("division") or []))
    if not division:
        print(f"Unknown department: {args.department!r}. The portal's department "
              "ids are numbers - pass the id, or the exact name from the page.")
        return None

    unit, unit_label = _resolve_unit(client, args.unit, division, zone,
                                      TENDER_WORK_AREAS.get(args.work_area, "-1"),
                                      selects)
    if not unit:
        print(f"Unknown unit: {args.unit!r}. Pass the unit id, or the exact name "
              "the portal lists for this department.")
        return None

    text = (args.text or "").strip()
    if text and len(text) < 3:
        print("The tender search needs at least 3 characters in --text.")
        return None

    allowed = TENDER_MATCH_BY_CRITERION.get(args.tender_criteria, ())
    if allowed and args.tender_match not in allowed:
        print(f"Note: for '{args.tender_criteria}' the portal offers only "
              f"{' and '.join(allowed)} - '{args.tender_match}' may be ignored.")

    criteria = SearchCriteria(
        mode="tenders",
        date_from=date_from,
        date_to=date_to,
        date_basis=date_basis,
        search_text=args.text,
        tender_criteria=args.tender_criteria,
        tender_match=args.tender_match,
        organisation=organisation,
        work_area=args.work_area,
        railway_zone=zone,
        division=division,
        unit=unit,
        tender_status=args.tender_status,
        tender_type=args.tender_type,
        tender_bidding=args.tender_bidding,
        tender_tab=args.tab,
    )
    criteria.fetch_details = bool(args.details)
    criteria.zone_label = zone_label
    criteria.division_label = division_label
    criteria.unit_label = unit_label
    criteria.organisation_label = organisation_label
    return criteria


def _tender_only_notes(args, parser) -> list[str]:
    """The tender-only flags that were set but do not apply in PO mode."""
    flags = [
        ("tender_criteria", "--tender-criteria"),
        ("tender_match", "--tender-match"),
        ("organisation", "--organisation"),
        ("work_area", "--work-area"),
        ("department", "--department"),
        ("unit", "--unit"),
        ("tender_status", "--tender-status"),
        ("tender_type", "--tender-type"),
        ("tender_bidding", "--tender-bidding"),
        ("tab", "--tab"),
    ]
    notes = []
    for dest, flag in flags:
        value = getattr(args, dest, None)
        if value is not None and value != parser.get_default(dest):
            notes.append(flag)
    return notes


# --- listing the portal's own options ---------------------------------------


def _list_po_units(client) -> int:
    """Print the PO page's organisation / unit list."""
    from core.discovery import discover

    info = discover(client.get(PO_SEARCH_URL).text)
    entries = info.selects.get("railwayZone") or info.selects.get("searchOption") or []
    print("Organisation / unit options (value  label):")
    for option in entries:
        print(f"  {option.value:>10}  {option.label}")
    return 0


def _list_tender_units(client, args) -> int:
    """Print the tender page's organisation and Railway/PU lists."""
    from core.discovery import discover, fetch_tender_zones

    organisation, _label = _resolve_organisation(args.organisation)
    print("Organisation options (value  label):")
    for name, organisation_id in TENDER_ORGANISATIONS.items():
        print(f"  {organisation_id:>10}  {name}")

    print(f"\nRailway / PU options for {args.organisation} (value  label):")
    options = fetch_tender_zones(client, organisation)
    if not options:
        # The AJAX list was empty - fall back to the page's own static list.
        info = discover(client.get(TENDER_SEARCH_URL).text)
        options = list(info.selects.get("railwayZone") or [])
    for option in options:
        print(f"  {option.value:>10}  {option.label}")
    if not options:
        print("  (the portal returned no list)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ireps_scraper",
        description=(
            "Scrape the IREPS portal into a formatted Excel workbook.\n"
            "  --mode po      the purchase-order (PO) / supply-contract search\n"
            "  --mode tenders the 'Search Tender' page - it paginates, 25 rows a page"
        ),
        epilog=(
            "Examples:\n"
            "  ireps_scraper --mode po --from 01/11/2026 --to 30/11/2026 --text GE\n"
            "  ireps_scraper --mode tenders --from 01/10/2026 --to 30/10/2026 "
            "--tender-criteria 'Tender Number' --text 123456\n"
            "  ireps_scraper --mode tenders --list-units"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--mode", choices=["po", "tenders"], default="po",
                        help="Which search to run: 'po' (purchase orders, default) "
                             "or 'tenders' (the portal's 'Search Tender' page)")
    parser.add_argument("--from", dest="date_from", help="dd/mm/yyyy")
    parser.add_argument("--to", dest="date_to", help="dd/mm/yyyy")
    parser.add_argument("--zone", default="-1",
                        help="PO mode: the organisation / unit id from the portal. "
                             "Tender mode: the Railway/PU id or name. "
                             "(default -1 = All. Use --list-units to see them.)")
    parser.add_argument("--list-units", action="store_true",
                        help="Print the organisation/unit options the portal offers, then exit")
    parser.add_argument("--criteria", default="Tender Title", choices=list(SEARCH_OPTIONS),
                        help="PO mode: what --text is matched against")
    parser.add_argument("--text", default="",
                        help="PL number or search text - the 'Search For' box in both modes")
    parser.add_argument("--match", default="Starting with", choices=list(MATCH_OPTIONS),
                        help="PO mode: how --text is matched")
    parser.add_argument("--po-min", default="1", help="PO mode: lowest PO number")
    parser.add_argument("--po-max", default="99999", help="PO mode: highest PO number")
    parser.add_argument("--date-basis", default=None, choices=DATE_BASIS_CHOICES,
                        help="Which date to search on (default: 'Tender Uploading Date' "
                             "in PO mode, 'Tender Closing Date' in tender mode)")
    parser.add_argument("--bidding", default="All", choices=list(BIDDING_OPTIONS),
                        help="PO mode: the bidding system")
    parser.add_argument("--status", default="Published", choices=list(TENDER_STAGE),
                        help="PO mode: the tender stage")
    parser.add_argument("--tender-criteria", default="Tender Number",
                        choices=list(TENDER_SEARCH_OPTIONS),
                        help="Tender mode: what --text is matched against")
    parser.add_argument("--tender-match", default="Starting with",
                        choices=list(TENDER_MATCH_OPTIONS),
                        help="Tender mode: how --text is matched")
    parser.add_argument("--organisation", default="Indian Railway", metavar="NAME_OR_ID",
                        help="Tender mode: the organisation, by name or id "
                             "(default: Indian Railway, which is 01)")
    parser.add_argument("--work-area", default="All", choices=list(TENDER_WORK_AREAS),
                        help="Tender mode: Works / Goods & Services / Earning / Leasing")
    parser.add_argument("--department", default="-1", metavar="ID_OR_NAME",
                        help="Tender mode: the department (division) id or name "
                             "(default -1 = All)")
    parser.add_argument("--unit", default="-1", metavar="ID_OR_NAME",
                        help="Tender mode: the unit id or name (default -1 = All)")
    parser.add_argument("--tender-status", default="All", choices=list(TENDER_STATUS),
                        help="Tender mode: the tender status")
    parser.add_argument("--tender-type", default="All", choices=list(TENDER_TYPES),
                        help="Tender mode: the tender type")
    parser.add_argument("--tender-bidding", default="All", choices=list(TENDER_BIDDING_OPTIONS),
                        help="Tender mode: single packet or two packet")
    parser.add_argument("--tab", default=CUSTOM_SEARCH_TAB, choices=TENDER_TAB_LABELS,
                        help="Tender mode: which of the portal's six tabs to run "
                             "(default 'Custom Search')")
    parser.add_argument("--details", action="store_true", help="Also fetch every detail page")
    parser.add_argument("--out", default=str(OUTPUT_DIR),
                        help="Where to write the workbook")
    parser.add_argument("--max-pages", type=int, default=200,
                        help="Stop after this many pages - tender mode paginates "
                             "25 rows a page, so a long search needs a high limit")
    parser.add_argument("--min-interval", type=float, default=3.0,
                        help="Seconds to wait between requests")
    parser.add_argument("--mobile", default="", help="Mobile number for the OTP")
    parser.add_argument("--login", action="store_true",
                        help="Sign in interactively first (asks for the captcha and the OTP)")
    parser.add_argument("--debug", action="store_true", help="Keep the raw results HTML")
    return parser


def _default_date_basis(mode: str) -> str:
    """The date column each mode searches on when --date-basis is not given."""
    return "Tender Closing Date" if mode == "tenders" else "Tender Uploading Date"


def _check_date_span(mode: str, start: datetime, end: datetime) -> str:
    """The portal's own limit for the date range, as an error message.

    The PO page allows a range of up to two years, the tender page only one.
    """
    span = (end - start).days
    if mode == "tenders":
        if span >= TENDER_MAX_DATE_SPAN_DAYS:
            return (f"The tender page rejects a date range of a year or more "
                    f"(you asked for {span} days).")
        return ""
    if span > MAX_DATE_SPAN_DAYS:
        return "The portal rejects a PO date range longer than two years."
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    mode = args.mode
    settings = Settings().load()
    settings.mobile = args.mobile or settings.mobile
    settings.min_interval = args.min_interval
    settings.max_pages = args.max_pages
    settings.output_dir = Path(args.out)

    client = IrepsClient(
        limiter=RateLimiter(settings.min_interval, settings.jitter),
        timeout=settings.timeout,
    )
    auth = GuestAuth(client, settings.mobile, settings.country_code)

    if args.login:
        print("Signing in to IREPS...")
        try:
            auth.open_guest_page()
            captcha = auth.fetch_captcha()
            import tempfile
            from pathlib import Path as _Path

            target = _Path(tempfile.gettempdir()) / "ireps_login_captcha.jpg"
            target.write_bytes(captcha.image)
            _open_image(target)
            print(f"Verification code image: {target}")
            answer = input("Type the characters from the image: ").strip()
            outcome = auth.request_otp(answer)
            if outcome != "OK":
                print(f"Could not request the OTP: {outcome}")
                return 2
            otp = input("Enter the OTP from the SMS: ").strip()
            if not auth.submit_otp(otp):
                print("The OTP was not accepted.")
                return 2
            auth.save_session()
            print("Signed in. The session is cached for today.")
        except LoginError as exc:
            print(f"Sign in failed: {exc}")
            return 2
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return 130
    else:
        auth.load_session()
        if not auth.is_authenticated():
            print("No valid cached session. Run once with --login, or sign in from the GUI.")
            return 2

    if args.list_units:
        if mode == "tenders":
            return _list_tender_units(client, args)
        return _list_po_units(client)

    date_from, date_to = args.date_from, args.date_to
    if not date_from or not date_to:
        date_from, date_to = date_window(30)
        print(f"No date range given, using the last 30 days: {date_from} to {date_to}")

    try:
        start = datetime.strptime(date_from, "%d/%m/%Y")
        end = datetime.strptime(date_to, "%d/%m/%Y")
    except ValueError:
        print("Dates must be written as dd/mm/yyyy.")
        return 2
    if end < start:
        print("Date To cannot be earlier than Date From.")
        return 2

    date_basis = args.date_basis or _default_date_basis(mode)
    problem = _check_date_span(mode, start, end)
    if problem:
        print(problem)
        return 2

    if mode == "tenders":
        criteria = _build_tender_criteria(args, client, date_from, date_to, date_basis)
        if criteria is None:
            return 2
    else:
        criteria = _build_po_criteria(args, date_from, date_to, date_basis)
        ignored = _tender_only_notes(args, parser)
        if ignored:
            print("Ignoring the tender-only flags in PO mode: " + ", ".join(ignored))

    engine = ScrapeEngine(client, settings)
    cancel = threading.Event()
    pages = 0
    collected = 0

    def on_progress(event: dict) -> None:
        nonlocal pages, collected
        kind = event.get("kind")
        if kind == "status":
            message = event.get("message", "")
            print(f"  {message}")
            if mode == "tenders" and "the portal reported" in message:
                print(f"  -> {pages} page(s) fetched "
                      f"({TENDER_ROWS_PER_PAGE} tender rows per page).")
        elif kind == "page":
            pages = int(event.get("page") or 0)
            rows = int(event.get("rows") or 0)
            collected += rows
            if mode == "tenders":
                print(f"  page {pages} - {rows} rows ({collected} collected)")
            else:
                print(f"  page {pages} - {rows} rows")
        elif kind == "error":
            print(f"  ERROR: {event.get('message')}")

    result = engine.run(criteria, captcha_prompt=_captcha_prompt,
                         progress=on_progress, cancel_event=cancel)

    if mode == "tenders":
        total = result.total_count or 0
        if total:
            needed = -(-total // TENDER_ROWS_PER_PAGE)
            print(f"\nThe portal reported {total} tenders - about {needed} page(s) "
                  f"of {TENDER_ROWS_PER_PAGE} rows.")
            if result.pages_fetched >= settings.max_pages and len(result.records) < total:
                print("The --max-pages limit stopped the run before every page was "
                      "fetched. Raise it and run again to collect the rest.")
        else:
            print("\nThe portal did not report a total for this search.")

    if not result.records:
        print("No records were returned.")
        return 1

    path = export(result.records, result, criteria, settings.output_dir)
    print(f"\nSaved {len(result.records)} records to:\n  {path}")
    print(f"  pages {result.pages_fetched} | details fetched {result.details_fetched} "
          f"| cached {result.details_cached} | failed {result.details_failed} "
          f"| {result.elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
