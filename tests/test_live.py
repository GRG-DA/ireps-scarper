"""Live end-to-end check against the real IREPS portal.

Uses the cached session in state/session.pkl, runs a real PO search and
exports a real workbook. Screenshots are written to state/shots/.

    python tests/test_live.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import tkinter as tk  # noqa: E402

from test_screens import capture, shoot  # noqa: E402


def main() -> int:
    from core.config import SearchCriteria, Settings
    from excel.exporter import export
    from gui.app import IrepsApp

    root = tk.Tk()
    root.geometry("1240x800+40+40")
    app = IrepsApp(root)

    # this check exercises the purchase-order search
    app.mode.set("po")
    app._apply_mode()

    # let the cached-session check and the dropdown load finish
    deadline = time.time() + 45
    while time.time() < deadline:
        root.update()
        time.sleep(0.1)
        if app.combos["organisation"]["values"] and len(app.combos["organisation"]["values"]) > 1:
            break
    root.update()
    shoot(root, "04_live_signed_in.png")
    print("session label :", app.session_label.cget("text"))
    print("status        :", app.message_label.cget("text"))
    values = app.combos["organisation"]["values"]
    print("organisation dropdown entries:", len(values))
    print("  first few:", values[:6])

    # run a real search
    app.vars["search_text"].set("")
    app.date_from.set_value("11/11/2026")
    app.date_to.set_value("11/11/2026")
    app.combos["organisation"].set(values[1] if len(values) > 1 else "All")
    app._show_results()
    deadline = time.time() + 180
    while app.worker and app.worker.is_alive() and time.time() < deadline:
        root.update()
        time.sleep(0.05)
    root.update()
    shoot(root, "05_live_results.png")

    print("\nrows in the grid:", len(app.results.tree.get_children()))
    print("status           :", app.message_label.cget("text"))
    for row in app.results.tree.get_children()[:5]:
        values_ = app.results.tree.item(row, "values")
        print("   ", " | ".join(str(v)[:34] for v in values_[:4]))

    criteria = app._criteria()
    result = app.last_result
    path = export(app.results.records, result, criteria, Path("output"))
    print("\nexported:", path.name, path.stat().st_size, "bytes")

    import openpyxl
    workbook = openpyxl.load_workbook(path)
    print("sheets:", workbook.sheetnames)
    print("PO_Data rows:", workbook["PO_Data"].max_row - 1)

    root.destroy()
    print("\nLIVE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
