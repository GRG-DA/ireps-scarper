# IREPS Tender & Purchase Order Scraper

A Python desktop app that mirrors the IREPS search website, scrapes **tender
notices** and **Purchase Order / Supply Contract** records (plus each record's
detail page) and exports everything to a formatted Excel workbook.

| Search | Portal page |
|---|---|
| Tenders | <https://www.ireps.gov.in/epsn/anonymSearch.do> |
| Purchase Orders | <https://www.ireps.gov.in/epsn/anonymSearchPO.do> |

Both searches run on the same core, so the GUI and the command line produce
identical output.

---

## Quick start

```bat
pip install -r requirements.txt
python main.py
```

The GUI opens. Press **Sign in**, type the mobile number, read the
verification code from the image, request the OTP, type the OTP from the SMS,
and the search form becomes usable.

> The captcha is solved **by hand**, on purpose. The app downloads the image
> and shows it; you type what you can see. The hidden `ver` field still
> carries the server-issued value, because the portal's own JavaScript fills
> it that way and the server expects it - but the answer you type is checked
> against the image by a person.

The session is cached in `state/session.pkl`. The OTP stays valid for the
whole day, so you normally sign in once and then just press **Show Results**.

## The GUI

A radio switch at the top of the window picks the search:

| Mode | Left panel | Right panel |
|---|---|---|
| **Tenders** | The portal's "Search Tender" page: six tabs, the Custom Search form, the date range | Results grid, one row per tender |
| **Purchase Orders** | The smaller PO form: organisation/unit, PL number, PO value range, date range | Results grid, one row per PO line item |

- The dropdown options are read from the live page, so they always match the
  portal rather than a stale hardcoded list. The tender form's Railway/PU and
  Unit lists are fetched from the portal's own AJAX endpoints as you change
  the organisation, department or zone.
- Double-click a row to open its detail page as a key/value table.
- **Fetch detail pages** (checkbox) controls whether every record's detail
  page is fetched. It multiplies the request count 10-50x, so the rate
  limiter matters. A PO search has no per-record detail page - the PO rows
  link to nothing - so the checkbox only has an effect on a tender search.
- All scraping runs on a worker thread, so the window never freezes.
  **Cancel** stops the run and keeps whatever was collected.

### The tender form

It mirrors the portal's Custom Search form:

| Field | Notes |
|---|---|
| Search Criteria | Tender Number / Name Of Work / Item Code / Item Description |
| Match | Starting with / Equals / Containing - narrowed by the criterion |
| Search For | The text. At least 3 characters. |
| Organization | Indian Railway, KRCL, DMRC, ... |
| Railway/PU * | Required by the portal |
| Unit | Filled in from the portal once zone and department are chosen |
| Department * | |
| Work Area * | Works / Goods & Services / Earning / Leasing |
| Tender Status | Published, Under Evaluation, Cancelled, ... |
| Tender Type | Limited / Open / Special Limited / Single |
| Bidding System | All / Single Packet / Two Packet |
| Select Date | Tender Closing Date or Tender Uploading Date |
| From / To | dd/mm/yyyy, and **within one year** |

The six portal tabs are rendered as buttons above the form - **Active Tenders
Closing Today**, **All Active Tenders**, **Recently Closed Tenders**,
**Custom Search**, **Live & Upcoming e-RA**, **Closed e-RA**. Only "Custom
Search" shows the form; clicking any other tab runs that quick view instead.

Below the dates are the portal's relative-date radio buttons: **Last 6
months**, **Last 3 months**, **Next 3 months**, **Next 6 months** and
**Custom Date**. Picking one fills the From/To boxes the way the portal's own
shortcut does.

## Running a tender search

**In the GUI**

1. Leave the **Search** switch on **Tenders**.
2. Pick the organisation, the Railway/PU and the date range. The date range
   must be within a year, and with "Tender Uploading Date" the To date cannot
   be in the future - the app checks both before it starts.
3. Optionally type at least three characters into **Search For**.
4. Press **Show Results**. The first page arrives, then the app walks the
   remaining pages on its own until the portal's own total is reached (or
   `--max-pages` is hit).
5. Tick **Fetch detail pages** to pull each tender's notice page as well.
6. Press **Export to Excel**.

**On the command line**

```bat
python main.py --cli --mode tenders --from 01/10/2026 --to 11/11/2026 ^
  --organisation "Indian Railway" --work-area "Works" --details --max-pages 50
```

## The Excel file

One workbook per run in `output/`. The filename starts with `IREPS_TENDER_`
for a tender run and `IREPS_PO_` for a purchase-order run.

A tender workbook has six sheets:

| Sheet | Contents |
|---|---|
| README | What the file is, how it was produced, any warnings |
| Tender_Data | One row per tender, with the detail-page fields merged in |
| Tender_Details | Every label/value pair captured from each tender's detail page |
| Summary | Totals, and counts by status, work area, department and closing month |
| Filters | The exact search criteria, so the run can be reproduced |
| Run_Log | Per-page status, rows, HTTP status and errors |

`Raw_Response` (the raw HTML for debugging) is added when the run keeps it.

