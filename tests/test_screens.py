"""Take screenshots of the app for verification.

Captures the real login dialog (with a live captcha downloaded from the
portal), the populated results grid, and the record detail window.

    python tests/test_screens.py
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tkinter as tk  # noqa: E402

from core.client import IrepsClient, RateLimiter  # noqa: E402
from core.config import PO_SEARCH_URL, Settings  # noqa: E402
from core.discovery import discover  # noqa: E402

SHOTS = ROOT / "state" / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


def capture(hwnd: int, path: Path) -> None:
    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    def rect_of(handle):
        rect = RECT()
        user32.GetWindowRect(handle, ctypes.byref(rect))
        return rect.right - rect.left, rect.bottom - rect.top

    # Try the handle, its parent, then the root ancestor, and keep the first
    # one that actually has a size (Tk toplevels behave differently from
    # child widgets).
    candidates = [hwnd, user32.GetParent(hwnd), user32.GetAncestor(hwnd, 2)]
    width = height = 0
    for candidate in candidates:
        if not candidate:
            continue
        width, height = rect_of(candidate)
        if width > 50 and height > 50:
            hwnd = candidate
            break
    if width <= 50 or height <= 50:
        print(f"  ! could not size the window for {path.name}")
        return

    hdc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hdc)
    bitmap = gdi32.CreateCompatibleBitmap(hdc, width, height)
    gdi32.SelectObject(mem_dc, bitmap)
    user32.PrintWindow(hwnd, mem_dc, 2)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth = width
    header.biHeight = -height
    header.biPlanes = 1
    header.biBitCount = 32
    header.biCompression = 0

    buffer = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(mem_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0)

    from PIL import Image

    image = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1)
    image.convert("RGB").save(path)
    print(f"saved {path.name} ({width}x{height})")

    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hdc)


def shoot(widget: tk.Widget, name: str) -> None:
    try:
        widget.deiconify()
    except tk.TclError:
        pass
    try:
        widget.winfo_toplevel().deiconify()
    except tk.TclError:
        pass
    widget.update_idletasks()
    widget.update()
    time.sleep(0.5)
    widget.update()
    hwnd = int(widget.winfo_id())
    parent = user32.GetParent(hwnd) or hwnd
    capture(parent, SHOTS / name)


def main() -> int:
    from gui.app import IrepsApp
    from gui.login_dialog import LoginDialog

    # ------------------------------------------------------------------
    # 1. the real login dialog, with a live captcha from the portal
    # ------------------------------------------------------------------
    root = tk.Tk()
    root.geometry("1240x800+40+40")
    client = IrepsClient(limiter=RateLimiter(1.0, 0.5), timeout=45)
    from core.auth import GuestAuth

    auth = GuestAuth(client, "9876543210", "91")
    dialog = LoginDialog(root, auth)
    dialog._load_captcha()
    shoot(dialog, "01_login_dialog.png")
    print("live captcha downloaded, answer:", auth.captcha.answer if auth.captcha else None)
    dialog.destroy()
    root.destroy()

    # ------------------------------------------------------------------
    # 2. the main window with results in it (synthetic data)
    # ------------------------------------------------------------------
    sys.path.insert(0, str(ROOT / "tests"))
    from test_gui_flow import install_fake_client  # noqa: E402

    root = tk.Tk()
    app = IrepsApp(root)
    install_fake_client(app.client)
    app.auth.is_authenticated = lambda: True  # type: ignore[method-assign]
    root.update()
    app._handle_options({
        "organisation": [type("O", (), {"label": "East Central Railway", "value": "8937"})()],
    })
    app.combos["organisation"].set("East Central Railway")
    app._show_results()
    deadline = time.time() + 20
    while app.worker and app.worker.is_alive() and time.time() < deadline:
        root.update()
        time.sleep(0.05)
    root.update()
    root.deiconify()
    root.geometry("1240x800+40+40")
    root.update()
    shoot(root, "02_results.png")

    # 3. the detail window
    app.results.tree.selection_set("0")
    app._open_detail()
    root.update()
    time.sleep(0.3)
    root.update()
    for child in root.winfo_children():
        if isinstance(child, tk.Toplevel):
            shoot(child, "03_detail_window.png")
            child.destroy()
    root.destroy()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
