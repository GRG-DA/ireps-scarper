"""Guest authentication for the IREPS portal.

The portal does not serve any tender data to an anonymous visitor, so a guest
login (mobile number + captcha + OTP) is mandatory. Three things make this
practical rather than painful:

* the captcha image is downloaded and **shown to the user, who types the
  answer** - it is solved by hand, on purpose;
* the hidden ``ver`` field still carries the server-issued value, because the
  portal's own JavaScript populates it that way and the server expects it;
* the OTP stays valid for the whole day, so the resulting session is cached
  to disk and reused.
"""

from __future__ import annotations

import base64
import pickle
import re
from dataclasses import dataclass

from .client import IrepsClient
from .config import (
    BASE_URL,
    CAPTCHA_PATH,
    GUEST_SEARCH_URL,
    SESSION_FILE,
)

TOKEN_RE = re.compile(r'name="org\.apache\.struts\.taglib\.html\.TOKEN" value="([^"]+)"')
FORM_ACTION_RE = re.compile(r'<form[^>]*action="([^"]+)"')


class LoginError(RuntimeError):
    """Raised when the portal refuses a login attempt."""


@dataclass
class Captcha:
    """A captcha challenge waiting for a human to read it."""

    image: bytes                    # PNG bytes
    answer: str                     # the server-issued value (hidden 'ver' field)
    audio: bytes | None = None      # optional WAV, for screen-reader users

    @property
    def size(self) -> int:
        return len(self.image)


