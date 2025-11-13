# src/ui/app.py
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
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

    def on_project_selected_from_list(self, event=None):
        # ... (metoda zůstává stejná) ...
        selected_indices = self.project_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("Chyba", "Musíte vybrat projekt ze seznamu.")
            return
        
        project_name = self.project_listbox.get(selected_indices[0])
        
        self.withdraw()
        self.show_main_app(project_name)

    # --- NOVÁ METODA PRO MAZÁNÍ ---
    def on_delete_project(self):
        """Smaže vybraný projekt po potvrzení."""
        selected_indices = self.project_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("Chyba", "Musíte vybrat projekt pro smazání.")
            return
            
        project_name = self.project_listbox.get(selected_indices[0])
        
        # Potvrzovací dialog
        is_sure = messagebox.askyesno(
            title="Opravdu smazat projekt?",
            message=f"Opravdu chcete smazat projekt '{project_name}' ze seznamu?\n\n(Smaže se pouze záznam, soubory na disku zůstanou.)",
            icon='warning'
        )
        
        if is_sure:
            self.config_manager.delete_project(project_name)
            # Obnovíme seznam v UI
            self.populate_project_list()
            print(f"--- Projekt '{project_name}' smazán ---")

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