# Intégration Top Toilet / Bidet WC pour Home Assistant

Cette intégration permet de contrôler votre WC Japonais Monobloc Luxe DIAMOND PLUS Wings/Jitian via Bluetooth Low Energy (BLE) depuis Home Assistant. En tout cas je n'ai testé que ce modèle.

## Fonctionnalités

- **Contrôle de la chasse d'eau** : Déclenchez la chasse d'eau à distance via un bouton dans Home Assistant

## Prérequis

- Home Assistant avec support Bluetooth
- Un adaptateur Bluetooth compatible sur votre serveur Home Assistant
- Un bidet Wings/Jitian compatible (modèle avec connectivité Bluetooth, apparaît sous le nom "HMsoft" dans la liste des appareils Bluetooth)

## Installation

### Installation manuelle

1. Copiez le dossier `bidet_integration` dans le répertoire `custom_components` de votre installation Home Assistant.
   ```bash
   cp -r bidet_integration <chemin_vers_home_assistant>/config/custom_components/bidet
   ```

2. Redémarrez Home Assistant.

### Installation avec HACS (Home Assistant Community Store)

1. Assurez-vous que [HACS](https://hacs.xyz/) est installé.
2. Allez dans HACS → Intégrations → ⋮ → Dépôts personnalisés
3. Ajoutez l'URL du dépôt : `https://github.com/bigben3333/toptoilet-integration`
4. Sélectionnez "Intégration" comme catégorie
5. Cliquez sur "Ajouter"
6. Recherchez "Top Toilet / Bidet WC" et installez-le
7. Redémarrez Home Assistant

## Configuration

Cette intégration prend en charge la découverte Bluetooth automatique. Après l'installation :

1. Allez dans Home Assistant → Paramètres → Appareils et services → Ajouter une intégration
2. Recherchez "Top Toilet / Bidet WC"
3. Suivez les instructions à l'écran
   - Home Assistant recherchera automatiquement les bidets compatibles à proximité
   - Sélectionnez votre bidet dans la liste
   - Donnez un nom à votre bidet

## Utilisation

Une fois configuré, un nouveau dispositif apparaîtra dans Home Assistant avec l'entité suivante :

- **Bouton de chasse d'eau** : Appuyez sur ce bouton pour déclencher la chasse d'eau

### Exemples d'automatisations

#### Déclencher la chasse d'eau à une heure précise

```yaml
automation:
  - alias: "Déclencher la chasse d'eau à 8h"
    trigger:
      platform: time
      at: "08:00:00"
    action:
      service: button.press
      target:
        entity_id: button.nom_de_votre_bidet_chasse_d_eau
```

#### Déclencher la chasse d'eau par commande vocale

Avec Google Assistant, Amazon Alexa ou tout autre assistant vocal intégré à Home Assistant, vous pouvez configurer une commande personnalisée pour déclencher la chasse d'eau.

## Dépannage

### Problèmes de connexion Bluetooth

Si vous rencontrez des problèmes de connexion :

1. Assurez-vous que votre bidet est sous tension et que le Bluetooth est activé
2. Vérifiez que votre serveur Home Assistant est à portée du bidet (généralement moins de 10 mètres)
3. Redémarrez votre bidet et votre serveur Home Assistant

### Vérification de votre appareil Bluetooth

Vous pouvez vérifier que votre appareil Bluetooth est bien détecté par Home Assistant :

1. Allez dans Home Assistant → Paramètres → Appareils et services → Bluetooth
2. Vérifiez que votre bidet apparaît dans la liste des appareils détectés

## Améliorations futures

- Support pour d'autres fonctions du bidet (chaleur du siège, lavage, etc.)
- Interface utilisateur plus complète avec statuts et paramètres
- Prise en charge de modèles supplémentaires

## Contribuer

Les contributions sont les bienvenues ! N'hésitez pas à ouvrir une issue ou une pull request sur le dépôt GitHub.
