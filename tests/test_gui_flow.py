"""End-to-end test of the GUI against a fake IREPS server.

Serves a synthetic search page and results table, drives the real widgets, and
checks that rows land in the grid and the Excel file gets written.

    python tests/test_gui_flow.py
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tkinter as tk  # noqa: E402

from core.client import IrepsClient  # noqa: E402
from core.config import Settings  # noqa: E402

SEARCH_PAGE = """
<html><head><title>Search Purchase Order</title></head><body>
<form name="poSearchForm" method="post" action="/epsn/anonymSearchPO.do">
  <input type="text" name="plNumber" size="20" value="" id="plNumber">
  <input type="text" name="poValueFrom" size="12" value="5" id="poValueFrom">
  <input type="text" name="poValueTo" size="12" value="99999" id="poValueTo">
  <input type="text" name="dateFrom" size="12" value="12/10/2026" readonly="readonly" id="ddmmyyDateformat1">
  <input type="text" name="dateTo" size="12" value="11/11/2026" readonly="readonly" id="ddmmyyDateformat2">
  <input type="hidden" id="firmAccountId" name="firmAccountId" value="%"/>
  <input type="hidden" name="searchParam" id="searchParam">
  <select name="searchOption"><option value="-1">All</option>
    <option value="8937">East Central Railway</option><option value="561">Central Railway</option></select>
  <input type="submit" name="submit" tabindex="7" value="Show Results" onclick="return dateRange();">
</form>
</body></html>
"""

RESULTS_PAGE = """
<html><body>
<td class="formLabel"><b>&nbsp;Tender search results &nbsp;</b><B>3</B></td>
<table border="1" bordercolor="#4D817A" cellspacing="0" width="100%" align="center">
<tr height="20" align="center" style="background-color: #D9D9D9">
  <td width="5%" class="formLabel">Sr.&nbsp;</td>
  <td width="20%" class="formLabel">Supplier Name&nbsp;</td>
  <td width="5%" class="formLabel">PO Value&nbsp;</td>
  <td width="25%" class="formLabel">Item Description&nbsp;</td>
  <td width="5%" class="formLabel">PO Sl&nbsp;</td>
  <td width="10%" class="formLabel">Consignee&nbsp;</td>
  <td width="8%" class="formLabel">PO Qty/Unit&nbsp;</td>
  <td width="7%" class="formLabel">T.U.R.&nbsp;</td>
  <td width="8%" class="formLabel">Dely.Dt&nbsp;</td>
</tr>
<tr><td>1</td><td>NER/22261096104124 dt. 05-NOV-2026 on M/s. SUJAN INDUSTRIES-PALGHAR</td>
    <td>4257038.8</td><td>33500058 : Rubber Pad for longitudinal bump stop for FIAT bogies</td>
    <td>001</td><td>IZN</td><td>116 Nos.</td><td>430.70</td><td>05-FEB-2027</td></tr>
<tr><td>2</td><td>ICF/03261803102023 dt. 05-NOV-2026 on M/s. MG WORLDWIDE PVT. LTD.-NEW DELHI</td>
    <td>13932024</td><td>31058048 : Primary Vertical Damper for VB Trainset</td>
    <td>001</td><td>LHB</td><td>316 Nos.</td><td>13452.00</td><td>31-MAR-2027</td></tr>
<tr><td>3</td><td>CR/38260294105922 dt. 09-NOV-2026 on M/s. ACME INDUSTRIES</td>
    <td>1796219.6</td><td>38160444 : POH Kit for D.V.</td>
    <td>001</td><td>BD</td><td>136 Set</td><td>3091.60</td><td>09-FEB-2027</td></tr>
