"""HTTP retry policy, independent of Home Assistant and credentials."""
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import monotonic

from aiohttp import ClientError

_LOGGER = logging.getLogger(__name__)


def _endpoint(args):
    """URL path without the last segment, which may hold a device ID."""
    url = str(args[0]) if args else ""
    path = url.split("://", 1)[-1].partition("/")[2].split("?", 1)[0]
    return "/" + path.rsplit("/", 1)[0] if "/" in path else "/" + path


class PollingError(Exception):
    """Stop this refresh; never try another endpoint on transport/server errors."""


class RetryLater(PollingError):
    """An absolute monotonic deadline, not a duration extended on each attempt."""

    def __init__(self, deadline):
        self.deadline = deadline
        super().__init__("MySpeidel requested a polling pause")


def retry_after_seconds(value, now=None):
    """Accept HTTP delay-seconds or HTTP-date; invalid values use local backoff."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.isascii() and value.isdigit():
        try:
            return float(int(value))
        except (ValueError, OverflowError):
            return None
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            return None
        return max(0.0, (date - (now or datetime.now(timezone.utc))).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def error_delay(base, failures):
    """30, 60, 120, 240, 300 by default; respect longer configured bases."""
    return min(max(300, base), base * 2 ** min(max(0, failures - 1), 16))


class RequestPolicy:
    """Guard every HTTP request, including login and metadata requests."""

    def __init__(self):
        self.not_before = 0.0
        self.failures = 0

    @asynccontextmanager
    async def request(self, method, *args, **kwargs):
        if monotonic() < self.not_before:
            raise RetryLater(self.not_before)
        try:
            async with method(*args, **kwargs) as response:
                status = response.status
                if status == 429 or 500 <= status < 600:
                    delay = retry_after_seconds(getattr(response, "headers", {}).get("Retry-After"))
                    # Even without a usable header, stop fallback/re-login loops.
                    self.failures += 1
                    pause = max(error_delay(30, self.failures), delay or 0)
                    self.not_before = monotonic() + pause
                    _LOGGER.warning("MySpeidel answered HTTP %s for %s, pausing requests for %.0f s",
                                    status, _endpoint(args), pause)
                    raise RetryLater(self.not_before)
                self.failures = 0
                yield response
        except (ClientError, TimeoutError) as err:
            # A transport failure is not a server request to slow down. Stop
            # this refresh, but let the next normal polling tick try again.
            raise PollingError("MySpeidel transport request failed") from err
