"""Intégration Home Assistant pour contrôler le bidet Wings/Jitian via Bluetooth."""
import logging
import binascii
from typing import Any

from bleak import BleakClient, BleakError
from bleak_retry_connector import establish_connection, BleakNotFoundError

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import Entity
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import DOMAIN, PLATFORMS, SERVICE_UUID, CHARACTERISTIC_UUID, SERVICE_PREPARE_PAIRING

_LOGGER = logging.getLogger(__name__)


class BidetCoordinator:
    """Classe pour coordonner les communications avec le bidet."""

    def __init__(self, hass: HomeAssistant, address: str):
        """Initialiser le coordinateur."""
        self.hass = hass
        self.address = address
        self.client: BleakClient | None = None
        self.connected = False
        self._disconnect_callbacks = []

    async def connect(self) -> bool:
        """Établir la connexion avec le bidet."""
        try:
            def disconnected_callback(client: BleakClient):
                """Gérer la déconnexion."""
                self.connected = False
                for callback in self._disconnect_callbacks:
                    callback()

            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self.address, connectable=True
            )
            if not ble_device:
                _LOGGER.error("Impossible de trouver l'appareil: %s", self.address)
                return False

            self.client = await establish_connection(
                client_class=BleakClient,
                device=ble_device,
                name=self.address,
                disconnected_callback=disconnected_callback,
                use_services_cache=True,
            )
            self.connected = True
            return True
        except (BleakError, BleakNotFoundError) as error:
            _LOGGER.error("Erreur de connexion à %s: %s", self.address, error)
            self.connected = False
            return False

    async def disconnect(self) -> None:
        """Déconnecter le bidet."""
        if self.client:
            await self.client.disconnect()
            self.client = None
        self.connected = False

    def add_disconnect_callback(self, callback):
        """Ajouter un callback à appeler lors de la déconnexion."""
        self._disconnect_callbacks.append(callback)

    def remove_disconnect_callback(self, callback):
        """Supprimer un callback."""
        if callback in self._disconnect_callbacks:
            self._disconnect_callbacks.remove(callback)

    async def send_command(self, cmd: str, value: str) -> bool:
        """Envoyer une commande au bidet."""
        from .const import CMD_HEADER, CMD_PROTOCOL, CMD_TRAILER
        
        if not self.client or not self.connected:
            try:
                if not await self.connect():
                    _LOGGER.error("Impossible de se connecter pour envoyer la commande")
                    return False
            except Exception as err:
                _LOGGER.error("Erreur lors de la reconnexion: %s", err)
                return False

        try:
            # Construction de la commande
            cmd_length = "05"  # Longueur fixe pour la commande de chasse d'eau
            data_part = f"{cmd}{CMD_TRAILER}{value}"
            
            # Construction de la commande sans checksum
            cmd_without_checksum = f"{CMD_HEADER}{CMD_PROTOCOL}{cmd_length}{data_part}"
            
            # Calcul du checksum
            checksum = self._calculate_checksum(cmd_without_checksum)
            
            # Commande finale
            final_cmd = f"{cmd_without_checksum}{checksum}"
            
            _LOGGER.debug("Commande finale: %s", final_cmd)
            
            # Conversion en bytes
            cmd_bytes = binascii.unhexlify(final_cmd)
            
            # Envoi de la commande
            await self.client.write_gatt_char(CHARACTERISTIC_UUID, cmd_bytes)
            return True
        except Exception as err:
            _LOGGER.error("Erreur lors de l'envoi de la commande: %s", err)
            self.connected = False
            return False

    def _calculate_checksum(self, cmd_str: str) -> str:
        """Calculer le checksum selon la méthode du bidet."""
        # Divise la commande en paires de caractères (octets en hex)
        pairs = [cmd_str[i:i+2] for i in range(0, len(cmd_str), 2)]
        
        # Convertit chaque paire en entier et somme
        sum_value = sum(int(pair, 16) for pair in pairs)
        
        # Prend le modulo 256 et convertit en hex
        checksum = sum_value % 256
        checksum_hex = format(checksum, '02x')
        
        return checksum_hex


