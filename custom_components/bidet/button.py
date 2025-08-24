"""Support pour le bouton de chasse d'eau du bidet."""
from __future__ import annotations

import logging
import binascii

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BidetCoordinator
from .const import DOMAIN, CMD_FLUSH, VAL_FLUSH_ON, OLD_CHARACTERISTIC_UUID

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configurer l'entité button basée sur une entrée de configuration."""
    coordinator: BidetCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    # Ajouter l'entité bouton pour la chasse d'eau
    async_add_entities([
        BidetFlushButton(coordinator, entry),
        BidetFlushNewButton(coordinator, entry),
        BidetFlushOldButton(coordinator, entry),
    ])


class BidetFlushButton(ButtonEntity):
    """Représentation d'un bouton pour la chasse d'eau du bidet."""

    _attr_has_entity_name = True
    _attr_name = "Chasse d'eau"
    _attr_icon = "mdi:toilet"
    
    def __init__(self, coordinator: BidetCoordinator, entry: ConfigEntry) -> None:
        """Initialiser le bouton."""
        self.coordinator = coordinator
        self._entry = entry
        self.hass = coordinator.hass  # Accès à hass pour les notifications
        
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
        from homeassistant.components import persistent_notification

        _LOGGER.info("🚽 TENTATIVE D'ACTIVATION DE LA CHASSE D'EAU (via send_command)")
        try:
            # Notifier le début de l'action
            persistent_notification.create(
                self.hass,
                "Tentative d'activation de la chasse d'eau via l'intégration BLE.",
                "Test du Bidet WC",
                "bidet_test_command"
            )

            # Utiliser le chemin standard de l'intégration (sélection dynamique FFF1/FFE1 + encodage 55aa + checksum)
            result = await self.coordinator.send_command(CMD_FLUSH, VAL_FLUSH_ON)

            if result:
                _LOGGER.info("✅ Commande flush envoyée avec succès")
                persistent_notification.create(
                    self.hass,
                    "La commande flush a été envoyée avec succès. Vérifiez la réaction du bidet.",
                    "Commande envoyée",
                    "bidet_command_result"
                )
            else:
                _LOGGER.error("❌ Échec de l'envoi de la commande flush")
                persistent_notification.create(
                    self.hass,
                    "Échec de l'envoi de la commande flush. Vérifiez la connexion Bluetooth et réessayez.",
                    "Erreur d'envoi",
                    "bidet_command_error"
                )
        except Exception as err:
            _LOGGER.error("❌ Erreur lors de l'envoi de la commande flush: %s", err)
            from homeassistant.components import persistent_notification as pn
            pn.create(
                self.hass,
                f"Erreur lors de l'envoi de la commande flush: {err}",
                "Erreur d'envoi",
                "bidet_command_error"
            )
    
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


