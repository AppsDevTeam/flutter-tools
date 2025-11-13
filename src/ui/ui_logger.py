# src/ui/ui_logger.py

class UILogger:
    """
    Třída, která funguje jako 'callback', ale umožňuje logice posílat
    zprávy s různými úrovněmi (tagy), aniž by logika věděla, jak je UI zobrazí.
    """
    def __init__(self, queue, console_widget):
        self.queue = queue
        self.console = console_widget

    def _log(self, text, tag):
        """Interní metoda pro poslání zprávy do fronty."""
        # Ujistíme se, že i prázdné řádky se vypíšou
        if not text:
            text = "\n"
        # Přidáme konec řádku, pokud chybí
        if not text.endswith("\n"):
            text += "\n"
        
        self.queue.put((text, tag, self.console))

    # --- Veřejné metody pro logování ---

    def info(self, text):
        """Běžný text, výchozí barva."""
        self._log(text, "info")

    def header(self, text):
        """Zvýrazněný text (např. zelený, tučný)."""
        self._log(text, "header")
        
    def success(self, text):
        """Text pro úspěch (např. zelený)."""
        self._log(text, "success")

    def error(self, text):
        """Text pro chybu (např. červený)."""
        self._log(text, "error")

    def warn(self, text):
        """Text pro varování (např. žlutý)."""
        self._log(text, "warn")
        
    def raw(self, text):
        """
        Surový výstup z podprocesu. Automaticky detekuje chyby.
        """
        text_lower = text.lower()
        if "error:" in text_lower or "exception:" in text_lower or "failed" in text_lower:
            self._log(text, "error")
        else:
            self._log(text, "info")