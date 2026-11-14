"""Small reusable Tk widgets: labelled rows and a dd/mm/yyyy date picker."""

from __future__ import annotations

import calendar
import tkinter as tk
from datetime import datetime
from tkinter import ttk

BG = "#ffffff"
ACCENT = "#0E7C86"
TEXT = "#20303a"


def form_row(parent: tk.Widget, row: int, label: str, widget: tk.Widget,
             pady: int = 4) -> int:
    """Place a label and a widget side by side on one row. Returns the next row."""
    text = ttk.Label(parent, text=label, foreground=TEXT)
    text.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=pady)
    widget.grid(row=row, column=1, sticky="ew", pady=pady)
    return row + 1


class CalendarPopup(tk.Toplevel):
    """A compact month grid that hands back a ``dd/mm/yyyy`` string."""

    def __init__(self, parent: tk.Widget, on_pick, initial: datetime | None = None):
        super().__init__(parent)
        self.on_pick = on_pick
        self.selected = initial or datetime.now()
        self.title("Pick a date")
        self.resizable(False, False)
        self.configure(bg=BG)
        self._build()
        self.update_idletasks()
        x = parent.winfo_rootx() + parent.winfo_width()
        y = parent.winfo_rooty()
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _build(self) -> None:
        header = ttk.Frame(self, padding=6)
        header.pack(fill="x")
        ttk.Button(header, text="<", width=3, command=lambda: self._shift(-1)).pack(side="left")
        self.title_label = ttk.Label(header, anchor="center", font=("Segoe UI", 10, "bold"))
        self.title_label.pack(side="left", expand=True, fill="x")
        ttk.Button(header, text=">", width=3, command=lambda: self._shift(1)).pack(side="right")

        grid = ttk.Frame(self, padding=6)
        grid.pack()
        self._grid = grid
        for column, name in enumerate(("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")):
            ttk.Label(grid, text=name, width=4, anchor="center",
                      font=("Segoe UI", 9, "bold")).grid(row=0, column=column, padx=1, pady=1)
        self.buttons: dict[tuple[int, int], tk.Button] = {}
        self._fill()

    def _shift(self, months: int) -> None:
        month = self.selected.month - 1 + months
        year = self.selected.year + month // 12
        month = month % 12 + 1
        self.selected = self.selected.replace(year=year, month=month, day=1)
        self._fill()

    def _fill(self) -> None:
        for button in self.buttons.values():
            button.destroy()
        self.buttons.clear()
        self.title_label.configure(text=f"{calendar.month_name[self.selected.month]} {self.selected.year}")
        days = calendar.monthcalendar(self.selected.year, self.selected.month)
        today = datetime.now().date()
        for row, week in enumerate(days, start=1):
            for column, day in enumerate(week):
                if day == 0:
                    continue
                date = datetime(self.selected.year, self.selected.month, day)
                is_today = date.date() == today
                button = tk.Button(
                    self.buttons_frame(), text=str(day), width=4, relief="flat",
                    bd=0, cursor="hand",
                    background="#d9eef1" if is_today else BG,
                    foreground=TEXT,
                    command=lambda d=date: self._pick(d),
                )
                button.grid(row=row, column=column, padx=1, pady=1)
                self.buttons[(row, column)] = button

    def buttons_frame(self) -> tk.Widget:
        return self._grid

    def _pick(self, date: datetime) -> None:
        self.on_pick(date.strftime("%d/%m/%Y"))
        self.destroy()


class DateEntry(ttk.Frame):
    """A read-only-looking dd/mm/yyyy entry with a calendar button."""

    def __init__(self, parent: tk.Widget, value: str = "", width: int = 14):
        super().__init__(parent)
        self.var = tk.StringVar(value=value)
        self.entry = ttk.Entry(self, textvariable=self.var, width=width, justify="center")
        self.entry.pack(side="left", fill="x", expand=True)
        ttk.Button(self, text="📅", width=3, command=self._open).pack(side="left", padx=(4, 0))

    def _open(self) -> None:
        try:
            current = datetime.strptime(self.var.get(), "%d/%m/%Y")
        except ValueError:
            current = datetime.now()
        CalendarPopup(self, self.set_value, current)

    def set_value(self, text: str) -> None:
        self.var.set(text)

    def get(self) -> str:
        return self.var.get().strip()
