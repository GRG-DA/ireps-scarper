"""End-to-end test of the tender flow against a fake IREPS server.

The tender search is the part of the portal that broke first: the results
grid is wrapped in several layout tables, every row keeps its detail link
inside an ``onclick`` attribute and the rows are spread over several pages.
This test serves a synthetic portal - a search page, a paginated results
grid and the tender detail pages - drives the real core (engine + exporter)
against it and checks what comes out.

    python tests/test_tender_flow.py
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.detail as detail_module  # noqa: E402
from core.client import IrepsClient  # noqa: E402
from core.config import SearchCriteria, Settings  # noqa: E402
from core.engine import ScrapeEngine  # noqa: E402

# --- the pages the fake portal serves ---------------------------------------

#: The tender search page: the form the engine posts its criteria to.
SEARCH_PAGE = """
<html><head><title>Search Tender</title></head><body>
<form name="tenderSearchForm" method="post" action="/epsn/anonymSearch.do">
  <input type="hidden" name="searchParam" id="searchParam" value="">
  <input type="hidden" name="activity" id="activity" value="">
  <select name="searchOption"><option value="1">Tender Number</option>
    <option value="2">Name Of Work</option></select>
  <select name="searchOptorOption"><option value="0">Starting with</option>
    <option value="1">Equals</option></select>
  <input type="text" name="advancedSearch" id="advancedSearch" value="">
  <select name="organization"><option value="01">Indian Railway</option>
    <option value="-1">All</option></select>
  <select name="workArea"><option value="-1">All</option>
    <option value="PT">Goods &amp; Services</option></select>
  <select name="railwayZone"><option value="-1">All</option>
    <option value="483">Western Railway</option></select>
  <select name="division"><option value="-1">All</option></select>
  <select name="unit"><option value="-1">All</option></select>
  <select name="tenderStage"><option value="-1">All</option>
    <option value="1">Published</option></select>
  <select name="tenderType"><option value="-1">All</option>
    <option value="1">Limited</option></select>
  <select name="bidding"><option value="-1">All</option>
    <option value="0">Single Packet</option></select>
  <select name="selectDate"><option value="TENDER_OPENING_DATE">Tender Closing Date</option>
    <option value="TENDER_PUBLISHING_DATE">Tender Uploading Date</option></select>
  <input type="text" name="dateFrom" id="ddmmyyDateformat1" value="01/10/2026" readonly="readonly">
  <input type="text" name="dateTo" id="ddmmyyDateformat2" value="11/11/2026" readonly="readonly">
  <input type="submit" name="submit" tabindex="7" value="Show Results">
</form>
</body></html>
"""

#: The grid's own label row. The parser looks for exactly this row.
GRID_HEADER = """<tr height="20" align="center" style="background-color: #D9D9D9">
  <td class="formLabel">Deptt./Rly. Unit&nbsp;</td>
  <td class="formLabel">Tender No&nbsp;</td>
  <td class="formLabel">Tender Title&nbsp;</td>
  <td class="formLabel">Status&nbsp;</td>
  <td class="formLabel">Work Area&nbsp;</td>
  <td class="formLabel">Due Date/Time&nbsp;</td>
  <td class="formLabel">Due Days&nbsp;</td>
  <td class="formLabel">Actions&nbsp;</td>
</tr>"""


def grid_row(dept: str, number: str, title: str, status: str, work_area: str,
             due: str, days: str, oid: str) -> str:
    """One row of the tender grid.

    The "View Details" link carries the real address in its ``onclick``
    attribute - the href is only a placeholder - and the opaque tender id
    travels in that address.
    """
    return f"""<tr height="20">
  <td bgcolor="white">{dept}&nbsp;</td>
  <td bgcolor="white"><span style="color:BLACK;">{number}</span>&nbsp;</td>
  <td bgcolor="white"><span class="dataText">{title}</span></td>
  <td align="center" bgcolor="#00CCFF">{status}&nbsp;</td>
  <td bgcolor="white">{work_area}&nbsp;</td>
  <td bgcolor="white">{due}&nbsp;</td>
  <td bgcolor="white">{days}&nbsp;</td>
  <td bgcolor="white"><a href="#" onclick="postRequestNewWindow('/epsn/nitViewAnonyms/rfq/nitPublish.do?tenderAnonymsOid={oid}&activity=viewNIT', 'nitPublish.do', 'width=900,height=700')"><img src="/ireps/images/common/View Details.png"></a>&nbsp;</td>
