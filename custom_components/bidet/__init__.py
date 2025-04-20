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

            # Revenir aux paramètres d'origine qui fonctionnaient
            self.client = await establish_connection(
                client_class=BleakClient,
                device=ble_device,
                name=self.address,
                disconnected_callback=disconnected_callback,
                use_services_cache=True,  # Réactivation du cache
            )
            
            # La connexion a réussi, ne pas faire de vérifications supplémentaires
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
        _LOGGER.info("Tentative d'envoi de commande pour activer la chasse d'eau")
        
        # S'assurer que nous sommes connectés
        if not self.client or not self.connected:
            try:
                if not await self.connect():
                    _LOGGER.error("Impossible de se connecter pour envoyer la commande")
                    return False
            except Exception as err:
                _LOGGER.error("Erreur lors de la reconnexion: %s", err)
                return False
            
        # Commandes binaires directes (hardcodées) pour la chasse d'eau
        # Ces commandes sont basées sur l'analyse de l'application officielle
        # et devraient fonctionner directement sans avoir besoin de calculer des checksums
        simple_commands = [
            # Chasse d'eau simplifiée pour les anciens modèles
            b'\x55\xaa\x00\x01\x05\x7b\x00\x01\x01\xa1',
            # Alternative avec format légèrement différent
            b'\x55\xaa\x00\x01\x00\x01\x01',
            # Commande plus simple
            b'\x01'
        ]
        
        try:
            # Découvrir tous les services et caractéristiques
            _LOGGER.info("Découverte des services et caractéristiques...")
            services = await self.client.get_services(force_discovery=True)
            
            # Première tentative: essayer directement avec l'ancien UUID
            _LOGGER.info("Tentative directe avec l'ancien UUID FFE1...")
            try:
                for cmd_bytes in simple_commands:
                    try:
                        _LOGGER.info("Envoi commande: %s sur FFE1", cmd_bytes.hex())
                        await self.client.write_gatt_char("0000ffe1-0000-1000-8000-00805f9b34fb", cmd_bytes)
                        _LOGGER.info("Commande envoyée avec succès sur FFE1!")
                        return True
                    except Exception as cmd_err:
                        _LOGGER.info("Échec commande spécifique: %s", cmd_err)
            except Exception as err:
                _LOGGER.warning("Échec FFE1: %s", err)
            
            # Deuxième tentative: parcourir toutes les caractéristiques
            _LOGGER.info("Parcours de toutes les caractéristiques...")
            for service in services:
                _LOGGER.info("Service: %s", service.uuid)
                for char in service.characteristics:
                    if "write" in char.properties or "write-without-response" in char.properties:
                        _LOGGER.info("Caractéristique avec écriture: %s", char.uuid)
                        for cmd_bytes in simple_commands:
                            try:
                                _LOGGER.info("Envoi commande sur %s", char.uuid)
                                await self.client.write_gatt_char(char.uuid, cmd_bytes)
                                _LOGGER.info("SUCCÈS sur %s", char.uuid)
                                return True
                            except Exception:
                                pass  # Continuer avec la prochaine commande/caractéristique
            
            _LOGGER.error("Échec: aucune commande n'a fonctionné sur aucune caractéristique")
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
