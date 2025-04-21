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
        self._counter = 0  # Compteur pour alterner les commandes
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
        # Force l'exécution des nouveaux tests
        test_num = self.hass.states.get(f"{DOMAIN}.test_counter")
        
        # Si l'entité d'état n'existe pas, la créer
        if not test_num:
            self.hass.states.async_set(f"{DOMAIN}.test_counter", "5")
            current_test = 5
        else:
            # Récupérer la valeur actuelle et l'incrémenter
            try:
                current_test = int(test_num.state)
                current_test = (current_test + 1) % 11  # 0-10
                if current_test == 0:  # Éviter le test #0, commencer à 1
                    current_test = 1
            except ValueError:
                current_test = 5  # Valeur par défaut = test des commandes spéciales
            
            # Mettre à jour l'état
            self.hass.states.async_set(f"{DOMAIN}.test_counter", str(current_test))
        
        _LOGGER.info("👆 EXÉCUTION du TEST #%s", current_test)
        
        try:
            # TESTS DE COMMANDES SPÉCIALES (FORCE)
            if current_test == 6:
                # Variation avec un préfixe d'authentification
                _LOGGER.info("👆 TEST #6: Commande avec préfixe d'authentification (d8b673097b01)")
                result = await self.coordinator.send_raw_command(bytes.fromhex("d8b673097b01"))
            elif current_test == 7:
                # Commande avec préfixe et xor
                _LOGGER.info("👆 TEST #7: Commande avec préfixe XOR (27498cf67b01)")
                result = await self.coordinator.send_raw_command(bytes.fromhex("27498cf67b01"))
            elif current_test == 8:
                # Format AT (commun pour certains appareils Bluetooth)
                _LOGGER.info("👆 TEST #8: Format AT (AT+FLUSH)")
                result = await self.coordinator.send_raw_command(b'AT+FLUSH')
            elif current_test == 9:
                # Format simple mais avec header
                _LOGGER.info("👆 TEST #9: Format simple avec header 55AA (55AA7B01)")
                result = await self.coordinator.send_raw_command(bytes.fromhex("55AA7B01"))
            elif current_test == 10:
                # Format juste avec le header
                _LOGGER.info("👆 TEST #10: Header uniquement (55AA)")
                result = await self.coordinator.send_raw_command(bytes.fromhex("55AA"))
            
            # TESTS CLASSIQUES
            elif current_test == 1:
                # Commande standard avec tous les extras
                _LOGGER.info("👆 TEST #1: Commande standard complète (avec notifications, auth, etc.)")
                result = await self.coordinator.send_command(CMD_FLUSH, VAL_FLUSH_ON)
            elif current_test == 2:
                # Commande simplifiée
                _LOGGER.info("👆 TEST #2: Commande simplifiée (7b 01)")
                result = await self.coordinator.send_raw_command(b'\x7b\x01')
            elif current_test == 3:
                # Ancien format complet
                _LOGGER.info("👆 TEST #3: Ancien format complet (55aa00010...)")
                result = await self.coordinator.send_raw_command(b'\x55\xaa\x00\x01\x05\x7b\x00\x01\x01\xa1')
            elif current_test == 4:
                # Nouveau format complet
                _LOGGER.info("👆 TEST #4: Nouveau format complet (55aa00060...)")
                result = await self.coordinator.send_raw_command(b'\x55\xaa\x00\x06\x05\x7b\x00\x01\x01\xdb')
            elif current_test == 5:
                # Format simple 1 byte
                _LOGGER.info("👆 TEST #5: Commande ultra simplifiée (01)")
                result = await self.coordinator.send_raw_command(b'\x01')
            
            _LOGGER.info("👆 Résultat du test #%s: %s", current_test, "Succès" if result else "Échec")
            
            # Notification temporaire pour informer l'utilisateur
            from homeassistant.components import persistent_notification
            persistent_notification.create(
                self.hass,
                f"Test #{current_test} envoyé avec succès. "
                f"Vérifiez si votre bidet a réagi. "
                f"Appuyez à nouveau pour essayer un format différent.",
                "Test du Bidet WC",
                f"bidet_test_{current_test}"
            )
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
