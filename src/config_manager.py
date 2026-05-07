import json
import os
from .constants import (
    PRESET_MANUAL, KEY_TRANSLATIONS_PATH, KEY_BUILD_TYPE, KEY_BUILD_MODE,
    KEY_FLAVOR, KEY_ENV, KEY_BUMP_STRATEGY, BUMP_PATCH, KEY_GIT_PUSH,
    KEY_DISABLE_OBFUSCATION, KEY_UPLOAD_SYMBOLS, KEY_INSTALL_COCOAPODS,
    KEY_CHECK_SQLITE_WEB, KEY_UPDATE_CHANGELOG
)

# Defaults applied to every build preset; used both for new projects and lazy
# migration of existing config.json entries that miss newer keys.
PRESET_DEFAULTS = {
    KEY_BUILD_TYPE: "apk",
    KEY_BUILD_MODE: "release",
    KEY_FLAVOR: "",
    KEY_ENV: "",
    KEY_BUMP_STRATEGY: BUMP_PATCH,
    KEY_GIT_PUSH: True,
    KEY_DISABLE_OBFUSCATION: False,
    KEY_UPLOAD_SYMBOLS: True,
    KEY_INSTALL_COCOAPODS: True,
    KEY_CHECK_SQLITE_WEB: False,
    KEY_UPDATE_CHANGELOG: False,
}

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ROOT_DIR = os.path.dirname(SRC_DIR)
DEFAULT_CONFIG_PATH = os.path.join(APP_ROOT_DIR, 'config.json')

