"""Actions of the Speidel Braumeister integration.

upload_recipes replaces all recipes on the Braumeister through the Braumeister Bridge
app (option recipe_write_enabled). The recipes use the same shape as the "recipes"
attribute of the device-recipes sensor, so a list can be copied, edited and written back.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from aiohttp import ClientError, ClientTimeout

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import BRIDGE_RECIPES_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_UPLOAD_RECIPES = "upload_recipes"
ATTR_RECIPES = "recipes"
ATTR_CONFIG_ENTRY = "config_entry_id"
POLL_INTERVAL = 2
UPLOAD_TIMEOUT = 180  # the Bridge gives up after 30 s + 10 s per step

SCHEMA = vol.Schema({
    vol.Required(ATTR_RECIPES): vol.All(cv.ensure_list, [dict]),
    vol.Optional(ATTR_CONFIG_ENTRY): cv.string,
})


def _coordinator(hass: HomeAssistant, entry_id: str | None):
    coordinators = {
        key: value for key, value in hass.data.get(DOMAIN, {}).items()
        if hasattr(value, "async_request_refresh")
    }
    if entry_id:
        if entry_id not in coordinators:
            raise ServiceValidationError(f"No loaded Speidel Braumeister entry {entry_id}")
        return coordinators[entry_id]
    if len(coordinators) != 1:
        raise ServiceValidationError("Choose the Braumeister (config_entry_id)")
    return next(iter(coordinators.values()))


async def _upload_recipes(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    coordinator = _coordinator(hass, call.data.get(ATTR_CONFIG_ENTRY))
    device_id = coordinator._machine_uuid.split(".")[0]
    session = async_get_clientsession(hass)
    try:
        async with session.post(
            BRIDGE_RECIPES_URL, json={"device_id": device_id, "recipes": call.data[ATTR_RECIPES]},
            timeout=ClientTimeout(total=5),
        ) as response:
            text = await response.text()
            if response.status == 400:
                raise ServiceValidationError(text)
            if response.status != 202:
                raise HomeAssistantError(f"Braumeister Bridge: {text} (HTTP {response.status})")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + UPLOAD_TIMEOUT
        while True:
            await asyncio.sleep(POLL_INTERVAL)
            async with session.get(BRIDGE_RECIPES_URL, timeout=ClientTimeout(total=5)) as response:
                status: dict[str, Any] = await response.json()
            if status.get("result") not in ("queued", "sending") or loop.time() > deadline:
                break
    except (ClientError, asyncio.TimeoutError) as err:
        raise HomeAssistantError(f"Braumeister Bridge not reachable: {err}") from err
    await coordinator.async_request_refresh()
    if status.get("result") != "confirmed":
        raise HomeAssistantError(
            f"Recipe upload {status.get('result', 'unknown')}: {status.get('written', 0)} of "
            f"{status.get('recipes', '?')} recipes written. The device may now hold only these; upload again."
        )
    _LOGGER.info("Uploaded %s recipes to the Braumeister", status.get("recipes"))
    return {"result": status["result"], "recipes": status.get("recipes")}


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions (once, not per config entry)."""

    async def handle(call: ServiceCall) -> ServiceResponse:
        return await _upload_recipes(hass, call)

    hass.services.async_register(
        DOMAIN, SERVICE_UPLOAD_RECIPES, handle, schema=SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
