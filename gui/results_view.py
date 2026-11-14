"""The results grid - a ttk.Treeview that mirrors the portal's columns."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

TEXT = "#20303a"

#: (heading, column id, width)
PO_COLUMNS = [
    ("Sr", "sr", 50),
    ("Supplier Name", "supplier", 200),
    ("PO Value", "value", 110),
    ("Item Description", "description", 380),
    ("PO Sl", "sl", 60),
    ("Consignee", "consignee", 170),
    ("PO Qty/Unit", "qty", 90),
    ("T.U.R.", "tur", 70),
    ("Delivery Date", "delivery", 110),
]

#: The tender grid, in the order the portal renders it.
TENDER_COLUMNS = [
    ("Sr", "sr", 45),
    ("Dept/Rly Unit", "dept", 190),
    ("Tender No", "number", 110),
    ("Tender Title", "title", 420),
    ("Status", "status", 150),
    ("Work Area", "workarea", 130),
    ("Due Date/Time", "due", 120),
    ("Due Days", "duedays", 90),
]

#: Which record field each column shows, per mode.
PO_FIELDS = [
    "Sr", "Supplier Name", "PO Value (text)", "Item Description", "PO Sl",
    "Consignee", "PO Qty/Unit", "T.U.R.", "Dely.Dt",
]

TENDER_FIELDS = [
    "Sr", "Dept/Rly Unit", "Tender No", "Tender Title", "Status",
    "Work Area", "Due Date/Time", "Due Days",
]

COLUMN_SETS = {"po": (PO_COLUMNS, PO_FIELDS), "tenders": (TENDER_COLUMNS, TENDER_FIELDS)}


class ResultsView(ttk.Frame):
    """Shows the scraped rows and keeps the mapping back to the record dict."""

    def __init__(self, parent: tk.Widget, mode: str = "po"):
        super().__init__(parent)
        self.records: list[dict] = []
        self._sort_column = None
        self._sort_reverse = False
        self.mode = mode
        columns, _ = COLUMN_SETS.get(mode, COLUMN_SETS["po"])

        self.tree = ttk.Treeview(
            self, columns=[c[1] for c in columns], show="headings", selectmode="browse"
        )
        for heading, column, width in columns:
            self.tree.heading(
                column, text=heading,
                command=lambda c=column: self._sort_by(c),
            )
            self.tree.column(column, width=width, minwidth=40, anchor="w", stretch=True)
        self.tree.tag_configure("odd", background="#F7F9FA")

        vertical = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    # -- data --------------------------------------------------------------
    def clear(self) -> None:
        self.records.clear()
        self.tree.delete(*self.tree.get_children())

    def set_mode(self, mode: str) -> None:
        """Switch the grid between the PO columns and the tender columns."""
        if mode == self.mode:
            return
        self.mode = mode
        columns, _ = COLUMN_SETS.get(mode, COLUMN_SETS["po"])
        self.tree.configure(columns=[c[1] for c in columns])
        for heading, column, width in columns:
            self.tree.heading(column, text=heading,
                              command=lambda c=column: self._sort_by(c))
            self.tree.column(column, width=width, minwidth=40, anchor="w", stretch=True)
        self.clear()

    def add_records(self, records: list[dict]) -> None:
        """Append rows, keeping the index into ``self.records`` in the row id."""
        _, fields = COLUMN_SETS.get(self.mode, COLUMN_SETS["po"])
        for record in records:
            index = len(self.records)
            self.records.append(record)
            self.tree.insert(
                "", "end", iid=str(index),
                values=tuple(record.get(name, "") for name in fields),
                tags=("odd",) if index % 2 else (),
            )

    def replace_records(self, records: list[dict]) -> None:
        self.clear()
        self.add_records(records)

    def selected_record(self) -> dict | None:
        selection = self.tree.selection()
        if not selection:
            return None
        try:
            return self.records[int(selection[0])]
        except (ValueError, IndexError):
            return None

    def selected_index(self) -> int | None:
        selection = self.tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except ValueError:
            return None

    # -- sorting -----------------------------------------------------------
    def _sort_by(self, column: str) -> None:
        if self._sort_column == column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = False

        columns, fields = COLUMN_SETS.get(self.mode, COLUMN_SETS["po"])
        order = {c[1]: name for c, name in zip(columns, fields)}
        key_name = order.get(column, column)
        self.records.sort(
            key=lambda r: (str(r.get(key_name, "") or "").lower()),
            reverse=self._sort_reverse,
        )
        selected = self.selected_index()
        self.clear()
        self.add_records(self.records)
        if selected is not None and 0 <= selected < len(self.records):
            self.tree.selection_set(str(selected))
