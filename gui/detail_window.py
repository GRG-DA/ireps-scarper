"""The record detail window - a key/value view of one PO or one tender."""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

TEXT = "#20303a"
MUTED = "#6b7c88"

#: The purchase-order fields, in the order they are worth reading.
KNOWN_ORDER = [
    "PO Reference", "PO Date", "Supplier Name", "Supplier GSTIN", "Supplier Address",
    "Consignee", "Item Code / PLNO", "Item Description", "PO Qty/Unit", "Unit Rate",
    "PO Value (text)", "Order / Contract No", "Contact Person / Email",
    "Delivery Date", "T.U.R.", "Zone / Rly Unit", "Source URL", "Detail Fetched",
]

#: The tender fields, in the order they are worth reading. The first seven come
#: from the tender grid; "Tender Type" and "Tender Status" are picked up from
#: the tender's detail page.
TENDER_ORDER = [
    "Tender No", "Tender Title", "Status", "Work Area", "Due Date/Time", "Due Days",
    "Dept/Rly Unit", "Tender Type", "Tender Status",
]


def record_is_tender(record: dict) -> bool:
    """True when a record came from the tender search rather than the PO one.

    A tender row carries a "Tender No"; a purchase-order row carries a
    "Supplier Name" and a "PO Reference" instead. A PO's own detail page can
    name the tender the order was placed against, so the PO marker wins.
    """
    if "Supplier Name" in record or "PO Reference" in record:
        return False
    return "Tender No" in record


def _join_parts(*parts: object) -> str:
    """Join the parts that carry a value, skipping the empty ones."""
    return " - ".join(str(part).strip() for part in parts if part not in (None, ""))


class DetailWindow(tk.Toplevel):
    """Shows every field captured for one record."""

    def __init__(self, parent: tk.Widget, record: dict):
        super().__init__(parent)
        self.record = record
        self.tender = record_is_tender(record)
        self.order = TENDER_ORDER if self.tender else KNOWN_ORDER
        self.title("Record detail")
        self.geometry("720x620")
        self.transient(parent)

        ttk.Label(self, text="Record detail", font=("Segoe UI", 13, "bold"),
                  foreground=TEXT).pack(anchor="w", padx=14, pady=(12, 0))
        subtitle = self._subtitle()
        ttk.Label(self, text=subtitle, font=("Segoe UI", 9), foreground=MUTED,
                  wraplength=680, justify="left").pack(anchor="w", padx=14)

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=14, pady=10)
        tree = ttk.Treeview(tree_frame, columns=("label", "value"), show="headings")
        tree.heading("label", text="Field")
        tree.heading("value", text="Value")
        tree.column("label", width=190, anchor="w")
        tree.column("value", width=470, anchor="w")
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        for label, value in self._pairs():
            tree.insert("", "end", values=(label, value))

        ttk.Button(self, text="Close", command=self.destroy).pack(anchor="e", padx=14, pady=(0, 12))

    def _subtitle(self) -> str:
        """The one-line summary under the title."""
        if self.tender:
            return _join_parts(self.record.get("Tender No"),
                               self.record.get("Tender Title"))
        return _join_parts(self.record.get("Supplier Name"),
                           self.record.get("PO Reference"))

    def _pairs(self) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        used: set[str] = set()
        for name in self.order:
            value = self.record.get(name)
            if value not in (None, ""):
                pairs.append((name, str(value)))
                used.add(name)

        extra_raw = self.record.get("Detail_Extra") or ""
        if extra_raw:
            try:
                extra = json.loads(extra_raw)
            except (TypeError, ValueError):
                extra = {}
            for label, value in extra.items():
                if label in used:
                    continue
                pairs.append((label, str(value)))
                used.add(label)

        for key, value in self.record.items():
            if key in used or key.startswith("_"):
                continue
            if key in ("Detail Labels", "Detail_Extra"):
                # already shown above, expanded into readable rows
                continue
            if value in (None, ""):
                continue
            pairs.append((key, str(value)))
            used.add(key)
        return pairs