class BidetPairingButtonEntity(ButtonEntity):
    """Représentation du bouton d'appairage du bidet."""
    
    _attr_has_entity_name = True
    _attr_name = "Assistant d'appairage"
    _attr_icon = "mdi:bluetooth-connect"
    _attr_entity_id = "button.bidet_pairing_assistant"
    _attr_should_poll = False
    
    def __init__(self, hass: HomeAssistant) -> None:
        """Initialiser le bouton."""
        self.hass = hass
        self._attr_unique_id = "bidet_pairing_assistant"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "pairing_assistant")},
            "name": "Assistant d'appairage Bidet WC",
            "manufacturer": "Home Assistant",
            "model": "Assistant",
            "sw_version": "1.0",
        }
    
    async def async_press(self) -> None:
        """Gérer l'appui sur le bouton."""
        _LOGGER.info("Assistant d'appairage du bidet activé. Suivez les instructions pour mettre votre bidet en mode appairage:")
        _LOGGER.info("1. Assurez-vous que le bidet est sous tension")
        _LOGGER.info("2. Vérifiez que la lunette des toilettes est baissée")
        _LOGGER.info("3. Appuyez et maintenez le bouton 'Stop' sur le panneau pendant 3 secondes")
        _LOGGER.info("4. Attendez que la LED commence à clignoter")
        
        # Notification pour l'utilisateur
        self.hass.components.persistent_notification.create(
            "Pour mettre votre Top Toilet / Bidet WC en mode appairage :<br><br>"
            "1. Assurez-vous que le bidet est sous tension<br>"
            "2. Vérifiez que la lunette des toilettes est baissée<br>"
            "3. Appuyez et maintenez le bouton 'Stop' sur le panneau pendant 3 secondes<br>"
            "4. Attendez que la LED commence à clignoter<br><br>"
            "Une fois ces étapes effectuées, vous pouvez ajouter l'intégration via "
            "Paramètres → Appareils et services → Ajouter une intégration → Top Toilet / Bidet WC",
            "Instructions d'appairage du Bidet WC",
            "bidet_pairing_instructions"
        )


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Configurer le service d'appairage."""
    
    # Définir le service de préparation d'appairage
    async def handle_prepare_pairing(call: ServiceCall) -> None:
        """Gérer le service de préparation à l'appairage."""
        _LOGGER.info("Service de préparation à l'appairage appelé. Suivez les instructions pour mettre votre bidet en mode appairage:")
        _LOGGER.info("1. Assurez-vous que le bidet est sous tension")
        _LOGGER.info("2. Vérifiez que la lunette des toilettes est baissée")
        _LOGGER.info("3. Appuyez et maintenez le bouton 'Stop' sur le panneau pendant 3 secondes")
        _LOGGER.info("4. Attendez que la LED commence à clignoter")
        
        # Notification pour l'utilisateur
        hass.components.persistent_notification.create(
            "Pour mettre votre Top Toilet / Bidet WC en mode appairage :<br><br>"
            "1. Assurez-vous que le bidet est sous tension<br>"
            "2. Vérifiez que la lunette des toilettes est baissée<br>"
            "3. Appuyez et maintenez le bouton 'Stop' sur le panneau pendant 3 secondes<br>"
            "4. Attendez que la LED commence à clignoter<br><br>"
            "Une fois ces étapes effectuées, vous pouvez ajouter l'intégration via "
            "Paramètres → Appareils et services → Ajouter une intégration → Top Toilet / Bidet WC",
            "Instructions d'appairage du Bidet WC",
            "bidet_pairing_instructions"
        )
        
    hass.services.async_register(
        DOMAIN,
        SERVICE_PREPARE_PAIRING,
        handle_prepare_pairing,
        schema=vol.Schema({})
    )
    
    # Ajouter l'entité bouton pour l'assistant d'appairage
    button = BidetPairingButtonEntity(hass)
    hass.add_job(hass.async_add_entities, [button])
    
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configurer le bidet à partir d'une entrée de configuration."""
    # Assurez-vous que le setup général a été effectué
    if not hass.data.get(DOMAIN):
        hass.data[DOMAIN] = {}
        await async_setup(hass, {})
    
    address = entry.data[CONF_ADDRESS]
    
    coordinator = BidetCoordinator(hass, address)
    if not await coordinator.connect():
        raise ConfigEntryNotReady(f"Impossible de se connecter au bidet {address}")
    
    # Stocker le coordinateur pour être utilisé par les plateformes
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    
    # S'assurer de déconnecter proprement à l'arrêt
    async def on_hass_stop(event):
        """Gérer l'arrêt de Home Assistant."""
        await coordinator.disconnect()
        
    # S'abonner à l'événement d'arrêt
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, on_hass_stop)
    )
    
    # Configurer les plateformes
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Décharger une entrée de configuration."""
    # Décharger les plateformes
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    # Déconnecter le bidet
    if unload_ok and entry.entry_id in hass.data[DOMAIN]:
        coordinator = hass.data[DOMAIN][entry.entry_id]
        await coordinator.disconnect()
        hass.data[DOMAIN].pop(entry.entry_id)
        
    return unload_ok
