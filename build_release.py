import os
import shutil
import platform
import subprocess
import sys

# --- KONFIGURACE ---
APP_NAME = "ADT Flutter Tools"
MAIN_SCRIPT = "main.py"

# Cesty k ikonám (obě musí existovat v src/ui)
ICON_PNG = os.path.join("src", "ui", "icon.png")
ICON_ICO = os.path.join("src", "ui", "icon.ico")

def clean_build_dirs():
    """Smaže dočasné složky po předchozím buildu."""
    dirs = ['build', 'dist', '__pycache__']
    for d in dirs:
        if os.path.exists(d):
            try:
                shutil.rmtree(d)
            except Exception as e:
                print(f"Varování: Nelze smazat {d}: {e}")
    
    spec_file = f"{APP_NAME}.spec"
    if os.path.exists(spec_file):
        os.remove(spec_file)

def get_icon_path(system):
    """Vrátí cestu ke správné ikoně podle OS."""
    if system == "Windows":
        if os.path.exists(ICON_ICO):
            return ICON_ICO
        else:
            print(f"⚠️ VAROVÁNÍ: Pro Windows chybí '{ICON_ICO}'. Exe bude bez ikony.")
            return None
    else:
        # macOS i Linux zvládnou PNG (PyInstaller na macOS si s tím poradí)
        if os.path.exists(ICON_PNG):
            return ICON_PNG
        else:
            print(f"⚠️ VAROVÁNÍ: Chybí '{ICON_PNG}'.")
            return None

def build():
    system = platform.system()
    print(f"🚀 Spouštím build pro platformu: {system}")
    print("------------------------------------------------")
    print(f"Tento skript vytvoří aplikaci POUZE pro {system}.")
    print("Pro ostatní systémy musíš skript spustit na nich.")
    print("------------------------------------------------\n")

    # 1. Výběr ikony
    icon_path = get_icon_path(system)

    # 2. Základní příkaz
    cmd = [
        "pyinstaller",
        "--noconsole",       # Skrýt černé okno
        "--onefile",         # Jeden exe soubor
        "--name", APP_NAME,
        "--clean",
        MAIN_SCRIPT
    ]

    # Přidání dat (src složka a ikony)
    sep = ";" if system == "Windows" else ":"
    cmd.append(f"--add-data=src{sep}src") 
    
    # Přibalíme ikonu dovnitř aplikace (pro GUI okna)
    if os.path.exists(ICON_PNG):
        cmd.append(f"--add-data={ICON_PNG}{sep}src/ui")

    # 3. Specifika pro OS
    if system == "Windows":
        if icon_path:
            cmd.append(f"--icon={icon_path}")
            
    elif system == "Darwin": # macOS
        # Na macOS chceme .app bundle
        if "--onefile" in cmd:
            cmd.remove("--onefile")
        cmd.append("--windowed")
        
        if icon_path:
            cmd.append(f"--icon={icon_path}")
            
        # Bundle identifier
        cmd.append(f"--osx-bundle-identifier=com.adt.fluttertools")

    elif system == "Linux":
        if icon_path:
            cmd.append(f"--icon={icon_path}")

    # 4. Spuštění
    print(f"Spouštím příkaz:\n{' '.join(cmd)}\n")
    
    try:
        subprocess.check_call(cmd)
        print("\n✅ Build úspěšně dokončen!")
        
        dist_dir = os.path.join(os.getcwd(), 'dist')
        print(f"\nVýstup najdeš ve složce: {dist_dir}")
        
        if system == "Windows":
            print(f" -> {APP_NAME}.exe")
        elif system == "Darwin":
            print(f" -> {APP_NAME}.app")
            print("\n💡 TIP PRO MACOS: Pokud aplikace nejde spustit, použij: xattr -cr dist/*.app")
        else:
            print(f" -> {APP_NAME}")

    except subprocess.CalledProcessError as e:
        print(f"\n❌ Chyba při buildu: {e}")

if __name__ == "__main__":
    clean_build_dirs()
    
    if shutil.which("pyinstaller") is None:
        print("CHYBA: PyInstaller není nainstalován.")
        print("Spusť: pip install pyinstaller")
        sys.exit(1)

    build()