"""Conservative RTC offset monitoring; no device writes or network requests."""

import re
from datetime import datetime
from typing import Any

MAX_SAMPLE_AGE = 120  # seconds without an advancing device timestamp
WARNING_AFTER = 180  # seconds of continuous, fresh abnormal observations
WARNING_MINUTES = 5
UNCERTAINTY_MINUTES = 1  # HH:MM quantization and ordinary transport delay


class RTCMonitor:
    """Compare local clock faces, using monotonic time for freshness/persistence.

    The device epoch is an identity/progression signal, never a trusted host
    timestamp. First samples and discontinuities establish a baseline only.
    Cloud data that advances can still be delayed by the server: this is an
    approximate diagnostic, not a synchronization or connectivity guarantee.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Forget evidence after loss of data or source/timezone changes."""
        self._stamp: int | None = None
        self._seen: float | None = None
        self._wall: float | None = None
        self._context: tuple | None = None
        self._offset: int | None = None
        self._abnormal_since: float | None = None
        self._abnormal_samples = 0
        self._warning: bool | None = None

    def observe(self, data: dict[str, Any], now: datetime, monotonic: float) -> dict[str, Any]:
        """Return signed offset in minutes and sustained-warning state, or unknown."""
        unknown = {"rtc_offset": None, "rtc_warning": None}
        stamp, clock = data.get("device_timestamp"), data.get("time_display")
        if (data.get("connection_status") != "online" or type(stamp) is not int or stamp <= 0
                or not isinstance(clock, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", clock)):
            self.reset()
            return unknown
        context = (data.get("data_source"), str(now.tzinfo), now.utcoffset())
        if context != self._context:
            self.reset()
            self._context = context
        elapsed = monotonic - self._seen if self._seen is not None else None
        # Host clock corrections (including manual changes) invalidate evidence.
        host_jump = elapsed is not None and abs((now.timestamp() - self._wall) - elapsed) > 5
        expired = elapsed is not None and (elapsed < 0 or elapsed >= MAX_SAMPLE_AGE)
        if expired or host_jump:
            self._offset = self._warning = self._abnormal_since = None
            self._abnormal_samples = 0
        if stamp == self._stamp:
            # Never re-age a cached response or recompute its offset at fetch time.
            return {"rtc_offset": self._offset, "rtc_warning": self._warning}
        discontinuity = (self._stamp is None or expired or host_jump
                         or stamp <= self._stamp or abs((stamp - self._stamp) - elapsed) > 90)
        self._stamp, self._seen, self._wall = stamp, monotonic, now.timestamp()
        if discontinuity:
            self._offset = self._warning = self._abnormal_since = None
            self._abnormal_samples = 0
            return unknown
        hour, minute = map(int, clock.split(":"))
        # Shortest signed distance across midnight; date errors cannot be inferred.
        self._offset = ((hour * 60 + minute - (now.hour * 60 + now.minute) + 720) % 1440) - 720
        abnormal = abs(self._offset) - UNCERTAINTY_MINUTES >= WARNING_MINUTES
        if abnormal:
            if self._abnormal_since is None:
                self._abnormal_since = monotonic
            self._abnormal_samples += 1
            self._warning = self._abnormal_samples >= 3 and monotonic - self._abnormal_since >= WARNING_AFTER
        else:
            self._abnormal_since = None
            self._abnormal_samples = 0
            self._warning = False
        return {"rtc_offset": self._offset, "rtc_warning": self._warning}
