# FAQ BIOS / UEFI

[English](bios-faq.md)

Les noms de menus changent selon les versions de micrologiciel : les chemins ci-dessous sont les plus
courants, pas des garanties. Ils sont stockés dans
[`bios_hints.json`](../src/winbootfix/data/bios_hints.json), que winbootfix utilise pour ses conseils. Les
menus sont presque toujours en anglais, même sur un PC français : ils sont donc cités en anglais.

## Touches du menu de démarrage

| Fabricant | Entrer dans le BIOS | Menu de démarrage ponctuel |
|---|---|---|
| ASUS | Suppr ou F2 | F8 (PC fixe), Échap (portable) |
| MSI | Suppr | F11 |
| Gigabyte / AORUS | Suppr | F12 |
| ASRock | F2 ou Suppr | F11 |
| Dell | F2 | F12 |
| HP | F10 (Échap affiche le menu de démarrage) | F9 |
| Lenovo | F2, F1 (ThinkPad/ThinkCentre) ou bouton Novo | F12 |
| Acer | F2 | F12 (activer d'abord « F12 Boot Menu » dans Main) |
| Microsoft Surface | maintenir Volume + et appuyer sur Marche | maintenir Volume - et appuyer sur Marche |

Windows peut aussi redémarrer dans le BIOS : Paramètres > Système > Récupération > Démarrage avancé >
Redémarrer maintenant > Dépannage > Options avancées > Changer les paramètres du microprogramme UEFI.

## « Aucun disque interne visible » : VMD, Intel RST, RAID et AHCI

Beaucoup de PC récents (Intel 11e génération et suivantes, surtout les portables) placent le disque NVMe ou
SATA derrière **Intel VMD** ou **Intel RST (mode RAID)**. Windows a le pilote, Linux pas toujours : winbootfix
ne voit alors aucun disque et l'explique (code de sortie 14).

| Fabricant | Réglage habituel |
|---|---|
| ASUS | Advanced > PCH Storage Configuration > SATA Mode Selection : AHCI ; Advanced > VMD setup menu > Enable VMD controller : Disabled |
| MSI | Settings > Advanced > Integrated Peripherals > SATA Mode : AHCI ; Intel VMD technology : Disabled |
| Gigabyte | Settings > IO Ports > SATA and RST Configuration > SATA Mode Selection : AHCI ; Intel VMD Technology : Disabled |
| ASRock | Advanced > Storage Configuration > SATA Mode : AHCI ; VMD Configuration > Enable VMD controller : Disabled |
| Dell | Storage > SATA/NVMe Operation : AHCI/NVMe au lieu de « RAID On » |
| HP | Advanced > System Options > décocher « Configure Storage Controller for Intel Optane / VMD » |
| Lenovo | Configuration > Storage : AHCI au lieu de « Intel RST Premium » / désactiver « VMD Controller » |
| Acer | Main > SATA Mode / VMD Controller (Ctrl+S sur l'onglet Main l'affiche sur certains modèles) |

**Important :**

1. **Notez le réglage d'origine.**
2. Changez-le, démarrez la clé winbootfix, réparez.
3. **Remettez le réglage d'origine avant de démarrer Windows** : un Windows installé en mode RST/VMD peut
   s'arrêter avec `INACCESSIBLE_BOOT_DEVICE` en mode AHCI.
4. Une vraie grappe RAID de plusieurs disques ne doit jamais passer en AHCI : utilisez plutôt la variante
   WinPE avec le pilote Intel RST (`build-winpe.ps1 -DriverPath`).

L'ISO winbootfix utilise un noyau Debian qui contient le pilote VMD : les disques derrière VMD sont souvent
visibles sans rien changer ; le mode « RAID » RST en SATA ne l'est généralement pas.

## Secure Boot

L'ISO winbootfix démarre avec Secure Boot **activé** : elle utilise le shim de Debian signé par Microsoft
(« Microsoft Corporation UEFI CA », autorité tierce).

- **« Secure Boot violation », « Image failed to verify » ou rien ne se passe** : certains PC ne font
  confiance qu'à Windows par défaut (Microsoft Surface, modèles Lenovo/HP « Secured-core »). Dans le BIOS,
  autorisez l'**autorité tierce** (« Allow Microsoft 3rd Party UEFI CA », « Microsoft & 3rd party CA » sur
  Surface), ou désactivez Secure Boot le temps de la réparation puis réactivez-le.
- **BitLocker** : modifier Secure Boot peut faire demander la clé de récupération BitLocker au démarrage
  suivant. Ayez la clé sous la main (<https://account.microsoft.com/devices/recoverykey>).
- **Fichiers de démarrage signés en 2023** : depuis les correctifs BlackLotus, certains BIOS ne font plus
  confiance à la signature de 2011. winbootfix lit les bases du micrologiciel (db/dbx) et copie le jeu
  adapté (`Windows\Boot\EFI` ou `Windows\Boot\EFI_EX`).

| Fabricant | Chemin habituel |
|---|---|
| ASUS | Boot > Secure Boot > OS Type / Key Management |
| MSI | Settings > Advanced > Windows OS Configuration > Secure Boot |
| Gigabyte | Boot > Secure Boot |
| ASRock | Security > Secure Boot |
| Dell | Boot Configuration (ou Secure Boot) > Enable Secure Boot |
| HP | Advanced (ou Security) > Secure Boot Configuration |
| Lenovo | Security > Secure Boot |
| Acer | Boot > Secure Boot (définir d'abord un mot de passe superviseur dans Security) |

## CSM / Legacy

Windows 10/11 sur un disque GPT démarre en mode **UEFI** : le CSM (Compatibility Support Module) doit être
désactivé et la clé démarrée sur son entrée « UEFI: ». Si la clé a démarré en mode Legacy, winbootfix le
signale. Un Windows installé en mode Legacy/MBR est détecté mais pas réparé par cette version.

| Fabricant | Chemin habituel |
|---|---|
| ASUS | Boot > CSM > Launch CSM : Disabled |
| MSI | Settings > Advanced > Windows OS Configuration > BIOS UEFI/CSM Mode : UEFI |
| Gigabyte | Boot > CSM Support : Disabled |
| ASRock | Boot > CSM : Disabled |
| Dell | Boot Configuration > Enable Legacy Option ROMs : Off |
| HP | Secure Boot Configuration > Legacy Support : Disabled |
| Lenovo | Startup > UEFI/Legacy Boot : UEFI Only |
| Acer | Boot > Boot Mode : UEFI |