</tr>"""


#: The tenders of page one.
PAGE_ONE_ROWS = "".join([
    grid_row("DAHOD/WESTERN RLY", "61265953A", "Tecspak pad of Side Bearer",
             "Tender Finalized", "Goods &amp; Service", "01/10/2026 11:00",
             "LAPSED", "ay+YPtpiUUECwgIvUE41/w=="),
    grid_row("MUMBAI/CENTRAL RLY", "61266012B",
             "Supply of 5 ton capacity hydraulic trolley", "Tender Opened",
             "Works", "05/11/2026 15:30", "12", "bZ+QRstVVWDFxgIwVAE52/X=="),
])

#: The tenders of page two - the engine has to ask for this page itself.
PAGE_TWO_ROWS = "".join([
    grid_row("PUNE/WESTERN RLY", "61266145C", "Repairs to platform roof at Pune",
             "Tender Opened", "Works", "08/11/2026 12:00", "9",
             "cP+SAbcWWEFYhJxWBAF63/Y=="),
    grid_row("AHMEDABAD/WESTERN RLY", "61266278D",
             "Supply of branded uniform cloth", "Tender Finalized",
             "Goods &amp; Service", "09/11/2026 17:00", "LAPSED",
             "dQR+TcdXXFGZiKyWCAG74/Z=="),
])

#: The pagination the portal renders under the grid. The page links live in
#: an onclick attribute - the portal builds them with a JavaScript helper.
PAGINATION = """<table border="0" width="100%" align="center"><tr>
  <td class="formLabel" align="center">
    <a href="#" onclick="postRequest('/epsn/anonymSearch.do?division=-1&amp;unit=-1&amp;tenderStage=-1&amp;tenderType=-1&amp;bidding=-1&amp;advancedSearch=&amp;searchParam=&amp;searchOption=1&amp;searchOptorOption=0&amp;railwayZone=483&amp;dateFrom=01/10/2026&amp;dateTo=11/11/2026&amp;linkVal=department&amp;selectDate=TENDER_OPENING_DATE&amp;count=4&amp;pageNo=1')">1</a>
    <a href="#" onclick="postRequest('/epsn/anonymSearch.do?division=-1&amp;unit=-1&amp;tenderStage=-1&amp;tenderType=-1&amp;bidding=-1&amp;advancedSearch=&amp;searchParam=&amp;searchOption=1&amp;searchOptorOption=0&amp;railwayZone=483&amp;dateFrom=01/10/2026&amp;dateTo=11/11/2026&amp;linkVal=department&amp;selectDate=TENDER_OPENING_DATE&amp;count=4&amp;pageNo=2')">2</a>
  </td>
</tr></table>"""


def results_page(count: int, rows: str) -> str:
    """A results page.

    The grid is nested inside the portal's layout tables - that nesting is
    what made the first implementation read the whole page instead of the
    grid, so the test reproduces it.
    """
    return f"""<html><body>
<div class="formHeader">
  <table border="0" width="100%"><tr><td>
    <table border="1" width="100%" align="center"><tr>
      <td class="formLabel"><b>&nbsp;Tender search results &nbsp;</b><B>{count}</B></td>
    </tr></table>
  </td></tr></table>
</div>
<table border="0" width="100%" align="center"><tr><td>
  <table border="1" bordercolor="#4D817A" cellspacing="0" width="100%" align="center">
{GRID_HEADER}
{rows}
  </table>
</td></tr></table>
{PAGINATION}
</body></html>"""


RESULTS_PAGE_ONE = results_page(4, PAGE_ONE_ROWS)
RESULTS_PAGE_TWO = results_page(4, PAGE_TWO_ROWS)


def detail_page(number: str, dept: str, closing: str, title: str,
                kind: str, status: str) -> str:
    """A tender's own detail page - a table of label/value pairs."""
    return f"""<html><body><table border="1" align="center">
<tr><td>Tender No:</td><td>{number}</td></tr>
<tr><td>Dept/Rly:</td><td>{dept}</td></tr>
<tr><td>Closing Date/Time:</td><td>{closing}</td></tr>
<tr><td>Tender Title:</td><td>{title}</td></tr>
<tr><td>Tender Type:</td><td>{kind}</td></tr>
<tr><td>Tender Status</td><td>{status}</td></tr>
</table></body></html>"""


