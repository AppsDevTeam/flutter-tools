# src/constants.py
"""
Centrální soubor pro ukládání globálních konstant,
textových šablon a názvů souborů.
"""

# Název konfiguračního souboru v každém projektu
ADT_PROJECT_CONFIG_FILENAME = "adt_tools_config.env"

# Šablona pro nově vytvořený konfigurační soubor
ADT_TOOLS_ENV_EXAMPLE = """PACKAGE_NAME=\"com.vasetvafirma.vasappka\"

# Nastavení pro Desktop (macOS, Linux, Windows)
# DESKTOP_APP_NAME="MojeAplikace"

# Ukázka pro flavors
# FIREBASE_APP_ID_cashdesk_prod="xxx"
# FIREBASE_APP_ID_cashdesk_prerelease="xxx"
# FIREBASE_APP_ID_tapygo_prod="xxx"
# FIREBASE_APP_ID_tapygo_prerelease="xxx"

# Ukázka dart defines
# DART_DEFINES_SHOW_BANNER_prod=false
# DART_DEFINES_SHOW_BANNER_prerelease=true

# Ukázka dart defines načtených ze souboru (--dart-define-from-file).
# Vhodné pro skupinu hodnot, které patří k sobě a nesmí se dostat do buildu
# jiného flavoru; na stejný soubor se pak odkáže i launch.json v IDE.
# DART_DEFINE_FILES_tapygo=dart_defines/tapygo.json

# Odkazy na tikety v release notes psaných přes Claude (viz README, Release notes).
# JIRA_BROWSE_URL=https://firma.atlassian.net/browse
# JIRA_PROJECT_KEYS=TAPY,PAY   # jiné kódy v Trello slugu (tvsb-635) pak nejsou Jira
# Model a effort pro Claude lze per projekt přepsat; výchozí jsou v nástroji.
# RELEASE_NOTES_MODEL=sonnet
# RELEASE_NOTES_EFFORT=medium
# RELEASE_NOTES_FALLBACK_MODEL=opus

# Ukázka google services pro flavors
# IOS_PLIST_DEFAULT=ios/Firebase/GoogleService-Info.plist
# IOS_PLIST_tapygo_prod=ios/Firebase/GoogleService-Info-Tapygo.plist
# IOS_PLIST_tapygo_prerelease=ios/Firebase/GoogleService-Info-Tapygo-Prerelease.plist
# IOS_PLIST_cashdesk_prod=ios/Firebase/GoogleService-Info.plist
# IOS_PLIST_cashdesk_prerelease=ios/Firebase/GoogleService-Info-Prerelease.plist
"""

# Speciální název pro výchozí preset
PRESET_MANUAL = "Ručně"

# Klíče pro nastavení záložky "Nezalomitelná mezera"
KEY_TRANSLATIONS_PATH = "translations_path"

# Klíče pro nastavení záložky "Build"
KEY_PRESET = "preset"
KEY_BUILD_TYPE = "build_type"
KEY_BUILD_MODE = "build_mode"
KEY_FLAVOR = "flavor"
KEY_ENV = "env"
KEY_GIT_PUSH = "git_push"
KEY_DISABLE_OBFUSCATION = "disable_obfuscation"
KEY_UPLOAD_SYMBOLS = "upload_symbols"
KEY_INSTALL_COCOAPODS = "install_cocoapods"
KEY_CHECK_SQLITE_WEB = "check_sqlite_web"
KEY_UPDATE_CHANGELOG = "update_changelog"
KEY_CHANGELOG_VIA_CLAUDE = "changelog_via_claude"

KEY_BUMP_STRATEGY = "bump_strategy"

# Klíče pro jednotlivé strategie
BUMP_NONE = "none"
BUMP_MAJOR = "major"
BUMP_MINOR = "minor"
BUMP_PATCH = "patch"
BUMP_BUILD = "build"

# Release notes přes Claude Code CLI (záložka Build, "Sepsat přes Claude").
# Slash command, který nástroj v projektu zakládá a volá: .claude/commands/<name>.md
RELEASE_NOTES_COMMAND_NAME = "release-notes"
# Aliasy, ne plná ID modelů: alias CLI vždy přeloží na aktuální model dané řady, takže
# vyřazení konkrétní verze (např. claude-sonnet-5-5) nic nerozbije. Kdyby zanikl celý
# alias, CLI skončí chybou, nástroj ji vypíše a spadne na výpis git log — pak stačí
# změnit hodnotu tady, nebo dočasně RELEASE_NOTES_MODEL v adt_tools_config.env.
RELEASE_NOTES_MODEL = "sonnet"
RELEASE_NOTES_EFFORT = "medium"
RELEASE_NOTES_FALLBACK_MODEL = "opus"
# Claude čte diffy a píše, běžně 1–3 minuty; po tomhle limitu ho nástroj ukončí
# a použije výpis git log, aby zaseknutý proces nedržel build.
RELEASE_NOTES_TIMEOUT_S = 15 * 60