A purchase-order workbook has the same shape with different names:

| Sheet | Contents |
|---|---|
| README | What the file is, how it was produced, any warnings |
| PO_Data | One row per line item, with the detail-page fields merged in |
| Details | Every label/value pair captured from each detail page |
| Summary | Totals, and counts/values by supplier, consignee and zone |
| Filters | The exact search criteria, so the run can be reproduced |
| Run_Log | Per-page status, rows, HTTP status and errors |
| Raw_Response | Raw HTML for debugging (only with `--debug`) |

`PO Value` appears twice: the raw text the portal printed, and a parsed
numeric INR amount. A blank numeric cell means the printed value could not
be parsed - the original text is still there.

## Command line

The CLI runs the same core as the GUI, so both produce identical output.

```bat
python main.py --cli --login
python main.py --cli --from 01/10/2026 --to 11/11/2026 --zone "NORTHERN RLY" --details
python main.py --cli --from 01/10/2026 --to 11/11/2026 --out output --max-pages 50
```

`--login` is interactive: it opens the captcha image, asks for the answer and
the OTP, then caches the session. After that, scheduled runs need no input.

Common flags: `--zone`, `--division`, `--unit`, `--criteria`, `--text`,
`--match`, `--po-min`, `--po-max`, `--date-basis`, `--bidding`, `--status`,
`--details`, `--out`, `--max-pages`, `--min-interval`, `--debug`.

### Tender flags

`--mode tenders` switches the CLI to the tender search. The flags below
select what the portal's Custom Search form selects:

