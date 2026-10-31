"""Read the local bridge; no cloud calls, credentials or control commands."""
import time
from aiohttp import ClientError, ClientTimeout
from .device_protocol import from_bridge
from .polling import display_flags

BRIDGE_URL = "http://127.0.0.1:8642/api/status"
MAX_AGE = 10


async def read_bridge(session, machine_uuid):
    device_id = machine_uuid.split(".")[0]
    try:
        async with session.get(BRIDGE_URL, params={"device": device_id}, timeout=ClientTimeout(total=1)) as response:
            if response.status != 200:
                return None
            status = await response.json()
        # Use HA host time, not a possibly stale cached API 'now' value.
        status["now"] = time.time()
        data = from_bridge(status, device_id, MAX_AGE)
        if not data or data.get("device_uuid", "").lower() != device_id.lower():
            return None
        device = next(d for d in status["devices"] if d["device_id"].lower() == device_id.lower())
        age = status["now"] - float(device["bm_stat_received"])
        if not 0 <= age <= MAX_AGE:
            return None
        fields = device["bm_stat"].split(";")[3].split("X")
        # Preserve the fork's bool/unknown alarm contract and fast hop flags.
        data["alarm_type"] = data.get("alarm")
        data.update(display_flags(fields))
        data.update(connection_status="online", data_source="bridge", bridge_age=age, payment_required=False)
        code = data.get("state_code")
        data["device_mode"] = "manual" if code in (4006, 4007) else "automatic" if data.get("process_status") == "running" else "waiting"
        # Detailed localized display texts are a separate follow-up change.
        data["current_step"] = f"Statuscode {code}" if code is not None else None
        return data
    except (ClientError, TimeoutError, ValueError, TypeError, KeyError, IndexError, AttributeError, StopIteration, OverflowError):
        return None
