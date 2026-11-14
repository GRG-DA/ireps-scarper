"""The HTTP client's retry behaviour.

The portal closes the connection and times out now and then, so a request
that fails for those reasons has to be tried again rather than ending the
run.

    python tests/test_client.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from core.client import IrepsClient, RateLimiter, SessionExpired  # noqa: E402


class FakeResponse:
    def __init__(self, text: str = "ok", status_code: int = 200):
        self.text = text
        self.status_code = status_code


class FlakySession:
    """A session that fails the first ``failures`` times it is used."""

    def __init__(self, failures: int, error: Exception):
        self.failures = failures
        self.error = error
        self.calls = 0
        self.headers = {}

    def request(self, method, url, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return FakeResponse()


def main() -> int:
    for error in (requests.ConnectionError("connection reset"),
                  requests.Timeout("timed out")):
        session = FlakySession(failures=2, error=error)
        client = IrepsClient(session=session, limiter=RateLimiter(0, 0))
        response = client.get("https://www.ireps.gov.in/epsn/anonymSearch.do")
        assert session.calls == 3, (
            f"{type(error).__name__} should be retried twice, saw {session.calls} calls")
        assert response.text == "ok"
        print(f"  {type(error).__name__:18s} retried -> {session.calls} calls, answer ok")

    # a failure that never goes away is passed on, not swallowed
    session = FlakySession(failures=99, error=requests.ConnectionError("down"))
    client = IrepsClient(session=session, limiter=RateLimiter(0, 0))
    try:
        client.get("https://www.ireps.gov.in/epsn/anonymSearch.do")
    except requests.ConnectionError:
        print("  a permanent failure is passed on")
    else:
        raise AssertionError("a permanent failure must not be swallowed")

    # the client still notices an expired session
    client = IrepsClient(session=FlakySession(0, RuntimeError()), limiter=RateLimiter(0, 0))
    try:
        client.ensure_alive("<html>ADM.004 - session expired</html>")
    except SessionExpired:
        print("  an expired session is still noticed")
    else:
        raise AssertionError("ensure_alive must raise on ADM.004")

    print("\nCLIENT TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
