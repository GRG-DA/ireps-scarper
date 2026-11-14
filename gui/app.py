"""The main window.

The layout mirrors the IREPS website: the search form on the left, the
results grid on the right, action buttons underneath, status along the bottom.

Two searches live here. The **tender** search is the portal's "Search Tender"
page - six tabs across the top and the Custom Search form underneath. The
**purchase order** search is the older, smaller form.

All network work happens on a worker thread. The worker never touches a
widget - it pushes messages onto a queue that the Tk event loop drains.
"""

from __future__ import annotations

import io
import os
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.auth import GuestAuth, LoginError  # noqa: E402
from core.client import IrepsClient, RateLimiter  # noqa: E402
from core.config import (  # noqa: E402
    MAX_DATE_SPAN_DAYS,
    PO_SEARCH_URL,
    TENDER_DATE_BASIS,
    TENDER_MATCH_BY_CRITERION,
    TENDER_MAX_DATE_SPAN_DAYS,
    TENDER_SEARCH_OPTIONS,
    TENDER_SEARCH_URL,
    TENDER_TABS,
    SearchCriteria,
    Settings,
)
from core.discovery import discover, fetch_tender_units, fetch_tender_zones  # noqa: E402
from core.engine import ScrapeEngine  # noqa: E402
from core.normalize import date_window, today_ist  # noqa: E402
from excel.exporter import export  # noqa: E402
from gui.detail_window import DetailWindow  # noqa: E402
from gui.login_dialog import LoginDialog  # noqa: E402
from gui.results_view import ResultsView  # noqa: E402
from gui.widgets import DateEntry, form_row  # noqa: E402

BG = "#f4f6f7"
PANEL = "#ffffff"
ACCENT = "#0E7C86"
TEXT = "#20303a"
MUTED = "#6b7c88"

#: The portal's own header and tab colours.
PORTAL_BLUE = "#0090c6"
PORTAL_ORANGE = "#D75125"


class _CaptchaBridge:
    """Carries a captcha question from the worker thread to the UI thread."""

    def __init__(self, message_queue: queue.Queue):
        self.queue = message_queue
        self.event = threading.Event()
        self.answer: str | None = None

    def ask(self, info) -> str | None:
        self.queue.put(("captcha", info, self))
        self.event.wait()
        self.event.clear()
        return self.answer

    def resolve(self, answer: str | None) -> None:
        self.answer = answer
        self.event.set()


class _CaptchaPrompt(tk.Toplevel):
    """A small modal that shows the search-page captcha and takes the answer."""

    def __init__(self, parent: tk.Widget, info):
        super().__init__(parent)
        self.answer: str | None = None
        self.title("Verification code")
        self.configure(bg=PANEL)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        ttk.Label(self, text="Type the characters shown below",
                  font=("Segoe UI", 11, "bold"), foreground=TEXT).pack(anchor="w", padx=16, pady=(14, 6))
        ttk.Label(self, text="The IREPS search page asks for a code on every search.",
                  font=("Segoe UI", 9), foreground=MUTED).pack(anchor="w", padx=16)

        holder = ttk.Frame(self)
        holder.pack(fill="x", padx=16, pady=10)
        self.image = None
        if getattr(info, "image_url", ""):
            try:
                from PIL import Image, ImageTk

                raw = self._download(info.image_url)
                image = Image.open(io.BytesIO(raw)).resize((240, 70))
                self.image = ImageTk.PhotoImage(image)
            except Exception:
                self.image = None
        if self.image is not None:
            ttk.Label(holder, image=self.image).pack()

        row = ttk.Frame(self)
        row.pack(fill="x", padx=16)
        self.var = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.var, width=24, font=("Consolas", 12))
        entry.pack(side="left")
        entry.focus_set()
        ttk.Button(row, text="Search", command=self._accept).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Cancel", command=self._cancel).pack(side="left", padx=(4, 0))
        self.bind("<Return>", lambda _event: self._accept())
        self.bind("<Escape>", lambda _event: self._cancel())

    def _download(self, url: str) -> bytes:
        import requests

        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.content

    def _accept(self) -> None:
        self.answer = self.var.get().strip()
        self.destroy()

    def _cancel(self) -> None:
        self.answer = None
        self.destroy()


