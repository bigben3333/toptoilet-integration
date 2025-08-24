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

from .const import DOMAIN, SERVICE_UUID, OLD_SERVICE_UUID

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

        # Accepter uniquement les appareils exposant nos services (FFF0 nouveaux, FFE0 anciens)
        service_uuids = {u.lower() for u in (discovery_info.service_uuids or [])}
        if SERVICE_UUID.lower() not in service_uuids and OLD_SERVICE_UUID.lower() not in service_uuids:
            return self.async_abort(reason="not_supported")

        device = discovery_info.device
        name = device.name or discovery_info.address
        return self.async_create_entry(
            title=name,
            data={
                CONF_NAME: name,
                CONF_ADDRESS: discovery_info.address,
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the user step to pick discovered device."""
        # Si l'utilisateur a déjà fourni des données (sélectionné un appareil)
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data=user_input,
            )

        # Découvrir les appareils
        self._discovered_devices = {}
        current_addresses = self._async_current_ids()
        for discovery_info in async_discovered_service_info(self.hass):
            address = discovery_info.address
            if address in current_addresses:
                continue

            # Filtrer sur les UUIDs de service attendus (FFF0 nouveaux, FFE0 anciens)
            service_uuids = {u.lower() for u in (discovery_info.service_uuids or [])}
            if SERVICE_UUID.lower() not in service_uuids and OLD_SERVICE_UUID.lower() not in service_uuids:
                continue

            device = discovery_info.device
            self._discovered_devices[address] = device

        # Si aucun appareil n'est trouvé
        if not self._discovered_devices:
            # Afficher les instructions de redémarrage dans le message d'erreur
            return self.async_abort(
                reason="no_devices_found",
                description_placeholders={
                    "instructions": "Redémarrez votre toilette (coupez l'alimentation et rallumez). "
                                   "Assurez-vous que votre toilette est à portée du serveur Home Assistant."
                }
            )

        # Créer un formulaire avec la liste des appareils détectés
        data_schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS): vol.In(
                    {
                        address: f"{device.name or 'Unknown'} ({address})"
                        for address, device in self._discovered_devices.items()
                    }
                ),
                vol.Required(CONF_NAME, default="Bidet WC"): str,
            }
        )
        
        # Afficher le formulaire
        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            description_placeholders={
                "instructions": "Pour assurer une bonne détection, redémarrez votre toilette "
                               "(coupez l'alimentation et rallumez)."
            }
        )