class BidetFlushNewButton(ButtonEntity):
    """Bouton pour envoyer la trame Nouveau format (0006) directement."""

    _attr_has_entity_name = True
    _attr_name = "Chasse d'eau (Nouveau format)"
    _attr_icon = "mdi:toilet"

    def __init__(self, coordinator: BidetCoordinator, entry: ConfigEntry) -> None:
        self.coordinator = coordinator
        self._entry = entry
        self.hass = coordinator.hass
        self._attr_unique_id = f"{entry.entry_id}_flush_new"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Wings/Jitian",
            model="Top Toilet WC",
        )

        coordinator.add_disconnect_callback(self._handle_disconnect)

    async def async_press(self) -> None:
        from homeassistant.components import persistent_notification as pn
        try:
            pn.create(
                self.hass,
                "Envoi trame Nouveau format (0006) directement sur la caractéristique d'écriture.",
                "Test du Bidet WC",
                "bidet_test_command_new"
            )
            # S'assurer de la connexion
            if not self.coordinator.client or not self.coordinator.connected:
                ok = await self.coordinator.connect()
                if not ok:
                    raise RuntimeError("Connexion BLE impossible")

            # Sélection/caractéristique actuelle
            if not self.coordinator.write_char_uuid:
                await self.coordinator._select_characteristics()
            target_char = self.coordinator.write_char_uuid or OLD_CHARACTERISTIC_UUID

            # Construire trame et envoyer
            cmd = self.coordinator._build_new_frame(CMD_FLUSH, VAL_FLUSH_ON)
            result = await self.coordinator.send_raw_to_char(cmd, target_char)

            if result:
                pn.create(self.hass, f"Trame 0006 envoyée sur {target_char}: {cmd.hex()}", "Commande envoyée", "bidet_cmd_new_ok")
            else:
                pn.create(self.hass, f"Échec envoi trame 0006 sur {target_char}: {cmd.hex()}", "Erreur d'envoi", "bidet_cmd_new_err")
        except Exception as err:
            from homeassistant.components import persistent_notification as pn2
            pn2.create(self.hass, f"Erreur trame 0006: {err}", "Erreur d'envoi", "bidet_cmd_new_err")

    def _handle_disconnect(self) -> None:
        self._attr_available = False
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self._attr_available = self.coordinator.connected

    async def async_will_remove_from_hass(self) -> None:
        self.coordinator.remove_disconnect_callback(self._handle_disconnect)


class BidetFlushOldButton(ButtonEntity):
    """Bouton pour envoyer la trame Ancien format (0001) directement (avec impulsion)."""

    _attr_has_entity_name = True
    _attr_name = "Chasse d'eau (Ancien format)"
    _attr_icon = "mdi:toilet"

    def __init__(self, coordinator: BidetCoordinator, entry: ConfigEntry) -> None:
        self.coordinator = coordinator
        self._entry = entry
        self.hass = coordinator.hass
        self._attr_unique_id = f"{entry.entry_id}_flush_old"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Wings/Jitian",
            model="Top Toilet WC",
        )

        coordinator.add_disconnect_callback(self._handle_disconnect)

    async def async_press(self) -> None:
        from homeassistant.components import persistent_notification as pn
        try:
            pn.create(
                self.hass,
                "Envoi trame Ancien format (0001) avec impulsion ON→OFF→ON sur FFE1.",
                "Test du Bidet WC",
                "bidet_test_command_old"
            )
            # S'assurer de la connexion
            if not self.coordinator.client or not self.coordinator.connected:
                ok = await self.coordinator.connect()
                if not ok:
                    raise RuntimeError("Connexion BLE impossible")

            # Forcer FFE1 si possible (modèle ancien)
            target_char = OLD_CHARACTERISTIC_UUID

            # Construire trames et envoyer (impulsion)
            on_cmd = self.coordinator._build_old_frame(CMD_FLUSH, VAL_FLUSH_ON)
            off_cmd = self.coordinator._build_old_frame(CMD_FLUSH, VAL_FLUSH_OFF)

            ok1 = await self.coordinator.send_raw_to_char(on_cmd, target_char)
            await asyncio.sleep(0.35)
            ok2 = await self.coordinator.send_raw_to_char(off_cmd, target_char)
            await asyncio.sleep(0.35)
            ok3 = await self.coordinator.send_raw_to_char(on_cmd, target_char)

            if ok1 or ok2 or ok3:
                pn.create(self.hass, f"Trames 0001 envoyées sur {target_char} (impulsion).", "Commande envoyée", "bidet_cmd_old_ok")
            else:
                pn.create(self.hass, f"Échec envoi trames 0001 sur {target_char}.", "Erreur d'envoi", "bidet_cmd_old_err")
        except Exception as err:
            from homeassistant.components import persistent_notification as pn2
            pn2.create(self.hass, f"Erreur trame 0001: {err}", "Erreur d'envoi", "bidet_cmd_old_err")

    def _handle_disconnect(self) -> None:
        self._attr_available = False
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self._attr_available = self.coordinator.connected

    async def async_will_remove_from_hass(self) -> None:
        self.coordinator.remove_disconnect_callback(self._handle_disconnect)
