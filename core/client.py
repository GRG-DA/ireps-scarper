"""HTTP client with a shared rate limiter.

Every request to the portal goes through :class:`IrepsClient` so the rate
limiter can never be bypassed by accident. The portal is a legacy Struts app
that reacts badly to aggressive traffic - a 3-5 second gap between requests
keeps the IP out of trouble.
"""

from __future__ import annotations

import random
import time

import requests


class SessionExpired(RuntimeError):
    """Raised when the portal answers with ADM.004 (session expired)."""


class RateLimiter:
    """Sleeps so that consecutive requests are at least ``min_interval`` apart."""

    def __init__(self, min_interval: float = 3.0, jitter: float = 1.5):
        self.min_interval = float(min_interval)
        self.jitter = float(jitter)
        self._last_call = 0.0

    def wait(self) -> float:
        target = self._last_call + self.min_interval + random.uniform(0, self.jitter)
        now = time.monotonic()
        if now < target:
            time.sleep(target - now)
        self._last_call = time.monotonic()
        return self._last_call - now


class IrepsClient:
    """A ``requests.Session`` with the portal's headers and a rate limiter."""

    #: How many times a request is tried before the error is passed on.
    attempts = 3

    def __init__(
        self,
        session: requests.Session | None = None,
        limiter: RateLimiter | None = None,
        timeout: int = 45,
        base_referer: str = "https://www.ireps.gov.in/ireps.html",
    ):
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": base_referer,
                "Upgrade-Insecure-Requests": "1",
            }
        )
        self.limiter = limiter or RateLimiter()
        self.timeout = timeout

    # -- low level ---------------------------------------------------------
    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Send a request, retrying when the portal drops the connection.

        The portal is a legacy Struts app and it does close the connection
        without an answer now and then - a plain retry gets the page. The
        rate limiter spaces the attempts out, so this does not turn into
        traffic the portal would object to.
        """
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("allow_redirects", True)
        last_error: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            self.limiter.wait()
            try:
                return self.session.request(method, url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                if attempt >= self.attempts:
                    break
                time.sleep(2.0 * attempt)
        raise last_error if last_error else RuntimeError("The request failed.")

    def get(self, url: str, **kwargs) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        return self.request("POST", url, **kwargs)

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def looks_like_login_page(html: str) -> bool:
        """True when the response is the guest login form."""
        return "guestLogonForm" in html

    @staticmethod
    def session_expired(html: str) -> bool:
        """True when the portal says the session is gone."""
        return "ADM.004" in html or "Your session has expired" in html

    def ensure_alive(self, html: str) -> None:
        if self.session_expired(html):
            raise SessionExpired("The IREPS session has expired - log in again.")
