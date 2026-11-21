# Créer la clé USB winbootfix

[English](usb-guide.md)

Il vous faut : l'ISO `winbootfix-X.Y.Z-amd64.iso` des
[Releases](https://github.com/jojolenpls/winbootfix/releases), une clé USB d'au moins 1 Go (**son contenu
sera effacé**) et n'importe quel ordinateur qui fonctionne (pas forcément le PC en panne).

## 1. Vérifier le téléchargement (conseillé)

| Système | Commande |
|---|---|
| Windows (PowerShell) | `Get-FileHash .\winbootfix-X.Y.Z-amd64.iso -Algorithm SHA256` |
| macOS | `shasum -a 256 winbootfix-X.Y.Z-amd64.iso` |
| Linux | `sha256sum -c winbootfix-X.Y.Z-amd64.iso.sha256` |

La valeur doit être celle du fichier `.sha256`.

## 2. Écrire la clé

| Outil | Système | Rapport et sauvegardes enregistrés sur la clé ? |
|---|---|---|
| **Rufus** (conseillé sous Windows) | Windows | **oui** en « mode Image ISO » ; non en « mode Image DD » |
| **Ventoy** | Windows, Linux | **oui** (la clé reste utilisable pour d'autres fichiers et ISO) |
| **balenaEtcher** | Windows, macOS, Linux | non (clé en lecture seule) : branchez un second disque USB pour les sauvegardes |
| `dd` | Linux, macOS | non (comme Etcher) |

Quand la clé est en lecture seule, winbootfix enregistre ses sauvegardes sur un autre disque USB ou sur la
partition Windows ; s'il ne trouve aucun endroit sûr, il ne modifie rien.

### Rufus (Windows)

1. Téléchargez Rufus sur <https://rufus.ie> et lancez-le.
2. **Périphérique** : votre clé. **Type de démarrage** : SÉLECTION → l'ISO winbootfix.
3. **Schéma de partition** : GPT. **Système de destination** : UEFI (non CSM).
4. DÉMARRER. Si Rufus le demande, choisissez **« Écrire en mode Image ISO (Recommandé) »**.

### Ventoy (Windows, Linux)

1. Installez Ventoy une fois sur la clé (<https://www.ventoy.net>), en laissant « Secure Boot support »
   activé.
2. Copiez le fichier ISO sur la partition Ventoy comme n'importe quel fichier.
3. Au démarrage, Ventoy liste les ISO : choisissez winbootfix. La première fois avec Secure Boot, Ventoy
   demande d'enregistrer sa clé (« Enroll key » puis redémarrage) : suivez son écran.

### balenaEtcher (Windows, macOS, Linux)

1. Téléchargez-le sur <https://etcher.balena.io>, lancez-le.
2. « Flash from file » → l'ISO, « Select target » → la clé, « Flash! ».

### dd (Linux / macOS, experts)

```sh
lsblk                                  # repérez la clé, ex. /dev/sdb (PAS une partition comme /dev/sdb1)
sudo dd if=winbootfix-X.Y.Z-amd64.iso of=/dev/sdX bs=4M status=progress conv=fsync
```

Sous macOS : `diskutil list`, `diskutil unmountDisk /dev/diskN`, puis `of=/dev/rdiskN bs=4m`.

## 3. Démarrer le PC en panne sur la clé

1. Branchez la clé, allumez le PC et appuyez plusieurs fois sur la **touche du menu de démarrage**
   (voir le tableau de la [FAQ BIOS](bios-faq.fr.md#touches-du-menu-de-démarrage)).
2. Choisissez l'entrée qui commence par **`UEFI:`** suivie du nom de la clé.
3. Le menu winbootfix s'ouvre au bout d'une minute environ.

Rien ne se passe / « Secure Boot violation » ? Voir la [FAQ BIOS](bios-faq.fr.md#secure-boot).

## Variante WinPE

L'ISO WinPE optionnelle (créée avec `build-winpe.ps1`) s'écrit de la même façon. Avec Rufus, gardez les
réglages proposés pour une image Windows.
