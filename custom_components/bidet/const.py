"""Constants for the Bidet WC integration."""
from homeassistant.const import Platform

DOMAIN = "bidet"

# Plateformes utilisées par cette intégration
PLATFORMS = [Platform.BUTTON]

# UUID pour le service Bluetooth et les caractéristiques
SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"

# Constantes pour l'appairage
PAIRING_TIMEOUT = 30  # Durée en secondes pour l'appairage
SERVICE_PREPARE_PAIRING = "prepare_pairing"  # Nom du service d'appairage

# Commandes
CMD_FLUSH = "7b"  # Commande pour la chasse d'eau
VAL_FLUSH_ON = "01"  # Valeur pour activer
VAL_FLUSH_OFF = "00"  # Valeur pour désactiver

# Commande complète avec checksum et format
CMD_HEADER = "55aa"  # En-tête de la commande
CMD_PROTOCOL = "0006"  # Protocole (nouveau)
CMD_TRAILER = "0001"  # Fin de la commande
