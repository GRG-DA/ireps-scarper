"""Excel output.

One workbook per run with seven sheets. The formatting is deliberate: frozen
headers, filters, real dates and numbers (never text), wrapped long
descriptions, and a per-run audit trail so any file can be traced back to the
exact search that produced it.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from core.config import LogEntry, SearchCriteria

NAVY = "0F2A3D"
TEAL = "0E7C86"
LIGHT = "EAF1F5"
GREY = "F4F6F7"

HEADER_FONT = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
BODY_FONT = Font(name="Segoe UI", size=10)
TITLE_FONT = Font(name="Segoe UI", size=14, bold=True, color=NAVY)
LABEL_FONT = Font(name="Segoe UI", size=10, bold=True)
MONO_FONT = Font(name="Consolas", size=9)

THIN = Side(style="thin", color="C9D4DB")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
TOP = Alignment(vertical="top")

#: (column name, kind, width) - kind drives the number format.
PO_DATA_COLUMNS = [
    ("Sr", "int", 6),
    ("Supplier Name", "text", 28),
    ("PO Value (text)", "text", 16),
    ("PO Value", "currency", 16),
    ("Item Description", "text", 46),
    ("PO Sl", "text", 10),
    ("Consignee", "text", 26),
    ("PO Qty/Unit", "text", 14),
    ("T.U.R.", "text", 12),
    ("Delivery Date", "date", 14),
    ("PO Date", "date", 13),
    ("Item Code / PLNO", "text", 16),
    ("Supplier GSTIN", "text", 18),
    ("Supplier Address", "text", 34),
    ("Unit Rate", "currency", 14),
    ("Order / Contract No", "text", 20),
    ("Contact Person / Email", "text", 26),
    ("Zone / Rly Unit", "text", 24),
    ("PO Reference", "text", 18),
    ("Source URL", "link", 40),
    ("Detail Labels", "text", 40),
    ("Detail_Extra", "text", 40),
    ("Detail Fetched", "text", 12),
    ("Scraped At", "datetime", 18),
    ("Batch ID", "text", 20),
]

DETAIL_COLUMNS = [
    ("PO Reference", 20),
    ("PO Sl", 10),
    ("Supplier Name", 28),
    ("PO Date", 13),
    ("Item Code / PLNO", 16),
    ("Supplier GSTIN", 18),
    ("Supplier Address", 34),
    ("Unit Rate", 14),
    ("Order / Contract No", 20),
    ("Contact Person / Email", 26),
    ("Consignee", 26),
    ("PO Qty/Unit", 14),
    ("Item Description", 46),
    ("Delivery Date", 14),
    ("T.U.R.", 12),
    ("Source URL", 44),
]

#: The tender grid, in the order the portal renders it, plus the fields the
#: detail page adds.
TENDER_DATA_COLUMNS = [
    ("Sr", "int", 6),
    ("Tender No", "text", 16),
    ("Tender Title", "text", 62),
    ("Status", "text", 24),
    ("Work Area", "text", 18),
    ("Due Date/Time", "text", 18),
    ("Due Date", "date", 14),
    ("Due Days", "text", 12),
    ("Dept/Rly Unit", "text", 28),
    ("Tender Type", "text", 16),
    ("Tender Status", "text", 20),
    ("Tender ID", "text", 26),
    ("Source URL", "link", 44),
    ("Detail Labels", "text", 40),
    ("Detail_Extra", "text", 40),
    ("Detail Fetched", "text", 12),
    ("Scraped At", "datetime", 18),
    ("Batch ID", "text", 20),
]

TENDER_DETAIL_COLUMNS = [
    ("Tender No", 16),
    ("Tender Title", 62),
    ("Status", 24),
    ("Work Area", 18),
    ("Due Date/Time", 18),
    ("Due Days", 12),
    ("Dept/Rly Unit", 28),
    ("Tender Type", 16),
    ("Tender Status", 20),
    ("Tender ID", 26),
    ("Source URL", 44),
]

DATE_FORMAT = "dd-mmm-yyyy"
DATETIME_FORMAT = "dd-mmm-yyyy hh:mm"
CURRENCY_FORMAT = '#,##0.00'


def _style_header(sheet, row: int, headers: list[str], fill: str = TEAL) -> None:
    for index, name in enumerate(headers, start=1):
        cell = sheet.cell(row=row, column=index, value=name)
        cell.font = HEADER_FONT
        cell.fill = PatternFill("solid", fgColor=fill)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
    sheet.row_dimensions[row].height = 30


def _apply_widths(sheet, widths: list[int]) -> None:
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width


def _write_readme(sheet, result, criteria: SearchCriteria | None, path: Path) -> None:
    sheet.column_dimensions["A"].width = 26
    sheet.column_dimensions["B"].width = 108
    is_tender = bool(criteria and criteria.mode == "tenders")
    sheet["A1"] = "IREPS Tender export" if is_tender else "IREPS Purchase Order export"
    sheet["A1"].font = TITLE_FONT
    sheet["A2"] = f"Generated {datetime.now():%d-%b-%Y %H:%M:%S}   |   File: {path.name}"
    sheet["A2"].font = MONO_FONT

    if is_tender:
        rows = [
            ("Source", "https://www.ireps.gov.in/epsn/anonymSearch.do"),
            ("What this file contains", "Every tender returned by the search, merged with the "
             "fields captured from each tender's own detail page."),
            ("Records", str(len(result.records))),
            ("Portal record count", str(result.total_count) if result.total_count else "not reported"),
            ("Pages fetched", str(result.pages_fetched)),
            ("Detail pages", f"fetched {result.details_fetched}, from cache {result.details_cached}, failed {result.details_failed}"),
            ("Run time", f"{result.elapsed:.1f} seconds"),
            ("Status", "cancelled by the user" if result.cancelled else "completed"),
            ("Tender_Data", "The main dataset - one row per tender."),
            ("Tender_Details", "The fields captured from each tender's detail page."),
            ("Summary", "Counts by status, work area, department and closing month."),
            ("Filters", "The exact search criteria used, so this file can be reproduced."),
            ("Run_Log", "Per-page status, rows, HTTP status and errors."),
            ("Raw_Response", "Raw HTML kept for debugging. Off by default."),
            ("Note", "The portal's own tender documents are listed by name but never "
             "downloaded - only the public notice text is collected."),
        ]
    else:
        rows = [
            ("Source", "https://www.ireps.gov.in/epsn/anonymSearchPO.do"),
            ("What this file contains", "Every Purchase Order / Supply Contract line returned by the search, "
             "merged with the detail page fields where they could be fetched."),
            ("Records", str(len(result.records))),
            ("Portal record count", str(result.total_count) if result.total_count else "not reported"),
            ("Pages fetched", str(result.pages_fetched)),
            ("Detail pages", f"fetched {result.details_fetched}, from cache {result.details_cached}, failed {result.details_failed}"),
            ("Run time", f"{result.elapsed:.1f} seconds"),
            ("Status", "cancelled by the user" if result.cancelled else "completed"),
            ("PO_Data", "The main dataset - one row per line item."),
            ("Details", "Every label/value pair captured from each detail page, including labels that are not mapped to a column."),
            ("Summary", "Counts and values by zone, supplier, consignee and month."),
            ("Filters", "The exact search criteria used, so this file can be reproduced."),
            ("Run_Log", "Per-page status, rows, HTTP status and errors."),
            ("Raw_Response", "Raw HTML kept for debugging. Off by default."),
            ("Refresh", "Re-run the app with the same criteria in the Filters sheet."),
            ("Note", "PO Value is shown twice: the raw portal text and a parsed numeric INR amount. "
             "Blank numeric cells mean the portal printed a value this exporter could not parse - the text is still there."),
        ]
    if criteria:
        rows.insert(6, ("Search criteria", "; ".join(f"{k}={v}" for k, v in criteria.describe() if v)))

    for index, (label, value) in enumerate(rows, start=4):
        label_cell = sheet.cell(row=index, column=1, value=label)
        label_cell.font = LABEL_FONT
        label_cell.fill = PatternFill("solid", fgColor=LIGHT)
        label_cell.alignment = TOP
        value_cell = sheet.cell(row=index, column=2, value=value)
        value_cell.font = BODY_FONT
        value_cell.alignment = Alignment(wrap_text=True, vertical="top")
        sheet.row_dimensions[index].height = 30
    sheet.sheet_view.showGridLines = False


def _write_data(sheet, records: list[dict], columns, batch_id: str, scraped_at: str) -> None:
    headers = [name for name, _, _ in columns]
    _style_header(sheet, 1, headers)
    _apply_widths(sheet, [width for _, _, width in columns])

    for row_index, record in enumerate(records, start=2):
        for column_index, (name, kind, _) in enumerate(columns, start=1):
            value = record.get(name)
            if name == "Scraped At":
                value = scraped_at
            elif name == "Batch ID":
                value = batch_id
            cell = sheet.cell(row=row_index, column=column_index, value=value)
            cell.font = BODY_FONT
            cell.alignment = WRAP
            cell.border = BORDER
            if row_index % 2 == 1:
                cell.fill = PatternFill("solid", fgColor=GREY)
            if kind == "date" and isinstance(value, datetime):
                cell.number_format = DATE_FORMAT
            elif kind == "datetime" and isinstance(value, datetime):
                cell.number_format = DATETIME_FORMAT
            elif kind == "currency" and isinstance(value, (int, float)):
                cell.number_format = CURRENCY_FORMAT
            elif kind == "link" and isinstance(value, str) and value.startswith("http"):
                cell.hyperlink = value
                cell.font = Font(name="Segoe UI", size=10, color="0563C1", underline="single")

    last_row = max(1, len(records) + 1)
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{last_row}"
    sheet.freeze_panes = "A2"


def _write_po_data(sheet, records: list[dict], batch_id: str, scraped_at: str) -> None:
    _write_data(sheet, records, PO_DATA_COLUMNS, batch_id, scraped_at)


def _write_details(sheet, records: list[dict], columns=None) -> None:
    columns = columns or DETAIL_COLUMNS
    headers = [name for name, _ in columns]
    _style_header(sheet, 1, headers)
    _apply_widths(sheet, [width for _, width in columns])

    for row_index, record in enumerate(records, start=2):
        for column_index, (name, _) in enumerate(columns, start=1):
            cell = sheet.cell(row=row_index, column=column_index, value=record.get(name))
            cell.font = BODY_FONT
            cell.alignment = WRAP
            cell.border = BORDER
            if row_index % 2 == 1:
                cell.fill = PatternFill("solid", fgColor=GREY)
            if name in ("PO Date", "Delivery Date", "Due Date") and isinstance(cell.value, datetime):
                cell.number_format = DATE_FORMAT
            if name == "Unit Rate" and isinstance(cell.value, (int, float)):
                cell.number_format = CURRENCY_FORMAT
            if name == "Source URL" and isinstance(cell.value, str) and cell.value.startswith("http"):
                cell.hyperlink = cell.value
                cell.font = Font(name="Segoe UI", size=10, color="0563C1", underline="single")

    last_row = max(1, len(records) + 1)
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{last_row}"
    sheet.freeze_panes = "A2"


def _write_summary(sheet, records: list[dict]) -> None:
    sheet.column_dimensions["A"].width = 34
    sheet.column_dimensions["B"].width = 20
    sheet.column_dimensions["C"].width = 20
    sheet["A1"] = "Summary"
    sheet["A1"].font = TITLE_FONT

    total_value = sum(r.get("PO Value") or 0 for r in records)
    sheet["A3"] = "Metric"
    sheet["B3"] = "Value"
    _style_header(sheet, 3, ["Metric", "Value"])

    metrics = [
        ("Total line items", len(records)),
        ("Total PO value (INR)", round(total_value, 2)),
        ("Distinct suppliers", len({r.get("Supplier Name", "") for r in records if r.get("Supplier Name")})),
        ("Distinct consignees", len({r.get("Consignee", "") for r in records if r.get("Consignee")})),
        ("Records with a parsed value", sum(1 for r in records if r.get("PO Value"))),
        ("Average PO value (INR)", round(total_value / len(records), 2) if records else 0),
    ]
    for index, (label, value) in enumerate(metrics, start=4):
        sheet.cell(row=index, column=1, value=label).font = LABEL_FONT
        cell = sheet.cell(row=index, column=2, value=value)
        cell.font = BODY_FONT
        if "value" in label.lower():
            cell.number_format = CURRENCY_FORMAT

    def block(start_row: int, title: str, key: str) -> int:
        sheet.cell(row=start_row, column=1, value=title).font = LABEL_FONT
        _style_header(sheet, start_row + 1, [title, "Count", "PO Value (INR)"])
        buckets: dict[str, list] = {}
        for record in records:
            name = (record.get(key) or "").strip()
            if not name:
                continue
            bucket = buckets.setdefault(name, [0, 0.0])
            bucket[0] += 1
            bucket[1] += record.get("PO Value") or 0.0
        ordered = sorted(buckets.items(), key=lambda kv: kv[1][1], reverse=True)
        row = start_row + 2
        for name, (count, value) in ordered:
            sheet.cell(row=row, column=1, value=name).font = BODY_FONT
            sheet.cell(row=row, column=2, value=count).font = BODY_FONT
            cell = sheet.cell(row=row, column=3, value=round(value, 2))
            cell.font = BODY_FONT
            cell.number_format = CURRENCY_FORMAT
            row += 1
        return row

    row = 4 + len(metrics) + 1
    row = block(row, "By Supplier", "Supplier Name")
    row += 1
    block(row, "By Consignee", "Consignee")
    sheet.sheet_view.showGridLines = False


def _write_tender_summary(sheet, records: list[dict]) -> None:
    """Counts for the tender dataset - the tender grid carries no money."""
    sheet.column_dimensions["A"].width = 34
    sheet.column_dimensions["B"].width = 20
    sheet["A1"] = "Summary"
    sheet["A1"].font = TITLE_FONT

    sheet["A3"] = "Metric"
    sheet["B3"] = "Value"
    _style_header(sheet, 3, ["Metric", "Value"])

    metrics = [
        ("Tenders", len(records)),
        ("Distinct tender numbers", len({r.get("Tender No", "") for r in records if r.get("Tender No")})),
        ("Distinct departments", len({r.get("Dept/Rly Unit", "") for r in records if r.get("Dept/Rly Unit")})),
        ("With a closing date", sum(1 for r in records if r.get("Due Date"))),
        ("With a detail page fetched", sum(1 for r in records if r.get("Detail Fetched"))),
    ]
    for index, (label, value) in enumerate(metrics, start=4):
        sheet.cell(row=index, column=1, value=label).font = LABEL_FONT
        sheet.cell(row=index, column=2, value=value).font = BODY_FONT

    def block(start_row: int, title: str, key: str) -> int:
        sheet.cell(row=start_row, column=1, value=title).font = LABEL_FONT
        _style_header(sheet, start_row + 1, [title, "Tenders"])
        buckets: dict[str, int] = {}
        for record in records:
            name = (record.get(key) or "").strip()
            if not name:
                continue
            buckets[name] = buckets.get(name, 0) + 1
        row = start_row + 2
        for name, count in sorted(buckets.items(), key=lambda kv: (-kv[1], kv[0])):
            sheet.cell(row=row, column=1, value=name).font = BODY_FONT
            sheet.cell(row=row, column=2, value=count).font = BODY_FONT
            row += 1
        return row

    def month_block(start_row: int) -> int:
        sheet.cell(row=start_row, column=1, value="By closing month").font = LABEL_FONT
        _style_header(sheet, start_row + 1, ["Closing month", "Tenders"])
        buckets: dict[str, int] = {}
        for record in records:
            value = record.get("Due Date")
            if not isinstance(value, datetime):
                continue
            key = value.strftime("%b-%Y")
            buckets[key] = buckets.get(key, 0) + 1
        row = start_row + 2
        for name, count in sorted(buckets.items(), key=lambda kv: kv[0]):
            sheet.cell(row=row, column=1, value=name).font = BODY_FONT
            sheet.cell(row=row, column=2, value=count).font = BODY_FONT
            row += 1
        return row

    row = 4 + len(metrics) + 1
    row = block(row, "By status", "Status")
    row += 1
    row = block(row, "By work area", "Work Area")
    row += 1
    row = block(row, "By department", "Dept/Rly Unit")
    row += 1
    month_block(row)
    sheet.sheet_view.showGridLines = False


def _write_filters(sheet, criteria: SearchCriteria | None, result, batch_id: str) -> None:
    sheet.column_dimensions["A"].width = 30
    sheet.column_dimensions["B"].width = 100
    sheet["A1"] = "Search criteria used for this file"
    sheet["A1"].font = TITLE_FONT
    _style_header(sheet, 3, ["Setting", "Value"])

    pairs: list[tuple[str, str]] = []
    if criteria:
        pairs = [(k, str(v)) for k, v in criteria.describe()]
    pairs += [
        ("Batch ID", batch_id),
        ("Run started", datetime.fromtimestamp(result.started_at).strftime("%d-%b-%Y %H:%M:%S") if result.started_at else ""),
        ("Run finished", datetime.fromtimestamp(result.finished_at).strftime("%d-%b-%Y %H:%M:%S") if result.finished_at else ""),
        ("Pages fetched", str(result.pages_fetched)),
        ("Portal record count", str(result.total_count) if result.total_count else "not reported"),
        ("Rows written", str(len(result.records))),
    ]
    for index, (label, value) in enumerate(pairs, start=4):
        label_cell = sheet.cell(row=index, column=1, value=label)
        label_cell.font = LABEL_FONT
        label_cell.fill = PatternFill("solid", fgColor=LIGHT)
        label_cell.alignment = TOP
        value_cell = sheet.cell(row=index, column=2, value=value)
        value_cell.font = MONO_FONT
        value_cell.alignment = TOP
    sheet.sheet_view.showGridLines = False


def _write_run_log(sheet, entries: list[LogEntry]) -> None:
    headers = ["Scope", "Item", "Status", "Rows", "HTTP", "Seconds", "Detail"]
    _style_header(sheet, 1, headers)
    _apply_widths(sheet, [12, 46, 12, 8, 8, 10, 70])
    for row_index, entry in enumerate(entries, start=2):
        values = [entry.scope, entry.item, entry.status, entry.rows, entry.http_status,
                  round(entry.seconds, 2), entry.detail]
        for column_index, value in enumerate(values, start=1):
            cell = sheet.cell(row=row_index, column=column_index, value=value)
            cell.font = BODY_FONT
            cell.alignment = WRAP
            cell.border = BORDER
            if row_index % 2 == 1:
                cell.fill = PatternFill("solid", fgColor=GREY)
    sheet.freeze_panes = "A2"


def _write_raw(sheet, html: str) -> None:
    sheet.column_dimensions["A"].width = 120
    sheet["A1"] = html[:1_000_000]
    sheet["A1"].font = MONO_FONT
    sheet["A1"].alignment = Alignment(wrap_text=True, vertical="top")


def export(
    records: list[dict],
    result,
    criteria: SearchCriteria | None,
    output_dir: Path,
    raw_html: str | None = None,
    timestamp: str | None = None,
) -> Path:
    """Write the workbook and return its path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    is_tender = bool(criteria and criteria.mode == "tenders")
    zone = (criteria.zone_label if criteria else "") or (criteria.railway_zone if criteria else "") or "all"
    zone = "".join(ch if ch.isalnum() else "_" for ch in str(zone)).strip("_")[:28] or "all"
    date_from = (criteria.date_from if criteria else "").replace("/", "")
    date_to = (criteria.date_to if criteria else "").replace("/", "")
    prefix = "IREPS_TENDER" if is_tender else "IREPS_PO"
    filename = f"{prefix}_{zone}_{date_from}_{date_to}_{stamp}.xlsx"
    path = output_dir / filename

    batch_id = f"RUN-{stamp}"
    scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    workbook = Workbook()
    readme = workbook.active
    readme.title = "README"
    _write_readme(readme, result, criteria, path)

    if is_tender:
        data_sheet = workbook.create_sheet("Tender_Data")
        _write_data(data_sheet, records, TENDER_DATA_COLUMNS, batch_id, scraped_at)

        details_sheet = workbook.create_sheet("Tender_Details")
        _write_details(details_sheet, records, TENDER_DETAIL_COLUMNS)

        summary_sheet = workbook.create_sheet("Summary")
        _write_tender_summary(summary_sheet, records)
    else:
        po_sheet = workbook.create_sheet("PO_Data")
        _write_po_data(po_sheet, records, batch_id, scraped_at)

        details_sheet = workbook.create_sheet("Details")
        _write_details(details_sheet, records)

        summary_sheet = workbook.create_sheet("Summary")
        _write_summary(summary_sheet, records)

    filters_sheet = workbook.create_sheet("Filters")
    _write_filters(filters_sheet, criteria, result, batch_id)

    log_sheet = workbook.create_sheet("Run_Log")
    _write_run_log(log_sheet, result.log)

    if raw_html:
        raw_sheet = workbook.create_sheet("Raw_Response")
        _write_raw(raw_sheet, raw_html)

    for sheet in workbook.worksheets:
        sheet.sheet_view.showGridLines = False
        sheet.sheet_properties.tabColor = NAVY
    workbook.active = 0
    workbook.save(path)
    return path
