# src/ui/project_config_dialog.py
import tkinter as tk
from tkinter import ttk, messagebox

from ..constants import ADT_PROJECT_CONFIG_FILENAME

# Výsledek dialogu: uložit hodnoty, pokračovat bez nich, nebo zrušit.
RESULT_SAVED = "saved"
RESULT_SKIP = "skip"
RESULT_CANCEL = "cancel"


class ConfigField:
    """Pole nastavení projektu: klíč v adt_tools_config.env, popisek a nápověda, kde hodnotu najít."""

    def __init__(self, key, label, help_text, value="", placeholder=""):
        self.key = key
        self.label = label
        self.help_text = help_text
        self.value = value
        self.placeholder = placeholder


class ProjectConfigDialog(tk.Toplevel):
    """
    Nastavení projektu, které patří do adt_tools_config.env (git, platí pro všechny): pole
    s nápovědou, Uložit. S [skip_label] je i tlačítko pro pokračování bez nastavení (spuštění
    buildu, kterému něco chybí).
    """

    def __init__(self, parent, title, intro, fields, save_label="Uložit", skip_label=None):
        super().__init__(parent)
        self.transient(parent)
        self.title(f"ADT flutter tools - {title}")
        self.resizable(False, False)

        self.fields = fields
        self.result = RESULT_CANCEL
        self.values = {}
        self._vars = {}

        frame = ttk.Frame(self, padding=12)
        frame.pack(expand=True, fill='both')
        frame.grid_columnconfigure(0, weight=1)

        ttk.Label(frame, text=intro, wraplength=460, justify="left").grid(row=0, column=0, sticky="w", pady=(0, 10))

        row = 1
        first_entry = None
        for field in fields:
            ttk.Label(frame, text=f"{field.label} ({field.key})").grid(row=row, column=0, sticky="w")
            var = tk.StringVar(value=field.value)
            self._vars[field.key] = var
            entry = ttk.Entry(frame, textvariable=var, width=60)
            entry.grid(row=row + 1, column=0, sticky="ew", pady=(2, 0))
            first_entry = first_entry or entry
            help_text = field.help_text + (f" Např. {field.placeholder}" if field.placeholder else "")
            ttk.Label(frame, text=help_text, wraplength=460, justify="left", foreground="#666666").grid(
                row=row + 2, column=0, sticky="w", pady=(2, 10)
            )
            row += 3

        ttk.Label(
            frame,
            text=f"Uloží se do {ADT_PROJECT_CONFIG_FILENAME} v projektu (commitne se s buildem, platí pro všechny).",
            wraplength=460, justify="left", foreground="#666666"
        ).grid(row=row, column=0, sticky="w", pady=(0, 10))

        buttons = ttk.Frame(frame)
        buttons.grid(row=row + 1, column=0, sticky="e")
        ttk.Button(buttons, text=save_label, command=self._save).pack(side="right")
        if skip_label:
            ttk.Button(buttons, text=skip_label, command=self._skip).pack(side="right", padx=(0, 5))
        ttk.Button(buttons, text="Zrušit", command=self.destroy).pack(side="right", padx=(0, 5))

        self.bind("<Return>", lambda event: self._save())
        self.bind("<Escape>", lambda event: self.destroy())
        if first_entry:
            first_entry.focus_set()

        self.grab_set()

    @classmethod
    def ask(cls, parent, title, intro, fields, save_label="Uložit", skip_label=None):
        """Modálně: (RESULT_*, {klíč: hodnota}); hodnoty jen u RESULT_SAVED."""
        dialog = cls(parent, title, intro, fields, save_label=save_label, skip_label=skip_label)
        parent.wait_window(dialog)
        return dialog.result, dialog.values

    def _save(self):
        values = {key: var.get().strip() for key, var in self._vars.items()}
        empty = [field.label for field in self.fields if not values[field.key]]
        if empty:
            messagebox.showwarning("Chybí hodnoty", f"Vyplňte: {', '.join(empty)}.", parent=self)
            return

        self.values = values
        self.result = RESULT_SAVED
        self.destroy()

    def _skip(self):
        self.result = RESULT_SKIP
        self.destroy()
