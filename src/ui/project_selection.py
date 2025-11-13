# src/ui/project_selection.py
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os

class AddProjectDialog(tk.Toplevel):
    """Dialog pro přidání nového projektu."""
    def __init__(self, parent, config_manager, on_project_saved):
        super().__init__(parent)
        self.transient(parent) 
        self.grab_set() 
        self.title("ADT flutter tools - Přidat projekt") # <-- ZMĚNA NÁZVU
        
        self.config_manager = config_manager
        self.on_project_saved = on_project_saved
        
        self.path_var = tk.StringVar()
        self.name_var = tk.StringVar()

        frame = ttk.Frame(self, padding=10)
        frame.pack(expand=True, fill='both')
        
        ttk.Label(frame, text="Název projektu:").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(frame, textvariable=self.name_var).grid(row=0, column=1, columnspan=2, sticky="ew", pady=2)
        
        ttk.Label(frame, text="Cesta k projektu:").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Entry(frame, textvariable=self.path_var).grid(row=1, column=1, sticky="ew", pady=2)
        ttk.Button(frame, text="...", width=3, command=self.browse_path).grid(row=1, column=2, padx=(5,0))
        
        ttk.Button(frame, text="Uložit projekt", command=self.save_project).grid(row=2, column=0, columnspan=3, pady=10)
        
    def browse_path(self):
        path = filedialog.askdirectory(title="Vyberte kořenový adresář Flutter projektu")
        if path:
            self.path_var.set(path)
            if not self.name_var.get():
                self.name_var.set(os.path.basename(path))
                
    def save_project(self):
        name = self.name_var.get().strip()
        path = self.path_var.get().strip()
        
        if not name or not path:
            messagebox.showwarning("Chyba", "Název i cesta musí být vyplněny.", parent=self)
            return
        
        if name in self.config_manager.get_projects():
            messagebox.showerror("Chyba", f"Projekt s názvem '{name}' již existuje.", parent=self)
            return

        self.config_manager.add_project(name, path)
        self.destroy()
        self.on_project_saved(name)