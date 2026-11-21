# winbootfix

[English](README.md) · **Français**

Outil libre et gratuit (licence MIT) qui répare automatiquement deux problèmes fréquents de Windows 10 et 11 :

1. **Le PC ne démarre plus sur Windows** parce que l'entrée « Windows Boot Manager » a disparu du BIOS/UEFI
   (ou parce que les fichiers de démarrage ou la configuration BCD sont abîmés).
2. **Windows démarre mais fonctionne mal** après une réparation ou une mise à jour : pilote graphique non
   chargé (« Carte graphique de base Microsoft », fenêtres blanches), erreurs `0xc000007b` « Image
   incorrecte », DLL du mauvais type ou abîmées, fichiers système endommagés.

Il se présente sous trois formes :

| Livrable | Pour qui | Où |
|---|---|---|
| **Clé USB de réparation (ISO)** | tout le monde, même si Windows ne démarre plus | Releases : `winbootfix-X.Y.Z-amd64.iso` |
| **Outil Linux `winbootfix`** | si vous avez déjà Linux sur le PC | [Installation](#installer-loutil-sous-linux) |
| **Script Windows `winbootfix-post.ps1`** (+ variante WinPE) | pour finir la réparation dans Windows | Releases : `winbootfix-windows.zip` |

> Par défaut, winbootfix **ne modifie rien** : il fait un diagnostic. Les réparations ne se font qu'après
> votre confirmation, et tout est sauvegardé avant. Il ne formate jamais rien et ne supprime aucun fichier
> (les fichiers suspects sont mis en quarantaine).

---

## Guide pas à pas (débutants)

Il vous faut une clé USB d'au moins 1 Go et, si votre PC ne démarre plus, **un autre ordinateur** pour
préparer la clé.

1. **Téléchargez l'ISO** dans la page [Releases](https://github.com/jojolenpls/winbootfix/releases)
   (`winbootfix-X.Y.Z-amd64.iso`) et vérifiez sa somme SHA256 (fichier `.sha256`).
2. **Préparez la clé USB** avec Rufus (Windows), balenaEtcher (Windows, macOS, Linux) ou Ventoy.
   Le [guide de création de la clé](docs/usb-guide.fr.md) explique chaque outil. Conseil : avec Rufus en
   « mode ISO » ou avec Ventoy, le rapport et les sauvegardes peuvent être enregistrés sur la clé.
3. **Démarrez le PC sur la clé** : allumez-le en appuyant sur la touche du menu de démarrage
   (souvent F12, F11, F8 ou Échap ; voir la [FAQ BIOS](docs/bios-faq.fr.md)) et choisissez l'entrée qui
   commence par **« UEFI: »**. Secure Boot peut rester activé.
4. Le menu winbootfix s'ouvre tout seul, dans la langue de votre Windows (clavier AZERTY compris) :

   ```
   ┌──────────────────────────── Choix ─────────────────────────────┐
   │ winbootfix - réparer le démarrage et la santé de Windows.      │
   │ Que voulez-vous faire ?                                        │
   │                                                                │
   │        Diagnostiquer et réparer (recommandé)                   │
   │        Diagnostiquer seulement (ne modifie rien)               │
   │        Mode expert                                             │
   │        Exporter le rapport (pour le partager sur un forum)     │
   │        Langue / Language                                       │
   │        Ligne de commande (shell)                               │
   │        Redémarrer l'ordinateur                                 │
   │        Éteindre l'ordinateur                                   │
   │                                                                │
   │                 <OK>                  <Retour>                 │
   └────────────────────────────────────────────────────────────────┘
   ```

5. Choisissez **« Diagnostiquer et réparer »**. winbootfix explique ce qu'il a trouvé, puis ce qu'il va
   faire, en langage courant, et vous demande la permission. Exemple :

   ```
   Ce que j'ai trouvé
   ==================
   x [CRITIQUE] L'entrée « Windows Boot Manager » a disparu du BIOS : c'est pour cela que le PC ne
   démarre plus Windows.
       -> L'entrée peut être recréée sans toucher à vos fichiers.
   x [PROBLÈME] Le pilote graphique « NVIDIA GeForce RTX 3070 » est désactivé (service nvlddmkm).
       -> Il peut être réactivé maintenant.
   x [PROBLÈME] System32\wintab32.dll n'est pas du bon type (x86) pour ce dossier : les programmes qui
   l'utilisent échouent avec l'erreur 0xc000007b. Éditeur : Wacom Technology Corp. Provient de : Wacom
   tablet driver, Huion tablet driver, XP-Pen tablet driver, Gaomon / Veikk tablet driver.
       -> Le fichier peut être mis en quarantaine ; réinstallez ensuite : Wacom tablet driver, ...

   Voici ce que je vais faire
   ==========================
   1. Recréer l'entrée de démarrage « Windows Boot Manager » dans le BIOS (disque Samsung SSD 980
   (500 GB, NVME), partition 1). Vos fichiers ne seront pas touchés.
   2. Réactiver le pilote graphique « NVIDIA GeForce RTX 3070 » (service nvlddmkm) pour que Windows le
   charge à nouveau.
   3. Déplacer le fichier abîmé Windows\System32\wintab32.dll dans C:\winbootfix_quarantine (il n'est
   pas supprimé et peut être remis en place).
   4. Préparer une réparation automatique qui se lancera à la prochaine ouverture de session Windows
   (vérification des fichiers système, pilote graphique).

   Avant toute modification, une sauvegarde est faite (partition EFI, entrées de démarrage, registre).
   Vos fichiers personnels ne sont pas touchés.
   Voulez-vous que je le fasse ? [o/N]
   ```

6. Quand c'est fini, choisissez **« Redémarrer l'ordinateur »** et retirez la clé.
7. À la première ouverture de session, une fenêtre **winbootfix** s'ouvre toute seule : elle vérifie les
   fichiers système (DISM puis SFC), répare le pilote graphique et indique quels logiciels réinstaller.
   Laissez-la aller jusqu'au bout (30 à 60 minutes). Le PC ne redémarre jamais sans votre accord.

Toujours un problème ? Choisissez **« Exporter le rapport »** dans le menu (ou récupérez
`C:\winbootfix\reports\`) et ouvrez un [ticket « Cas non couvert »](https://github.com/jojolenpls/winbootfix/issues/new/choose).
Le rapport est anonymisé (noms d'utilisateur, numéros de série et clés BitLocker retirés).

---

## Ce que fait winbootfix

### Réparation du démarrage (équivalent de `bcdboot C:\Windows /s S: /f UEFI`, sans Windows)

Vérifications : démarrage en mode UEFI, partitions EFI (FAT32, type `c12a7328-…`), partitions Windows (NTFS
avec `Windows\System32`), BitLocker, hibernation / démarrage rapide, disques invisibles (VMD/RST/RAID).

Réparation par niveaux, chacun seulement si nécessaire :

| Niveau | Problème | Réparation |
|---|---|---|
| a | entrée NVRAM absente, désactivée ou pointant ailleurs | `efibootmgr -c` ; si GRUB/systemd-boot est en premier, il le reste (sauf `--windows-first`) |
| b | `EFI\Microsoft\Boot\bootmgfw.efi` absent ou abîmé | copie depuis `Windows\Boot\EFI` (jeu signé 2011 ou 2023 selon votre BIOS), polices, ressources ; `EFI\Boot\bootx64.efi` seulement s'il est libre ou déjà à Microsoft |
| c | `BCD` absent, illisible ou pointant vers une autre partition | génération depuis `BCD-Template` (**expérimental**, voir [docs/BCD.md](docs/BCD.md)) ; Windows régénère ensuite un BCD officiel avec `bcdboot` au premier démarrage |

### Santé de Windows (hors ligne)

- **Pilote graphique** NVIDIA / AMD / Intel, y compris PC portables à deux GPU : service désactivé
  (`Start=4`), service ou fichier `.sys` disparu, paquet absent du DriverStore, carte sur « Carte graphique
  de base Microsoft ». Réparation immédiate de `Start`, le reste par le script post-réparation.
- **DLL** de `System32` / `SysWOW64` : mauvaise architecture (x86 dans System32, x64 dans SysWOW64), taille
  nulle, en-tête invalide. Les assemblys .NET AnyCPU et les DLL de ressources ne sont pas signalées. Les DLL
  tierces vont en quarantaine (`C:\winbootfix_quarantine\` + `restore.cmd`) ; les DLL Microsoft ne sont
  jamais déplacées (SFC s'en charge). La [base DLL → logiciel](src/winbootfix/data/dll_db.json) indique quoi
  réinstaller.
- **Intégrité** : fichiers essentiels absents ou vides, `pending.xml` bloqué, erreurs du journal CBS, ruches
  de registre abîmées.

### Script post-réparation (Windows)

`winbootfix-post.ps1` s'exécute à la prochaine connexion (RunOnce) ou à la main (double-clic sur
`winbootfix-post.cmd`) : `bcdboot` si besoin, `DISM /Online /Cleanup-Image /RestoreHealth` puis
`sfc /scannow`, pilote graphique (réactivation, réinstallation depuis le DriverStore, Windows Update, pilote
officiel signé du fabricant, DDU en mode sans échec en dernier recours), liste des DLL en quarantaine,
vérification finale (version du pilote, aucune erreur `0xc000007b`). Rapport dans `C:\winbootfix\reports\`.

### Variante WinPE (optionnelle)

Sur un PC Windows avec le [Windows ADK et son module WinPE](https://learn.microsoft.com/windows-hardware/get-started/adk-install) :

```powershell
powershell -ExecutionPolicy Bypass -File .\winpe\build-winpe.ps1 -Language fr-fr
# avec pilotes Intel RST/VMD : -DriverPath C:\pilotes\rst
```

L'ISO WinPE produite ouvre un menu : réparer le démarrage (`bcdboot`, avec sauvegarde de la partition EFI),
réparer hors ligne (`DISM /Image … /RestoreHealth /Source:install.wim`, puis `sfc /offbootdir`),
déverrouiller BitLocker. Les volumes sont détectés avec les cmdlets de stockage (indépendantes de la langue).
Rien de Microsoft n'est redistribué : c'est vous qui générez l'image.

---

## Limites

| Cas | Comportement |
|---|---|
| **BitLocker** | détecté (signature `-FVE-FS-`). Avec la clé de récupération de 48 chiffres (Mode expert > BitLocker, ou `--bitlocker-key ask`), winbootfix ouvre le volume via dislocker. Un BitLocker « en attente d'activation » / suspendu s'ouvre sans clé, en lecture seule. Sans clé : arrêt, avec explications. |
| **Ancien PC en mode BIOS/Legacy (MBR)** | détecté et expliqué, **non réparé** dans cette version (piste : `bootrec` depuis le support d'installation). |
| **Clé démarrée en Legacy sur un PC UEFI** | détecté : redémarrez la clé sur l'entrée « UEFI: ». La santé de Windows reste vérifiable. |
| **Windows ARM64** | détecté et signalé, non pris en charge. L'ISO est pour PC x86-64. |
| **Disques invisibles (VMD / Intel RST / RAID)** | détecté, conseils BIOS selon le fabricant (voir la [FAQ BIOS](docs/bios-faq.fr.md)). |
| **Hibernation / démarrage rapide** | lecture seule ; le démarrage peut quand même être réparé ; pour réparer dans Windows, il faut accepter la suppression du fichier de veille prolongée (session ouverte perdue, fichiers conservés). |
| **Secure Boot** | l'ISO démarre avec Secure Boot (shim signé). Certains PC (Surface, Lenovo « Secured-core ») exigent d'autoriser « Microsoft 3rd-party UEFI CA » dans le BIOS. |
| **Partition EFI supprimée** | winbootfix ne crée ni ne formate de partition : utilisez WinPE ou demandez de l'aide. |

---

## Installer l'outil sous Linux

```sh
curl -fsSL https://raw.githubusercontent.com/jojolenpls/winbootfix/main/install.sh | sudo sh
```

ou le paquet `.deb` des Releases (`sudo apt install ./winbootfix_X.Y.Z-1_all.deb`), ou `packaging/aur/PKGBUILD`
(Arch Linux), ou depuis le dépôt : `sudo make install`.
Dépendances : `python3` (≥ 3.9), `python3-hivex`, `efibootmgr`, `ntfs-3g`, `util-linux`, `dosfstools` ;
optionnelles : `whiptail`, `dislocker`.

```
sudo winbootfix                      # diagnostic complet, aucune modification
sudo winbootfix --apply              # diagnostic puis réparation, avec confirmation
sudo winbootfix boot --apply --expert --esp /dev/nvme0n1p1
sudo winbootfix health
sudo winbootfix report --report-dir /media/usb
sudo winbootfix list-backups
sudo winbootfix restore /chemin/winbootfix-backups/20261121-130114 --apply
winbootfix --help                    # aide traduite (--lang fr|en)
```

Journal : `/var/log/winbootfix.log`. Rapports : `/var/log/winbootfix-reports/` (texte + JSON).

### Codes de sortie

| Code | Signification |
|---|---|
| 0 | rien à faire |
| 1 | problèmes trouvés (diagnostic seul) |
| 2 | réparé |
| 3 | réparé en partie |
| 4 | annulé |
| 10 | pas lancé en root |
| 11 | pas en mode UEFI / Windows en mode Legacy |
| 12 | aucun Windows trouvé |
| 13 | BitLocker verrouillé |
| 14 | aucun disque interne (VMD/RST/RAID) |
| 15 | Windows ARM64 |
| 16 | aucun emplacement sûr pour la sauvegarde |
| 64 | mauvaise utilisation |
| 70 | erreur interne |

### Sauvegardes et sécurité

Avant toute modification : archive `tar.gz` complète de la partition EFI, sortie `efibootmgr -v` et
`BootOrder`, copie de chaque ruche de registre modifiée, manifeste `manifest.json` pour `winbootfix restore`.
Depuis la clé USB, la sauvegarde va sur un support persistant (la clé si elle est en FAT32/exFAT, un autre
disque USB, ou la partition Windows) ; s'il n'y en a pas, rien n'est modifié.

---

## Construire l'ISO

```sh
docker build -t winbootfix-iso iso && docker run --rm --privileged -v "$PWD:/src" winbootfix-iso
# ou, sur Debian 13 en root : apt install live-build make && iso/build.sh
```

Debian 13 « trixie » live-build, image hybride UEFI (Secure Boot via shim signé) et BIOS, paquets épinglés sur
un instantané `snapshot.debian.org` (`iso/SNAPSHOT`) et `SOURCE_DATE_EPOCH` pour un résultat reproductible.
Le menu est en texte (whiptail) : il fonctionne sur tous les écrans, même sans pilote graphique.
Les sources des paquets Debian inclus sont disponibles sur snapshot.debian.org à la date indiquée dans
`iso/SNAPSHOT` (liste exacte : fichier `.packages` de chaque release).

## Tests

- `make test` : tests unitaires (détection, BitLocker, en-têtes PE, ruches, BCD, NVRAM, traductions, données).
- `sudo make test-root` : intégration sur de vraies images disque GPT (FAT32 + NTFS via ntfs-3g) : réparation
  complète, restauration, hibernation, BitLocker.
- `tests/iso/boot_smoke.sh` : démarrage de l'ISO dans QEMU + OVMF avec Secure Boot.
- `tests/vm/` : VM Windows 10 (anglais) et 11 (français) avec QEMU + OVMF + swtpm ; scénarios entrée NVRAM,
  fichiers EFI, BCD, double démarrage GRUB, pilote graphique / DLL x86 / fichier système. Voir
  [tests/vm/README.md](tests/vm/README.md) (ISO Windows d'évaluation nécessaires, KVM recommandé).
- GitHub Actions : lint, tests unitaires, intégration loop, Pester (Windows), paquet .deb, build et test de
  démarrage de l'ISO ; publication automatique des Releases sur les tags `vX.Y.Z`.

## Contribuer

Ajouter une langue, enrichir la base DLL → logiciel, signaler un cas non couvert : voir
[CONTRIBUTING.fr.md](CONTRIBUTING.fr.md). Architecture du code : [docs/architecture.md](docs/architecture.md).

## Licence

[MIT](LICENSE). winbootfix n'est pas affilié à Microsoft. Windows, BitLocker et les autres marques citées
appartiennent à leurs propriétaires.
