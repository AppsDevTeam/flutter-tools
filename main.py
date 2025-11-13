# main.py
from src.ui.app import App
import sys

if __name__ == "__main__":
    """Hlavní vstupní bod aplikace."""
    print(f"--- 1. START: Spouštím main.py (Python verze: {sys.version.split()[0]}) ---")
    
    # Jednoduše vytvoříme a spustíme aplikaci
    app = App()
    print("--- 2. Vytvořena instance App() ---")
    
    app.mainloop()
    
    print("--- 3. Aplikace ukončena (po mainloop) ---")