| Flag | What it does |
|---|---|
| `--mode` | `tenders` for the tender search, `po` for the purchase-order search |
| `--tender-criteria` | Tender Number / Name Of Work / Item Code / Item Description |
| `--tender-match` | Starting with / Equals / Containing |
| `--text` | The "Search For" text (at least 3 characters) |
| `--organisation` | The organisation - Indian Railway, KRCL, DMRC, ... |
| `--work-area` | Works / Goods & Services / Earning / Leasing |
| `--department` | The department (the portal's "Department" dropdown) |
| `--unit` | The unit |
| `--zone` | The Railway/PU |
| `--tender-status` | Published / Tender Box Open / Under Evaluation / ... |
| `--tender-type` | Limited / Open / Special Limited / Single |
| `--tender-bidding` | All / Single Packet / Two Packet |
| `--tab` | Runs one of the six quick views instead of a custom search |
| `--from` / `--to` | The date range, dd/mm/yyyy, within one year |
| `--details` | Also fetch every tender's detail page |
| `--max-pages` | How many pages of results to walk |

The dropdown flags take the labels the portal itself shows. The underlying
values are the ones in `core/config.py` - for example the organisation
`Indian Railway` is `01`, and the work areas are `WT` (Works), `PT` (Goods &
Services) and `LT` (Earning / Leasing).

## Daily scheduled run

`run_daily.cmd` is ready for Windows Task Scheduler. The CLI never prompts,
so it will not hang: if the cached session has expired it prints a message and
exits instead of waiting.

```
run_daily.cmd 01/10/2026 11/11/2026 "NORTHERN RLY"
run_daily.cmd 01/10/2026 11/11/2026 "NORTHERN RLY" tenders
```

The fourth argument picks the search - `po` (the default) or `tenders`.

## Project layout

```
ireps_scraper/
  main.py            entry point (GUI by default, --cli for headless)
  cli.py             command line front-end (PO and tender modes)
  core/              the engine - no GUI or Excel imports in here
    config.py        URLs, paths, option vocabularies, SearchCriteria
                     (one criteria object carries both search forms)
    client.py        HTTP session + shared rate limiter
    auth.py          guest login: captcha image, typed answer, OTP, session cache
    discovery.py     reads the search page so field names are never guessed;
                     also the tender page's AJAX dropdown lists
    parser.py        results table -> flat records (PO grid and tender grid)
    detail.py        detail page -> label/value pairs
    normalize.py     dates, amounts ("Rs. 1.25 Lakh" -> 125000.0)
    engine.py        orchestrates search, pagination and details
  excel/exporter.py  the formatted workbook (PO sheets and tender sheets)
  gui/               Tkinter front-end
    app.py           the window: mode switch, both search forms, the six tabs
    results_view.py  the results grid - a column set per mode
  state/             session.pkl, the detail-page cache
  output/            the .xlsx files
  logs/              run logs
```

## Notes on the portal

Everything below was established by probing the live site on 11 Nov 2026, not
from documentation.

### The purchase order page

- `anonymSearchPO.do` does **not** return a search form. It returns the guest
  login page (mobile + captcha + OTP). The login has to come first.
- The login captcha answer is handed to the client in cleartext, but the app
  still asks a human to type it - that was an explicit decision.
- The OTP step submits the **whole form**, not just the OTP: the Struts TOKEN,
  `actionMode=srchPO` and `imageField=Proceed` have to travel with it. Sending
  only the five login fields is rejected with "That OTP was not accepted".
- The portal limits how many OTPs may be **sent** - two per hour per mobile
  number - but an OTP that was already sent stays valid for the day and works
  in a fresh session. One OTP per hour-band is enough.
- The PO search page carries **no captcha**. The portal's own
  `validateCaptcha()` call is commented out.
- The PO form is `poSearchForm` posting to `/epsn/anonymSearchPO.do` with
  `plNumber`, `poValueFrom`, `poValueTo`, `dateFrom`, `dateTo`,
  `firmAccountId`, `railwayZone`, `searchParam` and `submit`.
- The organisation dropdown is named `railwayZone` and holds 44 entries
  (`--list-units` prints them).
- The PO date range cannot exceed two years (735 days).
- **There is no pagination and no Excel/CSV download** - the whole result set
  comes back in one HTML page, and the rows carry no per-record detail link.
  The list is the complete dataset.
- **Large results are silently truncated** by the portal at roughly 2 MB of
  HTML (a 10-day window reported 5,056 records and rendered 1,106). The app
  compares the portal's reported count with the rows it received and, when
  they differ, **halves the date window and searches each half** until
  everything fits. Verified: 5,056 reported, 5,056 collected.
- Two columns hide more than they look: the "Supplier Name" cell actually
  carries the PO reference, the PO date and the supplier, and the "Item
  Description" cell starts with the material code. The parser splits both.

### The tender page

- The page is `anonymSearch.do`, and the form is `advancedSearchForm` posting
  to `/epsn/anonymSearch.do`. Its fields are `searchOption`,
  `searchOptorOption`, `advancedSearch`, `organization`, `workArea`,
  `railwayZone`, `division`, `unit`, `tenderStage`, `tenderType`, `bidding`,
  `selectDate`, `dateFrom`, `dateTo`, `radioDuration`, `direction`,
  `monthDay`, `noMonthDay`, `changezone`, `searchParam` and `activity`.
- **Three traps**, all of which cost a full search to discover:
  1. `searchParam` must be **empty** for a custom search. The portal's
     JavaScript only writes the tab name into that field while the tab button
     is being clicked; a real custom search sends it blank and carries
     `activity=submitCustumSearch` instead. Sending
     `searchParam=custumSearch` silently returns the blank form with no
     results - no error, just nothing.
  2. `activity=submitCustumSearch` **and** `submit=Show Results` both have to
     travel with the request, or the server just re-renders the form.
  3. The "Starting with / Equals / Containing" dropdown is **empty in the
     HTML** - the portal fills it in JavaScript. Numbers (Tender Number, Item
     Code) get "Equals"; text (Name Of Work, Item Description) gets
     "Containing".
- **The organisation dropdown has no "All" entry.** It lists only the
  sixteen organisations the portal knows, and an organisation it does not
  know (`-1`, say) makes it answer with an **empty result set** rather than
  an error - a search that looks like it found nothing. The app therefore
  offers no "All" for the organisation, falls back to Indian Railway when
  none is set, and sends "-1" for a zone, department or unit that is not a
  real id. The same trap applies to the zone dropdown, whose first entry is
  a "---Select---" that carries no id at all.
- The portal validates the form itself: a Railway/PU must be selected, the
  search text needs at least three characters, and **the date range must be
  within one year** (the portal's own check alerts at 366 days, so 365 days is
  the usable limit). With "Tender Uploading Date" the To date cannot be in the
  future. The app mirrors all of these before it sends anything.
- The results grid has eight columns: **Deptt./Rly. Unit, Tender No, Tender
  Title, Status, Work Area, Due Date/Time, Due Days, Actions**. It uses the
  same `bordercolor="#4D817A"` table as the PO grid, so the parser tells the
  two apart by their label row - and the grid is wrapped in several nested
  layout tables, so the table is taken from the label row's own parent.
- **The tender search paginates**, unlike the PO search. The portal reports
  the total ("Tender search results 3750") and renders **25 rows per page**.
  The page links are built by a JavaScript helper, so they live in an
  `onclick` attribute, not an `href`; they carry the search criteria in a
  query string and a `pageNo`. The app posts those same parameters, which is
  what the portal's own JavaScript does.
- The portal is **flaky**: it now and then answers a search with the form
  instead of a result set - no count, no "No Results Found", just nothing -
  and it closes the connection outright when it is pushed. The app asks a
  search that came back empty-and-uncounted up to three times, and retries a
  dropped connection twice before giving up.
- Each row's "View Details" link posts an opaque id (`tenderAnonymsOid`) to
  `/epsn/nitViewAnonyms/rfq/nitPublish.do`. The portal's own JavaScript
  truncates that id at the first "=" (dropping the base64 padding) and the
  server only accepts the truncated form.
- The detail page is a label/value table: Tender No, Dept/Rly, Closing
  Date/Time, Tender Title, Tender Type, Tender Status, the list of attached
  tender documents (names only) and the corrigenda list.

### Being a good citizen

- 3-5 seconds between requests, single threaded (`--min-interval`).
- Public tender notices only. The app lists the attached tender documents by
  name but **never downloads the bid documents themselves**, and there is no
  bulk downloading of bid documents.
- Use your own mobile number; the app does not store the OTP, only the
  resulting session cookies.