#: The detail pages, keyed by the id the engine posts (already truncated at
#: the first "=", exactly as the portal's own JavaScript does it).
DETAIL_PAGES = {
    "ay+YPtpiUUECwgIvUE41/w": detail_page(
        "61265953A", "DAHOD/WESTERN RLY", "01/10/2026 11:00",
        "Tecspak pad of Side Bearer", "Limited", "Tender Opened"),
    "bZ+QRstVVWDFxgIwVAE52/X": detail_page(
        "61266012B", "MUMBAI/CENTRAL RLY", "05/11/2026 15:30",
        "Supply of 5 ton capacity hydraulic trolley", "Open", "Tender Opened"),
    "cP+SAbcWWEFYhJxWBAF63/Y": detail_page(
        "61266145C", "PUNE/WESTERN RLY", "08/11/2026 12:00",
        "Repairs to platform roof at Pune", "Limited", "Tender Opened"),
    "dQR+TcdXXFGZiKyWCAG74/Z": detail_page(
        "61266278D", "AHMEDABAD/WESTERN RLY", "09/11/2026 17:00",
        "Supply of branded uniform cloth", "Open", "Tender Opened"),
}

#: Every request the fake client was asked to make: (method, url, body).
REQUESTS: list[tuple[str, str, dict]] = []


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.url = "https://www.ireps.gov.in/epsn/anonymSearch.do"


def install_fake_client(client: IrepsClient) -> None:
    """Point the client at the synthetic pages.

    Nothing here touches the network: the client's own request method is
    replaced, so neither the session nor the rate limiter is used.
    """

    def fake_get(url, **kwargs):
        REQUESTS.append(("GET", url, {}))
        return FakeResponse(SEARCH_PAGE)

    def fake_post(url, **kwargs):
        data = dict(kwargs.get("data") or {})
        REQUESTS.append(("POST", url, data))
        if "nitPublish.do" in url:
            return FakeResponse(DETAIL_PAGES.get(data.get("tenderAnonymsOid", ""),
                                                detail_page("", "", "", "", "", "")))
        if str(data.get("pageNo", "")) == "2":
            return FakeResponse(RESULTS_PAGE_TWO)
        return FakeResponse(RESULTS_PAGE_ONE)

    client.get = fake_get          # type: ignore[method-assign]
    client.post = fake_post        # type: ignore[method-assign]


def build_criteria() -> SearchCriteria:
    """A tender search with every filter the portal offers."""
    return SearchCriteria(
        mode="tenders",
        date_from="01/10/2026",
        date_to="11/11/2026",
        date_basis="Tender Closing Date",
        search_text="",
        tender_criteria="Tender Number",
        tender_match="Starting with",
        organisation="01",
        work_area="Goods & Services",
        railway_zone="483",
        division="-1",
        unit="-1",
        tender_status="Published",
        tender_type="Limited",
        tender_bidding="All",
        fetch_details=True,
    )


