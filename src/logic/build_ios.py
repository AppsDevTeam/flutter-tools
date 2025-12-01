# src/logic/build_ios.py
import os
import shutil
import glob
import stat

# Importujeme konstanty a funkce
from .build_common import execute_command
from ..constants import KEY_FLAVOR, KEY_ENV, KEY_DISABLE_OBFUSCATION, KEY_UPLOAD_SYMBOLS, KEY_INSTALL_COCOAPODS

def _resolve_ios_plist_path(flavor, env, env_vars):
    """
    Vyřeší cestu k GoogleService-Info.plist podle priority.
    """
    key = f"IOS_PLIST_{flavor}_{env}"
    if flavor and env and key in env_vars:
        return env_vars[key]
    
    key = f"IOS_PLIST_{flavor}"
    if flavor and key in env_vars:
        return env_vars[key]
        
    return env_vars.get("IOS_PLIST_DEFAULT")

def _find_upload_symbols_script(logger):
    """Najde cestu k binárce upload-symbols (CocoaPods)."""
    # 1. Standardní cesta pro CocoaPods
    pods_path = os.path.join('ios', 'Pods', 'FirebaseCrashlytics', 'upload-symbols')
    if os.path.exists(pods_path):
        return pods_path
    
    # 2. Pokus o nalezení pro SPM (Swift Package Manager) - složitější, protože cesta je dynamická
    # Zde bychom ideálně potřebovali prohledat DerivedData, ale to je bez Xcode env vars těžké.
    # Zkusíme alespoň vyhledat v typických cestách, pokud by to bylo lokálně.
    
    logger.warn("Skript 'upload-symbols' nebyl nalezen v Pods. Pokud používáte SPM, automatické nahrání nemusí fungovat.")
    return None

def _find_latest_xcarchive(logger):
    """Najde nejnovější vytvořený .xcarchive."""
    archive_dir = os.path.join('build', 'ios', 'archive')
    pattern = os.path.join(archive_dir, '*.xcarchive')
    
    candidates = glob.glob(pattern)
    if not candidates:
        return None
    
    # Seřadíme podle času změny (nejnovější nakonec) a vrátíme poslední
    latest = max(candidates, key=os.path.getmtime)
    return latest

def run_ios_tasks_pre_build(logger, params, env_vars):
    """
    Spustí úlohy specifické pro iOS před buildem.
    """
    # --- 1. CocoaPods ---
    if params.get(KEY_INSTALL_COCOAPODS, False):
        logger.header("--- Spouštím CocoaPods úklid a instalaci ---")
        ios_dir = 'ios'
        if not os.path.isdir(ios_dir):
            logger.error(f"Složka '{ios_dir}' neexistuje. Nelze spustit pod install.")
            return False

        commands = [
            (['rm', '-rf', 'Pods'], "Mazání složky Pods"),
            (['pod', 'cache', 'clean', '--all'], "Čištění cache"),
            (['pod', 'deintegrate'], "Pod deintegrate"),
            (['pod', 'setup'], "Pod setup"),
            (['pod', 'install', '--repo-update'], "Pod install")
        ]

        for cmd, title in commands:
            ret_code, _ = execute_command(cmd, logger, title=title, working_dir=ios_dir)
            if cmd[0] == 'pod' and cmd[1] == 'install' and ret_code != 0:
                logger.error("Instalace Cocoapods selhala. Build byl přerušen.")
                return False
    
    # --- 2. GoogleService-Info.plist ---
    flavor = params.get(KEY_FLAVOR)
    env = params.get(KEY_ENV)
    
    plist_src = _resolve_ios_plist_path(flavor, env, env_vars)
    plist_dst = "ios/Runner/GoogleService-Info.plist"
    
    logger.info(f"Hledám konfiguraci pro Plist (flavor={flavor}, env={env})...")
    
    if not plist_src:
        logger.error("Nebyla nalezena žádná cesta k GoogleService-Info.plist v konfiguraci.")
        return False
        
    if not os.path.exists(plist_src):
        logger.error(f"Zdrojový soubor '{plist_src}' neexistuje.")
        return False
        
    try:
        shutil.copy(plist_src, plist_dst)
        logger.success(f"Zkopírováno: '{plist_src}' -> '{plist_dst}'")
    except Exception as e:
        logger.error(f"Chyba při kopírování Plist souboru: {e}")
        return False
    
    return True 

def run_ios_tasks_post_build(logger, params, env_vars, actions_performed):
    """
    Spustí úlohy specifické pro iOS po úspěšném buildu.
    Hlavním úkolem je najít dSYMs v archivu a nahrát je na Firebase.
    """
    
    # Kontrola, zda máme nahrávat symboly
    if params.get(KEY_DISABLE_OBFUSCATION, False) or not params.get(KEY_UPLOAD_SYMBOLS, False):
        return None # Nic neděláme

    logger.header("--- Nahrávám symboly (iOS dSYM) na Firebase ---")

    # 1. Najít skript upload-symbols
    upload_script = _find_upload_symbols_script(logger)
    if not upload_script:
        logger.error("Nahrání symbolů selhalo: Skript 'upload-symbols' nenalezen.")
        return None
    
    # Ujistíme se, že je skript spustitelný
    try:
        st = os.stat(upload_script)
        os.chmod(upload_script, st.st_mode | stat.S_IEXEC)
    except Exception as e:
        logger.warn(f"Nepodařilo se nastavit executable flag pro skript: {e}")

    # 2. Najít nejnovější archiv
    archive_path = _find_latest_xcarchive(logger)
    if not archive_path:
        logger.error("Nahrání symbolů selhalo: Žádný .xcarchive nenalezen v build/ios/archive/.")
        return None
    
    logger.info(f"Nalezen archiv: {archive_path}")

    # 3. Cesty k dSYMs a Plist
    dsyms_dir = os.path.join(archive_path, "dSYMs")
    gsp_path = os.path.join("ios", "Runner", "GoogleService-Info.plist")

    if not os.path.isdir(dsyms_dir):
        logger.error(f"Složka dSYMs nenalezena v archivu: {dsyms_dir}")
        return None
    
    if not os.path.exists(gsp_path):
        logger.error(f"GoogleService-Info.plist nenalezen: {gsp_path}")
        return None

    # 4. Najít všechny .dSYM soubory a nahrát je
    # Ekvivalent bash: find "$DSYMS" -name "*.dSYM" -type d ... | xargs ...
    
    dsym_found = False
    # Projdeme složku dSYMs
    for item_name in os.listdir(dsyms_dir):
        if item_name.endswith(".dSYM"):
            dsym_path = os.path.join(dsyms_dir, item_name)
            if os.path.isdir(dsym_path):
                dsym_found = True
                logger.info(f"Nahrávám: {item_name}...")
                
                cmd = [
                    upload_script,
                    '-gsp', gsp_path,
                    '-p', 'ios',
                    dsym_path
                ]
                
                ret_code, _ = execute_command(cmd, logger, log_stdout=True)
                
                if ret_code != 0:
                    logger.error(f"Chyba při nahrávání {item_name}")
                else:
                    logger.success(f"Nahráno: {item_name}")

    if dsym_found:
        actions_performed["symbols"] = True
        logger.success("Proces nahrávání symbolů dokončen.")
    else:
        logger.warn("V archivu nebyly nalezeny žádné soubory .dSYM.")
            
    return None # iOS nemá přejmenování souboru jako Android, vrací None