class IrepsApp:
    """The application window."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("IREPS - Tender & Purchase Order Search")
        self.root.geometry("1320x860")
        self.root.minsize(1040, 680)
        self.root.configure(bg=BG)

        self.settings = Settings().load()
        self.client = IrepsClient(
            limiter=RateLimiter(self.settings.min_interval, self.settings.jitter),
            timeout=self.settings.timeout,
        )
        self.auth = GuestAuth(self.client, self.settings.mobile, self.settings.country_code)
        self.engine = ScrapeEngine(self.client, self.settings)

        self.queue: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.records: list[dict] = []
        self.last_result = None
        self.mode = tk.StringVar(value="tenders")
        self._combo_values: dict[str, dict[str, str]] = {}
        self._tender_values: dict[str, dict[str, str]] = {}
        self._tab_buttons: dict[str, tk.Button] = {}

        self._build_style()
        self._build_toolbar()
        self._build_body()
        self._build_statusbar()
        self._reset_form()
        self._apply_mode()
        # The cached session is read straight away, so a search started in the
        # first moments still carries the cookies.
        self._session_loaded = self.auth.load_session()
        self._poll()
        self.root.after(400, self._bootstrap)

    # -- construction ------------------------------------------------------
    def _build_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=PANEL)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI", 9))
        style.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Note.TLabel", background=PANEL, foreground="#b3261e",
                        font=("Segoe UI", 9, "bold"))
        style.configure("Title.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI", 13, "bold"))
        style.configure("TButton", font=("Segoe UI", 9), padding=(8, 5))
        style.configure("Accent.TButton", font=("Segoe UI", 9, "bold"), padding=(10, 6),
                        background=ACCENT, foreground="#ffffff")
        style.map("Accent.TButton",
                  background=[("active", "#0a626a"), ("disabled", "#b9c7cc")])
        style.configure("TLabelframe", background=PANEL, bordercolor="#d6e0e5")
        style.configure("TLabelframe.Label", background=PANEL, foreground=TEXT,
                        font=("Segoe UI", 9, "bold"))
        style.configure("Status.TLabel", background="#e9eef1", foreground=TEXT, font=("Segoe UI", 9))

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self.root, padding=(12, 10))
        bar.pack(fill="x")

        self.login_button = ttk.Button(bar, text="Sign in", command=self._login)
        self.login_button.pack(side="left")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)

        self.search_button = ttk.Button(bar, text="Show Results", style="Accent.TButton",
                                        command=self._show_results)
        self.search_button.pack(side="left")
        self.reset_button = ttk.Button(bar, text="Reset", command=self._reset_form)
        self.reset_button.pack(side="left", padx=6)
        self.cancel_button = ttk.Button(bar, text="Cancel", command=self._cancel, state="disabled")
        self.cancel_button.pack(side="left")

        self.details_var = tk.BooleanVar(value=self.settings.fetch_details)
        self.details_check = ttk.Checkbutton(
            bar, text="Fetch detail pages", variable=self.details_var)
        self.details_check.pack(side="left", padx=14)

        self.export_button = ttk.Button(bar, text="Export to Excel", command=self._export)
        self.export_button.pack(side="right")
        ttk.Label(bar, text="IREPS", font=("Segoe UI", 13, "bold"),
                  foreground=ACCENT).pack(side="right", padx=(0, 14))

        # which of the two searches is on screen
        switch = ttk.Frame(self.root, padding=(12, 0))
        switch.pack(fill="x")
        ttk.Label(switch, text="Search:", style="Muted.TLabel").pack(side="left")
        ttk.Radiobutton(switch, text="Tenders", variable=self.mode, value="tenders",
                        command=self._apply_mode).pack(side="left", padx=(4, 0))
        ttk.Radiobutton(switch, text="Purchase Orders", variable=self.mode, value="po",
                        command=self._apply_mode).pack(side="left", padx=(10, 0))

    def _build_body(self) -> None:
        paned = ttk.PanedWindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=12, pady=(8, 10))

        left = ttk.Frame(paned, padding=10, style="Panel.TFrame")
        right = ttk.Frame(paned, padding=10, style="Panel.TFrame")
        paned.add(left, weight=0)
        paned.add(right, weight=1)

        # ---------------- search form -------------------------------------
        canvas = tk.Canvas(left, bg=PANEL, highlightthickness=0, width=560)
        scrollbar = ttk.Scrollbar(left, orient="vertical", command=canvas.yview)
        holder = ttk.Frame(canvas, style="Panel.TFrame")
        window = canvas.create_window((0, 0), window=holder, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        holder.bind("<Configure>",
                    lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda event: canvas.itemconfigure(window, width=event.width))

        self.vars: dict[str, tk.Variable] = {
            "organisation": tk.StringVar(value="All"),
            "search_text": tk.StringVar(value=""),
            "po_value_from": tk.StringVar(value="5"),
            "po_value_to": tk.StringVar(value="99999"),
        }
        self.combos: dict[str, ttk.Combobox] = {}
        self.tender_combos: dict[str, ttk.Combobox] = {}

        self.tender_frame = self._build_tender_form(holder)
        self.po_frame = self._build_po_form(holder)

        # ---------------- results -----------------------------------------
        ttk.Label(right, text="Results", style="Title.TLabel").pack(anchor="w", pady=(0, 6))
        self.results = ResultsView(right, mode=self.mode.get())
        self.results.pack(fill="both", expand=True)
        self.results.tree.bind("<Double-1>", lambda _event: self._open_detail())

    # -- the tender form (the portal's "Search Tender" page) ----------------
    def _build_tender_form(self, parent: tk.Widget) -> ttk.Frame:
        form = ttk.Frame(parent, style="Panel.TFrame")

        header = tk.Frame(form, bg=PORTAL_BLUE, height=26)
        header.pack(fill="x")
        tk.Label(header, text="  Search Tender", bg=PORTAL_BLUE, fg="white",
                 font=("Segoe UI", 11, "bold", "italic")).pack(side="left")

        # the portal's six tabs, laid out three to a row so they always fit
        tabs = tk.Frame(form, bg=PANEL)
        tabs.pack(fill="x", pady=(8, 0))
        for index, (label, _search_param) in enumerate(TENDER_TABS):
            button = tk.Button(
                tabs, text=label, relief="raised", bd=1,
                background="#e8edef", foreground=TEXT,
                font=("Segoe UI", 8, "bold"),
                command=lambda name=label: self._run_tab(name),
            )
            button.grid(row=index // 3, column=index % 3, sticky="w",
                        padx=(0, 4), pady=2)
            self._tab_buttons[label] = button

        ttk.Label(
            form,
            text="(Please choose one or more option for search, view & Downloading "
                 "E-Tender Notices and Click 'Show results' to view Details of E-tenders)",
            font=("Segoe UI", 9, "bold"), foreground=TEXT, wraplength=520,
            justify="left",
        ).pack(anchor="w", pady=(10, 8))

        # --- search criteria + search text -------------------------------
        self.tender_vars: dict[str, tk.Variable] = {
            "tender_criteria": tk.StringVar(value="Tender Number"),
            "tender_match": tk.StringVar(value="Starting with"),
            "search_text": tk.StringVar(value=""),
            "tender_organisation": tk.StringVar(value="Indian Railway"),
            "work_area": tk.StringVar(value="All"),
            "railway_zone": tk.StringVar(value="All"),
            "division": tk.StringVar(value="All"),
            "unit": tk.StringVar(value="All"),
            "tender_status": tk.StringVar(value="All"),
            "tender_type": tk.StringVar(value="All"),
            "tender_bidding": tk.StringVar(value="All"),
            "date_basis": tk.StringVar(value="Tender Closing Date"),
            "period": tk.StringVar(value="custom"),
        }

        criteria_row = ttk.Frame(form)
        criteria_row.pack(fill="x")
        ttk.Label(criteria_row, text="Search Criteria:").grid(row=0, column=0, sticky="w")
        self.tender_criteria_combo = self._tender_combo(
            criteria_row, "tender_criteria", list(TENDER_SEARCH_OPTIONS),
            width=18, command=self._sync_match_options)
        self.tender_criteria_combo.grid(row=0, column=1, padx=(6, 4))
        self.tender_match_combo = self._tender_combo(
            criteria_row, "tender_match", list(TENDER_MATCH_BY_CRITERION["Tender Number"]),
            width=16)
        self.tender_match_combo.grid(row=0, column=2)
        ttk.Label(criteria_row, text="Search For :").grid(row=0, column=3, padx=(14, 6))
        ttk.Entry(criteria_row, textvariable=self.tender_vars["search_text"],
                  width=26).grid(row=0, column=4, sticky="ew")
        criteria_row.columnconfigure(4, weight=1)

        ttk.Label(
            form,
            text="Note:- Please enter minimum first 3 characters of Tender Number or PLNO "
                 "(these are case sensitive) or any 3 consecutive characters of Tender title "
                 "or item description.",
            style="Note.TLabel", wraplength=520, justify="left",
        ).pack(anchor="w", pady=(6, 10))

        # --- the two columns of dropdowns ---------------------------------
        grid = ttk.Frame(form)
        grid.pack(fill="x")
        for column in (0, 1):
            grid.columnconfigure(column, weight=1)

        left_box = ttk.Frame(grid)
        left_box.grid(row=0, column=0, sticky="new", padx=(0, 10))
        left_box.columnconfigure(1, weight=1)
        right_box = ttk.Frame(grid)
        right_box.grid(row=0, column=1, sticky="new")
        right_box.columnconfigure(1, weight=1)

        row = 0
        row = form_row(left_box, row, "Organization",
                       self._tender_combo(left_box, "tender_organisation",
                                          ["Indian Railway"], width=24,
                                          command=self._reload_zones))
        row = form_row(left_box, row, "Railway/PU *",
                       self._tender_combo(left_box, "railway_zone", ["All"], width=24,
                                          command=self._reload_units))
        row = form_row(left_box, row, "Unit",
                       self._tender_combo(left_box, "unit", ["All"], width=24))
        row = form_row(left_box, row, "Tender Status:",
                       self._tender_combo(left_box, "tender_status", ["All"], width=24))
        row = form_row(left_box, row, "Bidding System",
                       self._tender_combo(left_box, "tender_bidding", ["All"], width=24))
        form_row(left_box, row, "Tender Type:",
                 self._tender_combo(left_box, "tender_type", ["All"], width=24))

        row = 0
        row = form_row(right_box, row, "Work Area *",
                       self._tender_combo(right_box, "work_area", ["All"], width=24))
        row = form_row(right_box, row, "Department *",
                       self._tender_combo(right_box, "division", ["All"], width=24))
        row = form_row(right_box, row, "Select Date",
                       self._tender_combo(right_box, "date_basis",
                                          list(TENDER_DATE_BASIS), width=24))

        # --- the date range -----------------------------------------------
        dates = ttk.Frame(form)
        dates.pack(fill="x", pady=(10, 0))
        self.tender_date_from = DateEntry(dates, width=12)
        self.tender_date_to = DateEntry(dates, width=12)
        ttk.Label(dates, text="From").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.tender_date_from.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        ttk.Label(dates, text="To").grid(row=0, column=2, sticky="w", padx=(0, 4))
        self.tender_date_to.grid(row=0, column=3, sticky="ew")
        dates.columnconfigure(1, weight=1)
        dates.columnconfigure(3, weight=1)

        # --- the relative date shortcuts ----------------------------------
        periods = ttk.Frame(form)
        periods.pack(fill="x", pady=(8, 0))
        choices = [("Last 6 months", "6"), ("Last 3 months", "3"),
                   ("Next 3 months", "3n"), ("Next 6 months", "6n"),
                   ("Custom Date", "custom")]
        for index, (label, value) in enumerate(choices):
            ttk.Radiobutton(periods, text=label, variable=self.tender_vars["period"],
                            value=value, command=self._apply_period).grid(
                row=0, column=index, sticky="w", padx=(0, 10))

        ttk.Label(form, text="*Date range should be within one year",
                  style="Note.TLabel").pack(anchor="w", pady=(4, 0))

        ttk.Button(form, text="Show Results", style="Accent.TButton",
                   command=self._show_results).pack(anchor="e", pady=(10, 14))
        return form

    def _tender_combo(self, parent, key: str, values: list[str], width: int = 20,
                      command=None) -> ttk.Combobox:
        combo = ttk.Combobox(parent, textvariable=self.tender_vars[key], values=values,
                             state="readonly", width=width)
        self.tender_combos[key] = combo
        if command:
            combo.bind("<<ComboboxSelected>>", lambda _event: command())
        return combo

    def _sync_match_options(self) -> None:
        """The portal offers "Equals" for numbers and "Containing" for text."""
        criterion = self.tender_vars["tender_criteria"].get()
        options = list(TENDER_MATCH_BY_CRITERION.get(criterion, ("Starting with",)))
        self.tender_match_combo.configure(values=options)
        if self.tender_vars["tender_match"].get() not in options:
            self.tender_vars["tender_match"].set(options[-1])

    # -- the purchase order form --------------------------------------------
    def _build_po_form(self, parent: tk.Widget) -> ttk.Frame:
        form = ttk.Frame(parent, style="Panel.TFrame")

        header = tk.Frame(form, bg=PORTAL_BLUE, height=26)
        header.pack(fill="x")
        tk.Label(header, text="  Search Purchase Order", bg=PORTAL_BLUE, fg="white",
                 font=("Segoe UI", 11, "bold", "italic")).pack(side="left")

        search_box = ttk.LabelFrame(form, text="Search", padding=10)
        search_box.pack(fill="x", pady=(10, 8))
        row = 0
        row = form_row(search_box, row, "Organisation / Unit",
                       self._combo(search_box, "organisation", ["All"]))
        row = form_row(search_box, row, "PL Number",
                       ttk.Entry(search_box, textvariable=self.vars["search_text"]))
        row = form_row(search_box, row, "PO Value From",
                       ttk.Entry(search_box, textvariable=self.vars["po_value_from"], width=14))
        form_row(search_box, row, "PO Value To",
                 ttk.Entry(search_box, textvariable=self.vars["po_value_to"], width=14))

        date_box = ttk.LabelFrame(form, text="Date Range", padding=10)
        date_box.pack(fill="x", pady=(0, 8))
        row = 0
        self.date_from = DateEntry(date_box)
        self.date_to = DateEntry(date_box)
        row = form_row(date_box, row, "Date From", self.date_from)
        row = form_row(date_box, row, "Date To", self.date_to)
        ttk.Label(date_box, text="The portal will not accept a range longer than two years.",
                  style="Muted.TLabel", wraplength=300, justify="left").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Label(form, text="Dates are dd/mm/yyyy (IST). Leave PL Number empty to "
                             "return every order in the date range.",
                  style="Muted.TLabel", wraplength=330, justify="left").pack(
            anchor="w", pady=(4, 10))
        return form

    def _combo(self, parent, key: str, values: list[str]) -> ttk.Combobox:
        combo = ttk.Combobox(parent, textvariable=self.vars[key], values=values,
                             state="readonly", width=24)
        self.combos[key] = combo
        return combo

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self.root, style="TFrame", padding=(12, 5))
        bar.pack(fill="x", side="bottom")
        self.session_label = ttk.Label(bar, text="Not signed in", style="Status.TLabel")
        self.session_label.pack(side="left")
        self.count_label = ttk.Label(bar, text="0 records", style="Status.TLabel")
        self.count_label.pack(side="right")
        self.message_label = ttk.Label(bar, text="Ready.", style="Status.TLabel")
        self.message_label.pack(side="right", padx=(0, 20))
        self.progress = ttk.Progressbar(bar, mode="determinate", length=140)
        self.progress.pack(side="right", padx=(0, 16))

    # -- state -------------------------------------------------------------
    def _apply_mode(self) -> None:
        """Show the form that belongs to the selected search."""
        mode = self.mode.get()
        self.tender_frame.pack_forget()
        self.po_frame.pack_forget()
        if mode == "tenders":
            self.tender_frame.pack(fill="both", expand=True)
            self._highlight_tab("Custom Search")
        else:
            self.po_frame.pack(fill="both", expand=True)
        self.results.set_mode(mode)
        self.root.title("IREPS - Tender Search" if mode == "tenders"
                        else "IREPS - Purchase Order Search")

    def _highlight_tab(self, active: str) -> None:
        for label, button in self._tab_buttons.items():
            if label == active:
                button.configure(background=PORTAL_ORANGE, foreground="white")
            else:
                button.configure(background="#e8edef", foreground=TEXT)

    def _reset_form(self) -> None:
        start, end = date_window(30)
        self.date_from.set_value(start)
        self.date_to.set_value(end)
        self.vars["search_text"].set("")
        self.vars["po_value_from"].set("5")
        self.vars["po_value_to"].set("99999")

        self.tender_vars["search_text"].set("")
        self.tender_vars["period"].set("custom")
        self.tender_vars["date_basis"].set("Tender Closing Date")
        self.tender_date_from.set_value(start)
        self.tender_date_to.set_value(end)

    def _apply_period(self) -> None:
        """Set the dates the way the portal's shortcut buttons do."""
        period = self.tender_vars["period"].get()
        today = today_ist()
        if period == "6":
            start = today - timedelta(days=182)
            end = today
        elif period == "3":
            start = today - timedelta(days=91)
            end = today
        elif period == "3n":
            start = today
            end = today + timedelta(days=91)
        elif period == "6n":
            start = today
            end = today + timedelta(days=182)
        else:
            return
        self.tender_date_from.set_value(start.strftime("%d/%m/%Y"))
        self.tender_date_to.set_value(end.strftime("%d/%m/%Y"))

    def _bootstrap(self) -> None:
        """Check the cached session at start-up so a normal run needs no login."""
        if self._session_loaded:
            self._set_status("Cached session found - checking it...")
            threading.Thread(target=self._check_session, daemon=True).start()
        else:
            self._set_status("Not signed in. Press Sign in to get an OTP.")

    def _check_session(self) -> None:
        alive = self.auth.is_authenticated()
        self.queue.put(("session", alive, None))

    def _login(self) -> None:
        dialog = LoginDialog(self.root, self.auth)
        self.root.wait_window(dialog)
        if dialog.result:
            self.auth.save_session()
            self._set_status("Signed in. Loading the search options from IREPS...")
            threading.Thread(target=self._load_options, daemon=True).start()
        else:
            self._set_status("Sign in cancelled.")

    def _load_options(self) -> None:
        """Populate the dropdowns from the live pages.

        The two forms live on two different pages and their "Railway/PU"
        dropdowns hold different ids, so both pages are read.
        """
        options: dict[str, list] = {}
        try:
            tender_info = discover(self.client.get(TENDER_SEARCH_URL).text)
        except Exception as exc:  # noqa: BLE001
            self.queue.put(("status", f"Could not load the dropdowns: {exc}", None))
            return
        options.update(
            {
                "tender_organisation": tender_info.selects.get("organization", []),
                "railway_zone": tender_info.selects.get("railwayZone", []),
                "division": tender_info.selects.get("division", []),
                "unit": tender_info.selects.get("unit", []),
                "tender_status": tender_info.selects.get("tenderStage", []),
                "tender_type": tender_info.selects.get("tenderType", []),
                "tender_bidding": tender_info.selects.get("bidding", []),
                "work_area": tender_info.selects.get("workArea", []),
            }
        )
        try:
            po_info = discover(self.client.get(PO_SEARCH_URL).text)
            options["organisation"] = (po_info.selects.get("railwayZone")
                                        or po_info.selects.get("searchOption") or [])
        except Exception:  # noqa: BLE001 - the PO form can wait for its own page
            options["organisation"] = []
        self.queue.put(("options", options, None))

    def _reload_zones(self) -> None:
        """Ask the portal for the Railway/PU list of the chosen organisation."""
        organisation = self._resolve_tender("tender_organisation",
                                            self.tender_vars["tender_organisation"].get())
        if not organisation:
            return
        threading.Thread(target=self._load_zones, args=(organisation,), daemon=True).start()

    def _load_zones(self, organisation: str) -> None:
        options = fetch_tender_zones(self.client, organisation)
        self.queue.put(("zones", options, None))

    def _reload_units(self) -> None:
        """Ask the portal for the Unit list of the chosen department and zone."""
        zone = self._resolve_tender("railway_zone", self.tender_vars["railway_zone"].get())
        division = self._resolve_tender("division", self.tender_vars["division"].get())
        work_area = self._resolve_tender("work_area", self.tender_vars["work_area"].get())
        threading.Thread(target=self._load_units, args=(division, zone, work_area),
                         daemon=True).start()

    def _load_units(self, division: str, zone: str, work_area: str) -> None:
        options = fetch_tender_units(self.client, division, zone, work_area)
        self.queue.put(("units", options, None))

    # -- running -----------------------------------------------------------
    def _criteria(self) -> SearchCriteria:
        if self.mode.get() == "tenders":
            return self._tender_criteria()
        criteria = SearchCriteria(
            date_from=self.date_from.get(),
            date_to=self.date_to.get(),
            date_basis="Tender Uploading Date",
            search_text=self.vars["search_text"].get(),
            railway_zone=self._resolve("organisation", self.vars["organisation"].get()),
            organisation=self.vars["organisation"].get(),
            po_value_from=self.vars["po_value_from"].get(),
            po_value_to=self.vars["po_value_to"].get(),
            mode="po",
        )
        criteria.fetch_details = bool(self.details_var.get())
        criteria.zone_label = self.vars["organisation"].get()
        return criteria

    def _tender_criteria(self) -> SearchCriteria:
        criteria = SearchCriteria(
            mode="tenders",
            date_from=self.tender_date_from.get(),
            date_to=self.tender_date_to.get(),
            date_basis=self.tender_vars["date_basis"].get(),
            search_text=self.tender_vars["search_text"].get(),
            tender_criteria=self.tender_vars["tender_criteria"].get(),
            tender_match=self.tender_vars["tender_match"].get(),
            organisation=self._resolve_tender("tender_organisation",
                                              self.tender_vars["tender_organisation"].get()),
            work_area=self.tender_vars["work_area"].get(),
            railway_zone=self._resolve_tender("railway_zone",
                                              self.tender_vars["railway_zone"].get()),
            division=self._resolve_tender("division", self.tender_vars["division"].get()),
            unit=self._resolve_tender("unit", self.tender_vars["unit"].get()),
            tender_status=self.tender_vars["tender_status"].get(),
            tender_type=self.tender_vars["tender_type"].get(),
            tender_bidding=self.tender_vars["tender_bidding"].get(),
            tender_tab="Custom Search",
        )
        criteria.fetch_details = bool(self.details_var.get())
        criteria.zone_label = self.tender_vars["railway_zone"].get()
        criteria.division_label = self.tender_vars["division"].get()
        criteria.unit_label = self.tender_vars["unit"].get()
        criteria.organisation_label = self.tender_vars["tender_organisation"].get()
        return criteria

    def _validate(self, criteria: SearchCriteria) -> str:
        if criteria.mode == "tenders":
            return self._validate_tender(criteria)
        if not criteria.date_from or not criteria.date_to:
            return "Set both the Date From and Date To fields."
        try:
            start = datetime.strptime(criteria.date_from, "%d/%m/%Y")
            end = datetime.strptime(criteria.date_to, "%d/%m/%Y")
        except ValueError:
            return "Dates must be written as dd/mm/yyyy."
        if end < start:
            return "Date To cannot be earlier than Date From."
        span = (end - start).days
        if span > MAX_DATE_SPAN_DAYS:
            return ("The portal rejects a PO date range longer than two years "
                    f"(you asked for {span} days).")
        return ""

    def _validate_tender(self, criteria: SearchCriteria) -> str:
        if not criteria.date_from or not criteria.date_to:
            return "Set both the From and To dates."
        try:
            start = datetime.strptime(criteria.date_from, "%d/%m/%Y")
            end = datetime.strptime(criteria.date_to, "%d/%m/%Y")
        except ValueError:
            return "Dates must be written as dd/mm/yyyy."
        if end < start:
            return "The To date cannot be earlier than the From date."
        if (end - start).days >= TENDER_MAX_DATE_SPAN_DAYS:
            return ("The tender page rejects a date range of a year or more "
                    f"(you asked for {(end - start).days} days).")
        if criteria.date_basis == "Tender Uploading Date" and end > today_ist():
            return "With 'Tender Uploading Date' the To date cannot be in the future."
        if criteria.railway_zone in ("", "-Select--"):
            return "Please select a Railway/PU."
        text = (criteria.search_text or "").strip()
        if text and len(text) < 3:
            return "The search text needs at least 3 characters."
        return ""

    def _show_results(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        criteria = self._criteria()
        problem = self._validate(criteria)
        if problem:
            messagebox.showwarning("IREPS", problem, parent=self.root)
            return
        self._start(criteria)

    def _run_tab(self, label: str) -> None:
        """Run one of the portal's six quick views."""
        if self.worker and self.worker.is_alive():
            return
        criteria = self._tender_criteria()
        criteria.tender_tab = label
        # The quick views ignore the custom search form, so the date range is
        # not checked for them.
        self._highlight_tab(label)
        self._start(criteria)

    def _start(self, criteria: SearchCriteria) -> None:
        self.cancel_event.clear()
        self.results.clear()
        self.records = []
        self.progress["value"] = 0
        self._set_busy(True)
        self._set_status("Starting the search...")

        bridge = _CaptchaBridge(self.queue)
        self.worker = threading.Thread(
            target=self._run_worker, args=(criteria, bridge), daemon=True
        )
        self.worker.start()

    def _run_worker(self, criteria: SearchCriteria, bridge: _CaptchaBridge) -> None:
        try:
            self.engine.run(
                criteria,
                captcha_prompt=lambda info: bridge.ask(info),
                progress=lambda event: self.queue.put(("progress", event, None)),
                cancel_event=self.cancel_event,
            )
        except Exception as exc:  # noqa: BLE001
            self.queue.put(("progress", {"kind": "error", "message": repr(exc)}, None))

    def _cancel(self) -> None:
        self.cancel_event.set()
        self._set_status("Cancelling...")

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.search_button.configure(state=state)
        self.export_button.configure(state=state)
        self.cancel_button.configure(state="normal" if busy else "disabled")
        self.login_button.configure(state=state)

    # -- the event loop ----------------------------------------------------
    def _poll(self) -> None:
        try:
            while True:
                kind, payload, extra = self.queue.get_nowait()
                if kind == "progress":
                    self._handle_progress(payload)
                elif kind == "captcha":
                    prompt = _CaptchaPrompt(self.root, payload)
                    self.root.wait_window(prompt)
                    extra.resolve(prompt.answer)
                elif kind == "session":
                    self._handle_session(payload)
                elif kind == "options":
                    self._handle_options(payload)
                elif kind == "zones":
                    self._handle_zones(payload)
                elif kind == "units":
                    self._handle_units(payload)
                elif kind == "status":
                    self._set_status(payload)
        except queue.Empty:
            pass
        self.root.after(120, self._poll)

    def _handle_session(self, alive: bool) -> None:
        if alive:
            self._set_status("Session is valid.")
            self.session_label.configure(text=f"Signed in (mobile {self.auth.mobile[-4:]})")
            threading.Thread(target=self._load_options, daemon=True).start()
        else:
            self.session_label.configure(text="Not signed in")
            self._set_status("The cached session has expired. Press Sign in.")

    def _handle_options(self, options: dict) -> None:
        """Fill the dropdowns, remembering label -> portal value for each."""
        for key, entries in options.items():
            if key == "organisation":
                combo, values = self.combos.get("organisation"), self._combo_values
            else:
                combo, values = self.tender_combos.get(key), self._tender_values
            if combo is None:
                continue
            labels: list[str] = []
            mapping: dict[str, str] = {}
            for entry in entries:
                if not entry.label or entry.label in mapping:
                    continue
                # The zone dropdown opens with a "---Select---" entry that
                # carries no id; the portal rejects an empty zone.
                if not entry.value:
                    continue
                labels.append(entry.label)
                mapping[entry.label] = entry.value
            # Most of the portal's dropdowns list an "All" entry; make sure
            # it maps to -1. The organisation dropdown does **not** have one -
            # the portal only knows the organisations it lists - so an "All"
            # is not invented for it, because the server answers an unknown
            # organisation with an empty result set.
            if "All" not in mapping and key != "tender_organisation":
                labels.insert(0, "All")
            mapping["All"] = mapping.get("All") or "-1"
            combo.configure(values=labels)
            values[key] = mapping
        self._set_status("Search options loaded from IREPS.")

    def _handle_zones(self, options: list) -> None:
        if not options:
            return
        labels = [option.label for option in options]
        mapping = {option.label: option.value for option in options}
        if "All" not in mapping:
            labels.insert(0, "All")
            mapping["All"] = "-1"
        self.tender_combos["railway_zone"].configure(values=labels)
        self._tender_values["railway_zone"] = mapping
        if self.tender_vars["railway_zone"].get() not in labels:
            self.tender_vars["railway_zone"].set("All")
        self._set_status(f"{len(options)} Railway/PU options loaded from IREPS.")

    def _handle_units(self, options: list) -> None:
        if not options:
            return
        labels = [option.label for option in options]
        mapping = {option.label: option.value for option in options}
        if "All" not in mapping:
            labels.insert(0, "All")
            mapping["All"] = "-1"
        self.tender_combos["unit"].configure(values=labels)
        self._tender_values["unit"] = mapping
        if self.tender_vars["unit"].get() not in labels:
            self.tender_vars["unit"].set("All")
        self._set_status(f"{len(options)} Unit options loaded from IREPS.")

    def _resolve(self, key: str, label: str) -> str:
        """Turn a visible label into the value the portal expects."""
        mapping = getattr(self, "_combo_values", {}).get(key, {})
        return mapping.get(label, label if label != "All" else "-1")

    def _resolve_tender(self, key: str, label: str) -> str:
        """The same, for the tender form's dropdowns."""
        mapping = getattr(self, "_tender_values", {}).get(key, {})
        return mapping.get(label, label if label != "All" else "-1")

    def _handle_progress(self, event: dict) -> None:
        kind = event.get("kind")
        if kind == "status":
            self._set_status(event.get("message", ""))
        elif kind == "page":
            page = event.get("page", 0)
            self.progress["maximum"] = max(10, page)
            self.progress["value"] = page
        elif kind == "rows":
            self.results.add_records(event.get("records", []))
            self.records = self.results.records
            self.count_label.configure(text=f"{len(self.records)} records")
        elif kind == "error":
            self._set_status(event.get("message", ""))
            messagebox.showerror("IREPS", event.get("message", "Something went wrong."),
                                 parent=self.root)
        elif kind == "done":
            result = event.get("result")
            self.last_result = result
            self._set_busy(False)
            self.progress["value"] = 0
            self.records = self.results.records
            self.count_label.configure(text=f"{len(self.records)} records")
            if result and result.cancelled:
                self._set_status("Cancelled - the rows collected so far are still available.")
            else:
                self._set_status(
                    f"Done: {len(self.records)} records from {result.pages_fetched} page(s) "
                    f"in {result.elapsed:.0f}s."
                )

    def _set_status(self, message: str) -> None:
        self.message_label.configure(text=message)

    # -- detail ------------------------------------------------------------
    def _open_detail(self) -> None:
        record = self.results.selected_record()
        if record is None:
            return
        DetailWindow(self.root, record)

    # -- export ------------------------------------------------------------
    def _export(self) -> None:
        records = self.results.records
        if not records:
            messagebox.showinfo("IREPS", "There is nothing to export yet - run a search first.",
                                parent=self.root)
            return
        criteria = self._criteria()
        result = self.last_result
        if result is None:
            from core.engine import ScrapeResult

            result = ScrapeResult(criteria=criteria, records=records)
            result.started_at = result.finished_at = datetime.now().timestamp()
        try:
            path = export(records, result, criteria, self.settings.output_dir)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("IREPS", f"Could not write the workbook:\n{exc}",
                                 parent=self.root)
            return
        self._set_status(f"Saved {path.name}")
        if messagebox.askyesno(
            "IREPS", f"Saved to:\n{path}\n\nOpen the folder now?", parent=self.root
        ):
            try:
                os.startfile(str(path.parent))
            except Exception:
                pass


def main() -> int:
    root = tk.Tk()
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    IrepsApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
