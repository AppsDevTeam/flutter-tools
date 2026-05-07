# adt_flutter_tools

Desktopová utilita pro automatizaci buildů Flutter projektů (Android / iOS / Web), úpravy `pubspec.yaml`, generování CHANGELOGu, nahrávání symbolů na Firebase Crashlytics a další běžné kroky.

## První spuštění

Před prvním použitím spusťte interaktivní setup, který detekuje chybějící závislosti a nabídne jejich instalaci:

```bash
./setup.sh
```

Pokud po stažení (např. ze ZIPu) script není spustitelný, povolte to:

```bash
chmod +x setup.sh
```

Na Windows v Git Bash / WSL stejné, v PowerShellu spusťte: `bash setup.sh`.

Skript funguje na **macOS, Linuxu (apt / dnf / pacman / zypper) i Windows** (Git Bash / WSL — používá winget / scoop / choco). Pokud je dostupných víc package managerů (např. `brew` i `npm` pro Firebase CLI), skript se zeptá, který chcete použít.

### Co setup zkontroluje a případně nainstaluje

| Závislost | Nutné | Použití |
|---|---|---|
| Git | ano | klonování / verzování |
| Flutter SDK | ano | vlastní buildy |
| Python 3 + Tkinter | ano | běh této aplikace (GUI) |
| Firebase CLI | volitelné | nahrávání symbolů na Crashlytics (Android) |
| CocoaPods (jen macOS) | volitelné | iOS buildy |

Bez Pythonu 3 a Tkinteru aplikace nepoběží — setup v takovém případě skončí chybou. Ostatní závislosti lze přeskočit, pokud odpovídající funkce nepoužíváte.

## Spuštění aplikace

```bash
python3 main.py
```