class ConfigManager:
    """Spravuje ukládání a načítání projektů do souboru config.json."""
    
    def __init__(self, config_file=DEFAULT_CONFIG_PATH):
        self.config_file = config_file
        print(f"--- ConfigManager používá soubor: {self.config_file} ---")
        self.config = self._load_data_from_file()

    def _load_data_from_file(self):
        """Načte data ze souboru nebo vrátí výchozí."""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            config_data = {}

        # Zajistíme existenci všech klíčů
        config_data.setdefault('projects', {})
        config_data.setdefault('last_project', None)
        config_data.setdefault('last_tab', 0)
        
        return config_data

    def save_config(self):
        """Uloží aktuální konfiguraci do souboru."""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4)

    def get_projects(self):
        return self.config.get('projects', {})

    def add_project(self, name, path):
        """Přidá projekt s výchozí strukturou."""
        if 'projects' not in self.config:
            self.config['projects'] = {}
            
        self.config['projects'][name] = {
            "path": path,
            "flavors": [],
            "envs": [],
            "last_selected_build_preset": "Ručně",
            "build_presets": {
                PRESET_MANUAL: dict(PRESET_DEFAULTS)
            },
            "nbsp_settings": {
                KEY_TRANSLATIONS_PATH: "assets/translations"
            }
        }
        self.save_config()

    def rename_project(self, old_name, new_name):
        """Přejmenuje projekt (změní klíč v dict)."""
        projects = self.config.get('projects', {})
        
        if old_name not in projects:
            return False
        if new_name in projects:
            return False # Nové jméno už existuje
            
        # Převedeme data pod nový klíč
        project_data = projects.pop(old_name)
        projects[new_name] = project_data
        
        # Pokud byl tento projekt poslední otevřený, aktualizujeme i odkaz
        if self.config.get('last_project') == old_name:
            self.config['last_project'] = new_name
            
        self.save_config()
        return True

    def update_project_path(self, name, new_path):
        """Aktualizuje cestu k projektu."""
        project_data = self._get_project(name)
        if project_data:
            project_data['path'] = new_path
            self.save_config()
            return True
        return False

    def delete_project(self, name):
        """Smaže projekt z konfigurace."""
        if name in self.config['projects']:
            del self.config['projects'][name]
            if self.config['last_project'] == name:
                self.config['last_project'] = None
            self.save_config()

    def _get_project(self, project_name):
        """Bezpečně vrátí slovník projektu a zajistí existenci klíčů."""
        projects = self.config.get('projects', {})
        if project_name not in projects:
            return None
        
        project_data = projects[project_name]
        
        if not isinstance(project_data, dict):
             print(f"CHYBA: Záznam pro projekt '{project_name}' není slovník!")
             return None
        
        project_data.setdefault("flavors", [])
        project_data.setdefault("envs", [])
        project_data.setdefault("build_presets", {PRESET_MANUAL: {}})
        project_data.setdefault("nbsp_settings", {KEY_TRANSLATIONS_PATH: "assets/translations"})
        project_data.setdefault("last_selected_build_preset", PRESET_MANUAL)
        
        return project_data

    def get_last_project(self):
        return self.config.get('last_project')

    def set_last_project(self, name):
        if name in self.config.get('projects', {}):
            self.config['last_project'] = name
            self.save_config()

    def get_project_path(self, name):
        """Vrátí cestu k projektu."""
        project_data = self.get_projects().get(name)
        if isinstance(project_data, dict):
            return project_data.get("path")
        return None

    def validate_project(self, name):
        """Kontroluje, zda projekt existuje a zda jeho cesta je platná."""
        if not name:
            return False
        path = self.get_project_path(name) 
        if not path or not os.path.isdir(path):
            print(f"Konfigurace: Cesta pro projekt '{name}' nebyla nalezena: {path}")
            return False
        return True

    def get_last_tab(self):
        return self.config.get('last_tab', 0)

    def set_last_tab(self, index):
        self.config['last_tab'] = index
        self.save_config()

    # --- Seznamy (Flavors, Envs) ---
    
    def get_project_list(self, project_name, list_name):
        """Vrátí specifický seznam (flavors, envs) pro projekt."""
        project_data = self._get_project(project_name)
        return project_data.get(list_name, []) if project_data else []

    def save_project_list(self, project_name, list_name, new_list):
        """Uloží specifický seznam (flavors, envs) pro projekt."""
        project_data = self._get_project(project_name)
        if project_data:
            project_data[list_name] = new_list
            self.save_config()

    # --- Presety Buildu ---

    # --- ZDE JE OPRAVENÁ METODA ---
    def get_project_build_presets(self, project_name):
        """
        Vrátí slovník všech build presetů pro daný projekt.
        Vždy zajistí přítomnost klíče PRESET_MANUAL ('Ručně') a doplní
        chybějící klíče v každém presetu (lazy migrace).
        """
        project_data = self._get_project(project_name)
        default_presets = {PRESET_MANUAL: dict(PRESET_DEFAULTS)}

        if not project_data:
            return default_presets

        presets = project_data.get('build_presets', default_presets)

        # 1. Pojistka proti špatnému typu
        if not isinstance(presets, dict):
            print(f"OPRAVA: 'build_presets' pro '{project_name}' byl poškozen. Resetuji na výchozí.")
            project_data['build_presets'] = default_presets
            self.save_config()
            return default_presets

        # 2. Pojistka: VŽDY zajistit existenci "Ručně"
        # I když je v configu smazaný nebo prázdný, v paměti (a pro UI) ho chceme vidět.
        if PRESET_MANUAL not in presets:
            presets[PRESET_MANUAL] = dict(PRESET_DEFAULTS)

        # 3. Lazy migrace: doplň chybějící klíče v každém presetu výchozími hodnotami
        if self._migrate_preset_defaults(presets):
            self.save_config()

        return presets
    # --- KONEC OPRAVENÉ METODY ---

    def _migrate_preset_defaults(self, presets):
        """
        Doplní v každém presetu chybějící klíče z PRESET_DEFAULTS.
        Vrací True, pokud bylo něco doplněno (volající má pak uložit config).
        """
        changed = False
        for preset_name, settings in presets.items():
            if not isinstance(settings, dict):
                continue
            for key, default_val in PRESET_DEFAULTS.items():
                if key not in settings:
                    settings[key] = default_val
                    changed = True
                    print(f"MIGRACE: '{preset_name}' doplněn klíč '{key}' = {default_val}")
        return changed

    def save_project_build_preset(self, project_name, preset_name, settings):
        """Uloží nebo přepíše nastavení pro jeden build preset v rámci projektu."""
        project_data = self._get_project(project_name)
        if project_data:
            # Pojistka, kdyby 'build_presets' stále nebyl dict
            if not isinstance(project_data['build_presets'], dict):
                project_data['build_presets'] = {PRESET_MANUAL: {}}
            project_data['build_presets'][preset_name] = settings
            self.save_config()

    def delete_project_build_preset(self, project_name, preset_name):
        """Smaže jeden build preset z projektu."""
        project_data = self._get_project(project_name)
        # Použijeme .get() pro bezpečný přístup
        if project_data and preset_name in project_data.get('build_presets', {}):
            if preset_name == PRESET_MANUAL:
                print(f"Nelze smazat '{preset_name}' preset.")
                return
            del project_data['build_presets'][preset_name]
            self.save_config()

    def get_last_build_preset_name(self, project_name):
        """Vrátí název naposledy použitého build presetu."""
        project_data = self._get_project(project_name)
        default = PRESET_MANUAL
        return project_data.get('last_selected_build_preset', default) if project_data else default

    def save_last_build_preset_name(self, project_name, preset_name):
        """Uloží název naposledy použitého build presetu."""
        project_data = self._get_project(project_name)
        if project_data:
            project_data['last_selected_build_preset'] = preset_name
            self.save_config()

    # --- Nastavení NBSP ---

    def get_project_nbsp_settings(self, project_name):
        """Vrátí nastavení pro NBSP záložku."""
        project_data = self._get_project(project_name)
        default = {KEY_TRANSLATIONS_PATH: "assets/translations"}
        
        if not project_data:
            return default
            
        settings = project_data.get('nbsp_settings', default)
        
        # Pojistka
        if not isinstance(settings, dict):
            print(f"OPRAVA: 'nbsp_settings' pro '{project_name}' byl poškozen. Resetuji.")
            project_data['nbsp_settings'] = default
            self.save_config()
            return default
            
        return settings

    def save_project_nbsp_settings(self, project_name, settings):
        """Uloží nastavení pro NBSP záložku."""
        project_data = self._get_project(project_name)
        if project_data:
            project_data['nbsp_settings'] = settings
            self.save_config()