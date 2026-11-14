"""The login dialog: mobile number, captcha image, typed answer, OTP.

The captcha is solved by hand. The image is downloaded from the portal and
shown here at a readable size; the user types the characters they can see.
"""

from __future__ import annotations

import io
import tkinter as tk
from tkinter import messagebox, ttk

from core.auth import GuestAuth, LoginError
from core.config import COUNTRY_CODES

BG = "#ffffff"
ACCENT = "#0E7C86"
TEXT = "#20303a"
MUTED = "#6b7c88"


class LoginDialog(tk.Toplevel):
    """Modal guest-login flow.

    Step 1 - mobile number.
    Step 2 - captcha image, typed by the user, then "Send OTP".
    Step 3 - the OTP from the SMS, then "Sign in".
    """

    def __init__(self, parent: tk.Widget, auth: GuestAuth):
        super().__init__(parent)
        self.auth = auth
        self.result = False
        self._otp_sent = False

        self.title("IREPS - Sign in")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.mobile_var = tk.StringVar(value=auth.mobile or "")
        self.code_var = tk.StringVar(value=list(COUNTRY_CODES)[0])
        self.captcha_var = tk.StringVar()
        self.otp_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Enter your mobile number to begin.")
        self.captcha_image = None

        self._build()
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.mobile_entry.focus_set()
        self.bind("<Return>", lambda _event: self._primary())

    # -- layout ------------------------------------------------------------
    def _build(self) -> None:
        outer = ttk.Frame(self, padding=18)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Sign in to IREPS",
                  font=("Segoe UI", 14, "bold"), foreground=TEXT).pack(anchor="w")
        ttk.Label(
            outer,
            text=("The portal only serves tender data to a signed-in guest. "
                  "An OTP is sent to your mobile - the code is valid for the whole day."),
            font=("Segoe UI", 9), foreground=MUTED, wraplength=430, justify="left",
        ).pack(anchor="w", pady=(4, 14))

        # --- step 1: mobile ------------------------------------------------
        mobile_frame = ttk.LabelFrame(outer, text="1. Mobile number", padding=10)
        mobile_frame.pack(fill="x")
        row = ttk.Frame(mobile_frame)
        row.pack(fill="x")
        ttk.Combobox(row, textvariable=self.code_var, values=list(COUNTRY_CODES),
                     state="readonly", width=12).pack(side="left")
        self.mobile_entry = ttk.Entry(row, textvariable=self.mobile_var, width=22)
        self.mobile_entry.pack(side="left", padx=(8, 0))
        self.continue_button = ttk.Button(row, text="Continue", command=self._load_captcha)
        self.continue_button.pack(side="left", padx=(8, 0))

        # --- step 2: captcha ----------------------------------------------
        self.captcha_frame = ttk.LabelFrame(outer, text="2. Verification code (type what you see)", padding=10)
        self.captcha_frame.pack(fill="x", pady=(10, 0))

        image_holder = ttk.Frame(self.captcha_frame)
        image_holder.pack(fill="x", pady=(0, 6))
        self.image_label = ttk.Label(image_holder, text="", anchor="center")
        self.image_label.pack()
        self.refresh_button = ttk.Button(image_holder, text="Refresh", command=self._load_captcha, width=9)
        self.refresh_button.pack(pady=(4, 0))

        answer_row = ttk.Frame(self.captcha_frame)
        answer_row.pack(fill="x")
        self.captcha_entry = ttk.Entry(answer_row, textvariable=self.captcha_var, width=22,
                                       font=("Consolas", 12))
        self.captcha_entry.pack(side="left")
        self.send_otp_button = ttk.Button(answer_row, text="Send OTP", command=self._send_otp)
        self.send_otp_button.pack(side="left", padx=(8, 0))

        # --- step 3: OTP ---------------------------------------------------
        self.otp_frame = ttk.LabelFrame(outer, text="3. OTP from the SMS", padding=10)
        self.otp_frame.pack(fill="x", pady=(10, 0))
        otp_row = ttk.Frame(self.otp_frame)
        otp_row.pack(fill="x")
        self.otp_entry = ttk.Entry(otp_row, textvariable=self.otp_var, width=22,
                                   font=("Consolas", 12))
        self.otp_entry.pack(side="left")
        self.signin_button = ttk.Button(otp_row, text="Sign in", command=self._sign_in)
        self.signin_button.pack(side="left", padx=(8, 0))

        # --- footer --------------------------------------------------------
        footer = ttk.Frame(outer)
        footer.pack(fill="x", side="bottom", pady=(14, 0))
        self.footer = footer
        ttk.Label(footer, textvariable=self.status_var, font=("Segoe UI", 9),
                  foreground=MUTED, wraplength=430, justify="left").pack(side="left")
        ttk.Button(footer, text="Close", command=self.destroy).pack(side="right")

        self._set_step(1)

    def _set_step(self, step: int) -> None:
        """Show the steps up to ``step``; the footer always stays at the bottom."""
        self.captcha_frame.pack_forget()
        self.otp_frame.pack_forget()
        if step >= 2:
            self.captcha_frame.pack(fill="x", pady=(10, 0), before=self.footer)
        if step >= 3:
            self.otp_frame.pack(fill="x", pady=(10, 0), before=self.footer)

    def _busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for widget in (self.send_otp_button, self.signin_button, self.refresh_button,
                       self.continue_button):
            widget.configure(state=state)

    # -- actions -----------------------------------------------------------
    def _load_captcha(self) -> None:
        self._busy(True)
        self.status_var.set("Downloading the verification code...")
        self.update_idletasks()
        try:
            captcha = self.auth.fetch_captcha()
        except LoginError as exc:
            self._busy(False)
            self.status_var.set(str(exc))
            messagebox.showerror("IREPS", str(exc), parent=self)
            return
        except Exception as exc:  # noqa: BLE001
            self._busy(False)
            self.status_var.set("Could not reach the portal.")
            messagebox.showerror("IREPS", repr(exc), parent=self)
            return

        try:
            from PIL import Image, ImageTk  # optional, for crisp scaling
            image = Image.open(io.BytesIO(captcha.image)).resize((240, 70))
            self.captcha_image = ImageTk.PhotoImage(image)
        except Exception:
            self.captcha_image = tk.PhotoImage(data=captcha.image)
        self.image_label.configure(image=self.captcha_image)
        self.captcha_var.set("")
        self._busy(False)
        # Move the dialog on to the verification step so the image is visible.
        self._set_step(2)
        self.status_var.set("Type the characters in the image, then press Send OTP.")
        self.captcha_entry.focus_set()

    def _send_otp(self) -> None:
        answer = self.captcha_var.get().strip()
        if not answer:
            self.status_var.set("Type the verification code from the image first.")
            return
        if not self.mobile_var.get().strip():
            self.status_var.set("Enter your mobile number first.")
            return

        self.auth.mobile = self.mobile_var.get().strip()
        self.auth.country_code = COUNTRY_CODES.get(self.code_var.get(), "91")

        self._busy(True)
        self.status_var.set("Sending the OTP...")
        self.update_idletasks()
        try:
            outcome = self.auth.request_otp(answer)
        except LoginError as exc:
            self._busy(False)
            self.status_var.set(str(exc))
            messagebox.showerror("IREPS", str(exc), parent=self)
            return
        except Exception as exc:  # noqa: BLE001
            self._busy(False)
            self.status_var.set("Could not reach the portal.")
            messagebox.showerror("IREPS", repr(exc), parent=self)
            return

        self._busy(False)
        if outcome == "OK":
            self._otp_sent = True
            self._set_step(3)
            self.status_var.set("OTP sent. Enter the code from the SMS.")
            self.otp_var.set("")
            self.otp_entry.focus_set()
            return

        messages = {
            "CAPTCHA_WRONG": "That verification code does not match the image. A fresh code has been loaded - try again.",
            "OTP_LIMIT": "You have requested too many OTPs. Only two are allowed per hour - wait, or sign in from a browser and import the cookies.",
            "BLOCKED": "The portal has blocked this mobile number. Contact the IREPS help desk.",
            "BLOCKED_TEMP": "Too many wrong OTP attempts for today. Try again tomorrow.",
            "ERROR": "The portal rejected the request. Check the mobile number and try again.",
        }
        message = messages.get(outcome, "The portal rejected the request.")
        self.status_var.set(message)
        if outcome == "CAPTCHA_WRONG":
            self._load_captcha()
        else:
            messagebox.showwarning("IREPS", message, parent=self)

    def _sign_in(self) -> None:
        otp = self.otp_var.get().strip()
        if len(otp) != 6 or not otp.isdigit():
            self.status_var.set("The OTP is six digits.")
            return
        self._busy(True)
        self.status_var.set("Signing in...")
        self.update_idletasks()
        try:
            ok = self.auth.submit_otp(otp)
        except LoginError as exc:
            self._busy(False)
            self.status_var.set(str(exc))
            messagebox.showerror("IREPS", str(exc), parent=self)
            return
        except Exception as exc:  # noqa: BLE001
            self._busy(False)
            self.status_var.set("Could not reach the portal.")
            messagebox.showerror("IREPS", repr(exc), parent=self)
            return
        self._busy(False)
        if ok:
            self.result = True
            self.status_var.set("Signed in.")
            self.destroy()
        else:
            self.status_var.set("That OTP was not accepted. Try again.")
            messagebox.showwarning("IREPS", "That OTP was not accepted.", parent=self)

    def _primary(self) -> None:
        if not self._otp_sent:
            if self.captcha_frame.winfo_ismapped():
                self._send_otp()
            else:
                self._load_captcha()
        else:
            self._sign_in()
