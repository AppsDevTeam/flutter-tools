import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox, simpledialog
import os
import threading
import queue

# ... (importy logiky) ...
from .ui_logger import UILogger
from .project_selection import AddProjectDialog
from ..logic.nbsp_logic import run_add_nbsp_logic
from ..logic.serializable_logic import run_json_serializable_logic
from ..logic.build_logic import run_flutter_build_logic
from ..logic.build_common import get_version_from_pubspec, calculate_bump

from ..constants import (
    ADT_TOOLS_ENV_EXAMPLE, ADT_PROJECT_CONFIG_FILENAME, PRESET_MANUAL,
    KEY_TRANSLATIONS_PATH, KEY_PRESET, KEY_BUILD_TYPE, KEY_BUILD_MODE,
    KEY_FLAVOR, KEY_ENV, KEY_BUMP_STRATEGY, BUMP_NONE, BUMP_MAJOR, 
    BUMP_MINOR, BUMP_PATCH, BUMP_BUILD, KEY_GIT_PUSH, 
    KEY_DISABLE_OBFUSCATION, KEY_UPLOAD_SYMBOLS, KEY_INSTALL_COCOAPODS,
    KEY_CHECK_SQLITE_WEB
)

class MainWindow(tk.Toplevel):
    def __init__(self, parent, config_manager, current_project_name):
        super().__init__(parent) 
        self.protocol("WM_DELETE_WINDOW", parent.on_main_window_close)
        self.title(f"ADT flutter tools - {current_project_name}")
        self.geometry("800x750")

        self.config_manager = config_manager
        self.current_project_name = current_project_name
        
        self.is_running = False
        self.output_queue = queue.Queue()

        self._switch_to_project(current_project_name)

        self._is_loading_preset = False # Vlajka, která brání ukládání během načítání

        # --- ZMĚNA: Oddělené proměnné ---
        self.build_vars = {} 
        self.preset_selector = None
        self.flavor_selector = None
        self.env_selector = None

        self.bump_strategy_map = {} # např. {"Povýšit major (2.0.0+6)": "major"}
        self.bump_dropdown = None # Reference na combobox
        
        # Samostatná proměnná pro NBSP, načtená z configu
        nbsp_settings = self.config_manager.get_project_nbsp_settings(current_project_name)
        self.translations_path = tk.StringVar(
            value=nbsp_settings.get(KEY_TRANSLATIONS_PATH, "assets/translations")
        )
        # Sledování změn pro NBSP
        self.translations_path.trace_add("write", self._save_nbsp_settings)
        # --- KONEC ZMĚNY ---

        self._create_widgets()
        self._process_queue()
        
        # Načteme UI do stavu podle configu (až po vytvoření widgetů)
        self._load_last_preset()

        self._update_bump_dropdown_options()

    # ... (metody _switch_to_project, _ensure_project_config_exists, _create_widgets zůstávají stejné) ...
    def _switch_to_project(self, project_name):
        self.current_project_name = project_name
        self.config_manager.set_last_project(project_name)
        project_path = self.config_manager.get_project_path(project_name)
        
        if project_path and os.path.isdir(project_path):
            os.chdir(project_path)
            self.title(f"ADT flutter tools - {project_name}")
            print(f"--- Přepnuto do adresáře: {os.getcwd()} ---")
            self._ensure_project_config_exists()
        else:
            messagebox.showerror("Chyba cesty", f"Adresář pro projekt '{project_name}' nebyl nalezen:\n{project_path}")
            os.chdir(self.master.original_cwd) 
            self.title(f"ADT flutter tools - CHYBA PROJEKTU")

    def _ensure_project_config_exists(self):
        config_filename = ADT_PROJECT_CONFIG_FILENAME
        if not os.path.exists(config_filename):
            try:
                with open(config_filename, 'w', encoding='utf-8') as f:
                    f.write(ADT_TOOLS_ENV_EXAMPLE)
                print(f"--- Vytvořen nový konfigurační soubor: {config_filename} ---")
            except Exception as e:
                print(f"!!! Chyba při vytváření {config_filename}: {e} !!!")
                messagebox.showerror("Chyba souboru", f"Nepodařilo se vytvořit soubor {config_filename}:\n{e}")

    def _create_widgets(self):
        top_frame = ttk.Frame(self, padding=(10, 10, 10, 0))
        top_frame.pack(fill='x')
        ttk.Label(top_frame, text="Aktuální projekt:").pack(side='left')
        self.project_selector = ttk.Combobox(top_frame, state='readonly')
        self.project_selector.pack(side='left', expand=True, fill='x', padx=5)
        self.project_selector.bind("<<ComboboxSelected>>", self.on_project_switch)
        command = lambda: self.master.open_add_project_dialog(parent_window=self)
        ttk.Button(top_frame, text="+", width=3, command=command).pack(side='left')
        self.update_project_selector()
        
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(expand=True, fill="both", padx=10, pady=10)
        
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        
        # Vytvoříme build_vars PŘED vytvořením záložek
        self._initialize_build_vars()
        
        self.notebook.add(self._create_build_tab(), text="Build") 
        self.notebook.add(self._create_json_tab(), text="JsonSerializable")
        self.notebook.add(self._create_nbsp_tab(), text="Nezalomitelná mezera")

        self._define_console_tags(self.build_console)
        self._define_console_tags(self.json_console)
        self._define_console_tags(self.nbsp_console)

        try:
            last_tab_index = self.config_manager.get_last_tab()
            if 0 <= last_tab_index < len(self.notebook.tabs()):
                self.notebook.select(last_tab_index)
            else: self.notebook.select(0)
        except tk.TclError: pass 

    def _create_nbsp_tab(self):
        frame = ttk.Frame(self.notebook, padding="10")
        frame.grid_rowconfigure(1, weight=1, minsize=150)
        frame.grid_columnconfigure(0, weight=1)
        path_frame = ttk.Frame(frame)
        path_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        path_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(path_frame, text="Cesta k překladům:").grid(row=0, column=0, padx=(0, 5))
        
        # --- ZMĚNA: Používá globální 'self.translations_path' ---
        self.path_entry = ttk.Entry(path_frame, textvariable=self.translations_path, state="readonly")
        
        self.path_entry.grid(row=0, column=1, sticky="ew")
        browse_button = ttk.Button(path_frame, text="Procházet...", command=self._browse_directory)
        browse_button.grid(row=0, column=2, padx=(5, 0))
        self.nbsp_console = scrolledtext.ScrolledText(frame, wrap=tk.WORD, height=10, state="disabled")
        self.nbsp_console.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        self.nbsp_run_button = ttk.Button(frame, text="Spustit", command=self._run_nbsp_script)
        self.nbsp_run_button.grid(row=2, column=0)
        return frame
        
    def _create_json_tab(self):
        # ... (metoda zůstává stejná) ...
        frame = ttk.Frame(self.notebook, padding="10")
        frame.grid_rowconfigure(0, weight=1, minsize=150)
        frame.grid_columnconfigure(0, weight=1)
        self.json_console = scrolledtext.ScrolledText(frame, wrap=tk.WORD, height=10, state="disabled")
        self.json_console.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        self.json_run_button = ttk.Button(frame, text="Spustit", command=self._run_json_script)
        self.json_run_button.grid(row=1, column=0)
        return frame

    def _initialize_build_vars(self):
        """Inicializuje všechny Tkinter proměnné POUZE pro záložku Build."""
        self.build_vars = {
            KEY_PRESET: tk.StringVar(value=PRESET_MANUAL),
            KEY_BUILD_TYPE: tk.StringVar(value="apk"),
            KEY_BUILD_MODE: tk.StringVar(value="release"),
            KEY_FLAVOR: tk.StringVar(),
            KEY_ENV: tk.StringVar(),
            KEY_BUMP_STRATEGY: tk.StringVar(value=BUMP_PATCH),
            KEY_GIT_PUSH: tk.BooleanVar(value=True),
            KEY_DISABLE_OBFUSCATION: tk.BooleanVar(value=False),
            KEY_UPLOAD_SYMBOLS: tk.BooleanVar(value=True),
            KEY_INSTALL_COCOAPODS: tk.BooleanVar(value=True),
            KEY_CHECK_SQLITE_WEB: tk.BooleanVar(value=False),
        }
        
        # Propojení na ukládání při každé změně
        for key, var in self.build_vars.items():
            # Změna samotného presetu nemá spouštět ukládání!
            if key == KEY_PRESET:
                continue
            
            var.trace_add("write", self._save_current_build_settings)

    def _create_checkbox(self, parent, text, var_key, **pack_kwargs):
        """
        Vytvoří Checkbutton, naváže ho na proměnnou a command, a zabalí ho.
        Vrací vytvořený widget (pro případnou další manipulaci).
        """
        check = ttk.Checkbutton(
            parent, 
            text=text, 
            variable=self.build_vars[var_key],
            command=self._save_current_build_settings
        )
        
        # Výchozí parametry pro pack, pokud nejsou přepsány v pack_kwargs
        pack_args = {"anchor": "w", "pady": 2}
        pack_args.update(pack_kwargs)
        
        check.pack(**pack_args)
        return check
        
    def _create_build_tab(self):
        frame = ttk.Frame(self.notebook, padding="10")
        frame.grid_columnconfigure(1, weight=1)
        
        # ... (preset, separator, build type, build mode, flavor, env) ...
        # (Řádky 0-5 zůstávají stejné)
        ttk.Label(frame, text="Rychlá volba:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.preset_selector = ttk.Combobox(frame, textvariable=self.build_vars[KEY_PRESET], state="readonly")
        self.preset_selector.grid(row=0, column=1, sticky="ew", padx=5, pady=5)
        self.preset_selector.bind("<<ComboboxSelected>>", self._on_preset_selected)
        preset_btn_frame = ttk.Frame(frame)
        preset_btn_frame.grid(row=0, column=2, sticky="w")
        ttk.Button(preset_btn_frame, text="+", width=3, command=self._add_preset).pack(side="left", padx=(0, 5))
        ttk.Button(preset_btn_frame, text="-", width=3, command=self._delete_preset).pack(side="left")
        ttk.Separator(frame, orient="horizontal").grid(row=1, column=0, columnspan=3, sticky="ew", pady=10)
        ttk.Label(frame, text="Typ buildu:").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        build_type_combo = ttk.Combobox(
            frame, textvariable=self.build_vars[KEY_BUILD_TYPE],
            values=["apk", "appbundle", "ipa", "web", "macos", "linux", "windows"], state="readonly"
        )
        build_type_combo.grid(row=2, column=1, sticky="ew", padx=5, pady=2)
        ttk.Label(frame, text="Mód buildu:").grid(row=3, column=0, sticky="w", padx=5, pady=2)
        build_mode_combo = ttk.Combobox(
            frame, textvariable=self.build_vars[KEY_BUILD_MODE],
            values=["release", "profile", "debug"], state="readonly"
        )
        build_mode_combo.grid(row=3, column=1, sticky="ew", padx=5, pady=2)
        self.flavor_selector = self._create_dynamic_list_row(frame, 4, "Flavor:", "flavors", self.build_vars[KEY_FLAVOR])
        self.env_selector = self._create_dynamic_list_row(frame, 5, "Env:", "envs", self.build_vars[KEY_ENV])

        # --- ZMĚNA ROZLOŽENÍ ZDE (ŘÁDEK 6) ---
        # Frame pro Verzi a Checkboxy
        tasks_frame = ttk.Frame(frame)
        tasks_frame.grid(row=6, column=0, columnspan=3, sticky="ew", pady=5)
        tasks_frame.grid_columnconfigure(1, weight=1) # Necháme dropdown roztahovat

        # Řádek 0 (uvnitř tasks_frame): Verze
        ttk.Label(tasks_frame, text="Verze aplikace:").grid(row=0, column=0, sticky="nw", padx=5)
        self.bump_dropdown = ttk.Combobox(tasks_frame, state="readonly", width=30)
        self.bump_dropdown.grid(row=0, column=1, sticky="ew")
        self.bump_dropdown.bind("<<ComboboxSelected>>", self._on_bump_strategy_selected)
        
        checkbox_subframe = ttk.Frame(tasks_frame)
        checkbox_subframe.grid(row=1, column=0, columnspan=2, sticky="w", pady=(5,0), padx=5)

        self._create_checkbox(checkbox_subframe, "Nahrát na Git (Push)", KEY_GIT_PUSH)
        self._create_checkbox(checkbox_subframe, "Instalovat Cocoapods (pro iOS)", KEY_INSTALL_COCOAPODS)

        # ... (zbytek: obfuscate_frame, web_frame, konzole, tlačítko) ...
        # Všechny ostatní řádky se posunuly o 1 dolů
        obfuscate_frame = ttk.LabelFrame(frame, text="Obfuskace & Symboly", padding=5)
        obfuscate_frame.grid(row=7, column=0, columnspan=3, sticky="ew", padx=5, pady=5)
        
        self.obfuscate_check = self._create_checkbox(obfuscate_frame, "Vypnout obfuskaci", KEY_DISABLE_OBFUSCATION)
        self.obfuscate_check.pack(anchor="w")

        self.symbols_check = self._create_checkbox(
            obfuscate_frame, 
            "Nahrát symboly na Firebase", 
            KEY_UPLOAD_SYMBOLS, 
            padx=(20, 0)
        )
        
        self.web_frame = ttk.LabelFrame(frame, text="Web", padding=5)
        self.web_frame.grid(row=8, column=0, columnspan=3, sticky="ew", padx=5, pady=5)
        self.web_check = self._create_checkbox(
            self.web_frame, 
            "Zkontrolovat sqlite3.wasm & sqlite_sw.js", 
            KEY_CHECK_SQLITE_WEB
        )
        
        frame.grid_rowconfigure(9, weight=1, minsize=150)
        self.build_console = scrolledtext.ScrolledText(frame, wrap=tk.WORD, state="disabled")
        self.build_console.grid(row=9, column=0, columnspan=3, sticky="nsew", pady=(5, 10))
        
        self.build_run_button = ttk.Button(frame, text="Spustit build", command=self._run_build_script)
        self.build_run_button.grid(row=10, column=0, columnspan=3)

        # Navázání logiky (beze změny)
        self.build_vars[KEY_BUILD_TYPE].trace_add("write", self._update_build_ui_state)
        self.build_vars[KEY_DISABLE_OBFUSCATION].trace_add("write", self._update_build_ui_state)
        self._update_build_ui_state()
        self.build_vars[KEY_BUILD_TYPE].trace_add("write", lambda *args: self._update_build_ui_state())
        self.build_vars[KEY_DISABLE_OBFUSCATION].trace_add("write", lambda *args: self._update_build_ui_state())
        
        return frame
    
    def _update_bump_dropdown_options(self):
        """Načte aktuální verzi a dynamicky naplní dropdown pro povýšení verze."""
        if not self.bump_dropdown: # Pojistka, pokud se volá příliš brzy
            return
            
        # 1. Načteme aktuální verzi
        # Použijeme "falešný" logger, který jen sbírá chyby
        class VersionLogger:
            def __init__(self): self.error = None
            def info(self,t): pass
            def header(self,t): pass
            def success(self,t): pass
            def error(self,t): self.error = t
            def warn(self,t): pass
            def raw(self,t): pass
        
        v_logger = VersionLogger()
        _, v_name, b_num = get_version_from_pubspec(v_logger, log=False)
        
        if not v_name:
            self.bump_dropdown['values'] = ["Chyba čtení pubspec.yaml"]
            self.bump_dropdown.set("Chyba čtení pubspec.yaml")
            if v_logger.error:
                messagebox.showerror("Chyba verze", v_logger.error, parent=self)
            return
            
        # 2. Vypočítáme všechny možnosti
        strategies = {
            BUMP_NONE: "Nepovyšovat",
            BUMP_PATCH: "Povýšit patch",
            BUMP_BUILD: "Povýšit pouze build",
            BUMP_MINOR: "Povýšit minor",
            BUMP_MAJOR: "Povýšit major"
        }
        
        self.bump_strategy_map = {} # Mapování: "Popisek (1.2.4+6)" -> "patch"
        new_values = []
        
        for key, label in strategies.items():
            new_v, new_b = calculate_bump(v_name, b_num, key)
            full_string = f"{label}  ({new_v}+{new_b})"
            self.bump_strategy_map[full_string] = key
            new_values.append(full_string)

        # 3. Aktualizujeme dropdown
        self.bump_dropdown['values'] = new_values
        
        # 4. Nastavíme aktuálně vybranou hodnotu
        current_strategy_key = self.build_vars[KEY_BUMP_STRATEGY].get()
        current_value_string = None
        for k, v in self.bump_strategy_map.items():
            if v == current_strategy_key:
                current_value_string = k
                break
        
        if current_value_string:
            self.bump_dropdown.set(current_value_string)
        else:
            self.bump_dropdown.set(new_values[0]) # Fallback na "Nepovyšovat"
    
    def _on_bump_strategy_selected(self, event=None):
        """Zavolá se při výběru z dropdownu verzí."""
        selected_string = self.bump_dropdown.get()
        strategy_key = self.bump_strategy_map.get(selected_string, BUMP_NONE)
        
        # Uložíme klíč ("patch", "major", atd.) do naší proměnné
        # Tím se automaticky spustí _save_current_build_settings
        self.build_vars[KEY_BUMP_STRATEGY].set(strategy_key)

    # ... (metody _create_dynamic_list_row, _update_dynamic_list, _add_to_list_dialog, 
    # ... _remove_from_list, _update_build_ui_state zůstávají stejné) ...
    def _create_dynamic_list_row(self, parent, row, label, list_name, var):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=5, pady=2)
        
        combobox = ttk.Combobox(parent, textvariable=var, state="readonly")
        combobox.grid(row=row, column=1, sticky="ew", padx=5, pady=2)

        combobox.bind("<<ComboboxSelected>>", self._save_current_build_settings)
        
        btn_frame = ttk.Frame(parent)
        btn_frame.grid(row=row, column=2, sticky="w")
        
        ttk.Button(btn_frame, text="+", width=3, command=lambda: self._add_to_list_dialog(list_name, combobox)).pack(side="left", padx=(0, 5))
        ttk.Button(btn_frame, text="-", width=3, command=lambda: self._remove_from_list(list_name, combobox)).pack(side="left")
        
        self._update_dynamic_list(combobox, list_name)
        
        return combobox

    def _update_dynamic_list(self, combobox, list_name):
        items = self.config_manager.get_project_list(self.current_project_name, list_name)
        combobox['values'] = [""] + items
    
    def _add_to_list_dialog(self, list_name, combobox):
        new_item = simpledialog.askstring(f"Přidat {list_name}", f"Zadejte název nového {list_name}:", parent=self)
        if new_item and new_item.strip():
            items = self.config_manager.get_project_list(self.current_project_name, list_name)
            if new_item not in items:
                items.append(new_item)
                items.sort()
                self.config_manager.save_project_list(self.current_project_name, list_name, items)
                self._update_dynamic_list(combobox, list_name)
                combobox.set(new_item)

    def _remove_from_list(self, list_name, combobox):
        selected_item = combobox.get()
        if not selected_item:
            messagebox.showwarning("Chyba", "Není vybrána žádná položka ke smazání.", parent=self)
            return
        if messagebox.askyesno("Opravdu smazat?", f"Opravdu chcete smazat '{selected_item}' ze seznamu tohoto projektu?", parent=self):
            items = self.config_manager.get_project_list(self.current_project_name, list_name)
            if selected_item in items:
                items.remove(selected_item)
                self.config_manager.save_project_list(self.current_project_name, list_name, items)
                self._update_dynamic_list(combobox, list_name)
                combobox.set("")

    def _update_build_ui_state(self, *args):
        try:
            if self.build_vars[KEY_DISABLE_OBFUSCATION].get():
                self.symbols_check.config(state="disabled")
                self.build_vars[KEY_UPLOAD_SYMBOLS].set(False)
            else:
                self.symbols_check.config(state="normal")
            if self.build_vars[KEY_BUILD_TYPE].get() == "web":
                self.web_frame.grid() 
            else:
                self.web_frame.grid_remove() 
                self.build_vars[KEY_CHECK_SQLITE_WEB].set(False)
        except (AttributeError, tk.TclError):
            pass 
            
    # --- METODY PRO PRESETY (upravené) ---
    
    def _gather_build_settings(self):
        """Shromáždí všechna nastavení POUZE z build_vars do slovníku."""
        settings = {}
        for key, var in self.build_vars.items():
            if key == KEY_PRESET: continue 
            settings[key] = var.get()
        return settings

    def _load_build_settings(self, settings):
        """Nastaví všechny prvky UI (POUZE build_vars) podle slovníku nastavení."""
        if not settings:
            settings = {}
        
        # Načteme výchozí hodnoty z presetu PRESET_MANUAL, pokud by klíč chyběl
        default_settings = self.config_manager.get_project_build_presets(self.current_project_name).get(PRESET_MANUAL, {})
            
        for key, var in self.build_vars.items():
            if key == KEY_PRESET: continue
            
            # 1. Vem hodnotu z načítaného presetu
            # 2. Pokud tam není, vem ji z PRESET_MANUAL (jako fallback)
            # 3. Pokud ani tam, vem aktuální hodnotu (jako poslední záchrana)
            fallback_value = default_settings.get(key, var.get())
            var.set(settings.get(key, fallback_value))

    def _save_current_build_settings(self, *args):
        """Uloží aktuální stav UI (POUZE build_vars) do aktivního presetu."""

        if self._is_loading_preset:
            return
        
        if not self.preset_selector: return 
        
        current_preset = self.build_vars[KEY_PRESET].get()
        current_settings = self._gather_build_settings()
        
        self.config_manager.save_project_build_preset(
            self.current_project_name, 
            current_preset, 
            current_settings
        )

    def _load_last_preset(self):
        """Načte poslední použitý build preset pro tento projekt."""
        preset_name = self.config_manager.get_last_build_preset_name(self.current_project_name)
        all_presets = self.config_manager.get_project_build_presets(self.current_project_name)
        
        if preset_name not in all_presets:
            preset_name = PRESET_MANUAL
            
        self.build_vars[KEY_PRESET].set(preset_name)
        self._on_preset_selected()

    def _on_preset_selected(self, *args):
        """Načte nastavení z vybraného build presetu."""
        preset_name = self.build_vars[KEY_PRESET].get()
        
        all_presets = self.config_manager.get_project_build_presets(self.current_project_name)
        settings = all_presets.get(preset_name, {})
        
        self._is_loading_preset = True
        self._load_build_settings(settings)
        self._is_loading_preset = False
        
        self.config_manager.save_last_build_preset_name(self.current_project_name, preset_name)

    def _update_preset_list(self):
        """Aktualizuje seznam v dropdownu presetů."""
        presets = list(self.config_manager.get_project_build_presets(self.current_project_name).keys())
        self.preset_selector['values'] = presets
        
    def _add_preset(self):
        """Uloží aktuální nastavení jako nový preset."""
        preset_name = simpledialog.askstring("Nový preset", "Zadejte název nového presetu:", parent=self)
        if not preset_name or preset_name == PRESET_MANUAL:
            return
            
        current_settings = self._gather_build_settings()
        self.config_manager.save_project_build_preset(
            self.current_project_name,
            preset_name, 
            current_settings
        )
        
        self._update_preset_list()
        self.build_vars[KEY_PRESET].set(preset_name)

    def _delete_preset(self):
        """Smaže vybraný preset."""
        preset_name = self.build_vars[KEY_PRESET].get()
        if preset_name == PRESET_MANUAL:
            messagebox.showwarning("Chyba", "Nelze smazat základní preset 'Ručně'.", parent=self)
            return
        
        if messagebox.askyesno("Opravdu smazat?", f"Opravdu chcete smazat preset '{preset_name}'?", parent=self):
            self.config_manager.delete_project_build_preset(self.current_project_name, preset_name)
            self._update_preset_list()
            self.build_vars[KEY_PRESET].set(PRESET_MANUAL) 
            self._on_preset_selected()

    # --- NOVÁ METODA PRO UKLÁDÁNÍ NBSP ---
    def _save_nbsp_settings(self, *args):
        """Uloží aktuální stav UI záložky NBSP."""
        settings = {
            "translations_path": self.translations_path.get()
        }
        self.config_manager.save_project_nbsp_settings(self.current_project_name, settings)

    # --- Metody pro spouštění skriptů (zjednodušené) ---

    def _run_nbsp_script(self):
        """Spustí skript pro nezalomitelné mezery."""
        # Ukládání se děje automaticky přes trace
        path = self.translations_path.get()
        self._run_script_in_thread(lambda cb: run_add_nbsp_logic(path, cb), self.nbsp_console)

    def _run_json_script(self):
        """Spustí skript pro JsonSerializable."""
        self._run_script_in_thread(run_json_serializable_logic, self.json_console)

    def _run_build_script(self):
        """Spustí build s aktuálním nastavením UI."""
        # Ukládání se děje automaticky přes trace
        params = self._gather_build_settings()
        self._run_script_in_thread(run_flutter_build_logic, self.build_console, params)

    # ... (metody on_project_switch, _on_tab_changed, update_project_selector, _set_ui_state,
    # ... _browse_directory, _clear_console, _run_script_in_thread, _process_queue
    # ...  zůstávají beze změny) ...
    def on_project_switch(self, event=None):
        new_project = self.project_selector.get()
        if new_project and new_project != self.current_project_name:
            self.master.show_main_app(new_project)

    def _on_tab_changed(self, event):
        try:
            index = self.notebook.index(self.notebook.select())
            self.config_manager.set_last_tab(index)
        except tk.TclError:
            pass 

    def update_project_selector(self):
        projects = list(self.config_manager.get_projects().keys())
        self.project_selector['values'] = projects
        self.project_selector.set(self.current_project_name)

    def _set_ui_state(self, is_running):
        self.is_running = is_running
        state = "disabled" if is_running else "normal"
        self.nbsp_run_button.config(state=state)
        self.json_run_button.config(state=state)
        self.build_run_button.config(state=state)
        self.project_selector.config(state=state)
        self.preset_selector.config(state=state)

    def _browse_directory(self):
        # --- ZMĚNA: Ukládá do 'self.translations_path' ---
        path = filedialog.askdirectory(initialdir=os.getcwd(), title="Vyberte složku s překlady")
        if path:
            try:
                rel_path = os.path.relpath(path, os.getcwd())
                self.translations_path.set(rel_path)
            except ValueError:
                self.translations_path.set(path)

    def _clear_console(self, console):
        console.config(state="normal")
        console.delete(1.0, tk.END)
        console.config(state="disabled")

    def _define_console_tags(self, console_widget):
        """Definuje barevné 'značky' (tags) pro daný textový widget."""
        console_widget.tag_configure("header", foreground="#00C853", font=("TkDefaultFont", 9, "bold")) # Zelená tučná
        console_widget.tag_configure("success", foreground="#00C853") # Zelená
        console_widget.tag_configure("error", foreground="#D50000", font=("TkDefaultFont", 9, "bold")) # Červená tučná
        console_widget.tag_configure("warn", foreground="#FFAB00") # Oranžová/Žlutá

    def _run_script_in_thread(self, logic_function, console_widget, params=None):
        """Spustí logiku v odděleném vlákně a předá jí UILogger."""
        self._clear_console(console_widget)
        self._set_ui_state(True)
        
        def task():
            # --- ZMĚNA: Vytvoříme logger místo lambdy ---
            logger = UILogger(self.output_queue, console_widget)
            
            try:
                if params:
                    # Předáme logger do logické funkce
                    logic_function(params, logger)
                else:
                    # Předáme logger do logické funkce
                    logic_function(logger)
            except Exception as e:
                # Použijeme logger pro výpis chyby
                logger.error(f"Nastala neočekávaná chyba: {e}\n")
            finally:
                # Signál o konci posíláme stále stejným způsobem
                self.output_queue.put((None, None, None)) # Přidáno None pro tag
        
        threading.Thread(target=task, daemon=True).start()

    def _process_queue(self):
        """Zpracovává zprávy z fronty a aktualizuje UI."""
        try:
            while True:
                line, tag, console_widget = self.output_queue.get_nowait()
                
                if line is None:
                    self._set_ui_state(False)
                else:
                    console_widget.config(state="normal")
                    
                    if tag and tag != "info":
                        console_widget.insert(tk.END, line, tag)
                    else:
                        console_widget.insert(tk.END, line) # Bez tagu
                        
                    console_widget.see(tk.END)
                    console_widget.config(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._process_queue)