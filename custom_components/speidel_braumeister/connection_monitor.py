"""Passive device heartbeat evidence; never sends requests or control commands."""

from math import isfinite
from typing import Any

TIMEOUT_SECONDS = 120


class ConnectionMonitor:
    """Expire advancing device samples using host monotonic time.

    Two advancing samples establish evidence. Cached polls, source switches,
    missing timestamps and clock regressions cannot clear an existing warning.
    """

    def __init__(self) -> None:
        self._stamp: float | None = None
        self._source: str | None = None
        self._last_seen: float | None = None
        self._started: float | None = None
        self._verified = False
        self._activity: dict[str, Any] = {}

    def observe(self, data: dict[str, Any], monotonic: float) -> None:
        """Consider only successful, online bridge/XHR samples."""
        if self._started is None:
            self._started = monotonic
        stamp = data.get("device_timestamp")
        source = data.get("data_source")
        if (data.get("connection_status") != "online"
                or source not in ("bridge", "xhr")
                or isinstance(stamp, bool) or not isinstance(stamp, (int, float))
                or not isfinite(stamp) or stamp <= 0):
            return
        if source != self._source or self._stamp is None or stamp < self._stamp:
            self._source, self._stamp = source, stamp
            # New baseline only: neither refresh nor clear an existing alarm.
            if self._last_seen is None:
                self._remember(data)
            return
        if stamp > self._stamp:
            self._stamp = stamp
            self._last_seen = monotonic
            self._verified = True
            self._remember(data)

    def _remember(self, data: dict[str, Any]) -> None:
        # Incomplete telemetry must not turn a previously known hazard into off.
        process = data.get("process_status")
        if process in ("running", "idle", "finished"):
            self._activity["last_known_brewing"] = process == "running"
        enabled = data.get("heater_enabled")
        if isinstance(enabled, bool):
            self._activity["last_known_heater_enabled"] = enabled
        for key in ("heating", "pump"):
            if data.get(key) in ("on", "off"):
                self._activity[f"last_known_{key}"] = data[key]
        if isinstance(data.get("state_code"), int):
            self._activity["last_known_state_code"] = data["state_code"]

    def snapshot(self, monotonic: float) -> dict[str, Any]:
        """Unknown at startup; expired after timeout even if polling hangs."""
        anchor = self._last_seen if self._last_seen is not None else self._started
        age = max(0, monotonic - anchor) if anchor is not None else None
        lost = age is not None and age >= TIMEOUT_SECONDS
        warning = True if lost else (False if self._verified else None)
        risk = (self._activity.get("last_known_brewing") is True
                or self._activity.get("last_known_heater_enabled") is True
                or self._activity.get("last_known_heating") == "on")
        return {
            "warning": warning,
            "age_seconds": round(age, 1) if age is not None else None,
            "timeout_seconds": TIMEOUT_SECONDS,
            "evidence": "advancing_device_timestamp" if self._verified else "unconfirmed",
            "source": self._source,
            "last_device_timestamp": self._stamp,
            "activity_at_risk": bool(lost and risk),
            **self._activity,
        }
