"""Config flow for Bidet WC integration."""
import logging
from typing import Any

import voluptuous as vol
from bleak.backends.device import BLEDevice
from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, SERVICE_UUID, PAIRING_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class BidetConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bidet WC."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_devices: dict[str, BLEDevice] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle the bluetooth discovery step."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        for service_info in discovery_info.advertisement.service_uuids:
            if service_info.lower() == SERVICE_UUID.lower():
                return await self.async_step_bluetooth_confirm(discovery_info)
        return self.async_abort(reason="not_supported")

    async def async_step_bluetooth_confirm(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Confirm discovery."""
        device = discovery_info.device
        name = device.name or discovery_info.address
        
        return self.async_create_entry(
            title=name,
            data={
                CONF_NAME: name,
                CONF_ADDRESS: discovery_info.address,
            },
        )

    async def async_step_pairing(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the pairing step to prepare the bidet for connection."""
        if user_input is not None:
            # L'utilisateur a confirmé que l'appareil est en mode appairage
            return await self.async_step_user()
            
        return self.async_show_form(
            step_id="pairing",
            description_placeholders={
                "timeout": str(PAIRING_TIMEOUT)
            },
        )
    
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the user step to pick discovered device."""
        # Si l'utilisateur n'a pas encore fourni d'input, rediriger vers l'étape d'appairage
        if not user_input:
            return await self.async_step_pairing()
            
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data=user_input,
            )

        current_addresses = self._async_current_ids()
        for discovery_info in async_discovered_service_info(self.hass):
            address = discovery_info.address
            if address in current_addresses or address in self._discovered_devices:
                continue

            for service_info in discovery_info.advertisement.service_uuids:
                if service_info.lower() == SERVICE_UUID.lower():
                    device = discovery_info.device
                    self._discovered_devices[address] = device

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS): vol.In(
                    {
                        address: f"{device.name} ({address})"
                        for address, device in self._discovered_devices.items()
                    }
                ),
                vol.Required(CONF_NAME): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
        )