class GuestAuth:
    """Drives the guest login handshake."""

    def __init__(self, client: IrepsClient, mobile: str = "", country_code: str = "91"):
        self.client = client
        self.mobile = mobile.strip()
        self.country_code = country_code
        self.captcha: Captcha | None = None
        self._login_action: str | None = None
        self._token: str | None = None
        self._action_mode: str = "srchPO"

    # -- step 1: open the guest page --------------------------------------
    def open_guest_page(self) -> str:
        """Load the guest page and remember the login action and session id."""
        response = self.client.get(GUEST_SEARCH_URL)
        html = response.text
        match = FORM_ACTION_RE.search(html)
        if not match:
            raise LoginError(
                "Could not find the login form on the IREPS page. "
                "The portal may have changed - check the page in a browser."
            )
        self._login_action = match.group(1)
        token = TOKEN_RE.search(html)
        self._token = token.group(1) if token else None
        action_mode = re.search(r'id="actionMode"[^>]*value="([^"]*)"', html)
        if action_mode:
            self._action_mode = action_mode.group(1)
        return html

    # -- step 2: fetch the captcha image ----------------------------------
    def fetch_captcha(self) -> Captcha:
        """Download a captcha image for the user to read.

        The answer is *not* auto-filled anywhere - it is returned to the user
        so they can type it. It is kept on the object only because the
        portal's hidden ``ver`` field must carry it.
        """
        response = self.client.post(
            BASE_URL + CAPTCHA_PATH,
            data={},
            headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json,*/*"},
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise LoginError("The captcha service returned an unexpected response.") from exc

        image_b64 = payload.get("imageCaptcha") or ""
        if not image_b64:
            raise LoginError("The captcha service returned no image.")
        audio_b64 = payload.get("audioCaptcha") or ""

        self.captcha = Captcha(
            image=base64.b64decode(image_b64),
            answer=payload.get("newcaptcha", ""),
            audio=base64.b64decode(audio_b64) if audio_b64 else None,
        )
        return self.captcha

    # -- step 3: ask for the OTP ------------------------------------------
    def request_otp(self, typed_answer: str) -> str:
        """Send the captcha answer and ask the portal to text an OTP.

        Returns one of: ``OK``, ``CAPTCHA_WRONG``, ``OTP_LIMIT``,
        ``BLOCKED``, ``BLOCKED_TEMP`` or ``ERROR``.
        """
        if self.captcha is None:
            raise LoginError("Fetch a captcha before requesting an OTP.")
        if not self.mobile:
            raise LoginError("A mobile number is required to receive the OTP.")
        if not typed_answer:
            return "CAPTCHA_WRONG"

        # Check the typed answer locally first. A typo would otherwise burn
        # one of the two OTP requests allowed per hour.
        if self.captcha.answer and typed_answer.strip().lower() != self.captcha.answer.strip().lower():
            return "CAPTCHA_WRONG"

        if not self._login_action:
            self.open_guest_page()

        payload = {
            "activity": "submitGetOTP",
            "mobileNo": self.mobile,
            "ccode": self.country_code,
            "number": typed_answer.strip(),
            "ver": self.captcha.answer,
        }
        response = self.client.post(
            BASE_URL + self._login_action,
            data=payload,
            headers={"X-Requested-With": "XMLHttpRequest", "Accept": "*/*"},
        )
        body = response.text.strip()
        if body.startswith("OK#"):
            return "OK"
        if "ERRORL#" in body:
            return "OTP_LIMIT"
        if "BLOCKEDTEMP#" in body:
            return "BLOCKED_TEMP"
        if "BLOCKED#" in body:
            return "BLOCKED"
        return "ERROR"

    # -- step 4: submit the OTP -------------------------------------------
    def submit_otp(self, otp: str) -> bool:
        """Complete the login. Returns True on success.

        The portal's own JavaScript submits the *whole* form
        (``document.forms[0].submit()``) for this step, not just the OTP, so
        the Struts TOKEN, the actionMode and the submit button's value all
        have to travel with it. Verified live on 11 Nov 2026: sending only
        the five login fields is rejected, sending the full form succeeds.
        """
        if self.captcha is None:
            raise LoginError("Fetch a captcha before submitting the OTP.")
        if not self._login_action:
            self.open_guest_page()

        payload = {
            "org.apache.struts.taglib.html.TOKEN": self._token or "",
            "activity": "submitOTP",
            "actionMode": self._action_mode,
            "mobileNo": self.mobile,
            "ccode": self.country_code,
            "number": self.captcha.answer,
            "ver": self.captcha.answer,
            "otp": otp.strip(),
            "imageField": "Proceed",
        }
        response = self.client.post(BASE_URL + self._login_action, data=payload)
        html = response.text
        if self.client.session_expired(html):
            raise LoginError("The session was rejected. Check the OTP and try again.")
        if self.client.looks_like_login_page(html):
            raise LoginError(
                "The portal did not accept the OTP"
                + (f": {self._error_text(html)}" if self._error_text(html) else ".")
            )
        return True

    @staticmethod
    def _error_text(html: str) -> str:
        """Pull the portal's own error message out of the page, if there is one."""
        import re

        for pattern in (
            r'<font[^>]*color="red"[^>]*>([^<]{3,200})</font>',
            r'<div[^>]*class="[^"]*text-center[^"]*"[^>]*>(.*?)</div>',
            r"Error\s*Code\s*:\s*([A-Z0-9.]+)",
        ):
            match = re.search(pattern, html, re.I | re.S)
            if match:
                text = re.sub(r"<[^>]+>", " ", match.group(1))
                text = re.sub(r"\s+", " ", text).strip()
                if text:
                    return text
        return ""

    # -- session persistence ----------------------------------------------
    def save_session(self) -> None:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        with SESSION_FILE.open("wb") as handle:
            pickle.dump(
                {
                    "cookies": self.client.session.cookies.get_dict(),
                    "mobile": self.mobile,
                    "country_code": self.country_code,
                },
                handle,
            )

    def load_session(self) -> bool:
        """Restore a cached session. Returns False when there is none."""
        if not SESSION_FILE.exists():
            return False
        try:
            with SESSION_FILE.open("rb") as handle:
                data = pickle.load(handle)
        except (OSError, pickle.UnpicklingError, EOFError):
            return False
        cookies = data.get("cookies") or {}
        if not cookies:
            return False
        self.client.session.cookies.update(cookies)
        self.mobile = data.get("mobile") or self.mobile
        self.country_code = data.get("country_code") or self.country_code
        return True

    def is_authenticated(self) -> bool:
        """True when the cached session still gives us the search page."""
        from .config import PO_SEARCH_URL

        try:
            response = self.client.get(PO_SEARCH_URL)
        except Exception:
            return False
        html = response.text
        if self.client.session_expired(html):
            return False
        if self.client.looks_like_login_page(html):
            return False
        return "Show Results" in html or "poValueFrom" in html
