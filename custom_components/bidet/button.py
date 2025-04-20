"""Support pour le bouton de chasse d'eau du bidet."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BidetCoordinator
from .const import DOMAIN, CMD_FLUSH, VAL_FLUSH_ON

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configurer l'entité button basée sur une entrée de configuration."""
    coordinator: BidetCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    # Ajouter l'entité bouton pour la chasse d'eau
    async_add_entities([BidetFlushButton(coordinator, entry)])


class BidetFlushButton(ButtonEntity):
    """Représentation d'un bouton pour la chasse d'eau du bidet."""

    _attr_has_entity_name = True
    _attr_name = "Chasse d'eau"
    _attr_icon = "mdi:toilet"
    
    def __init__(self, coordinator: BidetCoordinator, entry: ConfigEntry) -> None:
        """Initialiser le bouton."""
        self.coordinator = coordinator
        self._entry = entry
        
        # L'ID unique de l'entité
        self._attr_unique_id = f"{entry.entry_id}_flush"
        
        # Information sur le dispositif
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Wings/Jitian",
            model="Top Toilet WC",
        )
        
        # Enregistre un callback pour la déconnexion
        coordinator.add_disconnect_callback(self._handle_disconnect)
    
    async def async_press(self) -> None:
        """Gérer l'appui sur le bouton."""
        _LOGGER.info("👆 Bouton de chasse d'eau pressé - envoi de la commande %s:%s", CMD_FLUSH, VAL_FLUSH_ON)
        try:
            result = await self.coordinator.send_command(CMD_FLUSH, VAL_FLUSH_ON)
            _LOGGER.info("👆 Résultat de l'envoi de commande: %s", "Succès" if result else "Échec")
        except Exception as err:
            _LOGGER.error("👆 Erreur lors de l'envoi de la commande: %s", err)
    
    def _handle_disconnect(self) -> None:
        """Gérer la déconnexion du bidet."""
        self._attr_available = False
        self.async_write_ha_state()
    
    async def async_added_to_hass(self) -> None:
        """Exécuté lors de l'ajout de l'entité à Home Assistant."""
        self._attr_available = self.coordinator.connected
    
    async def async_will_remove_from_hass(self) -> None:
        """Exécuté lorsque l'entité est supprimée de Home Assistant."""
        self.coordinator.remove_disconnect_callback(self._handle_disconnect)
