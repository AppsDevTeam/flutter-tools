# src/ui/app.py
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os
from ..config_manager import ConfigManager
from .main_window import MainWindow
from .project_selection import AddProjectDialog

class App(tk.Tk):
    # ... (__init__ zůstává stejný) ...
    def __init__(self):
        super().__init__()
        self.title("ADT flutter tools") 
        self.config_manager = ConfigManager()
        self.original_cwd = os.getcwd()

        self.main_window = None

        last_project = self.config_manager.get_last_project()
        
        if last_project and self.config_manager.validate_project(last_project):
            print(f"--- Načítám poslední platný projekt: {last_project} ---")
            self.withdraw()
            self.show_main_app(last_project)
        else:
            print("--- Nenačten platný poslední projekt, zobrazuji výběr ---")
            self.show_project_selection_ui()

    def show_project_selection_ui(self):
        """Nakonfiguruje toto (root) okno jako obrazovku pro výběr projektu."""
        self.title("ADT flutter tools - Výběr projektu")
        self.geometry("400x350") # Lehce zvětšeno pro nové tlačítko
        
        self.eval('tk::PlaceWindow . center')
        
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(expand=True, fill="both")
        
        ttk.Label(main_frame, text="Vyberte existující projekt:").pack(anchor="w")
        
        self.project_listbox = tk.Listbox(main_frame)
        self.project_listbox.pack(expand=True, fill="both", pady=5)
        self.project_listbox.bind("<Double-Button-1>", self.on_project_selected_from_list)
        
        self.populate_project_list()
        
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill="x", pady=5)
        
        ttk.Button(btn_frame, text="Vybrat projekt", command=self.on_project_selected_from_list).pack(side="left", expand=True, fill="x")
        ttk.Button(btn_frame, text="Přidat nový (+)", command=self.open_add_project_dialog).pack(side="left", expand=True, fill="x", padx=(5,0))

        edit_frame = ttk.Frame(main_frame)
        edit_frame.pack(fill="x", pady=(5, 0))
        
        ttk.Button(edit_frame, text="Přejmenovat", command=self.on_rename_project).pack(side="left", expand=True, fill="x")
        ttk.Button(edit_frame, text="Změnit cestu", command=self.on_edit_project_path).pack(side="left", expand=True, fill="x", padx=(5,0))

        # --- NOVÉ TLAČÍTKO PRO MAZÁNÍ ---
        delete_btn_frame = ttk.Frame(main_frame)
        delete_btn_frame.pack(fill="x", pady=(10,0))
        ttk.Button(delete_btn_frame, text="Smazat vybraný projekt", command=self.on_delete_project, style="Warning.TButton").pack(fill="x")
        
        # Styl pro varovné tlačítko (můžeš si přizpůsobit)
        style = ttk.Style(self)
        style.configure("Warning.TButton", foreground="red", background="red")


    def populate_project_list(self):
        # ... (metoda zůstává stejná) ...
        self.project_listbox.delete(0, tk.END)
        projects = self.config_manager.get_projects()
        last_project = self.config_manager.get_last_project()
        
        for i, name in enumerate(projects.keys()):
            self.project_listbox.insert(tk.END, name)
            if name == last_project:
                self.project_listbox.selection_set(i)
                self.project_listbox.activate(i)

    def _get_selected_project_name(self):
        """Získá projekt vybraný v listboxu (pro úvodní obrazovku)."""
        if not hasattr(self, 'project_listbox'): return None
        selected_indices = self.project_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("Chyba", "Musíte vybrat projekt ze seznamu.")
            return None
        return self.project_listbox.get(selected_indices[0])

    def on_project_selected_from_list(self, event=None):
        # ... (metoda zůstává stejná) ...
        selected_indices = self.project_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("Chyba", "Musíte vybrat projekt ze seznamu.")
            return
        
        project_name = self.project_listbox.get(selected_indices[0])
        
        self.withdraw()
        self.show_main_app(project_name)

    def on_rename_project(self, target_name=None):
        """
        Přejmenuje projekt.
        target_name: Pokud je zadáno, přejmenuje tento projekt. Jinak bere z listboxu.
        """
        old_name = target_name or self._get_selected_project_name()
        if not old_name: return

        new_name = simpledialog.askstring("Přejmenovat projekt", f"Zadejte nový název pro '{old_name}':", parent=self)
        
        if new_name and new_name.strip() and new_name != old_name:
            if self.config_manager.rename_project(old_name, new_name.strip()):
                print(f"--- Projekt '{old_name}' přejmenován na '{new_name}' ---")
                
                # Aktualizace UI listboxu (pokud existuje)
                self.populate_project_list()
                
                # Pokud je otevřené hlavní okno s tímto projektem, musíme ho aktualizovat
                if self.main_window and self.main_window.current_project_name == old_name:
                    self.main_window.current_project_name = new_name
                    self.main_window.title(f"ADT flutter tools - {new_name}")
                    self.main_window.update_project_selector()
            else:
                messagebox.showerror("Chyba", f"Nepodařilo se přejmenovat. Název '{new_name}' již možná existuje.")

    def on_edit_project_path(self, target_name=None):
        name = target_name or self._get_selected_project_name()
        if not name: return

        current_path_raw = self.config_manager.get_project_path(name)
        initial_dir = self.original_cwd 

        if current_path_raw:
            abs_path = os.path.abspath(current_path_raw)
            if os.path.isdir(abs_path):
                initial_dir = abs_path
            else:
                parent_dir = os.path.dirname(abs_path)
                if os.path.isdir(parent_dir):
                    initial_dir = parent_dir

        # --- ZDE JE OPRAVA ---
        # Musíme zjistit, které okno je aktuálně viditelné a nastavit ho jako rodiče.
        # Jinak macOS hodí dialog mimo obrazovku.
        current_parent = self
        if self.main_window and self.main_window.winfo_exists() and self.main_window.winfo_viewable():
            current_parent = self.main_window

        new_path = filedialog.askdirectory(
            title=f"Vyberte novou složku pro '{name}'",
            initialdir=initial_dir,
            parent=current_parent # Použijeme viditelného rodiče
        )
        # --- KONEC OPRAVY ---

        if new_path:
            if self.config_manager.update_project_path(name, new_path):
                print(f"--- Cesta pro '{name}' změněna na '{new_path}' ---")
                if self.main_window and self.main_window.current_project_name == name:
                    self.main_window._switch_to_project(name)
            else:
                messagebox.showerror("Chyba", "Nepodařilo se aktualizovat cestu.", parent=current_parent)

    def on_delete_project(self, target_name=None):
        project_name = target_name or self._get_selected_project_name()
        if not project_name: return
        
        is_sure = messagebox.askyesno(
            title="Opravdu smazat projekt?",
            message=f"Opravdu chcete smazat projekt '{project_name}' ze seznamu?\n\n(Smaže se pouze záznam, soubory na disku zůstanou.)",
            icon='warning',
            parent=self
        )
        
        if is_sure:
            self.config_manager.delete_project(project_name)
            print(f"--- Projekt '{project_name}' smazán ---")
            
            # Pokud jsme smazali aktuálně otevřený projekt, musíme zavřít hlavní okno a jít na výběr
            if self.main_window and self.main_window.current_project_name == project_name:
                self.main_window.destroy()
                self.main_window = None
                self.show_project_selection_ui()
            else:
                self.populate_project_list()

    def open_add_project_dialog(self, parent_window=None):
        # ... (metoda zůstává stejná) ...
        if parent_window is None:
            parent_window = self
            
        def on_new_project_saved(project_name):
            self.withdraw() 
            self.show_main_app(project_name) 
        
        AddProjectDialog(parent_window, self.config_manager, on_new_project_saved)

    def show_main_app(self, project_name):
        # ... (metoda zůstává stejná) ...
        if self.main_window:
            self.main_window.destroy()
        
        self.main_window = MainWindow(self, self.config_manager, project_name)
        self.main_window.protocol("WM_DELETE_WINDOW", self.on_main_window_close)

    def on_main_window_close(self):
        # ... (metoda zůstává stejná) ...
        print("--- Zavírám hlavní okno, ukončuji aplikaci. ---")
        self.destroy()