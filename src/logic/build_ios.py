# src/logic/build_ios.py
import os
import shutil
# Importujeme konstanty a funkce
from .build_common import execute_command, resolve_value
from ..constants import KEY_FLAVOR, KEY_ENV, KEY_DISABLE_OBFUSCATION, KEY_UPLOAD_SYMBOLS, KEY_INSTALL_COCOAPODS

def _resolve_ios_plist_path(flavor, env, env_vars):
    """
    Vyřeší cestu k GoogleService-Info.plist podle priority:
    1. IOS_PLIST_flavor_env
    2. IOS_PLIST_flavor
    3. IOS_PLIST_DEFAULT
    """
    # 1. Flavor + Env
    key = f"IOS_PLIST_{flavor}_{env}"
    if flavor and env and key in env_vars:
        return env_vars[key]
    
    # 2. Flavor
    key = f"IOS_PLIST_{flavor}"
    if flavor and key in env_vars:
        return env_vars[key]
        
    # 3. Default
    return env_vars.get("IOS_PLIST_DEFAULT")

def run_ios_tasks_pre_build(logger, params, env_vars):
    """
    Spustí úlohy specifické pro iOS před buildem.
    1. Robustní CocoaPods install (pokud je vybráno).
    2. Kopírování GoogleService-Info.plist.
    """
    
    # --- 1. CocoaPods ---
    if params.get(KEY_INSTALL_COCOAPODS, False):
        logger.header("--- Spouštím CocoaPods úklid a instalaci ---")
        ios_dir = 'ios'
        if not os.path.isdir(ios_dir):
            logger.error(f"Složka '{ios_dir}' neexistuje. Nelze spustit pod install.")
            return False

        # Sekvence příkazů pro čistou instalaci
        commands = [
            (['rm', '-rf', 'Pods'], "Mazání složky Pods"),
            (['pod', 'cache', 'clean', '--all'], "Čištění cache"),
            (['pod', 'deintegrate'], "Pod deintegrate"),
            (['pod', 'setup'], "Pod setup"),
            (['pod', 'install', '--repo-update'], "Pod install")
        ]

        for cmd, title in commands:
            ret_code, _ = execute_command(cmd, logger, title=title, working_dir=ios_dir)
            # Ignorujeme chyby u čištění, ale install musí projít
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
        logger.error("Zkontrolujte adt_tools_config.env a klíče IOS_PLIST_...")
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
    """Spustí úlohy specifické pro iOS po úspěšném buildu (Nahrání symbolů)."""
    
    flavor = params.get(KEY_FLAVOR)
    env = params.get(KEY_ENV)

    if not params.get(KEY_DISABLE_OBFUSCATION, False) and params.get(KEY_UPLOAD_SYMBOLS, False):
        logger.header("--- Nahrávám symboly (iOS) na Firebase ---")
        firebase_app_id = resolve_value("FIREBASE_APP_ID", flavor, env, env_vars)
        
        if firebase_app_id:
            symbols_cmd = [
                'flutterfire', 'crashlytics:symbols:upload',
                f'--app={firebase_app_id}',
                '--os=ios'
            ]
            ret_code, _ = execute_command(symbols_cmd, logger)
            if ret_code == 0:
                logger.success("Symboly úspěšně nahrány.")
                actions_performed["symbols"] = True
            else:
                logger.error("Nahrání symbolů selhalo.")
        else:
            logger.warn("FIREBASE_APP_ID nenalezen v adt_tools_config.env. Nelze nahrát symboly.")
            
    return None