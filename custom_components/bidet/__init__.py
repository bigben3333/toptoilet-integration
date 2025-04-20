"""Intégration Home Assistant pour contrôler le bidet Wings/Jitian via Bluetooth."""
import logging
import binascii
import asyncio
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

from .const import (
    DOMAIN, PLATFORMS, SERVICE_UUID, CHARACTERISTIC_UUID, 
    OLD_SERVICE_UUID, OLD_CHARACTERISTIC_UUID, 
    SERVICE_PREPARE_PAIRING, SERVICE_TEST_COMMAND,
    CMD_FLUSH, VAL_FLUSH_ON
)

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
        _LOGGER.info("⭐ Tentative d'activation de la chasse d'eau avec séquence exacte de l'application")
        
        # S'assurer que nous sommes connectés
        if not self.client or not self.connected:
            try:
                if not await self.connect():
                    _LOGGER.error("Impossible de se connecter pour envoyer la commande")
                    return False
            except Exception as err:
                _LOGGER.error("Erreur lors de la reconnexion: %s", err)
                return False
        
        # 1. ÉTAPE CRUCIALE - S'abonner aux notifications AVANT d'envoyer des commandes
        # C'est exactement ce que fait l'application originale
        try:
            _LOGGER.info("⚡ 1) ACTIVATION DES NOTIFICATIONS (étape cruciale selon l'application originale)")
            
            # L'application utilise la caractéristique FFE1 pour les notifications
            await self.client.start_notify(
                "0000ffe1-0000-1000-8000-00805f9b34fb", 
                self._notification_handler
            )
            _LOGGER.info("⚡ Notifications activées avec succès - Le bidet peut maintenant recevoir des commandes")
            await asyncio.sleep(0.5)  # Attendre que le mode notification soit stable
            
            # L'app originale fait d'abord une lecture après s'être abonnée
            try:
                _LOGGER.info("⚡ 2) LECTURE de l'état initial comme dans l'application originale")
                value_bytes = await self.client.read_gatt_char("0000ffe1-0000-1000-8000-00805f9b34fb")
                _LOGGER.info("⚡ Valeur actuelle: %s", value_bytes.hex() if value_bytes else "Aucune valeur")
                await asyncio.sleep(0.3)
            except Exception as err:
                _LOGGER.info("⚡ Lecture non critique impossible: %s", err)
                
        except Exception as err:
            _LOGGER.warning("⚡ Échec de l'abonnement aux notifications: %s", err)
            # Continuer quand même, certains appareils fonctionnent sans notifications
        
        # 3. PRÉPARATION DE LA COMMANDE EXACTE (comme dans l'application décompilée)
        # Dans l'app, la commande de chasse d'eau est une instance de CmdBean avec:
        # - type: paramètre du constructeur
        # - cmd: 7b (commande flush)
        # - value: 01 (valeur pour activer)
        
        # Construction de la commande comme dans l'app (MainActivity ligne 524-525)
        # Le checksum est calculé sur cette chaîne de base
        cmd_base = "55aa000100" + cmd + "0001" + value 
        checksum = self._calculate_checksum(cmd_base)
        full_cmd_hex = cmd_base + checksum
        
        _LOGGER.info("⚡ 3) ENVOI de la commande exacte formatée comme dans l'application: %s", full_cmd_hex)
        full_cmd = bytes.fromhex(full_cmd_hex)
        
        # 4. ENVOI DE LA COMMANDE - Exactement comme l'app le fait
        try:
            # L'application utilise toujours la caractéristique FFE1
            # En analysant MainActivity.java, l'app ne fait pas d'essais-erreurs,
            # elle envoie directement à la caractéristique trouvée
            _LOGGER.info("⚡ 4) ENVOI sur la caractéristique exacte de l'application: 0000ffe1-0000-1000-8000-00805f9b34fb")
            
            # Méthode exacte utilisée par l'app
            await self.client.write_gatt_char("0000ffe1-0000-1000-8000-00805f9b34fb", full_cmd)
            
            # L'app attend ensuite une notification de retour, mais c'est géré par le handler
            # On attendra donc un moment pour voir si une notification arrive
            _LOGGER.info("⚡ 5) ATTENTE de notification retour (comme dans l'app)...")
            await asyncio.sleep(1)  # Attendre que la notification arrive potentiellement
            
            # L'application renvoie TRUE à ce moment car elle considère l'envoi réussi
            # (indépendamment de si la chasse d'eau s'active, car cela sera confirmé par une notif)
            return True
        except Exception as err:
            _LOGGER.error("Erreur lors de l'envoi de la commande: %s", err)
            self.connected = False
            return False

    def _notification_handler(self, sender, data):
        """Gérer les notifications reçues du bidet."""
        _LOGGER.info("🔔 NOTIFICATION REÇUE: Caractéristique %s, Données: %s", 
                    sender, data.hex() if data else "Aucune donnée")

    async def send_raw_command(self, command: bytes) -> bool:
        """Envoyer une commande brute au bidet."""
        _LOGGER.info("Tentative d'envoi de commande brute: %s", command.hex())
        
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
            # Essayer d'abord les caractéristiques connues
            for uuid in [OLD_CHARACTERISTIC_UUID, CHARACTERISTIC_UUID]:
                try:
                    _LOGGER.info("Tentative d'envoi sur %s", uuid)
                    await self.client.write_gatt_char(uuid, command)
                    _LOGGER.info("✓ SUCCÈS! Commande envoyée sur %s", uuid)
                    return True
                except Exception as err:
                    _LOGGER.debug("Échec sur %s: %s", uuid, err)
            
            # Ensuite essayer toutes les caractéristiques disponibles
            services = self.client.services
            if services:
                for service in services:
                    for char in service.characteristics:
                        if "write" in char.properties or "write-without-response" in char.properties:
                            try:
                                _LOGGER.info("Tentative d'envoi sur %s", char.uuid)
                                await self.client.write_gatt_char(char.uuid, command)
                                _LOGGER.info("✓ SUCCÈS sur %s", char.uuid)
                                return True
                            except Exception:
                                pass  # Continue avec la caractéristique suivante
            
            _LOGGER.error("Échec de l'envoi de la commande brute")
            return False
        except Exception as err:
            _LOGGER.error("Erreur lors de l'envoi de la commande brute: %s", err)
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
    
    # Service de test pour le débogage
    async def handle_test_command(call: ServiceCall) -> None:
        """Gérer le service de test de commande."""
        _LOGGER.info("🔍 Service de test de commande appelé")
        
        device_id = call.data.get("device_id")
        command_type = call.data.get("command_type")
        raw_command = call.data.get("raw_command")
        
        # Récupérer le device_id et trouver le coordinateur correspondant
        device_registry = hass.helpers.device_registry.async_get(hass)
        device = device_registry.async_get(device_id)
        
        if not device:
            _LOGGER.error("🔍 Appareil non trouvé: %s", device_id)
            return
        
        # Trouver l'entrée de configuration correspondante
        for identifier in device.identifiers:
            if identifier[0] == DOMAIN:
                entry_id = identifier[1]
                break
        else:
            _LOGGER.error("🔍 Impossible de trouver l'entrée de configuration pour l'appareil %s", device_id)
            return
        
        coordinator = hass.data[DOMAIN].get(entry_id)
        if not coordinator:
            _LOGGER.error("🔍 Coordinateur non trouvé pour l'entrée %s", entry_id)
            return
        
        _LOGGER.info("🔍 Envoi de commande de test à l'appareil %s (type: %s)", device_id, command_type)
        
        try:
            result = False
            
            if command_type == "flush":
                # Commande de chasse d'eau standard
                _LOGGER.info("🔍 Envoi commande flush")
                result = await coordinator.send_command(CMD_FLUSH, VAL_FLUSH_ON)
            elif command_type == "old_format":
                # Force l'ancien format
                command = b'\x55\xaa\x00\x01\x05\x7b\x00\x01\x01\xa1'
                _LOGGER.info("🔍 Envoi commande ancien format: %s", command.hex())
                result = await coordinator.send_raw_command(command)
            elif command_type == "new_format":
                # Force le nouveau format
                command = b'\x55\xaa\x00\x06\x05\x7b\x00\x01\x01\xdb'
                _LOGGER.info("🔍 Envoi commande nouveau format: %s", command.hex())
                result = await coordinator.send_raw_command(command)
            elif command_type == "raw" and raw_command:
                # Commande brute
                try:
                    # Convertir la chaîne hex en bytes
                    command = bytes.fromhex(raw_command)
                    _LOGGER.info("🔍 Envoi commande brute: %s", command.hex())
                    result = await coordinator.send_raw_command(command)
                except ValueError as err:
                    _LOGGER.error("🔍 Format hexadécimal invalide: %s", err)
            
            _LOGGER.info("🔍 Résultat de la commande de test: %s", "Succès" if result else "Échec")
        except Exception as err:
            _LOGGER.error("🔍 Erreur lors de l'envoi de la commande de test: %s", err)
    
    # Service de test simplifié qui utilise le premier bidet configuré
    async def handle_test_simple(call: ServiceCall) -> None:
        """Gérer le service de test simplifié."""
        command_type = call.data.get("command_type", "flush")
        
        _LOGGER.info("🔎 Service de test simplifié appelé (type: %s)", command_type)
        
        # Trouver le premier coordinateur bidet disponible
        if not hass.data.get(DOMAIN):
            _LOGGER.error("🔎 Aucune intégration bidet configurée")
            hass.components.persistent_notification.create(
                "Aucune intégration Bidet WC n'est configurée. Veuillez d'abord ajouter l'intégration.",
                "Test du Bidet WC",
                "bidet_test_error"
            )
            return
        
        # Trouver le premier coordinateur
        entry_id = next(iter(hass.data[DOMAIN].keys()))
        coordinator = hass.data[DOMAIN][entry_id]
        
        _LOGGER.info("🔎 Utilisation du premier bidet trouvé: %s", coordinator.address)
        
        try:
            result = False
            
            if command_type == "flush":
                # Commande de chasse d'eau standard
                _LOGGER.info("🔎 Envoi commande flush")
                result = await coordinator.send_command(CMD_FLUSH, VAL_FLUSH_ON)
            elif command_type == "old_format":
                # Force l'ancien format
                command = b'\x55\xaa\x00\x01\x05\x7b\x00\x01\x01\xa1'
                _LOGGER.info("🔎 Envoi commande ancien format: %s", command.hex())
                result = await coordinator.send_raw_command(command)
            elif command_type == "new_format":
                # Force le nouveau format
                command = b'\x55\xaa\x00\x06\x05\x7b\x00\x01\x01\xdb'
                _LOGGER.info("🔎 Envoi commande nouveau format: %s", command.hex())
                result = await coordinator.send_raw_command(command)
            
            message = "✅ La commande a été envoyée avec succès" if result else "❌ Échec de l'envoi de la commande"
            _LOGGER.info("🔎 Résultat: %s", message)
            
            # Notification du résultat
            hass.components.persistent_notification.create(
                message,
                "Test du Bidet WC",
                "bidet_test_result"
            )
        except Exception as err:
            _LOGGER.error("🔎 Erreur lors de l'envoi de la commande: %s", err)
            hass.components.persistent_notification.create(
                f"Erreur lors de l'envoi de la commande: {err}",
                "Test du Bidet WC",
                "bidet_test_error"
            )
    
    # Enregistrer les services
    hass.services.async_register(
        DOMAIN,
        SERVICE_PREPARE_PAIRING,
        handle_prepare_pairing,
        schema=vol.Schema({})
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_TEST_COMMAND,
        handle_test_command,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Required("command_type"): vol.In(["flush", "old_format", "new_format", "raw"]),
            vol.Optional("raw_command"): cv.string,
        })
    )
    
    # Service de test simplifié
    hass.services.async_register(
        DOMAIN,
        "test_simple",
        handle_test_simple,
        schema=vol.Schema({
            vol.Optional("command_type", default="flush"): vol.In(["flush", "old_format", "new_format"]),
        })
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