</table>
</body></html>
"""

DETAIL_PAGE = """
<html><body><table border="1">
<tr><td>PO No</td><td>20261076</td></tr>
<tr><td>PO Date</td><td>01/09/2026</td></tr>
<tr><td>Supplier GSTIN</td><td>29ABCDE1234F1Z5</td></tr>
<tr><td>Supplier Address</td><td>12 MG Road, Bengaluru 560001</td></tr>
<tr><td>Item Code</td><td>PLN-7781</td></tr>
<tr><td>Order No</td><td>GEM/2026/4471</td></tr>
<tr><td>Contact</td><td>ravi@acme.in</td></tr>
<tr><td>Notes</td><td>Urgent requirement</td></tr>
</table></body></html>
"""

REQUESTS: list[str] = []


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.url = "https://www.ireps.gov.in/epsn/anonymSearchPO.do"


def install_fake_client(client: IrepsClient) -> None:
    """Point the client at the synthetic pages."""

    def fake_get(url, **kwargs):
        REQUESTS.append(f"GET {url}")
        if "poDetail" in url:
            return FakeResponse(DETAIL_PAGE)
        if "pageNo" in url:
            return FakeResponse(RESULTS_PAGE)
        return FakeResponse(SEARCH_PAGE)

    def fake_post(url, **kwargs):
        REQUESTS.append(f"POST {url}")
        return FakeResponse(RESULTS_PAGE)

    client.get = fake_get          # type: ignore[method-assign]
    client.post = fake_post        # type: ignore[method-assign]


def main() -> int:
    from gui.app import IrepsApp

    root = tk.Tk()
    root.withdraw()
    app = IrepsApp(root)
    install_fake_client(app.client)
    app.auth.is_authenticated = lambda: True  # type: ignore[method-assign]

    # this test exercises the purchase order search
    app.mode.set("po")
    app._apply_mode()

    # the dropdowns come from the fake page
    root.update()
    app._handle_options({
        "organisation": [
            type("O", (), {"label": "East Central Railway", "value": "8937"})(),
            type("O", (), {"label": "Central Railway", "value": "561"})(),
        ],
    })
    print("organisation options loaded:", app.combos["organisation"]["values"])

    app.combos["organisation"].set("East Central Railway")
    criteria = app._criteria()
    print("criteria value sent to the portal:", criteria.railway_zone)
    print("criteria label shown in Filters:    ", criteria.zone_label)
    assert criteria.railway_zone == "8937", "the numeric id must be sent, not the label"

    app._show_results()
    deadline = time.time() + 20
    while app.worker and app.worker.is_alive() and time.time() < deadline:
        root.update()
        time.sleep(0.05)
    root.update()

    rows = app.results.tree.get_children()
    print(f"\nrows in the grid: {len(rows)}")
    for row in rows:
        values = app.results.tree.item(row, "values")
        print("   ", " | ".join(str(v) for v in values[:5]))
    assert len(rows) == 3, f"expected 3 rows, got {len(rows)}"

    record = app.results.records[0]
    print("\nparsed record 1:")
    for key in ("Supplier Name", "PO Value (text)", "PO Value", "Item Description",
                "Consignee", "Delivery Date", "PO Reference", "PO Date",
                "Item Code / PLNO"):
        print(f"   {key:20s} = {record.get(key)}")
    assert record["PO Value"] == 4257038.8, "PO Value should parse to 4257038.8"
    assert record["Delivery Date"] is not None, "Delivery Date should be a datetime"
    assert record["PO Reference"] == "NER/22261096104124", "PO reference should be split out"
    assert record["PO Date"] is not None, "PO date should be split out"
    assert record["Item Code / PLNO"] == "33500058", "item code should be split out"
    assert record["Supplier Name"].startswith("M/s. SUJAN"), "supplier should be cleaned"

    # export
    app._export_called = True
    from excel.exporter import export
    path = export(app.results.records, app.last_result, app._criteria(),
                  Path("output"), raw_html=None)
    print(f"\nexported: {path.name} ({path.stat().st_size} bytes)")

    import openpyxl
    workbook = openpyxl.load_workbook(path)
    print("sheets:", workbook.sheetnames)
    print("PO_Data rows:", workbook["PO_Data"].max_row - 1)
    print("Details rows:", workbook["Details"].max_row - 1)

    print("\nrequests the app made:")
    for entry in REQUESTS:
        print("   ", entry)

    root.destroy()
    print("\nGUI FLOW TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
