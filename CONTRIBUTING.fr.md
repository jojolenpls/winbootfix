# Contribuer à winbootfix

[English](CONTRIBUTING.md)

Merci ! Les trois contributions les plus utiles ne demandent pas de savoir programmer.

## 1. Signaler un cas non couvert

winbootfix n'a pas réparé votre PC, ou a dit quelque chose de faux ?

1. Récupérez le rapport : menu **« Exporter le rapport »** de la clé USB, ou `/var/log/winbootfix-reports/`
   sous Linux, ou `C:\winbootfix\reports\` dans Windows.
2. Ouvrez un ticket avec le modèle **« Cas non couvert »** et joignez le fichier `.txt` (et `.json`).

Les rapports sont anonymisés (noms d'utilisateur, numéros de série, clés BitLocker retirés). Relisez-le
quand même avant de le publier.

## 2. Ajouter une langue

Voir [docs/translating.md](docs/translating.md) : copiez `locales/en.json`, traduisez les valeurs, gardez les
`{variables}`, lancez `python3 -m pytest tests/unit/test_i18n.py`, ouvrez une pull request.

## 3. Enrichir la base DLL → logiciel

[`src/winbootfix/data/dll_db.json`](src/winbootfix/data/dll_db.json) indique quoi réinstaller quand une DLL de
System32 / SysWOW64 pose problème (exemple : `wintab32.dll` → pilotes de tablette graphique).

```json
"wintab32.dll": {"software": ["Wacom tablet driver", "Huion tablet driver"]}
```

- nom de fichier en minuscules, `software` = des noms qu'un débutant peut chercher ;
- une seule entrée par pull request, c'est très bien ; indiquez d'où vient la DLL ;
- `python3 -m pytest tests/unit/test_data.py` vérifie le format.

Les autres fichiers de données fonctionnent de la même façon : `gpu.json` (fabricants de cartes graphiques,
pages officielles des pilotes), `bios_hints.json` (menus BIOS par fabricant), `languages.json` (identifiants
de langue et de clavier Windows), `critical_files.json`, `pe_allowlist.json` (une preuve est exigée pour une
exception).

## Code

```sh
sudo apt install python3-hivex python3-pytest shellcheck gdisk dosfstools ntfs-3g
make test            # tests unitaires
sudo make test-root  # intégration sur périphériques loop (vrais FAT32 / NTFS)
make lint            # ruff + shellcheck
```

Règles :

- uniquement la bibliothèque standard dans `src/` (cible : Python 3.9, présent sur les anciens systèmes
  live) ;
- toute modification d'un disque, de la NVRAM ou d'une ruche passe par une `Action` exécutée par
  l'`Executor` et appelle `core.guard.require_write()` ; le code de diagnostic n'écrit jamais ;
- aucune dépendance à la langue de Windows : valeurs du registre, en-têtes PE, GUID ; chemins Windows
  résolus avec `system.winpath` (insensible à la casse) ;
- tout texte affiché est une clé de traduction présente dans `en.json` et `fr.json`, en langage courant ;
- un test avec chaque changement (`tests/helpers/fakewin.py` crée de faux Windows, ruches et fichiers PE).

Les scripts PowerShell doivent tourner sous Windows PowerShell 5.1 ; tests avec Pester 5 (`tests/windows`).

## Publier une version

Augmentez `__version__` dans `src/winbootfix/__init__.py`, mettez à jour `CHANGELOG.md`,
`packaging/debian/changelog` et `packaging/aur/PKGBUILD`, puis poussez un tag `vX.Y.Z` : GitHub Actions
construit et publie l'ISO, sa somme SHA256, le `.deb`, l'archive des sources et celle des scripts Windows.
