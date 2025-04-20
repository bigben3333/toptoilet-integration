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

from .const import DOMAIN, PLATFORMS, SERVICE_UUID, CHARACTERISTIC_UUID, OLD_SERVICE_UUID, OLD_CHARACTERISTIC_UUID, SERVICE_PREPARE_PAIRING

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

            try:
                ble_device = bluetooth.async_ble_device_from_address(
                    self.hass, self.address, connectable=True
                )
                if not ble_device:
                    _LOGGER.error("Impossible de trouver l'appareil: %s", self.address)
                    return False
            except Exception as err:
                _LOGGER.error("Erreur lors de la recherche de l'appareil %s: %s", self.address, err)
                return False

            self.client = await establish_connection(
                client_class=BleakClient,
                device=ble_device,
                name=self.address,
                disconnected_callback=disconnected_callback,
                use_services_cache=False,  # Désactiver le cache pour forcer une nouvelle découverte
            )
            
            # Liste toutes les caractéristiques disponibles
            try:
                services = await self.client.get_services()
                _LOGGER.info("Services disponibles pour %s:", self.address)
                self.writable_characteristics = []
                for service in services:
                    _LOGGER.info("  Service: %s", service.uuid)
                    for char in service.characteristics:
                        props = []
                        if "read" in char.properties:
                            props.append("read")
                        if "write" in char.properties:
                            props.append("write")
                            self.writable_characteristics.append(char.uuid)
                        if "notify" in char.properties:
                            props.append("notify")
                        _LOGGER.info("    Caractéristique: %s (%s)", char.uuid, ", ".join(props))
                
                if not self.writable_characteristics:
                    _LOGGER.error("Aucune caractéristique d'écriture trouvée sur l'appareil")
                    return False
                    
                _LOGGER.info("Caractéristiques d'écriture disponibles: %s", self.writable_characteristics)
            except Exception as err:
                _LOGGER.warning("Impossible de lister les services/caractéristiques: %s", err)
                
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
        
        _LOGGER.info("Tentative d'envoi de commande au bidet: %s, %s", cmd, value)
        
        # S'assurer que nous sommes connectés
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
            
            _LOGGER.info("Commande finale: %s", final_cmd)
            
            # Conversion en bytes
            cmd_bytes = binascii.unhexlify(final_cmd)
            
            # Essayer d'abord la nouvelle caractéristique (fff1)
            try:
                _LOGGER.info("Tentative d'envoi sur la caractéristique NOUVELLE (fff1)")
                await self.client.write_gatt_char(CHARACTERISTIC_UUID, cmd_bytes)
                _LOGGER.info("Commande envoyée avec succès sur la NOUVELLE caractéristique")
                return True
            except Exception as err:
                _LOGGER.warning("Échec sur la caractéristique NOUVELLE: %s", err)
            
            # Ensuite essayer l'ancienne caractéristique (ffe1)
            try:
                _LOGGER.info("Tentative d'envoi sur la caractéristique ANCIENNE (ffe1)")
                await self.client.write_gatt_char(OLD_CHARACTERISTIC_UUID, cmd_bytes)
                _LOGGER.info("Commande envoyée avec succès sur l'ANCIENNE caractéristique")
                return True
            except Exception as err:
                _LOGGER.warning("Échec sur la caractéristique ANCIENNE: %s", err)
            
            # Si les deux échouent, rechercher toutes les caractéristiques qui supportent l'écriture
            _LOGGER.info("Tentative de découverte de toutes les caractéristiques d'écriture")
            services = await self.client.get_services()
            for service in services:
                _LOGGER.info("  Service UUID: %s", service.uuid)
                for char in service.characteristics:
                    if "write" in char.properties:
                        try:
                            _LOGGER.info("  Tentative d'écriture sur caractéristique: %s", char.uuid)
                            await self.client.write_gatt_char(char.uuid, cmd_bytes)
                            _LOGGER.info("  Commande envoyée avec succès sur caractéristique: %s", char.uuid)
                            return True
                        except Exception as write_err:
                            _LOGGER.warning("  Échec sur la caractéristique %s: %s", char.uuid, write_err)
            
            _LOGGER.error("Impossible d'envoyer la commande sur aucune caractéristique disponible")
            return False
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


# Aucune classe de bouton n'est nécessaire car nous utiliserons une notification directe


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Configurer le service d'appairage."""
    
    # Définir le service de préparation d'appairage
    async def handle_prepare_pairing(call: ServiceCall) -> None:
        """Gérer le service de préparation à l'appairage."""
        _LOGGER.info("Service de préparation à l'appairage appelé")
        
        # Notification pour l'utilisateur avec les instructions simplifiées
        hass.components.persistent_notification.create(
            "Pour préparer votre Top Toilet / Bidet WC à la détection Bluetooth :<br><br>"
            "1. Redémarrez votre toilette (coupez l'alimentation et rallumez)<br>"
            "2. Assurez-vous que votre toilette est à portée du serveur Home Assistant<br><br>"
            "Une fois ces étapes effectuées, vous pouvez ajouter l'intégration via "
            "Paramètres → Appareils et services → Ajouter une intégration → Top Toilet / Bidet WC",
            "Préparer votre toilette pour l'intégration",
            "bidet_pairing_instructions"
        )
        
    hass.services.async_register(
        DOMAIN,
        SERVICE_PREPARE_PAIRING,
        handle_prepare_pairing,
        schema=vol.Schema({})
    )
    
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
