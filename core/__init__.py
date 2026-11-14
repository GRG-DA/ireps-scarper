"""UI-agnostic scraping engine for the IREPS portal.

Nothing in this package may import from ``gui`` or ``excel`` - the GUI and the
CLI are both thin front-ends over this core.
"""

from .config import Settings
from .client import IrepsClient, RateLimiter
from .auth import GuestAuth, Captcha, LoginError
from .engine import ScrapeEngine, SearchCriteria

__all__ = [
    "Settings",
    "IrepsClient",
    "RateLimiter",
    "GuestAuth",
    "Captcha",
    "LoginError",
    "ScrapeEngine",
    "SearchCriteria",
]
