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
KEY_BUMP_STRATEGY = "bump_strategy" 

# Klíče pro jednotlivé strategie
BUMP_NONE = "none"
BUMP_MAJOR = "major"
BUMP_MINOR = "minor"
BUMP_PATCH = "patch"
BUMP_BUILD = "build"

# --- NOVÉ KONSTANTY PRO INNO SETUP ---
KEY_CREATE_INSTALLER = "create_installer"

# Klíče parametrů
KEY_INNO_PUBLISHER = "inno_publisher"
KEY_INNO_URL = "inno_url"
KEY_INNO_LICENSE = "inno_license"
KEY_INNO_WIZARD_IMAGE = "inno_wizard_image"
KEY_INNO_WIZARD_SMALL_IMAGE = "inno_wizard_small_image"
KEY_INNO_WIZARD_STYLE = "inno_wizard_style"
KEY_INNO_COMPRESSION = "inno_compression"
KEY_INNO_TASK_DESKTOP = "inno_task_desktop"
KEY_INNO_LANGUAGES = "inno_languages"
KEY_INNO_ICON = "inno_icon"

# Defaultní hodnoty (pro migraci a nové projekty)
DEFAULT_INNO_CONFIG = {
    KEY_INNO_PUBLISHER: "My Company",
    KEY_INNO_URL: "",
    KEY_INNO_LICENSE: "",
    KEY_INNO_WIZARD_IMAGE: "",
    KEY_INNO_WIZARD_SMALL_IMAGE: "",
    KEY_INNO_WIZARD_STYLE: "modern",
    KEY_INNO_COMPRESSION: "lzma",
    KEY_INNO_TASK_DESKTOP: True,
    KEY_INNO_LANGUAGES: "english, czech",
    KEY_INNO_ICON: "windows/runner/resources/app_icon.ico"
}