def main() -> int:
    from excel.exporter import export

    criteria = build_criteria()

    # --- 1. the request body the portal is asked for ---------------------
    payload = criteria.tender_payload()
    print("tender payload:")
    for key in sorted(payload):
        print(f"    {key:18s} = {payload[key]!r}")

    assert payload["searchParam"] == "", (
        "searchParam must be empty for a custom search, not 'custumSearch'")
    assert payload["activity"] == "submitCustumSearch", (
        "the portal runs the search on activity=submitCustumSearch")
    assert payload["submit"] == "Show Results", (
        "the portal dispatches on the submit button")
    assert payload["searchOption"] == "1", "Tender Number is search option 1"
    assert payload["searchOptorOption"] == "0", "Starting with is match option 0"
    assert payload["organization"] == "01", "the chosen organisation must travel"
    assert payload["workArea"] == "PT", "Goods & Services is work area PT"
    assert payload["railwayZone"] == "483", "the chosen railway must travel"
    assert payload["division"] == "-1" and payload["unit"] == "-1"
    assert payload["tenderStage"] == "1", "Published is tender stage 1"
    assert payload["tenderType"] == "1", "Limited is tender type 1"
    assert payload["bidding"] == "-1"
    assert payload["selectDate"] == "TENDER_OPENING_DATE"
    assert payload["dateFrom"] == "01/10/2026"
    assert payload["dateTo"] == "11/11/2026"

    # The portal's organisation dropdown has no "All" entry, and an unknown
    # organisation makes it answer with an empty result set instead of an
    # error - so an unset organisation must fall back to Indian Railway.
    for unset in ("", "-1", None):
        fallback = replace(criteria, organisation=unset).tender_payload()
        assert fallback["organization"] == "01", (
            f"organisation {unset!r} must fall back to Indian Railway, "
            f"not {fallback['organization']!r}")

    # A name is resolved to the id the portal wants, and a label that slipped
    # in by mistake must never travel as-is.
    by_name = replace(criteria, organisation="Indian Railway").tender_payload()
    assert by_name["organization"] == "01", "the organisation name must become its id"
    by_id = replace(criteria, organisation="05").tender_payload()
    assert by_id["organization"] == "05", "CRIS is organisation 05"
    nonsense = replace(criteria, organisation="Nowhere").tender_payload()
    assert nonsense["organization"] == "01", (
        "an organisation the portal does not know must fall back to Indian Railway")

    # The zone, department and unit are ids. A label slipped in by mistake -
    # the portal's own "---Select---" entry - would empty the result set.
    for label in ("---Select---", "", "Western Railway"):
        sloppy = replace(criteria, railway_zone=label).tender_payload()
        assert sloppy["railwayZone"] in ("-1", "483"), (
            f"railway zone {label!r} must not travel as a label")
    assert replace(criteria, division="Commercial").tender_payload()["division"] == "-1"

    print("\npayload checks: OK")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        # Keep the detail cache out of the project: the test must fetch the
        # detail pages, not read them back from a previous run.
        old_cache_dir = detail_module.CACHE_DIR
        detail_module.CACHE_DIR = tmp_dir / "detail_cache"
        try:
            client = IrepsClient()
            install_fake_client(client)
            settings = Settings(min_interval=0.0, jitter=0.0, max_pages=10)
            settings.output_dir = tmp_dir / "output"

            engine = ScrapeEngine(client, settings)
            result = engine.run(criteria)
        finally:
            detail_module.CACHE_DIR = old_cache_dir

        # --- 2. what the engine actually sent ---------------------------
        print("\nrequests the engine made:")
        for method, url, body in REQUESTS:
            print(f"    {method} {url}")
            if body:
                print(f"        {body}")

        method, url, _ = REQUESTS[0]
        assert method == "GET" and url.endswith("/epsn/anonymSearch.do"), (
            "the tender search page is the one to open")

        search_bodies = [body for method, url, body in REQUESTS
                         if method == "POST" and "nitPublish.do" not in url]
        assert search_bodies, "the search was never posted"
        sent = search_bodies[0]
        assert sent["searchParam"] == "", "searchParam must go out empty"
        assert sent["activity"] == "submitCustumSearch"
        assert sent["submit"] == "Show Results"
        assert sent["railwayZone"] == "483"
        assert sent["dateFrom"] == "01/10/2026"
        assert sent["dateTo"] == "11/11/2026"

        # --- 3. pagination ----------------------------------------------
        page_bodies = [body for body in search_bodies if "pageNo" in body]
        assert len(page_bodies) == 1, (
            f"expected one request for a second page, got {len(page_bodies)}")
        page_two = page_bodies[0]
        assert page_two["pageNo"] == "2", "the second page must be asked for"
        assert page_two["railwayZone"] == "483", (
            "a page request keeps the criteria of the search")
        assert page_two["dateFrom"] == "01/10/2026"
        assert "submit" not in page_two and "activity" not in page_two, (
            "a page request asks for a page, not for a new search")
        print(f"\npagination: page {page_two['pageNo']} requested "
              f"(count={page_two.get('count')}, linkVal={page_two.get('linkVal')})")

        # --- 4. the rows that were parsed -------------------------------
        print(f"\nrecords collected: {len(result.records)}")
        print(f"pages fetched: {result.pages_fetched} | portal count: {result.total_count}")
        for record in result.records:
            print(f"    {record['Tender No']:12s} {record['Dept/Rly Unit']:24s} "
                  f"{record['Status']:18s} {record['Due Date/Time']:17s} "
                  f"{record['Tender ID']}")

        assert len(result.records) == 4, (
            f"expected 4 tenders from two pages, got {len(result.records)}")
        assert result.pages_fetched == 2, "both pages should have been fetched"
        assert result.total_count == 4

        first = result.records[0]
        assert first["Tender No"] == "61265953A"
        assert first["Tender Title"] == "Tecspak pad of Side Bearer"
        assert first["Status"] == "Tender Finalized"
        assert first["Work Area"] == "Goods & Service"
        assert first["Due Date/Time"] == "01/10/2026 11:00"
        assert first["Due Days"] == "LAPSED"
        assert first["Dept/Rly Unit"] == "DAHOD/WESTERN RLY"
        assert isinstance(first["Due Date"], datetime), (
            "the due date must be a datetime, not text")
        assert first["Due Date"] == datetime(2026, 10, 1, 11, 0)
        assert first["Tender ID"] == "ay+YPtpiUUECwgIvUE41/w==", (
            "the opaque id must come out of the onclick link")
        assert first["Source URL"].endswith(
            "nitPublish.do?tenderAnonymsOid=ay+YPtpiUUECwgIvUE41/w==&activity=viewNIT"
        ), "the detail page address must be built from the tender id"

        numbers = [record["Tender No"] for record in result.records]
        assert len(numbers) == len(set(numbers)), "a tender was collected twice"
        assert numbers == ["61265953A", "61266012B", "61266145C", "61266278D"], (
            "the rows of both pages must be in the result")

        # --- 5. the detail pages ----------------------------------------
        detail_bodies = [body for method, url, body in REQUESTS
                         if method == "POST" and "nitPublish.do" in url]
        assert len(detail_bodies) == 4, (
            f"expected a detail request per tender, got {len(detail_bodies)}")
        for body in detail_bodies:
            assert body["activity"] == "viewNIT"
            assert "=" not in body["tenderAnonymsOid"], (
                "the id must be truncated at the first '='")
        assert detail_bodies[0]["tenderAnonymsOid"] == "ay+YPtpiUUECwgIvUE41/w", (
            "the id must be truncated the way the portal's JavaScript does it")
        print("\ndetail requests:")
        for body in detail_bodies:
            print(f"    {body}")

        assert result.details_fetched == 4
        assert result.details_failed == 0
        assert first["Tender Type"] == "Limited", (
            "the tender type comes from the detail page")
        assert first["Tender Status"] == "Tender Opened", (
            "the tender status comes from the detail page")
        assert first["Detail Fetched"] == "fetched"

        # --- 6. the workbook ---------------------------------------------
        path = export(result.records, result, criteria, tmp_dir / "output",
                      timestamp="20261111_120000")
        print(f"\nexported: {path.name} ({path.stat().st_size} bytes)")

        import openpyxl

        workbook = openpyxl.load_workbook(path)
        print("sheets:", workbook.sheetnames)
        assert workbook.sheetnames == ["README", "Tender_Data", "Tender_Details",
                                       "Summary", "Filters", "Run_Log"], (
            f"unexpected sheets: {workbook.sheetnames}")

        sheet = workbook["Tender_Data"]
        headers = [cell.value for cell in sheet[1]]
        print("Tender_Data headers:", headers)
        print("Tender_Data rows:", sheet.max_row - 1)
        assert sheet.max_row - 1 == 4, "one row per tender"
        assert headers[:9] == ["Sr", "Tender No", "Tender Title", "Status",
                               "Work Area", "Due Date/Time", "Due Date", "Due Days",
                               "Dept/Rly Unit"], f"unexpected headers: {headers}"
        assert "Tender ID" in headers

        row = [cell.value for cell in sheet[2]]
        assert row[1] == "61265953A"
        assert row[2] == "Tecspak pad of Side Bearer"
        assert isinstance(row[6], datetime), "the due date must be written as a date"
        assert row[6] == datetime(2026, 10, 1, 11, 0)
        tender_id_column = headers.index("Tender ID")
        assert row[tender_id_column] == "ay+YPtpiUUECwgIvUE41/w=="

        details_sheet = workbook["Tender_Details"]
        print("Tender_Details rows:", details_sheet.max_row - 1)
        assert details_sheet.max_row - 1 == 4

    print("\nTENDER FLOW TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
